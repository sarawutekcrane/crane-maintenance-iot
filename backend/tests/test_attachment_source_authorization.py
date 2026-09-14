"""Core Demo Fixes Delta REV06 section 14 (P1) — attachment security /
source validation.

The independent REV05 audit found `POST /attachments` and
`GET /attachments/by-source/{source_type}/{source_id}` accepted an
arbitrary `source_id` with no existence check and no authorization check
at all — attachment/source IDs are enumerable, so ID possession alone was
sufficient to read or attach evidence to ANY Repair Request. REV06 adds
`AttachmentService.authorize_source` (wired through
`InspectionService.upload_attachment`/`list_attachments_for_source`,
called by both endpoints) enforcing the minimum safe owner/manager model:
the Repair Request's own reporter, or an actor holding
`can_manage_repair`, may attach/read evidence for it — everyone else is
refused, and an unknown `source_id` or unsupported `source_type` is
refused outright rather than silently accepted.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


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


def _evidence_files() -> dict:
    return {"file": ("evidence.jpg", b"fake-jpeg-bytes", "image/jpeg")}


# ---------------------------------------------------------------------------
# 23 — nonexistent source denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_for_nonexistent_repair_request_source_is_denied(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_REQUEST_EVIDENCE", "source_type": "REPAIR_REQUEST", "source_id": "RRQ-9999"},
        files=_evidence_files(),
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPAIR_REQUEST_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_by_nonexistent_repair_request_source_is_denied(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/attachments/by-source/REPAIR_REQUEST/RRQ-9999", headers=_as("MAINTENANCE")
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPAIR_REQUEST_NOT_FOUND"


# ---------------------------------------------------------------------------
# 24-25 — unauthorized Repair Request attachment read/create denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_reporter_cannot_attach_evidence_to_someone_elses_request(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    response = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_REQUEST_EVIDENCE", "source_type": "REPAIR_REQUEST", "source_id": request_id},
        files=_evidence_files(),
        headers=_as("DRIVER", "user-driver-2"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_unrelated_reporter_cannot_list_evidence_for_someone_elses_request(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    response = await client.get(
        f"/api/v1/attachments/by-source/REPAIR_REQUEST/{request_id}",
        headers=_as("DRIVER", "user-driver-2"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


# ---------------------------------------------------------------------------
# 26 — authorized reporter access allowed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reporting_actor_can_attach_and_list_their_own_request_evidence(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    upload = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_REQUEST_EVIDENCE", "source_type": "REPAIR_REQUEST", "source_id": request_id},
        files=_evidence_files(),
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert upload.status_code == 200
    assert upload.json()["source_type"] == "REPAIR_REQUEST"
    assert upload.json()["source_id"] == request_id

    listing = await client.get(
        f"/api/v1/attachments/by-source/REPAIR_REQUEST/{request_id}",
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


# ---------------------------------------------------------------------------
# 27 — Maintenance access allowed regardless of who reported.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maintenance_can_attach_and_list_evidence_for_any_repair_request(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    upload = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_REQUEST_EVIDENCE", "source_type": "REPAIR_REQUEST", "source_id": request_id},
        files=_evidence_files(),
        headers=_as("MAINTENANCE", "user-maintenance-1"),
    )
    assert upload.status_code == 200

    listing = await client.get(
        f"/api/v1/attachments/by-source/REPAIR_REQUEST/{request_id}", headers=_as("MAINTENANCE")
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


# ---------------------------------------------------------------------------
# 28 — source type/id validation.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_source_type_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_EVIDENCE", "source_type": "REPAIR", "source_id": "RPR-0001"},
        files=_evidence_files(),
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_TYPE_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_source_type_without_source_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_REQUEST_EVIDENCE", "source_type": "REPAIR_REQUEST"},
        files=_evidence_files(),
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_upload_without_any_source_still_works_unchanged(client: AsyncClient) -> None:
    """Every attachment purpose predating REV05 (checklist reference
    image, inspection/PM/repair evidence) never sends `source_type`/
    `source_id` at all — proves the new authorization gate is a true
    no-op for that unchanged, majority code path."""
    response = await client.post(
        "/api/v1/attachments",
        data={"purpose": "INSPECTION_EVIDENCE"},
        files=_evidence_files(),
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 200
    assert response.json()["source_type"] is None
