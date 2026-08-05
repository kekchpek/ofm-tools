"""Core inspect tests."""

from __future__ import annotations

from core.inspect import (
    inspect_layout,
    inspect_metadata,
    inspect_preview_jpeg,
    inspect_segment_bytes,
)


def test_inspect_metadata_video6(video6_target):
    result = inspect_metadata(video6_target)
    assert result.filename == video6_target.name
    assert result.media_kind == "video"
    assert "Format:" in result.text


def test_inspect_layout_has_mdat(video6_target):
    layout = inspect_layout(video6_target)
    assert layout.file_size > 0
    assert any(segment.label == "mdat" for segment in layout.segments)


def test_inspect_preview_jpeg_magic(video6_target):
    data = inspect_preview_jpeg(video6_target)
    assert data.startswith(b"\xff\xd8\xff")


def test_inspect_segment_bytes(video6_target):
    layout = inspect_layout(video6_target)
    segment = layout.segments[0]
    result = inspect_segment_bytes(video6_target, segment.offset, limit=64)
    assert result.offset == segment.offset
    assert result.hex
