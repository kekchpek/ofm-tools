"""Shared pytest fixtures for Content Metadata Changer."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# OfmContent is sample media kept outside version control. Override the location
# with OFM_CONTENT_DIR; tests that need it skip when it is missing (e.g. in CI).
OFM_CONTENT = Path(os.environ.get("OFM_CONTENT_DIR", REPO_ROOT.parent / "OfmContent")).resolve()


def _optional_fixture(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"Fixture not found: {path}")
    return path


@pytest.fixture(autouse=True)
def disable_google_auth(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def ofm_content() -> Path:
    if not OFM_CONTENT.is_dir():
        pytest.skip(f"OfmContent directory not found: {OFM_CONTENT}")
    return OFM_CONTENT


@pytest.fixture
def video6_target(ofm_content: Path) -> Path:
    return _optional_fixture(ofm_content / "TikTok" / "Video" / "video6.mov")


@pytest.fixture
def video6_source(ofm_content: Path) -> Path:
    return _optional_fixture(ofm_content / "TikTok" / "Video" / "video6_meta_source.mov")


@pytest.fixture
def video6_output(ofm_content: Path) -> Path:
    return _optional_fixture(ofm_content / "TikTok" / "Video" / "video6_with_metadata.mov")


@pytest.fixture
def heic_source(ofm_content: Path) -> Path:
    return _optional_fixture(ofm_content / "TikTok" / "avatar_meta_data_source.HEIC")


@pytest.fixture
def tmp_media(tmp_path: Path) -> Path:
    directory = tmp_path / "media"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture
def synthetic_png(tmp_path: Path) -> Path:
    """A real image built on the fly.

    Tests that must run in CI use this instead of the ``OfmContent`` fixtures,
    which are not checked into the repository.
    """
    from PIL import Image

    path = tmp_path / "synthetic_fixture.png"
    Image.new("RGB", (48, 32), (120, 60, 200)).save(path, format="PNG")
    return path
