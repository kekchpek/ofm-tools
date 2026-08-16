"""Shared media type helpers."""

from __future__ import annotations

from pathlib import Path

VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_convertible_video(path: Path) -> bool:
    return is_video_path(path)


def is_convertible_image(path: Path) -> bool:
    return is_image_path(path)


#: Content types for download responses. iOS decides whether to offer
#: "Save Image" / "Save Video" in the share sheet from this, so
#: application/octet-stream would hide those options.
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
