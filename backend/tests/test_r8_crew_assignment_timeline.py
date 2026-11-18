"""R8 early workstream — pure crew record validation and derivation
(`crew_assignment_timeline`). SYNTHETIC data only; no I/O.

Proves: OD-1 role rules; the E2 time contract reused (FULL_DAY / shifts with an
explicit next-day end, half-open Bangkok units stored as UTC); revision chains;
person/vehicle immutability per event (OD-4); cancellation and early end; any
structural defect makes the whole model INVALID (never partial).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.crew_assignment_timeline import (
    CREW_ASSIGNMENT_HISTORY_COLUMNS,
    derive_crew,
    role_issue,
    validate_crew_row,
)

FP = "a" * 64


def row(record_id: str, *, kind: str = "ASSIGNMENT", event_id: str | None = None, rev: str = "1",
        supersedes: str = "", op: str = "CREATE", **cells) -> dict[str, str]:
    base = dict.fromkeys(CREW_ASSIGNMENT_HISTORY_COLUMNS, "")
    base.update(record_id=record_id, operation_id="CRO-1", record_kind=kind, entry_operation=op,
                event_id=event_id or record_id, revision_no=rev, supersedes_record_id=supersedes,
                vehicle_id="VEH-1048", recorded_at="2026-11-18T01:00:00+00:00", recorded_by="USR",
                request_id=f"req-{record_id}", request_fingerprint=FP, is_test_data="TRUE", test_batch_id="B")
    if kind != "CANCELLATION":
        base.update(personnel_id="PER-1", crew_role="RIGGER", mode="FULL_DAY", start_date="2026-11-20",
                    end_date="2026-11-21")
    base.update(cells)
    return base


@pytest.mark.parametrize("role,note,issue", [
    ("RIGGER", "", None), ("SIGNALMAN", "", None), ("OTHER", "ผู้ช่วยยกของ", None),
    ("OTHER", "", "ROLE_NOTE_REQUIRED"), ("OTHER", "   ", "ROLE_NOTE_REQUIRED"), ("OTHER", "x" * 201, "ROLE_NOTE_REQUIRED"),
    ("RIGGER", "note", "ROLE_NOTE_NOT_ALLOWED"), ("DRIVER", "", "ROLE_INVALID"), ("rigger", "", "ROLE_INVALID"),
])
def test_role_rules_od1(role, note, issue) -> None:
    assert role_issue(role, note) == issue


def test_full_day_units_are_half_open_bangkok_days() -> None:
    model = derive_crew([row("CRA-1")])
    assert model.status == "VALID"
    first, second = model.intervals
    assert first.start == datetime(2026, 11, 19, 17, 0, tzinfo=timezone.utc)  # 2026-11-20 00:00 Bangkok
    assert first.end == second.start == datetime(2026, 11, 20, 17, 0, tzinfo=timezone.utc)
    assert second.end == datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc)


def test_night_shift_with_next_day_end() -> None:
    model = derive_crew([row("CRA-1", mode="NIGHT_SHIFT", start_date="2026-11-20", end_date="2026-11-20",
                             shift_start_time="22:00", shift_end_time="06:00", shift_end_day_offset="1")])
    (unit,) = model.intervals
    assert unit.start == datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
    assert unit.end == datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc)
    assert unit.label_date.isoformat() == "2026-11-20"  # labelled by its starting date


@pytest.mark.parametrize("cells", [
    {"mode": "DAY_SHIFT"},  # shift required
    {"mode": "DAY_SHIFT", "shift_start_time": "08:00", "shift_end_time": "08:00", "shift_end_day_offset": "0"},
    {"mode": "FULL_DAY", "shift_start_time": "08:00"},
    {"end_date": "2026-11-19"},
    {"crew_role": "OTHER"},
    {"personnel_id": ""},
    {"is_test_data": "yes"},
    {"early_end_at": "2026-11-20T10:00:00"},  # naive
])
def test_structural_defects_make_the_model_invalid(cells) -> None:
    model = derive_crew([row("CRA-1", **cells)])
    assert model.status == "INVALID" and model.intervals == [] and model.issue_counts


def test_revision_cancellation_and_early_end() -> None:
    a = row("CRA-1")
    rev = row("CRA-2", kind="REVISION", event_id="CRA-1", rev="2", supersedes="CRA-1", op="REVISE",
              crew_role="SIGNALMAN", end_date="2026-11-20")
    model = derive_crew([a, rev])
    state = model.assignments["CRA-1"]
    assert (state.role, state.revision_no, len(model.intervals)) == ("SIGNALMAN", "2", 1)
    cancel = row("CRA-3", kind="CANCELLATION", event_id="CRA-1", rev="3", supersedes="CRA-2", op="CANCEL")
    model = derive_crew([a, rev, cancel])
    assert model.assignments["CRA-1"].lifecycle == "CANCELLED" and model.intervals == []
    early = row("CRA-4", kind="REVISION", event_id="CRA-1", rev="2", supersedes="CRA-1", op="EARLY_END",
                early_end_at="2026-11-20T03:00:00+00:00")
    (unit,) = derive_crew([a, early]).intervals
    assert unit.end == datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", [
    {"rev": "3"},  # gap in revisions
    {"supersedes": "CRA-X"},  # wrong predecessor
    {"vehicle_id": "VEH-OTHER"},  # an event never moves vehicle
    {"personnel_id": "PER-2"},  # OD-4: an event never changes person
])
def test_broken_chains_are_invalid(bad) -> None:
    cells = {k: v for k, v in bad.items() if k not in ("rev", "supersedes")}
    rev = row("CRA-2", kind="REVISION", event_id="CRA-1", rev=bad.get("rev", "2"),
              supersedes=bad.get("supersedes", "CRA-1"), op="REVISE", **cells)
    assert derive_crew([row("CRA-1"), rev]).status == "INVALID"


def test_nothing_follows_a_cancellation_and_cancellations_carry_no_state() -> None:
    cancel = row("CRA-2", kind="CANCELLATION", event_id="CRA-1", rev="2", supersedes="CRA-1", op="CANCEL")
    after = row("CRA-3", kind="REVISION", event_id="CRA-1", rev="3", supersedes="CRA-2", op="REVISE")
    assert derive_crew([row("CRA-1"), cancel, after]).status == "INVALID"
    assert "CANCELLATION_STATE_NOT_ALLOWED" in validate_crew_row({**cancel, "personnel_id": "PER-1"})
