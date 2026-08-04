"""PNG metadata format strategy."""

from pathlib import Path

from formats.base import MetadataFormat
from formats.image_common import format_image_metadata


class PngFormat(MetadataFormat):
    extensions = frozenset({".png"})

    def format_metadata(self, path: Path) -> str:
        return format_image_metadata(path, format_label="PNG")
