"""FastAPI route handlers."""

from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api.auth import (
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
    require_user_or_anonymous,
    safe_return_url,
    set_client_cookie,
    set_session_cookie,
    user_to_dto,
)
from api.database import UserRecord, delete_auth_session
from api.jobs import (
    create_convert_job,
    create_factory_job,
    create_transfer_job,
    create_update_preview_job,
    get_job,
    job_to_result,
)
from api.storage import (
    StorageError,
    create_session,
    get_file,
    save_upload,
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
    ErrorResponse,
    JobResult,
    LayoutResult,
    MetadataResult,
    SegmentBytesResult,
    SessionDTO,
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


def _max_upload_bytes() -> int:
    return int(os.environ.get("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))


def _storage_http_error(exc: StorageError) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": str(exc), "code": "not_found"})


def get_stored_file(
    file_id: str,
    user: UserRecord | None = Depends(get_current_user_optional),
    client_id: str | None = Depends(get_client_id_optional),
):
    try:
        stored = get_file(file_id)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    assert_file_access(stored.session_id, user, client_id)
    return stored


def ensure_file_access(file_id: str, user: UserRecord | None, client_id: str | None) -> None:
    try:
        stored = get_file(file_id)
    except StorageError as exc:
        raise _storage_http_error(exc) from exc
    assert_file_access(stored.session_id, user, client_id)


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
            "docs": "/docs",
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
    try:
        record = create_factory_job(
            body.source_file_id,
            body.metadata_file_id,
            body.output_filename,
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
