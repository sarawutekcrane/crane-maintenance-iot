"""R5 T1 — pure Repair substate and work-time rules (no I/O).

Roadmap examples EX-1..EX-3, explicit breaks, midnight / Asia/Bangkok dates,
no maximum length, same-technician overlap, revision chains and confirmation
validity (OD-2). Synthetic values only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.work_time import (
    RECORD_CORRECTION,
    RECORD_ENTRY,
    RECORD_VOID,
    SUBSTATE_AWAITING_PARTS,
    SUBSTATE_REPAIRING,
    TIME_CLASS_OVERTIME,
    TIME_CLASS_REGULAR,
    RepairSubstatePeriod,
    WorkBreak,
    WorkTimeConfirmation,
    WorkTimeEntry,
    WorkTimeRuleError,
    bangkok_dates,
    current_revisions,
    find_overlap,
    net_seconds,
    substate_conflict,
    substate_durations,
    team_totals,
    technician_totals,
    unconfirmed_entries,
    validate_breaks,
    validate_interval,
)

BKK = timezone(timedelta(hours=7))
NOW = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)
H = 3600


def at(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    """A Bangkok wall-clock instant, normalized to UTC."""
    return datetime(2026, month, day, hour, minute, tzinfo=BKK).astimezone(timezone.utc)


def entry(tid: str, start: datetime, end: datetime, klass: str = TIME_CLASS_REGULAR, *, breaks=(), job: str = "RPR-1",
          entry_id: str | None = None, revision: int = 1, kind: str = RECORD_ENTRY) -> WorkTimeEntry:
    return WorkTimeEntry(entry_id=entry_id or f"E-{tid}-{start.isoformat()}", revision=revision, record_kind=kind,
                         work_kind="REPAIR", job_id=job, technician_id=tid, started_at=start, ended_at=end,
                         time_class=klass, description="งานทดสอบ", breaks=tuple(breaks), recorded_by="u",
                         recorded_at=NOW, request_id=f"r-{tid}-{start.isoformat()}-{revision}",
                         request_fingerprint="f")


def period(substate: str, start: datetime, end: datetime | None, pid: str = "P", revision: int = 1,
           kind: str = RECORD_ENTRY) -> RepairSubstatePeriod:
    return RepairSubstatePeriod(period_id=pid, revision=revision, record_kind=kind, repair_id="RPR-1",
                                substate=substate, started_at=start, ended_at=end, recorded_by="u", recorded_at=NOW,
                                request_id=f"r-{pid}-{revision}", request_fingerprint="f")


# ---------------------------------------------------------------- Roadmap examples


def test_ex1_five_days_repairing_plus_ten_days_waiting_is_fifteen_elapsed_days() -> None:
    opened = at(1, 8)
    periods = [period(SUBSTATE_REPAIRING, opened, opened + timedelta(days=5), "P1"),
               period(SUBSTATE_AWAITING_PARTS, opened + timedelta(days=5), opened + timedelta(days=15), "P2")]
    durations = substate_durations(periods, opened, opened + timedelta(days=15))
    assert durations["repairing_seconds"] == 5 * 24 * H
    assert durations["awaiting_parts_seconds"] == 10 * 24 * H
    assert durations["elapsed_seconds"] == 15 * 24 * H  # 24-hour days, nights included
    assert durations["other_seconds"] == 0


def test_rm5_elapsed_includes_other_periods_and_other_is_never_assumed_zero() -> None:
    opened = at(1, 8)
    periods = [period(SUBSTATE_REPAIRING, opened + timedelta(days=1), opened + timedelta(days=2), "P1")]
    durations = substate_durations(periods, opened, opened + timedelta(days=4))
    assert durations["elapsed_seconds"] == 4 * 24 * H
    assert durations["other_seconds"] == 3 * 24 * H
    assert durations["repairing_seconds"] + durations["awaiting_parts_seconds"] != durations["elapsed_seconds"]


def test_ex2_four_technicians_eight_hours_five_days_is_160_man_hours() -> None:
    entries = [entry(f"T{t}", at(day, 8), at(day, 16)) for t in range(1, 5) for day in range(2, 7)]
    per = technician_totals(entries)
    assert all(row["total_seconds"] == 40 * H and len(row["workdays"]) == 5 for row in per.values())
    team = team_totals(per)
    assert team["total_seconds"] == 160 * H and team["technician_count"] == 4


def test_ex3_eight_plus_two_and_eight_plus_three_is_21_man_hours_16_regular_5_overtime_2_workdays() -> None:
    entries = [entry("T1", at(2, 8), at(2, 16)), entry("T1", at(2, 17), at(2, 19), TIME_CLASS_OVERTIME),
               entry("T1", at(3, 8), at(3, 16)), entry("T1", at(3, 17), at(3, 20), TIME_CLASS_OVERTIME)]
    row = technician_totals(entries)["T1"]
    assert (row["regular_seconds"], row["overtime_seconds"], row["total_seconds"]) == (16 * H, 5 * H, 21 * H)
    assert row["workdays"] == ["2026-11-02", "2026-11-03"]
    assert 21 / 8 == 2.625 and len(row["workdays"]) != 2.625  # actual dates, never an 8-hour man-day figure


def test_rm8_no_automatic_overtime_split_and_no_eight_hour_credit() -> None:
    long_regular = entry("T1", at(2, 6), at(2, 20))  # 14 h, all REGULAR as declared
    row = technician_totals([long_regular])["T1"]
    assert (row["regular_seconds"], row["overtime_seconds"]) == (14 * H, 0)
    short = technician_totals([entry("T2", at(2, 8), at(2, 9))])["T2"]
    assert short["total_seconds"] == H  # never rounded up to 8 h


# ---------------------------------------------------------------- breaks


def test_breaks_are_subtracted_and_the_declaration_is_mandatory() -> None:
    start, end = at(2, 8), at(2, 17)
    breaks = validate_breaks(start, end, [WorkBreak(started_at=at(2, 12), ended_at=at(2, 13))])
    assert net_seconds(entry("T1", start, end, breaks=breaks)) == 8 * H
    assert validate_breaks(start, end, []) == ()
    with pytest.raises(WorkTimeRuleError) as missing:
        validate_breaks(start, end, None)
    assert missing.value.code == "WORK_TIME_BREAKS_REQUIRED"


@pytest.mark.parametrize("brk", [
    (at(2, 7), at(2, 9)),     # starts before the period
    (at(2, 16), at(2, 18)),   # ends after the period
    (at(2, 12), at(2, 12)),   # zero length
    (at(2, 13), at(2, 12)),   # negative
])
def test_invalid_breaks_are_refused(brk) -> None:
    with pytest.raises(WorkTimeRuleError) as exc:
        validate_breaks(at(2, 8), at(2, 17), [WorkBreak(started_at=brk[0], ended_at=brk[1])])
    assert exc.value.code == "WORK_TIME_BREAK_INVALID"


def test_overlapping_breaks_and_breaks_covering_the_whole_period_are_refused() -> None:
    with pytest.raises(WorkTimeRuleError):
        validate_breaks(at(2, 8), at(2, 17), [WorkBreak(started_at=at(2, 12), ended_at=at(2, 13)),
                                             WorkBreak(started_at=at(2, 12, 30), ended_at=at(2, 14))])
    with pytest.raises(WorkTimeRuleError):
        validate_breaks(at(2, 8), at(2, 9), [WorkBreak(started_at=at(2, 8), ended_at=at(2, 9))])


def test_a_gap_between_two_periods_is_not_a_break() -> None:
    entries = [entry("T1", at(2, 8), at(2, 12)), entry("T1", at(2, 13), at(2, 17))]
    assert all(e.breaks == () for e in entries)
    assert technician_totals(entries)["T1"]["total_seconds"] == 8 * H  # the 1-h gap is simply unrecorded


# ---------------------------------------------------------------- intervals, midnight, dates


def test_interval_rules_without_an_invented_maximum_length() -> None:
    start, end = validate_interval(at(1, 8), at(3, 8), NOW)  # 48 h is accepted
    assert end - start == timedelta(hours=48)
    for bad in [(at(2, 9), at(2, 9)), (at(2, 9), at(2, 8)), (NOW, NOW + timedelta(hours=1))]:
        with pytest.raises(WorkTimeRuleError) as exc:
            validate_interval(bad[0], bad[1], NOW)
        assert exc.value.code == "WORK_TIME_INVALID_INTERVAL"
    with pytest.raises(WorkTimeRuleError) as naive:
        validate_interval(datetime(2026, 11, 2, 8), datetime(2026, 11, 2, 9), NOW)
    assert naive.value.code == "WORK_TIME_TIMEZONE_REQUIRED"


def test_work_across_midnight_counts_both_bangkok_dates_and_full_hours() -> None:
    night = entry("T1", at(2, 22), at(3, 2), TIME_CLASS_OVERTIME)
    row = technician_totals([night])["T1"]
    assert row["overtime_seconds"] == 4 * H
    assert row["workdays"] == ["2026-11-02", "2026-11-03"]


def test_dates_are_bangkok_dates_and_an_end_at_local_midnight_does_not_touch_the_next_day() -> None:
    assert bangkok_dates(at(2, 20), at(3, 0)) == {datetime(2026, 11, 2).date()}
    # 01:00–03:00 Bangkok on the 3rd is still the 2nd in UTC; the Bangkok date decides.
    assert bangkok_dates(at(3, 1), at(3, 3)) == {datetime(2026, 11, 3).date()}


def test_a_date_with_only_break_time_is_not_a_workday() -> None:
    e = entry("T1", at(2, 22), at(3, 6), breaks=[WorkBreak(started_at=at(2, 23), ended_at=at(3, 5))])
    assert technician_totals([e])["T1"]["workdays"] == ["2026-11-02", "2026-11-03"]
    only_break_on_3rd = entry("T1", at(2, 20), at(3, 1), breaks=[WorkBreak(started_at=at(2, 23), ended_at=at(3, 1))],
                              entry_id="E2")
    # The period ends at 01:00 on the 3rd but the 3rd holds only break time.
    with pytest.raises(WorkTimeRuleError):
        validate_breaks(only_break_on_3rd.started_at, only_break_on_3rd.ended_at,
                        [WorkBreak(started_at=at(2, 23), ended_at=at(3, 2))])
    assert technician_totals([only_break_on_3rd])["T1"]["workdays"] == ["2026-11-02"]


# ---------------------------------------------------------------- overlap


def test_same_technician_overlap_across_work_orders_is_detected() -> None:
    a = entry("T1", at(2, 8), at(2, 12), job="RPR-1")
    b = entry("T1", at(2, 11), at(2, 14), job="PMW-1", entry_id="E-B")
    assert find_overlap(b, [a]) == a
    adjacent = entry("T1", at(2, 12), at(2, 14), job="PMW-1", entry_id="E-C")
    assert find_overlap(adjacent, [a]) is None  # half-open: touching is not overlapping


def test_other_technicians_and_voided_entries_never_overlap() -> None:
    a = entry("T1", at(2, 8), at(2, 12))
    assert find_overlap(entry("T2", at(2, 8), at(2, 12), entry_id="X"), [a]) is None
    void = entry("T1", at(2, 8), at(2, 12), entry_id="V", kind=RECORD_VOID)
    assert find_overlap(entry("T1", at(2, 9), at(2, 10), entry_id="Y"), [void]) is None


def test_work_inside_another_entrys_break_is_not_an_overlap() -> None:
    a = entry("T1", at(2, 8), at(2, 17), breaks=[WorkBreak(started_at=at(2, 12), ended_at=at(2, 13))])
    inside_break = entry("T1", at(2, 12), at(2, 13), job="PMW-1", entry_id="E-IN")
    assert find_overlap(inside_break, [a]) is None
    assert find_overlap(entry("T1", at(2, 12), at(2, 13, 30), job="PMW-1", entry_id="E-OUT"), [a]) == a


def test_another_revision_of_the_same_entry_is_not_an_overlap() -> None:
    a = entry("T1", at(2, 8), at(2, 12), entry_id="E1")
    corrected = entry("T1", at(2, 9), at(2, 13), entry_id="E1", revision=2, kind=RECORD_CORRECTION)
    assert find_overlap(corrected, [a]) is None


# ---------------------------------------------------------------- substates


def test_substate_periods_never_overlap_and_only_one_can_be_ongoing() -> None:
    p1 = period(SUBSTATE_REPAIRING, at(2, 8), at(2, 12), "P1")
    assert substate_conflict(period(SUBSTATE_AWAITING_PARTS, at(2, 11), at(2, 14), "P2"), [p1]) == p1
    assert substate_conflict(period(SUBSTATE_AWAITING_PARTS, at(2, 12), None, "P2"), [p1]) is None
    ongoing = period(SUBSTATE_AWAITING_PARTS, at(2, 12), None, "P2")
    assert substate_conflict(period(SUBSTATE_REPAIRING, at(5, 8), None, "P3"), [ongoing]) == ongoing


def test_awaiting_parts_is_never_counted_as_repairing_and_creates_no_labor() -> None:
    opened = at(1, 8)
    periods = [period(SUBSTATE_AWAITING_PARTS, opened, opened + timedelta(days=2), "P1")]
    durations = substate_durations(periods, opened, opened + timedelta(days=2))
    assert (durations["repairing_seconds"], durations["awaiting_parts_seconds"]) == (0, 2 * 24 * H)
    assert technician_totals([]) == {}  # no labor exists unless a technician records it


def test_void_periods_are_ignored_and_an_ongoing_period_runs_to_the_end_bound() -> None:
    opened = at(1, 8)
    periods = [period(SUBSTATE_REPAIRING, opened, None, "P1"),
               period(SUBSTATE_AWAITING_PARTS, opened, opened + timedelta(days=1), "P2", kind=RECORD_VOID)]
    durations = substate_durations(periods, opened, opened + timedelta(hours=10))
    assert durations["repairing_seconds"] == 10 * H and durations["awaiting_parts_seconds"] == 0


# ---------------------------------------------------------------- revisions and confirmation


def test_void_revisions_are_excluded_from_totals() -> None:
    e1 = entry("T1", at(2, 8), at(2, 16), entry_id="E1")
    e1_void = entry("T1", at(2, 8), at(2, 16), entry_id="E1", revision=2, kind=RECORD_VOID)
    latest = current_revisions([e1, e1_void], "entry_id")
    assert technician_totals(latest.values()) == {}


def test_a_broken_revision_chain_is_untrusted_history() -> None:
    with pytest.raises(WorkTimeRuleError) as exc:
        current_revisions([entry("T1", at(2, 8), at(2, 9), entry_id="E1", revision=2)], "entry_id")
    assert exc.value.code == "WORK_TIME_DATA_INVALID"


def confirmation(*refs: str) -> WorkTimeConfirmation:
    return WorkTimeConfirmation(confirmation_id="C", work_kind="REPAIR", job_id="RPR-1", entries=refs,
                                confirmed_by="m", confirmed_at=NOW, request_id="rc", request_fingerprint="f")


def test_only_the_current_revision_is_confirmed_and_a_correction_needs_a_new_confirmation() -> None:
    r1 = entry("T1", at(2, 8), at(2, 16), entry_id="E1")
    assert unconfirmed_entries([r1], [confirmation("E1@1")]) == []
    r2 = entry("T1", at(2, 8), at(2, 17), entry_id="E1", revision=2, kind=RECORD_CORRECTION)
    assert [e.ref for e in unconfirmed_entries([r1, r2], [confirmation("E1@1")])] == ["E1@2"]
    assert unconfirmed_entries([r1, r2], [confirmation("E1@1"), confirmation("E1@2")]) == []


def test_a_voided_entry_still_needs_its_void_confirmed() -> None:
    r1 = entry("T1", at(2, 8), at(2, 16), entry_id="E1")
    r2 = entry("T1", at(2, 8), at(2, 16), entry_id="E1", revision=2, kind=RECORD_VOID)
    assert [e.ref for e in unconfirmed_entries([r1, r2], [confirmation("E1@1")])] == ["E1@2"]
