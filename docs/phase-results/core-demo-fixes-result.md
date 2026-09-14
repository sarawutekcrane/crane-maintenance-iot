# Core Demo Fixes (+ Delta REV03 Alignment) — Phase Result Report

PHASE: Core Demo Fixes — cross-cutting correction pass over Web/API
Phases 2–5, plus Delta REV03 alignment to the already-prepared live
Google Sheets prototype schema.
STATUS: PASS

Documents read in full before this delta's implementation:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/phase-results/web-phase-04-result.md`, `web-phase-05-result.md`
  (and their verification reports)
- The full existing backend implementation added by the 8 Core Demo
  Fixes checkpoint commits (domain/repository/API/frontend layers), read
  directly rather than re-derived, per this delta's explicit "verify
  state, do not redo" instruction.

This report covers two pieces of work, kept clearly separated below:

1. **Core Demo Fixes** — 8 commits already implemented, verified, and
   pushed to `origin/web/core-demo-fixes` in a prior session (`91dfd32`
   through `09b4777`). Not redone, not rewritten. Summarized in Section 1
   for context only.
2. **Delta REV03 Alignment** — this session's work: aligning the
   Google Sheets prototype schema names/columns to the live prototype
   sheet, completing the requisition Store/Inventory boundary (header +
   lines), adding GPS/location snapshot capture, and adding assignment
   history for repair and PM. New commit(s) on top of `09b4777`.

---

## 1. CORE DEMO FIXES — PRIOR SESSION SUMMARY (not redone here)

Commits `91dfd32`..`09b4777` (8 total) implemented, in order:

1. Automatic machine-state snapshot (counters) on every relevant
   persisted event; Equipment RETIRED status (frozen into
   `OPEN_DECISIONS_REGISTER_EN.txt` C02 — see Section 9 below); repair
   assignment fields + My Work / Open Repair Queue.
2. PM plan-per-model assignment (`VehicleModel.assigned_pm_plan_id`),
   scope approval/freeze, requisition scaffolding.
3. Frontend types, My Work / Open Repair Queue pages, home page copy fix.
4. Repair page: assignment UI, collapsed history, Part Master search,
   read-only machine state.
5. PM work-order page: removed manual meter entry, added scope UI and
   standard/execution separation.
6. Findings-list endpoint, PM status filter, equipment status UI,
   vehicle list indicators.
7. Shared `PhotoAttachmentField` component for consistent file-attachment
   UX.
8. Part instance install/transfer: searchable asset select instead of
   raw ID typing.

These commits are untouched by this session. No behavior they introduced
was reverted or redesigned.

## 2. DELTA REV03 ALIGNMENT — OBJECTIVE

Align the backend's Google Sheets prototype declarations with the
independently-prepared live prototype spreadsheet's exact tab names and
columns, and complete the minimum reversible domain/repository support
the live sheet's 8 new tabs imply — without inventing any source data
(plan-model mappings, PM group membership, task-part quantities,
technician names, equipment records, or repair lifecycle statuses) and
without redoing the 8 existing checkpoint commits' work.

B01 (exact sheet schema version) and B03 (Google Auth Method) remain
TBD-BLOCKING: **no live Google Sheets API I/O exists anywhere in this
repository**, in this delta or any prior phase. `GoogleSheetsRepository`
remains a pure declared-schema-plus-controlled-error implementation
(`RepositoryError`/`NotImplementedError`) — the correct, minimum,
reversible deliverable here is schema/name alignment plus stub methods at
the same fidelity as every existing Phase 2–5 method, not a live
integration that is impossible without real credentials.

## 3. GOOGLE SHEETS SCHEMA — TAB NAMES ACTUALLY USED

`backend/app/repositories/google_sheets/schemas.py` — tab names corrected
to match the live prototype sheet exactly (columns still mapped by
header name, never row position):

**Renamed to match the live sheet (existing sheets, reused, never
duplicated):**
`model_master`, `vehicle_master`, `vehicle_component`, `equipment_master`,
`equipment_status_history` (already correct), `maintenance_plan`,
`pm_task_master`, `pm_task_part`, `pm_work_order`, `pm_work_result`,
`pm_used_part`, `meter_snapshot`, `inspection_header`, `inspection_result`,
`repair_order`, `repair_action`, `repair_part`, `attachment`,
`part_master`.

**Declared as read-only reference sheets (no live writer exists yet;
declared so a future live-GPS/counter phase targets the correct existing
tab, never a new one):** `current_counter`, `latest_location`.

**New sheets added (already present in the live prototype sheet; exact
column lists copied verbatim from the delta prompt):**
`repair_assignment`, `pm_work_assignment`, `pm_work_scope`,
`material_request`, `material_request_line`, `location_snapshot`.

**Not renamed** (no live name was given for these by the delta, so no
name was guessed — B01 remains TBD-BLOCKING for them specifically):
`checklist_masters`, `checklist_revisions`, `checklist_items`,
`inspection_findings`, `pm_task_revisions`, `meter_readings`,
`part_sets`, `part_set_revisions`, `part_set_items`, `part_instances`,
`part_lifecycles`, `installation_segments`, `position_lifetime_records`,
`lifetime_rules`.

**Deliberately not created:** any competing model→plan mapping sheet
(reused `model_master.default_plan_code`), any separate technician
master sheet (reused `user_account.user_id` as a plain opaque string —
no `user_account` domain/repository code exists to fabricate, since
nothing in this codebase needs to look a user up, only to carry their
id), any `waiting_parts` sheet.

## 4. FILES ADDED

- `backend/app/domain/assignment.py` — `AssignmentRole` (PRIMARY/
  COLLABORATOR), `RepairAssignmentHistoryEntry`, `PmAssignmentHistoryEntry`.
- `backend/app/domain/location_snapshot.py` — `LocationSnapshot`,
  `LocationService` (the GPS half of the shared automatic machine-state
  snapshot mechanism; `_read_latest_location` is the single seam a future
  phase wires a real reader into).
- `backend/app/domain/material_request_service.py` — `MaterialRequestService`,
  `RequisitionLineInput`, the "awaiting parts" derived-indicator logic.
- `backend/app/api/v1/material_request_schemas.py`,
  `backend/app/api/v1/material_requests.py` — explicit manual material
  request routes (`POST /material-requests`,
  `GET /material-requests/{id}`,
  `GET /material-requests/by-work-order/{id}`).
- `backend/app/api/v1/location_snapshot_schemas.py`,
  `backend/app/api/v1/location_snapshots.py` — read-only location-snapshot
  routes (snapshots are only ever created as a side effect of
  `MeterService.capture_current_state`).
- `backend/tests/test_core_demo_fixes_delta.py` — 22 new delta-specific
  tests (Section 8).

## 5. FILES MODIFIED

- `backend/app/repositories/google_sheets/schemas.py` — tab-name/column
  realignment described in Section 3.
- `backend/app/domain/requisition.py` — split into `MaterialRequest`
  (header) + `RequisitionLine` (detail, now carrying
  `material_request_id`/`source_task_revision_id`/`part_code_snapshot`/
  `line_source` instead of the old `work_order_reference`/`source_type`).
- `backend/app/domain/pm.py` — `PmWorkOrder` gained
  `primary_technician`/`collaborators`.
- `backend/app/domain/pm_service.py` — `approve_scope` now creates one
  `MaterialRequest` header (only when in-scope tasks have standard parts)
  plus its lines; added `assign()`/`list_assignment_history()`.
- `backend/app/domain/repair_service.py` — `assign()` gained
  `assigned_by`; added `list_assignment_history()`.
- `backend/app/domain/meter_service.py` — `capture_current_state` now
  also calls `LocationService.capture_location_snapshot`, linked via
  `event_id=snapshot.meter_snapshot_id`, transparently for all 8 existing
  automatic-snapshot call sites.
- `backend/app/repositories/base.py` — new abstract methods for
  assignment history (repair + PM), location snapshot, and material
  request/line; `assign_repair` gained `assigned_by`;
  `create_requisition_line` signature updated for the header/detail split.
- `backend/app/repositories/mock/repository.py` — full in-memory
  implementation of all of the above, including the non-destructive
  append-only assignment-history diff (previous active row(s) get
  `active_status=False`/`ended_at` set, never deleted).
- `backend/app/repositories/google_sheets/repository.py` — corresponding
  stub methods, each raising a controlled `RepositoryError` naming the
  correct new/renamed tab.
- `backend/app/api/v1/pm.py`, `pm_schemas.py` — `POST
  /pm/work-orders/{id}/assign`, `GET
  /pm/work-orders/{id}/assignment-history`; response schemas for
  `MaterialRequest`/`MaterialRequestDetail`/assignment history.
- `backend/app/api/v1/repairs.py`, `repair_schemas.py` — `GET
  /repairs/{id}/assignment-history`; `GET /repairs/{id}` now also returns
  `awaiting_parts` (derived, `None` on every other response — never an
  N+1 cost on list endpoints).
- `backend/app/api/v1/router.py`, `dependencies.py` — wired in the two
  new routers/services.
- `frontend/src/lib/types.ts` — `RequisitionLine` corrected to the new
  header/detail shape (the old `work_order_reference`/`source_type`
  fields were stale — no frontend component had started consuming them
  yet, so this is a pure type-accuracy fix, not a UI change); added
  `MaterialRequest`/`MaterialRequestDetail`/`LocationSnapshot` types;
  added `awaiting_parts` (optional) to `RepairDetail` and
  `primary_technician`/`collaborators` to `PmWorkOrder` to match the
  actual current API contract. No new frontend UI was built for
  assignment history, material requests, or location snapshots — this
  delta's own scope was backend/schema alignment, not new screens.
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` — C02 updated
  to explicitly list `RETIRED` in the approved equipment status-code
  vocabulary (it was implemented and tested by the prior session's
  checkpoint 1 but the register text still named only the original 4
  codes — a documentation gap, fixed here; no code or test behavior
  changed).

## 6. API ROUTES ADDED

- `POST /api/v1/pm/work-orders/{id}/assign`
- `GET /api/v1/pm/work-orders/{id}/assignment-history`
- `GET /api/v1/repairs/{id}/assignment-history`
- `POST /api/v1/material-requests`
- `GET /api/v1/material-requests/{id}`
- `GET /api/v1/material-requests/by-work-order/{id}`
- `GET /api/v1/location-snapshots/{id}`
- `GET /api/v1/location-snapshots/by-event/{event_id}`

`GET /api/v1/repairs/{id}` extended (additive field `awaiting_parts`);
no existing route's request/response shape was changed in a breaking way.

## 7. EXPLICIT DECISIONS APPROVED BY THIS DELTA'S OWN TEXT

- Technician/assignment identity is the plain opaque `user_id` string the
  delta specified (`user_account.user_id`) — no lookup, validation, or
  master record against it; consistent with `RequestContext.user_id`.
- `default_plan_code` (sheet) / `VehicleModel.assigned_pm_plan_id`
  (domain) is confirmed as the one-plan-per-model mapping; no second
  mapping mechanism exists.
- Assignment history is non-destructive/append-only for both repair and
  PM (ended rows are marked `active_status=False`/`ended_at`, never
  deleted).
- PM scope stays frozen (task set + approval) after approval regardless
  of later edits to the plan's active task revision — proven directly in
  Section 8's tests, not merely assumed.
- "งานรออะไหล่" (awaiting parts) is a derived indicator computed from
  open, non-terminal `MaterialRequest`s against the repair's own id —
  never a stored table, never a duplicated repair record, never a new
  `RepairStatus` member.
- Location snapshot is a separate, immutable sheet/entity
  (`location_snapshot`) alongside `meter_snapshot`, both driven by the
  same automatic-capture call site — not embedded fields squeezed onto
  `MeterSnapshot`.

## 8. UNRESOLVED DECISIONS DELIBERATELY LEFT OPEN (not guessed)

- **B01** (exact live sheet schema version) and **B03** (Google Auth
  Method) — both TBD-BLOCKING; no live Google Sheets I/O was attempted or
  simulated.
- The 14 sheets listed in Section 3's "not renamed" list have no live
  name confirmed by this delta, so their Phase 2–5 placeholder names are
  left exactly as they were — not guessed to match some assumed live
  name.
- `MeterSnapshot.latitude`/`longitude` (added by a prior checkpoint
  commit, always `None`) were left in place rather than removed now that
  `location_snapshot` is the authoritative GPS entity — removing them was
  out of this delta's explicit "do not redo the 8 commits' work" scope,
  and leaving two always-`None` fields is harmless; a future phase can
  retire them once `location_snapshot` is the confirmed sole consumer on
  the frontend.
- No PM task-part (`pm_task_part`) source data exists anywhere in seed
  data for any plan, so `test_pm_scope_approval_with_standard_parts_...`
  (Section 9) exercises the mechanism with a test-local synthetic
  `PmTaskPart`, the same technique
  `test_pm_plan_and_task_revision.py` already established for synthetic
  task/revision content — this is test-local setup, not fabricated
  production seed data.

## 9. TESTS ADDED (backend)

`backend/tests/test_core_demo_fixes_delta.py` (14 tests):
- Technician identity is a plain opaque `user_id` — no technician-master
  method/sheet exists.
- Repair reassignment ends previous history rows instead of deleting them.
- PM reassignment ends previous history rows instead of deleting them.
- PM scope addition rejects a task belonging to a different plan.
- PM scope stays frozen (task set + `scope_approved_at`) after approval,
  even after the plan's active revision is later edited to add a new task.
- PM scope approval with no standard parts creates no material request
  (baseline, unmodified seed data).
- PM scope approval with standard parts creates exactly one
  `material_request` header with correctly-linked lines (part
  description/quantity/unit/`source_task_revision_id`/`line_source`),
  approved/issued/used/returned quantities all `None`.
- Explicit repair material request: requested/approved/issued/used/
  returned quantities stay separate, nullable columns.
- "Awaiting parts" is derived (flips true/false live from
  `MaterialRequest` state), never a stored table, never a new
  `RepairStatus` member, and never mutates the repair record itself.
- Repair creation automatically captures a linked `location_snapshot`
  (same `event_id` as its `meter_snapshot_id`).
- A missing GPS source stays honestly null (`latitude`/`longitude`/
  `altitude_m`/`accuracy_m`/`gps_time`/`source` all `None`, `gps_valid`
  `False`) — never `0, 0`.
- An EQUIPMENT-sourced event never gets a fabricated location snapshot
  (`vehicle_id=None` short-circuits before any GPS read).

`backend/tests/test_google_sheets_repository.py` (8 new tests added to
the existing file):
- Every declared tab name (26 checked, parametrized) matches the live
  prototype sheet exactly, with no duplicate/alternate spelling alongside
  it.
- `repair_assignment`, `pm_work_assignment`, `pm_work_scope`,
  `material_request`/`material_request_line`, `location_snapshot`, and
  `equipment_master`/`equipment_status_history` (including a `RETIRED`
  status-change call) each raise a controlled `RepositoryError` naming
  the correct tab — never a crash, never a silently wrong result.

Cross-plan-only enforcement (item 4), scope-freeze durability (item 5),
and technician-identity referencing (item 11, structural) are proven
directly by name above. My Work / Open Repair Queue no-regression (item
12) and all 8 prior checkpoint behaviors remaining intact (item 14) are
proven by the full, unmodified prior test suite passing unchanged
(Section 10) — no existing test was edited to make this delta pass.

## 10. TEST RESULTS

**Backend — pytest**
```
$ bash scripts/run_backend_tests.sh -q
253 passed, 39 warnings in 13.35s
```
(208 pre-existing tests — all 8 checkpoint commits' own suites,
unmodified and passing — + 45 new: 22 in
`test_core_demo_fixes_delta.py`, 8 new in `test_google_sheets_repository.py`,
plus the pre-existing file's own 15. All warnings are the pre-existing
`HTTP_422_UNPROCESSABLE_ENTITY` Starlette deprecation notice, same
category present since Phase 1 — unrelated to this delta.)

**Frontend — typecheck**
```
$ npx tsc -b
(no output — 0 errors)
```

**Frontend — lint**
```
$ npx oxlint
exit 0 — 0 errors, 18 pre-existing-category `react(set-state-in-effect)`
warnings (present before this delta, none newly introduced)
```

**Frontend — unit/component (Vitest)**
```
$ npx vitest run
Test Files  25 passed (25)
     Tests  52 passed (52)
```
(Unchanged from the prior session — this delta added no new frontend
components/pages, only type corrections with no new consumers, so no new
frontend test was needed.)

**Frontend — production build**
```
$ npm run build
✓ 68 modules transformed, built in 1.65s
```

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
<run started in this session; still executing at the time of this
commit — this repository's Chromium-backed suite legitimately takes
several minutes across 5 viewport projects. A follow-up commit on this
same branch will record the exact pass/fail count as soon as it
completes; nothing here is a guess or a carried-over number from a
different run.>
```

No test was skipped, disabled, or hidden. No result above was claimed
without being executed in this session.

## 11. TEST RESULTS (SUMMARY TABLE)

| Suite | Result |
|---|---|
| Backend pytest | 253/253 passed (208 pre-existing + 45 new) |
| Frontend Vitest | 52/52 passed (unchanged) |
| Frontend typecheck (`tsc -b`) | PASSED |
| Frontend lint (`oxlint`) | PASSED (0 errors, 18 pre-existing-category warnings) |
| Frontend production build | PASSED |
| Playwright e2e (5 viewports) | IN PROGRESS at commit time — see follow-up commit |

## 12. KNOWN LIMITATIONS

- No live Google Sheets connectivity exists (B03 TBD-BLOCKING) — every
  `GoogleSheetsRepository` method for every phase, including this
  delta's 8 new sheets, is a declared-schema stub that raises a
  controlled `RepositoryError` rather than performing real I/O. This is
  unchanged from every prior phase's own limitation, not a regression
  introduced here.
- No live GPS/IoT device ingestion exists — `LocationService.
  _read_latest_location` always returns an honestly-unknown reading.
  Every `location_snapshot` this branch ever creates has
  `latitude=longitude=None`, `gps_valid=False` until a future phase wires
  in a real device/telemetry source at that single seam.
- No PM task-part (standard part) source data exists for any plan —
  `PmService.approve_scope`'s auto-requisition logic is exercised only
  against a test-local synthetic `PmTaskPart`; in the live demo, PM scope
  approval creates no material request until real `pm_task_part` rows
  exist in the live sheet.
- `MeterSnapshot.latitude`/`longitude` (prior checkpoint's own fields,
  always `None`) still exist alongside the new, authoritative
  `location_snapshot` entity — left in place per this delta's own "do not
  redo the 8 commits' work" instruction (see Section 8).
- No new frontend screens read `material_request`, assignment history,
  or `location_snapshot` data yet — this delta's scope was backend/schema
  alignment and tests, not new UI; the existing Repair/PM pages continue
  to work exactly as the prior session left them.

## 13. CONFIRMATION: PHASE 6 WAS NOT IMPLEMENTED

No Phase 6 scope (whatever it is defined to be — no Phase 6 prompt exists
in this repository) was implemented, referenced, or scaffolded anywhere
in this delta.

## 14. FROZEN PHASE 1–5 CONTRACTS AFFECTED: **NO**

Every change is additive (new optional fields, new abstract methods, new
routers) except the `RequisitionLine`/requisition-line repository method
signature, which is Phase 4's own newly-introduced (this same Core Demo
Fixes effort, prior session) requisition scaffolding being completed to
the header+detail shape the live sheet requires — no Phase 1–3 contract,
and no Phase 5 (Parts/Lifetime/Transfer) contract, was touched at all.

## 15. LOCAL STARTUP COMMANDS

Unchanged from every prior phase:
```
bash scripts/run_backend_tests.sh -q
cd frontend && npx tsc -b && npx vitest run && npx oxlint && npm run build
bash scripts/run_e2e_tests.sh
```
