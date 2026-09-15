"""Web UAT Defect Fix — regression tests for UAT-F1/F2/F3.

- UAT-F1 (HIGH): `RepairCreatePage.tsx`'s Repair-Request flow dropped
  `source_type`/`source_id` even when the page had them from a Finding
  link. The backend contract this frontend fix relies on
  (`POST /repair-requests` accepting/persisting `source_type=FINDING`)
  was already covered by `test_defect_provenance.py`; this file covers
  the two NEW read surfaces added to support the fix end-to-end:
- UAT-F2 (MEDIUM): `GET /repair-requests/mine` — lets a reporter find a
  Repair Request they already submitted, scoped to their own
  `reported_by_user_id` (strictly narrower than the pre-existing,
  unrestricted `GET /repair-requests/{id}`).
- UAT-F3 (MEDIUM): `GET /repair-requests/by-source/{source_type}/{source_id}`
  — lets the UI derive "already reported" from persisted data instead of
  client-only React state that disappears on reload.
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


async def _open_pm_result(
    client: AsyncClient, vehicle_id: str = "VEH-1047", technician: str = "user-pm-tech-1"
) -> str:
    work_order = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": "PMP-0001"},
        headers=_as("MAINTENANCE"),
    )
    work_order_id = work_order.json()["work_order"]["pm_work_order_id"]
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": technician, "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    result = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": False, "remark": "พบความผิดปกติระหว่าง PM"},
        headers=_as("TECHNICIAN", technician),
    )
    assert result.status_code == 200
    return result.json()["results"][0]["pm_work_result_id"]


# ---------------------------------------------------------------------------
# UAT-F2 — GET /repair-requests/mine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mine_returns_only_this_reporters_own_requests(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "อาการของ driver-a"},
        headers=_as("DRIVER", "driver-a"),
    )
    await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1047", "symptom_th": "อาการของ driver-b"},
        headers=_as("DRIVER", "driver-b"),
    )

    mine_a = await client.get("/api/v1/repair-requests/mine", headers=_as("DRIVER", "driver-a"))
    assert mine_a.status_code == 200
    body_a = mine_a.json()
    assert body_a["total_items"] == 1
    assert body_a["items"][0]["symptom_th"] == "อาการของ driver-a"

    mine_b = await client.get("/api/v1/repair-requests/mine", headers=_as("DRIVER", "driver-b"))
    assert mine_b.json()["total_items"] == 1
    assert mine_b.json()["items"][0]["symptom_th"] == "อาการของ driver-b"


@pytest.mark.asyncio
async def test_mine_includes_both_pending_and_converted_requests(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "จะถูกเปิดใบงานซ่อม"},
        headers=_as("DRIVER", "driver-c"),
    )
    request_id = created.json()["request"]["repair_request_id"]

    before = await client.get("/api/v1/repair-requests/mine", headers=_as("DRIVER", "driver-c"))
    assert before.json()["items"][0]["request_status"] == "PENDING"

    await client.post(
        f"/api/v1/repair-requests/{request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )

    after = await client.get("/api/v1/repair-requests/mine", headers=_as("DRIVER", "driver-c"))
    assert after.json()["total_items"] == 1
    assert after.json()["items"][0]["request_status"] == "CONVERTED"
    assert after.json()["items"][0]["repair_id"] is not None


@pytest.mark.asyncio
async def test_mine_requires_can_report_repair_capability(client: AsyncClient) -> None:
    # No recognized role -> capabilities_for_roles() grants nothing (fails
    # closed), so this exercises the require_capability gate itself.
    response = await client.get(
        "/api/v1/repair-requests/mine",
        headers=_as("SOME_UNRECOGNIZED_ROLE", "nobody"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mine_is_empty_for_a_reporter_who_never_submitted_anything(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/repair-requests/mine", headers=_as("DRIVER", "driver-never-reported")
    )
    assert response.status_code == 200
    assert response.json()["total_items"] == 0
    assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# UAT-F3 — GET /repair-requests/by-source/{source_type}/{source_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_by_source_finds_a_request_reported_from_a_finding(client: AsyncClient) -> None:
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
    request_id = submitted.json()["request"]["repair_request_id"]

    response = await client.get(
        f"/api/v1/repair-requests/by-source/FINDING/{finding_id}", headers=_as("TECHNICIAN")
    )
    assert response.status_code == 200
    matches = response.json()
    assert len(matches) == 1
    assert matches[0]["repair_request_id"] == request_id
    assert matches[0]["source_type"] == "FINDING"
    assert matches[0]["source_id"] == finding_id


@pytest.mark.asyncio
async def test_by_source_finds_a_request_reported_from_a_pm_result(client: AsyncClient) -> None:
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
    request_id = submitted.json()["request"]["repair_request_id"]

    response = await client.get(
        f"/api/v1/repair-requests/by-source/PM_RESULT/{pm_result_id}",
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert response.status_code == 200
    matches = response.json()
    assert len(matches) == 1
    assert matches[0]["repair_request_id"] == request_id


@pytest.mark.asyncio
async def test_by_source_is_empty_when_no_request_references_that_source(
    client: AsyncClient,
) -> None:
    inspection = await _submit_failing_inspection(client, vehicle_id="VEH-1048")
    finding_id = inspection["findings"][0]["finding_id"]

    response = await client.get(
        f"/api/v1/repair-requests/by-source/FINDING/{finding_id}", headers=_as("TECHNICIAN")
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_by_source_does_not_cross_match_a_different_source_id(client: AsyncClient) -> None:
    inspection = await _submit_failing_inspection(client, vehicle_id="VEH-1046")
    finding_id = inspection["findings"][0]["finding_id"]
    await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "พบข้อบกพร่อง",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )

    response = await client.get(
        "/api/v1/repair-requests/by-source/FINDING/FND-9999", headers=_as("TECHNICIAN")
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_by_source_requires_can_report_repair_capability(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/repair-requests/by-source/FINDING/FND-0001",
        headers=_as("SOME_UNRECOGNIZED_ROLE", "nobody"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_manual_repair_request_never_appears_in_a_by_source_lookup(
    client: AsyncClient,
) -> None:
    """A plain, un-sourced Repair Request must never spuriously match a
    by-source query for any type/id (decode_provenance_note returns
    (None, None, note) for it, which can never equal a real source_type)."""
    await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "รายงานทั่วไปไม่มีแหล่งที่มา"},
        headers=_as("DRIVER", "driver-manual"),
    )

    response = await client.get(
        "/api/v1/repair-requests/by-source/FINDING/FND-0001", headers=_as("DRIVER")
    )
    assert response.json() == []
