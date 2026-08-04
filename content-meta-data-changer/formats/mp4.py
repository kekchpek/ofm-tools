"""MP4 metadata format strategy."""

from pathlib import Path

from formats.base import MetadataFormat
from formats.quicktime import format_quicktime_metadata


class Mp4Format(MetadataFormat):
    extensions = frozenset({".mp4", ".m4v"})

    def format_metadata(self, path: Path) -> str:
        return format_quicktime_metadata(path, format_label="MP4")
