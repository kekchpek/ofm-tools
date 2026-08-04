"""HEIF/HEIC helpers for item location parsing and mdat subdivision."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from layout.base import FileLayout, FileSegment

HEIF_METADATA_ITEM_TYPES = frozenset(
    {
        "Exif",
        "mime",
        "uri ",
        "XML ",
        "cdsc",
        "idat",
    }
)

HEIF_STRUCTURE_BOXES = frozenset(
    {
        "iloc",
        "iinf",
        "iprp",
        "ipma",
        "pitm",
        "iref",
        "ispe",
        "pixi",
        "auxC",
        "colr",
        "hvcC",
        "infe",
    }
)


@dataclass(frozen=True)
class HeifItemExtent:
    item_id: int
    offset: int
    length: int


def _read_int(data: bytes, offset: int, size: int) -> tuple[int, int]:
    if size == 0:
        return 0, offset
    end = offset + size
    return int.from_bytes(data[offset:end], "big"), end


def _parse_iinf(box: bytes) -> dict[int, str]:
    items: dict[int, str] = {}
    if len(box) < 14:
        return items

    count = struct.unpack_from(">H", box, 12)[0]
    pos = 14
    for _ in range(count):
        if pos + 8 > len(box):
            break
        entry_size = struct.unpack_from(">I", box, pos)[0]
        if entry_size < 8 or pos + entry_size > len(box):
            break
        entry = box[pos : pos + entry_size]
        if len(entry) >= 20:
            item_id = struct.unpack_from(">H", entry, 12)[0]
            item_type = entry[16:20].decode("latin-1", errors="replace")
            items[item_id] = item_type
        pos += entry_size
    return items


def _parse_iloc_apple_heif(box: bytes) -> list[HeifItemExtent] | None:
    """Parse Apple HEIC iloc (version 0 with packed sizes, base before extent_count)."""
    if len(box) < 18:
        return None

    offset_size = box[12] >> 4
    length_size = box[12] & 0xF
    base_offset_size = box[13] >> 4
    index_size = box[13] & 0xF
    if index_size != 0:
        return None
    if not (
        0 < offset_size <= 8
        and 0 < length_size <= 8
        and 0 <= base_offset_size <= 8
    ):
        return None

    item_count = struct.unpack_from(">H", box, 14)[0]
    pos = 16
    extents: list[HeifItemExtent] = []

    for _ in range(item_count):
        if pos + 4 + base_offset_size + 2 > len(box):
            return None
        item_id = struct.unpack_from(">H", box, pos)[0]
        pos += 2
        pos += 2  # data_reference_index
        base_offset, pos = _read_int(box, pos, base_offset_size)
        extent_count = struct.unpack_from(">H", box, pos)[0]
        pos += 2
        for _ in range(extent_count):
            extent_offset, pos = _read_int(box, pos, offset_size)
            extent_length, pos = _read_int(box, pos, length_size)
            if extent_length <= 0:
                continue
            extents.append(
                HeifItemExtent(
                    item_id=item_id,
                    offset=base_offset + extent_offset,
                    length=extent_length,
                )
            )
    return extents


def _parse_iloc_standard(box: bytes, *, skip_version_reserved: bool) -> list[HeifItemExtent]:
    if len(box) < 16:
        return []

    version = box[8]
    pos = 12
    if version in (1, 2):
        offset_size = box[pos] >> 4
        length_size = box[pos] & 0xF
        base_offset_size = box[pos + 1] >> 4
        index_size = box[pos + 1] & 0xF
        pos += 2
        if version == 1 and skip_version_reserved:
            pos += 2
    elif version == 0:
        offset_size = box[pos]
        length_size = box[pos + 1]
        base_offset_size = box[pos + 2]
        index_size = box[pos + 3]
        pos += 4
    else:
        return []

    if pos + 2 > len(box):
        return []

    item_count = struct.unpack_from(">H", box, pos)[0]
    pos += 2
    extents: list[HeifItemExtent] = []
    start_pos = pos

    for _ in range(item_count):
        if pos + 6 > len(box):
            return []
        item_id = struct.unpack_from(">H", box, pos)[0]
        pos += 2
        construction_method = 0
        if version in (1, 2):
            construction_method = struct.unpack_from(">H", box, pos)[0]
            pos += 2
        pos += 2  # data_reference_index
        extent_count = struct.unpack_from(">H", box, pos)[0]
        pos += 2
        base_offset = 0
        if base_offset_size > 0 and (
            version == 0 or construction_method in (0, 1)
        ):
            base_offset, pos = _read_int(box, pos, base_offset_size)
        for _ in range(extent_count):
            if index_size:
                _, pos = _read_int(box, pos, index_size)
            extent_offset, pos = _read_int(box, pos, offset_size)
            extent_length, pos = _read_int(box, pos, length_size)
            if extent_length <= 0:
                continue
            extents.append(
                HeifItemExtent(
                    item_id=item_id,
                    offset=base_offset + extent_offset,
                    length=extent_length,
                )
            )

    if pos > len(box) or (item_count and not extents and pos == start_pos):
        return []
    return extents


def _parse_iloc_standard_variants(box: bytes) -> list[HeifItemExtent]:
    variants: list[list[HeifItemExtent]] = []
    for skip_reserved in (False, True):
        parsed = _parse_iloc_standard(box, skip_version_reserved=skip_reserved)
        if parsed:
            variants.append(parsed)
    if not variants:
        return []
    return max(variants, key=len)


def parse_heif_item_extents(meta_box: bytes) -> tuple[dict[int, str], list[HeifItemExtent]]:
    items: dict[int, str] = {}
    extents: list[HeifItemExtent] = []
    pos = 12
    iloc_box: bytes | None = None

    while pos + 8 <= len(meta_box):
        size = struct.unpack_from(">I", meta_box, pos)[0]
        if size < 8 or pos + size > len(meta_box):
            break
        box_type = meta_box[pos + 4 : pos + 8]
        child = meta_box[pos : pos + size]
        if box_type == b"iinf":
            items = _parse_iinf(child)
        elif box_type == b"iloc":
            iloc_box = child
        pos += size

    if iloc_box is not None:
        apple_extents = _parse_iloc_apple_heif(iloc_box)
        if apple_extents:
            extents = apple_extents
        else:
            extents = _parse_iloc_standard_variants(iloc_box)
    return items, extents


def classify_heif_item_type(item_type: str) -> str:
    if item_type in HEIF_METADATA_ITEM_TYPES:
        return "metadata"
    if item_type in {"hvc1", "hev1", "avc1", "avc3", "grid", "tmap", "thmb", "auxl"}:
        return "payload"
    return "unknown"


def classify_heif_meta_box(atom_type: str) -> str | None:
    if atom_type in HEIF_STRUCTURE_BOXES:
        return "structure"
    if atom_type == "hdlr":
        return "metadata"
    return None


def _find_box(data: bytes, box_type: bytes, start: int = 0, end: int | None = None) -> bytes | None:
    end = end if end is not None else len(data)
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", data, pos)[0]
        if size < 8 or pos + size > end:
            break
        if data[pos + 4 : pos + 8] == box_type:
            return data[pos : pos + size]
        pos += size
    return None


def subdivide_heif_mdat_segments(
    data: bytes,
    segments: list[FileSegment],
) -> list[FileSegment]:
    meta_box = _find_box(data, b"meta")
    if meta_box is None:
        return segments

    item_types, item_extents = parse_heif_item_extents(meta_box)
    if not item_extents:
        return segments

    updated: list[FileSegment] = []
    for segment in segments:
        if segment.label != "mdat" or segment.category != "payload":
            updated.append(segment)
            continue

        mdat_start = segment.offset
        mdat_end = segment.end
        covered = [False] * segment.size
        child_segments: list[FileSegment] = []

        for extent in sorted(item_extents, key=lambda item: item.offset):
            start = extent.offset
            end = extent.offset + extent.length
            if start < mdat_start or end > mdat_end:
                continue
            rel_start = start - mdat_start
            rel_end = end - mdat_start
            for index in range(rel_start, rel_end):
                covered[index] = True

            item_type = item_types.get(extent.item_id, "?")
            category = classify_heif_item_type(item_type)
            child_segments.append(
                FileSegment(
                    offset=start,
                    size=extent.length,
                    label=f"mdat item #{extent.item_id} {item_type}",
                    category=category,
                    path=segment.path + (f"item#{extent.item_id}", item_type),
                )
            )

        if not child_segments:
            updated.append(segment)
            continue

        cursor = mdat_start
        for child in sorted(child_segments, key=lambda item: item.offset):
            if child.offset > cursor:
                updated.append(
                    FileSegment(
                        offset=cursor,
                        size=child.offset - cursor,
                        label="mdat gap",
                        category="unknown",
                        path=segment.path + ("gap",),
                    )
                )
            updated.append(child)
            cursor = child.end

        if cursor < mdat_end:
            updated.append(
                FileSegment(
                    offset=cursor,
                    size=mdat_end - cursor,
                    label="mdat gap",
                    category="unknown",
                    path=segment.path + ("gap",),
                )
            )

    return updated


def _format_segment_range(offset: int, size: int) -> str:
    return f"0x{offset:08X}-0x{offset + size:08X} ({size:,} bytes)"


def _scan_payload_strings(data: bytes, offset: int, size: int) -> list[str]:
    chunk = data[offset : offset + size]
    markers = (
        (b"Exif\x00", "EXIF header"),
        (b"Apple", "Apple"),
        (b"iPhone", "iPhone"),
        (b"GPS", "GPS"),
        (b"mdta", "QuickTime mdta"),
    )
    found: list[str] = []
    for needle, label in markers:
        if needle in chunk:
            rel = chunk.find(needle)
            found.append(f"{label} at +0x{rel:X}")
    return found


def format_payload_metadata_report(path: Path, layout: FileLayout) -> str:
    data = path.read_bytes()
    payload_segments = [segment for segment in layout.segments if segment.category == "payload"]
    metadata_in_payload = [
        segment
        for segment in layout.segments
        if segment.category == "metadata" and "mdat" in segment.path
    ]

    lines = [
        f"=== Payload metadata: {path.name} ===",
        "",
        f"Payload segments: {len(payload_segments)}",
        f"Metadata items inside mdat: {len(metadata_in_payload)}",
        "",
    ]

    if metadata_in_payload:
        lines.append("--- HEIF metadata items in mdat ---")
        for segment in metadata_in_payload:
            lines.append(
                f"{segment.label}  |  {_format_segment_range(segment.offset, segment.size)}"
            )
            markers = _scan_payload_strings(data, segment.offset, segment.size)
            if markers:
                lines.append(f"    markers: {', '.join(markers)}")
        lines.append("")

    suspicious_payload: list[tuple[FileSegment, list[str]]] = []
    for segment in payload_segments:
        markers = _scan_payload_strings(data, segment.offset, segment.size)
        if markers:
            suspicious_payload.append((segment, markers))

    if suspicious_payload:
        lines.append("--- Metadata-like strings in payload segments ---")
        for segment, markers in suspicious_payload:
            lines.append(
                f"{segment.label}  |  {_format_segment_range(segment.offset, segment.size)}"
            )
            lines.append(f"    markers: {', '.join(markers)}")
        lines.append("")
    elif not metadata_in_payload:
        lines.append("No metadata markers found inside payload segments.")
        lines.append("")

    if path.suffix.lower() in {".heic", ".heif"} and not metadata_in_payload and payload_segments:
        meta_box = _find_box(data, b"meta")
        if meta_box is not None:
            item_types, item_extents = parse_heif_item_extents(meta_box)
            mdat_segment = next(
                (segment for segment in layout.segments if segment.label == "mdat"),
                None,
            )
            if mdat_segment is not None:
                lines.append("--- HEIF iloc items overlapping mdat ---")
                for extent in item_extents:
                    item_type = item_types.get(extent.item_id, "?")
                    category = classify_heif_item_type(item_type)
                    start = extent.offset
                    end = extent.offset + extent.length
                    if end <= mdat_segment.offset or start >= mdat_segment.end:
                        continue
                    lines.append(
                        f"item #{extent.item_id} {item_type} ({category})  |  "
                        f"{_format_segment_range(start, extent.length)}"
                    )
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"
