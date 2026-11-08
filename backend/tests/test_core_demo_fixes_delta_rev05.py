"""Core Demo Fixes Delta REV05 — newly-approved Maintenance-controlled
Repair/PM authority model, Repair Request workflow, derived queues, and
the capability-based (not role-name-hardcoded) permission mechanism.

`client` runs every request as the fixed `dev-user`/`ADMIN` actor (every
capability granted) unless a test overrides it with the dev-only
`X-Dev-Role`/`X-Dev-User-Id` headers `app.context.RequestContextMiddleware`
honors only while `DEV_AUTH_MODE` is on (see that module) — this is how
these tests simulate a Driver/Technician/Maintenance actor without a real
login existing yet.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.pm_e01_support import (
    SEED_PRIMARY_USER,
    http_complete_and_close,
    http_save,
    http_start,
)
from tests.v2_http_assignment import (
    COLLABORATOR_USER,
    PRIMARY_USER,
    SEED_TECHNICIAN,
    assign_v2,
)


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _submit_repair_request(
    client: AsyncClient, vehicle_id: str = "VEH-1046", headers: dict[str, str] | None = None
) -> dict:
    response = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": vehicle_id, "symptom_th": "มีเสียงดังผิดปกติ", "priority": "NORMAL"},
        headers=headers or _as("DRIVER"),
    )
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# 1-6 — Repair Request creation, capability gating, conversion, idempotency.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reporter_without_manage_repair_can_submit_a_repair_request(
    client: AsyncClient,
) -> None:
    body = await _submit_repair_request(client)
    assert body["request"]["request_status"] == "PENDING"
    assert body["request"]["repair_id"] is None
    assert body["meter_snapshot_id"] is not None and body["meter_snapshot_id"].startswith("MSNAP-")


@pytest.mark.asyncio
async def test_reporter_without_manage_repair_cannot_open_a_repair_work_order_directly(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("DRIVER"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_can_convert_a_pending_repair_request_to_an_rpr(
    client: AsyncClient,
) -> None:
    body = await _submit_repair_request(client)
    repair_request_id = body["request"]["repair_request_id"]

    convert = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )
    assert convert.status_code == 200
    repair = convert.json()["repair"]
    assert repair["status"] == "OPEN"
    assert repair["primary_technician"] is None  # never forced at conversion time

    reread_request = await client.get(f"/api/v1/repair-requests/{repair_request_id}")
    assert reread_request.json()["request_status"] == "CONVERTED"


@pytest.mark.asyncio
async def test_converted_rpr_preserves_repair_request_source_linkage(
    client: AsyncClient,
) -> None:
    body = await _submit_repair_request(client)
    repair_request_id = body["request"]["repair_request_id"]
    convert = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )
    repair = convert.json()["repair"]
    assert repair["source_type"] == "REPAIR_REQUEST"
    assert repair["source_id"] == repair_request_id


@pytest.mark.asyncio
async def test_maintenance_can_open_an_rpr_directly_without_a_repair_request(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    assert response.json()["repair"]["status"] == "OPEN"


@pytest.mark.asyncio
async def test_converting_the_same_repair_request_twice_never_creates_a_duplicate_rpr(
    client: AsyncClient,
) -> None:
    body = await _submit_repair_request(client)
    repair_request_id = body["request"]["repair_request_id"]

    first = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )
    second = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert",
        json={},
        headers=_as("MAINTENANCE"),
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["repair"]["repair_id"] == second.json()["repair"]["repair_id"]

    all_repairs = await client.get(
        "/api/v1/repairs", params={"asset_id": "VEH-1046"}, headers=_as("MAINTENANCE")
    )
    matching = [
        r for r in all_repairs.json()["items"] if r.get("source_id") == repair_request_id
    ]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# 7-11 — deferred assignment / derived queues / non-destructive history.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpr_may_remain_open_with_no_technician_and_appears_in_waiting_assignment(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair = create.json()["repair"]
    assert repair["status"] == "OPEN"
    assert repair["primary_technician"] is None

    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration, owner final decision: V2 only): every new Repair is a
    # Technician V2 job, so "waiting for assignment" is the U1 V2 queue (assignment_status NONE).
    assert repair["assignment_model"] == "TECHNICIAN_V2"
    waiting = await client.get("/api/v1/repairs/v2-waiting-assignment", headers=_as("MAINTENANCE"))
    assert waiting.status_code == 200
    statuses = {r["job_id"]: r["assignment_status"] for r in waiting.json()["items"]}
    assert statuses[repair["repair_id"]] == "NONE"


@pytest.mark.asyncio
async def test_assigning_primary_removes_from_waiting_assignment_and_appears_in_my_work(
    client: AsyncClient,
) -> None:
    """Legacy cancelled (DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107): assigning the V2 team takes the
    repair off the V2 waiting queue and onto its PRIMARY's My Work (and nobody else's)."""
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]
    assert repair_id in await _v2_waiting_ids(client)

    await assign_v2(client, "repairs", repair_id, PRIMARY_USER)

    assert repair_id not in await _v2_waiting_ids(client)
    assert repair_id in await _v2_my_work_ids(client, PRIMARY_USER)
    assert repair_id not in await _v2_my_work_ids(client, COLLABORATOR_USER)

async def _v2_my_work_ids(client: AsyncClient, user: str) -> set[str]:
    response = await client.get("/api/v1/my-work", headers={"X-Dev-Role": "TECHNICIAN", "X-Dev-User-Id": user})
    assert response.status_code == 200, response.text
    return {item["job_id"] for item in response.json()["items"] or []}


async def _v2_waiting_ids(client: AsyncClient) -> set[str]:
    response = await client.get("/api/v1/repairs/v2-waiting-assignment",
                                headers={"X-Dev-Role": "MAINTENANCE", "X-Dev-User-Id": "dev-user"})
    assert response.status_code == 200, response.text
    return {item["job_id"] for item in response.json()["items"]}


@pytest.mark.asyncio
async def test_collaborators_do_not_replace_the_primary_technician(client: AsyncClient) -> None:
    """V2: a collaborator joins the set; the PRIMARY stays the PRIMARY and the job leaves the waiting queue."""
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    written = await assign_v2(client, "repairs", repair_id, PRIMARY_USER, [COLLABORATOR_USER])
    assert written["current"]["primary_technician_id"] == SEED_TECHNICIAN[PRIMARY_USER]
    assert written["current"]["collaborator_technician_ids"] == [SEED_TECHNICIAN[COLLABORATOR_USER]]

    assert repair_id not in await _v2_waiting_ids(client)
    for user in (PRIMARY_USER, COLLABORATOR_USER):
        assert repair_id in await _v2_my_work_ids(client, user)


# ---------------------------------------------------------------------------
# 12-16 — closure authority (Repair + PM).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_technician_cannot_final_close_a_repair(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    close = await client.post(
        f"/api/v1/repairs/{repair_id}/close", json={}, headers=_as("TECHNICIAN")
    )
    assert close.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_can_final_close_a_repair(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    close = await client.post(
        f"/api/v1/repairs/{repair_id}/close", json={}, headers=_as("MAINTENANCE")
    )
    assert close.status_code == 200
    assert close.json()["repair"]["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_driver_cannot_open_a_pm_work_order(client: AsyncClient) -> None:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
        headers=_as("DRIVER"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": plan_id},
        headers=_as("DRIVER"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_technician_cannot_final_close_a_pm_work_order(client: AsyncClient) -> None:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    open_response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    work_order_id = open_response.json()["work_order"]["pm_work_order_id"]

    close = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/close", json={}, headers=_as("TECHNICIAN")
    )
    assert close.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_can_open_approve_assign_and_close_pm(client: AsyncClient) -> None:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    open_response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    assert open_response.status_code == 200
    work_order = open_response.json()["work_order"]
    work_order_id = work_order["pm_work_order_id"]

    approve = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/scope/approve", headers=_as("MAINTENANCE")
    )
    assert approve.status_code == 200

    # Legacy cancelled (DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107): MAINTENANCE assigns the V2 team,
    # the PRIMARY starts, records every item and submits, and MAINTENANCE closes after review (E01).
    close = await http_complete_and_close(client, work_order_id)
    assert close.status_code == 200, close.text
    assert close.json()["work_order"]["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# 17-19 — Finding / PM defect never auto-create an RPR under non-Maintenance
# authority; traceability survives Repair Request conversion (already
# proven above; this covers the Finding/PM_RESULT source specifically).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_maintenance_finding_action_does_not_create_an_rpr_directly(
    client: AsyncClient,
) -> None:
    checklist = await client.get(
        "/api/v1/checklists/active",
        params={"asset_type": "VEHICLE"},
        headers=_as("DRIVER"),
    )
    items = [
        # R3-15 (deliberate migration): an abnormal result needs a remark.
        {"item_id": i["item_id"], "result": "FAIL" if index == 0 else "PASS",
         "remark": "E2E abnormal" if index == 0 else None}
        for index, i in enumerate(checklist.json()["items"])
    ]
    inspection = await client.post(
        "/api/v1/inspections",
        # R3 S2 (deliberate migration): one request id per submission
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
        headers={**_as("DRIVER"), "X-Request-Id": str(uuid.uuid4())},
    )
    assert inspection.status_code == 200
    finding_id = inspection.json()["findings"][0]["finding_id"]

    repair_attempt = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "FINDING",
            "source_id": finding_id,
            "symptom": "พบข้อบกพร่องระหว่างตรวจเช็ค",
        },
        headers=_as("DRIVER"),
    )
    assert repair_attempt.status_code == 403


@pytest.mark.asyncio
async def test_pm_technician_defect_does_not_create_an_rpr_directly(client: AsyncClient) -> None:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    open_response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    work_order = open_response.json()["work_order"]
    # REV06 section 13 / Legacy cancelled: the reporting technician is the PRIMARY of the V2 team and
    # records the defect as a Not Performed item (E01: after a Performed one), so this still exercises
    # "reporting a PM defect never grants implicit RPR authority", not the unassigned-denied case.
    wo_id = work_order["pm_work_order_id"]
    await http_start(client, wo_id)
    performed = await http_save(client, wo_id, work_order["scope_task_ids"][1])
    assert performed.status_code == 200, performed.text
    result = await http_save(client, wo_id, work_order["scope_task_ids"][0], "NOT_PERFORMED")
    assert result.status_code == 200, result.text
    pm_result_id = result.json()["result"]["pm_work_result_id"]

    repair_attempt = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
            "symptom": "พบข้อบกพร่องระหว่างทำ PM",
        },
        headers=_as("TECHNICIAN", SEED_PRIMARY_USER),
    )
    assert repair_attempt.status_code == 403


# ---------------------------------------------------------------------------
# 33-35 — permission extensibility: the gate is capability-driven, never a
# hard-coded role-name check.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unrecognized_role_name_grants_no_capability_fail_closed(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("SOME_FUTURE_ROLE_NOT_YET_DEFINED"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_granting_a_new_role_the_capability_is_enough_no_route_code_change(
    client: AsyncClient,
) -> None:
    """REV05 section 10/33-35: the route only ever checks
    `can_manage_repair`; whether a given role name carries it is pure data
    in `app.domain.authz.ROLE_CAPABILITIES`. Adding a brand-new role here
    and granting it the capability is enough to change what that role can
    do — proving business/route code never special-cases a role name."""
    from app.domain.authz import CAN_MANAGE_REPAIR, ROLE_CAPABILITIES

    ROLE_CAPABILITIES["DISPATCHER_PILOT_ROLE"] = frozenset({CAN_MANAGE_REPAIR})
    try:
        response = await client.post(
            "/api/v1/repairs",
            json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
            headers=_as("DISPATCHER_PILOT_ROLE"),
        )
        assert response.status_code == 200
    finally:
        del ROLE_CAPABILITIES["DISPATCHER_PILOT_ROLE"]


# ---------------------------------------------------------------------------
# 36-38 — no-regression / no-invention structural checks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_waiting_parts_status_and_no_duplicate_tables_introduced(
    client: AsyncClient,
) -> None:
    from app.domain.repair import RepairStatus
    from app.repositories.google_sheets import schemas as sheet_schemas

    # R3 TS-7 (deliberate migration): CANCELLED is the R3 round cancelled before any
    # recorded work. Still no waiting-parts / awaiting-parts lifecycle status.
    assert {member.value for member in RepairStatus} == {"OPEN", "CLOSED", "CANCELLED"}

    # INTENTIONAL CONTRACT EVOLUTION (R2 Batch R2f-a, Final Contract C1 §2):
    # "technician_master" is no longer a forbidden duplicate table — R2f
    # supersedes "no technician master" and reads the live tab, READ ONLY and
    # bounded. It may appear only as that read schema, never as a write path.
    from tests.test_relationship_read_batch_r2f_a import (
        assert_reference_surface_is_read_only,
    )

    assert_reference_surface_is_read_only()
    technician_tabs = {
        name for name, value in vars(sheet_schemas).items()
        if "technician_master" in getattr(value, "tab_name", "")
    }
    assert technician_tabs == {"TECHNICIAN_MASTER_READ_SHEET"}

    forbidden_fragments = (
        "waiting_assignment",
        "waiting_parts",
        "manual_repair",
        "driver_repair_order",
    )
    all_tab_names = {
        value.tab_name for value in vars(sheet_schemas).values() if hasattr(value, "tab_name")
    }
    for fragment in forbidden_fragments:
        assert not any(fragment in name for name in all_tab_names)
    assert "repair_request" in all_tab_names


@pytest.mark.asyncio
async def test_repair_request_report_captures_automatic_snapshot_never_manual(
    client: AsyncClient,
) -> None:
    body = await _submit_repair_request(client)
    meter_snapshot_id = body["meter_snapshot_id"]
    assert meter_snapshot_id is not None

    snapshot = await client.get(f"/api/v1/meter-snapshots/{meter_snapshot_id}")
    assert snapshot.status_code == 200
    assert snapshot.json()["is_automatic"] is True

    location = await client.get(f"/api/v1/location-snapshots/by-event/{meter_snapshot_id}")
    assert location.status_code == 200
    linked = location.json()
    assert len(linked) == 1
    assert linked[0]["event_type"] == "REPAIR_REQUEST_REPORT"
    assert linked[0]["latitude"] is None and linked[0]["gps_valid"] is False
