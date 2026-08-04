"""JPEG marker layout parser."""

from __future__ import annotations

import struct
from pathlib import Path

from layout.base import FileLayout, FileSegment, LayoutParseError, LayoutParser

MARKER_NAMES = {
    0xC0: "SOF0",
    0xC1: "SOF1",
    0xC2: "SOF2",
    0xC3: "SOF3",
    0xC4: "DHT",
    0xC5: "SOF5",
    0xC6: "SOF6",
    0xC7: "SOF7",
    0xC8: "JPG",
    0xC9: "SOF9",
    0xCA: "SOF10",
    0xCB: "SOF11",
    0xCC: "DAC",
    0xCD: "SOF13",
    0xCE: "SOF14",
    0xCF: "SOF15",
    0xD0: "RST0",
    0xD1: "RST1",
    0xD2: "RST2",
    0xD3: "RST3",
    0xD4: "RST4",
    0xD5: "RST5",
    0xD6: "RST6",
    0xD7: "RST7",
    0xD8: "SOI",
    0xD9: "EOI",
    0xDA: "SOS",
    0xDB: "DQT",
    0xDD: "DRI",
    0xDE: "DHP",
    0xDF: "EXP",
    0xFE: "COM",
}


def _marker_label(marker: int) -> str:
    if 0xE0 <= marker <= 0xEF:
        return f"APP{marker - 0xE0}"
    return MARKER_NAMES.get(marker, f"FF{marker:02X}")


def _classify_marker(label: str, data: bytes, offset: int, size: int) -> str:
    if label in {"SOI", "EOI"}:
        return "header"
    if label == "COM" or label.startswith("APP"):
        if label == "APP1" and size >= 10 and data[offset + 4 : offset + 10] == b"Exif\x00\x00":
            return "metadata"
        if label.startswith("APP"):
            return "metadata"
        return "metadata"
    if label == "SOS":
        return "structure"
    if label.startswith("SOF") or label in {"DHT", "DQT", "DRI", "DAC", "JPG"}:
        return "structure"
    if label.startswith("RST"):
        return "padding"
    return "unknown"


def _find_next_marker(data: bytes, start: int, end: int) -> int:
    index = start
    while index + 1 < end:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0x00:
            index += 2
            continue
        if marker == 0xFF:
            index += 1
            continue
        return index
    return end


def _parse_jpeg_layout(path: Path) -> FileLayout:
    data = path.read_bytes()
    file_size = len(data)
    if file_size < 2 or data[0:2] != b"\xFF\xD8":
        raise LayoutParseError("Not a JPEG file (missing SOI marker).")

    segments: list[FileSegment] = []
    segments.append(
        FileSegment(
            offset=0,
            size=2,
            label="SOI",
            category="header",
            path=("SOI",),
        )
    )

    offset = 2
    while offset < file_size:
        if data[offset] != 0xFF:
            next_marker = _find_next_marker(data, offset, file_size)
            if next_marker > offset:
                segments.append(
                    FileSegment(
                        offset=offset,
                        size=next_marker - offset,
                        label="scan",
                        category="payload",
                        path=("scan",),
                    )
                )
            offset = next_marker
            continue

        marker = data[offset + 1]
        label = _marker_label(marker)

        if marker in {0xD8, 0x01}:
            offset += 2
            continue

        if marker == 0xD9:
            segments.append(
                FileSegment(
                    offset=offset,
                    size=2,
                    label="EOI",
                    category="header",
                    path=("EOI",),
                )
            )
            if offset + 2 < file_size:
                segments.append(
                    FileSegment(
                        offset=offset + 2,
                        size=file_size - offset - 2,
                        label="trailing",
                        category="unknown",
                        path=("trailing",),
                    )
                )
            break

        if marker == 0xDA:
            if offset + 4 > file_size:
                raise LayoutParseError("Unexpected end of file in SOS marker.")
            length = struct.unpack_from(">H", data, offset + 2)[0]
            segment_size = 2 + length
            segments.append(
                FileSegment(
                    offset=offset,
                    size=segment_size,
                    label="SOS",
                    category="structure",
                    path=("SOS",),
                )
            )
            offset += segment_size
            next_marker = _find_next_marker(data, offset, file_size)
            if next_marker > offset:
                segments.append(
                    FileSegment(
                        offset=offset,
                        size=next_marker - offset,
                        label="scan",
                        category="payload",
                        path=("scan",),
                    )
                )
            offset = next_marker
            continue

        if offset + 4 > file_size:
            raise LayoutParseError(f"Unexpected end of file before {label} length.")

        length = struct.unpack_from(">H", data, offset + 2)[0]
        if length < 2:
            raise LayoutParseError(f"Invalid {label} segment length at offset {offset}.")
        segment_size = 2 + length
        category = _classify_marker(label, data, offset, segment_size)
        segments.append(
            FileSegment(
                offset=offset,
                size=segment_size,
                label=label,
                category=category,
                path=(label,),
            )
        )
        offset += segment_size

    return FileLayout(file_size=file_size, segments=tuple(segments))


class JpegLayoutParser(LayoutParser):
    extensions = frozenset({".jpg", ".jpeg"})

    def parse(self, path: Path) -> FileLayout:
        if not path.is_file():
            raise LayoutParseError(f"Not a file: {path}")
        return _parse_jpeg_layout(path)
