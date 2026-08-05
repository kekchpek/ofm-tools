"""Inspect metadata, layout, previews, and segment bytes."""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

import cv2
from PIL import Image

from core.errors import LayoutError, UnsupportedMediaError, wrap_layout_error
from core.models import (
    CATEGORY_LABELS_EXPORT,
    InspectSummary,
    LayoutResult,
    MetadataResult,
    SegmentBytesResult,
    TextResult,
    layout_to_result,
    metadata_text_to_result,
    summary_from_layout,
)
from formats.heif_support import register_heif_opener
from layout import LayoutParseError, UnsupportedLayoutError, parse_file_layout
from layout.atom_database import format_unknown_atom_keys
from layout.base import CATEGORY_LABELS, format_unknown_memory_segments
from layout.heif import format_payload_metadata_report
from media_types import is_image_path
from metadata import UnsupportedFormatError, format_metadata


def inspect_metadata(path: Path) -> MetadataResult:
    try:
        text = format_metadata(path)
    except UnsupportedFormatError as exc:
        raise UnsupportedMediaError(str(exc)) from exc
    return metadata_text_to_result(path, text)


def inspect_layout(path: Path) -> LayoutResult:
    try:
        layout = parse_file_layout(path)
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        raise wrap_layout_error(exc) from exc
    return layout_to_result(layout)


def inspect_summary(path: Path) -> InspectSummary:
    try:
        layout = parse_file_layout(path)
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        raise wrap_layout_error(exc) from exc
    return summary_from_layout(layout)


def inspect_unknown_headers(path: Path) -> TextResult:
    try:
        parsed = parse_file_layout(path)
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        raise wrap_layout_error(exc) from exc
    text = format_unknown_atom_keys(parsed.segments) or "(none)"
    return TextResult(text=text)


def inspect_unknown_memory(path: Path) -> TextResult:
    try:
        parsed = parse_file_layout(path)
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        raise wrap_layout_error(exc) from exc
    text = format_unknown_memory_segments(parsed.segments) or "(none)"
    return TextResult(text=text)


def inspect_payload_metadata(path: Path) -> TextResult:
    try:
        parsed = parse_file_layout(path)
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        raise wrap_layout_error(exc) from exc
    text = format_payload_metadata_report(path, parsed)
    return TextResult(text=text)


def inspect_segment_bytes(path: Path, offset: int, size: int | None = None, *, limit: int = 512) -> SegmentBytesResult:
    resolved = path.resolve()
    file_size = resolved.stat().st_size
    if offset < 0 or offset >= file_size:
        raise LayoutError(f"Offset {offset} is out of range for file size {file_size}.")

    read_size = size if size is not None else limit
    read_size = max(0, min(read_size, limit))
    truncated = False
    if size is None:
        layout = inspect_layout(path)
        segment = next((item for item in layout.segments if item.offset <= offset < item.end), None)
        if segment is not None:
            read_size = min(segment.size, limit)
        truncated = (segment.size if segment else file_size - offset) > read_size
    else:
        truncated = size > read_size

    with resolved.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(read_size)

    hex_bytes = " ".join(f"{byte:02X}" for byte in data)
    if truncated:
        hex_bytes += " ..."
    text = _format_text_preview(data)
    if truncated:
        text += " ..."

    return SegmentBytesResult(
        offset=offset,
        size=len(data),
        limit=limit,
        hex=hex_bytes,
        text=text,
        truncated=truncated,
    )


def inspect_preview_jpeg(path: Path, *, max_width: int = 1280) -> bytes:
    if is_image_path(path):
        return _encode_image_preview(path, max_width=max_width)
    return _encode_video_first_frame(path, max_width=max_width)


def _encode_image_preview(path: Path, *, max_width: int) -> bytes:
    register_heif_opener()
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        if rgb.width > max_width > 0:
            scale = max_width / rgb.width
            rgb = rgb.resize((max_width, max(1, round(rgb.height * scale))), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()


def _encode_video_first_frame(path: Path, *, max_width: int) -> bytes:
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            raise LayoutError("Could not read the first video frame.")
        height, width = frame.shape[:2]
        if width > max_width > 0:
            scale = max_width / width
            frame = cv2.resize(
                frame,
                (max_width, max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise LayoutError("Could not encode preview frame as JPEG.")
        return encoded.tobytes()
    finally:
        capture.release()


def _format_text_preview(data: bytes) -> str:
    chars: list[str] = []
    for byte in data:
        if 32 <= byte < 127:
            chars.append(chr(byte))
        else:
            chars.append(".")
    text = "".join(chars)
    if len(text) > 800:
        return text[:797] + "..."
    return text


def _format_segment_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def format_layout_text(layout: LayoutResult, *, category: str | None = None) -> str:
    segments = layout.segments
    if category is not None:
        segments = [segment for segment in segments if segment.category == category]
    total = len(segments)
    number_width = len(str(total)) if total else 1
    lines: list[str] = [
        f"File size: {layout.file_size:,} bytes | Segments: {total}",
        "",
    ]
    for index, segment in enumerate(segments, start=1):
        category_label = CATEGORY_LABELS.get(segment.category, segment.category.title())
        number = f"{index:>{number_width}}."
        lines.append(
            f"{number} {segment.label}  |  {_format_segment_size(segment.size)}  |  {category_label}"
        )
        lines.append(f"    0x{segment.offset:08X} | {segment.path_label}")
    return "\n".join(lines)


def format_layout_summary_text(layout: LayoutResult) -> str:
    counts = Counter(segment.category for segment in layout.segments)
    lines = [
        f"File size: {layout.file_size:,} bytes",
        f"Segments: {len(layout.segments)}",
        "",
        "By category:",
    ]
    for category in ("header", "structure", "metadata", "payload", "padding", "unknown"):
        if counts.get(category):
            label = CATEGORY_LABELS.get(category, category.title())
            lines.append(f"  {label}: {counts[category]}")
    return "\n".join(lines)


def inspect_file_report(path: Path) -> str:
    sections: list[str] = [f"=== {path.name} ===", ""]

    try:
        sections.extend(["--- Metadata ---", inspect_metadata(path).as_text(), ""])
    except UnsupportedMediaError as exc:
        sections.extend(["--- Metadata ---", f"Error: {exc}", ""])
    except Exception as exc:
        sections.extend(["--- Metadata ---", f"Error reading metadata: {exc}", ""])

    try:
        layout = inspect_layout(path)
    except LayoutError as exc:
        sections.extend(["--- Layout ---", f"Error: {exc}", ""])
        return "\n".join(sections)

    sections.extend(["--- Layout Summary ---", format_layout_summary_text(layout), ""])
    sections.extend(["--- Unknown Headers ---", inspect_unknown_headers(path).text, ""])
    sections.extend(["--- Unknown Memory ---", inspect_unknown_memory(path).text, ""])
    return "\n".join(sections).rstrip() + "\n"
