"""Embedded Finder preview update operations."""

from __future__ import annotations

import shutil
from pathlib import Path

from core.errors import PreviewError, wrap_preview_error
from video_preview import VideoPreviewError, update_video_preview


def update_embedded_preview(path: Path) -> None:
    try:
        update_video_preview(path)
    except VideoPreviewError as exc:
        raise wrap_preview_error(exc) from exc


def update_embedded_preview_copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    shutil.copy2(source, destination)
    update_embedded_preview(destination)
    return destination
