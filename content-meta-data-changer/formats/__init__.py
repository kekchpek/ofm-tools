"""Metadata format strategies."""

from pathlib import Path

from formats.base import MetadataFormat, UnsupportedFormatError
from formats.heic import HeicFormat
from formats.jpeg import JpegFormat
from formats.mov import MovFormat
from formats.mp4 import Mp4Format
from formats.png import PngFormat

FORMATS: tuple[type[MetadataFormat], ...] = (
    Mp4Format,
    MovFormat,
    JpegFormat,
    PngFormat,
    HeicFormat,
)


def get_format(path: Path) -> MetadataFormat:
    for format_cls in FORMATS:
        if format_cls.supports(path):
            return format_cls()

    extensions = ", ".join(sorted(supported_extensions()))
    raise UnsupportedFormatError(
        f"Unsupported file type: {path.suffix or '(no extension)'}. "
        f"Supported: {extensions}"
    )


def format_metadata(path: Path) -> str:
    return get_format(path).format_metadata(path)


def supported_extensions() -> set[str]:
    extensions: set[str] = set()
    for format_cls in FORMATS:
        extensions.update(format_cls.extensions)
    return extensions


__all__ = [
    "FORMATS",
    "MetadataFormat",
    "HeicFormat",
    "JpegFormat",
    "MovFormat",
    "Mp4Format",
    "PngFormat",
    "UnsupportedFormatError",
    "format_metadata",
    "get_format",
    "supported_extensions",
]
