"""R2 Batch R2-C1 — E2 operational driver assignment: the pure timeline
(`operational_driver_timeline`, no I/O). Every row is SYNTHETIC.

Batch-local ids: E2T-MODE (modes / durations / time boundaries), -UNIT
(units, Bangkok, half-open), -LIMIT (DQ-7), -ROW (row validation), -CHAIN
(revision chains and INVALID), -CONF (conflicts / adjacency), -HO (handover
structure).
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from app.domain.operational_driver_timeline import (
    HANDOVER_H2,
    HANDOVER_H3,
    MODE_DAY_SHIFT,
    MODE_FULL_DAY,
    MODE_NIGHT_SHIFT,
    OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS,
    STATUS_CONFLICTED,
    STATUS_INVALID,
    STATUS_VALID,
    AssignmentState,
    Interval,
    Schedule,
    adjacent_pairs,
    bangkok,
    derive,
    find_conflicts,
    handover_structure_issue,
    parse_dates,
    schedule_cells,
    schedule_issues,
    shift_duration_valid,
    validate_row,
)

UTC = timezone.utc
D = date(2026, 11, 20)
H = "a" * 64


def utc(y, mo, d, h=0, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def night(start=D, end=D, s=time(20, 0), e=time(8, 0)) -> Schedule:
    return Schedule(MODE_NIGHT_SHIFT, start, end, s, e, 1)


def full(start, end) -> Schedule:
    return Schedule(MODE_FULL_DAY, start, end)


def state(event_id: str, sched: Schedule, vehicle="V1") -> AssignmentState:
    return AssignmentState(event_id, vehicle, "1", event_id, {}, sched, "DRV", "ACTIVE", None, "", "")


def row(record_id: str, sched: Schedule, *, kind="ASSIGNMENT", rev="1", event=None, supersedes="", vehicle="V1",
        driver="DRV-1", **extra) -> dict[str, str]:
    r = dict.fromkeys(OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS, "")
    r.update(schedule_cells(sched))
    r.update(record_id=record_id, operation_id="ODO-1", record_kind=kind, entry_operation="CREATE",
             event_id=event or record_id, revision_no=rev, supersedes_record_id=supersedes, vehicle_id=vehicle,
             driver_id=driver, recorded_at="2026-10-01T00:00:00.000000+00:00", recorded_by="u", request_id="r",
             request_fingerprint=H, is_test_data="TRUE", test_batch_id="B")
    r.update(extra)
    return r


# ---------------------------------------------------------------------------
# E2T-MODE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("start,end,offset,ok", [
    ("08:00", "20:00", 0, True),
    ("20:00", "08:00", 1, True),  # cross midnight
    ("08:00", "08:00", 1, True),  # exactly 24 hours, explicit next-day marker
    ("08:00", "08:00", 0, False),  # ambiguous zero length is never accepted
    ("20:00", "08:00", 0, False),  # negative
    ("08:00", "09:00", 1, False),  # 25 hours
    ("00:00", "00:00", 1, True),
])
def test_e2t_mode_shift_duration_more_than_zero_at_most_24h(start, end, offset, ok) -> None:
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    assert shift_duration_valid(s, e, offset) is ok


def test_e2t_mode_full_day_takes_no_shift_and_shifts_need_times() -> None:
    assert schedule_issues(Schedule(MODE_FULL_DAY, D, D, time(8), time(20), 0)) == ["SHIFT_NOT_ALLOWED"]
    assert schedule_issues(Schedule(MODE_DAY_SHIFT, D, D)) == ["SHIFT_REQUIRED"]
    assert schedule_issues(Schedule(MODE_DAY_SHIFT, D, D, time(8), time(8), 0)) == ["SHIFT_DURATION_INVALID"]
    assert schedule_issues(Schedule(MODE_DAY_SHIFT, D, date(2026, 11, 19), time(8), time(20), 0)) == ["RANGE_INVALID"]
    assert schedule_issues(night()) == []


# ---------------------------------------------------------------------------
# E2T-UNIT — Asia/Bangkok, half-open, NIGHT labelled by its start date
# ---------------------------------------------------------------------------


def test_e2t_unit_full_day_is_bangkok_midnight_to_next_midnight() -> None:
    start, end = full(D, D).unit(D)
    assert (start, end) == (utc(2026, 11, 19, 17), utc(2026, 11, 20, 17))  # 00:00 / 24:00 ICT (UTC+7)
    assert bangkok(date(2026, 11, 21)) == end  # the stored end is next-day 00:00, never a literal 24:00


def test_e2t_unit_night_belongs_to_its_start_date_and_crosses_midnight() -> None:
    start, end = night().unit(D)
    assert (start, end) == (utc(2026, 11, 20, 13), utc(2026, 11, 21, 1))  # 20:00 Nov 20 -> 08:00 Nov 21 ICT


def test_e2t_unit_dates_skip_excluded_and_cells_round_trip() -> None:
    sched = Schedule(MODE_NIGHT_SHIFT, date(2026, 11, 15), date(2026, 11, 20), time(20), time(8), 1,
                     (date(2026, 11, 17),))
    assert [d.day for d in sched.dates()] == [15, 16, 18, 19, 20]
    cells = schedule_cells(sched)
    assert cells["excluded_dates"] == "2026-11-17" and cells["shift_end_day_offset"] == "1"
    assert parse_dates("2026-11-18,2026-11-17") is None  # strictly ascending only


# ---------------------------------------------------------------------------
# E2T-LIMIT — DQ-7
# ---------------------------------------------------------------------------


def test_e2t_limit_366_inclusive_days() -> None:
    assert schedule_issues(full(date(2026, 1, 1), date(2027, 1, 1))) == []  # 366 days
    assert schedule_issues(full(date(2026, 1, 1), date(2027, 1, 2))) == ["RANGE_TOO_LONG"]  # 367


def test_e2t_limit_stored_history_is_not_invalidated_by_the_duration_limit() -> None:
    # A stored row is history: the limit applies to writes, never retroactively to reading it.
    long = row("ODA-1", full(date(2024, 1, 1), date(2025, 6, 1)))
    assert validate_row(long) == []


# ---------------------------------------------------------------------------
# E2T-ROW / E2T-CHAIN
# ---------------------------------------------------------------------------


def test_e2t_row_server_set_fields_are_validated() -> None:
    good = row("ODA-1", full(D, D))
    assert validate_row(good) == []
    assert "FINGERPRINT_INVALID" in validate_row({**good, "request_fingerprint": "x"})
    assert "TEST_FLAG_INVALID" in validate_row({**good, "is_test_data": "true"})
    assert "SCOPE_INCONSISTENT" in validate_row({**good, "test_batch_id": ""})
    assert "EVENT_ID_MISMATCH" in validate_row({**good, "event_id": "OTHER"})
    assert "SCHEDULE_INVALID" in validate_row({**good, "start_date": "2026-11-31"})
    assert "FIELD_MUST_BE_BLANK:handover_at" in validate_row({**good, "handover_at": "2026-11-20T00:00:00+00:00"})


def test_e2t_chain_revision_and_cancellation_rules() -> None:
    first = row("ODA-1", full(D, D))
    rev = row("ODA-2", full(D, date(2026, 11, 21)), kind="REVISION", rev="2", event="ODA-1", supersedes="ODA-1")
    assert derive([first, rev]).status == STATUS_VALID
    bad_super = {**rev, "supersedes_record_id": "ODA-9"}
    assert derive([first, bad_super]).issue_counts == {"EVENT_CHAIN_INVALID": 1}
    cancel = dict.fromkeys(OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS, "")
    cancel.update({k: first[k] for k in ("operation_id", "vehicle_id", "recorded_at", "recorded_by", "request_id",
                                          "request_fingerprint", "is_test_data", "test_batch_id")})
    cancel.update(record_id="ODA-3", record_kind="CANCELLATION", entry_operation="CANCEL", event_id="ODA-1",
                  revision_no="2", supersedes_record_id="ODA-1", reason_th="r")
    model = derive([first, cancel])
    assert model.status == STATUS_VALID and model.assignments["ODA-1"].lifecycle == "CANCELLED"
    assert model.intervals == []  # released
    after_cancel = {**rev, "revision_no": "3", "supersedes_record_id": "ODA-3"}
    assert derive([first, cancel, after_cancel]).status == STATUS_INVALID  # terminal


# ---------------------------------------------------------------------------
# E2T-CONF
# ---------------------------------------------------------------------------


def _iv(event, vehicle, driver, start, end) -> Interval:
    return Interval(event, "1", vehicle, driver, MODE_DAY_SHIFT, D, start, end)


def test_e2t_conf_half_open_touching_is_not_overlap_but_warns_for_one_driver() -> None:
    a = _iv("A", "V1", "D1", utc(2026, 11, 20, 1), utc(2026, 11, 20, 13))
    b = _iv("B", "V2", "D1", utc(2026, 11, 20, 13), utc(2026, 11, 21, 1))
    assert find_conflicts([a, b]) == []
    assert adjacent_pairs([a, b]) == [(a, b)]


def test_e2t_conf_both_axes() -> None:
    a = _iv("A", "V1", "D1", utc(2026, 11, 20, 1), utc(2026, 11, 20, 13))
    same_vehicle = _iv("B", "V1", "D2", utc(2026, 11, 20, 12), utc(2026, 11, 20, 14))
    same_driver = _iv("C", "V2", "D1", utc(2026, 11, 20, 12), utc(2026, 11, 20, 14))
    axes = {(c.axis, c.key) for c in find_conflicts([a, same_vehicle, same_driver])}
    assert axes == {("VEHICLE", "V1"), ("DRIVER", "D1")}


def test_e2t_conf_overlapping_stored_rows_derive_conflicted_never_a_guess() -> None:
    a = row("ODA-1", full(D, D), driver="D1")
    b = row("ODA-2", full(D, D), driver="D2")
    model = derive([a, b])
    assert model.status == STATUS_CONFLICTED and model.vehicle_status("V1") == STATUS_CONFLICTED


# ---------------------------------------------------------------------------
# E2T-HO — H2 / E2-H3 structure on the stored schedules
# ---------------------------------------------------------------------------


def test_e2t_ho_h2_last_day_night_only_and_non_empty() -> None:
    pred = state("A", full(date(2026, 11, 1), D))
    succ = state("B", night(D, date(2026, 11, 25)))
    at = succ.schedule.unit(D)[0]
    assert handover_structure_issue(HANDOVER_H2, pred, succ, at) is None
    mid = state("B", night(date(2026, 11, 15), D))
    assert handover_structure_issue(HANDOVER_H2, pred, mid, mid.schedule.unit(date(2026, 11, 15))[0]) \
        == "HANDOVER_NOT_PERMITTED"  # B12: mid-range insertion
    midnight = state("B", night(D, D, time(0, 0), time(8, 0)))
    one_day = state("A", full(D, D))
    assert handover_structure_issue(HANDOVER_H2, one_day, midnight, midnight.schedule.unit(D)[0]) \
        == "HANDOVER_EMPTY_INTERVAL"  # the predecessor would keep nothing


def test_e2t_ho_one_day_full_day_to_same_day_night_is_a_valid_h2() -> None:
    pred = state("A", full(D, D))
    succ = state("B", night(D, D))
    assert handover_structure_issue(HANDOVER_H2, pred, succ, succ.schedule.unit(D)[0]) is None


def test_e2t_ho_e2_h3_needs_an_overnight_night_and_next_day_full_day() -> None:
    pred = state("B", night(D, D))
    succ = state("A", full(date(2026, 11, 21), date(2026, 11, 25)))
    assert handover_structure_issue(HANDOVER_H3, pred, succ, pred.schedule.unit(D)[1]) is None
    same_day = state("B", Schedule(MODE_NIGHT_SHIFT, D, D, time(18), time(23), 0))
    assert handover_structure_issue(HANDOVER_H3, same_day, succ, same_day.schedule.unit(D)[1]) \
        == "HANDOVER_NOT_PERMITTED"  # no carry into D+1
