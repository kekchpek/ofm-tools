"""Session TTL cleanup for uploaded files."""

from __future__ import annotations

import asyncio
import os

from api.storage import cleanup_expired_sessions

DEFAULT_INTERVAL_MINUTES = 60


def run_session_cleanup() -> int:
    hours = int(os.environ.get("SESSION_TTL_HOURS", "24"))
    return cleanup_expired_sessions(hours)


def cleanup_interval_seconds() -> int:
    minutes = int(os.environ.get("CLEANUP_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES)))
    return max(minutes, 1) * 60


async def run_periodic_cleanup() -> None:
    """Re-run TTL cleanup on an interval.

    Startup-only cleanup never reclaims anything on a long-running server, so
    uploads accumulate until the next restart.
    """
    interval = cleanup_interval_seconds()
    while True:
        await asyncio.sleep(interval)
        try:
            removed = await asyncio.to_thread(run_session_cleanup)
        except Exception as exc:  # never let the loop die on a transient error
            print(f"Session cleanup failed: {exc}")
            continue
        if removed:
            print(f"Removed {removed} expired upload session(s)")
