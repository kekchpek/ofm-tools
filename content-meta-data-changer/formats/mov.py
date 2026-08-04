"""MOV metadata format strategy."""

from pathlib import Path

from formats.base import MetadataFormat
from formats.quicktime import format_quicktime_metadata


class MovFormat(MetadataFormat):
    extensions = frozenset({".mov"})

    def format_metadata(self, path: Path) -> str:
        return format_quicktime_metadata(path, format_label="MOV")
