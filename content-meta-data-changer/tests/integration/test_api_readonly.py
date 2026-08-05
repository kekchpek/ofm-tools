"""Read-only API integration tests."""

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
async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_upload_and_inspect(client, video6_target):
    session = await client.post("/api/v1/sessions")
    session_id = session.json()["session_id"]
    file_id = await _upload(client, session_id, video6_target)

    metadata = await client.get(f"/api/v1/files/{file_id}/metadata")
    assert metadata.status_code == 200
    assert metadata.json()["media_kind"] == "video"

    layout = await client.get(f"/api/v1/files/{file_id}/layout")
    assert layout.status_code == 200
    assert len(layout.json()["segments"]) > 0

    preview = await client.get(f"/api/v1/files/{file_id}/preview.jpg")
    assert preview.status_code == 200
    assert preview.content[:3] == b"\xff\xd8\xff"
