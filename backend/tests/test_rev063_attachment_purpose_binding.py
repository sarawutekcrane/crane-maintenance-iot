"""REV06.3 delta — final independent audit HIGH finding fix.

The REV06.2 acceptance audit reproduced a purpose-confusion/source-
smuggling bypass: `AttachmentService.authorize_source`'s
`CHECKLIST_REFERENCE_IMAGE` branch returned immediately, before any
`source_type`/`source_id` was validated or authorized. A caller could
send `purpose=CHECKLIST_REFERENCE_IMAGE` alongside a REAL `source_type`
(e.g. `REPAIR`) and `source_id` belonging to a record they have no
relationship to, and the attachment was persisted with that real source —
entirely bypassing the source's own authorization gate — then surfaced in
that source's own by-source attachment listing.

`authorize_source` now validates `purpose`/`source_type` compatibility
(`_ALLOWED_SOURCE_TYPES_BY_PURPOSE`) before any purpose-specific bypass or
source-record resolution, for upload, list, and download/re-validation
alike. `CHECKLIST_REFERENCE_IMAGE` maps to an empty allowed set — it can
never carry any source_type/source_id, full stop.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.pm_e01_support import http_start


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


# DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (deliberate fixture migration): the owning job's team is
# a Technician V2 assignment set (the seeded TEST technicians linked to their TEST accounts), written
# through the real V2 route — the legacy assign seed is gone with the legacy runtime.
SEED_TECHNICIAN = {"USR-TEST-911": "TEC-TEST-911", "USR-TEST-912": "TEC-TEST-912"}


async def _assign_v2(client: AsyncClient, kind_path: str, job_id: str, user: str | None) -> None:
    import uuid

    path = f"/api/v1/{kind_path}/{job_id}/technician-assignments"
    current = (await client.get(path, headers=_as("MAINTENANCE"))).json().get("current")
    expected = None if not current else {"primary_technician_id": current["primary_technician_id"],
                                         "collaborator_technician_ids": current["collaborator_technician_ids"]}
    response = await client.post(path, json={"primary_technician_id": SEED_TECHNICIAN[user],
                                             "collaborator_technician_ids": [], "expected_current": expected},
                                 headers={**_as("MAINTENANCE"), "X-Request-Id": str(uuid.uuid4())})
    assert response.status_code == 200, response.text


async def _assign_and_start_pm(client: AsyncClient, work_order_id: str, user: str) -> None:
    """PM evidence is accepted only while the V2 work order is IN_PROGRESS (EV-048), so the PRIMARY starts it."""
    import uuid

    await _assign_v2(client, "pm/work-orders", work_order_id, user)
    started = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/start",
                                headers={**_as("TECHNICIAN", user), "X-Request-Id": str(uuid.uuid4())})
    assert started.status_code == 200, started.text


async def _assign_repair(client: AsyncClient, repair_id: str, primary: str | None) -> None:
    await _assign_v2(client, "repairs", repair_id, primary)


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


async def _upload(
    client: AsyncClient,
    purpose: str,
    source_type: str | None,
    source_id: str | None,
    headers: dict,
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
# Section 13 — mandatory exact exploit reproduction, end-to-end.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checklist_reference_image_cannot_smuggle_a_foreign_repair_source(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact exploit the independent audit reproduced: an unrelated
    actor sends purpose=CHECKLIST_REFERENCE_IMAGE with source_type=REPAIR
    pointing at a real Repair they cannot access. Must be rejected, must
    persist nothing, must never touch storage, and must never contaminate
    the real assignee's own by-source listing for that repair."""
    from app.storage.local import LocalFileStorageProvider

    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "USR-TEST-911")

    # Baseline: the legitimate assignee's by-source listing is empty
    # before the exploit attempt.
    baseline = await client.get(
        f"/api/v1/attachments/by-source/REPAIR/{repair_id}", headers=_as("TECHNICIAN", "USR-TEST-911")
    )
    assert baseline.status_code == 200
    assert baseline.json() == []

    async def _boom(self, filename: str, content_type: str, data: bytes):  # pragma: no cover
        raise AssertionError(
            "storage.save() was reached for a rejected CHECKLIST_REFERENCE_IMAGE+REPAIR upload"
        )

    monkeypatch.setattr(LocalFileStorageProvider, "save", _boom)

    exploit = await _upload(
        client,
        "CHECKLIST_REFERENCE_IMAGE",
        "REPAIR",
        repair_id,
        _as("DRIVER", "mallory-unrelated"),
    )
    assert exploit.status_code in (403, 422)
    assert exploit.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"

    # No row persisted: the legitimate assignee's by-source listing is
    # unchanged (still empty), proving no contamination occurred.
    after = await client.get(
        f"/api/v1/attachments/by-source/REPAIR/{repair_id}", headers=_as("TECHNICIAN", "USR-TEST-911")
    )
    assert after.status_code == 200
    assert after.json() == []


@pytest.mark.asyncio
async def test_checklist_reference_image_cannot_smuggle_a_foreign_pm_work_order_source(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_pm_work_order(client)
    await _assign_and_start_pm(client, work_order_id, "USR-TEST-911")
    exploit = await _upload(
        client,
        "CHECKLIST_REFERENCE_IMAGE",
        "PM_WORK_ORDER",
        work_order_id,
        _as("DRIVER", "mallory-unrelated"),
    )
    assert exploit.status_code in (403, 422)
    assert exploit.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


@pytest.mark.asyncio
async def test_checklist_reference_image_cannot_smuggle_an_inspection_asset_source(
    client: AsyncClient,
) -> None:
    exploit = await _upload(
        client, "CHECKLIST_REFERENCE_IMAGE", "INSPECTION_VEHICLE", "VEH-1046", _as("DRIVER")
    )
    assert exploit.status_code in (403, 422)
    assert exploit.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


@pytest.mark.asyncio
async def test_checklist_reference_image_with_only_source_type_is_rejected(
    client: AsyncClient,
) -> None:
    response = await _upload(client, "CHECKLIST_REFERENCE_IMAGE", "REPAIR", None, _as("DRIVER"))
    assert response.status_code in (403, 422)


@pytest.mark.asyncio
async def test_checklist_reference_image_with_only_source_id_is_rejected(
    client: AsyncClient,
) -> None:
    response = await _upload(client, "CHECKLIST_REFERENCE_IMAGE", None, "RPR-0001", _as("DRIVER"))
    assert response.status_code in (403, 422)


@pytest.mark.asyncio
async def test_checklist_reference_image_still_works_source_less(client: AsyncClient) -> None:
    """Regression guard: the genuinely source-less, master-content path
    (no source_type/source_id at all) must remain unaffected."""
    response = await _upload(client, "CHECKLIST_REFERENCE_IMAGE", None, None, _as("TECHNICIAN"))
    assert response.status_code == 200
    assert response.json()["source_type"] is None


# ---------------------------------------------------------------------------
# Section 14 — full purpose-confusion matrix.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_evidence_with_pm_work_order_source_is_rejected(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    response = await _upload(
        client, "REPAIR_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("MAINTENANCE")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


@pytest.mark.asyncio
async def test_pm_evidence_with_repair_source_is_rejected(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await _upload(client, "PM_EVIDENCE", "REPAIR", repair_id, _as("MAINTENANCE"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


@pytest.mark.asyncio
async def test_repair_request_evidence_with_repair_source_is_rejected(
    client: AsyncClient,
) -> None:
    repair_id = await _open_repair(client)
    response = await _upload(
        client, "REPAIR_REQUEST_EVIDENCE", "REPAIR", repair_id, _as("MAINTENANCE")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


@pytest.mark.asyncio
async def test_inspection_evidence_with_repair_source_is_rejected(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await _upload(
        client, "INSPECTION_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


@pytest.mark.asyncio
async def test_repair_evidence_with_repair_source_is_valid(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await _upload(client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("MAINTENANCE"))
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_pm_evidence_with_pm_work_order_source_is_valid(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    # R4 EV-048 E-1 (Owner rule) / EV-049 E-5: new evidence on a V2 PM work order is accepted only while
    # it is IN_PROGRESS. Every new work order is V2 and starts OPEN, so it is refused there ...
    refused = await _upload(client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("MAINTENANCE"))
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "PM_EVIDENCE_NOT_ALLOWED"
    # ... and the valid purpose/source pairing is accepted once the current V2 team has STARTed it.
    await http_start(client, work_order_id)
    response = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("MAINTENANCE")
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_repair_request_evidence_with_repair_request_source_is_valid(
    client: AsyncClient,
) -> None:
    submit = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "ทดสอบ"},
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert submit.status_code == 200
    request_id = submit.json()["request"]["repair_request_id"]
    response = await _upload(
        client,
        "REPAIR_REQUEST_EVIDENCE",
        "REPAIR_REQUEST",
        request_id,
        _as("DRIVER", "user-driver-1"),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_inspection_evidence_with_inspection_vehicle_source_is_valid(
    client: AsyncClient,
) -> None:
    response = await _upload(
        client, "INSPECTION_EVIDENCE", "INSPECTION_VEHICLE", "VEH-1046", _as("TECHNICIAN")
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_inspection_evidence_with_inspection_equipment_source_is_valid(
    client: AsyncClient,
) -> None:
    response = await _upload(
        client, "INSPECTION_EVIDENCE", "INSPECTION_EQUIPMENT", "EQP-0001", _as("TECHNICIAN")
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Section 12 — legacy malformed rows fail closed on download/list re-check,
# not just at upload time. Written directly through the repository,
# bypassing the (now-fixed) service-layer upload gate entirely, to
# reproduce the exact shape a pre-REV06.3 corrupted row (or, hypothetically,
# one written by some other future path) would have.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_malformed_checklist_reference_image_with_source_fails_closed_on_download(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.dependencies import get_repository
    from app.domain.attachment import AttachmentPurpose

    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "USR-TEST-911")

    repository = get_repository()
    malformed = await repository.create_attachment(
        purpose=AttachmentPurpose.CHECKLIST_REFERENCE_IMAGE,
        storage_ref="legacy-malformed-ref-never-read",
        filename="malformed.jpg",
        content_type="image/jpeg",
        size_bytes=12,
        uploaded_by="dev-user",
        source_type="REPAIR",
        source_id=repair_id,
    )

    from app.storage.local import LocalFileStorageProvider

    async def _boom(self, storage_ref: str):  # pragma: no cover - must never run
        raise AssertionError("storage.read() was reached for a malformed legacy attachment")

    monkeypatch.setattr(LocalFileStorageProvider, "read", _boom)

    response = await client.get(
        f"/api/v1/attachments/{malformed.attachment_id}/file",
        headers=_as("TECHNICIAN", "USR-TEST-911"),
    )
    assert response.status_code in (403, 422)
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


# ---------------------------------------------------------------------------
# Section 16 — authorization regression after the compatibility check was
# inserted ahead of every existing branch.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_evidence_authorization_regression(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "USR-TEST-911")

    allowed_primary = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "USR-TEST-911")
    )
    assert allowed_primary.status_code == 200

    allowed_maintenance = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("MAINTENANCE")
    )
    assert allowed_maintenance.status_code == 200

    denied_unrelated = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "tech-unrelated")
    )
    assert denied_unrelated.status_code == 403

    await _assign_repair(client, repair_id, "USR-TEST-912")
    denied_ended = await _upload(
        client, "REPAIR_EVIDENCE", "REPAIR", repair_id, _as("TECHNICIAN", "USR-TEST-911")
    )
    assert denied_ended.status_code == 403


@pytest.mark.asyncio
async def test_pm_evidence_authorization_regression(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    await _assign_and_start_pm(client, work_order_id, "USR-TEST-911")

    allowed = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("TECHNICIAN", "USR-TEST-911")
    )
    assert allowed.status_code == 200

    allowed_maintenance = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("MAINTENANCE")
    )
    assert allowed_maintenance.status_code == 200

    denied = await _upload(
        client, "PM_EVIDENCE", "PM_WORK_ORDER", work_order_id, _as("TECHNICIAN", "tech-unrelated")
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_repair_request_evidence_authorization_regression(client: AsyncClient) -> None:
    submit = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "ทดสอบ"},
        headers=_as("DRIVER", "user-driver-1"),
    )
    request_id = submit.json()["request"]["repair_request_id"]

    allowed_reporter = await _upload(
        client,
        "REPAIR_REQUEST_EVIDENCE",
        "REPAIR_REQUEST",
        request_id,
        _as("DRIVER", "user-driver-1"),
    )
    assert allowed_reporter.status_code == 200

    allowed_maintenance = await _upload(
        client, "REPAIR_REQUEST_EVIDENCE", "REPAIR_REQUEST", request_id, _as("MAINTENANCE")
    )
    assert allowed_maintenance.status_code == 200

    denied_unrelated = await _upload(
        client,
        "REPAIR_REQUEST_EVIDENCE",
        "REPAIR_REQUEST",
        request_id,
        _as("DRIVER", "user-driver-2"),
    )
    assert denied_unrelated.status_code == 403
