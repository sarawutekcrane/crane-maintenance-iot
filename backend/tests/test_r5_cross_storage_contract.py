"""R5 T7 — cross-storage contract (Revision 4 §5.7). [SIMULATION]

Google Sheets is TEST-ONLY: every R5 write refuses with the stable
FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE error and zero Sheets writes; R5 reads are
truthfully empty; the Repair `*_once` methods keep the pre-R5 (non-idempotent)
behaviour; no Sheets tab is added. Mock implements every R5 method. The enumerated
list is the R11 obligation: a PostgreSQL repository must override all of it."""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.domain.common import OperationalStatus
from app.domain.vehicle import VehicleStatusTimeCorrection
from app.domain.work_time import RepairSubstatePeriod, WorkTimeConfirmation, WorkTimeEntry
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from app.repositories.google_sheets import schemas as sheet_schemas
from app.repositories.mock.repository import MockRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import FakeSheetsBackend, _repo

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)

R5_WRITES = ("append_repair_substates", "append_work_time_record", "append_work_time_confirmation",
             "append_vehicle_status_event_effective", "append_vehicle_status_time_correction")
R5_READS = ("list_repair_substates", "list_work_time_records", "list_work_time_records_for_assignee",
            "list_work_time_confirmations", "list_vehicle_status_time_corrections")
R5_REPLAY = ("find_vehicle_status_request", "get_repair_request_record", "add_repair_action_once",
             "add_repair_part_once", "close_repair_once", "get_repair_close_capture", "record_repair_close_capture")
R11_OVERRIDE_CONTRACT = R5_WRITES + R5_READS + R5_REPLAY


def sheets_repo():
    backend = FakeSheetsBackend({"repair_order": [["repair_id"]]})
    return backend, _repo(backend)


def _entry() -> WorkTimeEntry:
    return WorkTimeEntry(entry_id="E", revision=1, record_kind="ENTRY", work_kind="REPAIR", job_id="RPR-1",
                         technician_id="T", started_at=NOW, ended_at=NOW.replace(hour=4), time_class="REGULAR",
                         description="d", recorded_by="u", recorded_at=NOW, request_id="r", request_fingerprint="f")


@pytest.mark.asyncio
async def test_every_r5_write_fails_closed_on_sheets_with_zero_writes() -> None:
    backend, repo = sheets_repo()
    period = RepairSubstatePeriod(period_id="P", revision=1, record_kind="ENTRY", repair_id="RPR-1",
                                  substate="REPAIRING", started_at=NOW, recorded_by="u", recorded_at=NOW,
                                  request_id="r", request_fingerprint="f")
    confirmation = WorkTimeConfirmation(confirmation_id="C", work_kind="REPAIR", job_id="RPR-1", entries=("E@1",),
                                        confirmed_by="m", confirmed_at=NOW, request_id="r", request_fingerprint="f")
    correction = VehicleStatusTimeCorrection(correction_id="X", vehicle_id="V", history_id="H",
                                             previous_effective_at=NOW, new_effective_at=NOW, reason="r",
                                             corrected_by="m", recorded_at=NOW, request_id="r",
                                             request_fingerprint="f")
    calls = [repo.append_repair_substates([period]), repo.append_work_time_record(_entry()),
             repo.append_work_time_confirmation(confirmation),
             repo.append_vehicle_status_event_effective("V", OperationalStatus.MAINTENANCE, NOW, "m", None, "r", "f"),
             repo.append_vehicle_status_time_correction(correction)]
    for call in calls:
        with pytest.raises(RepositoryFeatureNotImplementedError):
            await call
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r5_reads_on_sheets_are_truthfully_empty_and_read_nothing() -> None:
    backend, repo = sheets_repo()
    assert await repo.list_repair_substates("RPR-1") == []
    assert await repo.list_work_time_records("REPAIR", "RPR-1") == []
    assert await repo.list_work_time_records_for_assignee("T", "TRUE", "B") == []
    assert await repo.list_work_time_confirmations("PM", "PMW-1") == []
    assert await repo.list_vehicle_status_time_corrections("V") == []
    assert await repo.find_vehicle_status_request("V", "r") is None
    assert backend.requests == [] and backend.writes == []


@pytest.mark.asyncio
async def test_sheets_repair_replay_methods_keep_the_pre_r5_behaviour() -> None:
    _, repo = sheets_repo()
    calls = []

    async def add_repair_action(**kwargs):
        calls.append(("action", kwargs["action_text"]))

    async def close_repair(repair_id, **kwargs):
        calls.append(("close", repair_id))
        return "closed"

    repo.add_repair_action = add_repair_action
    repo.close_repair = close_repair
    await repo.add_repair_action_once("RPR-1", "x", "u", [], request_id="r", request_fingerprint="f")
    await repo.add_repair_action_once("RPR-1", "x", "u", [], request_id="r", request_fingerprint="f")
    assert calls == [("action", "x"), ("action", "x")]  # no replay protection on TEST-only Sheets (documented)
    assert await repo.close_repair_once("RPR-1", "m", None, None, request_id="r", request_fingerprint="f") == "closed"
    assert await repo.get_repair_request_record("RPR-1", "r") is None
    await repo.record_repair_close_capture("RPR-1", "r", "SNAP")
    assert await repo.get_repair_close_capture("RPR-1", "r") is None


def test_no_r5_sheets_tab_or_column_is_introduced() -> None:
    names = {value.tab_name for value in vars(sheet_schemas).values() if hasattr(value, "tab_name")}
    assert not [n for n in names if any(word in n for word in ("work_time", "substate", "status_event",
                                                                "downtime", "time_correction"))]
    assert "effective_at" not in sheet_schemas.VEHICLE_STATUS_HISTORY_SHEET.required_headers


def test_the_r11_override_contract_is_complete_in_mock_and_inherited_by_sheets() -> None:
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    for name in R11_OVERRIDE_CONTRACT:
        base = inspect.getattr_static(Repository, name)
        assert not getattr(base, "__isabstractmethod__", False), name  # instantiable storages stay valid
        assert inspect.getattr_static(MockRepository, name) is not base, f"Mock must implement {name}"
        assert inspect.getattr_static(GoogleSheetsRepository, name) is base, f"Sheets must inherit {name}"


@pytest.mark.asyncio
async def test_mock_r5_storage_refuses_conflicts_inside_the_repository() -> None:
    repo = MockRepository()
    first, replayed = await repo.append_work_time_record(_entry())
    assert not replayed
    _, replayed_again = await repo.append_work_time_record(_entry())
    assert replayed_again
    with pytest.raises(ValueError, match="R5_REQUEST_CONFLICT"):
        await repo.append_work_time_record(_entry().model_copy(update={"request_fingerprint": "other"}))
    with pytest.raises(ValueError, match="WORK_TIME_REVISION_STALE"):
        await repo.append_work_time_record(_entry().model_copy(update={"request_id": "r2", "revision": 3}))
    overlap = _entry().model_copy(update={"entry_id": "E2", "request_id": "r3", "job_id": "PMW-1",
                                          "work_kind": "PM"})
    with pytest.raises(ValueError, match="WORK_TIME_OVERLAP"):
        await repo.append_work_time_record(overlap)
    assert len(await repo.list_work_time_records("REPAIR", "RPR-1")) == 1 and first.entry_id == "E"
