"""REV08 live UAT defect (P0 BLOCKER) — repository-level persistence
regression.

Two sequential creates against the same tab must both survive physically
in the (fake) sheet, not just in the returned domain object. This is a
direct regression test for the live symptom: `INS-0001` disappeared the
moment `INS-0002` was created, and `MSNAP-0001..0007` disappeared the
moment `MSNAP-0008` was created — in both cases the *second* independent
`append_row` call silently destroyed everything written by prior calls
to the same tab. See `test_google_sheets_append_write_semantics.py` for
the underlying `GoogleSheetsClient` fix these tests exercise indirectly.
"""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue
from app.domain.common import PageParams
from app.domain.inspection import NewInspectionItemInput
from app.domain.meter import CounterType, MeterReading
from app.repositories.google_sheets import schemas
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws


def _item(item_id: str, sequence: int, result: InspectionResultValue) -> NewInspectionItemInput:
    return NewInspectionItemInput(
        item_id=item_id, sequence=sequence, title=f"Item {sequence}", is_critical=False, result=result
    )


@pytest.mark.asyncio
async def test_second_inspection_does_not_overwrite_the_first() -> None:
    header_ws = _ws(schemas.INSPECTION_SHEET)
    result_ws = _ws(schemas.INSPECTION_ITEM_RESULT_SHEET)
    finding_ws = _ws(schemas.INSPECTION_FINDING_SHEET)
    repo = _repo_with_fake_sheets(header_ws, result_ws, finding_ws)

    first = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=[_item("ITEM-1", 1, InspectionResultValue.PASS), _item("ITEM-2", 2, InspectionResultValue.FAIL)],
    )
    second = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-2",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=[_item("ITEM-1", 1, InspectionResultValue.PASS), _item("ITEM-2", 2, InspectionResultValue.FAIL)],
    )

    assert first.header.inspection_id != second.header.inspection_id
    # Physical rows: both headers, all four results, both findings.
    assert len(header_ws.rows) == 2
    assert len(result_ws.rows) == 4
    assert len(finding_ws.rows) == 2

    reread_first = await repo.get_inspection(first.header.inspection_id)
    reread_second = await repo.get_inspection(second.header.inspection_id)
    assert reread_first is not None and reread_second is not None
    assert reread_first.header.asset_id == "VEH-1"
    assert reread_second.header.asset_id == "VEH-2"
    assert len(reread_first.items) == 2
    assert len(reread_second.items) == 2

    summaries, total = await repo.list_inspections(asset_type=None, asset_id=None, params=PageParams())
    assert total == 2


@pytest.mark.asyncio
async def test_second_meter_snapshot_does_not_overwrite_the_first() -> None:
    snapshot_ws = _ws(schemas.METER_SNAPSHOT_SHEET)
    reading_ws = _ws(schemas.METER_READING_SHEET)
    repo = _repo_with_fake_sheets(snapshot_ws, reading_ws)

    first = await repo.create_meter_snapshot(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        readings=[MeterReading(component_id=None, counter_type=CounterType.ENGINE_HOUR, value=100.0)],
        recorded_by="user-1",
    )
    second = await repo.create_meter_snapshot(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        readings=[MeterReading(component_id=None, counter_type=CounterType.ENGINE_HOUR, value=105.0)],
        recorded_by="user-1",
    )

    assert first.meter_snapshot_id != second.meter_snapshot_id
    assert len(snapshot_ws.rows) == 2
    assert len(reading_ws.rows) == 2

    reread_first = await repo.get_meter_snapshot(first.meter_snapshot_id)
    reread_second = await repo.get_meter_snapshot(second.meter_snapshot_id)
    assert reread_first is not None and reread_second is not None
    assert reread_first.readings[0].value == 100.0
    assert reread_second.readings[0].value == 105.0


@pytest.mark.asyncio
async def test_second_location_snapshot_does_not_overwrite_the_first() -> None:
    location_ws = _ws(schemas.LOCATION_SNAPSHOT_SHEET)
    repo = _repo_with_fake_sheets(location_ws)

    await repo.create_location_snapshot(
        event_type="REPAIR_OPEN",
        event_id="MSNAP-0001",
        vehicle_id="VEH-1",
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
    await repo.create_location_snapshot(
        event_type="REPAIR_OPEN",
        event_id="MSNAP-0002",
        vehicle_id="VEH-1",
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

    assert len(location_ws.rows) == 2


@pytest.mark.asyncio
async def test_second_repair_request_does_not_overwrite_the_first() -> None:
    request_ws = _ws(schemas.REPAIR_REQUEST_SHEET)
    repo = _repo_with_fake_sheets(request_ws)

    first = await repo.create_repair_request(
        vehicle_id="VEH-1",
        reported_by_user_id="user-1",
        reporter_type="TECHNICIAN",
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="อาการที่ 1",
        priority=None,
        note_th=None,
    )
    second = await repo.create_repair_request(
        vehicle_id="VEH-1",
        reported_by_user_id="user-1",
        reporter_type="TECHNICIAN",
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="อาการที่ 2",
        priority=None,
        note_th=None,
    )

    assert first.repair_request_id != second.repair_request_id
    assert len(request_ws.rows) == 2

    reread_first = await repo.get_repair_request(first.repair_request_id)
    reread_second = await repo.get_repair_request(second.repair_request_id)
    assert reread_first is not None and reread_second is not None
    assert reread_first.symptom_th == "อาการที่ 1"
    assert reread_second.symptom_th == "อาการที่ 2"


@pytest.mark.asyncio
async def test_batch_inspection_pass_and_fail_stores_both_results_physically() -> None:
    header_ws = _ws(schemas.INSPECTION_SHEET)
    result_ws = _ws(schemas.INSPECTION_ITEM_RESULT_SHEET)
    finding_ws = _ws(schemas.INSPECTION_FINDING_SHEET)
    repo = _repo_with_fake_sheets(header_ws, result_ws, finding_ws)

    created = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="UAT-VEH-001",
        checklist_id="CHK-0001",
        revision_id="REV-0001",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=[
            _item("CHKITEM-UAT-001", 1, InspectionResultValue.PASS),
            _item("CHKITEM-UAT-002", 2, InspectionResultValue.FAIL),
        ],
        machine_state_snapshot_id="MSNAP-0007",
    )

    assert len(result_ws.rows) == 2
    result_ids_in_sheet = [row[0] for row in result_ws.rows]
    assert len(set(result_ids_in_sheet)) == 2
    assert len(created.items) == 2
    assert {item.result for item in created.items} == {InspectionResultValue.PASS, InspectionResultValue.FAIL}
