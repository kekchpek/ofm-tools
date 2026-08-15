"""Upload sessions must stay private to the client that created them.

These cover the anonymous (no OAuth configured) path, where ownership is
carried by the ``cmc_client`` cookie rather than a signed-in user.
"""

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


def _new_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _upload(client: AsyncClient, session_id: str, path: Path) -> str:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    response.raise_for_status()
    return response.json()["file_id"]


@pytest.mark.anyio
async def test_session_creation_sets_client_cookie(api_env):
    async with _new_client() as client:
        response = await client.post("/api/v1/sessions")
        assert response.status_code == 201
        assert "cmc_client" in response.cookies


@pytest.mark.anyio
async def test_other_client_cannot_read_file(api_env, synthetic_png):
    async with _new_client() as owner:
        session_id = (await owner.post("/api/v1/sessions")).json()["session_id"]
        file_id = await _upload(owner, session_id, synthetic_png)
        assert (await owner.get(f"/api/v1/files/{file_id}/metadata")).status_code == 200

    # A second browser knows the file id but carries a different cookie.
    async with _new_client() as intruder:
        for endpoint in ("metadata", "layout", "download", "preview.jpg", "unknown-headers"):
            response = await intruder.get(f"/api/v1/files/{file_id}/{endpoint}")
            assert response.status_code == 403, f"{endpoint} leaked to another client"


@pytest.mark.anyio
async def test_other_client_cannot_upload_into_session(api_env, synthetic_png):
    async with _new_client() as owner:
        session_id = (await owner.post("/api/v1/sessions")).json()["session_id"]

    async with _new_client() as intruder:
        with synthetic_png.open("rb") as handle:
            response = await intruder.post(
                f"/api/v1/sessions/{session_id}/files",
                files={"file": (synthetic_png.name, handle, "application/octet-stream")},
            )
        assert response.status_code == 403


@pytest.mark.anyio
async def test_other_client_cannot_start_job_on_foreign_file(api_env, synthetic_png):
    async with _new_client() as owner:
        session_id = (await owner.post("/api/v1/sessions")).json()["session_id"]
        file_id = await _upload(owner, session_id, synthetic_png)

    async with _new_client() as intruder:
        response = await intruder.post(
            "/api/v1/jobs/convert",
            json={"source_file_id": file_id, "output_filename": "stolen.jpg", "target": "jpg"},
        )
        assert response.status_code == 403


@pytest.mark.anyio
async def test_other_client_cannot_read_job_status(api_env, synthetic_png):
    async with _new_client() as owner:
        session_id = (await owner.post("/api/v1/sessions")).json()["session_id"]
        file_id = await _upload(owner, session_id, synthetic_png)
        job = (
            await owner.post(
                "/api/v1/jobs/convert",
                json={"source_file_id": file_id, "output_filename": "converted.jpg", "target": "jpg"},
            )
        ).json()
        assert job["status"] == "succeeded"

    async with _new_client() as intruder:
        response = await intruder.get(f"/api/v1/jobs/{job['id']}")
        assert response.status_code == 403


@pytest.mark.anyio
async def test_unknown_session_is_rejected(api_env):
    async with _new_client() as client:
        await client.post("/api/v1/sessions")
        response = await client.post(
            "/api/v1/sessions/00000000-0000-0000-0000-000000000000/files",
            files={"file": ("x.bin", b"data", "application/octet-stream")},
        )
        assert response.status_code == 403


@pytest.mark.anyio
async def test_owner_keeps_access_across_sessions(api_env, synthetic_png):
    """A second session created by the same client can still be reached."""
    async with _new_client() as owner:
        first = (await owner.post("/api/v1/sessions")).json()["session_id"]
        second = (await owner.post("/api/v1/sessions")).json()["session_id"]
        assert first != second
        for session_id in (first, second):
            file_id = await _upload(owner, session_id, synthetic_png)
            assert (await owner.get(f"/api/v1/files/{file_id}/metadata")).status_code == 200
