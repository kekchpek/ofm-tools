"""Metadata facade for supported file formats."""

from pathlib import Path

from formats import format_metadata, get_format, supported_extensions
from formats.base import UnsupportedFormatError

__all__ = [
    "UnsupportedFormatError",
    "format_metadata",
    "get_format",
    "supported_extensions",
]
