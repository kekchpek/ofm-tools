"""Low-level QuickTime atom helpers for metadata grafting."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MOOV_METADATA_ATOM_TYPES = frozenset({"udta", "meta", "uuid", "XMP_", "xml "})


@dataclass(frozen=True)
class AtomSlice:
    offset: int
    size: int
    atom_type: str

    @property
    def end(self) -> int:
        return self.offset + self.size

    def raw(self, data: bytes | memoryview) -> bytes:
        return bytes(data[self.offset : self.end])


def read_atom_header(data: bytes | memoryview, offset: int, container_end: int, file_size: int) -> AtomSlice:
    if offset + 8 > container_end:
        raise ValueError(f"Unexpected end of container at offset {offset}.")

    size32 = struct.unpack_from(">I", data, offset)[0]
    atom_type = data[offset + 4 : offset + 8].decode("latin-1", errors="replace")
    header_size = 8

    if size32 == 1:
        if offset + 16 > container_end:
            raise ValueError(f"Unexpected end of extended atom header at offset {offset}.")
        size = struct.unpack_from(">Q", data, offset + 8)[0]
        header_size = 16
    elif size32 == 0:
        size = min(file_size, container_end) - offset
    else:
        size = size32

    if size < header_size:
        raise ValueError(f"Invalid atom size for {atom_type!r} at offset {offset}.")

    atom_end = min(offset + size, container_end)
    return AtomSlice(offset=offset, size=atom_end - offset, atom_type=atom_type)


def iter_child_atoms(
    data: bytes | memoryview,
    start: int,
    end: int,
    file_size: int,
) -> list[AtomSlice]:
    atoms: list[AtomSlice] = []
    offset = start
    while offset + 8 <= end:
        atom = read_atom_header(data, offset, end, file_size)
        if atom.size < 8 or atom.end <= offset:
            break
        atoms.append(atom)
        offset = atom.end
    return atoms


def find_top_level_atom(data: bytes | memoryview, atom_type: str) -> AtomSlice | None:
    file_size = len(data)
    offset = 0
    while offset + 8 <= file_size:
        atom = read_atom_header(data, offset, file_size, file_size)
        if atom.atom_type == atom_type:
            return atom
        offset = atom.end
    return None


def trak_handler_type(trak_data: bytes) -> str | None:
    file_size = len(trak_data)
    for child in iter_child_atoms(trak_data, 8, len(trak_data), file_size):
        if child.atom_type != "mdia":
            continue
        mdia_data = child.raw(trak_data)
        for mdia_child in iter_child_atoms(mdia_data, 8, len(mdia_data), len(mdia_data)):
            if mdia_child.atom_type != "hdlr":
                continue
            hdlr = mdia_child.raw(mdia_data)
            if len(hdlr) >= 20:
                return hdlr[16:20].decode("latin-1", errors="replace")
    return None


def trak_child_atom(trak_data: bytes, atom_type: str) -> bytes | None:
    file_size = len(trak_data)
    for child in iter_child_atoms(trak_data, 8, len(trak_data), file_size):
        if child.atom_type == atom_type:
            return child.raw(trak_data)
    return None


def rebuild_trak_with_meta(trak_data: bytes, meta_atom: bytes | None) -> bytes:
    if meta_atom is None:
        return trak_data

    file_size = len(trak_data)
    kept: list[bytes] = []
    for child in iter_child_atoms(trak_data, 8, len(trak_data), file_size):
        if child.atom_type == "meta":
            continue
        kept.append(child.raw(trak_data))

    body = b"".join(kept) + meta_atom
    return struct.pack(">I", 8 + len(body)) + b"trak" + body


def extract_metadata_from_source(data: bytes) -> tuple[list[bytes], dict[str, bytes]]:
    moov = find_top_level_atom(data, "moov")
    if moov is None:
        return [], {}

    moov_metadata: list[bytes] = []
    trak_metadata: dict[str, bytes] = {}

    for child in iter_child_atoms(data, moov.offset + 8, moov.end, len(data)):
        if child.atom_type in MOOV_METADATA_ATOM_TYPES:
            moov_metadata.append(child.raw(data))
            continue
        if child.atom_type != "trak":
            continue

        trak_data = child.raw(data)
        handler = trak_handler_type(trak_data)
        meta_atom = trak_child_atom(trak_data, "meta")
        if handler and meta_atom:
            trak_metadata[handler] = meta_atom

    return moov_metadata, trak_metadata


def graft_metadata_into_target(target_data: bytes, moov_metadata: list[bytes], trak_metadata: dict[str, bytes]) -> bytes:
    moov = find_top_level_atom(target_data, "moov")
    if moov is None:
        raise ValueError("Target file does not contain a moov atom.")

    rebuilt_children: list[bytes] = []
    for child in iter_child_atoms(target_data, moov.offset + 8, moov.end, len(target_data)):
        if child.atom_type in MOOV_METADATA_ATOM_TYPES:
            continue

        child_bytes = child.raw(target_data)
        if child.atom_type == "trak":
            trak_data = child_bytes
            handler = trak_handler_type(trak_data)
            child_bytes = rebuild_trak_with_meta(trak_data, trak_metadata.get(handler) if handler else None)
        rebuilt_children.append(child_bytes)

    insert_at = len(rebuilt_children)
    for index in range(len(rebuilt_children) - 1, -1, -1):
        atom_type = rebuilt_children[index][4:8].decode("latin-1", errors="replace")
        if atom_type == "free":
            insert_at = index
        else:
            break

    for offset, metadata_atom in enumerate(moov_metadata):
        rebuilt_children.insert(insert_at + offset, metadata_atom)

    moov_body = b"".join(rebuilt_children)
    new_moov = struct.pack(">I", 8 + len(moov_body)) + b"moov" + moov_body
    return target_data[: moov.offset] + new_moov + target_data[moov.end :]


def write_metadata_graft(source: Path, target: Path, destination: Path) -> None:
    source_data = source.read_bytes()
    target_data = target.read_bytes()
    moov_metadata, trak_metadata = extract_metadata_from_source(source_data)
    if not moov_metadata and not trak_metadata:
        raise ValueError("Metadata source does not contain graftable QuickTime metadata atoms.")

    output = graft_metadata_into_target(target_data, moov_metadata, trak_metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)
