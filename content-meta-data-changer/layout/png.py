"""PNG chunk layout parser."""

from __future__ import annotations

import struct
from pathlib import Path

from layout.base import FileLayout, FileSegment, LayoutParseError, LayoutParser

METADATA_CHUNKS = frozenset({"tEXt", "zTXt", "iTXt", "eXIf", "tIME", "pHYs", "iCCP"})
STRUCTURE_CHUNKS = frozenset({"IHDR", "PLTE", "sBIT", "cHRM", "gAMA", "sRGB", "bKGD", "hIST", "sPLT"})
PAYLOAD_CHUNKS = frozenset({"IDAT"})


def _classify_chunk(chunk_type: str) -> str:
    if chunk_type == "IEND":
        return "header"
    if chunk_type in PAYLOAD_CHUNKS:
        return "payload"
    if chunk_type in METADATA_CHUNKS:
        return "metadata"
    if chunk_type in STRUCTURE_CHUNKS:
        return "structure"
    return "unknown"


def _parse_png_layout(path: Path) -> FileLayout:
    data = path.read_bytes()
    file_size = len(data)
    signature = b"\x89PNG\r\n\x1a\n"
    if file_size < len(signature) or data[: len(signature)] != signature:
        raise LayoutParseError("Not a PNG file (invalid signature).")

    segments: list[FileSegment] = [
        FileSegment(
            offset=0,
            size=len(signature),
            label="signature",
            category="header",
            path=("signature",),
        )
    ]

    offset = len(signature)
    while offset + 8 <= file_size:
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        chunk_size = 12 + length
        if offset + chunk_size > file_size:
            raise LayoutParseError(f"PNG chunk {chunk_type!r} extends past end of file.")

        label = chunk_type.strip() or "????"
        category = _classify_chunk(label)
        segments.append(
            FileSegment(
                offset=offset,
                size=chunk_size,
                label=label,
                category=category,
                path=(label,),
            )
        )
        offset += chunk_size
        if label == "IEND":
            if offset < file_size:
                segments.append(
                    FileSegment(
                        offset=offset,
                        size=file_size - offset,
                        label="trailing",
                        category="unknown",
                        path=("trailing",),
                    )
                )
            break

    return FileLayout(file_size=file_size, segments=tuple(segments))


class PngLayoutParser(LayoutParser):
    extensions = frozenset({".png"})

    def parse(self, path: Path) -> FileLayout:
        if not path.is_file():
            raise LayoutParseError(f"Not a file: {path}")
        return _parse_png_layout(path)
