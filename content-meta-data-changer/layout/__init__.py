"""File memory layout parsing."""

from pathlib import Path

from layout.base import FileLayout, LayoutParser, LayoutParseError, UnsupportedLayoutError
from layout.jpeg import JpegLayoutParser
from layout.png import PngLayoutParser
from layout.quicktime import QuickTimeLayoutParser

PARSERS: tuple[type[LayoutParser], ...] = (
    QuickTimeLayoutParser,
    JpegLayoutParser,
    PngLayoutParser,
)


def get_layout_parser(path: Path) -> LayoutParser:
    for parser_cls in PARSERS:
        if parser_cls.supports(path):
            return parser_cls()

    extensions = ", ".join(sorted(supported_layout_extensions()))
    raise UnsupportedLayoutError(
        f"Unsupported file type for layout view: {path.suffix or '(no extension)'}. "
        f"Supported: {extensions}"
    )


def parse_file_layout(path: Path) -> FileLayout:
    return get_layout_parser(path).parse(path)


def supported_layout_extensions() -> set[str]:
    extensions: set[str] = set()
    for parser_cls in PARSERS:
        extensions.update(parser_cls.extensions)
    return extensions


__all__ = [
    "FileLayout",
    "LayoutParseError",
    "LayoutParser",
    "UnsupportedLayoutError",
    "parse_file_layout",
    "supported_layout_extensions",
]
