"""R2 Batch R2-C1 — E2 operational driver assignment, mock / service / API level.

Every row and reference is SYNTHETIC and labelled; no live workbook value is
used. Scheduling cases run against the service in the TEST context with a
FIXED clock (`now`), so "future", "started" and "elapsed" are exact. API cases
run in mock mode (always the TEST context, batch MOCK_TEST_BATCH_ID).

The REV5 acceptance cases are named `test_b<NN>_...` (owner REV5 draft,
SHA-256 f15415d6…dc35); everything else is named after its A2 clause or
decision: E2-AUTH, -MODE, -DQ7, -REASON, -LIFE (cancel / early end / void),
-HO (handover lifecycle), -O3, -STALE, -REPLAY, -FAULT, -CONC, -REAL, -SCOPE,
-DATA, -CONFLICTED, -R2FF, -LEGACY.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.crane_driver_responsibility import CraneDriverResponsibilityService
from app.domain.operational_driver_assignment import OperationalDriverAssignmentService
from app.domain.operational_driver_timeline import OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST, ScopedReferenceRow
from app.repositories.mock.repository import MockRepository

API = "/api/v1"
BATCH = "SYN-R2C1-BATCH"
REASON = "บันทึกการมอบหมายผู้ขับ (ทดสอบ)"
V1, V2 = "VEH-SYN-E2-1", "VEH-SYN-E2-2"
A, B, C, X = "DRV-SYN-A", "DRV-SYN-B", "DRV-SYN-C", "DRV-SYN-X"
UTC = timezone.utc
DAY = {"start_time": "08:00", "end_time": "20:00", "end_day_offset": 0}
NIGHT = {"start_time": "20:00", "end_time": "08:00", "end_day_offset": 1}


def bkk(day: int, hour: int = 0, minute: int = 0, month: int = 11) -> datetime:
    """A Bangkok wall-clock instant in 2026 (UTC+7), as UTC."""
    return datetime(2026, month, day, hour, minute, tzinfo=UTC).replace(tzinfo=UTC) - _SEVEN


_SEVEN = datetime(2026, 1, 1, 7, tzinfo=UTC) - datetime(2026, 1, 1, tzinfo=UTC)
NOW = bkk(18, 12, month=10)  # 2026-10-18 12:00 ICT: every November case is in the future


def ref(key: str, value: str, *, batch: str = BATCH, status: str | None = None, scope: str = REFERENCE_SCOPE_TEST):
    values = {key: value}
    if status is not None:
        values["active_status"] = status
    return ScopedReferenceRow(values=values, scope=scope, test_batch_id=batch if scope == REFERENCE_SCOPE_TEST else "")


class E2Spy(MockRepository):
    """Mock repository with explicit synthetic references; logs public calls."""

    def __init__(self, *, batch: str = BATCH, inactive: tuple[str, ...] = (), yield_on_read: bool = False) -> None:
        super().__init__()
        self._vehicle_reference = [ref("vehicle_id", V1, batch=batch), ref("vehicle_id", V2, batch=batch)]
        self._driver_reference = [ref("driver_id", d, batch=batch, status="INACTIVE" if d in inactive else "ACTIVE")
                                  for d in (A, B, C, X)]
        self._personnel_master = []
        self.calls: list[str] = []
        self.yield_on_read = yield_on_read

    def set_status(self, driver: str, status: str) -> None:
        for r in self._driver_reference:
            if r.values["driver_id"] == driver:
                r.values["active_status"] = status

    def __getattribute__(self, name: str):
        value = object.__getattribute__(self, name)
        if name.startswith("_") or name in ("calls", "set_status", "yield_on_read") or not callable(value):
            return value
        object.__getattribute__(self, "calls").append(name)
        return value

    async def read_operational_driver_assignment_history_validated(self):
        read = await super().read_operational_driver_assignment_history_validated()
        if self.yield_on_read:
            await asyncio.sleep(0)  # let a concurrent request read the same version
        return read


def rows(repo) -> list[dict[str, str]]:
    return repo._operational_driver_assignment_history


class Svc(OperationalDriverAssignmentService):
    def __init__(self, repo, now: datetime = NOW, context: str | None = "TEST", batch: str = BATCH) -> None:
        super().__init__(repo, context, batch)
        self.fixed = now

    def _now(self) -> datetime:
        return self.fixed


async def op(repo, body: dict, *, vehicle: str = V1, now: datetime = NOW, request_id: str | None = None,
             context: str = "TEST"):
    return await Svc(repo, now, context).apply(vehicle, body, request_id=request_id or str(uuid.uuid4()),
                                               user_id="dev-user")


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


def create(driver: str, mode: str, start: str, end: str, shift: dict | None = None, *, handover=None,
           reason: str | None = REASON) -> dict:
    body: dict = {"operation": "CREATE", "driver_id": driver, "mode": mode, "start_date": start, "end_date": end}
    if shift is not None:
        body["shift"] = shift
    if handover is not None:
        body["handover"] = {"predecessor_event_id": handover[0], "expected_revision_no": handover[1]}
    if reason is not None:
        body["reason_th"] = reason
    return body


def nov(day: int) -> str:
    return f"2026-11-{day:02d}"


async def made(repo, body: dict, **kw) -> str:
    outcome = await op(repo, body, **kw)
    assert outcome.changed, outcome
    return outcome.event_ids[0]


async def sched(repo, vehicle: str = V1, now: datetime = NOW, **kw):
    return await Svc(repo, now).vehicle_schedule(vehicle, **kw)


def spans(schedule) -> list[tuple[str, datetime, datetime]]:
    return [(i.driver_id, i.start, i.end) for i in schedule.intervals]


def codes(warnings) -> set[str]:
    return {w.code for w in warnings}


# ---------------------------------------------------------------------------
# REV5 B01–B29 (B30 is the R2-C3 cutover: DEFERRED)
# ---------------------------------------------------------------------------


async def _r2ff_transfer(repo, vehicle: str, driver: str, expected: str | None, date: str) -> None:
    await CraneDriverResponsibilityService(repo, "TEST", BATCH).record_event(
        vehicle, {"operation": "TRANSFER", "driver_id": driver, "effective": {"mode": "DATE", "date": date},
                  "expected_current_driver_id": expected}, request_id=str(uuid.uuid4()), user_id="dev-user")


@pytest.mark.asyncio
async def test_b01_permanent_change_on_v1_leaves_v2_and_e2_unchanged() -> None:
    repo = E2Spy()
    await _r2ff_transfer(repo, V1, A, None, "2026-01-01")
    await _r2ff_transfer(repo, V2, A, None, "2026-01-01")
    await made(repo, create(B, "FULL_DAY", nov(1), nov(20)))
    e2_before = [dict(r) for r in rows(repo)]
    await _r2ff_transfer(repo, V1, C, A, "2026-02-01")  # A1.3 / A5.8: allowed while E2 is open, never blocked
    assert rows(repo) == e2_before  # E2 untouched by an R2f-f change
    v2 = await CraneDriverResponsibilityService(repo, "TEST", BATCH).responsible_drivers(V2)
    assert v2.timeline.current_driver_id == A
    assert spans(await sched(repo)) and {i.driver_id for i in (await sched(repo)).intervals} == {B}


@pytest.mark.asyncio
async def test_b02_no_permanent_driver_warns_but_saves() -> None:
    repo = E2Spy()
    outcome = await op(repo, create(B, "FULL_DAY", nov(1), nov(5)))
    assert outcome.changed and "NO_PERMANENT_RESPONSIBLE_DRIVER" in codes(outcome.warnings)
    assert "NO_PERMANENT_RESPONSIBLE_DRIVER" in codes((await sched(repo)).warnings)


@pytest.mark.asyncio
async def test_b03_permanent_driver_needs_no_daily_e2_and_is_not_claimed_as_driving() -> None:
    repo = E2Spy()
    await _r2ff_transfer(repo, V1, A, None, "2026-01-01")
    s = await sched(repo, now=bkk(10, 10))
    assert (s.current_status, s.current, s.intervals) == ("NONE", None, ())  # no E2 row was auto-created
    assert "NO_PERMANENT_RESPONSIBLE_DRIVER" not in codes(s.warnings)
    assert rows(repo) == []


@pytest.mark.asyncio
async def test_b04_permanent_driver_day_and_other_night_same_dates() -> None:
    repo = E2Spy()
    await _r2ff_transfer(repo, V1, A, None, "2026-01-01")
    await made(repo, create(A, "DAY_SHIFT", nov(10), nov(12), DAY))
    await made(repo, create(B, "NIGHT_SHIFT", nov(10), nov(12), NIGHT))
    s = await sched(repo)
    assert len(s.intervals) == 6 and s.timeline_status == "VALID"


@pytest.mark.asyncio
async def test_b05_two_non_permanent_drivers_day_and_night() -> None:
    repo = E2Spy()
    await _r2ff_transfer(repo, V1, A, None, "2026-01-01")
    await made(repo, create(B, "DAY_SHIFT", nov(10), nov(10), DAY))
    await made(repo, create(C, "NIGHT_SHIFT", nov(10), nov(10), NIGHT))
    assert [d for d, _, _ in spans(await sched(repo))] == [B, C]


@pytest.mark.asyncio
async def test_b06_one_shift_only_the_other_is_never_autofilled() -> None:
    repo = E2Spy()
    await _r2ff_transfer(repo, V1, A, None, "2026-01-01")
    await made(repo, create(B, "DAY_SHIFT", nov(10), nov(10), DAY))
    s = await sched(repo, now=bkk(10, 22))  # during the unassigned night
    assert spans(s) == [(B, bkk(10, 8), bkk(10, 20))]
    assert (s.current_status, s.current) == ("NONE", None)  # not A (permanent) and not invented


@pytest.mark.asyncio
async def test_b07_full_to_full_next_day_at_midnight() -> None:
    repo = E2Spy()
    await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await made(repo, create(B, "FULL_DAY", nov(21), nov(25)))
    s = await sched(repo)
    assert s.intervals[19].end == s.intervals[20].start == bkk(21)


@pytest.mark.asyncio
async def test_b08_full_to_full_overlapping_last_day_rejects() -> None:
    repo = E2Spy()
    await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    before = len(rows(repo))
    assert await code_of(op(repo, create(B, "FULL_DAY", nov(20), nov(25)))) == "E2_VEHICLE_CONFLICT"
    assert len(rows(repo)) == before


@pytest.mark.asyncio
async def test_b09_full_to_day_shift_driving_only_from_applied_start() -> None:
    repo = E2Spy()
    await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await made(repo, create(B, "DAY_SHIFT", nov(21), nov(25), DAY))
    s = await sched(repo)
    first_b = next(i for i in s.intervals if i.driver_id == B)
    assert first_b.start == bkk(21, 8)  # never 00:00: the administrative boundary is not driving (A2-3.6)
    assert (await sched(repo, now=bkk(21, 3))).current_status == "NONE"


@pytest.mark.asyncio
async def test_b10_full_to_day_shift_on_last_day_rejects() -> None:
    repo = E2Spy()
    await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    assert await code_of(op(repo, create(B, "DAY_SHIFT", nov(20), nov(25), DAY))) == "E2_VEHICLE_CONFLICT"


@pytest.mark.asyncio
async def test_b11_h2_last_day_night_handover_keeps_original_dates() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    outcome = await op(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    assert outcome.changed and len(outcome.record_ids) == 2
    s = await sched(repo)
    last_a = [i for i in s.intervals if i.driver_id == A][-1]
    assert last_a.end == bkk(20, 20)  # derived effective end = B's applied night start
    (a_row,) = [r for r in rows(repo) if r["event_id"] == a]
    assert a_row["end_date"] == nov(20)  # original A immutable
    (h_row,) = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"]
    assert (h_row["handover_kind"], h_row["predecessor_event_id"], h_row["predecessor_revision_no"],
            h_row["successor_revision_no"], h_row["handover_at"]) == ("H2", a, "1", "1", bkk(20, 20).isoformat())
    # A's derived end also frees the driver axis: A may drive another vehicle from 20:00
    await made(repo, create(A, "NIGHT_SHIFT", nov(20), nov(20), NIGHT), vehicle=V2)


@pytest.mark.asyncio
async def test_b12_mid_range_night_insertion_rejects_with_or_without_handover() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(15), nov(20), NIGHT, handover=(a, "1")))) \
        == "E2_HANDOVER_NOT_PERMITTED"
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(15), nov(20), NIGHT))) == "E2_VEHICLE_CONFLICT"
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT))) == "E2_VEHICLE_CONFLICT"


@pytest.mark.asyncio
async def test_b13_e2_h3_morning_handover_starts_full_day_at_night_end() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(20), NIGHT))
    outcome = await op(repo, create(A, "FULL_DAY", nov(21), nov(25), handover=(b, "1")))
    assert outcome.changed
    s = await sched(repo)
    first_a = next(i for i in s.intervals if i.driver_id == A)
    assert (first_a.label_date.isoformat(), first_a.start) == (nov(21), bkk(21, 8))
    a_row = next(r for r in rows(repo) if r["record_kind"] == "ASSIGNMENT" and r["driver_id"] == A)
    assert a_row["start_date"] == nov(21)
    assert next(r for r in rows(repo) if r["record_kind"] == "HANDOVER")["handover_kind"] == "E2_H3"
    # without the explicit handover the same pair is an ordinary overlap
    repo2 = E2Spy()
    await made(repo2, create(B, "NIGHT_SHIFT", nov(20), nov(20), NIGHT))
    assert await code_of(op(repo2, create(A, "FULL_DAY", nov(21), nov(25)))) == "E2_VEHICLE_CONFLICT"


@pytest.mark.asyncio
async def test_b14_physical_overlap_rejects_despite_labels() -> None:
    repo = E2Spy()
    await made(repo, create(A, "DAY_SHIFT", nov(10), nov(10), DAY))
    late = {"start_time": "19:00", "end_time": "07:00", "end_day_offset": 1}
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(10), nov(10), late))) == "E2_VEHICLE_CONFLICT"


@pytest.mark.asyncio
async def test_b15_same_driver_adjacent_on_two_vehicles_warns_not_a_safety_approval() -> None:
    repo = E2Spy()
    await made(repo, create(B, "DAY_SHIFT", nov(10), nov(10), DAY))
    outcome = await op(repo, create(B, "NIGHT_SHIFT", nov(10), nov(10), NIGHT), vehicle=V2)
    assert outcome.changed and "ADJACENT_ASSIGNMENT_REST_WARNING" in codes(outcome.warnings)


@pytest.mark.asyncio
async def test_b16_simultaneous_same_driver_or_same_vehicle_rejects() -> None:
    repo = E2Spy()
    await made(repo, create(B, "DAY_SHIFT", nov(10), nov(10), DAY))
    with pytest.raises(ApiError) as exc:
        await op(repo, create(B, "DAY_SHIFT", nov(10), nov(10), {"start_time": "12:00", "end_time": "14:00",
                                                                    "end_day_offset": 0}), vehicle=V2)
    assert exc.value.code == "E2_DRIVER_CONFLICT"
    assert exc.value.details["axis"] == "DRIVER" and exc.value.details["first"]["assigned_driver_id"] == B
    assert await code_of(op(repo, create(C, "DAY_SHIFT", nov(10), nov(10), DAY))) == "E2_VEHICLE_CONFLICT"


def _split_body(event: str, rev: str, start: str, end: str, shift: dict, day: str, driver: str = B) -> dict:
    return {"operation": "REVISE", "event_id": event, "expected_revision_no": rev, "driver_id": driver,
            "start_date": start, "end_date": end, "shift": shift, "split_from_date": day, "reason_th": REASON}


EARLY_NIGHT = {"start_time": "19:00", "end_time": "07:00", "end_day_offset": 1}


@pytest.mark.asyncio
async def test_b17_shift_time_change_splits_and_preserves_history() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(1), nov(20), NIGHT))
    original = dict(rows(repo)[0])
    outcome = await op(repo, _split_body(b, "1", nov(1), nov(20), EARLY_NIGHT, nov(10)))
    assert outcome.changed and len(outcome.record_ids) == 2
    assert rows(repo)[0] == original  # the original row is never rewritten
    head, new = rows(repo)[1], rows(repo)[2]
    assert (head["record_kind"], head["end_date"], head["shift_start_time"]) == ("REVISION", nov(9), "20:00")
    assert (new["start_date"], new["end_date"], new["shift_start_time"], new["relation"], new["related_event_id"]) \
        == (nov(10), nov(20), "19:00", "SPLIT", b)
    assert head["reason_th"] == new["reason_th"] == REASON and head["operation_id"] == new["operation_id"]
    s = await sched(repo)
    assert [i.start for i in s.intervals if i.label_date.day in (9, 10)] == [bkk(9, 20), bkk(10, 19)]


@pytest.mark.asyncio
async def test_b18_any_conflicting_segment_rejects_the_whole_change() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(1), nov(20), NIGHT))
    await made(repo, create(C, "DAY_SHIFT", nov(15), nov(15), {"start_time": "08:00", "end_time": "19:30",
                                                                "end_day_offset": 0}))
    before = [dict(r) for r in rows(repo)]
    # only the new 19:00 start of the Nov 15 night (one segment of the split) overlaps C until 19:30
    assert await code_of(op(repo, _split_body(b, "1", nov(1), nov(20), EARLY_NIGHT, nov(10)))) \
        == "E2_VEHICLE_CONFLICT"
    assert rows(repo) == before  # nothing of the edit applied, the old assignment remains


@pytest.mark.asyncio
async def test_b19_whole_night_substitution_keeps_unaffected_days() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(15), nov(20), NIGHT))
    outcome = await op(repo, {"operation": "SUBSTITUTE", "event_id": b, "expected_revision_no": "1",
                              "dates": [nov(17)], "driver_id": C, "reason_th": REASON})
    assert outcome.changed
    s = await sched(repo)
    assert [(i.label_date.day, i.driver_id) for i in s.intervals] == [
        (15, B), (16, B), (17, C), (18, B), (19, B), (20, B)]
    sub = rows(repo)[-1]
    assert (sub["relation"], sub["related_event_id"], sub["reason_th"]) == ("SUBSTITUTION", b, REASON)


@pytest.mark.asyncio
async def test_b19_full_day_substitution_is_whole_calendar_days_only_o4() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await op(repo, {"operation": "SUBSTITUTE", "event_id": a, "expected_revision_no": "1",
                    "dates": [nov(5), nov(7)], "driver_id": C, "reason_th": REASON})
    s = await sched(repo)
    assert [(i.label_date.day, i.driver_id) for i in s.intervals if i.label_date.day in (5, 6, 7)] == [
        (5, C), (6, A), (7, C)]
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(10), nov(10), NIGHT))) == "E2_VEHICLE_CONFLICT"


@pytest.mark.asyncio
async def test_b20_no_mid_shift_handover_in_any_operation(client) -> None:
    # A partial-shift substitute (a time inside the shift) cannot even be expressed.
    response = await client.post(f"{API}/vehicles/{V1}/operational-driver-assignment-operations",
                                 headers={"X-Dev-Role": "ADMIN", "X-Request-Id": str(uuid.uuid4())},
                                 json={"operation": "SUBSTITUTE", "event_id": "E", "expected_revision_no": "1",
                                       "dates": [nov(17)], "driver_id": C, "reason_th": REASON, "from_time": "23:00"})
    assert response.status_code == 422
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(15), nov(20), NIGHT))
    late = {"start_time": "23:00", "end_time": "08:00", "end_day_offset": 1}
    assert await code_of(op(repo, create(C, "NIGHT_SHIFT", nov(17), nov(17), late))) == "E2_VEHICLE_CONFLICT"
    assert await code_of(op(repo, create(C, "NIGHT_SHIFT", nov(17), nov(17), late, handover=(b, "1")))) \
        == "E2_HANDOVER_NOT_PERMITTED"


@pytest.mark.asyncio
async def test_b21_future_cancellation_releases_and_keeps_audit() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "FULL_DAY", nov(20), nov(25)))
    outcome = await op(repo, {"operation": "CANCEL", "event_id": b, "expected_revision_no": "1",
                              "reason_th": "ยกเลิกแผน (ทดสอบ)"}, now=bkk(18, 9))
    assert outcome.changed
    assert (await sched(repo)).intervals == ()
    await made(repo, create(C, "FULL_DAY", nov(20), nov(25)))  # the slot is released
    history = await Svc(repo).vehicle_history(V1)
    cancelled = next(a for a in history.assignments if a.event_id == b)
    assert cancelled.lifecycle == "CANCELLED"
    cancel_row = next(r for r in history.records if r["record_kind"] == "CANCELLATION")
    assert (cancel_row["reason_th"], cancel_row["recorded_by"], cancel_row["entry_operation"]) == (
        "ยกเลิกแผน (ทดสอบ)", "dev-user", "CANCEL")
    assert next(r for r in history.records if r["record_id"] == b)["start_date"] == nov(20)  # original kept
    assert await code_of(op(repo, {"operation": "CANCEL", "event_id": b, "expected_revision_no": "2",
                                   "reason_th": REASON})) == "E2_ASSIGNMENT_CANCELLED"


@pytest.mark.asyncio
async def test_b22_cancel_before_handover_restores_predecessor_coverage() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    outcome = await op(repo, {"operation": "CANCEL", "event_id": b, "expected_revision_no": "1",
                              "reason_th": REASON}, now=bkk(18, 9))
    assert outcome.changed and len(outcome.record_ids) == 2  # the assignment and its handover
    s = await sched(repo)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(21)  # original coverage restored
    history = await Svc(repo).vehicle_history(V1)
    assert [h.in_force for h in history.handovers] == [False]


@pytest.mark.asyncio
async def test_b23_after_handover_elapsed_time_is_never_given_back_and_is_unknown() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    after = bkk(21, 10)
    assert await code_of(op(repo, {"operation": "CANCEL", "event_id": b, "expected_revision_no": "1",
                                   "reason_th": REASON}, now=after)) == "E2_ASSIGNMENT_ALREADY_STARTED"
    void = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "void_elapsed": True,
            "reason_th": "บันทึกผิดคน (ทดสอบ)"}
    assert (await op(repo, void, now=after)).changed
    s = await sched(repo, now=after)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 20)  # A not restored
    assert [(u.start, u.end) for u in s.unknown] == [(bkk(20, 20), bkk(21))]  # exactly the moved elapsed time
    assert not [i for i in s.intervals if i.driver_id == B]
    assert all(r["voided"] == "" for r in rows(repo) if r["record_kind"] == "ASSIGNMENT")  # originals intact
    # an authorized, reasoned correction resolves the uncertainty
    await made(repo, create(C, "NIGHT_SHIFT", nov(20), nov(20), NIGHT), now=after)
    assert (await sched(repo, now=after)).unknown == ()


@pytest.mark.asyncio
async def test_b24_backdated_whole_shift_correction_with_reason() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(15), nov(20), NIGHT))
    later = bkk(25, 9)
    sub = {"operation": "SUBSTITUTE", "event_id": b, "expected_revision_no": "1", "dates": [nov(17)],
           "driver_id": C, "reason_th": "ข้อเท็จจริงภายหลัง (ทดสอบ)"}
    assert (await op(repo, sub, now=later)).changed
    assert {k: rows(repo)[-1][k] for k in ("driver_id", "reason_th", "recorded_by")} == {
        "driver_id": C, "reason_th": "ข้อเท็จจริงภายหลัง (ทดสอบ)", "recorded_by": "dev-user"}
    no_reason = {k: v for k, v in sub.items() if k != "reason_th"}
    assert await code_of(op(repo, {**no_reason, "expected_revision_no": "2"}, now=later)) == "REASON_REQUIRED"


@pytest.mark.asyncio
async def test_b25_future_inactive_driver_is_retained_and_flagged() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "FULL_DAY", nov(20), nov(25)))
    repo.set_status(B, "INACTIVE")
    s = await sched(repo)
    assert len(s.intervals) == 6  # no silent cancellation
    assert any(w.code == "FUTURE_ASSIGNMENT_DRIVER_NOT_ACTIVE_PENDING_REVIEW" and w.event_id == b
               for w in s.warnings)


@pytest.mark.asyncio
async def test_b26_current_inactive_driver_is_retained_flagged_and_needs_action() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "FULL_DAY", nov(1), nov(20)))
    repo.set_status(B, "INACTIVE")
    mid = bkk(10, 12)
    s = await sched(repo, now=mid)
    assert s.current.driver_id == B and "DRIVER_NOT_ACTIVE" in codes(s.warnings)
    extend = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "driver_id": B,
              "start_date": nov(1), "end_date": nov(25), "reason_th": REASON}
    assert await code_of(op(repo, extend, now=mid)) == "DRIVER_NOT_ACTIVE"
    early = {"operation": "EARLY_END", "event_id": b, "expected_revision_no": "1", "end": {"mode": "NOW"},
             "reason_th": REASON}
    assert (await op(repo, early, now=mid)).changed  # authorized human action, no eligibility gate


@pytest.mark.asyncio
async def test_b27_duplicate_and_replay() -> None:
    repo = E2Spy()
    body = create(B, "FULL_DAY", nov(20), nov(25))
    rid = str(uuid.uuid4())
    first = await op(repo, body, request_id=rid)
    dup = await op(repo, body)
    assert (dup.changed, dup.existing_event_id) == (False, first.event_ids[0])
    replay = await op(repo, body, request_id=rid)
    assert replay.replayed and replay.record_ids == first.record_ids and replay.event_ids == first.event_ids
    assert await code_of(op(repo, {**body, "end_date": nov(26)}, request_id=rid)) == "REQUEST_ID_REUSED"
    assert len(rows(repo)) == 1


@pytest.mark.asyncio
async def test_b28_one_process_concurrency_one_winner_never_partial_gated_by_r11() -> None:
    """Mock / ONE asyncio process only. B28 itself stays GATED by R11."""
    repo = E2Spy(yield_on_read=True)
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    first = op(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    second = op(repo, create(C, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    results = await asyncio.gather(first, second, return_exceptions=True)
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, ApiError)]
    assert len(winners) == 1 and [e.code for e in losers] == ["E2_CONCURRENT_CHANGE"]
    assert len(rows(repo)) == 3  # A, the winner's assignment and its handover — nothing of the loser
    # the loser's retry is now an explicit, reasoned refusal (A already hands over to the winner)
    assert await code_of(op(repo, create(C, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))) \
        == "E2_HANDOVER_NOT_PERMITTED"


@pytest.mark.asyncio
async def test_b29_search_by_vehicle_driver_date_and_mode(client) -> None:
    repo = E2Spy(batch=MOCK_TEST_BATCH_ID)
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        post = f"{API}/vehicles/{V1}/operational-driver-assignment-operations"
        for body in (create(A, "DAY_SHIFT", nov(10), nov(12), DAY), create(B, "NIGHT_SHIFT", nov(10), nov(12), NIGHT)):
            r = await http.post(post, json=body, headers={"X-Dev-Role": "ADMIN", "X-Request-Id": str(uuid.uuid4())})
            assert r.status_code == 200, r.text
        view = {"X-Dev-Role": "TECHNICIAN"}
        r = await http.get(f"{API}/vehicles/{V1}/operational-driver-assignments",
                           params={"from": nov(11), "to": nov(11), "mode": "NIGHT_SHIFT"}, headers=view)
        assert r.status_code == 200, r.text
        body = r.json()
        # a time-range lookup includes the Nov 10 night carrying into Nov 11 (labelled by its start date)
        assert [(i["label_date"], i["assigned_driver_id"]) for i in body["intervals"]] == [(nov(10), B), (nov(11), B)]
        flat = str(body)
        assert "actual" not in flat and "verified" not in flat  # G-2: assigned, never proof of driving
        r = await http.get(f"{API}/drivers/{A}/operational-driver-assignments", headers=view)
        assert [i["label_date"] for i in r.json()["intervals"]] == [nov(10), nov(11), nov(12)]
        r = await http.get(f"{API}/vehicles/{V1}/operational-driver-assignment-history", headers=view)
        assert r.status_code == 200 and len(r.json()["records"]) == 2 and len(r.json()["events"]) == 2
        bad = await http.get(f"{API}/vehicles/{V1}/operational-driver-assignments", params={"mode": "X"},
                             headers=view)
        assert bad.status_code == 422
    get_settings.cache_clear()
    reset_dependency_cache()


# ---------------------------------------------------------------------------
# E2-AUTH
# ---------------------------------------------------------------------------


async def _http(method: str, path: str, repo, *, role: str = "DRIVER_DEPARTMENT_MANAGER", json=None,
                request_id: str | None = "auto"):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    headers = {"X-Dev-Role": role}
    if request_id is not None:
        headers["X-Request-Id"] = str(uuid.uuid4()) if request_id == "auto" else request_id
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            return await http.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


OPS = f"{API}/vehicles/{V1}/operational-driver-assignment-operations"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER", "NO_SUCH_ROLE"])
async def test_e2_auth_writes_need_can_assign_crane_driver_with_zero_repository_calls(role) -> None:
    repo = E2Spy(batch=MOCK_TEST_BATCH_ID)
    response = await _http("POST", OPS, repo, role=role, json=create(B, "FULL_DAY", "2027-01-01", "2027-01-02"))
    assert response.status_code == 403 and repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_e2_auth_write_roles_record_test_scope_and_actor(role) -> None:
    repo = E2Spy(batch=MOCK_TEST_BATCH_ID)
    response = await _http("POST", OPS, repo, role=role, json=create(B, "FULL_DAY", "2027-01-01", "2027-01-02"))
    assert response.status_code == 200, response.text
    (row,) = rows(repo)
    assert list(row) == list(OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS)
    assert (row["is_test_data"], row["test_batch_id"], row["recorded_by"]) == ("TRUE", MOCK_TEST_BATCH_ID, "dev-user")


@pytest.mark.asyncio
async def test_e2_auth_request_id_and_strict_body_before_any_read() -> None:
    repo = E2Spy(batch=MOCK_TEST_BATCH_ID)
    body = create(B, "FULL_DAY", "2027-01-01", "2027-01-02")
    assert (await _http("POST", OPS, repo, json=body, request_id=None)).json()["error"]["code"] == \
        "REQUEST_ID_REQUIRED"
    server_set = ("record_id", "record_kind", "revision_no", "event_id", "supersedes_record_id", "recorded_at",
                  "recorded_by", "request_id", "request_fingerprint", "is_test_data", "test_batch_id",
                  "handover_at", "unknown_start_at", "relation", "voided", "operation_id")
    for name in server_set:
        assert (await _http("POST", OPS, repo, json={**body, name: "x"})).status_code == 422, name
    bad = [
        {**body, "operation": "DELETE"},
        {**body, "mode": "HALF_DAY"},
        {"operation": "CANCEL", "event_id": "E", "expected_revision_no": "1"},  # reason required
        {"operation": "REVISE", "event_id": "E", "expected_revision_no": "1", "void_elapsed": False,
         "reason_th": REASON},
        {"operation": "EARLY_END", "event_id": "E", "expected_revision_no": "1", "end": {"mode": "LATER"},
         "reason_th": REASON},
    ]
    for payload in bad:
        assert (await _http("POST", OPS, repo, json=payload)).status_code == 422, payload
    assert repo.calls == []


@pytest.mark.asyncio
async def test_e2_auth_no_delete_route() -> None:
    repo = E2Spy(batch=MOCK_TEST_BATCH_ID)
    for path in (OPS, f"{API}/vehicles/{V1}/operational-driver-assignments",
                 f"{API}/vehicles/{V1}/operational-driver-assignment-history"):
        assert (await _http("DELETE", path, repo)).status_code == 405


# ---------------------------------------------------------------------------
# E2-MODE / E2-DQ7 / E2-REASON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("body,code", [
    (create(B, "FULL_DAY", nov(1), nov(2), DAY), "E2_SHIFT_NOT_ALLOWED"),
    (create(B, "DAY_SHIFT", nov(1), nov(2)), "E2_SHIFT_REQUIRED"),
    (create(B, "DAY_SHIFT", nov(1), nov(2), {"start_time": "08:00", "end_time": "08:00", "end_day_offset": 0}),
     "E2_SHIFT_DURATION_INVALID"),
    (create(B, "NIGHT_SHIFT", nov(1), nov(2), {"start_time": "20:00", "end_time": "21:00", "end_day_offset": 1}),
     "E2_SHIFT_DURATION_INVALID"),
    (create(B, "DAY_SHIFT", nov(1), nov(2), {"start_time": "24:00", "end_time": "08:00", "end_day_offset": 1}),
     "E2_TIME_INVALID"),
    (create(B, "FULL_DAY", nov(5), nov(4)), "E2_RANGE_INVALID"),
    (create(B, "FULL_DAY", "2026-11-31", nov(4)), "E2_DATE_INVALID"),
])
async def test_e2_mode_contract_errors(body, code) -> None:
    repo = E2Spy()
    assert await code_of(op(repo, body)) == code
    assert rows(repo) == []


@pytest.mark.asyncio
async def test_e2_mode_exact_24_hour_shift_is_accepted() -> None:
    repo = E2Spy()
    await made(repo, create(B, "DAY_SHIFT", nov(1), nov(1), {"start_time": "08:00", "end_time": "08:00",
                                                              "end_day_offset": 1}))
    (i,) = (await sched(repo)).intervals
    assert (i.start, i.end) == (bkk(1, 8), bkk(2, 8))


@pytest.mark.asyncio
async def test_e2_dq7_duration_and_horizon() -> None:
    repo = E2Spy()
    with pytest.raises(ApiError) as exc:
        await op(repo, create(B, "FULL_DAY", nov(1), "2027-11-02"))  # 367 days
    assert (exc.value.code, exc.value.details["limit"]) == ("E2_RANGE_TOO_LONG", "DURATION")
    await made(repo, create(B, "FULL_DAY", nov(1), "2027-11-01"))  # 366 days
    with pytest.raises(ApiError) as exc:
        await op(repo, create(C, "FULL_DAY", "2027-10-20", "2027-10-21"), vehicle=V2)  # 367 days ahead
    assert (exc.value.code, exc.value.details["limit"]) == ("E2_RANGE_TOO_LONG", "START_HORIZON")
    await made(repo, create(C, "FULL_DAY", "2027-10-19", "2027-10-19"), vehicle=V2)  # exactly 366 ahead


@pytest.mark.asyncio
async def test_e2_dq7_split_records_are_limited_but_old_history_is_correctable() -> None:
    repo = E2Spy()
    old = await made(repo, create(B, "FULL_DAY", "2024-12-01", "2024-12-05"))  # > 366 days in the past
    fix = {"operation": "REVISE", "event_id": old, "expected_revision_no": "1", "driver_id": C,
           "start_date": "2024-12-01", "end_date": "2024-12-05", "reason_th": REASON}
    assert (await op(repo, fix)).changed
    too_long = {**fix, "expected_revision_no": "2", "end_date": "2025-12-02"}
    assert await code_of(op(repo, too_long)) == "E2_RANGE_TOO_LONG"


@pytest.mark.asyncio
async def test_e2_reason_backdated_create_needs_reason_same_day_does_not() -> None:
    repo = E2Spy()
    today = NOW.strftime("%Y-") + "10-18"
    assert (await op(repo, create(B, "FULL_DAY", today, today, reason=None))).changed  # entered after 00:00
    assert await code_of(op(repo, create(C, "FULL_DAY", "2026-10-17", "2026-10-17", reason=None), vehicle=V2)) \
        == "REASON_REQUIRED"


# ---------------------------------------------------------------------------
# E2-LIFE — cancel / early end / void (DQ-3, DQ-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2_life_early_end_now_keeps_elapsed_assigned_never_unknown() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    mid = bkk(10, 15)
    body = {"operation": "EARLY_END", "event_id": a, "expected_revision_no": "1", "end": {"mode": "NOW"},
            "reason_th": REASON}
    assert (await op(repo, body, now=mid)).changed
    s = await sched(repo, now=mid)
    assert s.intervals[-1].end == mid and len(s.intervals) == 10 and s.unknown == ()
    assert await code_of(op(repo, {**body, "expected_revision_no": "2"}, now=bkk(11))) \
        == "E2_ASSIGNMENT_ALREADY_ENDED"


@pytest.mark.asyncio
async def test_e2_life_early_end_after_date_and_not_started() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    body = {"operation": "EARLY_END", "event_id": a, "expected_revision_no": "1",
            "end": {"mode": "AFTER_DATE", "date": nov(12)}, "reason_th": REASON}
    assert await code_of(op(repo, body)) == "E2_ASSIGNMENT_NOT_STARTED"  # use CANCEL before the start
    assert await code_of(op(repo, {**body, "end": {"mode": "AFTER_DATE", "date": nov(5)}}, now=bkk(10, 9))) \
        == "E2_EARLY_END_INVALID"  # never ends elapsed days
    assert (await op(repo, body, now=bkk(10, 9))).changed
    assert (await sched(repo)).intervals[-1].label_date.day == 12


@pytest.mark.asyncio
async def test_e2_life_void_only_for_started_and_keeps_records() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "FULL_DAY", nov(1), nov(3)))
    void = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "void_elapsed": True,
            "reason_th": REASON}
    assert await code_of(op(repo, void)) == "E2_ASSIGNMENT_NOT_STARTED"
    assert (await op(repo, void, now=bkk(5))).changed
    assert (await sched(repo, now=bkk(5))).intervals == () and (await sched(repo, now=bkk(5))).unknown == ()
    assert [r["record_kind"] for r in rows(repo)] == ["ASSIGNMENT", "REVISION"] and rows(repo)[1]["voided"] == "TRUE"
    assert await code_of(op(repo, {**void, "expected_revision_no": "2"}, now=bkk(5))) == "E2_ASSIGNMENT_VOIDED"
    assert await code_of(op(repo, {**void, "driver_id": C}, now=bkk(5))) == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_e2_life_early_end_of_h2_successor_never_renews_predecessor_a5_4() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    at = bkk(20, 23)
    body = {"operation": "EARLY_END", "event_id": b, "expected_revision_no": "1", "end": {"mode": "NOW"},
            "reason_th": REASON}
    assert (await op(repo, body, now=at)).changed
    s = await sched(repo, now=at)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 20)
    assert s.unknown == () and s.current_status == "NONE"


# ---------------------------------------------------------------------------
# E2-HO — handover lifecycle and revision integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2_ho_revise_before_effect_moves_the_boundary_with_a_handover_revision() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    later = {"start_time": "21:00", "end_time": "08:00", "end_day_offset": 1}
    body = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "driver_id": B,
            "start_date": nov(20), "end_date": nov(25), "shift": later, "reason_th": REASON}
    outcome = await op(repo, body)
    assert outcome.changed and len(outcome.record_ids) == 2
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"]
    assert [x["revision_no"] for x in h] == ["1", "2"]
    assert (h[1]["successor_revision_no"], h[1]["handover_at"]) == ("2", bkk(20, 21).isoformat())
    s = await sched(repo)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 21)


def _h2_revise(b: str, rev: str, shift: dict, *, start: int = 20, driver: str = B) -> dict:
    return {"operation": "REVISE", "event_id": b, "expected_revision_no": rev, "driver_id": driver,
            "start_date": nov(start), "end_date": nov(25), "shift": shift, "reason_th": "แก้เวลาตามจริง (ทดสอบ)"}


async def _h2(repo) -> tuple[str, str]:
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    return a, b


@pytest.mark.asyncio
async def test_f1_effective_h2_night_start_corrected_later_withholds_time_as_unknown() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    originals = [dict(r) for r in rows(repo)]
    after = bkk(22, 10)
    late = {"start_time": "21:00", "end_time": "08:00", "end_day_offset": 1}
    outcome = await op(repo, _h2_revise(b, "1", late), now=after)
    assert outcome.changed and len(outcome.record_ids) == 2  # assignment revision + HANDOVER revision
    assert rows(repo)[:len(originals)] == originals  # original history preserved
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"][-1]
    assert (h["revision_no"], h["successor_revision_no"], h["handover_at"]) == ("2", "2", bkk(20, 21).isoformat())
    s = await sched(repo, now=after)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 20)  # never restored to A
    assert [(u.start, u.end) for u in s.unknown] == [(bkk(20, 20), bkk(20, 21))]
    # an authorized correction of who actually drove resolves exactly that hour
    await made(repo, create(A, "DAY_SHIFT", nov(20), nov(20), {"start_time": "20:00", "end_time": "21:00",
                                                                "end_day_offset": 0}), now=after)
    assert (await sched(repo, now=after)).unknown == ()


@pytest.mark.asyncio
async def test_f1_effective_h2_night_start_corrected_earlier_moves_the_cut() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    early = {"start_time": "19:00", "end_time": "08:00", "end_day_offset": 1}
    assert (await op(repo, _h2_revise(b, "1", early), now=bkk(22, 10))).changed
    s = await sched(repo, now=bkk(22, 10))
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 19) and s.unknown == ()


@pytest.mark.asyncio
async def test_f1_effective_e2_h3_night_end_corrected_earlier_never_moves_successor_back() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(20), NIGHT))
    await made(repo, create(A, "FULL_DAY", nov(21), nov(25), handover=(b, "1")))
    fix = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "driver_id": B,
           "start_date": nov(20), "end_date": nov(20),
           "shift": {"start_time": "20:00", "end_time": "06:00", "end_day_offset": 1}, "reason_th": REASON}
    assert (await op(repo, fix, now=bkk(22, 10))).changed
    s = await sched(repo, now=bkk(22, 10))
    assert next(i for i in s.intervals if i.driver_id == A).start == bkk(21, 8)  # A not moved back to 06:00
    assert [(u.start, u.end) for u in s.unknown] == [(bkk(21, 6), bkk(21, 8))]


@pytest.mark.asyncio
async def test_f1_effective_correction_checks_the_driver_axis_and_applies_nothing_on_conflict() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    await made(repo, create(B, "DAY_SHIFT", nov(20), nov(20), {"start_time": "10:00", "end_time": "18:30",
                                                                "end_day_offset": 0}), vehicle=V2)
    before = [dict(r) for r in rows(repo)]
    early = {"start_time": "18:00", "end_time": "08:00", "end_day_offset": 1}
    with pytest.raises(ApiError) as exc:
        await op(repo, _h2_revise(b, "1", early), now=bkk(22, 10))
    assert exc.value.code == "E2_DRIVER_CONFLICT" and rows(repo) == before


@pytest.mark.asyncio
async def test_f1_void_and_rerecord_is_faithful_and_never_restores_the_predecessor() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    after = bkk(22, 10)
    void = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "void_elapsed": True,
            "reason_th": REASON}
    assert (await op(repo, void, now=after)).changed
    late = {"start_time": "21:00", "end_time": "08:00", "end_day_offset": 1}
    await made(repo, create(C, "NIGHT_SHIFT", nov(20), nov(25), late), now=after)  # the established facts
    s = await sched(repo, now=after)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 20)
    assert [(u.start, u.end) for u in s.unknown] == [(bkk(20, 20), bkk(20, 21))]


@pytest.mark.asyncio
async def test_f1_effective_boundary_date_change_is_refused() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    assert await code_of(op(repo, _h2_revise(b, "1", NIGHT, start=21), now=bkk(22, 10))) \
        == "E2_HANDOVER_INVALIDATED"


# ---------------------------------------------------------------------------
# F2 — substitution on handover boundaries
# ---------------------------------------------------------------------------


def _sub(event: str, rev: str, days: list[int], driver: str = C) -> dict:
    return {"operation": "SUBSTITUTE", "event_id": event, "expected_revision_no": rev,
            "dates": [nov(d) for d in days], "driver_id": driver, "reason_th": REASON}


@pytest.mark.asyncio
@pytest.mark.parametrize("now", [NOW, bkk(22, 10)], ids=["planned", "after-effect"])
async def test_f2_h2_predecessor_last_day_substitute_takes_its_place(now) -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    assert (await op(repo, _sub(a, "1", [20]), now=now)).changed
    s = await sched(repo, now=now)
    assert [(i.driver_id, i.start, i.end) for i in s.intervals if i.label_date.day == 20 and i.mode == "FULL_DAY"] \
        == [(C, bkk(20), bkk(20, 20))]
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"][-1]
    sub = next(r for r in rows(repo) if r["relation"] == "SUBSTITUTION")
    assert (h["predecessor_event_id"], h["handover_at"]) == (sub["event_id"], bkk(20, 20).isoformat())
    assert s.unknown == ()


@pytest.mark.asyncio
async def test_f2_h2_successor_first_night_substitute_takes_its_place() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    assert (await op(repo, _sub(b, "1", [20, 21]))).changed
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"][-1]
    assert h["successor_event_id"] == next(r for r in rows(repo) if r["relation"] == "SUBSTITUTION")["event_id"]
    s = await sched(repo)
    assert [(i.label_date.day, i.driver_id) for i in s.intervals if i.mode == "NIGHT_SHIFT"][:3] == [
        (20, C), (21, C), (22, B)]


@pytest.mark.asyncio
async def test_f2_e2_h3_successor_first_day_substitute_starts_at_the_night_end() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(20), NIGHT))
    a = await made(repo, create(A, "FULL_DAY", nov(21), nov(25), handover=(b, "1")))
    assert (await op(repo, _sub(a, "1", [21]))).changed
    s = await sched(repo)
    assert next(i for i in s.intervals if i.label_date.day == 21 and i.mode == "FULL_DAY").start == bkk(21, 8)
    assert next(i for i in s.intervals if i.label_date.day == 21 and i.mode == "FULL_DAY").driver_id == C


@pytest.mark.asyncio
async def test_f2_units_cut_by_an_early_end_are_still_not_substitutable() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await op(repo, {"operation": "EARLY_END", "event_id": a, "expected_revision_no": "1", "end": {"mode": "NOW"},
                    "reason_th": REASON}, now=bkk(10, 15))
    assert await code_of(op(repo, _sub(a, "2", [10]), now=bkk(12))) == "E2_SUBSTITUTION_UNIT_INVALID"
    assert await code_of(op(repo, _sub(a, "2", [15]), now=bkk(12))) == "E2_SUBSTITUTION_UNIT_INVALID"


# ---------------------------------------------------------------------------
# F3 — partial historical correction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f3_exclude_specific_erroneous_elapsed_units_keeps_the_rest() -> None:
    repo = E2Spy(inactive=())
    b = await made(repo, create(B, "FULL_DAY", nov(1), nov(10)))
    original = dict(rows(repo)[0])
    repo.set_status(B, "INACTIVE")  # removal only: never re-gated as a new assignment
    later = bkk(15)
    fix = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "driver_id": B,
           "start_date": nov(1), "end_date": nov(10), "exclude_dates": [nov(3), nov(4)],
           "reason_th": "วันที่ 3-4 บันทึกผิด (ทดสอบ)"}
    assert (await op(repo, fix, now=later)).changed
    s = await sched(repo, now=later)
    assert [i.label_date.day for i in s.intervals] == [1, 2, 5, 6, 7, 8, 9, 10] and s.unknown == ()
    assert rows(repo)[0] == original and rows(repo)[1]["excluded_dates"] == f"{nov(3)},{nov(4)}"
    assert await code_of(op(repo, {**fix, "expected_revision_no": "2", "exclude_dates": [nov(11)]}, now=later)) \
        == "E2_DATE_INVALID"
    assert await code_of(op(repo, {**fix, "expected_revision_no": "2", "split_from_date": nov(5)}, now=later)) \
        == "E2_SPLIT_INVALID"


@pytest.mark.asyncio
async def test_f3_void_whole_versus_correct_part() -> None:
    repo = E2Spy()
    whole = await made(repo, create(B, "FULL_DAY", nov(1), nov(3)))
    part = await made(repo, create(C, "FULL_DAY", nov(1), nov(3)), vehicle=V2)
    later = bkk(10)
    await op(repo, {"operation": "REVISE", "event_id": whole, "expected_revision_no": "1", "void_elapsed": True,
                    "reason_th": REASON}, now=later)
    await op(repo, {"operation": "REVISE", "event_id": part, "expected_revision_no": "1", "driver_id": C,
                    "start_date": nov(1), "end_date": nov(3), "exclude_dates": [nov(2)], "reason_th": REASON},
             vehicle=V2, now=later)
    assert (await sched(repo, now=later)).intervals == ()
    assert [i.label_date.day for i in (await sched(repo, V2, now=later)).intervals] == [1, 3]
    assert len(rows(repo)) == 4  # nothing physically deleted


# ---------------------------------------------------------------------------
# F4 — early end and UNKNOWN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f4_early_end_keeps_elapsed_and_releases_the_future() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    at = bkk(10, 15)
    await op(repo, {"operation": "EARLY_END", "event_id": a, "expected_revision_no": "1", "end": {"mode": "NOW"},
                    "reason_th": REASON}, now=at)
    await made(repo, create(C, "DAY_SHIFT", nov(10), nov(10), {"start_time": "16:00", "end_time": "20:00",
                                                                "end_day_offset": 0}), now=at)
    await made(repo, create(C, "FULL_DAY", nov(11), nov(20)), now=at)
    s = await sched(repo, now=at)
    assert [i.driver_id for i in s.intervals][:10] == [A] * 10 and s.intervals[9].end == at and s.unknown == ()


@pytest.mark.asyncio
async def test_f4_early_end_of_predecessor_before_handover_is_not_unknown() -> None:
    repo = E2Spy()
    a, b = await _h2(repo)
    at = bkk(20, 15)
    assert (await op(repo, {"operation": "EARLY_END", "event_id": a, "expected_revision_no": "1",
                            "end": {"mode": "NOW"}, "reason_th": REASON}, now=at)).changed
    s = await sched(repo, now=bkk(20, 18))
    assert [i for i in s.intervals if i.driver_id == A][-1].end == at
    assert (s.current_status, s.unknown) == ("NONE", ())
    assert next(i for i in s.intervals if i.driver_id == B).start == bkk(20, 20)
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"][-1]
    assert h["predecessor_revision_no"] == "2"


@pytest.mark.asyncio
async def test_e2_ho_post_handover_driver_correction_revalidates_and_keeps_coverage() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    after = bkk(22, 10)
    fix = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "driver_id": C,
           "start_date": nov(20), "end_date": nov(25), "shift": NIGHT, "reason_th": REASON}
    assert (await op(repo, fix, now=after)).changed
    s = await sched(repo, now=after)
    assert s.unknown == ()  # the moved time is still covered (by the corrected driver)
    assert [i for i in s.intervals if i.driver_id == A][-1].end == bkk(20, 20)
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"][-1]
    assert (h["revision_no"], h["successor_revision_no"]) == ("2", "2")


@pytest.mark.asyncio
async def test_e2_ho_cancelling_the_predecessor_before_start_cancels_the_handover() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    cancel = {"operation": "CANCEL", "event_id": a, "expected_revision_no": "1", "reason_th": REASON}
    assert len((await op(repo, cancel)).record_ids) == 2
    s = await sched(repo)
    assert {i.driver_id for i in s.intervals} == {B} and s.intervals[0].start == bkk(20, 20)


@pytest.mark.asyncio
async def test_e2_ho_e2_h3_void_of_the_night_marks_only_the_moved_morning_unknown() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(20), NIGHT))
    await made(repo, create(A, "FULL_DAY", nov(21), nov(25), handover=(b, "1")))
    after = bkk(22, 9)
    void = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "void_elapsed": True,
            "reason_th": REASON}
    assert (await op(repo, void, now=after)).changed
    s = await sched(repo, now=after)
    assert [(u.start, u.end) for u in s.unknown] == [(bkk(21), bkk(21, 8))]  # A is not moved back to 00:00
    assert next(i for i in s.intervals if i.driver_id == A).start == bkk(21, 8)


@pytest.mark.asyncio
async def test_e2_ho_splitting_an_e2_h3_night_moves_the_handover_to_the_last_segment() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "NIGHT_SHIFT", nov(18), nov(20), NIGHT))
    await made(repo, create(A, "FULL_DAY", nov(21), nov(25), handover=(b, "1")))
    outcome = await op(repo, _split_body(b, "1", nov(18), nov(20), EARLY_NIGHT, nov(19)))
    assert outcome.changed and len(outcome.record_ids) == 3
    h = [r for r in rows(repo) if r["record_kind"] == "HANDOVER"][-1]
    new_piece = next(r for r in rows(repo) if r["relation"] == "SPLIT")
    assert (h["predecessor_event_id"], h["handover_at"]) == (new_piece["event_id"], bkk(21, 7).isoformat())
    assert next(i for i in (await sched(repo)).intervals if i.driver_id == A).start == bkk(21, 7)


@pytest.mark.asyncio
async def test_e2_ho_one_predecessor_hands_over_once() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await made(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    assert await code_of(op(repo, create(C, "NIGHT_SHIFT", nov(20), nov(20), NIGHT, handover=(a, "1")),
                            vehicle=V1)) == "E2_HANDOVER_NOT_PERMITTED"


@pytest.mark.asyncio
async def test_e2_ho_wrong_pair_kinds_are_not_handovers() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "DAY_SHIFT", nov(1), nov(20), DAY))
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))) \
        == "E2_HANDOVER_NOT_PERMITTED"


# ---------------------------------------------------------------------------
# E2-O3 — elapsed historical correction with a currently INACTIVE driver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2_o3_elapsed_correction_may_name_inactive_driver_but_never_future() -> None:
    repo = E2Spy(inactive=(X,))
    b = await made(repo, create(B, "FULL_DAY", nov(1), nov(3)))
    later = bkk(10)
    fix = {"operation": "REVISE", "event_id": b, "expected_revision_no": "1", "driver_id": X,
           "start_date": nov(1), "end_date": nov(3), "reason_th": "ข้อเท็จจริง (ทดสอบ)"}
    assert (await op(repo, fix, now=later)).changed
    assert await code_of(op(repo, create(X, "FULL_DAY", nov(20), nov(21)), now=later)) == "DRIVER_NOT_ACTIVE"
    assert await code_of(op(repo, create(X, "FULL_DAY", nov(9), nov(11)), now=later)) == "DRIVER_NOT_ACTIVE"
    assert (await op(repo, create(X, "FULL_DAY", nov(5), nov(6)), now=later, vehicle=V2)).changed  # elapsed create
    assert await code_of(op(repo, create("DRV-SYN-NONE", "FULL_DAY", nov(5), nov(6)), now=later)) \
        == "DRIVER_NOT_FOUND"  # O3 never waives reference / scope checks


@pytest.mark.asyncio
async def test_e2_o3_personnel_link_gate() -> None:
    repo = E2Spy()
    from tests.test_relationship_read_batch_r2f_a import person

    repo._personnel_master = [{**person("P-1", test=True, batch=BATCH), "driver_id": B, "active_status": "INACTIVE"}]
    assert await code_of(op(repo, create(B, "FULL_DAY", nov(20), nov(21)))) == "PERSONNEL_NOT_ACTIVE"
    repo._personnel_master.append({**person("P-2", test=True, batch=BATCH), "driver_id": B})
    assert await code_of(op(repo, create(B, "FULL_DAY", nov(20), nov(21)))) == "DRIVER_PERSONNEL_AMBIGUOUS"


# ---------------------------------------------------------------------------
# E2-STALE / E2-REPLAY / E2-FAULT / E2-CONC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2_stale_revision_and_unknown_event() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "FULL_DAY", nov(20), nov(25)))
    cancel = {"operation": "CANCEL", "event_id": b, "expected_revision_no": "2", "reason_th": REASON}
    assert await code_of(op(repo, cancel)) == "E2_ASSIGNMENT_STALE"
    assert await code_of(op(repo, {**cancel, "event_id": "ODA-NOPE"})) == "E2_ASSIGNMENT_NOT_FOUND"
    assert await code_of(op(repo, {**cancel, "expected_revision_no": "1"}, vehicle=V2)) == "E2_ASSIGNMENT_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault,outcome,applied", [("rejected", "rejected", False),
                                                   ("unknown_not_applied", "unknown", False),
                                                   ("unknown_applied", "unknown", True)])
async def test_e2_fault_write_outcomes_then_replay(fault, outcome, applied) -> None:
    repo = E2Spy()
    repo.registry_write_faults["W1"] = fault
    rid = str(uuid.uuid4())
    body = create(B, "NIGHT_SHIFT", nov(20), nov(21), NIGHT)
    with pytest.raises(ApiError) as exc:
        await op(repo, body, request_id=rid)
    assert (exc.value.code, exc.value.details["history_write_outcome"]) == ("E2_HISTORY_WRITE_FAILED", outcome)
    assert len(rows(repo)) == (1 if applied else 0)  # one row or none, never a part
    repo.registry_write_faults.clear()
    resend = await op(repo, body, request_id=rid)
    assert resend.replayed is applied and len(rows(repo)) == 1


@pytest.mark.asyncio
async def test_e2_fault_multi_row_operation_is_all_or_nothing() -> None:
    repo = E2Spy()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    repo.registry_write_faults["W1"] = "rejected"
    assert await code_of(op(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))) \
        == "E2_HISTORY_WRITE_FAILED"
    assert len(rows(repo)) == 1


# ---------------------------------------------------------------------------
# E2-REAL / E2-SCOPE / E2-DATA / E2-CONFLICTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2_real_writes_refused_before_any_repository_call_o1() -> None:
    repo = E2Spy()
    assert await code_of(op(repo, create(B, "FULL_DAY", nov(20), nov(21)), context="REAL")) \
        == "E2_REAL_WRITES_NOT_ENABLED"
    assert repo.calls == [] and rows(repo) == []
    assert await code_of(Svc(repo, context=None).apply(V1, create(B, "FULL_DAY", nov(20), nov(21)),
                                                       request_id=str(uuid.uuid4()), user_id="u")) \
        == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_e2_scope_other_batches_are_invisible_and_scope_is_proven() -> None:
    repo = E2Spy()
    await made(repo, create(B, "FULL_DAY", nov(20), nov(21)))
    other = Svc(repo, batch="OTHER-BATCH")
    with pytest.raises(ApiError) as exc:
        await other.vehicle_schedule(V1)
    assert exc.value.code == "VEHICLE_SCOPE_UNPROVEN"  # V1 is a TEST row of another batch
    repo._vehicle_reference.append(ref("vehicle_id", V1, batch="OTHER-BATCH"))
    assert (await other.vehicle_schedule(V1)).intervals == ()  # the first batch's rows never leak
    repo._vehicle_reference.append(ref("vehicle_id", V2, scope=REFERENCE_SCOPE_REAL))
    assert await code_of(Svc(repo).vehicle_schedule("VEH-NOPE")) == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_e2_data_invalid_history_fails_closed() -> None:
    repo = E2Spy()
    await made(repo, create(B, "FULL_DAY", nov(20), nov(21)))
    rows(repo)[0]["revision_no"] = "x"
    assert await code_of(sched(repo)) == "E2_HISTORY_DATA_INVALID"
    rows(repo)[0]["revision_no"] = "1"
    rows(repo)[0]["driver_id"] = "DRV-SYN-GONE"
    with pytest.raises(ApiError) as exc:
        await sched(repo)
    assert exc.value.code == "E2_HISTORY_DATA_INVALID" and exc.value.details["issues"] == {
        "DRIVER_REFERENCE_MISSING": 1}


@pytest.mark.asyncio
async def test_e2_conflicted_history_is_explicit_and_blocks_new_planning() -> None:
    repo = E2Spy()
    b = await made(repo, create(B, "FULL_DAY", nov(20), nov(21)))
    clash = dict(rows(repo)[0])
    clash.update(record_id="ODA-SYN-CLASH", event_id="ODA-SYN-CLASH", driver_id=C, request_id="r-clash")
    rows(repo).append(clash)  # e.g. a residual race outside one process
    s = await sched(repo, now=bkk(20, 9))
    assert (s.timeline_status, s.current_status, s.current) == ("CONFLICTED", "CONFLICTED", None)
    assert await code_of(op(repo, create(A, "FULL_DAY", nov(25), nov(26)))) == "E2_TIMELINE_CONFLICTED"
    cancel = {"operation": "CANCEL", "event_id": "ODA-SYN-CLASH", "expected_revision_no": "1", "reason_th": REASON}
    assert (await op(repo, cancel)).changed  # an authorized correction resolves it
    assert (await sched(repo)).timeline_status == "VALID" and b


# ---------------------------------------------------------------------------
# E2-R2FF / E2-LEGACY — non-interference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2_r2ff_e2_never_writes_permanent_responsibility_and_is_not_blocked_by_it() -> None:
    repo = E2Spy()
    await _r2ff_transfer(repo, V1, A, None, "2026-01-01")
    before = [dict(r) for r in repo._crane_driver_responsibility_history]
    repo.calls.clear()
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))  # the permanent driver explicitly assigned
    await op(repo, {"operation": "CANCEL", "event_id": a, "expected_revision_no": "1", "reason_th": REASON})
    assert repo._crane_driver_responsibility_history == before
    assert "append_crane_driver_responsibility_history" not in repo.calls


@pytest.mark.asyncio
async def test_e2_legacy_vehicle_driver_is_never_read_or_written() -> None:
    repo = E2Spy()
    assert not hasattr(repo, "_vehicle_driver_assignments")  # R2 Batch R2-C3: the legacy store is retired
    a = await made(repo, create(A, "FULL_DAY", nov(1), nov(20)))
    await op(repo, create(B, "NIGHT_SHIFT", nov(20), nov(25), NIGHT, handover=(a, "1")))
    await sched(repo)
    await Svc(repo).vehicle_history(V1)
    await Svc(repo).driver_schedule(A)
    assert not [c for c in repo.calls if "vehicle_driver" in c]


@pytest.mark.asyncio
async def test_e2_driver_master_routes_stay_and_phase6_assignment_routes_are_retired(client) -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    for path in ("/api/v1/drivers", "/api/v1/drivers/{driver_id}"):
        assert path in paths, path
    # R2 Batch R2-C3 (A2-10): the Phase 6 assignment routes are retired; E2 never replaced them in place.
    for path in ("/api/v1/vehicles/{vehicle_id}/driver-assignments", "/api/v1/vehicle-driver-assignments/{assignment_id}/end"):
        assert path not in paths, path
    e2 = sorted(p for p in paths if "operational-driver" in p)
    assert e2 == ["/api/v1/drivers/{driver_id}/operational-driver-assignments",
                  "/api/v1/vehicles/{vehicle_id}/operational-driver-assignment-history",
                  "/api/v1/vehicles/{vehicle_id}/operational-driver-assignment-operations",
                  "/api/v1/vehicles/{vehicle_id}/operational-driver-assignments"]
