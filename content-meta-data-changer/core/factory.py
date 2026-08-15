"""OFM Factory: rebuild source media in a donor file's format, wearing its metadata.

One operation combining the two existing primitives:

    payload  ← source content
    format   ← metadata content
    metadata ← metadata content

When the source is already in the donor's format the conversion step is skipped,
so nothing is re-encoded needlessly.
"""

from __future__ import annotations

from pathlib import Path

from core.convert import convert_image_file, convert_video_file
from core.errors import ConversionError, TransferError
from core.transfer import transfer_metadata_files
from media_types import is_image_path, is_video_path


def _media_kind(path: Path) -> str:
    if is_video_path(path):
        return "video"
    if is_image_path(path):
        return "image"
    return "unknown"


def factory_output_name(source: Path, metadata: Path) -> str:
    """Name the result after the source, in the donor's format."""
    return f"{source.stem}_ofm{metadata.suffix.lower()}"


def normalize_output_name(requested: str, metadata: Path, fallback_stem: str) -> str:
    """Force a user-supplied result name to carry the donor's extension.

    The extension decides how the file is actually written, so a name like
    "holiday.png" against a JPEG donor would produce a mislabelled file. Only
    the stem is taken from the request.
    """
    stem = Path(requested).name.strip()
    stem = Path(stem).stem.strip() if stem else ""
    if not stem:
        stem = fallback_stem
    return f"{stem}{metadata.suffix.lower()}"


def build_factory_result(
    source: Path,
    metadata: Path,
    destination: Path,
    *,
    work_dir: Path | None = None,
) -> Path:
    """Write ``destination``: source payload, donor format, donor metadata."""
    source = source.resolve()
    metadata = metadata.resolve()
    destination = destination.resolve()

    source_kind = _media_kind(source)
    metadata_kind = _media_kind(metadata)

    if source_kind == "unknown":
        raise ConversionError(f"Unsupported source content type: {source.suffix or 'no extension'}")
    if metadata_kind == "unknown":
        raise ConversionError(
            f"Unsupported metadata content type: {metadata.suffix or 'no extension'}"
        )
    if source_kind != metadata_kind:
        raise TransferError(
            "Source content and metadata content must be the same media type — "
            f"got {source_kind} source and {metadata_kind} metadata content."
        )

    target_suffix = metadata.suffix.lower()
    work_dir = work_dir or destination.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    converted: Path | None = None
    if source.suffix.lower() != target_suffix:
        converted = work_dir / f"{destination.stem}__converted{target_suffix}"
        target_key = target_suffix.lstrip(".")
        if source_kind == "video":
            convert_video_file(source, converted, target_key)
        else:
            convert_image_file(source, converted, target_key)
        payload = converted
    else:
        payload = source

    try:
        transfer_metadata_files(payload, metadata, destination)
    finally:
        if converted is not None:
            converted.unlink(missing_ok=True)

    return destination
