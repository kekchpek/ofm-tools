"""SQLite persistence for users and upload session ownership."""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class UserRecord:
    id: str
    google_sub: str
    email: str
    name: str
    picture_url: str | None


def database_path() -> Path:
    path = Path(os.environ.get("DATABASE_PATH", "data/app.db")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY NOT NULL,
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    picture_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- An upload session is owned either by a signed-in user (user_id) or by an
-- anonymous browser identified by a cookie (client_id). Exactly one is set.
CREATE TABLE IF NOT EXISTS upload_sessions (
    session_id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT,
    client_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY NOT NULL,
    return_url TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- An OFM is a shared workspace holding content pieces. It has one owner and
-- any number of invited members.
CREATE TABLE IF NOT EXISTS ofms (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    owner_user_id TEXT,
    owner_client_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Membership is keyed by email so someone can be invited before they have ever
-- signed in; user_id is bound on their first access. `role` is deliberately a
-- free-form string: today only "owner" and "editor" exist, but a richer
-- permission system is expected to add more without a migration.
CREATE TABLE IF NOT EXISTS ofm_members (
    id TEXT PRIMARY KEY NOT NULL,
    ofm_id TEXT NOT NULL,
    email TEXT NOT NULL,
    user_id TEXT,
    client_id TEXT,
    role TEXT NOT NULL,
    invited_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(ofm_id, email)
);

-- Saved OFM Factory projects, belonging to an OFM. Referenced files are pinned
-- against TTL cleanup for as long as the row exists.
CREATE TABLE IF NOT EXISTS content_pieces (
    id TEXT PRIMARY KEY NOT NULL,
    ofm_id TEXT NOT NULL,
    name TEXT NOT NULL,
    output_stem TEXT NOT NULL DEFAULT '',
    source_file_id TEXT,
    metadata_file_id TEXT,
    result_file_id TEXT,
    result_filename TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pieces_ofm ON content_pieces(ofm_id);
CREATE INDEX IF NOT EXISTS idx_members_ofm ON ofm_members(ofm_id);
CREATE INDEX IF NOT EXISTS idx_members_email ON ofm_members(email);
CREATE INDEX IF NOT EXISTS idx_ofms_owner_user ON ofms(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_ofms_owner_client ON ofms(owner_client_id);
"""

_initialized_paths: set[Path] = set()


def _migrate_upload_sessions(connection: sqlite3.Connection) -> None:
    """Add client_id to pre-anonymous-ownership databases.

    The original table declared ``user_id TEXT NOT NULL`` with a foreign key to
    users, which cannot hold an anonymous owner. SQLite cannot drop a NOT NULL
    constraint in place, so the table is rebuilt when the new column is absent.
    """
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(upload_sessions)")}
    if not columns or "client_id" in columns:
        return
    connection.executescript(
        """
        ALTER TABLE upload_sessions RENAME TO upload_sessions_legacy;

        CREATE TABLE upload_sessions (
            session_id TEXT PRIMARY KEY NOT NULL,
            user_id TEXT,
            client_id TEXT,
            created_at TEXT NOT NULL
        );

        INSERT INTO upload_sessions (session_id, user_id, client_id, created_at)
        SELECT session_id, user_id, NULL, created_at FROM upload_sessions_legacy;

        DROP TABLE upload_sessions_legacy;
        """
    )


def _migrate_pieces_into_ofms(connection: sqlite3.Connection) -> None:
    """Move account-owned pieces into a per-owner OFM.

    Pieces used to hang directly off a user or client cookie. Each distinct
    owner gets one OFM holding everything they had, so no saved work is lost.
    """
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(content_pieces)")}
    if not columns or "ofm_id" in columns:
        return

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ofms (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            owner_user_id TEXT,
            owner_client_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ofm_members (
            id TEXT PRIMARY KEY NOT NULL,
            ofm_id TEXT NOT NULL,
            email TEXT NOT NULL,
            user_id TEXT,
            client_id TEXT,
            role TEXT NOT NULL,
            invited_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(ofm_id, email)
        );

        ALTER TABLE content_pieces RENAME TO content_pieces_legacy;

        CREATE TABLE content_pieces (
            id TEXT PRIMARY KEY NOT NULL,
            ofm_id TEXT NOT NULL,
            name TEXT NOT NULL,
            output_stem TEXT NOT NULL DEFAULT '',
            source_file_id TEXT,
            metadata_file_id TEXT,
            result_file_id TEXT,
            result_filename TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    now = datetime.now(UTC).isoformat()
    owners = connection.execute(
        "SELECT DISTINCT user_id, client_id FROM content_pieces_legacy"
    ).fetchall()

    for owner in owners:
        user_id = owner["user_id"]
        client_id = owner["client_id"]
        ofm_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO ofms (id, name, owner_user_id, owner_client_id, created_at, updated_at)
            VALUES (?, 'My OFM', ?, ?, ?, ?)
            """,
            (ofm_id, user_id, client_id, now, now),
        )
        email = None
        if user_id:
            row = connection.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            email = row["email"] if row else None
        connection.execute(
            """
            INSERT INTO ofm_members (id, ofm_id, email, user_id, client_id, role, created_at)
            VALUES (?, ?, ?, ?, ?, 'owner', ?)
            """,
            (str(uuid.uuid4()), ofm_id, email or f"anon:{client_id}", user_id, client_id, now),
        )
        clause = "user_id = ?" if user_id else "client_id = ?"
        connection.execute(
            f"""
            INSERT INTO content_pieces
                (id, ofm_id, name, output_stem, source_file_id, metadata_file_id,
                 result_file_id, result_filename, position, created_at, updated_at)
            SELECT id, ?, name, output_stem, source_file_id, metadata_file_id,
                   result_file_id, result_filename, position, created_at, updated_at
            FROM content_pieces_legacy WHERE {clause}
            """,
            (ofm_id, user_id or client_id),
        )

    connection.executescript("DROP TABLE content_pieces_legacy;")


def _ensure_schema(path: Path) -> None:
    if path in _initialized_paths:
        return
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        _migrate_upload_sessions(connection)
        _migrate_pieces_into_ofms(connection)
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()
    _initialized_paths.add(path)


@contextmanager
def connect():
    path = database_path()
    _ensure_schema(path)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    _ensure_schema(database_path())


def upsert_google_user(*, google_sub: str, email: str, name: str, picture_url: str | None) -> UserRecord:
    now = datetime.now(UTC).isoformat()
    with connect() as connection:
        row = connection.execute(
            "SELECT id, google_sub, email, name, picture_url FROM users WHERE google_sub = ?",
            (google_sub,),
        ).fetchone()
        if row is None:
            user_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO users (id, google_sub, email, name, picture_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, google_sub, email, name, picture_url, now),
            )
        else:
            user_id = str(row["id"])
            connection.execute(
                """
                UPDATE users
                SET email = ?, name = ?, picture_url = ?
                WHERE id = ?
                """,
                (email, name, picture_url, user_id),
            )
    return get_user_by_id(user_id)


def get_user_by_id(user_id: str) -> UserRecord:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, google_sub, email, name, picture_url FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"Unknown user: {user_id}")
    return UserRecord(
        id=str(row["id"]),
        google_sub=str(row["google_sub"]),
        email=str(row["email"]),
        name=str(row["name"]),
        picture_url=str(row["picture_url"]) if row["picture_url"] else None,
    )


def create_auth_session(user_id: str, *, ttl_hours: int) -> str:
    token = str(uuid.uuid4())
    expires_at = (datetime.now(UTC) + timedelta(hours=ttl_hours)).isoformat()
    with connect() as connection:
        connection.execute(
            "INSERT INTO auth_sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at),
        )
    return token


def delete_auth_session(token: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))


def get_user_for_auth_token(token: str) -> UserRecord | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.google_sub, users.email, users.name, users.picture_url, auth_sessions.expires_at
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(UTC):
            connection.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            return None
    return UserRecord(
        id=str(row["id"]),
        google_sub=str(row["google_sub"]),
        email=str(row["email"]),
        name=str(row["name"]),
        picture_url=str(row["picture_url"]) if row["picture_url"] else None,
    )


@dataclass(frozen=True)
class UploadSessionOwner:
    user_id: str | None
    client_id: str | None


def register_upload_session(
    session_id: str,
    *,
    user_id: str | None = None,
    client_id: str | None = None,
) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO upload_sessions (session_id, user_id, client_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, user_id, client_id, datetime.now(UTC).isoformat()),
        )


def upload_session_owner(session_id: str) -> UploadSessionOwner | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT user_id, client_id FROM upload_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return UploadSessionOwner(
        user_id=str(row["user_id"]) if row["user_id"] else None,
        client_id=str(row["client_id"]) if row["client_id"] else None,
    )


def delete_upload_sessions(session_ids: list[str]) -> None:
    if not session_ids:
        return
    with connect() as connection:
        connection.executemany(
            "DELETE FROM upload_sessions WHERE session_id = ?",
            [(session_id,) for session_id in session_ids],
        )


def create_oauth_state(return_url: str, *, ttl_minutes: int = 10) -> str:
    state = str(uuid.uuid4())
    expires_at = (datetime.now(UTC) + timedelta(minutes=ttl_minutes)).isoformat()
    with connect() as connection:
        connection.execute(
            "INSERT INTO oauth_states (state, return_url, expires_at) VALUES (?, ?, ?)",
            (state, return_url, expires_at),
        )
    return state


def consume_oauth_state(state: str) -> str | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT return_url, expires_at FROM oauth_states WHERE state = ?",
            (state,),
        ).fetchone()
        connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    if row is None:
        return None
    if datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(UTC):
        return None
    return str(row["return_url"])


# --- OFMs, membership, and their content pieces -----------------------------


@dataclass(frozen=True)
class OfmRecord:
    id: str
    name: str
    owner_user_id: str | None
    owner_client_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OfmMemberRecord:
    id: str
    ofm_id: str
    email: str
    user_id: str | None
    client_id: str | None
    role: str
    created_at: str


@dataclass(frozen=True)
class ContentPieceRecord:
    id: str
    ofm_id: str
    name: str
    output_stem: str
    source_file_id: str | None
    metadata_file_id: str | None
    result_file_id: str | None
    result_filename: str | None
    position: int
    created_at: str
    updated_at: str

    def file_ids(self) -> list[str]:
        return [
            file_id
            for file_id in (self.source_file_id, self.metadata_file_id, self.result_file_id)
            if file_id
        ]


def _ofm_from_row(row: sqlite3.Row) -> OfmRecord:
    return OfmRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        owner_user_id=str(row["owner_user_id"]) if row["owner_user_id"] else None,
        owner_client_id=str(row["owner_client_id"]) if row["owner_client_id"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _member_from_row(row: sqlite3.Row) -> OfmMemberRecord:
    return OfmMemberRecord(
        id=str(row["id"]),
        ofm_id=str(row["ofm_id"]),
        email=str(row["email"]),
        user_id=str(row["user_id"]) if row["user_id"] else None,
        client_id=str(row["client_id"]) if row["client_id"] else None,
        role=str(row["role"]),
        created_at=str(row["created_at"]),
    )


def _piece_from_row(row: sqlite3.Row) -> ContentPieceRecord:
    return ContentPieceRecord(
        id=str(row["id"]),
        ofm_id=str(row["ofm_id"]),
        name=str(row["name"]),
        output_stem=str(row["output_stem"] or ""),
        source_file_id=str(row["source_file_id"]) if row["source_file_id"] else None,
        metadata_file_id=str(row["metadata_file_id"]) if row["metadata_file_id"] else None,
        result_file_id=str(row["result_file_id"]) if row["result_file_id"] else None,
        result_filename=str(row["result_filename"]) if row["result_filename"] else None,
        position=int(row["position"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def create_ofm(
    *,
    name: str,
    owner_user_id: str | None,
    owner_client_id: str | None,
    owner_email: str | None,
) -> OfmRecord:
    ofm_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO ofms (id, name, owner_user_id, owner_client_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ofm_id, name, owner_user_id, owner_client_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO ofm_members (id, ofm_id, email, user_id, client_id, role, created_at)
            VALUES (?, ?, ?, ?, ?, 'owner', ?)
            """,
            (
                str(uuid.uuid4()),
                ofm_id,
                (owner_email or f"anon:{owner_client_id}").lower(),
                owner_user_id,
                owner_client_id,
                now,
            ),
        )
    return get_ofm(ofm_id)  # type: ignore[return-value]


def get_ofm(ofm_id: str) -> OfmRecord | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM ofms WHERE id = ?", (ofm_id,)).fetchone()
    return _ofm_from_row(row) if row is not None else None


def rename_ofm(ofm_id: str, name: str) -> OfmRecord | None:
    with connect() as connection:
        connection.execute(
            "UPDATE ofms SET name = ?, updated_at = ? WHERE id = ?",
            (name, datetime.now(UTC).isoformat(), ofm_id),
        )
    return get_ofm(ofm_id)


def delete_ofm(ofm_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM content_pieces WHERE ofm_id = ?", (ofm_id,))
        connection.execute("DELETE FROM ofm_members WHERE ofm_id = ?", (ofm_id,))
        connection.execute("DELETE FROM ofms WHERE id = ?", (ofm_id,))


def member_role(ofm_id: str, *, email: str | None, client_id: str | None) -> str | None:
    """The caller's role in this OFM, or None if they are not a member."""
    with connect() as connection:
        if email:
            row = connection.execute(
                "SELECT role FROM ofm_members WHERE ofm_id = ? AND lower(email) = lower(?)",
                (ofm_id, email),
            ).fetchone()
            if row is not None:
                return str(row["role"])
        if client_id:
            row = connection.execute(
                "SELECT role FROM ofm_members WHERE ofm_id = ? AND client_id = ?",
                (ofm_id, client_id),
            ).fetchone()
            if row is not None:
                return str(row["role"])
    return None


def bind_member_user(ofm_id: str, email: str, user_id: str) -> None:
    """Attach a real account to an invitation once that person signs in."""
    with connect() as connection:
        connection.execute(
            """
            UPDATE ofm_members SET user_id = ?
            WHERE ofm_id = ? AND lower(email) = lower(?) AND user_id IS NULL
            """,
            (user_id, ofm_id, email),
        )


def list_ofms_for(*, email: str | None, client_id: str | None) -> list[OfmRecord]:
    conditions: list[str] = []
    params: list[str] = []
    if email:
        conditions.append("lower(m.email) = lower(?)")
        params.append(email)
    if client_id:
        conditions.append("m.client_id = ?")
        params.append(client_id)
    if not conditions:
        return []
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT o.* FROM ofms o
            JOIN ofm_members m ON m.ofm_id = o.id
            WHERE {" OR ".join(conditions)}
            GROUP BY o.id
            ORDER BY o.created_at
            """,
            params,
        ).fetchall()
    return [_ofm_from_row(row) for row in rows]


def list_members(ofm_id: str) -> list[OfmMemberRecord]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM ofm_members WHERE ofm_id = ? ORDER BY role != 'owner', created_at",
            (ofm_id,),
        ).fetchall()
    return [_member_from_row(row) for row in rows]


def get_member(member_id: str) -> OfmMemberRecord | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM ofm_members WHERE id = ?", (member_id,)
        ).fetchone()
    return _member_from_row(row) if row is not None else None


def add_member(ofm_id: str, email: str, role: str, invited_by: str | None) -> OfmMemberRecord:
    normalized = email.strip().lower()
    with connect() as connection:
        existing = connection.execute(
            "SELECT * FROM ofm_members WHERE ofm_id = ? AND lower(email) = ?",
            (ofm_id, normalized),
        ).fetchone()
        if existing is not None:
            return _member_from_row(existing)
        # Bind straight away when the invitee already has an account.
        user_row = connection.execute(
            "SELECT id FROM users WHERE lower(email) = ?", (normalized,)
        ).fetchone()
        member_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO ofm_members (id, ofm_id, email, user_id, client_id, role, invited_by, created_at)
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                member_id,
                ofm_id,
                normalized,
                user_row["id"] if user_row else None,
                role,
                invited_by,
                datetime.now(UTC).isoformat(),
            ),
        )
    return get_member(member_id)  # type: ignore[return-value]


def remove_member(member_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM ofm_members WHERE id = ?", (member_id,))


def create_content_piece(*, ofm_id: str, name: str, position: int) -> ContentPieceRecord:
    piece_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO content_pieces (id, ofm_id, name, output_stem, position, created_at, updated_at)
            VALUES (?, ?, ?, '', ?, ?, ?)
            """,
            (piece_id, ofm_id, name, position, now, now),
        )
    return get_content_piece(piece_id)  # type: ignore[return-value]


def get_content_piece(piece_id: str) -> ContentPieceRecord | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM content_pieces WHERE id = ?", (piece_id,)
        ).fetchone()
    return _piece_from_row(row) if row is not None else None


def list_content_pieces(ofm_id: str) -> list[ContentPieceRecord]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM content_pieces WHERE ofm_id = ? ORDER BY position, created_at",
            (ofm_id,),
        ).fetchall()
    return [_piece_from_row(row) for row in rows]


UPDATABLE_PIECE_FIELDS = frozenset(
    {
        "name",
        "output_stem",
        "source_file_id",
        "metadata_file_id",
        "result_file_id",
        "result_filename",
        "position",
    }
)


def update_content_piece(piece_id: str, changes: dict[str, object]) -> ContentPieceRecord | None:
    fields = {key: value for key, value in changes.items() if key in UPDATABLE_PIECE_FIELDS}
    if fields:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with connect() as connection:
            connection.execute(
                f"UPDATE content_pieces SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), datetime.now(UTC).isoformat(), piece_id),
            )
    return get_content_piece(piece_id)


def delete_content_piece(piece_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM content_pieces WHERE id = ?", (piece_id,))


def referenced_file_ids(*, excluding_piece: str | None = None) -> set[str]:
    """Every file id any saved piece points at — these must survive TTL cleanup."""
    query = "SELECT source_file_id, metadata_file_id, result_file_id FROM content_pieces"
    params: tuple = ()
    if excluding_piece is not None:
        query += " WHERE id != ?"
        params = (excluding_piece,)
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return {
        str(value)
        for row in rows
        for value in (row["source_file_id"], row["metadata_file_id"], row["result_file_id"])
        if value
    }


def ofm_ids_referencing_file(file_id: str) -> set[str]:
    """Which OFMs use this file — lets members read each other's uploads."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT ofm_id FROM content_pieces
            WHERE source_file_id = ? OR metadata_file_id = ? OR result_file_id = ?
            """,
            (file_id, file_id, file_id),
        ).fetchall()
    return {str(row["ofm_id"]) for row in rows}


def ofm_file_ids(ofm_id: str) -> set[str]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT source_file_id, metadata_file_id, result_file_id
            FROM content_pieces WHERE ofm_id = ?
            """,
            (ofm_id,),
        ).fetchall()
    return {
        str(value)
        for row in rows
        for value in (row["source_file_id"], row["metadata_file_id"], row["result_file_id"])
        if value
    }


def sessions_for_owner(*, user_id: str | None, client_id: str | None) -> list[str]:
    clause = "user_id = ?" if user_id is not None else "client_id = ?"
    value = user_id if user_id is not None else client_id
    with connect() as connection:
        rows = connection.execute(
            f"SELECT session_id FROM upload_sessions WHERE {clause}", (value,)
        ).fetchall()
    return [str(row["session_id"]) for row in rows]
