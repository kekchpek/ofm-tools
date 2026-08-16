"""OFMs: multiple per account, invitations, and the owner-only delete rule.

These run with OAuth enabled (via a stubbed signed-in user) because membership
is keyed by email, which only exists for real accounts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import api.auth as auth_module
from api.database import UserRecord, initialize_database
from api.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("JOBS_SYNC", "1")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    initialize_database()
    return tmp_path


def _user(email: str, name: str) -> UserRecord:
    from api.database import upsert_google_user

    return upsert_google_user(
        google_sub=f"sub-{email}", email=email, name=name, picture_url=None
    )


def _client_as(user: UserRecord) -> AsyncClient:
    """A client whose requests resolve to ``user``, bypassing the OAuth dance."""
    app.dependency_overrides[auth_module.get_current_user_optional] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _ofm(client: AsyncClient, name: str) -> dict:
    response = await client.post("/api/v1/ofms", json={"name": name})
    response.raise_for_status()
    return response.json()


@pytest.mark.anyio
async def test_account_can_hold_several_ofms(api_env):
    owner = _user("owner@example.com", "Owner")
    async with _client_as(owner) as client:
        await _ofm(client, "Summer")
        await _ofm(client, "Winter")
        listed = (await client.get("/api/v1/ofms")).json()

    assert [o["name"] for o in listed] == ["Summer", "Winter"]
    assert all(o["is_owner"] for o in listed)
    assert all(o["can_delete"] for o in listed)


@pytest.mark.anyio
async def test_creator_becomes_owner_with_a_membership_row(api_env):
    owner = _user("owner@example.com", "Owner")
    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Solo")
        members = (await client.get(f"/api/v1/ofms/{ofm['id']}/members")).json()

    assert len(members) == 1
    assert members[0]["email"] == "owner@example.com"
    assert members[0]["role"] == "owner"
    assert members[0]["accepted"] is True


@pytest.mark.anyio
async def test_invited_member_can_edit_but_not_delete(api_env):
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")

    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Shared")
        invite = await client.post(
            f"/api/v1/ofms/{ofm['id']}/members", json={"email": "guest@example.com"}
        )
        assert invite.status_code == 201
        assert invite.json()["role"] == "editor"

    async with _client_as(guest) as client:
        listed = (await client.get("/api/v1/ofms")).json()
        assert [o["name"] for o in listed] == ["Shared"]
        assert listed[0]["is_owner"] is False
        assert listed[0]["can_delete"] is False

        # Everything except deletion is open to members.
        assert (await client.patch(f"/api/v1/ofms/{ofm['id']}", json={"name": "Renamed"})).status_code == 200
        piece = await client.post(f"/api/v1/ofms/{ofm['id']}/pieces", json={"name": "Guest piece"})
        assert piece.status_code == 201
        assert (await client.delete(f"/api/v1/pieces/{piece.json()['id']}")).status_code == 204

        # Deleting the OFM is owner-only.
        denied = await client.delete(f"/api/v1/ofms/{ofm['id']}")
        assert denied.status_code == 403
        assert denied.json()["detail"]["error"] == "Only the owner of this OFM can delete it."


@pytest.mark.anyio
async def test_owner_can_delete_and_it_disappears_for_members(api_env):
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")

    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Doomed")
        await client.post(f"/api/v1/ofms/{ofm['id']}/members", json={"email": "guest@example.com"})
        assert (await client.delete(f"/api/v1/ofms/{ofm['id']}")).status_code == 204

    async with _client_as(guest) as client:
        assert (await client.get("/api/v1/ofms")).json() == []
        assert (await client.get(f"/api/v1/ofms/{ofm['id']}")).status_code == 404


@pytest.mark.anyio
async def test_invitation_works_before_the_invitee_has_an_account(api_env):
    """Invites are keyed by email, so they can precede the person signing up."""
    owner = _user("owner@example.com", "Owner")
    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Future")
        member = (
            await client.post(
                f"/api/v1/ofms/{ofm['id']}/members", json={"email": "newcomer@example.com"}
            )
        ).json()
        assert member["accepted"] is False  # nobody bound yet

    # The invitee signs in for the first time.
    newcomer = _user("newcomer@example.com", "Newcomer")
    async with _client_as(newcomer) as client:
        assert [o["name"] for o in (await client.get("/api/v1/ofms")).json()] == ["Future"]

    async with _client_as(owner) as client:
        members = (await client.get(f"/api/v1/ofms/{ofm['id']}/members")).json()
    accepted = {m["email"]: m["accepted"] for m in members}
    assert accepted["newcomer@example.com"] is True


@pytest.mark.anyio
async def test_invitations_are_case_insensitive_and_idempotent(api_env):
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")
    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Casing")
        first = await client.post(
            f"/api/v1/ofms/{ofm['id']}/members", json={"email": "Guest@Example.com"}
        )
        second = await client.post(
            f"/api/v1/ofms/{ofm['id']}/members", json={"email": "guest@example.com"}
        )
        assert first.json()["id"] == second.json()["id"]
        assert len((await client.get(f"/api/v1/ofms/{ofm['id']}/members")).json()) == 2

    async with _client_as(guest) as client:
        assert len((await client.get("/api/v1/ofms")).json()) == 1


@pytest.mark.anyio
async def test_owner_cannot_be_removed_from_their_own_ofm(api_env):
    owner = _user("owner@example.com", "Owner")
    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Orphan risk")
        members = (await client.get(f"/api/v1/ofms/{ofm['id']}/members")).json()
        response = await client.delete(f"/api/v1/ofms/{ofm['id']}/members/{members[0]['id']}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "cannot_remove_owner"


@pytest.mark.anyio
async def test_removed_member_loses_access(api_env):
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")
    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Revoked")
        member = (
            await client.post(
                f"/api/v1/ofms/{ofm['id']}/members", json={"email": "guest@example.com"}
            )
        ).json()
        assert (
            await client.delete(f"/api/v1/ofms/{ofm['id']}/members/{member['id']}")
        ).status_code == 204

    async with _client_as(guest) as client:
        assert (await client.get("/api/v1/ofms")).json() == []
        assert (await client.get(f"/api/v1/ofms/{ofm['id']}/pieces")).status_code == 404


@pytest.mark.anyio
async def test_members_can_read_each_others_uploaded_files(api_env, synthetic_png):
    """Uploads live in the uploader's session; sharing must reach across that."""
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")

    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Collab")
        await client.post(f"/api/v1/ofms/{ofm['id']}/members", json={"email": "guest@example.com"})
        session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
        with synthetic_png.open("rb") as handle:
            file_id = (
                await client.post(
                    f"/api/v1/sessions/{session_id}/files",
                    files={"file": (synthetic_png.name, handle, "image/png")},
                )
            ).json()["file_id"]
        piece = (
            await client.post(f"/api/v1/ofms/{ofm['id']}/pieces", json={"name": "Shared piece"})
        ).json()
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

    async with _client_as(guest) as client:
        # The guest never uploaded this file, but it is in their OFM.
        assert (await client.get(f"/api/v1/files/{file_id}/metadata")).status_code == 200
        assert (await client.get(f"/api/v1/files/{file_id}/download")).status_code == 200
        listed = (await client.get(f"/api/v1/ofms/{ofm['id']}/pieces")).json()
        assert listed[0]["source_file"]["filename"] == synthetic_png.name


@pytest.mark.anyio
async def test_outsider_still_cannot_read_a_shared_file(api_env, synthetic_png):
    owner = _user("owner@example.com", "Owner")
    outsider = _user("nobody@example.com", "Nobody")

    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Closed")
        session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
        with synthetic_png.open("rb") as handle:
            file_id = (
                await client.post(
                    f"/api/v1/sessions/{session_id}/files",
                    files={"file": (synthetic_png.name, handle, "image/png")},
                )
            ).json()["file_id"]
        piece = (
            await client.post(f"/api/v1/ofms/{ofm['id']}/pieces", json={"name": "Private piece"})
        ).json()
        await client.patch(f"/api/v1/pieces/{piece['id']}", json={"source_file_id": file_id})

    async with _client_as(outsider) as client:
        assert (await client.get(f"/api/v1/files/{file_id}/metadata")).status_code == 403


@pytest.mark.anyio
async def test_member_can_generate_from_a_teammates_upload(api_env, synthetic_png):
    """A job's result must land in the caller's session, not the uploader's.

    Otherwise the teammate who ran the job cannot attach the output: it lives in
    someone else's session and no piece references it yet, so neither ownership
    nor OFM sharing authorizes them.
    """
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")

    donor = api_env / "donor.jpg"
    from PIL import Image

    Image.new("RGB", (16, 16), (0, 0, 255)).save(donor, format="JPEG")

    async with _client_as(owner) as client:
        ofm = await _ofm(client, "Collab")
        await client.post(f"/api/v1/ofms/{ofm['id']}/members", json={"email": "guest@example.com"})
        session_id = (await client.post("/api/v1/sessions")).json()["session_id"]
        uploaded = {}
        for field, path in (("source_file_id", synthetic_png), ("metadata_file_id", donor)):
            with path.open("rb") as handle:
                uploaded[field] = (
                    await client.post(
                        f"/api/v1/sessions/{session_id}/files",
                        files={"file": (path.name, handle, "application/octet-stream")},
                    )
                ).json()["file_id"]
        piece = (
            await client.post(f"/api/v1/ofms/{ofm['id']}/pieces", json={"name": "Shared"})
        ).json()
        await client.patch(f"/api/v1/pieces/{piece['id']}", json=uploaded)

    async with _client_as(guest) as client:
        guest_session = (await client.post("/api/v1/sessions")).json()["session_id"]
        job = (
            await client.post(
                "/api/v1/jobs/factory",
                json={
                    **uploaded,
                    "output_filename": "hero",
                    "output_session_id": guest_session,
                },
            )
        ).json()
        assert job["status"] == "succeeded", job.get("error")

        attached = await client.patch(
            f"/api/v1/pieces/{piece['id']}",
            json={"result_file_id": job["output_file_id"], "result_filename": "hero.jpg"},
        )
        assert attached.status_code == 200, attached.text

    # And the owner can read what the guest produced.
    async with _client_as(owner) as client:
        listed = (await client.get(f"/api/v1/ofms/{ofm['id']}/pieces")).json()
        assert listed[0]["result_filename"] == "hero.jpg"
        assert (
            await client.get(f"/api/v1/files/{listed[0]['result_file_id']}/download")
        ).status_code == 200


@pytest.mark.anyio
async def test_cannot_write_a_job_result_into_someone_elses_session(api_env, synthetic_png):
    owner = _user("owner@example.com", "Owner")
    guest = _user("guest@example.com", "Guest")

    async with _client_as(owner) as client:
        owner_session = (await client.post("/api/v1/sessions")).json()["session_id"]
        with synthetic_png.open("rb") as handle:
            file_id = (
                await client.post(
                    f"/api/v1/sessions/{owner_session}/files",
                    files={"file": (synthetic_png.name, handle, "image/png")},
                )
            ).json()["file_id"]

    async with _client_as(guest) as client:
        await client.post("/api/v1/sessions")
        response = await client.post(
            "/api/v1/jobs/factory",
            json={
                "source_file_id": file_id,
                "metadata_file_id": file_id,
                "output_session_id": owner_session,
            },
        )
        assert response.status_code == 403
