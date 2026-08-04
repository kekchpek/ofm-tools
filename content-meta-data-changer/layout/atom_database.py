"""Atom and segment type descriptions backed by SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from layout.base import FileSegment

PACKAGE_DIR = Path(__file__).resolve().parent
DB_PATH = PACKAGE_DIR / "data" / "atoms.db"
SEED_PATH = PACKAGE_DIR / "data" / "atoms_seed.sql"
EDIT_SAFETY_SEED_PATH = PACKAGE_DIR / "data" / "edit_safety_seed.sql"

_UNKNOWN_DESCRIPTION = (
    "No description is available yet for this segment type. It may be a vendor "
    "extension, a rare atom, or unparsed file data."
)
_ITUNES_TAG_DESCRIPTION = (
    "iTunes-style metadata tag ({atom_key}). Four-character QuickTime metadata "
    "identifier, usually shown with a © prefix."
)
_MDTA_KEY_DESCRIPTION = (
    "mdta metadata item key (index {index}). Four-byte local key index used with "
    "the keys box in QuickTime mdta metadata. Match this index to the keys atom "
    "in the same meta box for the full reverse-DNS key name."
)
_IMAGE_SEGMENT_DESCRIPTIONS = {
    "SOI": "JPEG start-of-image marker.",
    "EOI": "JPEG end-of-image marker.",
    "SOS": "JPEG start-of-scan marker. Entropy-coded image data follows.",
    "scan": "JPEG entropy-coded image scan data.",
    "COM": "JPEG comment segment.",
    "DQT": "JPEG quantization table definition.",
    "DHT": "JPEG Huffman table definition.",
    "APP1": "JPEG application segment. Often contains EXIF metadata.",
    "signature": "PNG file signature (8-byte magic header).",
    "IHDR": "PNG image header chunk with width, height, bit depth, and color type.",
    "IDAT": "PNG compressed image data chunk.",
    "IEND": "PNG image end chunk.",
    "tEXt": "PNG uncompressed text metadata chunk.",
    "iTXt": "PNG international text metadata chunk.",
    "zTXt": "PNG compressed text metadata chunk.",
    "eXIf": "PNG chunk containing embedded EXIF metadata.",
    "PLTE": "PNG palette chunk.",
    "trailing": "Extra bytes after the final container marker or chunk.",
}

_connection: sqlite3.Connection | None = None


def _initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not SEED_PATH.is_file():
        raise FileNotFoundError(f"Atom seed file not found: {SEED_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS atom_descriptions (
                atom_key TEXT PRIMARY KEY NOT NULL,
                description TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM atom_descriptions").fetchone()[0]
        if count == 0:
            conn.executescript(SEED_PATH.read_text(encoding="utf-8"))

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS edit_safety (
                atom_key TEXT PRIMARY KEY NOT NULL,
                level TEXT NOT NULL CHECK(level IN ('safe', 'caution', 'unsafe')),
                reason TEXT NOT NULL
            )
            """
        )
        edit_count = conn.execute("SELECT COUNT(*) FROM edit_safety").fetchone()[0]
        if edit_count == 0:
            if not EDIT_SAFETY_SEED_PATH.is_file():
                raise FileNotFoundError(f"Edit safety seed file not found: {EDIT_SAFETY_SEED_PATH}")
            conn.executescript(EDIT_SAFETY_SEED_PATH.read_text(encoding="utf-8"))

        conn.commit()


def _get_connection() -> sqlite3.Connection:
    global _connection

    if _connection is None:
        _initialize_database()
        _connection = sqlite3.connect(DB_PATH)
        _connection.row_factory = sqlite3.Row

    return _connection


def resolve_atom_key(segment: FileSegment) -> str:
    label = segment.label.removesuffix(" header").strip()
    if label and label not in {"gap", "unparsed"}:
        return label

    for part in reversed(segment.path):
        if part in {"header", "<gap>", "<invalid>"}:
            continue
        return part.removesuffix(" header").strip()

    return segment.label


def lookup_atom_description(atom_key: str) -> str | None:
    row = _get_connection().execute(
        "SELECT description FROM atom_descriptions WHERE atom_key = ?",
        (atom_key,),
    ).fetchone()
    if row is None:
        return None
    return str(row["description"])


def lookup_edit_safety(atom_key: str) -> tuple[str, str] | None:
    row = _get_connection().execute(
        "SELECT level, reason FROM edit_safety WHERE atom_key = ?",
        (atom_key,),
    ).fetchone()
    if row is None:
        return None
    return str(row["level"]), str(row["reason"])


def get_atom_description(segment: FileSegment) -> tuple[str, str]:
    atom_key = resolve_atom_key(segment)
    description = lookup_atom_description(atom_key)

    if description is None and len(atom_key) == 4 and ord(atom_key[0]) == 0xA9:
        description = _ITUNES_TAG_DESCRIPTION.format(atom_key=atom_key)

    if description is None and len(atom_key) == 4 and all(ord(char) < 32 for char in atom_key):
        index = int.from_bytes(atom_key.encode("latin-1"), "big")
        if index > 0:
            description = _MDTA_KEY_DESCRIPTION.format(index=index)

    if description is None and atom_key in _IMAGE_SEGMENT_DESCRIPTIONS:
        description = _IMAGE_SEGMENT_DESCRIPTIONS[atom_key]

    if description is None and atom_key.startswith("APP") and atom_key[3:].isdigit():
        description = "JPEG application segment. May contain metadata such as EXIF, XMP, or ICC profile."

    if description is None and atom_key.startswith("SOF"):
        description = "JPEG start-of-frame marker with image frame parameters."

    if description is None:
        description = _UNKNOWN_DESCRIPTION

    return atom_key, description


def list_atom_descriptions() -> list[tuple[str, str]]:
    rows = _get_connection().execute(
        "SELECT atom_key, description FROM atom_descriptions ORDER BY atom_key COLLATE NOCASE"
    ).fetchall()
    return [(str(row["atom_key"]), str(row["description"])) for row in rows]


def _atom_key_has_non_printable(atom_key: str) -> bool:
    return any(not char.isprintable() or ord(char) < 32 for char in atom_key)


def format_atom_key_line(atom_key: str) -> str:
    if not _atom_key_has_non_printable(atom_key):
        return atom_key

    hex_repr = " ".join(f"{ord(char):02X}" for char in atom_key)
    text_repr = "".join(
        char if 32 <= ord(char) <= 126 else "."
        for char in atom_key
    )
    return f"{text_repr}  [{hex_repr}]"


def collect_unknown_atom_keys(segments: tuple[FileSegment, ...]) -> list[str]:
    unknown: set[str] = set()

    for segment in segments:
        atom_key = resolve_atom_key(segment)
        if atom_key in {"gap", "unparsed"}:
            continue
        if lookup_atom_description(atom_key) is None:
            if len(atom_key) == 4 and ord(atom_key[0]) == 0xA9:
                continue
            if len(atom_key) == 4 and all(ord(char) < 32 for char in atom_key):
                if int.from_bytes(atom_key.encode("latin-1"), "big") > 0:
                    continue
            if atom_key in _IMAGE_SEGMENT_DESCRIPTIONS:
                continue
            if atom_key.startswith("APP") and atom_key[3:].isdigit():
                continue
            if atom_key.startswith("SOF"):
                continue
            unknown.add(atom_key)

    return sorted(unknown, key=str.casefold)


def format_unknown_atom_keys(segments: tuple[FileSegment, ...]) -> str:
    return "\n".join(format_atom_key_line(key) for key in collect_unknown_atom_keys(segments))
