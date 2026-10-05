"""Phase 7 Batch 7O2a — pure registry domain (contract Final Rev2 §3.6, §4.3,
§4.5, §5, §7.1, §7.7, §8.1): RK1, effective time, branch record validation,
timeline derivation and revision tokens, registration history validation and
consistency, registry field states and reference parsing.

Acceptance rows: R-06, R-07, R-08 (domain part), R-09, R-10. Every fixture is
synthetic (SYN-/BR-TEST- ids), not company data.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.branch_timeline import (
    ASSET_BRANCH_HISTORY_COLUMNS,
    derive_timeline,
    history_revision,
    validate_branch_row,
    vehicle_history_rows,
)
from app.domain.effective_time import EffectiveTimeError, resolve_effective
from app.domain.registration import (
    REGISTRATION_HISTORY_COLUMNS,
    pair_is_valid,
    registration_consistency,
    registration_history_revision,
    registration_key,
    validate_registration_rows,
)
from app.domain.vehicle_registry import (
    REGISTRY_COLUMNS,
    parse_reference_rows,
    registry_from_record,
)

NOW = datetime(2026, 10, 5, 3, 0, 0, tzinfo=timezone.utc)
V = "SYN-V001"


def _fp(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Branch record builders (§5.1 per-kind matrix)
# ---------------------------------------------------------------------------

_seq = itertools.count(1)
_REC0 = datetime(2026, 9, 1, 3, 0, 0, tzinfo=timezone.utc)  # builders record in creation order


def _rec(**cells: str) -> dict[str, str]:
    row = dict.fromkeys(ASSET_BRANCH_HISTORY_COLUMNS, "")
    n = next(_seq)
    row.update(asset_type="VEHICLE", asset_id=V, recorded_by="SYN-USER", request_id=f"req-{n}",
               request_fingerprint=_fp(f"req-{n}"), is_test_data="TRUE", test_batch_id="SYN-BATCH",
               recorded_at=(_REC0 + timedelta(minutes=n)).isoformat())
    row.update(cells)
    return row


def assignment(rid: str, branch: str, start: str, *, src=("BR-TEST-A", "BASELINE"), baseline=None,
               op="TRANSFER", recorded_at: str | None = None, note: str = "") -> dict[str, str]:
    cells = dict(assignment_id=rid, record_kind="ASSIGNMENT", entry_operation=op, event_id=rid, revision_no="1",
                 branch_id=branch, start_at=start, effective_precision="DATETIME", effective_source="CLIENT",
                 recorded_from_branch_id=src[0] or "", recorded_from_source=src[1], note_th=note)
    if baseline is not None:
        cells.update(baseline_branch_id=baseline[0] or "", baseline_source=baseline[1])
    if recorded_at:
        cells["recorded_at"] = recorded_at
    return _rec(**cells)


def correction(rid: str, event: str, supersedes: str, rev: str, branch: str, start: str, *,
               src=("BR-TEST-A", "BASELINE"), recorded_at: str | None = None) -> dict[str, str]:
    cells = dict(assignment_id=rid, record_kind="CORRECTION", entry_operation="CORRECTION", event_id=event,
                 revision_no=rev, supersedes_record_id=supersedes, branch_id=branch, start_at=start,
                 effective_precision="DATETIME", effective_source="CLIENT", recorded_from_branch_id=src[0] or "",
                 recorded_from_source=src[1], note_th="แก้ไข")
    if recorded_at:
        cells["recorded_at"] = recorded_at
    return _rec(**cells)


def cancellation(rid: str, event: str, supersedes: str, rev: str, *, recorded_at: str | None = None) -> dict[str, str]:
    cells = dict(assignment_id=rid, record_kind="CANCELLATION", entry_operation="CANCELLATION", event_id=event,
                 revision_no=rev, supersedes_record_id=supersedes, note_th="ยกเลิก")
    if recorded_at:
        cells["recorded_at"] = recorded_at
    return _rec(**cells)


def reconciliation(rid: str, written: str, old: str, related: str = "", **extra: str) -> dict[str, str]:
    return _rec(assignment_id=rid, record_kind="PROJECTION_RECONCILIATION", entry_operation="PROJECTION_RECONCILIATION",
                branch_id=written, reconciled_old_master_branch_id=old, related_request_id=related,
                note_th="ปรับค่าหลัก", **extra)


T1, T2, T3 = "2026-08-01T00:00:00+00:00", "2026-08-10T00:00:00+00:00", "2026-08-20T00:00:00+00:00"


def _derive(records, master="BR-TEST-B", available=True, context="TEST"):
    return derive_timeline(records, master_branch_id=master, master_available=available, context=context)


# ---------------------------------------------------------------------------
# R-10 — RK1 (§4.3)
# ---------------------------------------------------------------------------


def test_rk1_owner_examples_are_equal() -> None:
    assert registration_key("กข 1234") == registration_key("กข-1234") == registration_key("กข ๑๒๓๔")


def test_rk1_engineering_removals_and_casefold() -> None:
    base = registration_key("AB1234")
    for variant in ("ab 1234", "AB\t1234", "A.B-1234", "AB‐1234", "AB‑1234", "AB–1234", "AB−1234",
                    "AB​1234", "﻿AB1234", " AB1234 ", "AB 1234"):
        assert registration_key(variant) == base, variant


def test_rk1_negatives_no_numeric_or_other_folding() -> None:
    assert registration_key("0012") != registration_key("12")
    assert registration_key("กข1234") != registration_key("กค1234")
    assert registration_key("AB/1234") != registration_key("AB1234")  # '/' is not removed
    assert registration_key("ＡＢ1234") != registration_key("AB1234")  # no full-width folding
    assert registration_key("AB—1234") != registration_key("AB1234")  # em dash is not in the set


def test_rk1_nfc_composes_thai_and_latin() -> None:
    assert registration_key("é") == registration_key("é")


def test_rk1_empty_key_and_pair_rules() -> None:
    assert registration_key(" -.​") == ""
    assert not pair_is_valid(" - ", None)
    assert not pair_is_valid(None, "TH-10")  # province without text
    assert not pair_is_valid("x" * 51, "TH-10")
    assert pair_is_valid("x" * 50, None)
    assert pair_is_valid(None, None)
    assert pair_is_valid("0012", "TH-21")


# ---------------------------------------------------------------------------
# R-09 — effective time (§3.6)
# ---------------------------------------------------------------------------


def test_effective_now_is_server_time_whole_seconds() -> None:
    eff = resolve_effective({"mode": "NOW"}, NOW.replace(microsecond=987654))
    assert (eff.instant, eff.precision, eff.source) == (NOW, "DATETIME", "SERVER_NOW")
    with pytest.raises(EffectiveTimeError) as err:
        resolve_effective({"mode": "NOW"}, NOW, allow_now=False)
    assert err.value.code == "EFFECTIVE_MODE_NOT_ALLOWED"


def test_effective_date_is_bangkok_midnight() -> None:
    eff = resolve_effective({"mode": "DATE", "date": "2026-09-01"}, NOW)
    assert eff.stored == "2026-08-31T17:00:00+00:00"
    assert (eff.precision, eff.source) == ("DATE", "CLIENT")


def test_effective_datetime_offset_precision_future_and_bounds() -> None:
    ok = resolve_effective({"mode": "DATETIME", "at": "2026-09-01T10:00:00+07:00"}, NOW)
    assert ok.stored == "2026-09-01T03:00:00+00:00"
    cases = {
        "EFFECTIVE_TIME_OFFSET_REQUIRED": {"mode": "DATETIME", "at": "2026-09-01T10:00:00"},
        "EFFECTIVE_TIME_PRECISION": {"mode": "DATETIME", "at": "2026-09-01T10:00:00.5+07:00"},
        "FUTURE_EFFECTIVE_NOT_ALLOWED": {"mode": "DATETIME", "at": "2026-10-05T03:00:01+00:00"},
        "EFFECTIVE_TIME_OUT_OF_RANGE": {"mode": "DATE", "date": "1989-12-31"},
        "EFFECTIVE_MODE_INVALID": {"mode": "DATE", "date": "2026-9-1"},
    }
    for code, effective in cases.items():
        with pytest.raises(EffectiveTimeError) as err:
            resolve_effective(effective, NOW)
        assert err.value.code == code, effective
    for bad in ({"mode": "LATER"}, {}, {"mode": "DATE", "date": "2026-02-30"}, {"mode": "DATE", "date": "2026-09-01\n"},
                {"mode": "DATETIME", "at": 5}, {"mode": "DATETIME", "at": "nonsense"}):
        with pytest.raises(EffectiveTimeError) as err:
            resolve_effective(bad, NOW)
        assert err.value.code == "EFFECTIVE_MODE_INVALID", bad
    # The exact instant `now` and the lower bound itself are accepted.
    assert resolve_effective({"mode": "DATETIME", "at": NOW.isoformat()}, NOW).instant == NOW
    assert resolve_effective({"mode": "DATETIME", "at": "1990-01-01T00:00:00+00:00"}, NOW)


def test_effective_same_instant_from_two_spellings() -> None:
    a = resolve_effective({"mode": "DATE", "date": "2026-09-01"}, NOW)
    b = resolve_effective({"mode": "DATETIME", "at": "2026-09-01T00:00:00+07:00"}, NOW)
    assert a.instant == b.instant and a.precision != b.precision


# ---------------------------------------------------------------------------
# R-06 — timeline derivation (§5.3, §5.4)
# ---------------------------------------------------------------------------


def test_transfer_then_insertion_recorded_vs_derived_source() -> None:
    first = assignment("R1", "BR-TEST-B", T3, src=("BR-TEST-A", "BASELINE"), baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    inserted = assignment("R2", "BR-TEST-C", T1, op="INSERTION", note="ตกหล่น", recorded_at="2026-09-28T00:00:00+00:00")
    t = _derive([first, inserted])
    assert t.status == "VALID" and t.issue_counts == {}
    assert [e.event_id for e in t.events] == ["R2", "R1"]
    later = t.events[1]
    assert later.derived_from_branch_id == "BR-TEST-C"  # derived, after the insertion
    assert later.head_entry_from_branch_id == "BR-TEST-A"  # recorded at entry time, never rewritten
    assert later.original_entry_from_source == "BASELINE"
    assert later.notes == ("RECORDED_SOURCE_DIFFERS",)
    assert t.events[0].derived_end_at == T3 and later.derived_end_at is None
    assert (t.current_branch_id, t.current_source, t.consistency) == ("BR-TEST-B", "EVENT", "CONSISTENT")
    assert (t.baseline_branch_id, t.baseline_source) == ("BR-TEST-A", "IMPORTED_MASTER")


def test_correction_moves_event_and_head_fields_follow() -> None:
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    b = assignment("R2", "BR-TEST-C", T2, src=("BR-TEST-B", "EVENT"))
    fix = correction("R3", "R1", "R1", "2", "BR-TEST-D", T3, src=("BR-TEST-C", "EVENT"))
    t = _derive([a, b, fix], master="BR-TEST-D")
    assert [(e.event_id, e.head_record_id, e.revision_no) for e in t.events] == [("R2", "R2", "1"), ("R1", "R3", "2")]
    assert t.current_branch_id == "BR-TEST-D" and t.consistency == "CONSISTENT"
    assert t.events[1].original_entry_from_branch_id == "BR-TEST-A"
    assert t.events[1].head_entry_from_branch_id == "BR-TEST-C"


def test_cancelling_every_event_restores_baseline_not_master() -> None:
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    cancel = cancellation("R2", "R1", "R1", "2")
    t = _derive([a, cancel], master="BR-TEST-B")  # master still holds the projected value
    assert (t.current_branch_id, t.current_source) == ("BR-TEST-A", "BASELINE")
    assert t.consistency == "PROJECTION_MISMATCH"
    assert [(e.in_force, e.notes, e.to_branch_id) for e in t.events] == [(False, ("CANCELLED",), "BR-TEST-B")]


def test_cancelling_all_with_none_baseline_is_unknown() -> None:
    a = assignment("R1", "BR-TEST-B", T1, src=(None, "NONE"), baseline=(None, "NONE"))
    t = _derive([a, cancellation("R2", "R1", "R1", "2")], master=None)
    assert (t.current_branch_id, t.current_source, t.consistency) == (None, "NONE", "CONSISTENT")
    assert t.has_baseline and t.baseline_branch_id is None


def test_cancelled_corrected_event_shows_last_value() -> None:
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    fix = correction("R2", "R1", "R1", "2", "BR-TEST-C", T2)
    t = _derive([a, fix, cancellation("R3", "R1", "R2", "3")], master="BR-TEST-A")
    (event,) = t.events
    assert (event.in_force, event.to_branch_id, event.effective_at, event.revision_no) == (False, "BR-TEST-C", T2, "3")


def test_redundant_note_and_no_records_states() -> None:
    a = assignment("R1", "BR-TEST-A", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    assert _derive([a], master="BR-TEST-A").events[0].notes == ("REDUNDANT",)
    empty = _derive([], master="BR-TEST-Q")
    assert (empty.current_branch_id, empty.current_source, empty.consistency) == ("BR-TEST-Q", "IMPORTED_MASTER", "NO_HISTORY")
    assert empty.revision == history_revision([]) and not empty.has_baseline
    blank = _derive([], master=None)
    assert (blank.current_branch_id, blank.current_source) == (None, "NONE")


def test_same_instant_is_ambiguous_not_invalid() -> None:
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    b = assignment("R2", "BR-TEST-C", "2026-08-01T07:00:00+07:00", src=("BR-TEST-B", "EVENT"))  # same instant
    c = assignment("R3", "BR-TEST-D", T3, src=("BR-TEST-C", "EVENT"))
    t = _derive([a, b, c], master="BR-TEST-D")
    assert t.status == "AMBIGUOUS_ORDER" and t.issue_counts == {}
    assert (t.current_branch_id, t.current_source, t.consistency) == (None, "UNDETERMINED", "UNDETERMINED")
    notes = {e.event_id: e.notes for e in t.events}
    assert notes == {"R1": ("SAME_INSTANT",), "R2": ("SAME_INSTANT",), "R3": ()}
    assert all(e.derived_from_branch_id is None and e.derived_end_at is None for e in t.events)
    # The repair: correcting one tied event resolves the order.
    fixed = _derive([a, b, c, correction("R4", "R2", "R2", "2", "BR-TEST-C", T2, src=("BR-TEST-B", "EVENT"))], master="BR-TEST-D")
    assert fixed.status == "VALID" and fixed.current_branch_id == "BR-TEST-D"


def test_master_column_absent_makes_consistency_undetermined() -> None:
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    t = _derive([a], master=None, available=False)
    assert t.current_branch_id == "BR-TEST-B" and t.consistency == "UNDETERMINED"


def test_revision_changes_for_an_older_event_edit_with_same_current() -> None:
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    b = assignment("R2", "BR-TEST-C", T3, src=("BR-TEST-B", "EVENT"))
    before = _derive([a, b], master="BR-TEST-C")
    after = _derive([a, b, correction("R3", "R1", "R1", "2", "BR-TEST-B", T2)], master="BR-TEST-C")
    assert (before.current_branch_id, before.events[-1].event_id) == (after.current_branch_id, after.events[-1].event_id)
    assert before.revision != after.revision
    # Hand edit of any column changes it; physical order does not.
    edited = dict(b, note_th="แก้ด้วยมือ")
    assert history_revision([a, edited]) != before.revision
    assert history_revision([b, a]) == before.revision
    assert before.revision.startswith("BHR1-") and len(before.revision) == 25


# ---------------------------------------------------------------------------
# R-06 — every §5.2 issue; every record kind; totality
# ---------------------------------------------------------------------------


def _issues(records, **kw) -> dict[str, int]:
    t = _derive(records, **kw)
    assert t.status == "INVALID"
    return t.issue_counts


def _first() -> dict[str, str]:
    return assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"))


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r.update(record_kind="MOVE"), "RECORD_KIND_INVALID"),
        (lambda r: r.update(record_kind=""), "LEGACY_ROW_UNCLASSIFIED"),
        (lambda r: r.update(event_id="R9"), "ASSIGNMENT_IDENTITY_INVALID"),
        (lambda r: r.update(revision_no="2"), "REVISION_INVALID"),
        (lambda r: r.update(supersedes_record_id="R0"), "FIELD_MUST_BE_BLANK:supersedes_record_id"),
        (lambda r: r.update(branch_id=""), "FIELD_REQUIRED:branch_id"),
        (lambda r: r.update(effective_precision="MONTH"), "EFFECTIVE_PRECISION_INVALID"),
        (lambda r: r.update(effective_source="GUESS"), "EFFECTIVE_SOURCE_INVALID"),
        (lambda r: r.update(entry_operation="CORRECTION"), "ENTRY_OPERATION_INVALID"),
        (lambda r: r.update(recorded_from_source="MASTER"), "RECORDED_FROM_SOURCE_INVALID"),
        (lambda r: r.update(recorded_from_source="NONE"), "RECORDED_FROM_BRANCH_INCONSISTENT"),
        (lambda r: r.update(baseline_source="GUESS"), "BASELINE_SOURCE_INVALID"),
        (lambda r: r.update(baseline_branch_id=""), "BASELINE_BRANCH_INCONSISTENT"),
        (lambda r: r.update(entry_operation="INSERTION", note_th=""), "REASON_REQUIRED"),
        (lambda r: r.update(recorded_at="2026-09-01T03:00:00"), "RECORDED_AT_INVALID"),
        (lambda r: r.update(start_at="01/08/2026"), "EFFECTIVE_AT_INVALID"),
        (lambda r: r.update(start_at="2026-08-01T00:00:00"), "EFFECTIVE_AT_INVALID"),
        (lambda r: r.update(request_fingerprint="A" * 64), "FINGERPRINT_INVALID"),
        (lambda r: r.update(request_fingerprint=_fp("x") + "\n"), "FINGERPRINT_INVALID"),
        (lambda r: r.update(is_test_data="yes"), "TEST_FLAG_INVALID"),
        (lambda r: r.update(asset_type="TRUCK"), "ASSET_TYPE_INVALID"),
        (lambda r: r.update(end_at=T2), "FIELD_MUST_BE_BLANK:end_at"),
        (lambda r: r.update(related_request_id="req-x"), "FIELD_MUST_BE_BLANK:related_request_id"),
        (lambda r: r.update(recorded_by=" "), "FIELD_REQUIRED:recorded_by"),
    ],
)
def test_each_assignment_row_rule(mutate, code) -> None:
    row = _first()
    mutate(row)
    assert code in _issues([row])


def test_baseline_missing_and_conflict_and_duplicates() -> None:
    no_base = assignment("R1", "BR-TEST-B", T1)
    assert "BASELINE_MISSING" in _issues([no_base])
    other = assignment("R2", "BR-TEST-C", T2, baseline=("BR-TEST-Z", "IMPORTED_MASTER"))
    assert "BASELINE_CONFLICT" in _issues([_first(), other])
    first = _first()
    dup = dict(assignment("R2", "BR-TEST-C", T2), assignment_id="R1", event_id="R1")
    assert "RECORD_ID_DUPLICATE" in _issues([first, dup])
    again = dict(assignment("R2", "BR-TEST-C", T2), request_id=first["request_id"])
    assert "REQUEST_ID_DUPLICATE" in _issues([first, again])


def test_baseline_only_on_the_first_recorded_record() -> None:
    first = _first()
    # A later ASSIGNMENT repeating the SAME baseline is still a matrix violation.
    same = assignment("R2", "BR-TEST-C", T2, src=("BR-TEST-B", "EVENT"), baseline=("BR-TEST-A", "IMPORTED_MASTER"))
    assert _issues([first, same]) == {
        "FIELD_MUST_BE_BLANK:baseline_branch_id": 1,
        "FIELD_MUST_BE_BLANK:baseline_source": 1,
    }
    none_again = assignment("R2", "BR-TEST-C", T2, src=("BR-TEST-B", "EVENT"), baseline=(None, "NONE"))
    # A different baseline on a later row is also a conflict (existing rule, unchanged).
    assert _issues([first, none_again]) == {"BASELINE_CONFLICT": 1, "FIELD_MUST_BE_BLANK:baseline_source": 1}
    # Later ASSIGNMENT with blank baseline fields: valid; the first record's baseline is kept.
    later = assignment("R2", "BR-TEST-C", T2, src=("BR-TEST-B", "EVENT"))
    t = _derive([first, later], master="BR-TEST-C")
    assert t.status == "VALID" and (t.baseline_branch_id, t.baseline_source) == ("BR-TEST-A", "IMPORTED_MASTER")
    # The first record is judged in RECORDED order, not physical order.
    early = dict(later, recorded_at="2026-01-01T00:00:00+00:00")
    assert "FIELD_MUST_BE_BLANK:baseline_branch_id" in _issues([first, early])
    # Corrections, cancellations and reconciliations behave as before (row matrix).
    fix = correction("R3", "R1", "R1", "2", "BR-TEST-D", T3)
    assert _derive([first, later, fix], master="BR-TEST-C").status == "VALID"
    assert _derive([first, cancellation("R3", "R1", "R1", "2")], master="BR-TEST-A").status == "VALID"
    rec = reconciliation("R3", "BR-TEST-B", "BR-TEST-Q", related=first["request_id"])
    assert _derive([first, rec], master="BR-TEST-B").status == "VALID"
    # A correction carrying baseline fields is caught by the unchanged row matrix (counted once there).
    same_on_fix = dict(fix, baseline_branch_id="BR-TEST-A", baseline_source="IMPORTED_MASTER")
    assert _issues([first, same_on_fix]) == {
        "FIELD_MUST_BE_BLANK:baseline_branch_id": 1,
        "FIELD_MUST_BE_BLANK:baseline_source": 1,
    }


def test_dangling_references_fork_gap_and_cancellation_not_last() -> None:
    a = _first()
    assert "DANGLING_REFERENCE" in _issues([a, correction("R2", "R-UNKNOWN", "R1", "2", "BR-TEST-C", T2)])
    assert "DANGLING_REFERENCE" in _issues([a, correction("R2", "R1", "R-UNKNOWN", "2", "BR-TEST-C", T2)])
    b = assignment("R2", "BR-TEST-C", T2)
    c = correction("R3", "R2", "R1", "2", "BR-TEST-D", T3)  # supersedes another event's record
    assert "REVISION_FORK_OR_GAP" in _issues([a, b, c])
    fork = [a, correction("R2", "R1", "R1", "2", "BR-TEST-C", T2), correction("R3", "R1", "R1", "2", "BR-TEST-D", T3)]
    assert "REVISION_FORK_OR_GAP" in _issues(fork)
    gap = [a, correction("R2", "R1", "R1", "3", "BR-TEST-C", T2)]
    assert "REVISION_FORK_OR_GAP" in _issues(gap)
    not_last = [a, cancellation("R2", "R1", "R1", "2"), correction("R3", "R1", "R2", "3", "BR-TEST-C", T2)]
    assert "CANCELLATION_NOT_LAST" in _issues(not_last)
    # A correction whose event_id names a CORRECTION record (not an ASSIGNMENT).
    fix = correction("R2", "R1", "R1", "2", "BR-TEST-C", T2)
    assert "DANGLING_REFERENCE" in _issues([a, fix, correction("R3", "R2", "R2", "2", "BR-TEST-D", T3)])


@pytest.mark.parametrize("revision", ["", "x", "0", "1", "²", "๒", "2.0", " 2", "2\n", "-2"])
def test_malformed_revision_numbers_are_issues_not_exceptions(revision: str) -> None:
    a = _first()
    for row in (correction("R2", "R1", "R1", revision, "BR-TEST-C", T2), cancellation("R2", "R1", "R1", revision)):
        assert "REVISION_INVALID" in _issues([a, row])


def test_cancellation_and_reconciliation_matrices() -> None:
    a = _first()
    bad_cancel = dict(cancellation("R2", "R1", "R1", "2"), branch_id="BR-TEST-C", start_at=T2, recorded_from_source="EVENT")
    issues = _issues([a, bad_cancel])
    assert {"FIELD_MUST_BE_BLANK:branch_id", "FIELD_MUST_BE_BLANK:start_at", "FIELD_MUST_BE_BLANK:recorded_from_source"} <= set(issues)
    assert "FIELD_REQUIRED:note_th" in _issues([a, dict(cancellation("R2", "R1", "R1", "2"), note_th="")])
    rec = reconciliation("R2", "BR-TEST-B", "BR-TEST-Q", related=a["request_id"])
    t = _derive([a, rec], master="BR-TEST-B")
    assert t.status == "VALID" and [e.event_id for e in t.events] == ["R1"]
    assert [r["record_kind"] for r in t.records] == ["ASSIGNMENT", "PROJECTION_RECONCILIATION"]
    assert "RELATED_REQUEST_DANGLING" in _issues([a, reconciliation("R2", "BR-TEST-B", "", related="req-none")])
    for field in ("event_id", "revision_no", "start_at", "baseline_source"):
        assert f"FIELD_MUST_BE_BLANK:{field}" in _issues([a, reconciliation("R2", "", "", **{field: "1"})])
    assert "FIELD_REQUIRED:note_th" in _issues([a, dict(reconciliation("R2", "", ""), note_th="")])
    assert "BASELINE_MISSING" in _issues([dict(reconciliation("R0", "", ""), recorded_at="2026-01-01T00:00:00+00:00"), a])


def test_validation_is_total_on_random_malformed_cells() -> None:
    rng = random.Random(7)
    junk = ["", " ", "x", "²", "๑", "-1", "1e3", "2026-13-40", "TRUE", "None", "\n", "0" * 70, "ASSIGNMENT",
            "CORRECTION", "CANCELLATION", "PROJECTION_RECONCILIATION", "R1", "R2", T1, "2026-08-01"]
    base = [_first(), correction("R2", "R1", "R1", "2", "BR-TEST-C", T2), cancellation("R3", "R1", "R2", "3"),
            reconciliation("R4", "", "")]
    for _ in range(600):
        rows = [dict(r) for r in base]
        for row in rows:
            for col in rng.sample(ASSET_BRANCH_HISTORY_COLUMNS, 4):
                row[col] = rng.choice(junk)
        t = _derive(rows)  # must never raise
        assert t.status in ("VALID", "AMBIGUOUS_ORDER", "INVALID")


def test_vehicle_history_rows_selects_exact_asset_and_reports_bad_type() -> None:
    a = _first()
    other = dict(_first(), asset_id="SYN-V002")
    padded = dict(_first(), asset_id=f" {V}")
    equipment = dict(_first(), asset_type="EQUIPMENT")
    typo = dict(_first(), asset_type="vehicle")
    assert vehicle_history_rows([a, other, padded, equipment, typo], V) == [a, typo]
    assert "ASSET_TYPE_INVALID" in _issues([a, typo])  # a selected malformed row is reported, not hidden


# ---------------------------------------------------------------------------
# R-08 — contexts (§8.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["TRUE", ""])
def test_real_context_fails_closed_on_test_or_blank_rows(flag: str) -> None:
    row = dict(_first(), is_test_data=flag)
    assert _derive([row], context="TEST").status == "VALID"
    assert _issues([row], context="REAL") == {"CUTOVER_INCOMPLETE": 1}
    reg = _reg(is_test_data=flag)
    assert validate_registration_rows([reg], "TEST") == {}
    assert validate_registration_rows([reg], "REAL") == {"CUTOVER_INCOMPLETE": 1}


def test_real_context_accepts_false_rows() -> None:
    assert _derive([dict(_first(), is_test_data="FALSE")], context="REAL").status == "VALID"
    assert validate_registration_rows([_reg(is_test_data="FALSE")], "REAL") == {}


# ---------------------------------------------------------------------------
# R-07 — registration history (§4.5, §7.7)
# ---------------------------------------------------------------------------

_reg_seq = itertools.count(1)
_REC0 = datetime(2026, 9, 1, 3, 0, 0, tzinfo=timezone.utc)  # builders record in creation order


def _reg(**cells: str) -> dict[str, str]:
    n = next(_reg_seq)
    row = dict.fromkeys(REGISTRATION_HISTORY_COLUMNS, "")
    row.update(change_id=f"VRH-{n:032x}", vehicle_id=V, change_kind="CHANGE", new_registration_no="กข 1234",
               new_registration_province_code="TH-21", recorded_at=(_REC0 + timedelta(minutes=n, microseconds=123456)).isoformat(),
               recorded_by="SYN-USER", request_id=f"rreq-{n}", request_fingerprint=_fp(f"rreq-{n}"), is_test_data="TRUE")
    row.update(cells)
    return row


@pytest.mark.parametrize(
    ("cells", "code"),
    [
        ({"change_kind": "EDIT"}, "CHANGE_KIND_INVALID"),
        ({"change_id": "VRH-xyz"}, "CHANGE_ID_INVALID"),
        ({"change_id": "VRH-" + "a" * 32 + "\n"}, "CHANGE_ID_INVALID"),
        ({"recorded_at": "2026-09-01T03:00:00"}, "RECORDED_AT_INVALID"),
        ({"recorded_by": ""}, "FIELD_REQUIRED:recorded_by"),
        ({"request_id": " "}, "FIELD_REQUIRED:request_id"),
        ({"request_fingerprint": "short"}, "FINGERPRINT_INVALID"),
        ({"is_test_data": "true"}, "TEST_FLAG_INVALID"),
        ({"new_registration_no": "", "new_registration_province_code": "TH-21"}, "NEW_PAIR_INVALID"),
        ({"new_registration_no": "x" * 51}, "NEW_PAIR_INVALID"),
        ({"change_kind": "RECONCILIATION_APPLY_RECORDED"}, "REASON_REQUIRED"),
        ({"related_request_id": "rreq-1"}, "RELATED_REQUEST_DANGLING"),
        ({"accepted_exceptions": "EXISTING_DUPLICATE_PAIR"}, "ACCEPTED_EXCEPTIONS_INVALID"),
    ],
)
def test_each_registration_row_rule(cells, code) -> None:
    assert code in validate_registration_rows([_reg(**cells)], "TEST")


def test_registration_cross_row_rules() -> None:
    first = _reg()
    accept = _reg(change_kind="RECONCILIATION_ACCEPT_MASTER", note_th="ยอมรับค่าหลัก", related_request_id=first["request_id"],
                  accepted_exceptions="REFERENCE_UNKNOWN_ACCEPTED;EXISTING_DUPLICATE_PAIR")
    assert validate_registration_rows([first, accept], "TEST") == {}
    bad_code = dict(accept, accepted_exceptions="REFERENCE_UNKNOWN_ACCEPTED;MADE_UP")
    assert "ACCEPTED_EXCEPTIONS_INVALID" in validate_registration_rows([first, bad_code], "TEST")
    later_ref = _reg(change_kind="RECONCILIATION_APPLY_RECORDED", note_th="x", related_request_id="rreq-future")
    assert "RELATED_REQUEST_DANGLING" in validate_registration_rows([later_ref, _reg(request_id="rreq-future")], "TEST")
    assert "REQUEST_ID_DUPLICATE" in validate_registration_rows([first, _reg(request_id=first["request_id"])], "TEST")
    assert "CHANGE_ID_DUPLICATE" in validate_registration_rows([first, _reg(change_id=first["change_id"])], "TEST")
    legacy_digits = _reg(change_id="VRH-17")
    assert validate_registration_rows([legacy_digits], "TEST") == {}
    # The old pair is a record of the imported master value: not re-validated.
    assert validate_registration_rows([_reg(old_registration_no=" - ", old_registration_province_code="TH-??")], "TEST") == {}


def test_registration_consistency_states_and_revision() -> None:
    a = _reg(new_registration_no="0012", new_registration_province_code="TH-21", recorded_at="2026-09-01T00:00:00+00:00")
    b = _reg(new_registration_no="กข 1234", new_registration_province_code="TH-10", recorded_at="2026-09-02T00:00:00+00:00")
    assert registration_consistency([], ("x", None)) == "NO_HISTORY"
    assert registration_consistency([b, a], ("กข 1234", "TH-10")) == "CONSISTENT"  # recorded order, not physical
    assert registration_consistency([a, b], ("0012", "TH-21")) == "MISMATCH"
    assert registration_consistency([a, b], ("กข-1234", "TH-10")) == "MISMATCH"  # exact text, not RK1
    assert registration_consistency([a, b], None) == "UNDETERMINED"
    cleared = _reg(new_registration_no="", new_registration_province_code="", recorded_at="2026-09-03T00:00:00+00:00")
    assert registration_consistency([a, cleared], (None, None)) == "CONSISTENT"
    rev = registration_history_revision([a, b])
    assert rev.startswith("RHR1-") and len(rev) == 25
    assert rev == registration_history_revision([b, a])  # recorded order
    assert rev != registration_history_revision([a, dict(b, note_th="edited")])
    assert registration_history_revision([]) == registration_history_revision([])


def test_registration_validation_is_total() -> None:
    rng = random.Random(11)
    junk = ["", " ", "²", "VRH-1", "CHANGE", "x" * 60, "2026-09-01", "2026-09-01T00:00:00+00:00", "TRUE", "a;b", "\n"]
    for _ in range(600):
        rows = [_reg(), _reg()]
        for row in rows:
            for col in rng.sample(REGISTRATION_HISTORY_COLUMNS, 5):
                row[col] = rng.choice(junk)
        validate_registration_rows(rows, rng.choice(["TEST", "REAL"]))
        registration_consistency(rows, ("x", None))
        registration_history_revision(rows)


# ---------------------------------------------------------------------------
# §7.1 registry field states; §7.2 reference parsing
# ---------------------------------------------------------------------------


def test_registry_states_and_exact_text() -> None:
    record = {"registration_no": "0012", "registration_province_code": "  ", "responsible_branch_id": " BR-TEST-A "}
    reg = registry_from_record(record, REGISTRY_COLUMNS)
    assert (reg.registration_no.state, reg.registration_no.value) == ("RECORDED", "0012")
    assert (reg.registration_province.state, reg.registration_province.value) == ("NOT_RECORDED", None)
    assert reg.responsible_branch.value == " BR-TEST-A "  # stored text exactly, never trimmed
    assert reg.registration_pair == ("0012", None)
    partial = registry_from_record(record, {"responsible_branch_id"})
    assert partial.registration_no.state == "NOT_IN_SCHEMA" and partial.registration_pair is None
    assert partial.responsible_branch.state == "RECORDED"
    numeric = registry_from_record({"registration_no": 12}, REGISTRY_COLUMNS)  # a numericised cell is still text
    assert numeric.registration_no.value == "12"


def test_reference_parsing_issues_and_order() -> None:
    rows = [
        {"branch_id": "BR-TEST-B", "branch_name": "บี", "is_active": "TRUE"},
        {"branch_id": "BR-TEST-A", "branch_name": "เอ", "is_active": "FALSE"},
    ]
    entries, issues = parse_reference_rows(rows, code_column="branch_id", name_column="branch_name")
    assert issues == {} and [(e.code, e.is_active) for e in entries] == [("BR-TEST-A", False), ("BR-TEST-B", True)]
    no_flag, issues = parse_reference_rows([{"branch_id": "B", "branch_name": "n"}], code_column="branch_id",
                                           name_column="branch_name", active_column_present=False)
    assert issues == {} and no_flag[0].is_active
    bad = rows + [
        {"branch_id": "BR-TEST-A", "branch_name": "ซ้ำ", "is_active": "TRUE"},
        {"branch_id": " ", "branch_name": "", "is_active": "true"},
    ]
    _, issues = parse_reference_rows(bad, code_column="branch_id", name_column="branch_name")
    assert issues == {"DUPLICATE_CODE": 2, "BLANK_CODE": 1, "BLANK_NAME": 1, "INVALID_ACTIVE_FLAG": 1}


def test_recorded_at_ties_keep_physical_order() -> None:
    same = "2026-09-01T00:00:00+00:00"
    a = assignment("R1", "BR-TEST-B", T1, baseline=("BR-TEST-A", "IMPORTED_MASTER"), recorded_at=same)
    b = assignment("R2", "BR-TEST-C", T2, src=("BR-TEST-B", "EVENT"), recorded_at=same)
    t = _derive([a, b], master="BR-TEST-C")
    assert [r["assignment_id"] for r in t.records] == ["R1", "R2"]
    # The baseline is judged on the first record in RECORDED order, not physical order.
    shifted = (datetime.fromisoformat(same) - timedelta(days=1)).isoformat()
    assert "BASELINE_MISSING" in _issues([a, dict(b, recorded_at=shifted)], master="BR-TEST-C")
