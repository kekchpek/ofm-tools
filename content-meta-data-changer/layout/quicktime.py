"""QuickTime/MP4 atom layout parser."""

from __future__ import annotations

import struct
from pathlib import Path

from layout.base import FileLayout, FileSegment, LayoutParseError, LayoutParser
from layout.heif import classify_heif_meta_box, subdivide_heif_mdat_segments

FULL_BOX_CONTAINERS = {
    "meta",
    "moof",
    "traf",
    "mvex",
    "mfra",
    "meco",
}

CONTAINER_ATOMS = {
    "moov",
    "trak",
    "mdia",
    "minf",
    "stbl",
    "edts",
    "udta",
    "meta",
    "ilst",
    "sinf",
    "schi",
    "dinf",
    "gmhd",
    "wave",
    "clip",
    "ipro",
    "moof",
    "traf",
    "mvex",
    "mfra",
    "meco",
    "merc",
    "mere",
    "tref",
    "tapt",
}

STRUCTURE_ATOMS = {
    "mvhd",
    "tkhd",
    "mdhd",
    "hdlr",
    "stco",
    "co64",
    "stsz",
    "stss",
    "stts",
    "stsc",
    "stsd",
    "ctts",
    "sdtp",
    "sgpd",
    "sbgp",
    "csgm",
    "cslg",
    "elst",
    "vmhd",
    "smhd",
    "nmhd",
    "hmhd",
    "gmin",
    "dref",
    "pssh",
    "sidx",
    "tfhd",
    "tfdt",
    "trun",
    "trex",
    "mfhd",
    "tfra",
    "mfro",
}


def _format_atom_type(raw: bytes) -> str:
    return raw.decode("latin-1", errors="replace")


def _looks_like_atom_header(size32: int, atom_type_bytes: bytes, max_size: int) -> bool:
    if size32 == 1:
        if len(atom_type_bytes) != 4:
            return False
        return all(32 <= byte < 127 for byte in atom_type_bytes)
    if size32 < 8 or size32 > max_size:
        return False
    if len(atom_type_bytes) != 4:
        return False
    if atom_type_bytes[0] == 0xA9:
        return True
    atom_type = _format_atom_type(atom_type_bytes)
    if atom_type in {"----", "data", "name", "mean", "hdlr", "keys"}:
        return True
    return all(32 <= byte < 127 for byte in atom_type_bytes)


def _fullbox_content_skip(data: bytes, content_start: int, content_end: int, atom_type: str) -> int:
    if atom_type not in FULL_BOX_CONTAINERS:
        return 0
    if content_start + 8 > content_end:
        return 0

    remaining = content_end - content_start
    first_size = struct.unpack_from(">I", data, content_start)[0]
    first_type = data[content_start + 4 : content_start + 8]
    if _looks_like_atom_header(first_size, first_type, remaining):
        return 0

    if content_start + 12 <= content_end:
        second_size = struct.unpack_from(">I", data, content_start + 4)[0]
        second_type = data[content_start + 8 : content_start + 12]
        if _looks_like_atom_header(second_size, second_type, remaining - 4):
            return 4

    return 4


def _is_metadata_item_container(atom_type: str, path: tuple[str, ...]) -> bool:
    if "ilst" not in path:
        return False
    if atom_type in {"----", "data", "name", "mean"}:
        return False
    if len(atom_type) == 4 and ord(atom_type[0]) == 0xA9:
        return True
    if atom_type == "----":
        return True
    if len(atom_type) == 4 and all(ord(char) < 32 for char in atom_type):
        return True
    return False


def _should_parse_children(atom_type: str, path: tuple[str, ...]) -> bool:
    if atom_type in CONTAINER_ATOMS:
        return True
    return _is_metadata_item_container(atom_type, path)


def _classify_atom(atom_type: str, path: tuple[str, ...]) -> str:
    if "meta" in path:
        heif_category = classify_heif_meta_box(atom_type)
        if heif_category is not None:
            return heif_category

    if atom_type in {"ftyp", "styp"}:
        return "header"
    if atom_type == "mdat":
        return "payload"
    if atom_type in {"free", "skip", "wide"}:
        return "padding"
    if atom_type in {"udta", "meta", "ilst", "uuid", "XMP_", "xml ", "keys", "psmt"}:
        return "metadata"
    if len(atom_type) == 4 and ord(atom_type[0]) == 0xA9:
        return "metadata"
    if atom_type == "----":
        return "metadata"
    if any(part in {"udta", "meta", "ilst"} for part in path):
        return "metadata"
    if any(part in {"tref", "tapt"} for part in path):
        return "structure"
    if atom_type in STRUCTURE_ATOMS:
        return "structure"
    if atom_type in CONTAINER_ATOMS:
        return "structure"
    return "unknown"


def _read_atom_header(data: bytes, offset: int, end: int, file_size: int) -> tuple[int, str, int]:
    if offset + 8 > end:
        raise LayoutParseError("Unexpected end of file while reading atom header.")

    size32 = struct.unpack_from(">I", data, offset)[0]
    atom_type = _format_atom_type(data[offset + 4 : offset + 8])
    header_size = 8

    if size32 == 1:
        if offset + 16 > end:
            raise LayoutParseError("Unexpected end of file while reading extended atom size.")
        size = struct.unpack_from(">Q", data, offset + 8)[0]
        header_size = 16
    elif size32 == 0:
        size = file_size - offset
    else:
        size = size32

    if size < header_size:
        raise LayoutParseError(f"Invalid atom size for {atom_type!r} at offset {offset}.")

    return size, atom_type, header_size


def _parse_atoms(
    data: bytes,
    start: int,
    end: int,
    file_size: int,
    path: tuple[str, ...],
) -> list[FileSegment]:
    segments: list[FileSegment] = []
    offset = start

    while offset < end:
        try:
            size, atom_type, header_size = _read_atom_header(data, offset, end, file_size)
        except LayoutParseError:
            segments.append(
                FileSegment(
                    offset=offset,
                    size=end - offset,
                    label="unparsed",
                    category="unknown",
                    path=path + ("<invalid>",),
                )
            )
            break

        atom_end = min(offset + size, end)
        if atom_end <= offset:
            break

        atom_path = path + (atom_type,)
        category = _classify_atom(atom_type, atom_path)
        content_start = offset + header_size
        content_end = atom_end
        fullbox_skip = _fullbox_content_skip(data, content_start, content_end, atom_type)
        if content_start + fullbox_skip > content_end:
            fullbox_skip = 0
        content_start += fullbox_skip
        header_segment_size = header_size + fullbox_skip

        if header_segment_size > 0:
            header_category = category if atom_type in {"ftyp", "styp", "free", "skip", "wide"} else "structure"
            segments.append(
                FileSegment(
                    offset=offset,
                    size=header_segment_size,
                    label=f"{atom_type} header",
                    category=header_category,
                    path=atom_path + ("header",),
                )
            )

        if _should_parse_children(atom_type, atom_path) and content_end > content_start:
            segments.extend(_parse_atoms(data, content_start, content_end, file_size, atom_path))
        elif content_end > content_start:
            segments.append(
                FileSegment(
                    offset=content_start,
                    size=content_end - content_start,
                    label=atom_type,
                    category=category,
                    path=atom_path,
                )
            )

        offset = atom_end

    return segments


def _fill_gaps(segments: list[FileSegment], file_size: int) -> list[FileSegment]:
    if file_size <= 0:
        return []

    ordered = sorted(segments, key=lambda segment: segment.offset)
    filled: list[FileSegment] = []
    cursor = 0

    for segment in ordered:
        if segment.offset > cursor:
            filled.append(
                FileSegment(
                    offset=cursor,
                    size=segment.offset - cursor,
                    label="gap",
                    category="unknown",
                    path=("<gap>",),
                )
            )
        if segment.end > cursor:
            filled.append(segment)
            cursor = segment.end

    if cursor < file_size:
        filled.append(
            FileSegment(
                offset=cursor,
                size=file_size - cursor,
                label="gap",
                category="unknown",
                path=("<gap>",),
            )
        )

    return filled


def _parse_quicktime_layout(path: Path) -> FileLayout:
    data = path.read_bytes()
    file_size = len(data)
    if file_size == 0:
        return FileLayout(file_size=0, segments=())

    top_level = _parse_atoms(data, 0, file_size, file_size, ())
    segments = _fill_gaps(top_level, file_size)
    if path.suffix.lower() in {".heic", ".heif"}:
        segments = subdivide_heif_mdat_segments(data, segments)
    return FileLayout(file_size=file_size, segments=tuple(segments))


class QuickTimeLayoutParser(LayoutParser):
    extensions = frozenset({".mp4", ".m4v", ".mov", ".heic", ".heif"})

    def parse(self, path: Path) -> FileLayout:
        if not path.is_file():
            raise LayoutParseError(f"Not a file: {path}")
        return _parse_quicktime_layout(path)
