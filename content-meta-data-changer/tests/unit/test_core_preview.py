"""Core preview update tests."""

from __future__ import annotations

import shutil

from core.preview import update_embedded_preview_copy


def test_update_preview_adds_artwork(tmp_media, video6_target):
    destination = tmp_media / "preview_updated.mov"
    update_embedded_preview_copy(video6_target, destination)
    data = destination.read_bytes()
    assert b"com.apple.quicktime.artwork" in data
    assert b"\xff\xd8\xff" in data
