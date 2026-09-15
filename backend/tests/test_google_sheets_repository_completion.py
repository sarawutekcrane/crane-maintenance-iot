"""Google Sheets repository completion pass — tests for every method that
used to be a true stub (a body consisting solely of
`self._require_configured(...)`) and is now real, header-mapped I/O
against a FAKE in-memory `gspread`-shaped client (never the real Google
API/network — see `tests/test_google_sheets_real_io.py`'s module
docstring and REV05 section 11G).

Covers: Vehicle/Model/Equipment, Checklist/Inspection, PM, and
Part/Part-Set/Instance/Lifetime. Also includes the AST regression test
that fails if any async repository method reverts to a true stub.
"""
from __future__ import annotations

import ast
from datetime import date

import pytest

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue
from app.domain.common import OperationalStatus, PageParams
from app.domain.equipment import EquipmentCategory
from app.domain.inspection import FindingStatus, NewInspectionItemInput
from app.domain.lifetime_rule import LifetimeRuleScope, LifetimeTriggerType
from app.domain.part import PartSetItemRequirement, TrackingMode
from app.domain.part_instance import LifecycleStartReason, PartInstanceStatus, PriorUsage, PriorUsageQuality
from app.domain.pm import PmTriggerType, PmWorkOrderStatus
from app.domain.vehicle_model import ComponentRole
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import schemas
from tests.test_google_sheets_real_io import FakeWorksheet, _repo_with_fake_sheets, _ws


# ---------------------------------------------------------------------------
# AST regression: fail if any repository method reverts to a true stub.
# ---------------------------------------------------------------------------


def test_no_repository_method_is_a_true_stub() -> None:
    path = "app/repositories/google_sheets/repository.py"
    tree = ast.parse(open(path).read())
    class_node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "GoogleSheetsRepository"
    )

    def _is_true_stub(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
        stmts = node.body
        if (
            stmts
            and isinstance(stmts[0], ast.Expr)
            and isinstance(stmts[0].value, ast.Constant)
            and isinstance(stmts[0].value.value, str)
        ):
            stmts = stmts[1:]
        if len(stmts) != 1:
            return False
        stmt = stmts[0]
        call = None
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
        elif isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
            call = stmt.value
        if call is None:
            return False
        func = call.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "_require_configured"
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        )

    stubs = [
        node.name
        for node in class_node.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and _is_true_stub(node)
    ]
    assert stubs == [], f"Found true stubs that must be implemented: {stubs}"


# ---------------------------------------------------------------------------
# Vehicle / Model / Equipment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_models_empty_sheet_returns_empty_not_error() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.VEHICLE_MODEL_SHEET), _ws(schemas.PM_PLAN_SHEET))
    items, total = await repo.list_vehicle_models(q=None, params=PageParams())
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_vehicle_models_filters_q_and_resolves_plan_id_and_paginates() -> None:
    model_ws = _ws(schemas.VEHICLE_MODEL_SHEET)
    model_ws.append_row(
        ["MDL-1", "MC-1", "Crane One", "", "", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "PLAN1"]
    )
    model_ws.append_row(
        ["MDL-2", "MC-2", "Loader Two", "", "", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", ""]
    )
    plan_ws = _ws(schemas.PM_PLAN_SHEET)
    plan_ws.append_row(
        ["PMP-0001", "PLAN1", "VEHICLE", "Plan 1", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]
    )
    repo = _repo_with_fake_sheets(model_ws, plan_ws)

    all_models, total = await repo.list_vehicle_models(q=None, params=PageParams())
    assert total == 2
    by_id = {m.model_id: m for m in all_models}
    assert by_id["MDL-1"].assigned_pm_plan_id == "PMP-0001"
    assert by_id["MDL-2"].assigned_pm_plan_id is None

    filtered, filtered_total = await repo.list_vehicle_models(q="crane", params=PageParams())
    assert filtered_total == 1
    assert filtered[0].model_id == "MDL-1"

    page1, total_paged = await repo.list_vehicle_models(q=None, params=PageParams(page=1, page_size=1))
    assert total_paged == 2
    assert len(page1) == 1


@pytest.mark.asyncio
async def test_list_vehicles_empty_filters_q_status_model_pagination_and_null_serial() -> None:
    ws = _ws(schemas.VEHICLE_SHEET)
    repo = _repo_with_fake_sheets(ws)
    items, total = await repo.list_vehicles(
        q=None, operational_status=None, model_id=None, params=PageParams()
    )
    assert items == []
    assert total == 0

    ws.append_row(["VEH-1", "220/1", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    ws.append_row(["VEH-2", "220/2", "MDL-2", "SN-2", "MAINTENANCE", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])

    all_vehicles, total = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
    assert total == 2
    veh1 = next(v for v in all_vehicles if v.vehicle_id == "VEH-1")
    assert veh1.machine_no == "220/1"  # opaque, never normalized
    assert veh1.serial_number is None  # blank -> None, never ""

    by_status, total_status = await repo.list_vehicles(
        q=None, operational_status=OperationalStatus.MAINTENANCE, model_id=None, params=PageParams()
    )
    assert total_status == 1
    assert by_status[0].vehicle_id == "VEH-2"

    by_model, total_model = await repo.list_vehicles(q=None, operational_status=None, model_id="MDL-1", params=PageParams())
    assert total_model == 1
    assert by_model[0].vehicle_id == "VEH-1"

    by_q, total_q = await repo.list_vehicles(q="220/2", operational_status=None, model_id=None, params=PageParams())
    assert total_q == 1
    assert by_q[0].vehicle_id == "VEH-2"

    page1, total_paged = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams(page=1, page_size=1))
    assert total_paged == 2
    assert len(page1) == 1


@pytest.mark.asyncio
async def test_update_vehicle_machine_no_preserves_slash_and_updates_only_target_row() -> None:
    ws = _ws(schemas.VEHICLE_SHEET)
    ws.append_row(["VEH-1", "220/1", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    ws.append_row(["VEH-2", "220/2", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    repo = _repo_with_fake_sheets(ws)

    updated = await repo.update_vehicle_machine_no("VEH-1", "220/3")
    assert updated.machine_no == "220/3"  # distinct opaque number, never normalized

    other = await repo.get_vehicle("VEH-2")
    assert other.machine_no == "220/2"  # untouched


@pytest.mark.asyncio
async def test_update_vehicle_machine_no_not_found_raises() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.VEHICLE_SHEET))
    with pytest.raises(RepositoryError):
        await repo.update_vehicle_machine_no("VEH-missing", "1/1")


@pytest.mark.asyncio
async def test_change_vehicle_status_appends_history_and_updates_current_status() -> None:
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(["VEH-1", "220/1", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    history_ws = _ws(schemas.VEHICLE_STATUS_HISTORY_SHEET)
    repo = _repo_with_fake_sheets(vehicle_ws, history_ws)

    entry = await repo.change_vehicle_status(
        "VEH-1", OperationalStatus.MAINTENANCE, changed_by="user-1", note="ซ่อมบำรุง"
    )
    assert entry.status == OperationalStatus.MAINTENANCE
    assert len(history_ws.rows) == 1

    vehicle = await repo.get_vehicle("VEH-1")
    assert vehicle.operational_status == OperationalStatus.MAINTENANCE

    entry2 = await repo.change_vehicle_status("VEH-1", OperationalStatus.READY, changed_by="user-1", note=None)
    assert len(history_ws.rows) == 2  # append-only, never overwritten

    history = await repo.list_vehicle_status_history("VEH-1")
    assert len(history) == 2
    assert history[0].history_id == entry2.history_id  # newest first


@pytest.mark.asyncio
async def test_list_equipment_empty_filters_and_pagination() -> None:
    ws = _ws(schemas.EQUIPMENT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    items, total = await repo.list_equipment(q=None, category=None, params=PageParams())
    assert items == []
    assert total == 0

    ws.append_row(["EQP-1", "EC-1", "เครื่องกลึง", "LATHE", "", "", "", "READY", "TRUE", "", ""])
    ws.append_row(["EQP-2", "EC-2", "ปั๊มลม", "AIR_COMPRESSOR", "", "", "", "READY", "TRUE", "", ""])

    all_items, total = await repo.list_equipment(q=None, category=None, params=PageParams())
    assert total == 2

    by_category, total_category = await repo.list_equipment(
        q=None, category=EquipmentCategory.AIR_COMPRESSOR, params=PageParams()
    )
    assert total_category == 1
    assert by_category[0].equipment_id == "EQP-2"

    by_q, total_q = await repo.list_equipment(q="กลึง", category=None, params=PageParams())
    assert total_q == 1
    assert by_q[0].equipment_id == "EQP-1"

    page1, total_paged = await repo.list_equipment(q=None, category=None, params=PageParams(page=1, page_size=1))
    assert total_paged == 2
    assert len(page1) == 1


# ---------------------------------------------------------------------------
# Checklist / Inspection
# ---------------------------------------------------------------------------


def _checklist_sheets() -> tuple[FakeWorksheet, FakeWorksheet, FakeWorksheet]:
    master_ws = _ws(schemas.CHECKLIST_MASTER_SHEET)
    master_ws.append_row(["CHK-1", "VEHICLE", "DAILY", "Daily Checklist", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    revision_ws = _ws(schemas.CHECKLIST_REVISION_SHEET)
    revision_ws.append_row(["REV-1", "CHK-1", "1", "2025-01-01", "2025-01-01T00:00:00+00:00"])
    revision_ws.append_row(["REV-2", "CHK-1", "2", "2099-01-01", "2099-01-01T00:00:00+00:00"])  # future, not yet active
    item_ws = _ws(schemas.CHECKLIST_ITEM_SHEET)
    item_ws.append_row(["ITEM-1", "REV-1", "1", "Brake check", "", "", "", "", "", "", "FALSE", "FALSE", "TRUE"])
    item_ws.append_row(["ITEM-2", "REV-2", "1", "Future item", "", "", "", "", "", "", "FALSE", "FALSE", "FALSE"])
    return master_ws, revision_ws, item_ws


@pytest.mark.asyncio
async def test_get_active_checklist_revision_picks_by_stored_effective_date_not_highest_number() -> None:
    master_ws, revision_ws, item_ws = _checklist_sheets()
    repo = _repo_with_fake_sheets(master_ws, revision_ws, item_ws)

    detail = await repo.get_active_checklist_revision(AssetType.VEHICLE)
    assert detail is not None
    assert detail.revision.revision_id == "REV-1"  # REV-2 is not yet effective
    assert len(detail.items) == 1
    assert detail.items[0].item_id == "ITEM-1"


@pytest.mark.asyncio
async def test_get_checklist_revision_reads_exact_historical_revision() -> None:
    master_ws, revision_ws, item_ws = _checklist_sheets()
    repo = _repo_with_fake_sheets(master_ws, revision_ws, item_ws)

    detail = await repo.get_checklist_revision("CHK-1", "REV-2")
    assert detail is not None
    assert detail.revision.revision_number == 2

    missing = await repo.get_checklist_revision("CHK-1", "REV-missing")
    assert missing is None


@pytest.mark.asyncio
async def test_create_inspection_then_get_round_trips_and_creates_finding_for_fail() -> None:
    repo = _repo_with_fake_sheets(
        _ws(schemas.INSPECTION_SHEET),
        _ws(schemas.INSPECTION_ITEM_RESULT_SHEET),
        _ws(schemas.INSPECTION_FINDING_SHEET),
    )
    items = [
        NewInspectionItemInput(
            item_id="ITEM-1", sequence=1, title="Brake check", is_critical=True, result=InspectionResultValue.FAIL
        ),
        NewInspectionItemInput(
            item_id="ITEM-2", sequence=2, title="Lights", is_critical=False, result=InspectionResultValue.PASS
        ),
    ]
    created = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=items,
        machine_state_snapshot_id="MSNAP-0001",
    )
    assert len(created.items) == 2
    assert len(created.findings) == 1
    assert created.findings[0].item_title == "Brake check"

    reread = await repo.get_inspection(created.header.inspection_id)
    assert reread is not None
    assert reread.header.asset_id == "VEH-1"
    assert reread.header.machine_state_snapshot_id == "MSNAP-0001"
    assert len(reread.items) == 2
    assert len(reread.findings) == 1
    assert reread.findings[0].status == FindingStatus.OPEN

    finding = await repo.find_inspection_finding(reread.findings[0].finding_id)
    assert finding is not None
    result = await repo.find_inspection_result(reread.items[0].result_id)
    assert result is not None

    findings = await repo.list_inspection_findings(asset_type=AssetType.VEHICLE, asset_id="VEH-1", status=FindingStatus.OPEN)
    assert len(findings) == 1

    summaries, total = await repo.list_inspections(asset_type=None, asset_id=None, params=PageParams())
    assert total == 1
    assert summaries[0].fail_count == 1
    assert summaries[0].pass_count == 1
    assert summaries[0].has_fail is True


@pytest.mark.asyncio
async def test_find_inspection_result_and_finding_not_found_returns_none() -> None:
    repo = _repo_with_fake_sheets(
        _ws(schemas.INSPECTION_ITEM_RESULT_SHEET), _ws(schemas.INSPECTION_FINDING_SHEET)
    )
    assert await repo.find_inspection_result("RES-missing") is None
    assert await repo.find_inspection_finding("FND-missing") is None


# ---------------------------------------------------------------------------
# PM
# ---------------------------------------------------------------------------


def _pm_plan_and_revision_sheets() -> dict[str, FakeWorksheet]:
    plan_ws = _ws(schemas.PM_PLAN_SHEET)
    plan_ws.append_row(["PMP-0001", "PLAN1", "VEHICLE", "Plan 1", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    revision_ws = _ws(schemas.PM_TASK_REVISION_SHEET)
    revision_ws.append_row(["PTR-1", "PMP-0001", "1", "2025-01-01", "", "2025-01-01T00:00:00+00:00"])
    task_ws = _ws(schemas.PM_TASK_SHEET)
    task_ws.append_row(["PMT-1", "PTR-1", "1", "ENGINE", "Change oil", "ENGINE_HOUR", "250", "hr"])
    task_ws.append_row(["PMT-2", "PTR-1", "2", "ENGINE", "Check belts", "", "", ""])
    task_part_ws = _ws(schemas.PM_TASK_PART_SHEET)
    task_part_ws.append_row(["PTP-1", "PMT-1", "Engine oil 15W-40", "10", "L"])
    return {
        "plan": plan_ws,
        "revision": revision_ws,
        "task": task_ws,
        "task_part": task_part_ws,
    }


@pytest.mark.asyncio
async def test_list_pm_plans_filters_by_asset_type_and_model() -> None:
    ws = _ws(schemas.PM_PLAN_SHEET)
    ws.append_row(["PMP-0001", "PLAN1", "VEHICLE", "Plan 1", "MDL-1,MDL-2", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    ws.append_row(["PMP-0002", "PLAN2", "EQUIPMENT", "Plan 2", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
    repo = _repo_with_fake_sheets(ws)

    vehicle_plans = await repo.list_pm_plans(asset_type=AssetType.VEHICLE, model_id=None)
    assert [p.pm_plan_id for p in vehicle_plans] == ["PMP-0001"]

    scoped = await repo.list_pm_plans(asset_type=AssetType.VEHICLE, model_id="MDL-1")
    assert len(scoped) == 1
    unscoped = await repo.list_pm_plans(asset_type=AssetType.VEHICLE, model_id="MDL-999")
    assert unscoped == []


@pytest.mark.asyncio
async def test_get_active_and_exact_pm_task_revision_join_standard_parts() -> None:
    sheets = _pm_plan_and_revision_sheets()
    repo = _repo_with_fake_sheets(*sheets.values())

    active = await repo.get_active_pm_task_revision("PMP-0001")
    assert active is not None
    assert len(active.tasks) == 2
    task1 = next(t for t in active.tasks if t.pm_task_id == "PMT-1")
    assert len(task1.standard_parts) == 1
    assert task1.standard_parts[0].part_description == "Engine oil 15W-40"

    exact = await repo.get_pm_task_revision("PMP-0001", "PTR-1")
    assert exact is not None
    assert exact.revision.revision_id == "PTR-1"

    missing = await repo.get_pm_task_revision("PMP-0001", "PTR-missing")
    assert missing is None


@pytest.mark.asyncio
async def test_create_pm_work_order_persists_scope_and_get_round_trips() -> None:
    sheets = _pm_plan_and_revision_sheets()
    work_order_ws = _ws(schemas.PM_WORK_ORDER_SHEET)
    scope_ws = _ws(schemas.PM_WORK_SCOPE_SHEET)
    assignment_ws = _ws(schemas.PM_WORK_ASSIGNMENT_SHEET)
    result_ws = _ws(schemas.PM_WORK_RESULT_SHEET)
    used_part_ws = _ws(schemas.PM_USED_PART_SHEET)
    repo = _repo_with_fake_sheets(
        *sheets.values(), work_order_ws, scope_ws, assignment_ws, result_ws, used_part_ws
    )

    created = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        pm_plan_id="PMP-0001",
        revision_id="PTR-1",
        due_reason=PmTriggerType.ENGINE_HOUR,
        opened_by="user-maint",
        note="scheduled",
        opened_snapshot_id="MSNAP-0001",
        scope_task_ids=["PMT-1", "PMT-2"],
    )
    assert created.pm_work_order_id.startswith("PMWO-")
    assert set(created.scope_task_ids) == {"PMT-1", "PMT-2"}
    assert len(scope_ws.rows) == 2

    detail = await repo.get_pm_work_order(created.pm_work_order_id)
    assert detail is not None
    assert detail.work_order.opened_snapshot_id == "MSNAP-0001"
    assert set(detail.work_order.scope_task_ids) == {"PMT-1", "PMT-2"}
    assert detail.work_order.scope_approved_at is None
    assert detail.results == []


@pytest.mark.asyncio
async def test_add_pm_scope_task_then_approve_freezes_all_rows() -> None:
    sheets = _pm_plan_and_revision_sheets()
    work_order_ws = _ws(schemas.PM_WORK_ORDER_SHEET)
    scope_ws = _ws(schemas.PM_WORK_SCOPE_SHEET)
    assignment_ws = _ws(schemas.PM_WORK_ASSIGNMENT_SHEET)
    result_ws = _ws(schemas.PM_WORK_RESULT_SHEET)
    used_part_ws = _ws(schemas.PM_USED_PART_SHEET)
    repo = _repo_with_fake_sheets(
        *sheets.values(), work_order_ws, scope_ws, assignment_ws, result_ws, used_part_ws
    )

    wo = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        pm_plan_id="PMP-0001",
        revision_id="PTR-1",
        due_reason=None,
        opened_by="user-maint",
        note=None,
        scope_task_ids=["PMT-1"],
    )
    audit = await repo.add_pm_scope_task(
        pm_work_order_id=wo.pm_work_order_id, pm_task_id="PMT-2", added_by="user-maint", reason="near due"
    )
    assert audit.pm_task_id == "PMT-2"
    assert len(scope_ws.rows) == 2

    approved = await repo.approve_pm_scope(wo.pm_work_order_id, approved_by="user-maint")
    assert approved.scope_approved_at is not None
    assert approved.scope_approved_by == "user-maint"
    assert set(approved.scope_task_ids) == {"PMT-1", "PMT-2"}

    detail = await repo.get_pm_work_order(wo.pm_work_order_id)
    assert len(detail.scope_additions) == 1
    assert detail.scope_additions[0].pm_task_id == "PMT-2"
    assert detail.scope_additions[0].reason == "near due"


@pytest.mark.asyncio
async def test_assign_pm_work_order_and_history_and_my_work_filter() -> None:
    sheets = _pm_plan_and_revision_sheets()
    work_order_ws = _ws(schemas.PM_WORK_ORDER_SHEET)
    scope_ws = _ws(schemas.PM_WORK_SCOPE_SHEET)
    assignment_ws = _ws(schemas.PM_WORK_ASSIGNMENT_SHEET)
    result_ws = _ws(schemas.PM_WORK_RESULT_SHEET)
    used_part_ws = _ws(schemas.PM_USED_PART_SHEET)
    repo = _repo_with_fake_sheets(
        *sheets.values(), work_order_ws, scope_ws, assignment_ws, result_ws, used_part_ws
    )
    wo = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1", pm_plan_id="PMP-0001", revision_id="PTR-1",
        due_reason=None, opened_by="user-maint", note=None, scope_task_ids=[],
    )
    updated = await repo.assign_pm_work_order(
        wo.pm_work_order_id, primary_technician="tech-1", collaborators=["tech-2"], assigned_by="user-maint"
    )
    assert updated.primary_technician == "tech-1"
    assert updated.collaborators == ["tech-2"]

    history = await repo.list_pm_work_order_assignment_history(wo.pm_work_order_id)
    assert len(history) == 2

    reassigned = await repo.assign_pm_work_order(
        wo.pm_work_order_id, primary_technician="tech-3", collaborators=[], assigned_by="user-maint"
    )
    assert reassigned.primary_technician == "tech-3"
    history_after = await repo.list_pm_work_order_assignment_history(wo.pm_work_order_id)
    assert len(history_after) == 3  # ended rows kept, never deleted
    active_count = sum(1 for e in history_after if e.active_status)
    assert active_count == 1

    my_work, total = await repo.list_pm_work_orders(
        asset_type=None, asset_id=None, params=PageParams(), assigned_to="tech-3"
    )
    assert total == 1
    other_work, other_total = await repo.list_pm_work_orders(
        asset_type=None, asset_id=None, params=PageParams(), assigned_to="tech-1"
    )
    assert other_total == 0  # tech-1's assignment is now ended, not authoritative


@pytest.mark.asyncio
async def test_get_last_closed_pm_work_order_uses_closed_at_not_row_order() -> None:
    sheets = _pm_plan_and_revision_sheets()
    work_order_ws = _ws(schemas.PM_WORK_ORDER_SHEET)
    scope_ws = _ws(schemas.PM_WORK_SCOPE_SHEET)
    assignment_ws = _ws(schemas.PM_WORK_ASSIGNMENT_SHEET)
    result_ws = _ws(schemas.PM_WORK_RESULT_SHEET)
    used_part_ws = _ws(schemas.PM_USED_PART_SHEET)
    repo = _repo_with_fake_sheets(
        *sheets.values(), work_order_ws, scope_ws, assignment_ws, result_ws, used_part_ws
    )
    wo1 = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1", pm_plan_id="PMP-0001", revision_id="PTR-1",
        due_reason=None, opened_by="u", note=None, scope_task_ids=[],
    )
    wo2 = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1", pm_plan_id="PMP-0001", revision_id="PTR-1",
        due_reason=None, opened_by="u", note=None, scope_task_ids=[],
    )
    # Close wo1 (the first-created row) LAST, with a clearly later closed_at
    # than wo2's, and verify selection follows the value, not row order.
    await repo.close_pm_work_order(wo2.pm_work_order_id, closed_by="u", note=None)
    await repo.close_pm_work_order(wo1.pm_work_order_id, closed_by="u", note=None)
    closed_at_index = schemas.PM_WORK_ORDER_SHEET.required_headers.index("closed_at")
    work_order_ws.rows[0][closed_at_index] = "2020-01-01T00:00:00+00:00"  # wo1 (created/closed first) -> earliest
    work_order_ws.rows[1][closed_at_index] = "2030-01-01T00:00:00+00:00"  # wo2 (created first, closed first) -> latest

    last = await repo.get_last_closed_pm_work_order(AssetType.VEHICLE, "VEH-1", "PMP-0001")
    assert last is not None
    assert last.work_order.pm_work_order_id == wo2.pm_work_order_id


@pytest.mark.asyncio
async def test_close_pm_work_order_keeps_existing_note_when_none_given() -> None:
    sheets = _pm_plan_and_revision_sheets()
    work_order_ws = _ws(schemas.PM_WORK_ORDER_SHEET)
    scope_ws = _ws(schemas.PM_WORK_SCOPE_SHEET)
    assignment_ws = _ws(schemas.PM_WORK_ASSIGNMENT_SHEET)
    result_ws = _ws(schemas.PM_WORK_RESULT_SHEET)
    used_part_ws = _ws(schemas.PM_USED_PART_SHEET)
    repo = _repo_with_fake_sheets(
        *sheets.values(), work_order_ws, scope_ws, assignment_ws, result_ws, used_part_ws
    )
    wo = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1", pm_plan_id="PMP-0001", revision_id="PTR-1",
        due_reason=None, opened_by="u", note="original note", scope_task_ids=[],
    )
    closed = await repo.close_pm_work_order(
        wo.pm_work_order_id, closed_by="user-maint", note=None, closed_snapshot_id="MSNAP-0002"
    )
    assert closed.status == PmWorkOrderStatus.CLOSED
    assert closed.note == "original note"
    assert closed.closed_snapshot_id == "MSNAP-0002"


@pytest.mark.asyncio
async def test_create_pm_work_result_persists_used_parts_and_find_round_trips() -> None:
    sheets = _pm_plan_and_revision_sheets()
    work_order_ws = _ws(schemas.PM_WORK_ORDER_SHEET)
    scope_ws = _ws(schemas.PM_WORK_SCOPE_SHEET)
    assignment_ws = _ws(schemas.PM_WORK_ASSIGNMENT_SHEET)
    result_ws = _ws(schemas.PM_WORK_RESULT_SHEET)
    used_part_ws = _ws(schemas.PM_USED_PART_SHEET)
    repo = _repo_with_fake_sheets(
        *sheets.values(), work_order_ws, scope_ws, assignment_ws, result_ws, used_part_ws
    )
    wo = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1", pm_plan_id="PMP-0001", revision_id="PTR-1",
        due_reason=None, opened_by="u", note=None, scope_task_ids=["PMT-1"],
    )
    result = await repo.create_pm_work_result(
        pm_work_order_id=wo.pm_work_order_id,
        pm_task_id="PMT-1",
        revision_id="PTR-1",
        sequence=1,
        task_description="Change oil",
        completed=True,
        meter_snapshot_id="MSNAP-0003",
        remark=None,
        used_parts=[{"part_description": "Engine oil 15W-40", "quantity": 10, "unit": "L"}],
        evidence_attachment_ids=["ATT-0001"],
        performed_by="tech-1",
    )
    assert result.pm_work_result_id.startswith("PMWR-")
    assert len(result.used_parts) == 1
    assert result.used_parts[0].pm_used_part_id.startswith("PMUP-")

    found = await repo.find_pm_work_result(result.pm_work_result_id)
    assert found is not None
    assert found.used_parts[0].part_description == "Engine oil 15W-40"
    assert found.evidence_attachment_ids == ["ATT-0001"]

    detail = await repo.get_pm_work_order(wo.pm_work_order_id)
    assert len(detail.results) == 1
    assert detail.results[0].completed is True


# ---------------------------------------------------------------------------
# Parts / Part Sets / Instances / Lifetime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_part_master_create_get_list_round_trip_with_metadata_and_q() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.PART_MASTER_SHEET))
    created = await repo.create_part_master(
        part_code="PC-1",
        name="Hydraulic hose",
        specification="10mm",
        manufacturer="ACME",
        part_number="HH-10",
        tracking_mode=TrackingMode.CONSUMABLE,
        category="hydraulics",
        metadata={"color": "black"},
    )
    assert created.part_id.startswith("PART-")

    fetched = await repo.get_part_master(created.part_id)
    assert fetched is not None
    assert fetched.metadata == {"color": "black"}
    assert fetched.is_active is True

    items, total = await repo.list_part_masters(q="hydraulic", tracking_mode=None, params=PageParams())
    assert total == 1
    items_mode, total_mode = await repo.list_part_masters(q=None, tracking_mode=TrackingMode.INSTANCE_TRACKED, params=PageParams())
    assert total_mode == 0

    missing = await repo.get_part_master("PART-missing")
    assert missing is None


@pytest.mark.asyncio
async def test_part_set_revision_create_and_read_active_and_exact() -> None:
    repo = _repo_with_fake_sheets(
        _ws(schemas.PART_SET_SHEET), _ws(schemas.PART_SET_REVISION_SHEET), _ws(schemas.PART_SET_ITEM_SHEET),
        _ws(schemas.PART_MASTER_SHEET),
    )
    part_set = await repo.create_part_set("KIT-1", "Basic Service Kit")
    part = await repo.create_part_master(
        part_code="PC-1", name="Filter", specification=None, manufacturer=None, part_number=None,
        tracking_mode=TrackingMode.CONSUMABLE, category=None, metadata={},
    )
    revision_detail = await repo.create_part_set_revision(
        part_set.part_set_id,
        date(2026, 1, 1),
        [{"part_id": part.part_id, "requirement": PartSetItemRequirement.REQUIRED, "quantity": 2, "unit": "pcs"}],
    )
    assert revision_detail.revision.revision_number == 1
    assert len(revision_detail.items) == 1

    active = await repo.get_active_part_set_revision(part_set.part_set_id)
    assert active is not None
    assert active.revision.revision_id == revision_detail.revision.revision_id

    exact = await repo.get_part_set_revision(part_set.part_set_id, revision_detail.revision.revision_id)
    assert exact is not None

    missing_set = await repo.get_part_set("PSET-missing")
    assert missing_set is None


@pytest.mark.asyncio
async def test_part_instance_lifecycle_and_installation_segment_flow() -> None:
    repo = _repo_with_fake_sheets(
        _ws(schemas.PART_INSTANCE_SHEET),
        _ws(schemas.PART_LIFECYCLE_SHEET),
        _ws(schemas.INSTALLATION_SEGMENT_SHEET),
    )
    detail = await repo.create_part_instance(
        part_id="PART-1",
        serial_number="SN-100",
        prior_usage=PriorUsage(quality=PriorUsageQuality.UNKNOWN),
        note=None,
        created_by="user-1",
    )
    assert detail.instance.status == PartInstanceStatus.READY_FOR_INSTALL
    assert len(detail.lifecycles) == 1
    assert detail.instance.prior_usage.value is None  # UNKNOWN never coerced to 0

    reread = await repo.get_part_instance(detail.instance.part_instance_id)
    assert reread is not None

    await repo.update_part_instance_status(detail.instance.part_instance_id, PartInstanceStatus.INSTALLED)
    updated = await repo.get_part_instance(detail.instance.part_instance_id)
    assert updated.instance.status == PartInstanceStatus.INSTALLED

    segment = await repo.create_installation_segment(
        part_instance_id=detail.instance.part_instance_id,
        lifecycle_id=detail.instance.current_lifecycle_id,
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        position_code="POS-1",
        installed_by="user-1",
        baseline_meter_snapshot_id="MSNAP-0001",
        install_note=None,
    )
    assert segment.status.value == "ACTIVE"

    closed_segment = await repo.close_installation_segment(
        segment.segment_id, removed_by="user-1", removal_meter_snapshot_id="MSNAP-0002", removal_reason="transfer"
    )
    assert closed_segment.status.value == "CLOSED"
    assert closed_segment.removed_at is not None

    await repo.start_new_part_lifecycle(
        detail.instance.part_instance_id, LifecycleStartReason.OVERHAUL, started_note="overhaul", started_by="user-2"
    )
    after_overhaul = await repo.get_part_instance(detail.instance.part_instance_id)
    assert len(after_overhaul.lifecycles) == 2
    assert after_overhaul.lifecycles[0].ended_at is not None  # old lifecycle preserved, never deleted
    assert len(after_overhaul.segments) == 1  # old segment still readable

    items, total = await repo.list_part_instances(part_id="PART-1", status=None, params=PageParams())
    assert total == 1


@pytest.mark.asyncio
async def test_position_lifetime_create_get_list() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.POSITION_LIFETIME_SHEET))
    record = await repo.create_position_lifetime(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        position_code="ENGINE-1",
        part_id="PART-1",
        lifetime_rule_id=None,
        baseline_meter_snapshot_id=None,
        prior_usage=PriorUsage(quality=PriorUsageQuality.KNOWN, value=100.0),
        started_by="user-1",
        note=None,
    )
    fetched = await repo.get_position_lifetime(record.position_lifetime_id)
    assert fetched is not None
    assert fetched.prior_usage.value == 100.0

    records = await repo.list_position_lifetime_for_asset(AssetType.VEHICLE, "VEH-1")
    assert len(records) == 1

    missing = await repo.get_position_lifetime("POSLT-missing")
    assert missing is None


@pytest.mark.asyncio
async def test_lifetime_rule_create_get_list() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.LIFETIME_RULE_SHEET))
    rule = await repo.create_lifetime_rule(
        part_id="PART-1",
        scope=LifetimeRuleScope.MODEL,
        model_id="MDL-1",
        vehicle_id=None,
        trigger_type=LifetimeTriggerType.ENGINE_HOUR,
        component_role=ComponentRole.CARRIER_ENGINE,
        first_due_value=250.0,
        interval_value=250.0,
        warning_window_value=20.0,
        note=None,
    )
    fetched = await repo.get_lifetime_rule(rule.lifetime_rule_id)
    assert fetched is not None
    assert fetched.component_role == ComponentRole.CARRIER_ENGINE

    rules = await repo.list_lifetime_rules_for_part("PART-1")
    assert len(rules) == 1

    missing = await repo.get_lifetime_rule("LTR-missing")
    assert missing is None
