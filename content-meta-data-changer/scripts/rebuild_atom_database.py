#!/usr/bin/env python3
"""Rebuild the atom descriptions SQLite database from the seed SQL file."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "layout" / "data" / "atoms.db"
SEED_PATH = ROOT / "layout" / "data" / "atoms_seed.sql"
EDIT_SAFETY_SEED_PATH = ROOT / "layout" / "data" / "edit_safety_seed.sql"


def rebuild() -> int:
    if not SEED_PATH.is_file():
        print(f"Seed file not found: {SEED_PATH}", file=sys.stderr)
        return 1
    if not EDIT_SAFETY_SEED_PATH.is_file():
        print(f"Edit safety seed file not found: {EDIT_SAFETY_SEED_PATH}", file=sys.stderr)
        return 1

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
        conn.executescript(EDIT_SAFETY_SEED_PATH.read_text(encoding="utf-8"))
        conn.commit()
        atom_count = conn.execute("SELECT COUNT(*) FROM atom_descriptions").fetchone()[0]
        safety_count = conn.execute("SELECT COUNT(*) FROM edit_safety").fetchone()[0]

    print(
        f"Rebuilt {DB_PATH} with {atom_count} atom descriptions "
        f"and {safety_count} edit safety rules."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(rebuild())
