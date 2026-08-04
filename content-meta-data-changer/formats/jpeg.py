"""JPEG metadata format strategy."""

from pathlib import Path

from formats.base import MetadataFormat
from formats.image_common import format_image_metadata


class JpegFormat(MetadataFormat):
    extensions = frozenset({".jpg", ".jpeg"})

    def format_metadata(self, path: Path) -> str:
        return format_image_metadata(path, format_label="JPEG")
