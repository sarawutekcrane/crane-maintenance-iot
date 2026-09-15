"""REV06.2 delta — final independent audit HIGH finding fix.

The REV06.1 audit found `authorize_source` was a no-op for every
attachment purpose but `REPAIR_REQUEST_EVIDENCE` (checklist reference
image, inspection/PM/repair evidence), since none of them carried a
`source_type`/`source_id` at all — attachment_id possession alone was
sufficient to download any of them. REV06.2 gives each purpose a real,
durable owning record (persisted at upload time) and reuses the exact same
authorization each owning record's own action endpoints already enforce:

- REPAIR_EVIDENCE:      source_type=REPAIR, source_id=repair_id — active
                        PRIMARY/COLLABORATOR or can_manage_repair (mirrors
                        `add_repair_action`/`add_repair_part`).
- PM_EVIDENCE:          source_type=PM_WORK_ORDER, source_id=pm_work_order_id
                        — assigned PRIMARY/COLLABORATOR or can_manage_pm
                        (mirrors `submit_pm_task_result`).
- INSPECTION_EVIDENCE:  source_type=INSPECTION_VEHICLE/INSPECTION_EQUIPMENT,
                        source_id=asset_id (no Inspection id exists yet at
                        upload time) — requires can_record_inspection.
- CHECKLIST_REFERENCE_IMAGE: master/reference content with no per-instance
                        owner — requires can_view instead (see
                        AttachmentService.authorize_source).

This file covers the REV06.2 test matrix (section 12 of the delta spec)
for the three newly-source-required purposes; CHECKLIST_REFERENCE_IMAGE
and the legacy/source-less fail-closed cases are covered in
test_attachment_source_authorization.py and
test_rev061_attachment_download_authorization.py.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


def _evidence_files() -> dict:
    return {"file": ("evidence.jpg", b"fake-jpeg-bytes", "image/jpeg")}


async def _open_repair(client: AsyncClient, vehicle_id: str = "VEH-1046") -> str:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    return response.json()["repair"]["repair_id"]


async def _assign_repair(client: AsyncClient, repair_id: str, primary: str | None) -> None:
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": primary, "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200


async def _open_pm_work_order(client: AsyncClient, vehicle_id: str = "VEH-1046") -> str:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": vehicle_id},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    return response.json()["work_order"]["pm_work_order_id"]


async def _assign_pm(client: AsyncClient, work_order_id: str, primary: str | None) -> None:
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": primary, "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200


async def _upload(
    client: AsyncClient, purpose: str, source_type: str | None, source_id: str | None, headers: dict
):
    data: dict[str, str] = {"purpose": purpose}
    if source_type is not None:
        data["source_type"] = source_type
    if source_id is not None:
        data["source_id"] = source_id
    return await client.post(
        "/api/v1/attachments", data=data, files=_evidence_files(), headers=headers
    )


# ---------------------------------------------------------------------------
# REPAIR_EVIDENCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_evidence_assigned_primary_can_upload_and_download(
    client: AsyncClient,
) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")

    upload = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "user-tech-1")
    )
    assert upload.status_code == 200
    attachment_id = upload.json()["attachment_id"]

    download = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("TECHNICIAN", "user-tech-1")
    )
    assert download.status_code == 200
    assert download.content == b"fake-jpeg-bytes"


@pytest.mark.asyncio
async def test_repair_evidence_unrelated_technician_is_denied(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")

    upload = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "user-unrelated")
    )
    assert upload.status_code == 403
    assert upload.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_repair_evidence_maintenance_can_upload_and_download_any_repair(
    client: AsyncClient,
) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")

    upload = await _upload(client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("MAINTENANCE"))
    assert upload.status_code == 200
    attachment_id = upload.json()["attachment_id"]

    download = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("MAINTENANCE")
    )
    assert download.status_code == 200


@pytest.mark.asyncio
async def test_repair_evidence_guessed_attachment_id_is_denied_to_unrelated_technician(
    client: AsyncClient,
) -> None:
    """Enumeration: a real, sequentially-issued attachment_id belonging to
    a repair the caller is not assigned to must not be downloadable."""
    repair_a = await _open_repair(client, "VEH-1046")
    repair_b = await _open_repair(client, "VEH-1047")
    await _assign_repair(client, repair_a, "user-tech-a")
    await _assign_repair(client, repair_b, "user-tech-b")

    upload_a = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_a, _as("TECHNICIAN", "user-tech-a")
    )
    attachment_a = upload_a.json()["attachment_id"]

    cross_read = await client.get(
        f"/api/v1/attachments/{attachment_a}/file", headers=_as("TECHNICIAN", "user-tech-b")
    )
    assert cross_read.status_code == 403


@pytest.mark.asyncio
async def test_repair_evidence_ended_primary_loses_access_new_primary_gains_it(
    client: AsyncClient,
) -> None:
    """Reassignment must be honored: after Maintenance moves the PRIMARY
    from user-tech-1 to user-tech-2, only user-tech-2 can still
    upload/download — the stale (now-ended) assignment must not linger."""
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")
    upload = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "user-tech-1")
    )
    attachment_id = upload.json()["attachment_id"]

    await _assign_repair(client, repair_id, "user-tech-2")

    now_denied = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("TECHNICIAN", "user-tech-1")
    )
    assert now_denied.status_code == 403

    now_allowed = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("TECHNICIAN", "user-tech-2")
    )
    assert now_allowed.status_code == 200


@pytest.mark.asyncio
async def test_repair_evidence_nonexistent_source_is_rejected(client: AsyncClient) -> None:
    response = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", "RPR-9999", _as("MAINTENANCE")
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPAIR_NOT_FOUND"


@pytest.mark.asyncio
async def test_repair_evidence_missing_source_is_rejected(client: AsyncClient) -> None:
    response = await _upload(client, "REPAIR_EVIDENCE", None, None, _as("MAINTENANCE"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_REQUIRED"


# ---------------------------------------------------------------------------
# PM_EVIDENCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm_evidence_assigned_primary_can_upload_and_download(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    await _assign_pm(client, work_order_id, "user-tech-1")

    upload = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("TECHNICIAN", "user-tech-1")
    )
    assert upload.status_code == 200
    attachment_id = upload.json()["attachment_id"]

    download = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("TECHNICIAN", "user-tech-1")
    )
    assert download.status_code == 200


@pytest.mark.asyncio
async def test_pm_evidence_unrelated_technician_is_denied(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    await _assign_pm(client, work_order_id, "user-tech-1")

    upload = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("TECHNICIAN", "user-unrelated")
    )
    assert upload.status_code == 403
    assert upload.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_pm_evidence_maintenance_can_upload_and_download_any_work_order(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_pm_work_order(client)
    await _assign_pm(client, work_order_id, "user-tech-1")

    upload = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("MAINTENANCE")
    )
    assert upload.status_code == 200
    download = await client.get(
        f"/api/v1/attachments/{upload.json()['attachment_id']}/file", headers=_as("MAINTENANCE")
    )
    assert download.status_code == 200


@pytest.mark.asyncio
async def test_pm_evidence_nonexistent_source_is_rejected(client: AsyncClient) -> None:
    response = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", "PMWO-9999", _as("MAINTENANCE")
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_WORK_ORDER_NOT_FOUND"


@pytest.mark.asyncio
async def test_pm_evidence_missing_source_is_rejected(client: AsyncClient) -> None:
    response = await _upload(client, "PM_EVIDENCE", None, None, _as("MAINTENANCE"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_REQUIRED"


@pytest.mark.asyncio
async def test_pm_evidence_mismatched_source_type_is_rejected(client: AsyncClient) -> None:
    """A real Repair id given under the PM_WORK_ORDER source type must not
    be silently accepted (cross-domain id confusion)."""
    repair_id = await _open_repair(client)
    response = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", repair_id, _as("MAINTENANCE")
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_WORK_ORDER_NOT_FOUND"


# ---------------------------------------------------------------------------
# INSPECTION_EVIDENCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inspection_evidence_any_recognized_role_can_upload_and_download(
    client: AsyncClient,
) -> None:
    upload = await _upload(
        client, "INSPECTION_EVIDENCE", "INSPECTION_VEHICLE", "VEH-1046", _as("TECHNICIAN")
    )
    assert upload.status_code == 200
    download = await client.get(
        f"/api/v1/attachments/{upload.json()['attachment_id']}/file",
        headers=_as("DRIVER", "someone-else"),
    )
    assert download.status_code == 200


@pytest.mark.asyncio
async def test_inspection_evidence_equipment_source_works(client: AsyncClient) -> None:
    upload = await _upload(
        client, "INSPECTION_EVIDENCE", "INSPECTION_EQUIPMENT", "EQP-0001", _as("TECHNICIAN")
    )
    assert upload.status_code == 200


@pytest.mark.asyncio
async def test_inspection_evidence_nonexistent_asset_is_rejected(client: AsyncClient) -> None:
    response = await _upload(
        client, "INSPECTION_EVIDENCE", "INSPECTION_VEHICLE", "VEH-9999", _as("TECHNICIAN")
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_inspection_evidence_missing_source_is_rejected(client: AsyncClient) -> None:
    response = await _upload(client, "INSPECTION_EVIDENCE", None, None, _as("TECHNICIAN"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_REQUIRED"


@pytest.mark.asyncio
async def test_inspection_evidence_unsupported_source_type_is_rejected(
    client: AsyncClient,
) -> None:
    """REV06.3: a source_type outside INSPECTION_EVIDENCE's allowed set
    (INSPECTION_VEHICLE/INSPECTION_EQUIPMENT) is now caught by the
    purpose/source_type compatibility check first."""
    response = await _upload(
        client, "INSPECTION_EVIDENCE", "INSPECTION_UNKNOWN", "VEH-1046", _as("TECHNICIAN")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


# ---------------------------------------------------------------------------
# Storage boundary: authorization must run before any storage access, for
# the newly-added source types too (not just REPAIR_REQUEST, already
# proven in test_rev061_attachment_download_authorization.py).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_evidence_authorization_runs_before_storage_is_ever_read(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage.local import LocalFileStorageProvider

    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")
    upload = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "user-tech-1")
    )
    attachment_id = upload.json()["attachment_id"]

    async def _boom(self, storage_ref: str):  # pragma: no cover - must never run
        raise AssertionError(
            "storage.read() was reached for an unauthorized REPAIR_EVIDENCE download"
        )

    monkeypatch.setattr(LocalFileStorageProvider, "read", _boom)

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("TECHNICIAN", "user-unrelated")
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_pm_evidence_authorization_runs_before_storage_is_ever_read(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage.local import LocalFileStorageProvider

    work_order_id = await _open_pm_work_order(client)
    await _assign_pm(client, work_order_id, "user-tech-1")
    upload = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("TECHNICIAN", "user-tech-1")
    )
    attachment_id = upload.json()["attachment_id"]

    async def _boom(self, storage_ref: str):  # pragma: no cover - must never run
        raise AssertionError(
            "storage.read() was reached for an unauthorized PM_EVIDENCE download"
        )

    monkeypatch.setattr(LocalFileStorageProvider, "read", _boom)

    response = await client.get(
        f"/api/v1/attachments/{attachment_id}/file", headers=_as("TECHNICIAN", "user-unrelated")
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Upload/list/download consistency: an actor who cannot upload to a source
# must also be refused when listing it, and vice versa — proven for
# REPAIR_EVIDENCE (PM_EVIDENCE/INSPECTION_EVIDENCE have no dedicated
# by-source listing UI, but share the exact same `authorize_source` gate).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_evidence_upload_list_and_download_authorization_agree(
    client: AsyncClient,
) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")
    upload = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "user-tech-1")
    )
    attachment_id = upload.json()["attachment_id"]

    for headers, expect_allowed in (
        (_as("TECHNICIAN", "user-tech-1"), True),
        (_as("MAINTENANCE"), True),
        (_as("TECHNICIAN", "user-unrelated"), False),
    ):
        list_response = await client.get(
            f"/api/v1/attachments/by-source/REPAIR/{repair_id}", headers=headers
        )
        download_response = await client.get(
            f"/api/v1/attachments/{attachment_id}/file", headers=headers
        )
        assert (list_response.status_code == 200) == expect_allowed
        assert (download_response.status_code == 200) == expect_allowed
