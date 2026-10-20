"""R3-F1 — L10 final correction: Manager cancellation of a PENDING, never converted
Repair Request of ANY source (Owner decisions D8-A / D8-B).

- `can_cancel_repair_request` only (MAINTENANCE_MANAGER and ADMIN); checked on the
  route and again in the service; MAINTENANCE / SUPERVISOR / TECHNICIAN / DRIVER /
  DRIVER_DEPARTMENT_MANAGER are refused with nothing changed.
- Sources: an ordinary manual report, a PM result, an R3 Finding (the Finding case is
  in tests/test_r3_inspection_finding_followup.py).
- The existing Work Order is never touched; nothing is cancelled automatically.
- Mock only (Sheets mode answers 501). SYNTHETIC mock data; not production evidence.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain import authz
from tests.test_defect_provenance import _as, _open_pm_result

API = "/api/v1"
MANAGER = _as("MAINTENANCE_MANAGER", "USR-MGR")


async def _manual_request(client: AsyncClient, symptom: str = "เบรกมีเสียงดังผิดปกติ") -> dict:
    response = await client.post(f"{API}/repair-requests", json={"vehicle_id": "VEH-1046", "symptom_th": symptom,
                                 "note_th": "แจ้งโดยคนขับ"}, headers=_as("DRIVER", "driver-1"))
    assert response.status_code == 200, response.text
    return response.json()["request"]


def _cancel(client: AsyncClient, request_id: str, payload: dict | None = None, headers: dict | None = None):
    return client.post(f"{API}/repair-requests/{request_id}/cancellation",
                       json=payload if payload is not None else {"reason_th": "แจ้งซ้ำกับใบงานที่กำลังซ่อม"},
                       headers=headers or MANAGER)


def test_the_capability_is_held_only_by_the_maintenance_manager_and_admin() -> None:
    holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if authz.CAN_CANCEL_REPAIR_REQUEST in caps}
    assert holders == {"MAINTENANCE_MANAGER", "ADMIN"}
    assert authz.CAN_CANCEL_REPAIR_REQUEST in authz.ALL_CAPABILITIES


@pytest.mark.asyncio
async def test_an_ordinary_manual_report_is_cancelled_with_its_original_data_and_audit_kept(client) -> None:
    original = await _manual_request(client)
    work_order = await client.post(f"{API}/repairs", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                   "source_type": "MANUAL", "symptom": "เบรกมีเสียง"}, headers=_as("MAINTENANCE"))
    repair_id = work_order.json()["repair"]["repair_id"]
    cancelled = await _cancel(client, original["repair_request_id"], {"reason_th": "ซ้ำกับใบงานที่กำลังซ่อม",
                                                                      "duplicate_of_repair_id": repair_id})
    assert cancelled.status_code == 200, cancelled.text
    after = cancelled.json()
    assert (after["request_status"], after["cancelled_by_user_id"], after["cancel_reason_th"],
            after["duplicate_of_repair_id"]) == ("CANCELLED", "USR-MGR", "ซ้ำกับใบงานที่กำลังซ่อม", repair_id)
    assert after["cancelled_at"] is not None and after["repair_id"] is None
    audit = {"request_status", "cancelled_at", "cancelled_by_user_id", "cancel_reason_th", "duplicate_of_repair_id",
             "duplicate_of_repair_request_id"}
    assert {k: after[k] for k in original if k not in audit} == {k: original[k] for k in original if k not in audit}
    # Out of the actionable queue, still in the detail and in the reporter's history.
    pending = (await client.get(f"{API}/repair-requests/pending", params={"page_size": 200},
                                headers=_as("MAINTENANCE"))).json()["items"]
    assert original["repair_request_id"] not in {i["repair_request_id"] for i in pending}
    detail = await client.get(f"{API}/repair-requests/{original['repair_request_id']}", headers=_as("MAINTENANCE"))
    assert detail.json()["request_status"] == "CANCELLED"
    mine = (await client.get(f"{API}/repair-requests/mine", headers=_as("DRIVER", "driver-1"))).json()["items"]
    assert [i["request_status"] for i in mine if i["repair_request_id"] == original["repair_request_id"]] == \
        ["CANCELLED"]
    # Never converted afterwards; the existing Work Order is untouched.
    refused = await client.post(f"{API}/repair-requests/{original['repair_request_id']}/convert", json={},
                                headers=_as("MAINTENANCE"))
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "REPAIR_REQUEST_CANCELLED")
    repair = (await client.get(f"{API}/repairs/{repair_id}", headers=_as("MAINTENANCE"))).json()["repair"]
    assert repair["status"] == "OPEN" and repair["source_type"] == "MANUAL"


@pytest.mark.asyncio
async def test_a_pm_result_request_follows_the_same_rules_and_keeps_its_source(client) -> None:
    pm_result_id = await _open_pm_result(client)
    reported = await client.post(f"{API}/repair-requests", json={"vehicle_id": "VEH-1047", "symptom_th": "พบจาก PM",
                                 "source_type": "PM_RESULT", "source_id": pm_result_id},
                                 headers=_as("TECHNICIAN", "user-pm-tech-1"))
    assert reported.status_code == 200, reported.text
    request_id = reported.json()["request"]["repair_request_id"]
    cancelled = await _cancel(client, request_id)
    assert cancelled.status_code == 200, cancelled.text
    assert (cancelled.json()["source_type"], cancelled.json()["source_id"]) == ("PM_RESULT", pm_result_id)
    # The exact-source uniqueness rule is unchanged: the PM result stays reported.
    again = await client.post(f"{API}/repair-requests", json={"vehicle_id": "VEH-1047", "symptom_th": "แจ้งใหม่",
                              "source_type": "PM_RESULT", "source_id": pm_result_id},
                              headers=_as("TECHNICIAN", "user-pm-tech-1"))
    assert (again.status_code, again.json()["error"]["code"]) == (422, "REPAIR_REQUEST_SOURCE_ALREADY_REPORTED")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_every_other_role_is_refused_with_nothing_changed(client, role) -> None:
    original = await _manual_request(client)
    refused = await _cancel(client, original["repair_request_id"], headers=_as(role))
    assert refused.status_code == 403
    detail = await client.get(f"{API}/repair-requests/{original['repair_request_id']}", headers=_as("MAINTENANCE"))
    assert detail.json() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["MAINTENANCE_MANAGER", "ADMIN"])
async def test_the_manager_and_admin_are_authorized(client, role) -> None:
    original = await _manual_request(client)
    assert (await _cancel(client, original["repair_request_id"], headers=_as(role))).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(("payload", "status_code", "error_code"), [
    ({}, 422, "REPAIR_REQUEST_CANCEL_REASON_REQUIRED"),
    ({"reason_th": "   "}, 422, "REPAIR_REQUEST_CANCEL_REASON_REQUIRED"),
    ({"reason_th": "ซ้ำ", "duplicate_of_repair_id": "RPR-9999"}, 422, "REPAIR_REQUEST_DUPLICATE_REFERENCE_NOT_FOUND"),
    ({"reason_th": "ซ้ำ", "duplicate_of_repair_request_id": "RRQ-9999"}, 422,
     "REPAIR_REQUEST_DUPLICATE_REFERENCE_NOT_FOUND"),
])
async def test_a_missing_reason_or_an_invalid_reference_is_refused(client, payload, status_code, error_code) -> None:
    original = await _manual_request(client)
    refused = await _cancel(client, original["repair_request_id"], payload)
    assert (refused.status_code, refused.json()["error"]["code"]) == (status_code, error_code)
    self_reference = await _cancel(client, original["repair_request_id"],
                                   {"reason_th": "ซ้ำ", "duplicate_of_repair_request_id": original["repair_request_id"]})
    assert self_reference.json()["error"]["code"] == "REPAIR_REQUEST_DUPLICATE_REFERENCE_NOT_FOUND"
    detail = await client.get(f"{API}/repair-requests/{original['repair_request_id']}", headers=_as("MAINTENANCE"))
    assert detail.json()["request_status"] == "PENDING"


@pytest.mark.asyncio
async def test_a_reference_to_another_request_is_kept(client) -> None:
    first = await _manual_request(client)
    duplicate = await _manual_request(client, "เบรกมีเสียง (แจ้งซ้ำ)")
    cancelled = await _cancel(client, duplicate["repair_request_id"], {
        "reason_th": "ซ้ำกับคำขอเดิม", "duplicate_of_repair_request_id": first["repair_request_id"]})
    assert cancelled.json()["duplicate_of_repair_request_id"] == first["repair_request_id"]
    remaining = await client.get(f"{API}/repair-requests/{first['repair_request_id']}", headers=_as("MAINTENANCE"))
    assert remaining.json()["request_status"] == "PENDING"  # the referenced request is untouched


@pytest.mark.asyncio
async def test_a_converted_request_cannot_be_cancelled_and_conversion_stays_idempotent(client) -> None:
    original = await _manual_request(client)
    converted = await client.post(f"{API}/repair-requests/{original['repair_request_id']}/convert", json={},
                                  headers=_as("MAINTENANCE"))
    repair_id = converted.json()["repair"]["repair_id"]
    refused = await _cancel(client, original["repair_request_id"])
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "REPAIR_REQUEST_NOT_PENDING")
    retry = await client.post(f"{API}/repair-requests/{original['repair_request_id']}/convert", json={},
                              headers=_as("MAINTENANCE"))
    assert retry.json()["repair"]["repair_id"] == repair_id  # REV05 idempotency unchanged


@pytest.mark.asyncio
async def test_a_cancellation_racing_a_conversion_never_leaves_an_orphan_work_order(client, monkeypatch) -> None:
    """Mock guarantee (single process, no await between re-check and write): the
    cancellation lands after conversion read the request as PENDING, before the Work
    Order is created. Creation re-checks the request and refuses; no Work Order exists."""
    from app.dependencies import get_repository
    from app.domain.repair import RepairSourceType

    original = await _manual_request(client)
    repo = get_repository()
    real_find = repo.find_repairs_by_source

    async def cancel_then_find(source_type, source_id):
        await repo.cancel_repair_request(source_id, cancelled_by="USR-MGR", reason="แข่งกัน",
                                         duplicate_of_repair_id=None, duplicate_of_repair_request_id=None)
        return await real_find(source_type, source_id)

    monkeypatch.setattr(repo, "find_repairs_by_source", cancel_then_find)
    refused = await client.post(f"{API}/repair-requests/{original['repair_request_id']}/convert", json={},
                                headers=_as("MAINTENANCE"))
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "REPAIR_REQUEST_CANCELLED")
    monkeypatch.setattr(repo, "find_repairs_by_source", real_find)
    assert await repo.find_repairs_by_source(RepairSourceType.REPAIR_REQUEST, original["repair_request_id"]) == []
    detail = await client.get(f"{API}/repair-requests/{original['repair_request_id']}", headers=_as("MAINTENANCE"))
    assert detail.json()["request_status"] == "CANCELLED"
