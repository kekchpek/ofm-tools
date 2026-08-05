"""Smoke tests for fixture availability and existing parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from layout import parse_file_layout
from metadata import format_metadata, supported_extensions


def test_repo_root_exists(repo_root: Path) -> None:
    assert repo_root.is_dir()
    assert (repo_root / "cli.py").is_file()


def test_supported_extensions_include_primary_formats() -> None:
    extensions = supported_extensions()
    assert ".mov" in extensions
    assert ".heic" in extensions


def test_video6_target_is_file(video6_target: Path) -> None:
    assert video6_target.suffix.lower() == ".mov"


def test_video6_layout_parses(video6_target: Path) -> None:
    layout = parse_file_layout(video6_target)
    assert layout.file_size > 0
    assert len(layout.segments) > 0


def test_video6_metadata_non_empty(video6_target: Path) -> None:
    text = format_metadata(video6_target)
    assert "Format:" in text
    assert len(text.strip()) > 0


@pytest.mark.parametrize(
    "fixture_name",
    ["video6_source", "video6_output", "heic_source"],
)
def test_optional_fixtures_skip_when_missing(fixture_name: str, request: pytest.FixtureRequest) -> None:
    try:
        path = request.getfixturevalue(fixture_name)
    except pytest.SkipException:
        pytest.skip(f"{fixture_name} unavailable")
    assert path.is_file()
