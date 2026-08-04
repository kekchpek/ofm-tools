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
