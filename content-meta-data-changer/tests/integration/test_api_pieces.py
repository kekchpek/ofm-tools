"""Saved content pieces: persistence, ownership, file pinning, and quota."""

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
        piece = (await client.post("/api/v1/pieces", json={"name": "Beach set"})).json()
        file_id = await _upload(client, session_id, synthetic_png)
        await client.patch(
            f"/api/v1/pieces/{piece['id']}",
            json={"source_file_id": file_id, "output_stem": "beach"},
        )

        # A brand new upload session stands in for a page reload.
        await _session(client)
        pieces = (await client.get("/api/v1/pieces")).json()

    assert len(pieces) == 1
    assert pieces[0]["name"] == "Beach set"
    assert pieces[0]["output_stem"] == "beach"
    assert pieces[0]["source_file_id"] == file_id
    # The file itself is resolved so the UI can show name and size immediately.
    assert pieces[0]["source_file"]["filename"] == synthetic_png.name


@pytest.mark.anyio
async def test_pieces_are_private_to_their_owner(api_env):
    async with _client() as owner:
        await _session(owner)
        piece = (await owner.post("/api/v1/pieces", json={"name": "Mine"})).json()

    async with _client() as intruder:
        await _session(intruder)
        assert (await intruder.get("/api/v1/pieces")).json() == []
        assert (await intruder.patch(f"/api/v1/pieces/{piece['id']}", json={"name": "Yours"})).status_code == 404
        assert (await intruder.delete(f"/api/v1/pieces/{piece['id']}")).status_code == 404


@pytest.mark.anyio
async def test_piece_cannot_point_at_someone_elses_file(api_env, synthetic_png):
    async with _client() as owner:
        session_id = await _session(owner)
        file_id = await _upload(owner, session_id, synthetic_png)

    async with _client() as intruder:
        await _session(intruder)
        piece = (await intruder.post("/api/v1/pieces", json={"name": "Theft"})).json()
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
        pinned = await _upload(client, session_id, synthetic_png)
        loose = await _upload(client, session_id, synthetic_png)
        piece = (await client.post("/api/v1/pieces", json={"name": "Keep me"})).json()
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": pinned})

        # Expire everything: max_age_hours=0 puts the cutoff at "now".
        cleanup_expired_sessions(0)

        assert (await client.get(f"/api/v1/files/{pinned}/metadata")).status_code == 200
        assert (await client.get(f"/api/v1/files/{loose}/metadata")).status_code == 404
        assert (await client.get("/api/v1/pieces")).json()[0]["source_file_id"] == pinned


@pytest.mark.anyio
async def test_deleting_a_piece_frees_its_files(api_env, synthetic_png):
    async with _client() as client:
        session_id = await _session(client)
        file_id = await _upload(client, session_id, synthetic_png)
        piece = (await client.post("/api/v1/pieces", json={"name": "Temp"})).json()
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

        before = (await client.get("/api/v1/storage")).json()["used_bytes"]
        assert before > 0

        assert (await client.delete(f"/api/v1/pieces/{piece['id']}")).status_code == 204

        assert (await client.get(f"/api/v1/files/{file_id}/metadata")).status_code == 404
        assert (await client.get("/api/v1/storage")).json()["used_bytes"] == 0


@pytest.mark.anyio
async def test_deleting_a_piece_keeps_files_another_piece_shares(api_env, synthetic_png):
    async with _client() as client:
        session_id = await _session(client)
        shared = await _upload(client, session_id, synthetic_png)

        first = (await client.post("/api/v1/pieces", json={"name": "One"})).json()
        second = (await client.post("/api/v1/pieces", json={"name": "Two"})).json()
        await client.patch(f"/api/v1/pieces/{first['id']}", json={"source_file_id": shared})
        await client.patch(f"/api/v1/pieces/{second['id']}", json={"metadata_file_id": shared})

        await client.delete(f"/api/v1/pieces/{first['id']}")

        assert (await client.get(f"/api/v1/files/{shared}/metadata")).status_code == 200


@pytest.mark.anyio
async def test_clearing_a_slot(api_env, synthetic_png):
    """`clear` expresses "empty this slot", which a null field cannot."""
    async with _client() as client:
        session_id = await _session(client)
        file_id = await _upload(client, session_id, synthetic_png)
        piece = (await client.post("/api/v1/pieces", json={"name": "Clearable"})).json()
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
        usage = (await client.get("/api/v1/storage")).json()
        assert usage["quota_bytes"] == 1024

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
        file_id = await _upload(client, session_id, synthetic_png)
        piece = (await client.post("/api/v1/pieces", json={"name": "Orphan"})).json()
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

        delete_file_by_id(file_id)

        listed = (await client.get("/api/v1/pieces")).json()
        assert listed[0]["source_file_id"] == file_id
        assert listed[0]["source_file"] is None
