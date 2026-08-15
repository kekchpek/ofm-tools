"""Upload session and file storage."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.models import StoredFileDTO
from media_types import is_image_path, is_video_path


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    session_id: str
    filename: str
    path: Path
    size: int
    media_kind: str
    created_at: datetime


class StorageError(RuntimeError):
    pass


def upload_root() -> Path:
    root = Path(os.environ.get("UPLOAD_DIR", "data/uploads")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_session() -> str:
    session_id = str(uuid.uuid4())
    session_dir = upload_root() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_id


def session_dir(session_id: str) -> Path:
    directory = upload_root() / session_id
    if not directory.is_dir():
        raise StorageError(f"Unknown session: {session_id}")
    return directory


def save_upload(session_id: str, filename: str, data: bytes) -> StoredFile:
    session_dir(session_id)
    file_id = str(uuid.uuid4())
    safe_name = Path(filename).name or "upload.bin"
    path = session_dir(session_id) / f"{file_id}_{safe_name}"
    path.write_bytes(data)

    if is_video_path(path):
        media_kind = "video"
    elif is_image_path(path):
        media_kind = "image"
    else:
        media_kind = "unknown"

    return StoredFile(
        file_id=file_id,
        session_id=session_id,
        filename=safe_name,
        path=path,
        size=len(data),
        media_kind=media_kind,
        created_at=datetime.now(UTC),
    )


def get_file(file_id: str) -> StoredFile:
    for session_path in upload_root().iterdir():
        if not session_path.is_dir():
            continue
        for candidate in session_path.glob(f"{file_id}_*"):
            if candidate.is_file():
                session_id = session_path.name
                filename = candidate.name.split("_", 1)[1]
                if is_video_path(candidate):
                    media_kind = "video"
                elif is_image_path(candidate):
                    media_kind = "image"
                else:
                    media_kind = "unknown"
                return StoredFile(
                    file_id=file_id,
                    session_id=session_id,
                    filename=filename,
                    path=candidate,
                    size=candidate.stat().st_size,
                    media_kind=media_kind,
                    created_at=datetime.fromtimestamp(candidate.stat().st_mtime, UTC),
                )
    raise StorageError(f"Unknown file: {file_id}")


def save_output_file(session_id: str, filename: str, data: bytes) -> StoredFile:
    return save_upload(session_id, filename, data)


def copy_to_output(session_id: str, source: StoredFile, output_filename: str) -> StoredFile:
    destination = session_dir(session_id) / f"{uuid.uuid4()}_{Path(output_filename).name}"
    shutil.copy2(source.path, destination)
    file_id = destination.name.split("_", 1)[0]
    return StoredFile(
        file_id=file_id,
        session_id=session_id,
        filename=Path(output_filename).name,
        path=destination,
        size=destination.stat().st_size,
        media_kind=source.media_kind,
        created_at=datetime.now(UTC),
    )


def register_existing_file(session_id: str, path: Path, filename: str | None = None) -> StoredFile:
    session_dir(session_id)
    file_id = path.name.split("_", 1)[0] if "_" in path.name else str(uuid.uuid4())
    display_name = filename or (path.name.split("_", 1)[1] if "_" in path.name else path.name)
    if is_video_path(path):
        media_kind = "video"
    elif is_image_path(path):
        media_kind = "image"
    else:
        media_kind = "unknown"
    return StoredFile(
        file_id=file_id,
        session_id=session_id,
        filename=display_name,
        path=path,
        size=path.stat().st_size,
        media_kind=media_kind,
        created_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
    )


def stored_file_to_dto(stored: StoredFile) -> StoredFileDTO:
    return StoredFileDTO(
        file_id=stored.file_id,
        session_id=stored.session_id,
        filename=stored.filename,
        size=stored.size,
        media_kind=stored.media_kind,  # type: ignore[arg-type]
    )


def delete_session(session_id: str) -> None:
    directory = upload_root() / session_id
    if directory.is_dir():
        shutil.rmtree(directory)


def cleanup_expired_sessions(max_age_hours: int) -> int:
    from api.database import delete_upload_sessions

    expired: list[str] = []
    cutoff = datetime.now(UTC).timestamp() - max_age_hours * 3600
    for session_path in upload_root().iterdir():
        if not session_path.is_dir():
            continue
        if session_path.stat().st_mtime < cutoff:
            shutil.rmtree(session_path, ignore_errors=True)
            expired.append(session_path.name)
    delete_upload_sessions(expired)
    return len(expired)
