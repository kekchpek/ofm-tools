"""Edit safety guidance for memory layout segments."""

from __future__ import annotations

from dataclasses import dataclass

from layout.atom_database import lookup_edit_safety, resolve_atom_key
from layout.base import FileSegment

EditSafetyLevel = str  # "safe" | "caution" | "unsafe"

EDIT_SAFETY_LABELS: dict[EditSafetyLevel, str] = {
    "safe": "Usually safe",
    "caution": "Edit with care",
    "unsafe": "Do not edit",
}

EDIT_SAFETY_MARKS: dict[EditSafetyLevel, str] = {
    "safe": "\u2713",
    "caution": "!",
    "unsafe": "\u2717",
}

EDIT_SAFETY_COLORS: dict[EditSafetyLevel, str] = {
    "safe": "#43a047",
    "caution": "#ffa726",
    "unsafe": "#e53935",
}


@dataclass(frozen=True)
class EditSafetyInfo:
    level: EditSafetyLevel
    label: str
    reason: str


def _make_edit_safety_info(level: str, reason: str) -> EditSafetyInfo:
    return EditSafetyInfo(level, EDIT_SAFETY_LABELS[level], reason)


def _lookup_or_default(atom_key: str) -> EditSafetyInfo:
    row = lookup_edit_safety(atom_key)
    if row is not None:
        return _make_edit_safety_info(*row)
    fallback = lookup_edit_safety("<caution-default>")
    if fallback is not None:
        return _make_edit_safety_info(*fallback)
    return EditSafetyInfo(
        "caution",
        EDIT_SAFETY_LABELS["caution"],
        "Effect on playback is unclear. Edit only if you understand this atom type.",
    )


def get_edit_safety(segment: FileSegment) -> EditSafetyInfo:
    atom_key = resolve_atom_key(segment)
    is_header = segment.label.endswith(" header") or "header" in segment.path

    if is_header:
        return _lookup_or_default("<header>")

    if atom_key in {"gap", "unparsed"} or "<invalid>" in segment.path:
        row = lookup_edit_safety(atom_key) or lookup_edit_safety("<unknown-default>")
        if row is not None:
            return _make_edit_safety_info(*row)

    if segment.category == "unknown":
        return _lookup_or_default("<unknown-default>")

    if segment.category == "payload" or atom_key == "mdat":
        return _lookup_or_default("mdat")

    row = lookup_edit_safety(atom_key)
    if row is not None:
        return _make_edit_safety_info(*row)

    if len(atom_key) == 4 and all(ord(char) < 32 for char in atom_key):
        index = int.from_bytes(atom_key.encode("latin-1"), "big")
        if index > 0:
            mdta_default = lookup_edit_safety("<mdta-key-default>")
            if mdta_default is not None:
                return _make_edit_safety_info(*mdta_default)

    if len(atom_key) == 4 and ord(atom_key[0]) == 0xA9:
        return _lookup_or_default("<metadata-default>")

    if segment.category == "metadata":
        return _lookup_or_default("<metadata-default>")

    if segment.category == "structure":
        return _lookup_or_default("<structure-default>")

    if segment.category == "header":
        return _lookup_or_default("<header>")

    return _lookup_or_default("<caution-default>")


def format_edit_safety_mark(segment: FileSegment) -> str:
    info = get_edit_safety(segment)
    return EDIT_SAFETY_MARKS[info.level]


def format_edit_safety_summary(segment: FileSegment) -> str:
    info = get_edit_safety(segment)
    mark = EDIT_SAFETY_MARKS[info.level]
    return f"{mark} {info.label}"
