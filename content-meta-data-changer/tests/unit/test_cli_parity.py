"""CLI and core output parity."""

from __future__ import annotations

from cli import run_command
from core.inspect import inspect_layout, inspect_metadata


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip() + "\n"


def test_metadata_parity(video6_target):
    cli_text = run_command("metadata", video6_target)
    core_text = inspect_metadata(video6_target).as_text()
    assert _normalize(cli_text) == _normalize(core_text)


def test_layout_parity(video6_target):
    cli_text = run_command("layout", video6_target)
    core_text = inspect_layout(video6_target).as_text()
    assert _normalize(cli_text) == _normalize(core_text)
