"""REV06.1 — independent-audit CRITICAL-1 fix.

The REV06 independent audit found `GET /attachments/{attachment_id}/file`
had no authorization at all, even though REV06 had already added
`AttachmentService.authorize_source` in front of upload/list-by-source:
`attachment_id`s are sequentially enumerable (`ATT-0001`, `ATT-0002`, ...),
so anyone able to reach the API could download ANY attachment's file
bytes by guessing/incrementing the id, entirely bypassing the new gate on
the two endpoints REV06 did fix. `InspectionService.require_readable_attachment`
now runs the exact same `authorize_source` check — keyed off the
attachment's own recorded `source_type`/`source_id` — before any file
content is read from storage.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


def _evidence_files() -> dict:
    return {"file": ("evidence.jpg", b"fake-jpeg-bytes", "image/jpeg")}


async def _submit_repair_request(
    client: AsyncClient, reporter_user_id: str = "user-driver-1"
) -> str:
    response = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "มีเสียงดังผิดปกติ"},
        headers=_as("DRIVER", reporter_user_id),
    )
    assert response.status_code == 200
    return response.json()["request"]["repair_request_id"]


async def _upload_repair_request_evidence(
    client: AsyncClient, source_id: str, uploader_headers: dict[str, str]
) -> str:
    response = await client.post(
        "/api/v1/attachments",
        data={
            "purpose": "REPAIR_REQUEST_EVIDENCE",
            "source_type": "REPAIR_REQUEST",
            "source_id": source_id,
        },
        files=_evidence_files(),
        headers=uploader_headers,
    )
    assert response.status_code == 200
    return response.json()["attachment_id"]


# ---------------------------------------------------------------------------
# 1 — nonexistent attachment ID never returns a file.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_of_nonexistent_attachment_is_denied(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/attachments/ATT-9999/file", headers=_as("MAINTENANCE")
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# 3/6 — an unrelated reporter cannot download another Repair Request's
# evidence merely by knowing/guessing its (sequential) attachment_id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_reporter_cannot_download_someone_elses_request_evidence(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    attachment_id = await _upload_repair_request_evidence(
        client, request_id, _as("DRIVER", "user-driver-1")
    )

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("DRIVER", "user-driver-2")
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"
    # The 403 must carry no file content.
    assert response.content == b"" or b"fake-jpeg-bytes" not in response.content


@pytest.mark.asyncio
async def test_guessing_a_sequential_attachment_id_does_not_bypass_source_authorization(
    client: AsyncClient,
) -> None:
    """Two different Repair Requests, two different reporters, two
    sequentially-numbered attachments — the second reporter must not be
    able to read the first reporter's evidence just by incrementing the id
    (or vice versa)."""
    request_a = await _submit_repair_request(client, reporter_user_id="user-driver-a")
    attachment_a = await _upload_repair_request_evidence(
        client, request_a, _as("DRIVER", "user-driver-a")
    )
    request_b = await _submit_repair_request(client, reporter_user_id="user-driver-b")
    attachment_b = await _upload_repair_request_evidence(
        client, request_b, _as("DRIVER", "user-driver-b")
    )
    assert attachment_a != attachment_b

    cross_read_a = await client.get(
        f"/api/v1/attachments/{attachment_a}/file", headers=_as("DRIVER", "user-driver-b")
    )
    assert cross_read_a.status_code == 403

    cross_read_b = await client.get(
        f"/api/v1/attachments/{attachment_b}/file", headers=_as("DRIVER", "user-driver-a")
    )
    assert cross_read_b.status_code == 403


# ---------------------------------------------------------------------------
# 4 — the reporting actor can download their own attachment.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reporting_actor_can_download_their_own_request_evidence(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    attachment_id = await _upload_repair_request_evidence(
        client, request_id, _as("DRIVER", "user-driver-1")
    )

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("DRIVER", "user-driver-1")
    )
    assert response.status_code == 200
    assert response.content == b"fake-jpeg-bytes"


# ---------------------------------------------------------------------------
# 5 — Maintenance can download evidence for any Repair Request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maintenance_can_download_evidence_for_any_repair_request(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    attachment_id = await _upload_repair_request_evidence(
        client, request_id, _as("DRIVER", "user-driver-1")
    )

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("MAINTENANCE")
    )
    assert response.status_code == 200
    assert response.content == b"fake-jpeg-bytes"


# ---------------------------------------------------------------------------
# 9 — listing authorization and download authorization are consistent
# (both call the exact same `authorize_source` gate).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_and_download_authorization_agree(client: AsyncClient) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    attachment_id = await _upload_repair_request_evidence(
        client, request_id, _as("DRIVER", "user-driver-1")
    )

    for headers, expect_allowed in (
        (_as("DRIVER", "user-driver-1"), True),
        (_as("MAINTENANCE"), True),
        (_as("DRIVER", "user-driver-2"), False),
    ):
        list_response = await client.get(
            f"/api/v1/attachments/by-source/REPAIR_REQUEST/{request_id}", headers=headers
        )
        download_response = await client.get(
            f"/api/v1/attachments/{attachment_id}/file", headers=headers
        )
        list_allowed = list_response.status_code == 200
        download_allowed = download_response.status_code == 200
        assert list_allowed == expect_allowed
        assert download_allowed == expect_allowed
        assert list_allowed == download_allowed


# ---------------------------------------------------------------------------
# 10 — authorization runs before any storage/file exposure. Proven by the
# 403 responses above never containing the uploaded bytes; this test makes
# the ordering explicit by patching the storage read to fail loudly if it
# is ever reached for an unauthorized request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorization_runs_before_storage_is_ever_read(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage.local import LocalFileStorageProvider

    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    attachment_id = await _upload_repair_request_evidence(
        client, request_id, _as("DRIVER", "user-driver-1")
    )

    async def _boom(self, storage_ref: str):  # pragma: no cover - must never run
        raise AssertionError(
            "storage.read() was reached for an unauthorized download — "
            "authorization must run first"
        )

    monkeypatch.setattr(LocalFileStorageProvider, "read", _boom)

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("DRIVER", "user-driver-2")
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Unchanged behavior: attachments with no source_type at all (checklist
# reference image, inspection/PM/repair evidence — every purpose predating
# REV05, which link back via their owner's own attachment_ids field rather
# than this join) remain downloadable exactly as before REV06.1 — this
# fix does not invent a new authorization policy for them.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_without_any_source_still_works_unchanged(client: AsyncClient) -> None:
    upload = await client.post(
        "/api/v1/attachments",
        data={"purpose": "INSPECTION_EVIDENCE"},
        files=_evidence_files(),
        headers=_as("TECHNICIAN"),
    )
    assert upload.status_code == 200
    attachment_id = upload.json()["attachment_id"]

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("DRIVER", "someone-else")
    )
    assert response.status_code == 200
    assert response.content == b"fake-jpeg-bytes"
