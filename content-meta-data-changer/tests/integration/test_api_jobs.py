"""Job API integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("JOBS_SYNC", "1")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def _upload(client: AsyncClient, session_id: str, path: Path) -> str:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    response.raise_for_status()
    return response.json()["file_id"]


@pytest.mark.anyio
async def test_transfer_video6(client, video6_target, video6_source):
    session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
    target_id = await _upload(client, session_id, video6_target)
    source_id = await _upload(client, session_id, video6_source)

    response = await client.post(
        "/api/v1/jobs/transfer",
        json={
            "target_file_id": target_id,
            "source_file_id": source_id,
            "output_filename": "video6_with_metadata.mov",
        },
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "succeeded"
    assert job["output_file_id"]

    download = await client.get(f"/api/v1/files/{job['output_file_id']}/download")
    assert download.status_code == 200
    assert len(download.content) > video6_target.stat().st_size


@pytest.mark.anyio
async def test_update_preview(client, video6_target):
    session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
    file_id = await _upload(client, session_id, video6_target)

    response = await client.post(
        "/api/v1/jobs/update-preview",
        json={
            "source_file_id": file_id,
            "output_filename": "video6_preview_updated.mov",
        },
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "succeeded"

    download = await client.get(f"/api/v1/files/{job['output_file_id']}/download")
    assert b"com.apple.quicktime.artwork" in download.content
