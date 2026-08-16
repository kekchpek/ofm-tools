"""Content pieces inside an OFM: persistence, access, file pinning, and quota."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("JOBS_SYNC", "1")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    return tmp_path


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _session(client: AsyncClient) -> str:
    return (await client.post("/api/v1/sessions")).json()["session_id"]


async def _ofm(client: AsyncClient, name: str = "Test OFM") -> str:
    response = await client.post("/api/v1/ofms", json={"name": name})
    response.raise_for_status()
    return response.json()["id"]


async def _piece(client: AsyncClient, ofm_id: str, name: str) -> dict:
    response = await client.post(f"/api/v1/ofms/{ofm_id}/pieces", json={"name": name})
    response.raise_for_status()
    return response.json()


async def _upload(client: AsyncClient, session_id: str, path: Path) -> str:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    response.raise_for_status()
    return response.json()["file_id"]


@pytest.mark.anyio
async def test_pieces_persist_across_browser_sessions(api_env, synthetic_png):
    """The whole point: reload the page and your work is still there."""
    async with _client() as client:
        session_id = await _session(client)
        ofm_id = await _ofm(client)
        piece = await _piece(client, ofm_id, "Beach set")
        file_id = await _upload(client, session_id, synthetic_png)
        await client.patch(
            f"/api/v1/pieces/{piece['id']}",
            json={"source_file_id": file_id, "output_stem": "beach"},
        )

        # A brand new upload session stands in for a page reload.
        await _session(client)
        pieces = (await client.get(f"/api/v1/ofms/{ofm_id}/pieces")).json()

    assert len(pieces) == 1
    assert pieces[0]["name"] == "Beach set"
    assert pieces[0]["output_stem"] == "beach"
    assert pieces[0]["source_file_id"] == file_id
    assert pieces[0]["source_file"]["filename"] == synthetic_png.name


@pytest.mark.anyio
async def test_pieces_are_private_to_non_members(api_env):
    async with _client() as owner:
        await _session(owner)
        ofm_id = await _ofm(owner, "Private")
        piece = await _piece(owner, ofm_id, "Mine")

    async with _client() as intruder:
        await _session(intruder)
        # A non-member cannot even see that the OFM exists.
        assert (await intruder.get(f"/api/v1/ofms/{ofm_id}")).status_code == 404
        assert (await intruder.get(f"/api/v1/ofms/{ofm_id}/pieces")).status_code == 404
        assert (
            await intruder.patch(f"/api/v1/pieces/{piece['id']}", json={"name": "Yours"})
        ).status_code == 404
        assert (await intruder.delete(f"/api/v1/pieces/{piece['id']}")).status_code == 404
        assert (await intruder.get("/api/v1/ofms")).json() == []


@pytest.mark.anyio
async def test_piece_cannot_point_at_someone_elses_file(api_env, synthetic_png):
    async with _client() as owner:
        session_id = await _session(owner)
        await _ofm(owner)
        file_id = await _upload(owner, session_id, synthetic_png)

    async with _client() as intruder:
        await _session(intruder)
        ofm_id = await _ofm(intruder, "Intruder OFM")
        piece = await _piece(intruder, ofm_id, "Theft")
        response = await intruder.patch(
            f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id}
        )
        assert response.status_code == 403


@pytest.mark.anyio
async def test_cleanup_keeps_files_a_saved_piece_uses(api_env, synthetic_png):
    """TTL cleanup must not delete the media behind a saved project."""
    from api.storage import cleanup_expired_sessions

    async with _client() as client:
        session_id = await _session(client)
        ofm_id = await _ofm(client)
        pinned = await _upload(client, session_id, synthetic_png)
        loose = await _upload(client, session_id, synthetic_png)
        piece = await _piece(client, ofm_id, "Keep me")
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": pinned})

        # Expire everything: max_age_hours=0 puts the cutoff at "now".
        cleanup_expired_sessions(0)

        assert (await client.get(f"/api/v1/files/{pinned}/metadata")).status_code == 200
        assert (await client.get(f"/api/v1/files/{loose}/metadata")).status_code == 404
        assert (await client.get(f"/api/v1/ofms/{ofm_id}/pieces")).json()[0][
            "source_file_id"
        ] == pinned


@pytest.mark.anyio
async def test_deleting_a_piece_frees_its_files(api_env, synthetic_png):
    async with _client() as client:
        session_id = await _session(client)
        ofm_id = await _ofm(client)
        file_id = await _upload(client, session_id, synthetic_png)
        piece = await _piece(client, ofm_id, "Temp")
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

        assert (await client.get("/api/v1/storage")).json()["used_bytes"] > 0

        assert (await client.delete(f"/api/v1/pieces/{piece['id']}")).status_code == 204

        assert (await client.get(f"/api/v1/files/{file_id}/metadata")).status_code == 404
        assert (await client.get("/api/v1/storage")).json()["used_bytes"] == 0


@pytest.mark.anyio
async def test_deleting_the_last_piece_leaves_none(api_env):
    """Removing the only piece must leave zero — nothing recreates one."""
    async with _client() as client:
        await _session(client)
        ofm_id = await _ofm(client)
        piece = await _piece(client, ofm_id, "Only one")

        await client.delete(f"/api/v1/pieces/{piece['id']}")

        assert (await client.get(f"/api/v1/ofms/{ofm_id}/pieces")).json() == []
        assert (await client.get(f"/api/v1/ofms/{ofm_id}/pieces")).json() == []


@pytest.mark.anyio
async def test_deleting_a_piece_keeps_files_another_piece_shares(api_env, synthetic_png):
    async with _client() as client:
        session_id = await _session(client)
        ofm_id = await _ofm(client)
        shared = await _upload(client, session_id, synthetic_png)

        first = await _piece(client, ofm_id, "One")
        second = await _piece(client, ofm_id, "Two")
        await client.patch(f"/api/v1/pieces/{first['id']}", json={"source_file_id": shared})
        await client.patch(f"/api/v1/pieces/{second['id']}", json={"metadata_file_id": shared})

        await client.delete(f"/api/v1/pieces/{first['id']}")

        assert (await client.get(f"/api/v1/files/{shared}/metadata")).status_code == 200


@pytest.mark.anyio
async def test_clearing_a_slot(api_env, synthetic_png):
    """`clear` expresses "empty this slot", which a null field cannot."""
    async with _client() as client:
        session_id = await _session(client)
        ofm_id = await _ofm(client)
        file_id = await _upload(client, session_id, synthetic_png)
        piece = await _piece(client, ofm_id, "Clearable")
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

        updated = (
            await client.patch(f"/api/v1/pieces/{piece['id']}", json={"clear": ["source_file_id"]})
        ).json()
        assert updated["source_file_id"] is None
        assert updated["name"] == "Clearable"


@pytest.mark.anyio
async def test_quota_blocks_uploads_and_reports_usage(api_env, monkeypatch, synthetic_png):
    monkeypatch.setenv("USER_STORAGE_QUOTA_BYTES", "1024")

    async with _client() as client:
        session_id = await _session(client)
        assert (await client.get("/api/v1/storage")).json()["quota_bytes"] == 1024

        big = api_env / "big.png"
        big.write_bytes(synthetic_png.read_bytes() * 50)
        with big.open("rb") as handle:
            response = await client.post(
                f"/api/v1/sessions/{session_id}/files",
                files={"file": (big.name, handle, "application/octet-stream")},
            )
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "quota_exceeded"


@pytest.mark.anyio
async def test_missing_pinned_file_degrades_to_empty_slot(api_env, synthetic_png):
    """A file lost despite pinning should not break the whole piece list."""
    from api.storage import delete_file_by_id

    async with _client() as client:
        session_id = await _session(client)
        ofm_id = await _ofm(client)
        file_id = await _upload(client, session_id, synthetic_png)
        piece = await _piece(client, ofm_id, "Orphan")
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

        delete_file_by_id(file_id)

        listed = (await client.get(f"/api/v1/ofms/{ofm_id}/pieces")).json()
        assert listed[0]["source_file_id"] == file_id
        assert listed[0]["source_file"] is None
