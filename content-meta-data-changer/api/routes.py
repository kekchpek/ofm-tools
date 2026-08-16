"""FastAPI route handlers."""

from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api.auth import (
    Owner,
    assert_file_access,
    assert_session_access,
    auth_config,
    build_google_login_url,
    clear_session_cookie,
    complete_google_login,
    get_client_id_optional,
    get_current_user_optional,
    new_client_id,
    register_session_owner,
    require_owner,
    require_user_or_anonymous,
    safe_return_url,
    set_client_cookie,
    set_session_cookie,
    user_to_dto,
)
from api.database import (
    UPDATABLE_PIECE_FIELDS,
    ContentPieceRecord,
    OfmMemberRecord,
    OfmRecord,
    UserRecord,
    add_member,
    bind_member_user,
    create_content_piece,
    create_ofm,
    delete_auth_session,
    delete_content_piece,
    delete_ofm,
    get_content_piece,
    get_member,
    get_ofm,
    list_content_pieces,
    list_members,
    list_ofms_for,
    member_role,
    ofm_file_ids,
    ofm_ids_referencing_file,
    referenced_file_ids,
    remove_member,
    rename_ofm,
    sessions_for_owner,
    update_content_piece,
)
from api.jobs import (
    create_convert_job,
    create_factory_job,
    create_transfer_job,
    create_update_preview_job,
    get_job,
    job_to_result,
)
from api.permissions import (
    ROLE_EDITOR,
    ROLE_OWNER,
    Action,
    can,
    describe_denial,
)
from api.storage import (
    StorageError,
    create_session,
    default_quota_bytes,
    delete_file_by_id,
    get_file,
    save_upload,
    session_usage_bytes,
    stored_file_to_dto,
)
from core.errors import LayoutError, UnsupportedMediaError
from core.inspect import (
    inspect_layout,
    inspect_metadata,
    inspect_preview_jpeg,
    inspect_segment_bytes,
    inspect_unknown_headers,
    inspect_unknown_memory,
)
from core.models import (
    AuthConfigDTO,
    ContentPieceDTO,
    ErrorResponse,
    JobResult,
    LayoutResult,
    MetadataResult,
    OfmDTO,
    OfmMemberDTO,
    SegmentBytesResult,
    SessionDTO,
    StorageUsageDTO,
    StoredFileDTO,
    TextResult,
    UserDTO,
)

router = APIRouter(prefix="/api/v1")


class TransferJobRequest(BaseModel):
    target_file_id: str
    source_file_id: str
    output_filename: str = Field(min_length=1)


class ConvertJobRequest(BaseModel):
    source_file_id: str
    output_filename: str = Field(min_length=1)
    target: str = Field(min_length=1)


class UpdatePreviewJobRequest(BaseModel):
    source_file_id: str
    output_filename: str = Field(min_length=1)


class FactoryJobRequest(BaseModel):
    source_file_id: str
    metadata_file_id: str
    output_filename: str | None = Field(default=None, min_length=1)
    #: Where the result should be stored. Defaults to the source file's session,
    #: which is wrong when a teammate runs the job on someone else's upload.
    output_session_id: str | None = None


def _max_upload_bytes() -> int:
    return int(os.environ.get("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))


def _storage_http_error(exc: StorageError) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": str(exc), "code": "not_found"})


def _shared_via_ofm(file_id: str, user: UserRecord | None, client_id: str | None) -> bool:
    """True when the file belongs to a piece in an OFM the caller is a member of.

    Uploads live in the uploader's own session, so without this a teammate's
    files would be invisible to everyone else in a shared OFM.
    """
    email = user.email if user is not None else None
    return any(
        member_role(ofm_id, email=email, client_id=client_id) is not None
        for ofm_id in ofm_ids_referencing_file(file_id)
    )


def authorize_file(file_id: str, user: UserRecord | None, client_id: str | None):
    try:
        stored = get_file(file_id)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    try:
        assert_file_access(stored.session_id, user, client_id)
    except HTTPException:
        if not _shared_via_ofm(file_id, user, client_id):
            raise
    return stored


def get_stored_file(
    file_id: str,
    user: UserRecord | None = Depends(get_current_user_optional),
    client_id: str | None = Depends(get_client_id_optional),
):
    return authorize_file(file_id, user, client_id)


def ensure_file_access(file_id: str, user: UserRecord | None, client_id: str | None) -> None:
    authorize_file(file_id, user, client_id)


@router.get("/auth/config", response_model=AuthConfigDTO)
def auth_config_route() -> AuthConfigDTO:
    return auth_config()


@router.get("/auth/me", response_model=UserDTO)
def auth_me(user: UserRecord | None = Depends(get_current_user_optional)) -> UserDTO:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "Not signed in.", "code": "unauthorized"},
        )
    return user_to_dto(user)


@router.get("/auth/google")
def auth_google(request: Request) -> RedirectResponse:
    try:
        login_url = build_google_login_url(safe_return_url(request))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": str(exc), "code": "auth_not_configured"},
        ) from exc
    return RedirectResponse(login_url)


@router.get("/auth/google/callback")
async def auth_google_callback(
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail={"error": "Missing OAuth callback parameters.", "code": "oauth_callback_error"},
        )
    user, session_token, return_url = await complete_google_login(code, state)
    response = RedirectResponse(return_url)
    set_session_cookie(response, session_token)
    return response


@router.post("/auth/logout")
def auth_logout(
    response: Response,
    cmc_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    if cmc_session:
        delete_auth_session(cmc_session)
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def service_root() -> dict[str, object]:
    """Payload for ``GET /``.

    The API mounts everything under /api/v1, so the bare domain used to answer
    with a naked 404 that reads like a broken deploy. Point at the useful URLs
    instead, and report whether sign-in is switched on.
    """
    return {
        "service": "Content Metadata Changer API",
        "status": "ok",
        "auth_enabled": auth_config().enabled,
        "endpoints": {
            "health": "/api/v1/health",
            "auth_config": "/api/v1/auth/config",
            **({"docs": "/docs"} if os.environ.get("ENABLE_API_DOCS", "1") != "0" else {}),
        },
    }


@router.post("/sessions", response_model=SessionDTO, status_code=201)
def create_upload_session(
    response: Response,
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> SessionDTO:
    if user is None:
        # Anonymous callers get a durable cookie so later requests can prove
        # they own the sessions they created.
        if client_id is None:
            client_id = new_client_id()
        set_client_cookie(response, client_id)
    session_id = create_session()
    register_session_owner(session_id, user, client_id)
    return SessionDTO(session_id=session_id)


@router.post("/sessions/{session_id}/files", response_model=StoredFileDTO, status_code=201)
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> StoredFileDTO:
    assert_file_access(session_id, user, client_id)
    data = await file.read()
    if len(data) > _max_upload_bytes():
        raise HTTPException(
            status_code=413,
            detail={"error": "Upload exceeds maximum allowed size.", "code": "payload_too_large"},
        )

    # Saved pieces keep their files indefinitely, so without a per-user ceiling
    # one account could fill the volume for everyone.
    owner_user_id = user.id if user is not None else None
    owner_client_id = None if user is not None else client_id
    quota = default_quota_bytes()
    used = session_usage_bytes(
        sessions_for_owner(user_id=owner_user_id, client_id=owner_client_id)
    )
    if used + len(data) > quota:
        raise HTTPException(
            status_code=413,
            detail={
                "error": (
                    f"Storage quota reached ({used / 1e9:.2f} GB of {quota / 1e9:.2f} GB used). "
                    "Delete a saved content piece to free space."
                ),
                "code": "quota_exceeded",
            },
        )

    filename = file.filename or "upload.bin"
    try:
        stored = save_upload(session_id, filename, data)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    return stored_file_to_dto(stored)


@router.get("/files/{file_id}/metadata", response_model=MetadataResult)
def file_metadata(stored=Depends(get_stored_file)) -> MetadataResult:
    try:
        return inspect_metadata(stored.path)
    except UnsupportedMediaError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "unsupported_format"}) from exc


@router.get("/files/{file_id}/layout", response_model=LayoutResult)
def file_layout(stored=Depends(get_stored_file)) -> LayoutResult:
    try:
        return inspect_layout(stored.path)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "layout_error"}) from exc


@router.get("/files/{file_id}/segments/{offset}", response_model=SegmentBytesResult)
def file_segment_bytes(
    offset: int,
    limit: int = 512,
    stored=Depends(get_stored_file),
) -> SegmentBytesResult:
    try:
        return inspect_segment_bytes(stored.path, offset, limit=limit)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "layout_error"}) from exc


@router.get("/files/{file_id}/preview.jpg")
def file_preview(stored=Depends(get_stored_file)) -> Response:
    try:
        data = inspect_preview_jpeg(stored.path)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "preview_error"}) from exc
    return Response(content=data, media_type="image/jpeg")


@router.get("/files/{file_id}/unknown-headers", response_model=TextResult)
def file_unknown_headers(stored=Depends(get_stored_file)) -> TextResult:
    try:
        return inspect_unknown_headers(stored.path)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "layout_error"}) from exc


@router.get("/files/{file_id}/unknown-memory", response_model=TextResult)
def file_unknown_memory(stored=Depends(get_stored_file)) -> TextResult:
    try:
        return inspect_unknown_memory(stored.path)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "layout_error"}) from exc


@router.get("/files/{file_id}/download")
def download_file(stored=Depends(get_stored_file)) -> StreamingResponse:

    def iterator():
        with stored.path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk

    headers = {"Content-Disposition": f'attachment; filename="{stored.filename}"'}
    return StreamingResponse(iterator(), media_type="application/octet-stream", headers=headers)


@router.post("/jobs/transfer", response_model=JobResult, status_code=202)
def start_transfer_job(
    body: TransferJobRequest,
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> JobResult:
    ensure_file_access(body.target_file_id, user, client_id)
    ensure_file_access(body.source_file_id, user, client_id)
    try:
        record = create_transfer_job(body.target_file_id, body.source_file_id, body.output_filename)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    return job_to_result(record)


@router.post("/jobs/convert", response_model=JobResult, status_code=202)
def start_convert_job(
    body: ConvertJobRequest,
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> JobResult:
    ensure_file_access(body.source_file_id, user, client_id)
    try:
        record = create_convert_job(body.source_file_id, body.output_filename, body.target)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    return job_to_result(record)


@router.post("/jobs/update-preview", response_model=JobResult, status_code=202)
def start_update_preview_job(
    body: UpdatePreviewJobRequest,
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> JobResult:
    ensure_file_access(body.source_file_id, user, client_id)
    try:
        record = create_update_preview_job(body.source_file_id, body.output_filename)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    return job_to_result(record)


@router.post("/jobs/factory", response_model=JobResult, status_code=202)
def start_factory_job(
    body: FactoryJobRequest,
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> JobResult:
    ensure_file_access(body.source_file_id, user, client_id)
    ensure_file_access(body.metadata_file_id, user, client_id)
    if body.output_session_id:
        # Only into a session the caller actually owns.
        assert_session_access(body.output_session_id, user, client_id)
    try:
        record = create_factory_job(
            body.source_file_id,
            body.metadata_file_id,
            body.output_filename,
            body.output_session_id,
        )
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    return job_to_result(record)


@router.get("/jobs/{job_id}", response_model=JobResult)
def job_status(
    job_id: str,
    user: UserRecord | None = Depends(require_user_or_anonymous),
    client_id: str | None = Depends(get_client_id_optional),
) -> JobResult:
    try:
        record = get_job(job_id)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    if record.session_id is not None:
        assert_session_access(record.session_id, user, client_id)
    return job_to_result(record)


# --- OFMs, membership, and their content pieces -----------------------------


class CreateOfmRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RenameOfmRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class InviteMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class CreatePieceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdatePieceRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    output_stem: str | None = Field(default=None, max_length=200)
    source_file_id: str | None = None
    metadata_file_id: str | None = None
    result_file_id: str | None = None
    result_filename: str | None = None
    position: int | None = None
    # Distinguishes "leave unchanged" from "clear this slot", which a plain
    # None cannot express.
    clear: list[str] = Field(default_factory=list)


def _not_found(what: str = "OFM") -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": f"{what} not found.", "code": "not_found"},
    )


def caller_email(user: UserRecord | None) -> str | None:
    return user.email if user is not None else None


def require_role(ofm_id: str, owner: Owner, user: UserRecord | None) -> str:
    """The caller's role, 404ing when they are not a member.

    404 rather than 403 so a non-member cannot probe which OFM ids exist.
    """
    email = caller_email(user)
    role = member_role(ofm_id, email=email, client_id=owner.client_id)
    if role is None:
        raise _not_found()
    if user is not None and email:
        # First access by an invitee: attach their account to the invitation.
        bind_member_user(ofm_id, email, user.id)
    return role


def require_can(ofm_id: str, owner: Owner, user: UserRecord | None, action: Action) -> str:
    role = require_role(ofm_id, owner, user)
    if not can(role, action):
        raise HTTPException(
            status_code=403,
            detail={"error": describe_denial(action), "code": "forbidden"},
        )
    return role


def _ofm_to_dto(record: OfmRecord, role: str) -> OfmDTO:
    pieces = list_content_pieces(record.id)
    return OfmDTO(
        id=record.id,
        name=record.name,
        role=role,
        is_owner=role == ROLE_OWNER,
        piece_count=len(pieces),
        member_count=len(list_members(record.id)),
        created_at=record.created_at,
        updated_at=record.updated_at,
        can_delete=can(role, Action.DELETE_OFM),
    )


def _member_to_dto(record: OfmMemberRecord) -> OfmMemberDTO:
    return OfmMemberDTO(
        id=record.id,
        email=record.email,
        role=record.role,
        accepted=record.user_id is not None,
        created_at=record.created_at,
    )


@router.get("/ofms", response_model=list[OfmDTO])
def list_ofms(
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> list[OfmDTO]:
    email = caller_email(user)
    records = list_ofms_for(email=email, client_id=owner.client_id)
    result: list[OfmDTO] = []
    for record in records:
        role = member_role(record.id, email=email, client_id=owner.client_id)
        if role:
            if user is not None and email:
                # Seeing an OFM is enough to bind the invitation to the account,
                # so it stops showing as a pending invite to the rest of the team.
                bind_member_user(record.id, email, user.id)
            result.append(_ofm_to_dto(record, role))
    return result


@router.post("/ofms", response_model=OfmDTO, status_code=201)
def create_ofm_route(
    body: CreateOfmRequest,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> OfmDTO:
    record = create_ofm(
        name=body.name,
        owner_user_id=owner.user_id,
        owner_client_id=owner.client_id,
        owner_email=caller_email(user),
    )
    return _ofm_to_dto(record, ROLE_OWNER)


@router.get("/ofms/{ofm_id}", response_model=OfmDTO)
def get_ofm_route(
    ofm_id: str,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> OfmDTO:
    role = require_role(ofm_id, owner, user)
    record = get_ofm(ofm_id)
    if record is None:
        raise _not_found()
    return _ofm_to_dto(record, role)


@router.patch("/ofms/{ofm_id}", response_model=OfmDTO)
def rename_ofm_route(
    ofm_id: str,
    body: RenameOfmRequest,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> OfmDTO:
    role = require_can(ofm_id, owner, user, Action.RENAME_OFM)
    record = rename_ofm(ofm_id, body.name)
    if record is None:
        raise _not_found()
    return _ofm_to_dto(record, role)


@router.delete("/ofms/{ofm_id}", status_code=204)
def delete_ofm_route(
    ofm_id: str,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> Response:
    require_can(ofm_id, owner, user, Action.DELETE_OFM)
    # Free every file this OFM alone was keeping alive.
    own_files = ofm_file_ids(ofm_id)
    delete_ofm(ofm_id)
    still_used = referenced_file_ids()
    for file_id in own_files - still_used:
        delete_file_by_id(file_id)
    return Response(status_code=204)


@router.get("/ofms/{ofm_id}/members", response_model=list[OfmMemberDTO])
def list_members_route(
    ofm_id: str,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> list[OfmMemberDTO]:
    require_role(ofm_id, owner, user)
    return [_member_to_dto(record) for record in list_members(ofm_id)]


@router.post("/ofms/{ofm_id}/members", response_model=OfmMemberDTO, status_code=201)
def invite_member_route(
    ofm_id: str,
    body: InviteMemberRequest,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> OfmMemberDTO:
    require_can(ofm_id, owner, user, Action.INVITE_MEMBERS)
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(
            status_code=422,
            detail={"error": "Enter a valid email address.", "code": "invalid_email"},
        )
    record = add_member(ofm_id, email, ROLE_EDITOR, invited_by=owner.user_id)
    return _member_to_dto(record)


@router.delete("/ofms/{ofm_id}/members/{member_id}", status_code=204)
def remove_member_route(
    ofm_id: str,
    member_id: str,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> Response:
    require_can(ofm_id, owner, user, Action.REMOVE_MEMBERS)
    record = get_member(member_id)
    if record is None or record.ofm_id != ofm_id:
        raise _not_found("Member")
    if record.role == ROLE_OWNER:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "The owner cannot be removed from their own OFM.",
                "code": "cannot_remove_owner",
            },
        )
    remove_member(member_id)
    return Response(status_code=204)


def _resolve_stored(file_id: str | None) -> StoredFileDTO | None:
    if not file_id:
        return None
    try:
        return stored_file_to_dto(get_file(file_id))
    except StorageError:
        return None  # pinned file went missing; surface as an empty slot


def _piece_to_dto(record: ContentPieceRecord) -> ContentPieceDTO:
    return ContentPieceDTO(
        id=record.id,
        ofm_id=record.ofm_id,
        name=record.name,
        output_stem=record.output_stem,
        source_file_id=record.source_file_id,
        metadata_file_id=record.metadata_file_id,
        result_file_id=record.result_file_id,
        result_filename=record.result_filename,
        position=record.position,
        created_at=record.created_at,
        updated_at=record.updated_at,
        source_file=_resolve_stored(record.source_file_id),
        metadata_file=_resolve_stored(record.metadata_file_id),
        result_file=_resolve_stored(record.result_file_id),
    )


@router.get("/ofms/{ofm_id}/pieces", response_model=list[ContentPieceDTO])
def list_pieces_route(
    ofm_id: str,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> list[ContentPieceDTO]:
    require_role(ofm_id, owner, user)
    return [_piece_to_dto(record) for record in list_content_pieces(ofm_id)]


@router.post("/ofms/{ofm_id}/pieces", response_model=ContentPieceDTO, status_code=201)
def create_piece_route(
    ofm_id: str,
    body: CreatePieceRequest,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> ContentPieceDTO:
    require_can(ofm_id, owner, user, Action.EDIT_PIECES)
    existing = list_content_pieces(ofm_id)
    record = create_content_piece(ofm_id=ofm_id, name=body.name, position=len(existing))
    return _piece_to_dto(record)


@router.patch("/pieces/{piece_id}", response_model=ContentPieceDTO)
def patch_piece(
    piece_id: str,
    body: UpdatePieceRequest,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
    client_id: str | None = Depends(get_client_id_optional),
) -> ContentPieceDTO:
    existing = get_content_piece(piece_id)
    if existing is None:
        raise _not_found("Content piece")
    require_can(existing.ofm_id, owner, user, Action.EDIT_PIECES)

    changes = body.model_dump(exclude_none=True, exclude={"clear"})
    for field in body.clear:
        if field in UPDATABLE_PIECE_FIELDS:
            changes[field] = None

    # Never let a piece point at a file the caller cannot read.
    for field in ("source_file_id", "metadata_file_id", "result_file_id"):
        file_id = changes.get(field)
        if file_id:
            ensure_file_access(str(file_id), user, client_id)

    record = update_content_piece(piece_id, changes)
    if record is None:
        raise _not_found("Content piece")
    return _piece_to_dto(record)


@router.delete("/pieces/{piece_id}", status_code=204)
def remove_piece(
    piece_id: str,
    owner: Owner = Depends(require_owner),
    user: UserRecord | None = Depends(get_current_user_optional),
) -> Response:
    record = get_content_piece(piece_id)
    if record is None:
        raise _not_found("Content piece")
    require_can(record.ofm_id, owner, user, Action.EDIT_PIECES)
    # Free the storage immediately, but keep files another piece still uses.
    still_used = referenced_file_ids(excluding_piece=piece_id)
    for file_id in record.file_ids():
        if file_id not in still_used:
            delete_file_by_id(file_id)
    delete_content_piece(piece_id)
    return Response(status_code=204)


@router.get("/storage", response_model=StorageUsageDTO)
def storage_usage(owner: Owner = Depends(require_owner)) -> StorageUsageDTO:
    sessions = sessions_for_owner(user_id=owner.user_id, client_id=owner.client_id)
    return StorageUsageDTO(
        used_bytes=session_usage_bytes(sessions),
        quota_bytes=default_quota_bytes(),
    )
