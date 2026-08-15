"""Structural invariants for the byte-range layout parsers.

These build their own fixtures rather than relying on ``OfmContent/``, which is
not checked in — so they run everywhere, including CI.

The invariant that matters for the layout viewer and for edit-safety marks is
that segments describe the file exactly: sorted, non-overlapping, in bounds. A
parser that silently drops or double-counts a byte range puts the wrong safety
verdict on whatever the user is about to edit.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import Image

from core.inspect import inspect_layout, inspect_segment_bytes
from layout import parse_file_layout
from layout.base import CATEGORY_LABELS

VALID_CATEGORIES = set(CATEGORY_LABELS)


def _atom(atom_type: bytes, payload: bytes) -> bytes:
    assert len(atom_type) == 4
    return struct.pack(">I", 8 + len(payload)) + atom_type + payload


@pytest.fixture
def mov_file(tmp_path: Path) -> Path:
    """A minimal but structurally real QuickTime file."""
    ftyp = _atom(b"ftyp", b"qt  " + b"\x00\x00\x02\x00" + b"qt  ")
    title = _atom(b"\xa9nam", _atom(b"data", b"\x00" * 8 + b"Test Title"))
    udta = _atom(b"udta", title)
    moov = _atom(b"moov", _atom(b"mvhd", b"\x00" * 100) + udta)
    mdat = _atom(b"mdat", bytes(range(256)) * 4)

    path = tmp_path / "synthetic.mov"
    path.write_bytes(ftyp + moov + mdat)
    return path


@pytest.fixture
def png_file(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic.png"
    Image.new("RGB", (32, 24), (200, 40, 90)).save(path, format="PNG")
    return path


@pytest.fixture
def jpeg_file(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic.jpg"
    Image.new("RGB", (32, 24), (10, 120, 220)).save(path, format="JPEG", quality=80)
    return path


def _assert_well_formed(layout, file_size: int) -> None:
    assert layout.segments, "parser produced no segments"
    assert layout.file_size == file_size

    cursor = 0
    for segment in layout.segments:
        assert segment.size > 0, f"zero-size segment at {segment.offset}"
        assert segment.offset >= cursor, f"segment at {segment.offset} overlaps previous segment"
        assert segment.end <= file_size, f"segment at {segment.offset} runs past end of file"
        assert segment.category in VALID_CATEGORIES, f"unknown category {segment.category!r}"
        cursor = segment.end


def _assert_tiles_exactly(layout, file_size: int) -> None:
    _assert_well_formed(layout, file_size)
    assert layout.segments[0].offset == 0, "first segment does not start at byte 0"
    assert layout.segments[-1].end == file_size, "last segment does not reach end of file"
    assert sum(segment.size for segment in layout.segments) == file_size


# --- QuickTime -------------------------------------------------------------


def test_quicktime_layout_tiles_file(mov_file):
    layout = parse_file_layout(mov_file)
    _assert_tiles_exactly(layout, mov_file.stat().st_size)


def test_quicktime_finds_expected_atoms(mov_file):
    layout = parse_file_layout(mov_file)
    labels = {segment.label for segment in layout.segments}
    assert "ftyp header" in labels
    assert "moov header" in labels
    assert "mdat" in labels

    by_label = {segment.label: segment for segment in layout.segments}
    assert by_label["mdat"].category == "payload"
    assert by_label["ftyp header"].category == "header"


def test_quicktime_marks_udta_content_as_metadata(mov_file):
    """Atom headers stay 'structure'; only the content under udta is metadata."""
    layout = parse_file_layout(mov_file)
    udta = [segment for segment in layout.segments if "udta" in segment.path]
    assert udta, "no segments found under udta"

    content = [segment for segment in udta if "header" not in segment.path]
    assert content, "udta had headers but no content segment"
    assert all(segment.category == "metadata" for segment in content)
    assert all(segment.category == "structure" for segment in udta if "header" in segment.path)


def test_quicktime_truncated_file_does_not_crash(mov_file, tmp_path):
    """A file cut mid-atom should still parse into a described layout."""
    truncated = tmp_path / "truncated.mov"
    data = mov_file.read_bytes()
    truncated.write_bytes(data[: len(data) // 2])

    layout = parse_file_layout(truncated)
    _assert_tiles_exactly(layout, truncated.stat().st_size)


# --- PNG -------------------------------------------------------------------


def test_png_layout_tiles_file(png_file):
    layout = parse_file_layout(png_file)
    _assert_tiles_exactly(layout, png_file.stat().st_size)


def test_png_finds_expected_chunks(png_file):
    layout = parse_file_layout(png_file)
    labels = [segment.label for segment in layout.segments]
    assert labels[0] == "signature"
    assert "IHDR" in labels
    assert "IDAT" in labels
    assert labels[-1] == "IEND"

    by_label = {segment.label: segment for segment in layout.segments}
    assert by_label["IDAT"].category == "payload"
    assert by_label["IHDR"].category == "structure"


def test_png_rejects_bad_signature(tmp_path):
    from layout.base import LayoutParseError

    path = tmp_path / "not-really.png"
    path.write_bytes(b"\x00" * 64)
    with pytest.raises(LayoutParseError):
        parse_file_layout(path)


# --- JPEG ------------------------------------------------------------------


def test_jpeg_layout_is_well_formed(jpeg_file):
    layout = parse_file_layout(jpeg_file)
    _assert_well_formed(layout, jpeg_file.stat().st_size)


def test_jpeg_finds_expected_markers(jpeg_file):
    layout = parse_file_layout(jpeg_file)
    labels = [segment.label for segment in layout.segments]
    assert labels[0] == "SOI"
    assert "SOS" in labels
    assert "scan" in labels
    assert "EOI" in labels

    scan = next(segment for segment in layout.segments if segment.label == "scan")
    assert scan.category == "payload"


def test_jpeg_rejects_missing_soi(tmp_path):
    from layout.base import LayoutParseError

    path = tmp_path / "not-really.jpg"
    path.write_bytes(b"\x00" * 64)
    with pytest.raises(LayoutParseError):
        parse_file_layout(path)


# --- Cross-cutting: what the API actually serves ---------------------------


@pytest.mark.parametrize("fixture_name", ["mov_file", "png_file", "jpeg_file"])
def test_every_segment_carries_edit_safety(fixture_name, request):
    path = request.getfixturevalue(fixture_name)
    result = inspect_layout(path)
    assert result.segments
    for segment in result.segments:
        assert segment.edit_safety.level in {"safe", "caution", "unsafe"}
        assert segment.edit_safety.label
        assert segment.edit_safety.reason


@pytest.mark.parametrize("fixture_name", ["mov_file", "png_file", "jpeg_file"])
def test_segment_bytes_match_the_file(fixture_name, request):
    """The hex the inspector shows must be the bytes actually on disk."""
    path = request.getfixturevalue(fixture_name)
    raw = path.read_bytes()
    result = inspect_layout(path)

    for segment in result.segments[:12]:
        view = inspect_segment_bytes(path, segment.offset)
        shown = bytes.fromhex(view.hex.replace(" ...", "").replace(" ", ""))
        assert shown == raw[segment.offset : segment.offset + len(shown)]
        assert view.truncated == (segment.size > len(shown))


@pytest.mark.parametrize("fixture_name", ["mov_file", "png_file", "jpeg_file"])
def test_summary_counts_match_segments(fixture_name, request):
    path = request.getfixturevalue(fixture_name)
    result = inspect_layout(path)
    assert sum(result.summary.values()) == len(result.segments)
