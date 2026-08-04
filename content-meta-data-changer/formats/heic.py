"""HEIC/HEIF metadata format strategy."""

from pathlib import Path

from formats.base import MetadataFormat
from formats.heif_support import heif_support_available, register_heif_opener
from formats.image_common import format_image_metadata


class HeicFormat(MetadataFormat):
    extensions = frozenset({".heic", ".heif"})

    def format_metadata(self, path: Path) -> str:
        register_heif_opener()
        if not heif_support_available():
            stat = path.stat()
            return "\n".join(
                [
                    f"File: {path.name}",
                    f"Path: {path.resolve()}",
                    "Format: HEIC",
                    f"Size: {stat.st_size:,} bytes",
                    "",
                    "HEIC preview and EXIF require pillow-heif.",
                    "Install it with: pip install pillow-heif",
                ]
            )
        return format_image_metadata(path, format_label="HEIC")
