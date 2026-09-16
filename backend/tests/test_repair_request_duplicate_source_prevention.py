"""Latest approved Decision B — exact-source duplicate Repair Request
prevention.

Independent audit found: `RepairRequestService.create()` validated that a
named `source_type`/`source_id` (FINDING/PM_RESULT) refers to a real
record, but never checked whether a Repair Request had already been
created from that exact same source — a second `POST /repair-requests`
with the identical `source_type`/`source_id` silently persisted a
duplicate row. The existing frontend gating (`RepairCreatePage`,
`PmWorkOrderDetailPage` both query `GET /repair-requests/by-source/...`
and hide the report form once a request exists) only protects the normal
UI path — a direct/race API call bypassed it entirely (backend
enforcement is what an audit requires; frontend-only is not sufficient).

Fixed by `RepairRequestService._require_source_not_already_reported`,
called right after the existing `_require_defect_source_exists` check and
strictly BEFORE the automatic meter/location snapshot is captured — so a
rejected duplicate attempt never leaves an orphan snapshot. Uses the
existing `Repository.list_repair_requests_by_source` method (already used
elsewhere for the "already reported" UI derivation) — no new repository
method, no schema change, no symptom-text comparison, and MANUAL/
source-less reports are entirely unaffected (the check only runs for
`source_type` values already confirmed to be FINDING/PM_RESULT by
`_require_defect_source_exists`).

API-level tests run against the default `client` fixture (MockRepository,
DEV_AUTH_MODE). Repository-level tests exercise the FAKE in-memory
`gspread`-shaped client from `tests.test_google_sheets_real_io` (never the
real Google API/network — see that module's docstring and REV05 section
11G): no live-sheet I/O happens here.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue
from app.domain.common import PageParams
from app.domain.inspection import NewInspectionItemInput
from app.domain.meter_service import MeterService
from app.domain.repair_service import RepairService
from app.domain.repair_request_service import RepairRequestService
from app.errors import ApiError
from app.repositories.google_sheets import schemas
from app.repositories.mock.repository import MockRepository
from tests.test_defect_provenance import _as, _open_pm_result, _submit_failing_inspection
from tests.test_google_sheets_repair_real_io import _vehicle_row
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws


# ---------------------------------------------------------------------------
# 1. FINDING source: first RRQ succeeds, second with the same finding_id
#    is rejected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_rrq_from_same_finding_is_rejected(client: AsyncClient) -> None:
    inspection = await _submit_failing_inspection(client)
    finding_id = inspection["findings"][0]["finding_id"]

    first = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "พบข้อบกพร่องระหว่างตรวจเช็ค",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    assert first.status_code == 200
    first_repair_request_id = first.json()["request"]["repair_request_id"]

    second = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "แจ้งซ้ำจากคนละคน แต่จุดเดิม",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN", user_id="another-user"),
    )
    assert second.status_code == 422
    body = second.json()["error"]
    assert body["code"] == "REPAIR_REQUEST_SOURCE_ALREADY_REPORTED"
    assert body["details"]["source_type"] == "FINDING"
    assert body["details"]["source_id"] == finding_id
    assert body["details"]["repair_request_id"] == first_repair_request_id

    # No second row was persisted.
    mine = await client.get(
        "/api/v1/repair-requests/mine", headers=_as("TECHNICIAN")
    )
    matching = [r for r in mine.json()["items"] if r.get("source_id") == finding_id]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# 2. PM_RESULT source: first RRQ succeeds, second exact-source RRQ is
#    rejected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_rrq_from_same_pm_result_is_rejected(client: AsyncClient) -> None:
    pm_result_id = await _open_pm_result(client)

    first = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1047",
            "symptom_th": "พบข้อบกพร่องระหว่างทำ PM",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
        },
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert first.status_code == 200
    first_repair_request_id = first.json()["request"]["repair_request_id"]

    second = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1047",
            "symptom_th": "พบข้อบกพร่องระหว่างทำ PM (แจ้งซ้ำ)",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
        },
        headers=_as("TECHNICIAN", "user-pm-tech-1"),
    )
    assert second.status_code == 422
    body = second.json()["error"]
    assert body["code"] == "REPAIR_REQUEST_SOURCE_ALREADY_REPORTED"
    assert body["details"]["repair_request_id"] == first_repair_request_id


# ---------------------------------------------------------------------------
# 3. Different Finding IDs: both RRQs are allowed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_findings_both_allowed(client: AsyncClient) -> None:
    inspection_a = await _submit_failing_inspection(client, vehicle_id="VEH-1046")
    finding_a = inspection_a["findings"][0]["finding_id"]
    inspection_b = await _submit_failing_inspection(client, vehicle_id="VEH-1046")
    finding_b = inspection_b["findings"][0]["finding_id"]
    assert finding_a != finding_b

    response_a = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "จุดที่ 1", "source_type": "FINDING", "source_id": finding_a},
        headers=_as("TECHNICIAN"),
    )
    response_b = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "จุดที่ 2", "source_type": "FINDING", "source_id": finding_b},
        headers=_as("TECHNICIAN"),
    )
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert (
        response_a.json()["request"]["repair_request_id"]
        != response_b.json()["request"]["repair_request_id"]
    )


# ---------------------------------------------------------------------------
# 4. MANUAL/source-less reports: similar/equal symptom text remains
#    allowed — symptom-based dedupe is NOT approved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_reports_with_identical_symptom_text_remain_allowed(
    client: AsyncClient,
) -> None:
    payload = {
        "vehicle_id": "VEH-1046",
        "symptom_th": "เครื่องยนต์มีเสียงดังผิดปกติ",
    }
    first = await client.post("/api/v1/repair-requests", json=payload, headers=_as("DRIVER"))
    second = await client.post("/api/v1/repair-requests", json=payload, headers=_as("DRIVER"))
    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        first.json()["request"]["repair_request_id"]
        != second.json()["request"]["repair_request_id"]
    )
    assert first.json()["request"]["source_type"] is None
    assert second.json()["request"]["source_type"] is None


# ---------------------------------------------------------------------------
# 5 & 7. Rejected duplicate does not create an extra meter/location
#    snapshot or an extra RRQ row — verified directly at the
#    repository/service level for BOTH MockRepository and
#    GoogleSheetsRepository (fake sheets), proving the same behavior
#    through the same service contract.
# ---------------------------------------------------------------------------


async def _seed_finding_mock(repo: MockRepository, vehicle_id: str) -> str:
    detail = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id=vehicle_id,
        checklist_id="CHK-TEST",
        revision_id="REV-TEST",
        revision_number=1,
        inspector_user_id="user-inspector",
        overall_remark=None,
        items=[
            NewInspectionItemInput(
                item_id="ITM-TEST-1",
                sequence=1,
                title="ทดสอบ",
                is_critical=False,
                result=InspectionResultValue.FAIL,
            )
        ],
    )
    return detail.findings[0].finding_id


@pytest.mark.asyncio
async def test_mock_repository_rejected_duplicate_creates_no_orphan_snapshot() -> None:
    repo = MockRepository()
    finding_id = await _seed_finding_mock(repo, "VEH-1046")
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)

    first, first_meter_snapshot_id = await request_service.create(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-a",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="พบข้อบกพร่อง",
        priority=None,
        note_th=None,
        source_type="FINDING",
        source_id=finding_id,
    )
    assert first_meter_snapshot_id is not None
    snapshots_after_first = await repo.list_meter_snapshots_for_asset(AssetType.VEHICLE, "VEH-1046")
    assert len(snapshots_after_first) == 1

    with pytest.raises(ApiError) as exc_info:
        await request_service.create(
            vehicle_id="VEH-1046",
            reported_by_user_id="user-b",
            reporter_type=None,
            reporter_driver_id=None,
            reporter_name_snapshot_th=None,
            report_channel=None,
            symptom_th="พบข้อบกพร่องอีกครั้ง",
            priority=None,
            note_th=None,
            source_type="FINDING",
            source_id=finding_id,
        )
    assert exc_info.value.code == "REPAIR_REQUEST_SOURCE_ALREADY_REPORTED"
    assert exc_info.value.details["repair_request_id"] == first.repair_request_id

    # No orphan meter snapshot (and therefore no orphan location snapshot,
    # which is only ever created paired 1:1 with a meter snapshot via the
    # same event_id — see MeterService.capture_current_state).
    snapshots_after_rejected_attempt = await repo.list_meter_snapshots_for_asset(
        AssetType.VEHICLE, "VEH-1046"
    )
    assert len(snapshots_after_rejected_attempt) == 1

    # No extra Repair Request row.
    pending, total = await repo.list_pending_repair_requests(PageParams())
    assert total == 1


@pytest.mark.asyncio
async def test_google_sheets_repository_rejected_duplicate_creates_no_orphan_snapshot() -> None:
    finding_ws = _ws(schemas.INSPECTION_FINDING_SHEET)
    finding_ws.append_row(
        [
            "FND-0001",
            "INS-0001",
            "RES-0001",
            "VEHICLE",
            "VEH-9001",
            "ตรวจสอบ (SIMULATION_ONLY)",
            "FALSE",
            "OPEN",
            "2026-01-01T00:00:00+00:00",
        ]
    )
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(_vehicle_row("VEH-9001"))
    meter_snapshot_ws = _ws(schemas.METER_SNAPSHOT_SHEET)
    location_snapshot_ws = _ws(schemas.LOCATION_SNAPSHOT_SHEET)
    repair_request_ws = _ws(schemas.REPAIR_REQUEST_SHEET)
    repo = _repo_with_fake_sheets(
        finding_ws,
        vehicle_ws,
        _ws(schemas.VEHICLE_COMPONENT_SHEET),
        meter_snapshot_ws,
        _ws(schemas.METER_READING_SHEET),
        location_snapshot_ws,
        repair_request_ws,
        _ws(schemas.CURRENT_COUNTER_SHEET),
        _ws(schemas.LATEST_LOCATION_SHEET),
    )
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)

    first, first_meter_snapshot_id = await request_service.create(
        vehicle_id="VEH-9001",
        reported_by_user_id="user-a",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="พบข้อบกพร่อง",
        priority=None,
        note_th=None,
        source_type="FINDING",
        source_id="FND-0001",
    )
    assert first_meter_snapshot_id is not None
    assert len(meter_snapshot_ws.rows) == 1
    assert len(location_snapshot_ws.rows) == 1
    assert len(repair_request_ws.rows) == 1

    with pytest.raises(ApiError) as exc_info:
        await request_service.create(
            vehicle_id="VEH-9001",
            reported_by_user_id="user-b",
            reporter_type=None,
            reporter_driver_id=None,
            reporter_name_snapshot_th=None,
            report_channel=None,
            symptom_th="พบข้อบกพร่องอีกครั้ง",
            priority=None,
            note_th=None,
            source_type="FINDING",
            source_id="FND-0001",
        )
    assert exc_info.value.code == "REPAIR_REQUEST_SOURCE_ALREADY_REPORTED"
    assert exc_info.value.details["repair_request_id"] == first.repair_request_id

    # Exact physical row counts prove no orphan meter snapshot, no orphan
    # location snapshot, and no second repair_request row.
    assert len(meter_snapshot_ws.rows) == 1
    assert len(location_snapshot_ws.rows) == 1
    assert len(repair_request_ws.rows) == 1


# ---------------------------------------------------------------------------
# 6. Existing RRQ -> RPR conversion idempotency remains unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rrq_to_rpr_conversion_idempotency_unaffected(client: AsyncClient) -> None:
    inspection = await _submit_failing_inspection(client)
    finding_id = inspection["findings"][0]["finding_id"]

    submitted = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "พบข้อบกพร่อง",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    repair_request_id = submitted.json()["request"]["repair_request_id"]

    first_convert = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert", json={}, headers=_as("MAINTENANCE")
    )
    assert first_convert.status_code == 200
    repair_id = first_convert.json()["repair"]["repair_id"]

    # Idempotent retry: same repair_id, never a second RPR.
    second_convert = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert", json={}, headers=_as("MAINTENANCE")
    )
    assert second_convert.status_code == 200
    assert second_convert.json()["repair"]["repair_id"] == repair_id

    # A second RRQ from the same Finding is still rejected after conversion
    # (the existing RRQ is CONVERTED, not deleted — it still counts as
    # "already reported" for this exact source).
    duplicate_attempt = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "แจ้งซ้ำหลังแปลงเป็นใบงานซ่อมแล้ว",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    assert duplicate_attempt.status_code == 422
    assert duplicate_attempt.json()["error"]["code"] == "REPAIR_REQUEST_SOURCE_ALREADY_REPORTED"
    assert duplicate_attempt.json()["error"]["details"]["repair_request_id"] == repair_request_id
