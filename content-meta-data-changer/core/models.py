"""Pydantic DTOs for API and core layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from layout.base import CATEGORY_LABELS, FileLayout, FileSegment
from layout.edit_safety import EDIT_SAFETY_MARKS, get_edit_safety
from media_types import is_image_path, is_video_path


class EditSafetyDTO(BaseModel):
    level: Literal["safe", "caution", "unsafe"]
    label: str
    reason: str
    mark: str


class SegmentDTO(BaseModel):
    offset: int
    size: int
    end: int
    label: str
    category: Literal["header", "metadata", "payload", "structure", "padding", "unknown"]
    path: list[str]
    path_label: str
    edit_safety: EditSafetyDTO


class LayoutResult(BaseModel):
    file_size: int
    segments: list[SegmentDTO]
    summary: dict[str, int]

    def as_text(self, *, category: str | None = None) -> str:
        from core.inspect import format_layout_text

        return format_layout_text(self, category=category)


class MetadataSection(BaseModel):
    title: str
    lines: list[str]


class MetadataResult(BaseModel):
    filename: str
    format_label: str
    file_size: int
    media_kind: Literal["video", "image", "unknown"]
    sections: list[MetadataSection]
    text: str

    def as_text(self) -> str:
        return self.text


class InspectSummary(BaseModel):
    file_size: int
    segment_count: int
    summary: dict[str, int]


class SegmentBytesResult(BaseModel):
    offset: int
    size: int
    limit: int
    hex: str
    text: str
    truncated: bool


class TextResult(BaseModel):
    text: str


class StoredFileDTO(BaseModel):
    file_id: str
    session_id: str
    filename: str
    size: int
    media_kind: Literal["video", "image", "unknown"]


class SessionDTO(BaseModel):
    session_id: str


class UserDTO(BaseModel):
    id: str
    email: str
    name: str
    picture_url: str | None = None


class AuthConfigDTO(BaseModel):
    enabled: bool
    login_url: str | None = None
    redirect_uri: str | None = None


class JobResult(BaseModel):
    id: str
    type: Literal["transfer", "convert", "update_preview"]
    status: Literal["queued", "running", "succeeded", "failed"]
    error: str | None = None
    output_file_id: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ErrorResponse(BaseModel):
    error: str
    code: str


def segment_to_dto(segment: FileSegment) -> SegmentDTO:
    safety = get_edit_safety(segment)
    return SegmentDTO(
        offset=segment.offset,
        size=segment.size,
        end=segment.end,
        label=segment.label,
        category=segment.category,  # type: ignore[arg-type]
        path=list(segment.path),
        path_label=segment.path_label,
        edit_safety=EditSafetyDTO(
            level=safety.level,  # type: ignore[arg-type]
            label=safety.label,
            reason=safety.reason,
            mark=EDIT_SAFETY_MARKS[safety.level],
        ),
    )


def layout_to_result(layout: FileLayout) -> LayoutResult:
    summary: dict[str, int] = {}
    for segment in layout.segments:
        summary[segment.category] = summary.get(segment.category, 0) + 1
    return LayoutResult(
        file_size=layout.file_size,
        segments=[segment_to_dto(segment) for segment in layout.segments],
        summary=summary,
    )


def parse_metadata_sections(text: str) -> list[MetadataSection]:
    sections: list[MetadataSection] = []
    current_title = "Overview"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if current_lines or current_title != "Overview":
                sections.append(MetadataSection(title=current_title, lines=current_lines))
            current_title = line.removeprefix("--- ").removesuffix(" ---")
            current_lines = []
            continue
        current_lines.append(line)

    sections.append(MetadataSection(title=current_title, lines=current_lines))
    return sections


def metadata_text_to_result(path, text: str) -> MetadataResult:
    resolved = path.resolve()
    format_label = "Unknown"
    file_size = resolved.stat().st_size if resolved.is_file() else 0
    for line in text.splitlines():
        if line.startswith("Format:"):
            format_label = line.split(":", 1)[1].strip()
        elif line.startswith("Size:"):
            size_part = line.split(":", 1)[1].strip().split()[0].replace(",", "")
            try:
                file_size = int(size_part)
            except ValueError:
                pass

    if is_video_path(resolved):
        media_kind = "video"
    elif is_image_path(resolved):
        media_kind = "image"
    else:
        media_kind = "unknown"

    return MetadataResult(
        filename=resolved.name,
        format_label=format_label,
        file_size=file_size,
        media_kind=media_kind,
        sections=parse_metadata_sections(text),
        text=text,
    )


def summary_from_layout(layout: FileLayout) -> InspectSummary:
    result = layout_to_result(layout)
    return InspectSummary(
        file_size=result.file_size,
        segment_count=len(result.segments),
        summary=result.summary,
    )


CATEGORY_LABELS_EXPORT = CATEGORY_LABELS
