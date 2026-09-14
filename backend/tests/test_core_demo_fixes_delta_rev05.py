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

import pytest
from httpx import AsyncClient


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

    waiting = await client.get("/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE"))
    assert waiting.status_code == 200
    ids = {r["repair_id"] for r in waiting.json()["items"]}
    assert repair["repair_id"] in ids


@pytest.mark.asyncio
async def test_assigning_primary_removes_from_waiting_assignment_and_appears_in_my_work(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    assign = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "user-somchai", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    assert assign.status_code == 200

    waiting = await client.get("/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE"))
    assert repair_id not in {r["repair_id"] for r in waiting.json()["items"]}

    my_work = await client.get(
        "/api/v1/repairs/my-work", headers=_as("TECHNICIAN", user_id="user-somchai")
    )
    assert repair_id in {r["repair_id"] for r in my_work.json()["items"]}


@pytest.mark.asyncio
async def test_collaborators_do_not_replace_the_primary_technician(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    assign = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "user-a", "collaborators": ["user-b", "user-c"]},
        headers=_as("MAINTENANCE"),
    )
    assert assign.status_code == 200
    updated = assign.json()["repair"]
    assert updated["primary_technician"] == "user-a"
    assert set(updated["collaborators"]) == {"user-b", "user-c"}

    waiting = await client.get("/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE"))
    assert repair_id not in {r["repair_id"] for r in waiting.json()["items"]}


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

    assign = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-tech", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    assert assign.status_code == 200

    approve = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/scope/approve", headers=_as("MAINTENANCE")
    )
    assert approve.status_code == 200

    for task_id in work_order["scope_task_ids"]:
        result = await client.post(
            f"/api/v1/pm/work-orders/{work_order_id}/results",
            json={"pm_task_id": task_id, "completed": True},
            headers=_as("TECHNICIAN", user_id="user-tech"),
        )
        assert result.status_code == 200

    close = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/close", json={}, headers=_as("MAINTENANCE")
    )
    assert close.status_code == 200
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
        {"item_id": i["item_id"], "result": "FAIL" if index == 0 else "PASS"}
        for index, i in enumerate(checklist.json()["items"])
    ]
    inspection = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
        headers=_as("DRIVER"),
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
    # REV06 section 13: submitting a PM task result now requires being
    # assigned to THIS work order (or holding can_manage_pm) — assign the
    # technician first so this test still exercises "reporting a PM
    # defect never grants implicit RPR authority", not the separate
    # unassigned-technician-denied case (covered in
    # test_core_demo_fixes_delta_rev06.py).
    await client.post(
        f"/api/v1/pm/work-orders/{work_order['pm_work_order_id']}/assign",
        json={"primary_technician": "dev-user", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    result = await client.post(
        f"/api/v1/pm/work-orders/{work_order['pm_work_order_id']}/results",
        json={"pm_task_id": work_order["scope_task_ids"][0], "completed": False},
        headers=_as("TECHNICIAN"),
    )
    assert result.status_code == 200
    pm_result_id = result.json()["results"][0]["pm_work_result_id"]

    repair_attempt = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
            "symptom": "พบข้อบกพร่องระหว่างทำ PM",
        },
        headers=_as("TECHNICIAN"),
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

    assert {member.value for member in RepairStatus} == {"OPEN", "CLOSED"}

    forbidden_fragments = (
        "technician_master",
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
