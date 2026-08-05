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


@contextmanager
def connect():
    connection = sqlite3.connect(database_path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
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

            CREATE TABLE IF NOT EXISTS upload_sessions (
                session_id TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY NOT NULL,
                return_url TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )


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


def register_upload_session(session_id: str, user_id: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO upload_sessions (session_id, user_id, created_at)
            VALUES (?, ?, ?)
            """,
            (session_id, user_id, datetime.now(UTC).isoformat()),
        )


def upload_session_owner(session_id: str) -> str | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT user_id FROM upload_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row["user_id"])


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
