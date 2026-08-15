"""Background job execution."""

from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from api.storage import StorageError, get_file, register_existing_file, session_dir
from core.convert import convert_image_file, convert_video_file
from core.errors import ConversionError, PreviewError, TransferError
from core.models import JobResult
from core.preview import update_embedded_preview
from core.transfer import transfer_metadata_files


class JobType(str, Enum):
    transfer = "transfer"
    convert = "convert"
    update_preview = "update_preview"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


@dataclass
class JobRecord:
    id: str
    type: JobType
    status: JobStatus
    created_at: datetime
    session_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    output_file_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


_jobs: dict[str, JobRecord] = {}
_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("JOB_WORKERS", "2")))


def _now() -> datetime:
    return datetime.now(UTC)


def job_to_result(record: JobRecord) -> JobResult:
    return JobResult(
        id=record.id,
        type=record.type.value,  # type: ignore[arg-type]
        status=record.status.value,  # type: ignore[arg-type]
        error=record.error,
        output_file_id=record.output_file_id,
        created_at=record.created_at.isoformat(),
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
    )


def get_job(job_id: str) -> JobRecord:
    record = _jobs.get(job_id)
    if record is None:
        raise StorageError(f"Unknown job: {job_id}")
    return record


def create_transfer_job(
    target_file_id: str,
    source_file_id: str,
    output_filename: str,
) -> JobRecord:
    job_id = str(uuid.uuid4())
    record = JobRecord(
        id=job_id,
        type=JobType.transfer,
        status=JobStatus.queued,
        created_at=_now(),
        session_id=get_file(target_file_id).session_id,
        params={
            "target_file_id": target_file_id,
            "source_file_id": source_file_id,
            "output_filename": output_filename,
        },
    )
    _jobs[job_id] = record
    _dispatch(record, _run_transfer)
    return record


def create_convert_job(source_file_id: str, output_filename: str, target: str) -> JobRecord:
    job_id = str(uuid.uuid4())
    record = JobRecord(
        id=job_id,
        type=JobType.convert,
        status=JobStatus.queued,
        created_at=_now(),
        session_id=get_file(source_file_id).session_id,
        params={
            "source_file_id": source_file_id,
            "output_filename": output_filename,
            "target": target,
        },
    )
    _jobs[job_id] = record
    _dispatch(record, _run_convert)
    return record


def create_update_preview_job(source_file_id: str, output_filename: str) -> JobRecord:
    job_id = str(uuid.uuid4())
    record = JobRecord(
        id=job_id,
        type=JobType.update_preview,
        status=JobStatus.queued,
        created_at=_now(),
        session_id=get_file(source_file_id).session_id,
        params={
            "source_file_id": source_file_id,
            "output_filename": output_filename,
        },
    )
    _jobs[job_id] = record
    _dispatch(record, _run_update_preview)
    return record


def _dispatch(record: JobRecord, runner) -> None:
    if os.environ.get("JOBS_SYNC") == "1":
        runner(record)
        return
    _executor.submit(runner, record)


def _job_output_path(session_id: str, job_id: str, output_filename: str) -> Path:
    file_id = str(uuid.uuid4())
    safe_name = Path(output_filename).name
    return session_dir(session_id) / f"{file_id}_{safe_name}"


def _run_transfer(record: JobRecord) -> None:
    record.status = JobStatus.running
    record.started_at = _now()
    try:
        target = get_file(record.params["target_file_id"])
        source = get_file(record.params["source_file_id"])
        if target.media_kind != source.media_kind:
            raise TransferError("Target and metadata source must both be videos or both be images.")
        output_path = _job_output_path(target.session_id, record.id, record.params["output_filename"])
        transfer_metadata_files(target.path, source.path, output_path)
        stored = register_existing_file(target.session_id, output_path, record.params["output_filename"])
        record.output_file_id = stored.file_id
        record.status = JobStatus.succeeded
    except Exception as exc:
        record.status = JobStatus.failed
        record.error = str(exc)
    finally:
        record.finished_at = _now()


def _run_convert(record: JobRecord) -> None:
    record.status = JobStatus.running
    record.started_at = _now()
    try:
        source = get_file(record.params["source_file_id"])
        output_path = _job_output_path(source.session_id, record.id, record.params["output_filename"])
        target = record.params["target"]
        if source.media_kind == "video":
            convert_video_file(source.path, output_path, target)
        elif source.media_kind == "image":
            convert_image_file(source.path, output_path, target)
        else:
            raise ConversionError("Unsupported media kind for conversion.")
        stored = register_existing_file(source.session_id, output_path, record.params["output_filename"])
        record.output_file_id = stored.file_id
        record.status = JobStatus.succeeded
    except Exception as exc:
        record.status = JobStatus.failed
        record.error = str(exc)
    finally:
        record.finished_at = _now()


def _run_update_preview(record: JobRecord) -> None:
    record.status = JobStatus.running
    record.started_at = _now()
    try:
        source = get_file(record.params["source_file_id"])
        if source.media_kind != "video":
            raise PreviewError("Preview update is only available for video files.")
        output_path = _job_output_path(source.session_id, record.id, record.params["output_filename"])
        shutil.copy2(source.path, output_path)
        update_embedded_preview(output_path)
        stored = register_existing_file(source.session_id, output_path, record.params["output_filename"])
        record.output_file_id = stored.file_id
        record.status = JobStatus.succeeded
    except Exception as exc:
        record.status = JobStatus.failed
        record.error = str(exc)
    finally:
        record.finished_at = _now()
