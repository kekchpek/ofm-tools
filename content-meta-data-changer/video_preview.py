"""Embed Finder/QuickTime artwork from a video's first frame."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import cv2

from layout.atom_graft import find_top_level_atom, iter_child_atoms

ARTWORK_KEY = "mdtacom.apple.quicktime.artwork"
DATA_TYPE_JPEG = 13
MAX_PREVIEW_WIDTH = 480


class VideoPreviewError(RuntimeError):
    """Raised when embedded preview artwork cannot be updated."""


def _build_hdlr_mdta() -> bytes:
    body = b"\x00" * 4 + b"\x00" * 4 + b"mdta" + b"\x00" * 12
    return struct.pack(">I", 8 + len(body)) + b"hdlr" + body


def _build_data_atom(payload: bytes, data_type: int) -> bytes:
    body = struct.pack(">II", data_type, 0) + payload
    return struct.pack(">I", 8 + len(body)) + b"data" + body


def _build_ilst_item(index: int, data_atom: bytes) -> bytes:
    body = struct.pack(">I", index) + data_atom
    return struct.pack(">I", 8 + len(body)) + struct.pack(">I", index) + data_atom


def _build_keys_atom(key_names: list[str]) -> bytes:
    entries = b""
    for name in key_names:
        key_bytes = name.encode("utf-8") + b"\x00"
        entries += struct.pack(">I", len(key_bytes)) + key_bytes
    body = b"\x00" * 4 + struct.pack(">I", len(key_names)) + entries
    return struct.pack(">I", 8 + len(body)) + b"keys" + body


def _build_ilst_atom(items: dict[int, bytes]) -> bytes:
    body = b"".join(_build_ilst_item(index, data_atom) for index, data_atom in sorted(items.items()))
    return struct.pack(">I", 8 + len(body)) + b"ilst" + body


def _build_meta_atom(hdlr: bytes, keys: bytes, ilst: bytes) -> bytes:
    body = hdlr + keys + ilst
    return struct.pack(">I", 8 + len(body)) + b"meta" + body


def _parse_keys_atom(keys_atom: bytes) -> list[str]:
    body = keys_atom[8:]
    if len(body) < 8:
        return []

    count = struct.unpack_from(">I", body, 4)[0]
    pos = 8
    names: list[str] = []
    for _ in range(count):
        if pos + 4 > len(body):
            break
        entry_size = struct.unpack_from(">I", body, pos)[0]
        pos += 4
        if pos + entry_size > len(body):
            break
        names.append(body[pos : pos + entry_size].split(b"\x00", 1)[0].decode("utf-8"))
        pos += entry_size
    return names


def _parse_ilst_atom(ilst_atom: bytes) -> dict[int, bytes]:
    items: dict[int, bytes] = {}
    pos = 8
    end = len(ilst_atom)
    while pos + 8 <= end:
        item_size = struct.unpack_from(">I", ilst_atom, pos)[0]
        if item_size < 8 or pos + item_size > end:
            break
        item_index = struct.unpack_from(">I", ilst_atom, pos + 4)[0]
        item_body = ilst_atom[pos + 8 : pos + item_size]
        data_offset = item_body.find(b"data")
        if data_offset >= 4:
            data_atom = item_body[data_offset - 4 :]
            if len(data_atom) >= 8:
                items[item_index] = data_atom
        pos += item_size
    return items


def _meta_child_atoms(meta_atom: bytes) -> dict[str, bytes]:
    children: dict[str, bytes] = {}
    for child in iter_child_atoms(meta_atom, 8, len(meta_atom), len(meta_atom)):
        children[child.atom_type] = child.raw(meta_atom)
    return children


def _build_meta_with_artwork(existing_meta: bytes | None, jpeg_bytes: bytes) -> bytes:
    if existing_meta is None:
        key_names = [ARTWORK_KEY]
        ilst_items = {1: _build_data_atom(jpeg_bytes, DATA_TYPE_JPEG)}
        return _build_meta_atom(
            _build_hdlr_mdta(),
            _build_keys_atom(key_names),
            _build_ilst_atom(ilst_items),
        )

    children = _meta_child_atoms(existing_meta)
    hdlr = children.get("hdlr", _build_hdlr_mdta())
    key_names = _parse_keys_atom(children["keys"]) if "keys" in children else []
    ilst_items = _parse_ilst_atom(children["ilst"]) if "ilst" in children else {}

    if ARTWORK_KEY not in key_names:
        key_names.append(ARTWORK_KEY)
    artwork_index = key_names.index(ARTWORK_KEY) + 1
    ilst_items[artwork_index] = _build_data_atom(jpeg_bytes, DATA_TYPE_JPEG)

    valid_indices = set(range(1, len(key_names) + 1))
    ilst_items = {index: value for index, value in ilst_items.items() if index in valid_indices}

    return _build_meta_atom(
        hdlr,
        _build_keys_atom(key_names),
        _build_ilst_atom(ilst_items),
    )


def extract_first_frame_jpeg(path: Path, *, max_width: int = MAX_PREVIEW_WIDTH) -> bytes:
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            raise VideoPreviewError("Could not read the first video frame.")

        height, width = frame.shape[:2]
        if width > max_width > 0:
            scale = max_width / width
            frame = cv2.resize(
                frame,
                (max_width, max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 85],
        )
        if not ok:
            raise VideoPreviewError("Could not encode the first frame as JPEG.")
        return encoded.tobytes()
    finally:
        capture.release()


def replace_moov_meta(data: bytes, meta_atom: bytes) -> bytes:
    moov = find_top_level_atom(data, "moov")
    if moov is None:
        raise VideoPreviewError("File does not contain a moov atom.")

    rebuilt_children: list[bytes] = []
    inserted = False
    for child in iter_child_atoms(data, moov.offset + 8, moov.end, len(data)):
        if child.atom_type == "meta":
            rebuilt_children.append(meta_atom)
            inserted = True
            continue
        rebuilt_children.append(child.raw(data))

    if not inserted:
        insert_at = len(rebuilt_children)
        for index in range(len(rebuilt_children) - 1, -1, -1):
            atom_type = rebuilt_children[index][4:8].decode("latin-1", errors="replace")
            if atom_type == "free":
                insert_at = index
            else:
                break
        rebuilt_children.insert(insert_at, meta_atom)

    moov_body = b"".join(rebuilt_children)
    new_moov = struct.pack(">I", 8 + len(moov_body)) + b"moov" + moov_body
    return data[: moov.offset] + new_moov + data[moov.end :]


def update_video_preview(path: Path) -> None:
    """Replace embedded Finder artwork with a JPEG from the first frame."""
    resolved = path.resolve()
    jpeg_bytes = extract_first_frame_jpeg(resolved)
    data = resolved.read_bytes()

    existing_meta = None
    moov = find_top_level_atom(data, "moov")
    if moov is None:
        raise VideoPreviewError("File does not contain a moov atom.")

    for child in iter_child_atoms(data, moov.offset + 8, moov.end, len(data)):
        if child.atom_type == "meta":
            existing_meta = child.raw(data)
            break

    new_meta = _build_meta_with_artwork(existing_meta, jpeg_bytes)
    output = replace_moov_meta(data, new_meta)

    with tempfile.NamedTemporaryFile(
        dir=resolved.parent,
        prefix=f".{resolved.stem}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(output)

    temp_path.replace(resolved)
