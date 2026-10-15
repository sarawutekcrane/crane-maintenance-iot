# R2-C1 — E2 Operational Driver Assignment Backend — Result

Status: **IMPLEMENTED AND TESTED ON LOCAL BRANCH `review/r2-c1-e2-backend` — UNCOMMITTED, AWAITING OWNER REVIEW.**
Not committed, pushed, merged or deployed. Mock/TEST only. R2 is not accepted.

## 1. Baseline

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `6cf76173e32ee373bad8a03e240b20b64d5d646e` |
| Tree | `8e84e5a96618663b3ef3bde5d8469b3fa3bbfc67` |
| Governance | `docs/project-governance/c1-amendment-a2-driver-responsibility.md` (A2), `c1-amendment-a1-v2-only.md` (A1) |
| REV5 acceptance matrix | `R2_Temporary_Driver_Contract_Amendment_REV5_OWNER_REVIEW_DRAFT.txt` (owner-supplied, not in the repository), SHA-256 `f15415d63936539546723c75dbb421e64edce7e8ba6e2d90cd9de7177a03dc35` |
| Baseline backend suite (before any edit) | **4704 passed, 0 failed** (Python 3.13, `python -m pytest -q`) |

## 2. Scope delivered

A separate, append-only, revisioned E2 authority `crane_operational_driver_assignment_history` (mock store only).
It records ASSIGNED drivers, never verified actual driving. It never reads Phase 6 `vehicle_driver` and never
writes R2f-f `crane_driver_responsibility_history`.

- `backend/app/domain/operational_driver_timeline.py` — pure: columns, row validation, Bangkok units
  (half-open), H2 / E2-H3 structure and clips, early end, VOID, UNKNOWN, CONFLICTED, conflicts, adjacency.
- `backend/app/domain/operational_driver_assignment.py` — service: CREATE, REVISE (correction / extension /
  split / `void_elapsed`), SUBSTITUTE, CANCEL, EARLY_END; replay, stale, eligibility (O3), warnings.
- `backend/app/api/v1/operational_driver_assignment_schemas.py`, `..._routes.py` — the four approved routes.
- Additive repository methods (`base.py`, mock, Google Sheets refusal) and one router registration.

### Routes (four, no DELETE)

| Route | Capability |
|---|---|
| `GET /vehicles/{vehicle_id}/operational-driver-assignments?from&to&mode` | `can_view` |
| `GET /vehicles/{vehicle_id}/operational-driver-assignment-history` | `can_view` |
| `GET /drivers/{driver_id}/operational-driver-assignments?from&to&mode` | `can_view` |
| `POST /vehicles/{vehicle_id}/operational-driver-assignment-operations` | `can_assign_crane_driver` |

### Record kinds

ASSIGNMENT (revision 1), REVISION (full new state), HANDOVER (own revision chain naming the exact predecessor /
successor revisions), CANCELLATION (terminal). One request = one `operation_id` = one atomic append.

## 3. Decision traceability

| Decision | Implementation | Evidence |
|---|---|---|
| DQ-1 / O1 | REAL writes refused before any repository call; Sheets E2 methods raise before any request; no E2 Sheets schema; not in `_CORE_SCHEMAS`; readiness / health untouched | `test_e2_real_*`, `test_e2_sheets_*` (transport counter = 0, with positive control) |
| DQ-2 | R2f-f files unchanged; eligibility reimplemented; only public read helpers imported | `git diff` (no R2f-f path), `test_b01`, `test_e2_r2ff_*` |
| DQ-3 | CANCEL only before derived start; EARLY_END only after start (elapsed stays ASSIGNED); post-handover REVISE revalidates both parties, revisions, both axes and the handover; boundary moves after effect refused | `test_b21`–`test_b23`, `test_e2_life_*`, `test_e2_ho_*` |
| DQ-4 | Exactly four routes; five operations; strict bodies | `test_e2_legacy_phase6_driver_routes_are_still_present`, `test_e2_auth_*` |
| DQ-5 | A2-clause tests plus REV5 B01–B29 named tests; B30 deferred | §4 |
| DQ-6 | `void_elapsed: true` = a REVISION with `voided=TRUE`; originals intact; UNKNOWN only for elapsed time a handover had moved | `test_b23`, `test_e2_life_void_*`, `test_e2_ho_e2_h3_void_*` |
| DQ-7 | ≤ 366 inclusive days on every written state (incl. split / substitute); start ≤ 366 days ahead; old history correctable | `test_e2_dq7_*`, `test_e2t_limit_*` |
| G-1 | `from` / `to` / `mode` on both schedule GETs; no fifth route | `test_b29` |
| G-2 | `assigned_driver_id`; no proof-of-driving field | `test_b29` |
| G-3 | Stable codes only | route `responses` |
| O3 | Elapsed-only states may name an INACTIVE driver; never current / future; reference / scope / conflicts still checked | `test_e2_o3_*`, `test_b24` |
| O4 | FULL_DAY substitution by whole calendar day; partial units refused | `test_b19_full_day_*`, `test_b20` |
| P7 | One-process version guard: one winner, nothing partial; no production claim | `test_b28` |

## 4. REV5 B01–B30 evidence matrix

PASS = executed in R2-C1 and supported by a passing test. PARTIAL = the backend part passes; the rest is
frontend (R2-C2). GATED = depends on R11. DEFERRED = R2-C3.

| B | Status | Evidence |
|---|---|---|
| B01 | PASS | `test_b01_permanent_change_on_v1_leaves_v2_and_e2_unchanged` |
| B02 | PASS (backend) / PARTIAL (Thai wording R2-C2) | `test_b02_no_permanent_driver_warns_but_saves` |
| B03 | PASS | `test_b03_permanent_driver_needs_no_daily_e2_and_is_not_claimed_as_driving` |
| B04 | PASS | `test_b04_permanent_driver_day_and_other_night_same_dates` |
| B05 | PASS | `test_b05_two_non_permanent_drivers_day_and_night` |
| B06 | PARTIAL | `test_b06_one_shift_only_the_other_is_never_autofilled` (no auto-fill); the "ยังไม่ได้ระบุผู้ได้รับมอบหมาย" label is R2-C2 |
| B07 | PASS | `test_b07_full_to_full_next_day_at_midnight` |
| B08 | PASS | `test_b08_full_to_full_overlapping_last_day_rejects` |
| B09 | PASS | `test_b09_full_to_day_shift_driving_only_from_applied_start` |
| B10 | PASS | `test_b10_full_to_day_shift_on_last_day_rejects` |
| B11 | PASS | `test_b11_h2_last_day_night_handover_keeps_original_dates` |
| B12 | PASS | `test_b12_mid_range_night_insertion_rejects_with_or_without_handover` |
| B13 | PASS | `test_b13_e2_h3_morning_handover_starts_full_day_at_night_end` |
| B14 | PASS | `test_b14_physical_overlap_rejects_despite_labels` |
| B15 | PASS | `test_b15_same_driver_adjacent_on_two_vehicles_warns_not_a_safety_approval` |
| B16 | PASS | `test_b16_simultaneous_same_driver_or_same_vehicle_rejects` |
| B17 | PASS | `test_b17_shift_time_change_splits_and_preserves_history` |
| B18 | PASS | `test_b18_any_conflicting_segment_rejects_the_whole_change` |
| B19 | PASS | `test_b19_whole_night_substitution_keeps_unaffected_days`, `test_b19_full_day_substitution_is_whole_calendar_days_only_o4` |
| B20 | PASS (out of scope enforced) | `test_b20_no_mid_shift_handover_in_any_operation` |
| B21 | PASS | `test_b21_future_cancellation_releases_and_keeps_audit` |
| B22 | PASS | `test_b22_cancel_before_handover_restores_predecessor_coverage` |
| B23 | PASS | `test_b23_after_handover_elapsed_time_is_never_given_back_and_is_unknown` |
| B24 | PASS | `test_b24_backdated_whole_shift_correction_with_reason` |
| B25 | PASS (backend) / PARTIAL (display R2-C2) | `test_b25_future_inactive_driver_is_retained_and_flagged` |
| B26 | PASS (backend) / PARTIAL (display R2-C2) | `test_b26_current_inactive_driver_is_retained_flagged_and_needs_action` |
| B27 | PASS (backend) / PARTIAL (Thai message R2-C2) | `test_b27_duplicate_and_replay` |
| **B28** | **GATED (R11)** | `test_b28_one_process_concurrency_one_winner_never_partial_gated_by_r11` proves ONE mock process only |
| B29 | PARTIAL | `test_b29_search_by_vehicle_driver_date_and_mode` (vehicle / driver / date range / mode; "verified actual: unavailable" display is R2-C2; fleet-wide date-only search is a recorded gap) |
| **B30** | **DEFERRED (R2-C3)** | not in scope; `test_e2_legacy_phase6_driver_routes_are_still_present` proves nothing was removed |

Full REV5 acceptance is NOT claimed: R2-C2, R2-C3, R2-C4 and R11 remain.

## 5. Test results

| Command (from `backend/`) | Result |
|---|---|
| `python -m pytest -q tests/test_operational_driver_timeline_batch_r2_c1.py` | 21 passed |
| `python -m pytest -q tests/test_operational_driver_assignment_batch_r2_c1.py` | 91 passed (after the F1–F4 fix) |
| `python -m pytest -q tests/test_operational_driver_assignment_sheets_batch_r2_c1.py` | 11 passed |
| `python -m pytest -q` (full backend, first implementation) | 4813 passed, 0 failed (= 4704 baseline + 109 new; 14m16s) |
| `python -m pytest -q` (full backend, after the F1–F4 fix) | **4827 passed, 0 failed** (= 4704 baseline + 123 E2; 14m41s) |

Dependencies were installed into the execution environment only (`requirements.txt` plus pytest,
pytest-asyncio, httpx); no repository dependency file changed.

## 5a. Owner contract-gap review F1–F4 (fix round)

| Item | Finding before the fix | Classification | Change | Evidence |
|---|---|---|---|---|
| F1 effective handover corrections | Every change to the instant of an already-effective handover was refused, and the clips applied to the boundary date only, so VOID + re-record could not represent a corrected time faithfully | **FIXED** | A reasoned REVISE / split may correct the applied time of an effective H2 / E2-H3; the HANDOVER is revised with the new party revisions and instant; any elapsed time the giving side would regain becomes the handover's UNKNOWN span, which is withheld from the giver; clips are absolute; a handover with a VOIDED party is frozen at its recorded instant; both axes are re-checked; a change that breaks the boundary's dates is still refused (`E2_HANDOVER_INVALIDATED`) | `test_f1_*` (6), `test_e2_ho_*`, `test_b23` |
| F2 substitution on handover boundaries | Blanket refusal of a boundary unit | **FIXED** | A boundary unit (the whole unit the assignment holds after the handover) can be substituted; the substitute takes the assignment's place in the handover (HANDOVER revision); units cut by an early end stay non-substitutable; no partial unit is expressible | `test_f2_*` (5) |
| F3 partial historical correction | Only whole VOID, SUBSTITUTE or a full new state; no way to remove specific units, and an unchanged INACTIVE driver was re-gated on a removal-only revision | **FIXED** | REVISE `exclude_dates` removes specific erroneous units (originals kept); eligibility applies only to a changed driver or added coverage (A2-7.1) | `test_f3_*` (2) |
| F4 early end and UNKNOWN | Behaviour was right, but evidence was thin | **PASS AS IMPLEMENTED** (explicit tests added) | none | `test_f4_*` (2), `test_e2_life_early_end_*` (3) |

## 6. Known limitations and gated items

- **R11:** production atomic acceptance and REAL enablement. The mock guard (row count compared with the read,
  then the append with no `await` in between) is a single-process guarantee only. B28 stays GATED.
- **Sheets:** E2 answers 501 `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` in google_sheets mode, TEST included.
- **Effective handover:** its applied TIME can be corrected (F1). A change that breaks its DATES (a different
  boundary date) is refused (`E2_HANDOVER_INVALIDATED`); the path is VOID of the wrong assignment plus a
  re-recorded one, after which the handover is frozen at its recorded instant (the giver never regains elapsed
  time; only uncovered time shows UNKNOWN).
- **Frozen handover:** once a party is VOIDED, the boundary stays at its recorded instant, so a later extension of
  the other party past that instant has no effect; record the extra time as a separate, explicit assignment.
- **UNKNOWN envelope:** the stored span is one contiguous envelope per handover, clipped at the time of the
  correction; time after the correction instant is not marked UNKNOWN.
- **VOID** voids the whole erroneous assignment; a partly erroneous one is corrected with REVISE `exclude_dates`,
  SUBSTITUTE or a corrected state (F3).
- **Fleet-wide date-only search** is not provided (G-1 gap); per-vehicle and per-driver range search are.
- Warnings use the driver's `driver_master.active_status`; a linked Personnel's status gates writes only.
- REV5 is an owner-review draft not stored in the repository; it is cited here by hash.

## 7. Next

Owner review of this diff. Commit / push to `review/r2-c1-e2-backend` needs separate authorization; merge into
integration, R2-C2, R2-C3 and R2-C4 each need their own.
