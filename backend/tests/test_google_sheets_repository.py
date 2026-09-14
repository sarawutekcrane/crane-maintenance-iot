from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.common import PageParams
from app.domain.vehicle_service import VehicleService
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository
from app.repositories.google_sheets import schemas


@pytest.mark.asyncio
async def test_not_ready_when_unconfigured() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    ready, reason = await repo.check_ready()
    assert ready is False
    assert reason is not None
    assert repo.mode == "google_sheets"


@pytest.mark.asyncio
async def test_vehicle_domain_methods_report_not_configured_until_credentials_exist() -> None:
    """The domain/service layer must not know which repository backs it
    (docs/architecture/API_CONVENTIONS.md). `VehicleService` is exercised
    against `GoogleSheetsRepository` the same way it is against
    `MockRepository`; since no real Google credentials exist in this
    environment, the expected outcome is a controlled `RepositoryError`
    rather than a crash or a silently wrong result.
    """
    settings = Settings(google_sheet_id="", google_application_credentials="")
    service = VehicleService(GoogleSheetsRepository(settings))

    with pytest.raises(RepositoryError):
        await service.list_vehicles(
            q=None, operational_status=None, model_id=None, params=PageParams()
        )


@pytest.mark.asyncio
async def test_equipment_domain_methods_report_not_configured_until_credentials_exist() -> None:
    from app.domain.equipment_service import EquipmentService

    settings = Settings(google_sheet_id="", google_application_credentials="")
    service = EquipmentService(GoogleSheetsRepository(settings))

    with pytest.raises(RepositoryError):
        await service.list_equipment(q=None, category=None, params=PageParams())


# ---------------------------------------------------------------------------
# Core Demo Fixes Delta (REV03 alignment): the live prototype sheet's exact
# tab names take precedence over this module's original Phase 2-5 guesses.
# Every declared tab below must resolve to the delta's given name — never a
# duplicate/alternate/guessed one — and every new sheet the delta lists
# (repair_assignment, pm_work_assignment, pm_work_scope, material_request,
# material_request_line, location_snapshot, equipment_master,
# equipment_status_history) must have declared, stub-backed repository
# support at the same fidelity as every existing Phase 2-5 method (a
# controlled RepositoryError, never a crash or silent wrong result, since
# B03 — Google Auth Method — remains TBD-BLOCKING and no live Google API
# I/O exists anywhere in this repository).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected_tab_name",
    [
        "model_master",
        "vehicle_master",
        "vehicle_component",
        "equipment_master",
        "equipment_status_history",
        "maintenance_plan",
        "pm_task_master",
        "pm_task_part",
        "pm_work_order",
        "pm_work_result",
        "pm_used_part",
        "meter_snapshot",
        "inspection_header",
        "inspection_result",
        "repair_order",
        "repair_action",
        "repair_part",
        "attachment",
        "part_master",
        "current_counter",
        "latest_location",
        "repair_assignment",
        "pm_work_assignment",
        "pm_work_scope",
        "material_request",
        "material_request_line",
        "location_snapshot",
    ],
)
def test_declared_tab_names_match_the_live_prototype_sheet_exactly(expected_tab_name: str) -> None:
    all_tab_names = {
        value.tab_name for value in vars(schemas).values() if hasattr(value, "tab_name")
    }
    assert expected_tab_name in all_tab_names
    # No duplicate/alternate spelling of the same concept exists alongside it
    # (e.g. an old plural guess like "vehicle_models" or "repairs").
    assert len([n for n in all_tab_names if n == expected_tab_name]) == 1


@pytest.mark.asyncio
async def test_repair_assignment_google_sheets_stub_targets_the_correct_tab() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)

    with pytest.raises(RepositoryError, match="repair_assignment"):
        await repo.assign_repair(
            repair_id="RPR-0001", primary_technician="user-1", collaborators=[]
        )
    with pytest.raises(RepositoryError, match="repair_assignment"):
        await repo.list_repair_assignment_history("RPR-0001")


@pytest.mark.asyncio
async def test_pm_work_assignment_google_sheets_stub_targets_the_correct_tab() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)

    with pytest.raises(RepositoryError, match="pm_work_assignment"):
        await repo.assign_pm_work_order(
            pm_work_order_id="PMW-0001", primary_technician="user-1", collaborators=[]
        )
    with pytest.raises(RepositoryError, match="pm_work_assignment"):
        await repo.list_pm_work_order_assignment_history("PMW-0001")


@pytest.mark.asyncio
async def test_pm_work_scope_google_sheets_stub_targets_the_correct_tab() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)

    with pytest.raises(RepositoryError, match="pm_work_scope"):
        await repo.add_pm_scope_task(
            pm_work_order_id="PMW-0001", pm_task_id="PMT-0001", added_by="user-1", reason="x"
        )
    with pytest.raises(RepositoryError, match="pm_work_scope"):
        await repo.approve_pm_scope(pm_work_order_id="PMW-0001", approved_by="user-1")


@pytest.mark.asyncio
async def test_material_request_google_sheets_stub_targets_the_correct_tabs() -> None:
    from app.domain.requisition import RequisitionSourceType

    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)

    with pytest.raises(RepositoryError, match="material_request\\b"):
        await repo.create_material_request(
            source_type=RequisitionSourceType.PM,
            source_work_order_id="PMW-0001",
            vehicle_id="VEH-0001",
            created_by="user-1",
        )
    with pytest.raises(RepositoryError, match="material_request_line"):
        await repo.create_requisition_line(
            material_request_id="MREQ-0001",
            part_id=None,
            part_instance_id=None,
            part_code_snapshot=None,
            part_description="x",
            requested_quantity=1,
            unit="ชิ้น",
            source_task_revision_id=None,
            line_source=None,
            created_by="user-1",
        )


@pytest.mark.asyncio
async def test_location_snapshot_google_sheets_stub_targets_the_correct_tab() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)

    with pytest.raises(RepositoryError, match="location_snapshot"):
        await repo.create_location_snapshot(
            event_type="REPAIR_OPEN",
            event_id="MSNAP-0001",
            vehicle_id="VEH-0001",
            device_id=None,
            latitude=None,
            longitude=None,
            altitude_m=None,
            accuracy_m=None,
            gps_time=None,
            received_at=None,
            gps_valid=False,
            source=None,
        )


@pytest.mark.asyncio
async def test_equipment_google_sheets_stub_targets_the_new_equipment_sheets() -> None:
    """Equipment persistence (including RETIRED, C02) must map onto the
    live sheet's `equipment_master` / `equipment_status_history` tabs, not
    a guessed alternate name."""
    from app.domain.equipment import EquipmentOperationalStatus

    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)

    with pytest.raises(RepositoryError, match="equipment_master"):
        await repo.get_equipment("EQP-0001")
    with pytest.raises(RepositoryError, match="equipment_status_history"):
        await repo.change_equipment_status(
            equipment_id="EQP-0001",
            status=EquipmentOperationalStatus.RETIRED,
            reason="ทดสอบ",
            changed_by="user-1",
        )
