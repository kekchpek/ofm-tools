"""Session TTL cleanup for uploaded files."""

from __future__ import annotations

import os

from api.storage import cleanup_expired_sessions


def run_session_cleanup() -> int:
    hours = int(os.environ.get("SESSION_TTL_HOURS", "24"))
    return cleanup_expired_sessions(hours)
