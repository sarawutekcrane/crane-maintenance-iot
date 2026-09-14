"""Core Demo Fixes Delta REV06 section 15 (P1) — Finding/PM defect
traceability through Repair Request -> RPR.

The independent REV05 audit found the approved non-Maintenance routing
(section 4: `Finding/PM defect -> Repair Request -> Maintenance review ->
RPR`) broke provenance: the live `repair_request` sheet's fixed 16-column
schema has no dedicated source column, so a Finding/PM Work Result named
by a non-Maintenance reporter was silently dropped. REV06 encodes it into
`note_th` via a strict, centrally-parsed marker (see
`app.domain.repair_request.encode_provenance_note`/
`decode_provenance_note`) and decodes it back on every read — these tests
prove the encoding survives report -> review -> conversion and is
recoverable from the resulting Repair's own history chain
(`Repair.source_id` -> `RepairRequest` -> decoded `source_type`/
`source_id`), without ever changing the persisted schema.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _submit_failing_inspection(client: AsyncClient, vehicle_id: str = "VEH-1046") -> dict:
    checklist = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    items = [{"item_id": i["item_id"], "result": "PASS"} for i in checklist.json()["items"]]
    items[0]["result"] = "FAIL"
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "items": items},
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 200
    return response.json()


async def _open_pm_result(client: AsyncClient, vehicle_id: str = "VEH-1047") -> str:
    work_order = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": "PMP-0001"},
        headers=_as("MAINTENANCE"),
    )
    work_order_id = work_order.json()["work_order"]["pm_work_order_id"]
    # REV06 section 13: submitting a task result now requires assignment —
    # assign the reporting technician first.
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-tech-1", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    result = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": False, "remark": "พบความผิดปกติระหว่าง PM"},
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert result.status_code == 200
    return result.json()["results"][0]["pm_work_result_id"]


# ---------------------------------------------------------------------------
# 32 — Finding -> Repair Request preserves source provenance.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_defect_report_preserves_source_provenance(client: AsyncClient) -> None:
    inspection = await _submit_failing_inspection(client)
    finding_id = inspection["findings"][0]["finding_id"]

    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "พบข้อบกพร่องระหว่างตรวจเช็ค",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 200
    request = response.json()["request"]
    assert request["source_type"] == "FINDING"
    assert request["source_id"] == finding_id
    # The user-visible note is unaffected — no leaked internal marker.
    assert request["note_th"] is None

    reread = await client.get(f"/api/v1/repair-requests/{request['repair_request_id']}")
    assert reread.json()["source_type"] == "FINDING"
    assert reread.json()["source_id"] == finding_id


@pytest.mark.asyncio
async def test_finding_defect_report_preserves_a_real_user_note_alongside_provenance(
    client: AsyncClient,
) -> None:
    inspection = await _submit_failing_inspection(client)
    finding_id = inspection["findings"][0]["finding_id"]

    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "พบข้อบกพร่องระหว่างตรวจเช็ค",
            "note_th": "แจ้งจากช่างตรวจเช็ค พบรอยรั่ว",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 200
    request = response.json()["request"]
    assert request["source_type"] == "FINDING"
    assert request["note_th"] == "แจ้งจากช่างตรวจเช็ค พบรอยรั่ว"


@pytest.mark.asyncio
async def test_unknown_finding_source_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "ทดสอบ",
            "source_type": "FINDING",
            "source_id": "FND-9999",
        },
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPAIR_REQUEST_SOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 33 — Repair Request -> RPR retains original Finding provenance.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_converted_repair_retains_original_finding_provenance_via_the_request(
    client: AsyncClient,
) -> None:
    inspection = await _submit_failing_inspection(client)
    finding_id = inspection["findings"][0]["finding_id"]

    submitted = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "พบข้อบกพร่องระหว่างตรวจเช็ค",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    repair_request_id = submitted.json()["request"]["repair_request_id"]

    convert = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )
    assert convert.status_code == 200
    repair = convert.json()["repair"]
    # The Repair's own direct source is the Repair Request (REV06 section 9
    # — never silently rewritten to the transitive Finding).
    assert repair["source_type"] == "REPAIR_REQUEST"
    assert repair["source_id"] == repair_request_id

    # The original Finding provenance is still discoverable by following
    # that link.
    reread_request = await client.get(f"/api/v1/repair-requests/{repair_request_id}")
    assert reread_request.json()["source_type"] == "FINDING"
    assert reread_request.json()["source_id"] == finding_id


# ---------------------------------------------------------------------------
# 34 — PM defect -> Repair Request preserves PM source.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm_defect_report_preserves_pm_source_provenance(client: AsyncClient) -> None:
    pm_result_id = await _open_pm_result(client)

    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1047",
            "symptom_th": "พบข้อบกพร่องระหว่างทำ PM",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
        },
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert response.status_code == 200
    request = response.json()["request"]
    assert request["source_type"] == "PM_RESULT"
    assert request["source_id"] == pm_result_id


@pytest.mark.asyncio
async def test_unknown_pm_result_source_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1047",
            "symptom_th": "ทดสอบ",
            "source_type": "PM_RESULT",
            "source_id": "PMR-9999",
        },
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPAIR_REQUEST_SOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 35 — PM Request -> RPR retains original PM provenance.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_converted_repair_retains_original_pm_provenance_via_the_request(
    client: AsyncClient,
) -> None:
    pm_result_id = await _open_pm_result(client)

    submitted = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1047",
            "symptom_th": "พบข้อบกพร่องระหว่างทำ PM",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
        },
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    repair_request_id = submitted.json()["request"]["repair_request_id"]

    convert = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )
    assert convert.status_code == 200
    repair = convert.json()["repair"]
    assert repair["source_type"] == "REPAIR_REQUEST"
    assert repair["source_id"] == repair_request_id

    reread_request = await client.get(f"/api/v1/repair-requests/{repair_request_id}")
    assert reread_request.json()["source_type"] == "PM_RESULT"
    assert reread_request.json()["source_id"] == pm_result_id


# ---------------------------------------------------------------------------
# A technician reporting a PM/Finding defect never gains implicit RPR
# creation authority (section 4/16) — the request stays PENDING, never
# auto-converted, even though provenance is preserved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reporting_a_pm_defect_never_auto_creates_or_grants_rpr_authority(
    client: AsyncClient,
) -> None:
    pm_result_id = await _open_pm_result(client)
    submitted = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1047",
            "symptom_th": "พบข้อบกพร่องระหว่างทำ PM",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
        },
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert submitted.json()["request"]["request_status"] == "PENDING"
    assert submitted.json()["request"]["repair_id"] is None

    # The same reporter still cannot convert it themselves.
    convert_attempt = await client.post(
        f"/api/v1/repair-requests/{submitted.json()['request']['repair_request_id']}/convert",
        json={},
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert convert_attempt.status_code == 403
