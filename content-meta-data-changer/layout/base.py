"""Base types for file memory layout parsing."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


class LayoutParseError(ValueError):
    """Raised when a file layout cannot be parsed."""


class UnsupportedLayoutError(LayoutParseError):
    """Raised when no layout parser supports the given file."""


@dataclass(frozen=True)
class FileSegment:
    offset: int
    size: int
    label: str
    category: str
    path: tuple[str, ...] = field(default_factory=tuple)

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def path_label(self) -> str:
        return " / ".join(self.path)


@dataclass(frozen=True)
class FileLayout:
    file_size: int
    segments: tuple[FileSegment, ...]

    def segment_at(self, offset: int) -> FileSegment | None:
        for segment in self.segments:
            if segment.offset <= offset < segment.end:
                return segment
        return None


CATEGORY_COLORS = {
    "header": "#4a90d9",
    "metadata": "#43a047",
    "payload": "#e53935",
    "structure": "#8e24aa",
    "padding": "#757575",
    "unknown": "#fb8c00",
}

CATEGORY_LABELS = {
    "header": "Header",
    "metadata": "Metadata",
    "payload": "Payload",
    "structure": "Structure",
    "padding": "Padding",
    "unknown": "Unknown",
}


class LayoutParser(ABC):
    extensions: frozenset[str]

    @classmethod
    def supports(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.extensions

    @abstractmethod
    def parse(self, path: Path) -> FileLayout:
        """Parse the file into non-overlapping classified segments."""


def _format_segment_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _format_segment_offset(offset: int) -> str:
    return f"0x{offset:08X}"


def collect_unknown_memory_segments(
    segments: tuple[FileSegment, ...],
) -> list[tuple[int, FileSegment]]:
    return [
        (index, segment)
        for index, segment in enumerate(segments, start=1)
        if segment.category == "unknown"
    ]


def format_unknown_memory_segments(segments: tuple[FileSegment, ...]) -> str:
    unknown_segments = collect_unknown_memory_segments(segments)
    if not unknown_segments:
        return ""

    total = len(segments)
    number_width = len(str(total))
    lines: list[str] = []

    for index, segment in unknown_segments:
        category = CATEGORY_LABELS.get(segment.category, segment.category.title())
        number = f"{index:>{number_width}}."
        lines.append(
            f"{number} {segment.label}  |  {_format_segment_bytes(segment.size)}  |  {category}"
        )
        lines.append(
            f"    {_format_segment_offset(segment.offset)} | {segment.path_label}"
        )

    return "\n".join(lines)
