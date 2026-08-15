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
async def test_factory_job_combines_payload_and_metadata(client, tmp_path):
    """End to end: upload two images, generate a result, download it."""
    from PIL import Image

    source = tmp_path / "source.png"
    Image.new("RGB", (64, 48), (220, 30, 70)).save(source, format="PNG")

    donor = tmp_path / "donor.jpg"
    exif = Image.Exif()
    exif[271] = "ACME"
    Image.new("RGB", (16, 16), (0, 0, 255)).save(donor, format="JPEG", exif=exif)

    session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
    source_id = await _upload(client, session_id, source)
    donor_id = await _upload(client, session_id, donor)

    response = await client.post(
        "/api/v1/jobs/factory",
        json={"source_file_id": source_id, "metadata_file_id": donor_id},
    )
    assert response.status_code == 202
    job = response.json()
    assert job["type"] == "factory"
    assert job["status"] == "succeeded", job.get("error")

    download = await client.get(f"/api/v1/files/{job['output_file_id']}/download")
    assert download.status_code == 200

    result = tmp_path / "result.jpg"
    result.write_bytes(download.content)
    with Image.open(result) as image:
        assert image.size == (64, 48)  # payload from source
        assert image.format == "JPEG"  # format from donor
        assert image.getexif().get(271) == "ACME"  # metadata from donor


@pytest.mark.anyio
async def test_factory_job_honours_custom_output_name(client, tmp_path, synthetic_png):
    """A user-supplied name is used, but the donor's extension always wins."""
    from PIL import Image

    donor = tmp_path / "donor.jpg"
    Image.new("RGB", (16, 16), (0, 0, 255)).save(donor, format="JPEG")

    session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
    source_id = await _upload(client, session_id, synthetic_png)
    donor_id = await _upload(client, session_id, donor)

    response = await client.post(
        "/api/v1/jobs/factory",
        json={
            "source_file_id": source_id,
            "metadata_file_id": donor_id,
            # Deliberately the wrong extension for a JPEG donor.
            "output_filename": "my holiday shot.png",
        },
    )
    job = response.json()
    assert job["status"] == "succeeded", job.get("error")

    download = await client.get(f"/api/v1/files/{job['output_file_id']}/download")
    assert 'filename="my holiday shot.jpg"' in download.headers["content-disposition"]


@pytest.mark.anyio
async def test_factory_job_rejects_mixed_media_kinds(client, tmp_path, synthetic_png):
    fake_video = tmp_path / "donor.mov"
    fake_video.write_bytes(b"\x00" * 64)

    session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
    source_id = await _upload(client, session_id, synthetic_png)
    donor_id = await _upload(client, session_id, fake_video)

    response = await client.post(
        "/api/v1/jobs/factory",
        json={"source_file_id": source_id, "metadata_file_id": donor_id},
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "failed"
    assert "same media type" in (job["error"] or "")


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
