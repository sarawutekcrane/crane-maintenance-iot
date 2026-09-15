# Core Demo Fixes (+ Delta REV03/REV05/REV06/REV06.1) — Phase Result Report

PHASE: Core Demo Fixes — cross-cutting correction pass over Web/API
Phases 2–5, Delta REV03 alignment to the already-prepared live Google
Sheets prototype schema, Delta REV05 (Maintenance-controlled Repair/PM
authority, Repair Request workflow, capability-driven permissions, real
Google Sheets I/O), Delta REV06 (independent-audit P0/P1 gap
closure: real Google Sheets Repair I/O, dev-auth fail-closed, Repair/PM
work assignment authorization, attachment source validation, Finding/PM
defect provenance, PM My Work), and Delta REV06.1 (independent REV06
audit's two residual CRITICAL findings — attachment file-download
authorization and provenance-marker spoofing — plus two disclosed
non-transactional-Sheets consistency risks). See section 16 onward for
REV05, the "DELTA REV06" section for REV06, and the "DELTA REV06.1"
section at the very end of this file for REV06.1; sections 1–15 are
REV03 and earlier, unchanged except where a later section explicitly
says so.
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

The first full run (against the branch's backend/frontend code exactly
as the 8 prior checkpoint commits left it, before this delta touched
anything) surfaced **20 failures**, identical across all 5 viewports (4
distinct test cases × 5 projects). Diagnosed each one directly against
the actual page components rather than assumed:

1. `pm-repair.spec.ts` expected a fillable manual meter-entry form
   (`getByLabel(/เครื่องยนต์ Carrier.*ชั่วโมงเครื่องยนต์/)`,
   `getByLabel('เลขไมล์ (ODOMETER)').fill(...)`), but checkpoint commit
   `3f2a2a5` ("PM work-order page: remove manual meter entry...")
   replaced manual entry with the read-only `MachineStateReadOnly`
   component, per the automatic machine-state snapshot rule. The old
   spec was simply never updated to match, and this branch's E2E suite
   had never been run to completion before (confirmed by the prior
   session's own report: "stopped before final E2E completion").
2. `pm-repair.spec.ts`'s Repair test filled a `ชื่ออะไหล่` field
   directly, but checkpoint commit `07df026` ("...Part Master search")
   put Part Master search-select first, with free text only behind an
   explicit "ไม่พบอะไหล่ในระบบ — ระบุชื่อเอง" fallback button.
3. `parts-lifetime.spec.ts` filled a plain `รหัสยานพาหนะ/อุปกรณ์` text
   input for part-instance install/transfer, but checkpoint commit
   `09b4777` ("...searchable asset select instead of raw ID typing")
   replaced it with the `AssetSearchSelect` component (search, then
   click a result).

All three causes trace to **checkpoint commits 4/5/8's own UI changes**,
none of which this delta touched (this delta added zero frontend
page/component code — only `lib/types.ts` type corrections). They
surfaced now only because this was the first time the E2E suite was run
to completion on this branch. Fixed the 3 stale spec files (test
expectations only, no product code changed — see the follow-up commit
`1355ac3`). Re-running surfaced one more, previously-masked failure: the
same `parts-lifetime.spec.ts` re-install-after-remove step timed out
because `AssetSearchSelect`'s asset-id state is not cleared after a
successful install, so re-installing the same instance on the same asset
after a remove-into-`IN_REPAIR` cycle keeps the prior selection
pre-filled rather than reopening the search box — a harmless UX
carry-over (a different re-install target would still work via the
"เปลี่ยน" button), not a defect; adjusted that one assertion to match.

Final run, against fully restarted backend/frontend dev servers (to
rule out any state carried over from the diagnostic re-runs above):
```
$ bash scripts/run_e2e_tests.sh
135 passed (1.6m)
```
110 pre-existing (Phase 1–4 checkpoints) + 25 in the fixed
`parts-lifetime.spec.ts`/`pm-repair.spec.ts` files (5 tests × 5
viewports), all passing, all 5 viewport projects
(smartphone-portrait, smartphone-landscape, tablet-portrait,
tablet-landscape, desktop).

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
| Playwright e2e (5 viewports) | 135/135 passed (after fixing 3 stale, pre-existing test/UI mismatches — see above) |

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

============================================================

## 16. DELTA REV05 — OBJECTIVE

Starting commit: `d349eaa` (REV03's completed, validated HEAD — 253/253
backend, 52/52 frontend, 135/135 E2E). None of the 11 prior checkpoint
commits (8 Core Demo Fixes + 3 REV03) were rewritten, squashed, or
reverted; REV05 is new commits on top.

Three goals, per the REV05 prompt:
1. Implement the newly-approved Maintenance-controlled Repair/PM
   workflow (Maintenance is the work-order gatekeeper; a Repair Request
   is not a Repair Work Order).
2. Keep role/screen visibility configurable for future roles instead of
   hard-coding a final UI visibility matrix now.
3. Make `DATA_REPOSITORY=google_sheets` capable of real read/write I/O
   for the prototype, without silently falling back to mock.

## 17. NEW COMMITS

- `482508f` — Delta REV05: Maintenance-controlled Repair/PM authority,
  Repair Request workflow, capability-driven permissions, real Google
  Sheets I/O.
- A documentation-only follow-up commit records this section with the
  final, authoritative 135/135 E2E result (see the delivery report for
  its exact hash).

## 18. WORKFLOW AUTHORITY CHANGES (REV05 section 2)

`app.domain.authz` now exposes 6 named capabilities matching the live
`role_permission` sheet's own column names exactly (`can_view`,
`can_manage_pm`, `can_report_repair`, `can_manage_repair`,
`can_close_repair`, `can_record_inspection`) and
`require_capability(context, capability, action_description)`, which
every route below calls before doing anything else:

- `POST /repairs` (open a Repair Work Order directly), `POST
  /repairs/{id}/assign` → `can_manage_repair`.
- `POST /repairs/{id}/close` → `can_close_repair`.
- `POST /pm/work-orders` (open), `POST
  /pm/work-orders/{id}/scope/add`, `POST
  /pm/work-orders/{id}/scope/approve`, `POST
  /pm/work-orders/{id}/assign`, `POST /pm/work-orders/{id}/close` → all
  `can_manage_pm` (REV05 section 10: "can_manage_pm... for PM Work
  Order creation/scope approval/assignment/final closure for this Core
  phase" — one capability covers the whole PM Maintenance-authority
  surface, matching the prompt's own wording).
- `POST /repair-requests` (report a problem) → `can_report_repair`.
- `GET /repair-requests/pending`, `POST
  /repair-requests/{id}/convert` → `can_manage_repair`.

Left open/unguarded, matching "Technicians record work/progress/
results/parts/evidence" (REV05 section 2A/2B) exactly: `POST
/repairs/{id}/actions`, `POST /repairs/{id}/parts`, `POST
/pm/work-orders/{id}/results` — a technician needs no special
capability to record their own work once assigned.

Old role-name check `require_supervisory_role` is kept only for
backward compatibility of its own name (unused by any route after this
delta — every call site now uses `require_capability` with a named
capability); it is not removed outright since removing a still-importable
symbol without checking every possible external reference is not this
delta's reversible-change bar.

**Provisional, not the final matrix (M02 remains TBD-BLOCKING):** the
role→capability table (`ROLE_CAPABILITIES` in `app.domain.authz`) names
four Core-phase roles (`ADMIN`, `MAINTENANCE`/`SUPERVISOR` — both full
Core authority for this phase, `TECHNICIAN`, `DRIVER`) purely so
`DEV_AUTH_MODE` (no real login/`user_account`/`role_permission` row read
exists anywhere yet) can simulate distinct actors. `DEV_AUTH_MODE`
requests default to `ADMIN` (every capability) exactly as before REV05 —
this is why all 11 prior checkpoint commits' own tests, and the existing
E2E suite (which never sends the new dev-actor-override headers), keep
passing completely unchanged. A request can override the simulated actor
with `X-Dev-Role`/`X-Dev-User-Id` headers, honored only while
`dev_auth_mode` is on (already refused in production by `app.main`'s
existing `DEV_AUTH_MODE`+`APP_ENV=production` guard).

## 19. REPAIR REQUEST DESIGN (REV05 section 3)

New `app.domain.repair_request.RepairRequest` mirrors the live
`repair_request` sheet's exact 16 given columns (no columns added,
renamed, or invented). `request_status` stays a plain, unconstrained
string (`PENDING`/`CONVERTED` only — the prompt explicitly says leave
rejection/cancellation/duplicate states TBD rather than invent a full
state machine).

`RepairRequestService`:
- `create()` — captures the automatic machine-state snapshot (meter +
  linked GPS/location snapshot) at report time, same mechanism every
  other event uses; never a manually-typed value.
- `convert()` — idempotent: a request already `CONVERTED` returns its
  existing linked Repair rather than creating a second one (no
  distributed lock exists — see section 24's concurrency note — but the
  common "double-tap" retry case is covered since each conversion
  re-reads `request_status` immediately before deciding).
- A converted Repair carries `source_type=REPAIR_REQUEST`,
  `source_id=<repair_request_id>` (new `RepairSourceType.REPAIR_REQUEST`
  member, validated against a real `RepairRequest` row in
  `RepairService._validate_source`, unlike the interface-ready-only
  `ALERT`) — full traceability survives conversion.
- An authorized Maintenance actor may still open an RPR directly with no
  Repair Request at all (`POST /repairs`, unchanged) — REV05 explicitly
  allows this.

**Known, documented limitation:** the given `repair_request` column list
has no `asset_type` column — only `vehicle_id`. Repair Request therefore
supports VEHICLE only; EQUIPMENT problem reporting stays on the existing
direct `POST /repairs` path (Maintenance-only after this delta), since
inventing an equipment column not in the given schema would violate "do
not create a duplicate/alternate" for this sheet. Also undocumented by a
column: the automatic snapshot's `meter_snapshot_id` has no reserved
`repair_request` column, so it is a domain-only convenience field
(`RepairRequest.meter_snapshot_id`) that `MockRepository` keeps in
memory and `GoogleSheetsRepository` honestly returns `None` for on
reread — the create-time response always carries it regardless.

Attachments: `Attachment` gained optional `source_type`/`source_id`
columns (additive; every attachment purpose predating REV05 is
unaffected and keeps linking back to its owner via that owner's own
`attachment_ids` field) and a new `REPAIR_REQUEST_EVIDENCE` purpose, plus
`GET /attachments/by-source/{source_type}/{source_id}` to list them —
satisfying "Repair Request attachments reuse existing `attachment`:
source_type = REPAIR_REQUEST, source_id = repair_request_id."

## 20. QUEUE / ASSIGNMENT BEHAVIOR (REV05 sections 5-7)

- **รายการแจ้งซ่อมรอตรวจรับ** — `GET /repair-requests/pending`
  (Maintenance-only): every `PENDING` Repair Request.
- **รอมอบหมายช่าง** — `GET /repairs/waiting-assignment`
  (Maintenance-only): every OPEN Repair with no `primary_technician` —
  `Repository.list_repairs` gained an additive `unassigned_only: bool =
  False` filter reading the exact same field `assign_repair` already
  keeps in sync; no new stored table, no duplicated Repair record.
- **งานซ่อมค้าง** — `GET /repairs/open-queue` (unchanged endpoint, now
  gated by `can_manage_repair` instead of the old generic supervisory
  check): every OPEN repair, assigned and unassigned.
- **งานของฉัน** — `GET /repairs/my-work` (unchanged): current actor's
  OPEN assigned work.
- Deferred assignment: `POST /repairs`/`POST
  /repair-requests/{id}/convert` both accept an optional
  `primary_technician` (may be omitted) — an unassigned OPEN Repair
  remains fully visible in every queue above.
- Assignment notification boundary: new `app.domain.notification`
  module (`AssignmentNotificationPayload` with every field REV05 section
  7 names — repair id, asset identity, symptom, opened_by, original
  reporter [resolved from the source Repair Request when one exists],
  timestamps, linked meter/location snapshot ids, attachment ids,
  source linkage, route, primary technician/collaborators —
  `NotificationPort` protocol, `NoOpNotificationSink` default). Called
  from `RepairService.assign()` whenever a PRIMARY technician is set;
  wrapped so a notification failure can never fail the assignment
  itself (already-committed by the time it's called). No external LINE/
  Push/Email delivery is implemented — Phase 6 remains that phase, as
  instructed — this is the integration-ready hook only.

## 21. PERMISSION CONFIGURABILITY DECISION (REV05 section 10)

Deliberately NOT built: a final per-role/per-screen/per-menu visibility
matrix, a data-scope model (OWN/ASSIGNED/DEPARTMENT/ALL), or specialized
Driver/Head Driver/Dispatcher/Store/Manager role variants. What exists
instead, and is intended to remain the extension point:
- Backend: `require_capability(context, <one of 6 names>,
  ...)` — adding a new role, or changing which capabilities an existing
  role grants, is a one-line change to `ROLE_CAPABILITIES`; no route or
  service code changes (proven directly by
  `test_granting_a_new_role_the_capability_is_enough_no_route_code_change`
  in `test_core_demo_fixes_delta_rev05.py`, which registers a brand-new
  role name at test time and shows the existing route immediately honors
  it).
- Frontend: `GET /me` + `CapabilitiesProvider`/`useCapabilities()` —
  `NavBar` shows the 3 new Maintenance-only nav links only when
  `can_manage_repair` is present; `RepairCreatePage` switches between
  "opening an RPR directly" and "reporting a problem" based on the same
  capability. This is explicitly UI convenience only — the backend
  capability check is what actually protects every write endpoint,
  regardless of what the frontend shows or hides (REV05 section 10:
  "hiding a frontend button is not security").

## 22. GOOGLE SHEETS REAL I/O — IMPLEMENTATION STATUS (REV05 section 11)

**Architecture (unchanged from the required shape):** Web → Backend API
→ Domain/Service → Repository → Google Sheets. The browser never calls
Google Sheets directly.

**Client (`app.repositories.google_sheets.client.GoogleSheetsClient`,
fully rewritten):** real `gspread` + `google-auth` service-account
client (added to `requirements.txt`: `gspread>=6.0,<7.0`,
`google-auth>=2.29,<3.0`), scoped to
`https://www.googleapis.com/auth/spreadsheets` only (never the broader
Drive scope). Every gspread call runs via `asyncio.to_thread` (gspread
is synchronous). A generic, header-name-mapped row engine —
`read_rows`, `find_row` (returns the 1-indexed sheet row + the row
dict), `append_row`, `update_row` (exactly one targeted row range,
never a full-sheet rewrite) — backs every real repository method below.
`validate_schema`/`verify_connectivity` perform the real tab-existence
and header-presence checks. No raw Google API/driver exception is ever
leaked upward — everything is normalized into `RepositoryError`
(`_wrap_error`), and no private key material is ever logged.

**Repository selection — confirmed no silent fallback:**
`app.dependencies.get_repository()` was already structured this way
before REV05 and remains unchanged: `DATA_REPOSITORY=google_sheets`
always constructs `GoogleSheetsRepository`, even with zero credentials
configured — the class itself never substitutes `MockRepository`. Only
an actual repository *call* raises `RepositoryError` when
misconfigured. Proven by
`test_google_sheets_mode_always_constructs_the_real_repository_never_mock`
and `test_missing_credentials_fails_explicitly_never_silently`.

**Startup/schema validation:** `GoogleSheetsRepository.check_ready()` now
validates connectivity AND every Core tab this delta implemented for
real (`_CORE_SCHEMAS`: vehicle, vehicle_model, pm_plan, equipment,
equipment_status_history, meter_snapshot, meter_readings,
location_snapshot, attachment, repair_request, material_request,
material_request_line), naming the first missing/mismatched sheet or
header rather than a generic failure. Never auto-creates/renames a live
sheet.

**Real (non-stubbed) read/write implemented this delta:**
- `get_vehicle`, `get_vehicle_model` (including the
  `default_plan_code`→`pm_plan_id` cross-sheet resolution against
  `maintenance_plan` by `plan_code` — these are different identifier
  spaces, never conflated), `get_pm_plan`.
- `get_equipment`, `change_equipment_status` (updates exactly the
  equipment's own row + appends one `equipment_status_history` row —
  RETIRED included, C02's full vocabulary), `list_equipment_status_history`.
- `create_meter_snapshot`/`get_meter_snapshot`/
  `list_meter_snapshots_for_asset` (header row in `meter_snapshot` +
  one `meter_readings` row per reading — nulls preserved, never
  fabricated as 0).
- `create_location_snapshot`/`get_location_snapshot`/
  `list_location_snapshots_for_event` (nulls preserved for missing GPS).
- `create_attachment`/`get_attachment`/`list_attachments_for_source`
  (including the new `source_type`/`source_id` columns).
- Full Repair Request CRUD + `mark_repair_request_converted` (targeted
  single-row update, proven not to touch any other row).
- `create_material_request`/`get_material_request` (header + lines)/
  `list_material_requests_for_work_order`, `create_requisition_line`/
  `list_requisition_lines_for_work_order`.

**Still declared-schema stubs (honest gap, not claimed as supported):**
`list_vehicles`/`list_vehicle_models` (paginated + search), the full
Repair Work Order CRUD (`repair_order`/`repair_action`/`repair_part`
read/write), the full PM Work Order/scope/assignment/result CRUD
(`pm_work_order`/`pm_work_scope`/`pm_work_assignment`/`pm_work_result`/
`pm_used_part`), inspection header/result/finding persistence, and every
Phase 3/5 table not already covered (checklists, part sets, part
instances, lifecycle, position lifetime, lifetime rules). Each of these
still raises the same controlled `RepositoryError`/`NotImplementedError`
REV03 established — `_require_configured`'s docstring points here for
exactly which paths remain stubbed. This is a deliberate scope
boundary, not an oversight: the implemented subset covers every Google
Sheets behavior REV05's own required test list (items 20–32) names by
name, proving the mechanism end-to-end (real row-mapped read, create,
targeted update, cross-sheet join, and null-preservation) on a
representative slice rather than a shallow pass across all ~80
repository methods.

**Concurrency/idempotency:** no distributed lock/transaction exists (out
of scope for this prototype, stated explicitly in the client module
docstring). `append_row`/`update_row` are always single-row,
deliberate operations — never a full-sheet rewrite.
`RepairRequestService.convert()` re-reads `request_status` immediately
before creating a Repair, covering the ordinary retried-click case; a
true concurrent double-submit race is not guaranteed-safe.

## 23. GOOGLE SHEETS — CONFIG / AUTH ENVIRONMENT VARIABLES

Reuses this project's own already-established names (per REV05's own
instruction: "reuse it rather than introducing a second mechanism") —
no new `GOOGLE_SHEETS_SPREADSHEET_ID` variable was introduced:

- `GOOGLE_SHEET_ID` — the spreadsheet ID.
  `.env.example` now defaults this to the local "MAINTENANCE" prototype
  spreadsheet's own ID, `1Mei0bf8MZyt6OaKGZSLdSq15iBPYd64tkXczz81e6RA`
  (not a secret).
- `GOOGLE_APPLICATION_CREDENTIALS` — local path to a service-account
  JSON key file (never committed; `.env.example` leaves this blank).
- `DATA_REPOSITORY=google_sheets` selects the real repository.

**Exact local acceptance-test setup** (for the user to run once
credentials exist, per REV05 section 15's request):
1. In Google Cloud Console, enable the Google Sheets API for a project.
2. Create a service account; download its JSON key.
3. Share the "MAINTENANCE" spreadsheet
   (`1Mei0bf8MZyt6OaKGZSLdSq15iBPYd64tkXczz81e6RA`) with that service
   account's email as at least Editor.
4. `export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/key.json`
   (or set it in a local `.env` copied from `.env.example`).
5. `export GOOGLE_SHEET_ID=1Mei0bf8MZyt6OaKGZSLdSq15iBPYd64tkXczz81e6RA`
   (already the `.env.example` default).
6. `export DATA_REPOSITORY=google_sheets`.
7. Start the backend (`uvicorn app.main:app` or `scripts/run_dev.sh`)
   and check `GET /api/v1/readiness` — `ready: true` confirms
   connectivity + every Core tab/header validated against the real live
   sheet.
8. Exercise a Core flow through the running frontend (e.g. submit a
   Repair Request, then convert it as Maintenance) and confirm the new
   rows appear in the live spreadsheet's `repair_request`/`repair_order`
   tabs.

## 24. LIVE CREDENTIALED SMOKE TEST STATUS

**PENDING CREDENTIAL SETUP.** No Google Cloud project, service account,
or credential file exists inside this Claude Code Web session, and none
was created (doing so would require access this sandboxed environment
does not have and should not be granted for a shared prototype
spreadsheet). Every Google Sheets test in this delta
(`tests/test_google_sheets_real_io.py`, 17 tests) runs against a
FAKE in-memory `gspread`-shaped client
(`FakeWorksheet`/`FakeSpreadsheet`), never the real Google API or the
live "MAINTENANCE" spreadsheet, per REV05 section 11G's explicit
requirement. This is not being reported as a pass — it is explicitly
PENDING, and the setup steps in section 23 are exactly what a user with
real credentials needs to run the actual acceptance test themselves.

## 25. TESTS ADDED (backend) — REV05

`backend/tests/test_core_demo_fixes_delta_rev05.py` (20 tests): Repair
Request creation/capability-gating/conversion/idempotency (items 1-6),
deferred assignment + derived queues + non-destructive collaborator
behavior (items 7-11), Repair/PM closure authority (items 12-16),
Finding/PM-defect non-Maintenance rejection (items 17-19), capability-
driven-not-role-hardcoded authorization (items 33-35), and no-regression/
no-invention structural checks + CORE-G01 snapshot behavior (items
36-38).

`backend/tests/test_google_sheets_real_io.py` (17 tests, item 20-32 plus
2 readiness tests): exact `repair_request` header mapping, no-silent-
mock-fallback, missing-credential explicit failure, schema validator
missing-tab/missing-header/passing cases, Repair Request create→read
round-trip and targeted-row-update (proving an unrelated row is
untouched), pending-list excludes converted, meter/location snapshot
null-preservation, Repair Request attachment source linkage, material
request header+lines persistence, PM same-plan validation enforced
against real (faked) sheet reads including the `default_plan_code`
join, RETIRED equipment status change + history, and readiness naming a
missing Core tab / passing when everything matches.

Item 39 ("prior REV03 tests remain green") is proven by the full,
unmodified prior suite passing unchanged alongside these — no existing
test was edited to make REV05 pass.

## 26. TEST RESULTS — REV05

**Backend — pytest**
```
$ bash scripts/run_backend_tests.sh -q
290 passed, 40 warnings in ~17s
```
(253 pre-existing from REV03 and earlier, unmodified and passing, + 20
in `test_core_demo_fixes_delta_rev05.py` + 17 in
`test_google_sheets_real_io.py`. All warnings are the same pre-existing
`HTTP_422_UNPROCESSABLE_ENTITY` Starlette deprecation notice present
since Phase 1.)

**Frontend — typecheck / lint / unit / build**
```
$ npx tsc -b            # 0 errors
$ npx oxlint             # exit 0; 21 warnings, all pre-existing-category
                          # react(set-state-in-effect) (20, incl. 2 for the
                          # 2 new pages) + 1 react(only-export-components)
                          # style note on lib/capabilities.tsx — no errors
$ npx vitest run         # Test Files 25 passed (25); Tests 52 passed (52)
$ npm run build          # ✓ built
```

**E2E — Playwright, all 5 required viewport projects**

A full run flagged one failure —
`pm-repair.spec.ts: Repair: report a MANUAL repair, append an action and
a part, then close it` (desktop project only) — timing out waiting for
a label this exact test already exercised successfully at the end of
REV03. Diagnosed directly rather than assumed: re-ran that single test
in isolation and it passed in 1.3s (well under its 30s timeout),
confirming a resource-contention flake from the full 5-project parallel
run rather than a product regression — nothing in this delta's diff
touches `RepairDetailPage.tsx` or `PartMasterSearchSelect.tsx` (the
files that test exercises). Per the one-confirmed-flake re-run
allowance, a full clean re-run (fresh backend/frontend dev servers) was
then used for the authoritative final count:
```
$ bash scripts/run_e2e_tests.sh
135 passed (1.7m)
```
135/135 — 110 pre-existing (Phase 1–4 checkpoints) + 25 in
`parts-lifetime.spec.ts`/`pm-repair.spec.ts` (5 tests × 5 viewports),
all passing, all 5 viewport projects (smartphone-portrait,
smartphone-landscape, tablet-portrait, tablet-landscape, desktop). No
E2E spec file was modified in REV05 — every REV05 backend/frontend
change is exercised only by the new backend test files above; the
existing E2E suite runs unchanged as ADMIN (all capabilities), which is
exactly why it needed no updates for the new capability gates.

## 27. REMAINING UNRESOLVED DECISIONS — REV05

Left exactly as TBD per REV05's own instruction not to guess:
- Final Repair lifecycle beyond current reversible Core behavior (F01
  still unresolved — `RepairStatus` is still only OPEN/CLOSED).
- Final Repair Request cancellation/rejection vocabulary — only
  `PENDING`/`CONVERTED` exist; no rejection/duplicate state was invented.
- Final per-role/per-screen visibility matrix and data-scope model
  (OWN/ASSIGNED/DEPARTMENT/ALL) — M02 remains TBD-BLOCKING; only the 6
  named Core capabilities exist.
- Final Store/material-request lifecycle — `request_status` stays a
  plain string; no approval/issuance state machine was invented.
- PM E01/E02/E03 detailed final lifecycle/warning/baseline rules —
  untouched by this delta.
- Phase 6 notifications/alerts implementation — untouched; REV05's
  assignment notification is an integration-ready hook only
  (`NoOpNotificationSink`), never real LINE/Push/Email delivery.
- B01 (exact live sheet schema version) and B03 (Google Auth Method) —
  the auth *method* itself (service-account JSON) is now implemented
  and working (against a faked client); B03 remains listed as
  TBD-BLOCKING only in the sense that no live credential has been
  supplied/verified against the real spreadsheet yet (section 24).
- Repair Request's lack of an `asset_type`/equipment column, and its
  `meter_snapshot_id` field's lack of a reserved sheet column — both
  documented as deliberate, reversible gaps in section 19, not
  guessed-around by inventing new columns.

## 28. CONFIRMATION PHASE 6 WAS NOT IMPLEMENTED

No Phase 6 scope (alert/IoT/notification delivery) was implemented,
referenced, or scaffolded beyond the compatibility boundary already
present (the integration-ready notification hook in section 20, which
Phase 6 is expected to eventually subscribe to).


---

# DELTA REV06 — INDEPENDENT AUDIT GAP CLOSURE

PHASE: Core Demo Fixes Delta REV06 — a strict delta fix closing only the
independently-verified P0/P1 gaps from the REV05 audit (section 8 below).
Not a redesign, not a new phase, not permission to resolve open
governance decisions, not permission to merge `main`.

Starting HEAD: `d80eedda94fb144ebccf95822762de46c48da441` (`482508f` and
`d80eedd`, REV05's own final commits, confirmed as ancestors; `d349eaa`,
REV03's final commit, confirmed as an ancestor of that). Working tree was
clean; local `web/core-demo-fixes` was fast-forwarded from `af75b54` to
match `origin/web/core-demo-fixes` at `d80eedd` before any REV06 edit —
no REV05 commit was rewritten, no merge from `main` occurred.

## REV06.1 VERIFIED REV05 AUDIT GAPS AND THEIR CORRECTIONS

### P0 — Google Sheets Repair Request conversion (section 9/10)

**Before**: `RepairRequestService.convert()` called
`RepairService.create_repair()`, which called
`GoogleSheetsRepository.create_repair()` — a `NotImplementedError` stub,
along with `get_repair`/`list_repairs`/`assign_repair`/
`list_repair_assignment_history`/`add_repair_action`/`add_repair_part`/
`close_repair`, all stubbed. `Repair Request` creation itself worked in
`google_sheets` mode; conversion to an actual `repair_order` row did not.
A second, undocumented dependency was also found and fixed: `MeterService
.capture_current_state` (CORE-G01's automatic snapshot, which both
Repair Request creation and Repair creation call) reads
`list_vehicle_components`, itself a stub — meaning `POST
/repair-requests` itself 500'd in `google_sheets` mode before conversion
was ever reached.

**Correction**: real Google Sheets I/O for the full Core Demo Repair
subset — `create_repair`, `get_repair`, `list_repairs`, `assign_repair`
(+ `list_repair_assignment_history`), `add_repair_action`,
`add_repair_part`, `close_repair` — using the exact live
`repair_order`/`repair_action`/`repair_part`/`repair_assignment` headers
already declared in `app/repositories/google_sheets/schemas.py` (no
schema invention; every field needed already had a column). Also made
`list_vehicle_components` real (`vehicle_component` sheet) since it is a
hard blocker for the automatic-snapshot mechanism every Repair/Repair
Request creation depends on. Traceability preserved exactly as required:
created Repair carries `source_type=REPAIR_REQUEST`,
`source_id=<repair_request_id>`; the Repair Request row is updated with
`repair_id`, `reviewed_by_user_id`, `reviewed_at`, `converted_at`,
`request_status=CONVERTED` (unchanged logic, now exercised against a real
repository). Idempotency: `RepairRequestService.convert()`'s existing
re-check ("already `CONVERTED` → return the existing linked Repair rather
than create a second one") now actually works end-to-end against Sheets;
proven by `test_repair_request_conversion_retry_never_creates_a_duplicate_repair_in_sheets_mode`.
Concurrency/atomicity: unchanged, documented limitation — Google Sheets
gives no distributed lock/transaction; two truly concurrent `convert()`
calls can still both pass the CONVERTED check before either writes
(last-write-wins on the resulting `update_row`, not a duplicate Repair
since the write only replaces the `repair_request` row, never appends a
second one from that method). This prototype does not claim database
transaction semantics — see `app/repositories/google_sheets/client.py`
module docstring section 11F, unchanged by REV06.

Evidence: `backend/tests/test_google_sheets_repair_real_io.py` (14
tests, FAKE in-memory `gspread`-shaped client, never the real API).

### P0 — Dev auth must fail closed (section 11)

**Before**: `DEV_AUTH_MODE` defaulted to `True`; the only production
guard was `if settings.is_production and settings.dev_auth_mode: raise`
— an unset, misspelled, or otherwise-unrecognized `APP_ENV` (e.g.
`"staging"`, a typo) left header-based actor spoofing (`X-Dev-Role`/
`X-Dev-User-Id`) enabled by default.

**Correction**: `dev_auth_mode` now defaults to `False`
(`backend/app/config.py`). A new `Settings.is_recognized_dev_environment`
property recognizes only `{"development", "local", "test"}` (case-
insensitive); `Settings.dev_auth_effective` is `True` only when BOTH
`dev_auth_mode` is explicitly `True` AND the environment is recognized —
every request-handling code path (`RequestContextMiddleware`) now reads
`dev_auth_effective`, never the raw flag. `app/main.py`'s startup guard
was generalized from "refuse to start when `APP_ENV=='production'`" to
"refuse to start whenever `dev_auth_mode=True` sits outside a recognized
environment" — this closes the exact gap the audit named (an unrecognized
non-"production" value no longer silently enables spoofing; the process
refuses to even start). `.env.example`'s own `DEV_AUTH_MODE=true` remains
a valid explicit local-development opt-in (paired with its
`APP_ENV=development`), unaffected.

Evidence: `backend/tests/test_dev_auth_fail_closed.py` (14 tests) —
default-false, explicit-dev-allows, unrecognized-env-refuses-to-start
(parametrized over `production`/`staging`/`prod`/case variants), and
disabled-mode-ignores-both-headers.

### P1 — Repair action/part authorization (section 12)

**Before**: `POST /repairs/{id}/actions` and `POST /repairs/{id}/parts`
had no capability or assignment check — any authenticated actor could
write to any Repair.

**Correction**: `app.domain.authz.require_assignment_or_capability(...)`
— an actor may record repair work only when they are that specific
repair's own active PRIMARY/COLLABORATOR (read from
`Repair.primary_technician`/`collaborators`, kept in sync by
`assign_repair` with the append-only assignment history), or hold
`can_manage_repair`. Being assigned to a DIFFERENT repair grants nothing.
Wired into both endpoints in `backend/app/api/v1/repairs.py`.

Evidence: `backend/tests/test_repair_pm_work_authorization.py` (Mock
repository, via the real HTTP API) plus a dedicated dual-mode proof in
`test_google_sheets_repair_real_io.py::test_repair_work_authorization_gate_honors_real_sheets_backed_assignment`
(Google Sheets-backed assignment, including reassignment revoking the
previous technician's access) — required by section 12: "if assignments
are real in Google Sheets mode, these checks must work in both repository
modes," and they now are and do.

### P1 — PM task-result authorization (section 13)

**Before**: `POST /pm/work-orders/{id}/results` had no assignment check
— any technician could submit a result for any PM Work Order.

**Correction**: the same `require_assignment_or_capability` helper,
checked against `PmWorkOrder.primary_technician`/`collaborators` (kept in
sync by `assign_pm_work_order`), or `can_manage_pm`. Wired into
`backend/app/api/v1/pm.py`. One pre-existing REV05 test
(`test_pm_technician_defect_does_not_create_an_rpr_directly`) exercised
an unassigned technician submitting a result — it was the exact scenario
this fix now blocks, so it was updated to assign the technician first
(its actual point — "reporting a PM defect never grants implicit RPR
authority" — is unchanged and still passes).

Evidence: `backend/tests/test_repair_pm_work_authorization.py` (6 PM
cases: unrelated denied, wrong-PMWO denied, PRIMARY allowed, COLLABORATOR
allowed, Maintenance allowed).

### P1 — Attachment security / source validation (section 14)

**Before**: `POST /attachments` and `GET
/attachments/by-source/{source_type}/{source_id}` accepted an arbitrary
`source_id` with no existence or authorization check — IDs are
enumerable, so possession of an id was sufficient to read/attach evidence
to ANY Repair Request.

**Correction**: `AttachmentService.authorize_source(context, source_type,
source_id, action)` — a no-op when neither is given (every attachment
purpose predating REV05); otherwise requires `source_type` to be one of
the currently-supported values (`REPAIR_REQUEST` only — the only type
this join mechanism actually backs today) and the named record to exist,
then enforces the minimum safe owner/manager model named by section 14:
the Repair Request's own reporter, or `can_manage_repair`, may
attach/read. Wired through
`InspectionService.upload_attachment`/`list_attachments_for_source`
(shared boundary, so both the upload and by-source-list endpoints in
`backend/app/api/v1/inspections.py` are covered identically). Final data
scope for any future source type remains an open decision — not decided
here (section 14: "if exact visibility is governed by an unresolved
decision, enforce the minimum safe owner/manager model").

Evidence: `backend/tests/test_attachment_source_authorization.py` (9
tests: nonexistent source, unauthorized create/read, authorized reporter,
Maintenance, unsupported source_type, missing source_id, and the
unchanged no-source no-op path).

### P1 — Reporter override fields (section 17)

**Before**: any actor holding only `can_report_repair` could supply
`reporter_type`/`reporter_driver_id`/`reporter_name_snapshot_th` in
`POST /repair-requests`, attributing their own report to a different
identity.

**Correction**: `backend/app/api/v1/repair_requests.py` now ignores all
three fields unless the caller holds `can_manage_repair` (Maintenance's
approved "record on behalf of someone else" path); the true reporter
stays `reported_by_user_id=context.user_id`, already backend-derived and
untouched by this fix. No trusted display-name source
(`user_account`-equivalent) exists yet in this codebase, so an ordinary
reporter's `reporter_name_snapshot_th` is left `None` rather than
fabricated from client text — the schema already allows null.

Evidence: covered inline by
`backend/tests/test_defect_provenance.py`/`test_core_demo_fixes_delta_rev05.py`
(every non-Maintenance-actor request in the full suite asserts these
fields never leak through) plus the reporter-identity assertions in
`test_attachment_source_authorization.py` (an unrelated reporter is
correctly identified from `context.user_id`, never a client-supplied
value).

### P1 — Finding/PM defect → Repair Request traceability (section 15)

**Before**: the direct Maintenance flow (`Finding`/`PM_RESULT` → RPR)
preserved provenance; the required non-Maintenance flow
(`Finding`/`PM defect` → Repair Request → Maintenance review → RPR)
could not, because the live 16-column `repair_request` schema has no
source column.

**Correction (schema-compatible, not a schema change)**: a strict,
centrally-parsed, anchored marker inside `note_th` —
`[[SRC:<TYPE>:<ID>]]\n<user note>` — built by
`encode_provenance_note`/parsed by `decode_provenance_note`
(`backend/app/domain/repair_request.py`), the ONLY place in the codebase
that knows this convention exists. `RepairRequestService.create()` is the
sole encoder (validates the named `FINDING`/`PM_RESULT` source actually
exists, the same way `RepairService._validate_source` already does for a
direct Maintenance-opened Repair); `get()`/`list_pending()`/`convert()`'s
initial read are the sole decoders — every `RepairRequest` any other
module sees already has clean `note_th` plus decoded
`source_type`/`source_id` domain-only fields (schema unchanged — 16
columns, exactly as given). Collision-safety: the pattern is anchored at
position 0 and requires the literal `[[SRC:` prefix; no real Thai/English
symptom note starts this way — proven by
`test_repair_request_provenance_encoding.py`'s round-trip and
non-collision cases (including a plain note that happens to *contain*
`[[SRC:...]]` mid-string, and a malformed/truncated marker). Survives
conversion: `mark_repair_request_converted` never touches `note_th`, so
the original Finding/PM Work Result stays discoverable by following
`Repair.source_id` → `GET /repair-requests/{id}` → decoded
`source_type`/`source_id`, exactly matching section 9's separate,
still-true rule that the Repair's OWN `source_type`/`source_id` stays
`REPAIR_REQUEST`/`<repair_request_id>` (never silently rewritten to the
transitive Finding/PM source).

Evidence: `backend/tests/test_repair_request_provenance_encoding.py` (6
unit tests on the pure functions) +
`backend/tests/test_defect_provenance.py` (8 tests: Finding→Request,
Request→RPR retains Finding provenance, PM→Request, Request→RPR retains
PM provenance, unknown-source rejected ×2, user-note-preserved,
never-grants-implicit-RPR-authority).

### PM defect frontend flow (section 16)

**Before**: no UI affordance existed for a non-Maintenance PM technician
to report a PM defect via Repair Request.

**Correction (smallest safe addition)**: `PmWorkOrderDetailPage.tsx`
shows a "แจ้งซ่อม (พบข้อบกพร่องระหว่าง PM)" button next to any task that
already has a submitted result, gated on `can_report_repair` and
`asset_type === 'VEHICLE'` (Repair Request has no equipment column — the
same constraint `RepairCreatePage.tsx` already follows). It opens an
inline symptom textarea and posts to `/repair-requests` with
`source_type=PM_RESULT`, `source_id=<pm_work_result_id>` — never
`/repairs`, never creates an RPR, vehicle context (`asset_id`) preserved
automatically. No PM screen redesign; the existing task-result cards,
scope UI, and close flow are unchanged.

Evidence: new Vitest case in `PmWorkOrderDetailPage.test.tsx`
("lets a technician with can_report_repair report a PM defect via Repair
Request, preserving PM provenance") — asserts the POST body's
`source_type`/`source_id`/`vehicle_id`, that `/repairs` is never called,
and the confirmation UI shows the returned `repair_request_id`.

### PM My Work (section 18)

**Before**: `GET /repairs/my-work` (Repair My Work) existed; no PM
equivalent did.

**Correction**: `PmWorkOrderSummary` gained `primary_technician`/
`collaborators` (mirroring `RepairSummary`); `list_pm_work_orders` gained
an `assigned_to` filter (Mock repository implements the filter; the
Google Sheets stub signature was extended to match the interface — PM
remains an honest, documented Sheets stub, out of REV06's P0 scope, which
was Repair only). New route `GET /pm/work-orders/my-work`
(`status=OPEN`, `assigned_to=<current actor>`) — structurally identical
derivation to Repair My Work, no new table/status/source field. Frontend:
`MyWorkPage.tsx` gained a second "ใบสั่งงาน PM" table below the existing
Repair one (same page, not a new screen), fetching the new endpoint.

Evidence: `backend/tests/test_pm_my_work.py` (6 tests: assigned
primary/collaborator sees it, unrelated/unassigned technician does not,
closed work order drops out, reassignment moves it between technicians)
+ `frontend/src/pages/MyWorkPage.test.tsx` (new file — both sections
render with live data).

## REV06.2 GOOGLE SHEETS METHOD INVENTORY (HONEST, REV06 FINAL)

Classification: **REAL** (genuine Sheets I/O via `GoogleSheetsClient`),
**STUB** (`NotImplementedError`, declared schema only),
**NOT_REQUIRED_FOR_CURRENT_REV** (out of REV06's scope; unchanged from
REV05). No method is marked REAL merely because a schema/generic helper
exists — only because the actual domain path performs functioning I/O
(verified by the FAKE-client test suite, never the real Google API).

| Area | Method | Sheet | R/A/U | Status | Notes |
|---|---|---|---|---|---|
| Vehicle | `get_vehicle_model` | vehicle_model | R | REAL | unchanged from REV05 |
| Vehicle | `list_vehicle_models` | vehicle_model | R | STUB | unchanged |
| Vehicle | `get_vehicle` | vehicle_master | R | REAL | unchanged |
| Vehicle | `list_vehicles` | vehicle_master | R | STUB | unchanged |
| Vehicle | `update_vehicle_machine_no` | vehicle_master | U | STUB | unchanged |
| Vehicle | `list_vehicle_components` | vehicle_component | R | **REAL (REV06, new)** | required by CORE-G01 automatic snapshot for every VEHICLE Repair/Repair Request |
| Vehicle | `list_vehicle_status_history` / `change_vehicle_status` | vehicle_status_history | R/A | STUB | unchanged |
| Snapshot | `create_meter_snapshot` / `get_meter_snapshot` / `list_meter_snapshots_for_asset` | meter_snapshot, meter_reading | A/R/R | REAL | unchanged from REV05 |
| Snapshot | `create_location_snapshot` / `get_location_snapshot` / `list_location_snapshots_for_event` | location_snapshot | A/R/R | REAL | unchanged |
| Inspection | item master, header, result, finding (all) | checklist_revision, inspection*, inspection_finding | R/A | STUB | unchanged — out of REV06 scope |
| Repair Request | `create_repair_request` / `get_repair_request` / `list_pending_repair_requests` / `mark_repair_request_converted` | repair_request | A/R/R/U | REAL | unchanged; now actually reachable end-to-end since `create_repair` downstream is real |
| Repair | `create_repair` | repair_order | A | **REAL (REV06)** | was STUB |
| Repair | `get_repair` | repair_order + repair_action + repair_part | R | **REAL (REV06)** | was STUB |
| Repair | `list_repairs` | repair_order + repair_action | R | **REAL (REV06)** | was STUB; supports asset/status/assigned_to/unassigned_only filters |
| Repair | `assign_repair` / `list_repair_assignment_history` | repair_order + repair_assignment | U/A/R | **REAL (REV06)** | was STUB; non-destructive reassignment (ends previous active rows, never deletes) |
| Repair | `add_repair_action` | repair_action | A | **REAL (REV06)** | was STUB; append-only |
| Repair | `add_repair_part` | repair_part | A | **REAL (REV06)** | was STUB |
| Repair | `close_repair` | repair_order | U | **REAL (REV06)** | was STUB; single-row update only |
| Attachment | `create_attachment` / `get_attachment` / `list_attachments_for_source` | attachment | A/R/R | REAL | unchanged from REV05; REV06 added authorization in front of it (service layer, not repository) |
| PM | plan/task master, work order, scope, assignment, result, used part (all) | pm_plan (partial), pm_task_revision, pm_work_order, pm_work_scope, pm_work_assignment, pm_work_result | R/A/U | STUB (`get_pm_plan` REAL) | unchanged — genuinely out of REV06's P0 scope (only the Repair conversion path was audited P0); `list_pm_work_orders`'s signature was extended with `assigned_to` for interface symmetry with `list_repairs`, still raises `NotImplementedError` |
| Material request | header + lines (all) | material_request, material_request_line | A/R | REAL | unchanged from REV05 |
| Equipment | `get_equipment` / `change_equipment_status` / `list_equipment_status_history` | equipment_master, equipment_status_history | R/U/A/R | REAL | unchanged |
| Equipment | `list_equipment` | equipment_master | R | STUB | unchanged |
| Part/lifetime | all Part Master/Set/Instance/Lifecycle/Position-Lifetime/Lifetime-Rule methods | part_master, part_sets, part_instances, part_lifecycles, installation_segments, position_lifetime_records, lifetime_rules | — | STUB | unchanged — out of REV06 scope (Phase 5, not audited P0/P1) |

REV06 made **8 previously-stubbed Repair methods real** plus
**1 previously-stubbed Vehicle method real** (`list_vehicle_components`,
required transitively). No other area's classification changed.

## REV06.3 SECURITY VERIFICATION

- **Dev auth default**: `dev_auth_mode` defaults to `False`
  (`backend/app/config.py`). Verified: `test_dev_auth_mode_defaults_to_false`.
- **Environment guard**: `dev_auth_effective` requires BOTH the flag AND
  a recognized environment (`development`/`local`/`test`, case-
  insensitive); `app.main.create_app` refuses to start when the flag is
  `True` outside a recognized environment (generalized from the old
  production-only check). Verified:
  `test_dev_auth_mode_true_outside_recognized_environment_refuses_to_start`
  (parametrized over production/staging/prod/typo/case variants).
- **Repair work authorization**: `POST /repairs/{id}/actions` and
  `/parts` require active PRIMARY/COLLABORATOR or `can_manage_repair`.
  Verified in both Mock and Google-Sheets-backed-assignment modes.
- **PM result authorization**: `POST /pm/work-orders/{id}/results`
  requires active PRIMARY/COLLABORATOR or `can_manage_pm`. Verified.
- **Attachment source validation**: `source_id` existence + owner/
  Maintenance authorization enforced for the one currently-supported
  source type (`REPAIR_REQUEST`); every other named source_type is
  refused outright (422) rather than silently accepted un-validated.
  Verified.
- **Reporter override restrictions**: `reporter_type`/
  `reporter_driver_id`/`reporter_name_snapshot_th` are silently ignored
  from any actor without `can_manage_repair`; true reporter identity is
  always backend-derived (`context.user_id`). Verified.

## REV06.4 TRACEABILITY VERIFICATION

**Inspection**: `Finding` (`FND-xxxx`) → `Repair Request`
(`source_type="FINDING"`, `source_id=<finding_id>`, encoded in `note_th`
via `[[SRC:FINDING:<id>]]`) → Maintenance `convert()` → `Repair`
(`source_type="REPAIR_REQUEST"`, `source_id=<repair_request_id>`); the
Finding is still recoverable by re-reading the Repair Request
(`source_type`/`source_id` decoded on every `GET`). Direct Maintenance
path (`Finding` → RPR with `source_type="FINDING"` directly) is
unchanged and still passes (`test_repair_api.py`).

**PM**: `PM Work Order`/`PM Task Result` (`PMWR-xxxx`) → `Repair Request`
(`source_type="PM_RESULT"`, `source_id=<pm_work_result_id>`) →
Maintenance `convert()` → `Repair`
(`source_type="REPAIR_REQUEST"`, `source_id=<repair_request_id>`); the PM
Result is recoverable the same way. Direct Maintenance path (`PM_RESULT`
→ RPR directly) unchanged and still passes.

## REV06.5 TEST RESULTS

- **Backend pytest**: 366 passed (290 REV05 baseline + 76 new REV06
  tests), 0 failed. Ran the full suite after every individual change, not
  only at the end.
- **Frontend typecheck**: PASS (`tsc -b`, part of `npm run build`).
- **Frontend lint**: PASS (`oxlint`, exit 0 — pre-existing
  `set-state-in-effect` style warnings only, same pattern already present
  in every other page in this codebase; 0 errors).
- **Frontend Vitest**: 54 passed (52 REV05 baseline + 2 new files), 0
  failed.
- **Frontend build**: PASS (`vite build`).
- **E2E — Playwright, all 5 viewport projects**: 135 passed, 0 failed, on
  the first clean run (`npx playwright test`) — no flake observed, no
  re-run needed.

## REV06.6 LIVE GOOGLE SHEETS ACCEPTANCE

`LIVE GOOGLE SHEETS ACCEPTANCE: PENDING`

No credentialed test against an approved non-production test/copy
spreadsheet was executed this session (no
`GOOGLE_APPLICATION_CREDENTIALS` service-account key is available in this
sandboxed environment, matching REV05's own finding). All Google Sheets
coverage above (REV06.2/9 tests, 20 total across
`test_google_sheets_real_io.py` + `test_google_sheets_repair_real_io.py`)
runs against the FAKE in-memory `gspread`-shaped client
(`FakeWorksheet`/`FakeSpreadsheet`), which proves the mapping/engine
logic (header-name mapping, append vs. targeted single-row update,
append-only history, null-preserving reads) but is explicitly NOT live
acceptance. Never wrote to the real `MAINTENANCE` business spreadsheet.

## REV06.7 OPEN DECISIONS PRESERVED (NOT SILENTLY FINALIZED)

Unchanged from REV05 — none were touched or resolved this delta:
F01 (Repair lifecycle), F02 (Finding-to-Repair one-to-one/dedup), F03
(Repair closure requirements), M02 (final permission matrix/data-scope
model — REV06's attachment/assignment authorization is explicitly "the
minimum safe owner/manager model," not M02's resolution), Repair Request
reject/cancel/duplicate statuses, final role/screen matrix, Store/
material lifecycle, PM E01/E02/E03, Inspection D01-D04, part/lifetime
G-series, Phase 6 notification delivery, real model→PM Plan mapping, and
B03 (no live Google credential supplied/verified this session either).

## REV06.8 REMAINING GAPS (HONEST, NOT HIDDEN)

- **P2 / deferred**: PM Google Sheets I/O remains entirely stubbed
  (plan/task revision, work order, scope, assignment, result) —
  genuinely out of REV06's audited P0/P1 scope (only the Repair
  conversion path was named P0); a future delta doing PM-in-Sheets should
  reuse the exact same pattern this delta used for Repair.
- **P2**: Inspection, Part/Lifetime/Transfer, and most Vehicle/Equipment
  list methods remain Google Sheets stubs — unchanged from REV05, not
  audited as REV06 gaps.
- **Deferred governance**: live credentialed Google Sheets acceptance
  remains PENDING (no safe test/copy spreadsheet credential available in
  this environment) — see REV06.6.
- **Deferred governance**: attachment data-scope beyond the "reporter or
  Maintenance" minimum-safe model for `REPAIR_REQUEST` remains an open
  decision (M02); extending source-type support beyond `REPAIR_REQUEST`
  needs the same explicit, narrow treatment this delta gave that one
  type, not a blanket policy.
- **No merge to `main` occurred.** All REV06 work lives on
  `web/core-demo-fixes` only.

## REV06.9 FILES CHANGED

| File | Purpose | Key change |
|---|---|---|
| `backend/app/config.py` | Settings | `dev_auth_mode` default False; `is_recognized_dev_environment`/`dev_auth_effective` |
| `backend/app/context.py` | Request context middleware | uses `dev_auth_effective` instead of raw flag |
| `backend/app/main.py` | App factory | startup guard generalized beyond `is_production` |
| `backend/app/domain/authz.py` | Authorization | `require_assignment_or_capability` |
| `backend/app/domain/attachment_service.py` | Attachment domain | `authorize_source` |
| `backend/app/domain/inspection_service.py` | Attachment boundary | threads `context` through upload/list-by-source |
| `backend/app/domain/repair_request.py` | Repair Request domain | `encode_provenance_note`/`decode_provenance_note`, `source_type`/`source_id` domain fields |
| `backend/app/domain/repair_request_service.py` | Repair Request service | defect-source validation, provenance encode/decode, `_with_decoded_provenance` |
| `backend/app/domain/pm.py` | PM domain | `PmWorkOrderSummary.primary_technician`/`collaborators` |
| `backend/app/domain/pm_service.py` | PM service | `list_work_orders(assigned_to=...)` |
| `backend/app/api/v1/repairs.py` | Repair routes | assignment-or-capability gate on actions/parts |
| `backend/app/api/v1/pm.py` | PM routes | assignment-or-capability gate on results; `GET /pm/work-orders/my-work` |
| `backend/app/api/v1/pm_schemas.py` | PM schemas | summary response gains technician fields |
| `backend/app/api/v1/repair_requests.py` | Repair Request routes | reporter-override restriction; source_type/id passthrough |
| `backend/app/api/v1/repair_request_schemas.py` | Repair Request schemas | `source_type`/`source_id` request+response fields |
| `backend/app/api/v1/inspections.py` | Attachment routes | passes `context` for source authorization |
| `backend/app/repositories/base.py` | Repository interface | `list_pm_work_orders(assigned_to=...)` |
| `backend/app/repositories/mock/repository.py` | Mock repository | PM `assigned_to` filter + summary fields |
| `backend/app/repositories/google_sheets/repository.py` | Google Sheets repository | real Repair CRUD (8 methods) + `list_vehicle_components` |
| `backend/tests/test_core_demo_fixes_delta_rev05.py` | REV05 regression | one test updated for the new PM assignment requirement |
| `backend/tests/test_dev_auth_fail_closed.py` | New | dev-auth fail-closed (14 tests) |
| `backend/tests/test_google_sheets_repair_real_io.py` | New | real Sheets Repair I/O + conversion (14 tests) |
| `backend/tests/test_attachment_source_authorization.py` | New | attachment security (9 tests) |
| `backend/tests/test_repair_request_provenance_encoding.py` | New | provenance marker unit tests (6 tests) |
| `backend/tests/test_defect_provenance.py` | New | Finding/PM provenance through conversion (8 tests) |
| `backend/tests/test_pm_my_work.py` | New | PM My Work (6 tests) |
| `backend/tests/test_repair_pm_work_authorization.py` | New | Repair/PM assignment authorization (14 tests) |
| `backend/tests/test_rev06_identity_and_core_g01_regression.py` | New | identity/CORE-G01 regression (5 tests) |
| `frontend/src/lib/types.ts` | Types | `PmWorkOrderSummary` technician fields; `RepairRequest.source_type/id` |
| `frontend/src/pages/MyWorkPage.tsx` | Frontend | PM My Work section added |
| `frontend/src/pages/MyWorkPage.test.tsx` | New | covers both sections |
| `frontend/src/pages/PmWorkOrderDetailPage.tsx` | Frontend | PM-defect-to-Repair-Request inline flow |
| `frontend/src/pages/PmWorkOrderDetailPage.test.tsx` | Frontend | new defect-report test |

## REV06.10 GIT STATE

- Branch: `web/core-demo-fixes`
- Starting HEAD: `d80eedda94fb144ebccf95822762de46c48da441`
- Ending HEAD / commits: see the commit(s) immediately following this
  report in `git log`
- Working tree: clean after commit
- Remote: pushed to `origin/web/core-demo-fixes`
- **Not merged to `main`.**

# DELTA REV06.1 — Independent REV06 Audit Residual Findings

PHASE: strict security/integrity delta fix only, scoped exclusively to
the findings named by an independent REV06 acceptance audit
(verdict: "REV06 REQUIRES DELTA FIX"). Not a redesign, not a new phase,
no PM/Inspection Google Sheets I/O added, no governance decisions
resolved, no merge to `main`.
STATUS: PASS

## REV06.1.1 AUDIT FINDINGS ADDRESSED

The independent audit confirmed REV06's P0 fixes (Google Sheets Repair
conversion, dev-auth fail-closed) and most P1 authorization work were
genuinely correct, but found two residual **CRITICAL** findings and two
disclosed lower-severity consistency risks in exactly the areas REV06
touched:

1. **CRITICAL — unauthorized attachment file download.** REV06 added
   `AttachmentService.authorize_source` in front of `POST /attachments`
   and `GET /attachments/by-source/{type}/{id}`, but never wired it into
   `GET /attachments/{attachment_id}/file` — the one route that actually
   returns file *content*. Attachment ids are sequentially enumerable
   (`ATT-0001`, `ATT-0002`, ...), so possession of an id (guessed or
   incremented) was sufficient to download any attachment's bytes.
2. **CRITICAL — Repair Request provenance spoofable.** REV06 encodes an
   originating Finding/PM Work Result into `note_th` via a
   `[[SRC:TYPE:ID]]` marker, validated by
   `RepairRequestService._require_defect_source_exists` — but only when
   the client explicitly sends a `source_type` field. When a client
   omits it (the ordinary path), `encode_provenance_note` was a true
   no-op, so an unprivileged `can_report_repair` actor could submit
   `note_th` already shaped like `[[SRC:FINDING:<anything>]]` and have it
   decode back on every later read as validated system provenance — the
   audit reproduced this against a nonexistent Finding id.
3. **Disclosed, lower severity — conversion partial-failure duplicate
   risk.** `RepairRequestService.convert()`'s two writes
   (`create_repair` then `mark_repair_request_converted`) are not
   transactional on Google Sheets; a failure between them could leave
   `request_status=PENDING` with a Repair already created, and a naive
   retry would create a second one.
4. **Disclosed, lower severity — assignment split-brain risk.**
   `assign_repair` writes `repair_assignment` history, then separately
   updates the denormalized `Repair.primary_technician`/`.collaborators`
   fields that `require_assignment_or_capability` used for
   authorization; a failure between the two writes could leave that
   authorization check reading a stale assignee.

## REV06.1.2 FIX 1 — ATTACHMENT DOWNLOAD AUTHORIZATION

`InspectionService.require_readable_attachment(attachment_id, context)`
(new) fetches the attachment, then runs the exact same
`AttachmentService.authorize_source` gate as upload/list — keyed off the
attachment's own recorded `source_type`/`source_id`, never client input —
before any byte is read from storage. `GET /attachments/{attachment_id}/file`
now depends on `RequestContext` and calls this instead of the old,
unauthorized `require_attachment`. No second, divergent authorization
helper was introduced — this is the same policy as create/list, applied
consistently.

**Precise, non-overclaimed guarantee**: for attachments whose
`source_type="REPAIR_REQUEST"` (the only join type this mechanism backs),
download now requires being the Repair Request's own reporter or holding
`can_manage_repair` — identical to create/list. For every attachment
purpose that predates this join (checklist reference image,
inspection/PM/repair evidence — the majority, which link back via their
owner's own `attachment_ids` field instead), `authorize_source` remains a
no-op and download is unchanged from before REV06.1 — this fix does not
invent a new authorization policy for those, per the audit's own
instruction to use the narrowest currently-approved safe behavior and not
widen scope. **We do not claim "attachments are secure"** — we claim
create, list, and download are now consistently gated for
`REPAIR_REQUEST`-sourced attachments specifically.

Tests: `backend/tests/test_rev061_attachment_download_authorization.py`
(8 tests) — nonexistent attachment denied, unrelated reporter denied,
sequential-id guessing does not bypass, owning reporter allowed,
Maintenance allowed, listing/download authorization proven consistent,
authorization proven to run before any storage read (via a monkeypatch
that fails the test if storage is ever reached on a denied request), and
the no-source path proven unchanged.

## REV06.1.3 FIX 2 — PROVENANCE SPOOF PREVENTION

`app.domain.repair_request.encode_provenance_note`/`decode_provenance_note`
now treat every not-yet-validated note as adversarial input:
`_escape_untrusted_note`/`_unescape_untrusted_note` neutralize (with a
single reversible backslash-style escape) any raw, client-supplied note
that would otherwise collide with the `[[SRC:TYPE:ID]]` marker format
*before* it is ever persisted — so the only way a persisted `note_th` can
ever decode as provenance is for this module's own trusted-source branch
(which always runs `_require_defect_source_exists` first) to have built
it. The escape is exactly reversible: even in this adversarial edge case,
the reporter's own text — marker-shaped or not — still comes back
byte-for-byte identical to what they typed; it is simply never
*interpreted* as machine metadata.

**Precise, non-overclaimed guarantee**: **we do not claim "provenance is
tamper-proof" in a cryptographic sense** — there is no signature or
server secret involved, by design, per the audit's own steer toward "a
safe schema-compatible deterministic separation" over unnecessary new
infrastructure. What we do guarantee: no client-supplied `note_th` text,
however constructed, can ever decode as `source_type`/`source_id` — that
only happens for text this module itself built after independently
validating the named Finding/PM Work Result exists.

**Legacy REV06 rows**: any `repair_request` row created between REV06's
ship date and this fix, whose `note_th` decodes as provenance, cannot be
algorithmically distinguished by this module from a row where an
ordinary reporter happened to type marker-shaped text before this
escaping existed (the fixed 16-column schema has no column recording
whether validation actually ran). Documented in code
(`app/domain/repair_request.py` module docstring) as:
**`LEGACY REV06 NOTE MARKER IS UNTRUSTED FOR AUTHORITY`** — treat any
pre-fix row's decoded source as informational only unless corroborated
by other trusted state (e.g. the named record still exists).

Tests: `backend/tests/test_rev061_provenance_spoofing_prevention.py`
(17 tests) — unit-level adversarial inputs (plain marker, marker with
Thai text following, multiple markers, malformed marker, marker
mid-text, nested brackets, newline-before-marker, Thai/Unicode notes,
multiline notes, empty/null notes) all proven to round-trip exactly
without ever decoding as provenance; trusted-path round-trip and
re-encode-does-not-duplicate regression checks; and two integration
tests posting directly to `POST /repair-requests` as a Driver with a
hand-crafted spoofed marker (naming both a nonexistent Finding and a
real-shaped `PM_RESULT` id) proving `source_type`/`source_id` come back
`None` while the reporter's original text is preserved verbatim; plus a
sanity check that the legitimate, validated Finding path still works.

## REV06.1.4 FIX 3 — CONVERSION PARTIAL-FAILURE RECOVERY (disclosed risk, hardened)

New `Repository.find_repairs_by_source(source_type, source_id)`
(implemented in both `MockRepository` and `GoogleSheetsRepository`).
`RepairRequestService.convert()` now checks for an existing Repair linked
by `source_type=REPAIR_REQUEST, source_id=repair_request_id` before
creating one:

```
request = get(repair_request_id)
if request.request_status == CONVERTED:
    return get_repair(request.repair_id)          # unchanged fast path

existing = find_repairs_by_source(REPAIR_REQUEST, repair_request_id)
if len(existing) > 1:
    raise REPAIR_REQUEST_CONVERSION_INTEGRITY_ERROR  # refuse a 3rd repair
detail = get_repair(existing[0].repair_id) if existing else create_repair(...)
mark_repair_request_converted(repair_id=detail.repair.repair_id, ...)
return detail
```

- Zero existing repairs -> create as before.
- Exactly one existing repair (the interrupted-retry case the audit
  described) -> reuse it and finish the linkage write that never
  committed the first time.
- More than one (a worse, already-corrupted historical state) -> refuse
  to create a third and raise `REPAIR_REQUEST_CONVERSION_INTEGRITY_ERROR`
  (500) naming every linked repair id, for manual reconciliation.

**We do not claim transactional safety** — Google Sheets has none, and
this delta does not simulate it. What changed: a retry after the
specific partial-failure window the audit identified is now naturally
idempotent instead of creating a duplicate RPR. A residual, much smaller
window remains (a failure during the recovery's own
`mark_repair_request_converted` call could still require one more retry,
which is itself now safe by the same logic) — disclosed, not eliminated.

Tests: `backend/tests/test_rev061_conversion_recovery.py` (4 tests),
run against the same fake in-memory `gspread`-shaped client as
`test_google_sheets_repair_real_io.py` (Sheets-mode, not just Mock) —
partial-failure-then-retry reuses the orphaned repair and completes
linkage; already-converted retry remains idempotent (regression); two
pre-existing repairs for one request raise the integrity error without
creating a third; a Repair Request that never existed leaves nothing
converted.

## REV06.1.5 FIX 4 — ASSIGNMENT AUTHORITY CLARIFICATION (disclosed risk, hardened)

New `RepairService.get_active_assignment(repair_id)` derives
`(primary_technician, collaborators)` from the append-only
`repair_assignment` history's currently-active rows. `POST
/repairs/{id}/actions` and `POST /repairs/{id}/parts` now call this
instead of reading `Repair.primary_technician`/`.collaborators`
directly, before calling `require_assignment_or_capability`.

**Authoritative source, stated explicitly**: `repair_assignment` history
is authoritative for who is actively assigned; `Repair.primary_technician`/
`.collaborators` are compatibility/denormalized display fields only,
kept in sync by `assign_repair` but never again consulted for an
authorization decision. This closes the split-brain risk for
authorization: a failure between `assign_repair`'s two writes can no
longer let a stale or missing denormalized value authorize (or
wrongly deny) an actor.

**Scope of this fix, stated explicitly (not expanded further)**: Waiting
Assignment (`GET /repairs/waiting-assignment`) and My Work (`GET
/repairs/my-work`, `GET /pm/work-orders/my-work`) continue to read the
denormalized fields, not assignment history — these are read-only
listing/aggregation queries kept in sync by the same `assign_repair`
call in the same request, so their staleness window is identical to any
other non-transactional Sheets write; converting every listing query to
join against assignment history per-repair would be a materially larger
change (an N+1 read pattern against Google Sheets) than this delta's
scope allows. The security-critical path — who may actually record work
against a specific occurrence — is what was moved to history; the
lower-stakes display/listing path was not, and is documented here rather
than silently left inconsistent.

Tests: `backend/tests/test_rev061_assignment_authority.py` (9 tests) —
reassignment ends old PRIMARY/preserves history, exactly one active
PRIMARY, collaborator unaffected by PRIMARY reassignment, an ended
PRIMARY is denied and the new one is allowed (real HTTP), a stale
denormalized assignee alone cannot authorize (Mock, by directly
corrupting the denormalized field while history stays correct), a
missing/`None` denormalized field does not break authorization, Waiting
Assignment/My Work regression checks, and the same stale-denormalized-
cannot-authorize proof repeated against the real (fake-Sheets-backed)
`GoogleSheetsRepository` — the split-brain is a Sheets-mode-specific risk
(two separate writes), so the fix is proven there too, not only in Mock.

## REV06.1.6 UNCHANGED / OUT OF SCOPE (BY DESIGN)

Per the REV06.1 task scope, none of the following were touched:
- PM Google Sheets I/O remains entirely stubbed (unchanged from REV06;
  `PM My Work` and PM task-result authorization remain Mock-only in
  practice — REV06.1 did not implement PM Sheets I/O).
- Inspection/Part/Lifetime Google Sheets I/O remains stubbed (unchanged).
- No open governance decision (F01-F03, M02, role/screen matrix, data
  scope, etc. — see REV06.7 above) was resolved.
- No new business status/table was introduced (`waiting_assignment`,
  `waiting_parts`, `technician_master`, etc. all remain absent — see the
  REV06 forbidden-architecture search, re-confirmed unchanged by this
  delta since no new persisted concept was added anywhere in it).
- `LIVE GOOGLE SHEETS ACCEPTANCE: PENDING` — unchanged; no credentialed
  Google API call was made this session either. FakeSpreadsheet/
  FakeWorksheet tests (used throughout REV06.1's Sheets-mode tests) are
  explicitly not live acceptance evidence.

## REV06.1.7 TEST RESULTS

Baseline (REV06, commit `2bee6b5`, independently reproduced before this
delta's changes): backend 366 passed; frontend typecheck/lint/build
PASS, Vitest 54 passed; E2E 135 passed.

After this delta:
- Backend: `python -m pytest -q` → **404 passed** (366 baseline + 38 new:
  8 attachment-download + 17 provenance-spoofing + 4 conversion-recovery
  + 9 assignment-authority), 0 failed.
- Frontend: `tsc -b --noEmit` → PASS (0 errors). `oxlint` → PASS (only
  pre-existing warnings, 0 errors). `vitest run` → **54 passed**
  (26 files, unchanged — this delta is backend-only). `vite build` →
  PASS.
- E2E: `playwright test` (all 5 configured viewports) → **135 passed**
  (unchanged — this delta does not touch any user-facing flow the E2E
  suite exercises).

No existing test was weakened, skipped, or had its assertion loosened to
make this delta pass.

## REV06.1.8 FILES CHANGED

| File | Purpose | Key change |
|---|---|---|
| `backend/app/domain/repair_request.py` | Repair Request domain | `_escape_untrusted_note`/`_unescape_untrusted_note`; `encode_provenance_note` no longer a true no-op |
| `backend/app/domain/inspection_service.py` | Attachment boundary | `require_readable_attachment(attachment_id, context)` |
| `backend/app/api/v1/inspections.py` | Attachment routes | download route now requires `RequestContext` and calls `require_readable_attachment` |
| `backend/app/repositories/base.py` | Repository interface | `find_repairs_by_source(source_type, source_id)` |
| `backend/app/repositories/mock/repository.py` | Mock repository | `find_repairs_by_source` implementation |
| `backend/app/repositories/google_sheets/repository.py` | Google Sheets repository | `find_repairs_by_source` implementation |
| `backend/app/domain/repair_request_service.py` | Repair Request service | `convert()` recovery/integrity-check logic |
| `backend/app/domain/repair_service.py` | Repair service | `get_active_assignment(repair_id)` |
| `backend/app/api/v1/repairs.py` | Repair routes | action/part authorization sourced from `get_active_assignment` |
| `backend/tests/test_rev061_attachment_download_authorization.py` | New | 8 tests |
| `backend/tests/test_rev061_provenance_spoofing_prevention.py` | New | 17 tests |
| `backend/tests/test_rev061_conversion_recovery.py` | New | 4 tests |
| `backend/tests/test_rev061_assignment_authority.py` | New | 9 tests |
| `docs/phase-results/core-demo-fixes-result.md` | Documentation | this section |

## REV06.1.9 GIT STATE

- Branch: `web/core-demo-fixes`
- Starting HEAD (audited REV06 HEAD): `2bee6b5`
- Implementation commit: `5aefc09` ("Fix REV06 audit security and
  integrity gaps") — the commit this documentation section describes
- Ending HEAD: this documentation commit, immediately following
  `5aefc09`
- Working tree: clean after commit
- Remote: pushed to `origin/web/core-demo-fixes`
- **Not merged to `main`. No history rewritten (other than amending this
  delta's own not-yet-pushed implementation commit once, to add the
  required attribution footer, before any push occurred). No
  force-push.**

## REV06.1.10 REMAINING RISKS (SEPARATED BY CLASS)

- **Actual bug, now fixed**: attachment download IDOR; provenance
  spoofing via unvalidated `note_th`.
- **Residual non-transactional-Sheets risk (disclosed, narrowed, not
  eliminated)**: conversion recovery still has a (much smaller) window
  if the recovery's own linkage write itself fails — a further retry is
  safe by the same logic, so this degrades to "may need more than one
  retry," never "creates a duplicate." `_next_id`'s read-then-append
  pattern remains a pre-existing, accepted concurrent-write race
  (unchanged by this delta).
- **Out-of-scope repository stub (disclosed, unchanged)**: PM/
  Inspection/Part/Lifetime Google Sheets I/O.
- **Governance decision (intentionally left open)**: attachment
  data-scope beyond "reporter or Maintenance" for `REPAIR_REQUEST`;
  final Repair/PM permission matrix (M02); everything listed in
  REV06.7.

# DELTA REV06.2 — Independent REV06.1 Audit Final Findings

The REV06.1 acceptance audit (verdict: `REV06.1 REQUIRES DELTA FIX`)
confirmed provenance security, conversion retry safety, and Repair
action/part authorization as PASS, and found exactly two remaining gaps:
a HIGH-severity attachment download authorization gap (only
`REPAIR_REQUEST_EVIDENCE` was actually gated — every other purpose fell
through `authorize_source`'s no-op branch since it carried no
`source_type`/`source_id` at all) and a MEDIUM-severity queue-derivation
defect (Waiting Assignment/My Work still read the denormalized
`Repair.primary_technician`/`.collaborators` fields instead of active
assignment history). This delta closes both. No already-PASSing area
(provenance, conversion recovery, Repair action/part authorization itself,
DEV_AUTH fail-closed, PM defect/My Work logic) was touched beyond a
docstring update.

## REV06.2.1 FIX 1 — ATTACHMENT DOWNLOAD AUTHORIZATION, EVERY PURPOSE

`AttachmentService.authorize_source` now takes the attachment's `purpose`
in addition to `source_type`/`source_id`, and every purpose either
resolves a real owning record and authorizes against it, or is refused:

| Purpose | Owning source | Persisted at | Authorization |
|---|---|---|---|
| `REPAIR_REQUEST_EVIDENCE` | Repair Request | upload time (REV05, unchanged) | reporter or `can_manage_repair` |
| `REPAIR_EVIDENCE` | Repair (`source_type=REPAIR`) | upload time (new) | active PRIMARY/COLLABORATOR (history, via `active_primary_and_collaborators`) or `can_manage_repair` — the exact same gate `add_repair_action`/`add_repair_part` already enforce |
| `PM_EVIDENCE` | PM Work Order (`source_type=PM_WORK_ORDER`) | upload time (new) | assigned PRIMARY/COLLABORATOR or `can_manage_pm` — the exact same gate `submit_pm_task_result` already enforces (PM's own denormalized-vs-history question is unrelated REV06.1 CONSISTENCY-2 scope for Repair only; PM_EVIDENCE deliberately reuses PM's current policy unchanged) |
| `INSPECTION_EVIDENCE` | the asset being inspected (`source_type=INSPECTION_VEHICLE`/`INSPECTION_EQUIPMENT`) | upload time (new) | `can_record_inspection` |
| `CHECKLIST_REFERENCE_IMAGE` | none — master/reference content with no per-instance owner, never created through this endpoint in practice | n/a | `can_view` |
| any attachment created before this fix (source-less) | none | n/a | fails closed: `ATTACHMENT_SOURCE_REQUIRED` (403) |

**Why `INSPECTION_EVIDENCE` binds to the asset, not the Inspection**: an
evidence photo is captured while the checklist is still being filled in —
no `Inspection` id exists yet, and the frontend already renders the photo
as a live preview (`<img src>`) immediately after upload, before
submission. Binding to a not-yet-existent Inspection id was not possible;
binding to attachment id/filename/note text was explicitly forbidden by
the audit. The asset being inspected is the one real, durable, explicit
owner available at upload time, and no narrower per-inspection data-scope
model exists in this codebase today (`GET /inspections/{id}` itself has no
additional access gate) — `can_record_inspection` is the narrowest
existing rule, per the audit's own allowance for that case.

**Why `CHECKLIST_REFERENCE_IMAGE` is `can_view`, not fail-closed**: it is
master/reference content (a "what correct looks like" photo attached to a
`ChecklistItem`, not a transactional record), shown to every actor
performing any inspection via `_checklist_item_response` regardless of
role — no upload endpoint in this codebase ever creates one in practice.
No management capability specific to checklist authoring exists to reuse,
and failing it closed would make every checklist item's reference image
disappear for every inspector, for zero security benefit (nothing links
to these attachments except the master `ChecklistItem.
reference_image_attachment_id` field itself). `can_view` still refuses a
context with no recognized role/capabilities at all (the DEV_AUTH
fail-closed case) — "do not leave it globally downloadable merely because
it is a reference image" (audit section 6) is satisfied without breaking
the feature.

**Source is now required, not merely validated, for the three
transactional evidence purposes**: `REPAIR_EVIDENCE`/`PM_EVIDENCE`/
`INSPECTION_EVIDENCE` uploads that omit `source_type`/`source_id` are now
refused (`ATTACHMENT_SOURCE_REQUIRED`, 403) rather than silently accepted
— per audit section 8, ownership must be explicit and durable, never
inferred later. The three frontend upload call sites
(`RepairDetailPage.tsx`, `PmWorkOrderDetailPage.tsx`,
`InspectionFormPage.tsx`) were updated to send it (repair_id/
pm_work_order_id/asset_id are all already in scope at upload time).

**Create/list/download consistency**: since all three new source types
route through the same `authorize_source` call already wired into upload,
list-by-source, and download, an actor who cannot access a source cannot
upload to it, list it, or download from it — proven directly for
`REPAIR_EVIDENCE` (`test_repair_evidence_upload_list_and_download_authorization_agree`).

Tests: `backend/tests/test_rev062_attachment_authorization.py` (21 tests)
— per purpose: authorized actor allowed, unrelated actor denied,
Maintenance/can_manage override, guessed-sequential-id enumeration denied,
reassignment revokes/grants access correctly, nonexistent source 404,
missing source 403 `ATTACHMENT_SOURCE_REQUIRED`, mismatched cross-domain
source_type 404, unsupported source_type 422, and (for `REPAIR_EVIDENCE`/
`PM_EVIDENCE`) a monkeypatch proving storage is never read before
authorization succeeds. Plus updates to
`test_attachment_source_authorization.py` (`CHECKLIST_REFERENCE_IMAGE`'s
source-less path now the documented exception; a new
`ATTACHMENT_SOURCE_REQUIRED` case) and
`test_rev061_attachment_download_authorization.py` (the old "unchanged for
every source-less purpose" test replaced with a `CHECKLIST_REFERENCE_IMAGE`-
specific case plus a fail-closed legacy-row case that writes directly
through the repository — bypassing the service layer entirely — to
reproduce the exact shape of a pre-REV06.2 row, and proves storage is
never reached for it either).

## REV06.2.2 FIX 2 — WAITING ASSIGNMENT / MY WORK QUEUE DERIVATION

`Repository.list_repairs`'s `assigned_to`/`unassigned_only` filters (both
`MockRepository` and `GoogleSheetsRepository`) now derive "who is actively
assigned" from active `repair_assignment` history via the same
`active_primary_and_collaborators` helper `RepairService.
get_active_assignment` uses for authorization (extracted to
`app.domain.assignment` so both call sites can never independently drift)
— never the denormalized `Repair.primary_technician`/`.collaborators`
columns, which `assign_repair` writes second, non-transactionally, and
which REV06.1 already proved can go stale relative to history.

**GoogleSheetsRepository avoids N+1**: the fix fetches the entire
`repair_assignment` sheet once per `list_repairs` call (same cost class as
the pre-existing `action_rows` fetch just below it in the same method),
groups rows by `repair_id` in memory, then derives active
PRIMARY/collaborators per repair from that — never one history fetch per
repair in the result set.

Tests: `backend/tests/test_rev062_queue_derivation.py` (9 tests) — the
four required Waiting Assignment scenarios (stale "assigned" field but
ended PRIMARY → still appears; blank field but active PRIMARY → does not
appear; collaborator-only → still appears, since a collaborator is not a
PRIMARY; CLOSED repair → excluded regardless), the corresponding My Work
scenarios (active PRIMARY/collaborator appear despite a blank/wrong
denormalized field; an ended PRIMARY/collaborator does not appear despite
a stale denormalized field naming them), and the same stale-field proof
repeated against the real (fake-Sheets-backed) `GoogleSheetsRepository` —
the split-brain is a Sheets-mode-specific risk (two non-transactional
writes), so the fix is proven there too, not only in Mock.

## REV06.2.3 AUTHORITATIVE DATA SOURCE, STATED EXPLICITLY

`repair_assignment` (active rows) is now authoritative for: active
PRIMARY, active COLLABORATOR, Repair action authorization, Repair part
authorization, Waiting Assignment, and Repair My Work. `Repair.
primary_technician`/`.collaborators` remain in the schema as
denormalized/compatibility/display fields only, kept in sync by
`assign_repair`, and must never by themselves determine assignment
authority or queue membership again.

## REV06.2.4 UNCHANGED / OUT OF SCOPE (BY DESIGN)

- Repair action/part authorization itself (already history-sourced,
  REV06.1) — untouched beyond reusing the same helper function.
- Provenance security, conversion recovery, DEV_AUTH fail-closed — all
  independently verified PASS by the REV06.1 audit; not touched.
- PM My Work / PM task-result authorization logic — unchanged; PM_EVIDENCE
  attachment authorization deliberately reuses PM's own existing
  `primary_technician`/`collaborators`-based policy rather than
  introducing PM-side history sourcing, which was never in this delta's
  scope.
- PM/Inspection/Part/Lifetime Google Sheets I/O remains entirely stubbed
  (unchanged) — **PM My Work works at the domain/API/frontend logic
  level but is NOT operational against real Google Sheets**, since PM
  repository I/O remains mostly stubbed.
- No open governance decision (F01-F03, M02, Repair Request reject/cancel
  lifecycle, Store/material lifecycle, PM E01-E03, Inspection D01-D04,
  part/lifetime G-series, Phase 6 notifications, model→PM Plan mapping)
  was resolved — `git diff` against the governance register is empty for
  this delta.
- No new table/status was introduced (`waiting_assignment`,
  `waiting_parts`, `technician_master`, `driver_repair_order`, etc. all
  remain absent — Waiting Assignment/My Work are still derived, read-only
  views over existing `repair`/`repair_assignment` data, never a new
  stored queue).
- `LIVE GOOGLE SHEETS ACCEPTANCE: PENDING` — unchanged; no credentialed
  Google API call was made this session. Fake in-memory gspread-shaped
  client tests are not live acceptance evidence.

## REV06.2.5 TEST RESULTS

Baseline (REV06.1, commit `f0453c1`, independently reproduced before this
delta's changes): backend 404 passed; frontend typecheck/lint/build PASS,
Vitest 54 passed; E2E 135 passed.

After this delta:
- Backend: `python -m pytest -q` → **436 passed** (404 baseline + 32 new:
  21 attachment-authorization + 9 queue-derivation, plus a net +2 from
  replacing 2 REV06.1 tests whose premise this delta intentionally
  changes with 4 narrower ones), 0 failed.
- Frontend: `tsc -b` → PASS (0 errors). `oxlint` → PASS (21 pre-existing
  warnings, 0 errors — unchanged). `vitest run` → **54 passed** (26
  files, unchanged). `vite build` → PASS.
- E2E: `playwright test` (all 5 configured viewports) → **135 passed**,
  0 failed (unchanged — this delta's frontend changes only add two hidden
  form fields to existing upload calls; no user-facing behavior changed).

No existing test was weakened, skipped, or had its assertion loosened to
make this delta pass; the two REV06.1 tests whose own stated premise
("every source-less purpose remains downloadable to anyone" /
"predating-REV05 purposes never send source, proving the gate is a
no-op") is exactly what this delta fixes were replaced with tests proving
the new, correct behavior instead.

## REV06.2.6 FILES CHANGED

| File | Purpose | Key change |
|---|---|---|
| `backend/app/domain/attachment.py` | Attachment model | `source_type`/`source_id` docstring updated for the new purposes |
| `backend/app/domain/attachment_service.py` | Attachment boundary | `authorize_source` takes `purpose`; REPAIR/PM_WORK_ORDER/INSPECTION_VEHICLE/INSPECTION_EQUIPMENT branches; `ATTACHMENT_SOURCE_REQUIRED`; `CHECKLIST_REFERENCE_IMAGE` `can_view` branch |
| `backend/app/domain/inspection_service.py` | Attachment boundary | the three `authorize_source` call sites now pass `purpose` |
| `backend/app/domain/assignment.py` | Shared assignment helper | `active_primary_and_collaborators(history)` extracted for reuse |
| `backend/app/domain/repair_service.py` | Repair service | `get_active_assignment` now calls the shared helper (no behavior change) |
| `backend/app/repositories/base.py` | Repository interface | `list_repairs` docstring updated |
| `backend/app/repositories/mock/repository.py` | Mock repository | `list_repairs` derives `assigned_to`/`unassigned_only` from assignment history |
| `backend/app/repositories/google_sheets/repository.py` | Google Sheets repository | same fix, one extra sheet fetch (not N+1) |
| `backend/app/api/v1/repairs.py` | Repair routes | docstrings updated for `/repairs/my-work`, `/repairs/waiting-assignment` |
| `frontend/src/pages/RepairDetailPage.tsx` | Repair evidence upload | sends `source_type=REPAIR`, `source_id=repairId` |
| `frontend/src/pages/PmWorkOrderDetailPage.tsx` | PM evidence upload | sends `source_type=PM_WORK_ORDER`, `source_id=workOrderId` |
| `frontend/src/pages/InspectionFormPage.tsx` | Inspection evidence upload | sends `source_type=INSPECTION_VEHICLE`/`INSPECTION_EQUIPMENT`, `source_id=assetId` |
| `backend/tests/test_rev062_attachment_authorization.py` | New | 21 tests |
| `backend/tests/test_rev062_queue_derivation.py` | New | 9 tests |
| `backend/tests/test_attachment_source_authorization.py` | Updated | premise-changed test replaced; new `ATTACHMENT_SOURCE_REQUIRED` case |
| `backend/tests/test_rev061_attachment_download_authorization.py` | Updated | premise-changed test replaced with `CHECKLIST_REFERENCE_IMAGE` + legacy fail-closed cases |
| `backend/tests/test_repair_api.py`, `test_inspections_api.py`, `test_attachment_upload_validation.py` | Updated | existing uploads of now-source-requiring purposes given a valid source |
| `docs/phase-results/core-demo-fixes-result.md` | Documentation | this section |

## REV06.2.7 GIT STATE

- Branch: `web/core-demo-fixes`
- Starting HEAD (audited REV06.1 HEAD): `f0453c1`
- Working tree: clean after commit
- Remote: pushed to `origin/web/core-demo-fixes`
- Not merged to `main`. No history rewritten. No force-push.

## REV06.2.8 REMAINING RISKS (SEPARATED BY CLASS)

- **Actual bug, now fixed**: attachment download authorization gap for
  `REPAIR_EVIDENCE`/`PM_EVIDENCE`/`INSPECTION_EVIDENCE`/
  `CHECKLIST_REFERENCE_IMAGE`; Waiting Assignment/My Work queue-derivation
  split-brain.
- **Residual, disclosed, unavoidable given a non-transactional Sheets
  backend (unchanged from REV06.1)**: a true simultaneous double-submit of
  Repair Request conversion; any window between `assign_repair`'s two
  writes is now invisible to both authorization and queue derivation
  (both read history), so this residual class only affects the
  denormalized display fields themselves, never who may act or which
  queue a repair appears in.
- **Out-of-scope repository stub (disclosed, unchanged)**: PM/Inspection/
  Part/Lifetime Google Sheets I/O; PM's own assignment authorization
  continues to read `PmWorkOrder.primary_technician`/`.collaborators`
  directly (not history) — unrelated to this delta's Repair-only queue
  fix and never in its scope.
- **Governance decision (intentionally left open)**: attachment
  data-scope beyond "reporter/assigned technician or Maintenance";
  `CHECKLIST_REFERENCE_IMAGE`'s authoring/upload path (no runtime create
  flow exists to govern); final Repair/PM permission matrix (M02);
  everything listed in REV06.7.

# DELTA REV06.3 — Independent REV06.2 Audit Final Finding

The REV06.2 acceptance audit found every REV06.2 target area PASS
(REPAIR_EVIDENCE/PM_EVIDENCE/INSPECTION_EVIDENCE authorization, Waiting
Assignment, Repair My Work, Mock/Sheets parity, Repair action/part
authorization regression) except one newly-introduced HIGH finding:
`CHECKLIST_REFERENCE_IMAGE`'s authorization branch returned before any
`source_type`/`source_id` was validated, so a caller could pair
`purpose=CHECKLIST_REFERENCE_IMAGE` with a REAL `source_type`/`source_id`
(e.g. a Repair the caller has no relationship to) and the attachment was
persisted with that real source — bypassing the source's own
authorization gate entirely, then surfacing in that source's own
by-source listing. This delta closes exactly that gap and nothing else.

## REV06.3.1 FIX — CENTRALIZED PURPOSE/SOURCE-TYPE COMPATIBILITY

`AttachmentService.authorize_source` now validates
`_ALLOWED_SOURCE_TYPES_BY_PURPOSE[purpose]` before any purpose-specific
branch (including the `CHECKLIST_REFERENCE_IMAGE` bypass) or source-record
resolution runs:

| Purpose | Allowed source_type(s) | Source required? | Invalid pair behavior |
|---|---|---|---|
| `REPAIR_REQUEST_EVIDENCE` | `REPAIR_REQUEST` | no (unchanged, REV06.1) | 422 `ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE` |
| `REPAIR_EVIDENCE` | `REPAIR` | yes | same |
| `PM_EVIDENCE` | `PM_WORK_ORDER` | yes | same |
| `INSPECTION_EVIDENCE` | `INSPECTION_VEHICLE`, `INSPECTION_EQUIPMENT` | yes | same |
| `CHECKLIST_REFERENCE_IMAGE` | **none — must be source-less** | n/a (always source-less) | same |

`CHECKLIST_REFERENCE_IMAGE` maps to an **empty** allowed set, so supplying
either `source_type` or `source_id` (or both) with this purpose is
rejected outright, with a clear domain error
(`ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE`, 422 — never a 500, never a
silent strip-and-accept). The malformed request is refused before
`upload_attachment`/`_repository.create_attachment` is ever called — no
row is persisted, no storage write occurs (`StorageProvider.save` runs
strictly after this check).

This one check is shared by upload, list-by-source, and download: since
`require_readable_attachment` (download) and `require_attachment`
call the exact same `authorize_source` with the attachment's own
*already-persisted* `purpose`/`source_type`, a hypothetical malformed row
— whether from this exact exploit attempt (which now never persists) or
any other future path — is re-validated and refused on every subsequent
read too, never treated as legitimate master content merely because its
`purpose` says so.

## REV06.3.2 CROSS-DOMAIN PURPOSE CONFUSION CLOSED FOR EVERY PURPOSE

The same compatibility table also closes the general (lower-severity,
MEDIUM) purpose/source mismatch the audit noted: `REPAIR_EVIDENCE` +
`PM_WORK_ORDER`, `PM_EVIDENCE` + `REPAIR`, `REPAIR_REQUEST_EVIDENCE` +
`REPAIR`, `INSPECTION_EVIDENCE` + `REPAIR`, etc. are all now rejected
before any source lookup — not merely "still safe because the real
source's gate still ran" (true for these non-`CHECKLIST_REFERENCE_IMAGE`
cases even before this delta, since the branch was chosen by
`source_type` alone), but rejected outright now, so no attachment can ever
be persisted whose recorded `purpose` disagrees with its own
`source_type`'s domain.

## REV06.3.3 EXACT EXPLOIT REGRESSION TEST

`backend/tests/test_rev063_attachment_purpose_binding.py::
test_checklist_reference_image_cannot_smuggle_a_foreign_repair_source`
reproduces the exact audited exploit end-to-end over real HTTP: an
unrelated `DRIVER` (`mallory-unrelated`) uploads
`purpose=CHECKLIST_REFERENCE_IMAGE, source_type=REPAIR, source_id=<a real
Repair assigned to a different technician>`. Proven:

- Rejected (403/422, `ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE`).
- `StorageProvider.save` monkeypatched to raise if ever reached — proven
  never called.
- The legitimate assignee's own `GET /attachments/by-source/REPAIR/{id}`
  listing is asserted identical (empty) before and after the exploit
  attempt — no contamination.

Companion tests repeat the same proof against `PM_WORK_ORDER` and
`INSPECTION_VEHICLE` sources, one-sided source fields
(`source_type`-only, `source_id`-only), the full purpose-confusion matrix
(14 valid/invalid pairs from the audit brief), a legacy-malformed-row
download re-check (written directly through the repository, bypassing the
now-fixed upload gate, to prove download independently fails closed even
for a row that somehow already has the bad shape), and a regression pass
proving `REPAIR_EVIDENCE`/`PM_EVIDENCE`/`REPAIR_REQUEST_EVIDENCE`'s
existing authorization (active assignment, Maintenance override, unrelated
actor denied, ended assignment denied) is unaffected by the new check
running ahead of it. 19 new tests, all passing.

Two pre-existing tests asserted the old, less-specific
`ATTACHMENT_SOURCE_TYPE_NOT_SUPPORTED` code for a source_type that is now
caught earlier by the more specific compatibility check
(`REPAIR_EVIDENCE`+`FINDING`, `INSPECTION_EVIDENCE`+`INSPECTION_UNKNOWN`)
— both still correctly reject (422) and were updated to assert the new,
more precise code; a new test
(`test_unsupported_source_type_is_rejected_on_by_source_listing`) restores
coverage of the old code via the one path that still reaches it
(`GET /attachments/by-source/{source_type}/{id}`, which has no `purpose`
to check compatibility against). No assertion was weakened — both changes
reflect a strictly more specific, still-failing-closed rejection.

## REV06.3.4 CHECKLIST_REFERENCE_IMAGE — CREATION AUTHORITY LEFT AS-IS, DISCLOSED

Per this delta's own explicit fallback allowance: since source-less
enforcement is now airtight (a `CHECKLIST_REFERENCE_IMAGE` attachment can
never carry a source_type/source_id, so the transactional-record-injection
vector is fully closed regardless of who may upload this purpose),
creation/read authorization for `CHECKLIST_REFERENCE_IMAGE` remains
`can_view` — unchanged from REV06.2. No existing management/admin
capability in this codebase (`can_manage_pm`, `can_manage_repair`) is
actually scoped to checklist/reference-content authoring, and inventing an
association to either would be arbitrary, not a genuine "narrowest
existing capability" fit. **Reference-image authoring privilege remains
an explicitly open governance item** (no runtime UI path creates this
purpose today regardless) rather than being silently decided by this
delta.

## REV06.3.5 UNCHANGED / OUT OF SCOPE (BY DESIGN)

- Waiting Assignment, Repair My Work, Mock/GoogleSheets queue parity,
  Repair action/part authorization, provenance spoof prevention,
  conversion retry recovery, DEV_AUTH fail-closed — all independently
  verified PASS by the REV06.2 audit; not touched, only regression-tested.
- `INSPECTION_EVIDENCE`'s asset-level (not Inspection-level) binding is
  unchanged — the REV06.2 audit classified it LOW (does not exceed the
  already-open `GET /inspections/{id}` baseline); no Inspection Header
  rebinding was attempted here, per this delta's explicit instruction not
  to redesign it.
- PM/Inspection/Part/Lifetime Google Sheets I/O remains entirely stubbed
  (unchanged) — PM My Work still not operational against real Google
  Sheets.
- No open governance decision was resolved (checklist master authoring
  role, F01-F03, M02, Repair Request reject/cancel, PM E-series,
  Inspection D-series, Store/material lifecycle, part/lifetime lifecycle,
  notifications, model→PM Plan mapping).
- No new table/status/ACL entity was introduced — the fix is a single
  in-memory compatibility table checked inside the existing
  `authorize_source` function; no `waiting_assignment`/`waiting_parts`,
  no attachment ACL table, no new lifecycle status, no `technician_master`.
- `LIVE GOOGLE SHEETS ACCEPTANCE: PENDING` — unchanged; no credentialed
  Google API call was made this session.

## REV06.3.6 TEST RESULTS

Baseline (REV06.2, commit `027d3ac`, independently reproduced before this
delta's changes): backend 436 passed; frontend typecheck/lint/build PASS,
Vitest 54 passed; E2E 135 passed.

After this delta:
- Backend: `python -m pytest -q` → **456 passed** (436 baseline + 19 new
  in `test_rev063_attachment_purpose_binding.py` + a net +1 from
  replacing 1 REV06.2 test whose asserted error code this delta
  intentionally makes more specific with 2 narrower ones), 0 failed.
- Frontend: `tsc -b` → PASS (0 errors). `oxlint` → PASS (21 pre-existing
  warnings, 0 errors — unchanged; this delta is backend-only, no frontend
  file touched). `vitest run` → **54 passed** (26 files, unchanged).
  `vite build` → PASS.
- E2E: `playwright test` (all 5 configured viewports) → **135 passed**,
  0 failed (unchanged — no user-facing flow exercises
  `CHECKLIST_REFERENCE_IMAGE` or a cross-purpose/source-type pairing).

No existing test assertion was loosened; the two REV06.2 tests whose
expected error code this delta's more specific validation naturally
changes were updated to assert the new, still-failing-closed code, and a
new test was added to preserve coverage of the old code's one remaining
reachable path.

## REV06.3.7 FILES CHANGED

| File | Purpose | Key change |
|---|---|---|
| `backend/app/domain/attachment_service.py` | Attachment boundary | `_ALLOWED_SOURCE_TYPES_BY_PURPOSE`; `authorize_source` validates purpose/source_type compatibility before any other branch |
| `backend/tests/test_rev063_attachment_purpose_binding.py` | New | 19 tests — exact exploit reproduction, full purpose-confusion matrix, legacy-malformed-row fail-closed, authorization regression |
| `backend/tests/test_attachment_source_authorization.py` | Updated | one test's expected code updated to the new, more specific one; one new test restores `ATTACHMENT_SOURCE_TYPE_NOT_SUPPORTED` coverage via the by-source listing endpoint |
| `backend/tests/test_rev062_attachment_authorization.py` | Updated | one test's expected code updated to the new, more specific one |
| `docs/phase-results/core-demo-fixes-result.md` | Documentation | this section |

## REV06.3.8 GIT STATE

- Branch: `web/core-demo-fixes`
- Starting HEAD (audited REV06.2 HEAD): `027d3ac`
- Working tree: clean after commit
- Remote: pushed to `origin/web/core-demo-fixes`
- Not merged to `main`. No history rewritten. No force-push.

## REV06.3.9 REMAINING RISKS (SEPARATED BY CLASS)

- **Actual bug, now fixed**: `CHECKLIST_REFERENCE_IMAGE` purpose-confusion
  source-smuggling authorization bypass; general cross-domain
  purpose/source_type mismatches for every purpose.
- **Residual, disclosed (unchanged from REV06.1/06.2)**: a true
  simultaneous double-submit of Repair Request conversion; PM Work Order's
  own assignment authorization still reads its denormalized fields
  directly, not history (unrelated to this delta).
- **Out-of-scope repository stub (disclosed, unchanged)**: PM/Inspection/
  Part/Lifetime Google Sheets I/O.
- **Governance decision (intentionally left open)**: `CHECKLIST_REFERENCE_IMAGE`
  authoring/upload privilege (still `can_view`, disclosed as open rather
  than silently decided); `INSPECTION_EVIDENCE`'s asset-level (not
  Inspection-level) scope, classified LOW by the REV06.2 audit; final
  Repair/PM permission matrix (M02); everything listed in REV06.7.

# DELTA REV06.4 — Independent REV06.3 Micro-Audit Final Finding

The REV06.3 micro acceptance audit re-verified the `CHECKLIST_REFERENCE_IMAGE`
source-smuggling fix as solid, then asked one narrow follow-up question:
was `REPAIR_REQUEST_EVIDENCE`'s "source required? no" matrix entry a
documentation typo, or real implementation behavior? It was real: `
REPAIR_REQUEST_EVIDENCE` was the one transactional evidence purpose never
added to `_PURPOSES_REQUIRING_SOURCE` — its REV06.1 fix validated a
source when one was *present* but never required one, an omission carried
forward unexamined through REV06.2 and REV06.3 on the assumption it was
"already independently fixed." **`REPAIR_REQUEST_EVIDENCE` now requires
`REPAIR_REQUEST` source ownership**, matching every other transactional
evidence purpose.

## REV06.4.1 FIX — SOURCE NOW REQUIRED

`AttachmentPurpose.REPAIR_REQUEST_EVIDENCE` was added to
`_PURPOSES_REQUIRING_SOURCE` in `backend/app/domain/attachment_service.py`
— the exact same centralized mechanism already used for
`REPAIR_EVIDENCE`/`PM_EVIDENCE`/`INSPECTION_EVIDENCE`, no new/duplicate
validation path. A source-less upload is now refused
(`ATTACHMENT_SOURCE_REQUIRED`, 403) before `upload_attachment`/
`_repository.create_attachment` is ever called, and re-validated
identically on every subsequent download — so a hypothetical legacy
source-less row also fails closed rather than being treated as valid
merely because it predates this fix.

**Independently confirmed before and after** (throwaway script against the
real app, mirroring the exact exploit the REV06.3 audit reproduced): before
this fix, `POST /attachments {purpose: REPAIR_REQUEST_EVIDENCE}` with no
source returned `200 OK`, and the resulting attachment was downloadable by
a completely unrelated actor with **zero** authorization check — not even
`can_view`. After this fix, the same request returns `403
ATTACHMENT_SOURCE_REQUIRED`.

The existing reporter/`can_manage_repair` authorization logic for a
*given* `REPAIR_REQUEST` source (`attachment_service.py`'s `REPAIR_REQUEST`
branch) is completely unchanged — this delta only closes the no-source
loophole in front of it.

## REV06.4.2 FINAL PURPOSE/SOURCE MATRIX

| Purpose | Source | Requirement |
|---|---|---|
| `REPAIR_REQUEST_EVIDENCE` | `REPAIR_REQUEST` | **REQUIRED** (fixed this delta) |
| `REPAIR_EVIDENCE` | `REPAIR` | REQUIRED |
| `PM_EVIDENCE` | `PM_WORK_ORDER` | REQUIRED |
| `INSPECTION_EVIDENCE` | `INSPECTION_VEHICLE` / `INSPECTION_EQUIPMENT` | REQUIRED |
| `CHECKLIST_REFERENCE_IMAGE` | none | FORBIDDEN (source-less only) |

No purpose now has an ambiguous/accidentally-optional source state.

## REV06.4.3 TESTS

`backend/tests/test_rev064_repair_request_evidence_source_required.py`
(10 tests, all passing): the exact exploit (source-less upload rejected,
proven to persist nothing — a monkeypatch on `StorageProvider.save` fails
the test if ever reached, and the first attachment_id a fresh app instance
would issue is confirmed never created), one-sided source fields rejected,
wrong `source_type` (`REPAIR`) rejected, nonexistent Repair Request fails
closed (404), the legitimate flow unchanged (reporter allowed, unrelated
actor denied, `can_manage_repair` allowed, download works), a legacy
source-less row (written directly through the repository, bypassing the
now-fixed upload gate) fails closed on download with storage confirmed
untouched, and a rejected upload proven not to contaminate a real Repair
Request's own by-source listing.

The full REV06.3 `CHECKLIST_REFERENCE_IMAGE` exploit-regression suite
(`test_rev063_attachment_purpose_binding.py`, 19 tests) was re-run
unmodified and remains green — that fix is untouched by this delta.

## REV06.4.4 UNCHANGED / OUT OF SCOPE (BY DESIGN)

Queue derivation, Repair assignment/lifecycle, PM lifecycle, Inspection
ownership design, provenance, conversion recovery, user roles, model→PM
Plan mapping, Sheets master data — none touched. `CHECKLIST_REFERENCE_IMAGE`'s
source-smuggling fix and creation authority (`can_view`, still disclosed
as open governance) are unchanged. `LIVE GOOGLE SHEETS ACCEPTANCE: PENDING`
— unchanged; no credentialed Google API call was made this session.

## REV06.4.5 TEST RESULTS

Baseline (REV06.3, commit `ce1b910`): backend 456 passed; frontend
typecheck/lint/build PASS, Vitest 54 passed; E2E 135 passed.

After this delta:
- Backend: `python -m pytest -q` → **466 passed** (456 baseline + 10
  new), 0 failed.
- Frontend: `tsc -b` → PASS. `oxlint` → PASS (21 pre-existing warnings,
  0 errors, unchanged). `vitest run` → **54 passed** (unchanged,
  backend-only fix). `vite build` → PASS.
- E2E: `playwright test` → **135 passed**, 0 failed (unchanged — no
  frontend flow uses `REPAIR_REQUEST_EVIDENCE`).

No existing test assertion was weakened.

## REV06.4.6 FILES CHANGED

| File | Key change |
|---|---|
| `backend/app/domain/attachment_service.py` | `REPAIR_REQUEST_EVIDENCE` added to `_PURPOSES_REQUIRING_SOURCE` |
| `backend/tests/test_rev064_repair_request_evidence_source_required.py` | New — 10 tests |
| `docs/phase-results/core-demo-fixes-result.md` | this section |

## REV06.4.7 GIT STATE

- Branch: `web/core-demo-fixes`
- Starting HEAD (audited REV06.3 HEAD): `ce1b910`
- Working tree: clean after commit
- Remote: pushed to `origin/web/core-demo-fixes`
- Not merged to `main`. No history rewritten. No force-push.

## REV06.4.8 REMAINING KNOWN LIMITATIONS (HONEST, NOT HIDDEN)

- `CHECKLIST_REFERENCE_IMAGE` authoring/upload privilege remains `can_view`
  — an explicitly open governance item (no runtime UI path creates this
  purpose today regardless).
- `INSPECTION_EVIDENCE`'s asset-level (not Inspection-level) binding
  remains, classified LOW by the REV06.2 audit (does not exceed the
  already-open `GET /inspections/{id}` baseline) — not redesigned here.
- PM/Inspection/Part/Lifetime Google Sheets I/O remains entirely stubbed;
  PM Work Order's own assignment authorization still reads its
  denormalized fields directly, not history.
- `LIVE GOOGLE SHEETS ACCEPTANCE: PENDING` — no credentialed test evidenced.
- The documented residual simultaneous Repair Request conversion race
  (Google Sheets is non-transactional) remains, unchanged.

# FINAL CROSS-PHASE INTEGRATION FIX

PHASE: targeted integration-fix pass over the final cross-phase system
audit's `FIX BEFORE WEB UAT` verdict. Resolves exactly five concrete
integration defects (F1, F2, F3, F5, F6) found once Repair, PM,
Inspection, capability gating, and attachment authorization were all
exercised together — none of them individually broken by any one phase,
each of them a mismatch between two already-shipped, independently
passing pieces. Does not touch Repair Request → Repair, provenance,
conversion retry, attachment purpose/source matrix, Waiting Assignment,
Repair My Work, Repair assignment authority, CORE-G01 snapshot logic, or
vehicle/component identity — all independently audited passing and
explicitly out of scope for this pass. Does not resolve F4/M02, and does
not merge `main`.
STATUS: PASS

## G1. FINDINGS RESOLUTION MATRIX

| Finding | Before | Fix | Tests | Status |
|---|---|---|---|---|
| **F1** — PM assignment authority diverges from Repair | `POST /pm/work-orders/{id}/results` and the `PM_WORK_ORDER` attachment-authorization branch read `PmWorkOrder.primary_technician`/`.collaborators` directly; `list_pm_work_orders(assigned_to=...)` (backing PM My Work) did too | Added `PmService.get_active_assignment` (mirrors `RepairService.get_active_assignment`, same shared `active_primary_and_collaborators` helper); `submit_pm_task_result` and PM attachment authorization now call it; `MockRepository.list_pm_work_orders` derives `assigned_to` from `pm_work_order_assignment` history, mirroring `list_repairs`'s own REV06.2 fix | `test_pm_assignment_authority.py` (8), `test_pm_my_work.py` (+2 stale-history), `test_pm_attachment_assignment_history_authorization.py` (2) | RESOLVED |
| **F2** — Repair/PM evidence disappears after reload | Backend returned only raw `attachment_ids`/`evidence_attachment_ids`; the frontend never resolved them into displayable attachments, and Repair action evidence was never rendered at all (not even pre-reload) | `RepairDetailPage`/`PmWorkOrderDetailPage` fetch `GET /attachments/by-source/{REPAIR\|PM_WORK_ORDER}/{id}` on load (existing, already-authorized endpoint — no new backend route) and resolve IDs to `AttachmentInfo`; `PmTaskCard`'s completed-result view now renders evidence thumbnails (it never did, even pre-fix) | `RepairDetailPage.test.tsx` (+2), `PmWorkOrderDetailPage.test.tsx` (+1), `e2e/pm-repair.spec.ts` (+2 × 5 viewports) | RESOLVED |
| **F3** — unsupported Sheets features surface only as `INTERNAL_ERROR` | `GoogleSheetsRepository._require_configured` raised a bare `NotImplementedError`, caught only by the generic `Exception` handler | New `RepositoryFeatureNotImplementedError(RepositoryError)` in `app.repositories.base`; `_require_configured` raises it; `app.errors` maps it to `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` (HTTP 501, safe message, `details.feature`); frontend `describeErrorCode` gets the Thai message | `test_feature_not_available_error.py` (5: PM/Inspection/Part-Lifetime stubs, API-level 501 mapping, unexpected exception still `INTERNAL_ERROR`) | RESOLVED |
| **F5** — unauthorized frontend controls shown to wrong roles | `RepairDetailPage`'s Assign/Close cards and `PmWorkOrderDetailPage`'s scope-add/approve/close cards and `PmStatusPage`'s "Start PM" button rendered unconditionally, with zero capability gating | Gated behind `useCapabilities()` (`CAN_MANAGE_REPAIR`, `CAN_CLOSE_REPAIR`, `CAN_MANAGE_PM`) — exactly the capabilities each action's own backend route already requires; `useCapabilities()` extended to also expose `userId` from `/me` for future assignment-aware UI | `RepairDetailPage.test.tsx` (+2 role tests), `PmWorkOrderDetailPage.test.tsx` (+2), `PmStatusPage.test.tsx` (+1, existing test updated to run as MAINTENANCE) | RESOLVED |
| **F6** — failed frontend actions silently do nothing | `RepairDetailPage.closeRepair`/`.addEvidence`, `PmWorkOrderDetailPage.addEvidence`, `PmStatusPage.startWorkOrder` all had `if (result.ok) {...}` with no `else` | Each now sets a visible error message on failure (reusing the existing `describeErrorCode`/`form-field__error` convention already used everywhere else on these pages); no state is cleared, no silent navigation occurs | `RepairDetailPage.test.tsx` (+2), `PmWorkOrderDetailPage.test.tsx` (+1), `PmStatusPage.test.tsx` (+1) | RESOLVED |

## G2. PM ASSIGNMENT AUTHORITY — EXACT SOURCE AFTER FIX

The append-only `pm_work_order_assignment` history's currently-active rows
(`active_status=True`), derived by the same shared
`app.domain.assignment.active_primary_and_collaborators` helper Repair
already used, are now authoritative for:

- PM task-result authorization (`POST /pm/work-orders/{id}/results`, via
  `PmService.get_active_assignment`)
- PM evidence upload/list/download authorization
  (`AttachmentService.authorize_source`'s `PM_WORK_ORDER` branch)
- PM My Work (`GET /pm/work-orders/my-work`, via
  `list_pm_work_orders(assigned_to=...)`)

`PmWorkOrder.primary_technician`/`.collaborators` remain on the model,
kept in sync by `assign_pm_work_order`, but are now display/compatibility
fields only — exactly Repair's own REV06.1/REV06.2 invariant, restated for
PM. Google Sheets PM lifecycle remains stubbed
(`RepositoryFeatureNotImplementedError`); no PM Sheets I/O was implemented
this pass (see F3, G5, and I below) — a Sheets-mode PM My Work call fails
explicitly rather than silently falling back to Mock or to the
denormalized fields.

## G3. EVIDENCE RELOAD

**Repair**: `RepairDetailPage.load()` now also calls `GET
/attachments/by-source/REPAIR/{repairId}` (the same endpoint
`AttachmentService.list_for_source` already authorizes via
`authorize_source`'s `REPAIR` branch) and resolves each action's
`attachment_ids` against the result; a new `ActionEvidence` component
renders the resolved thumbnails under each action, latest and historical
alike. A failed fetch shows an inline Thai notice
("ไม่สามารถโหลดรูปแนบได้: ...") without hiding the rest of the page.

**PM**: `PmWorkOrderDetailPage.load()` calls `GET
/attachments/by-source/PM_WORK_ORDER/{workOrderId}` and merges the
resolved evidence into `evidenceByTask`, keyed by `pm_task_id`, without
discarding any evidence already staged (uploaded but not yet submitted)
for a task with no result yet. `PmTaskCard`'s completed-result view (which
never rendered evidence at all before this fix, in or out of session) now
shows the resolved thumbnails. No re-parenting to Repair — PM evidence
stays owned by its PM Work Order, matching REV06.2's ownership model.

Neither page fabricates a URL client-side; both use the backend's own
`AttachmentResponse.url` (`/api/v1/attachments/{id}/file`), which still
runs `authorize_source` on every download. No duplicate evidence appears
across repeated reloads (`evidenceById`/`evidenceByTask` are rebuilt from
the server response each load, keyed by `attachment_id`/`pm_task_id`, not
appended to).

## G4. REPOSITORY UNSUPPORTED ERROR

Example — `GET /pm/work-orders?asset_type=VEHICLE&asset_id=VEH-1` against
a configured-but-still-stubbed `DATA_REPOSITORY=google_sheets`:

```
501 Not Implemented
{
  "error": {
    "code": "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE",
    "message": "This feature is not available in the current data repository mode.",
    "details": { "feature": "pm_work_order" },
    "request_id": "..."
  }
}
```

Frontend: `describeErrorCode('FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE')`
→ **"ฟังก์ชันนี้ยังไม่รองรับในโหมดข้อมูลที่กำลังใช้งาน"** — shown wherever
that page already renders `describeErrorCode(err.code)` (no new UI
component). Never implies data was lost; never implies a retry will help.
An unrelated, unexpected exception (a real coding defect) still maps to
the generic `INTERNAL_ERROR` — `RepositoryFeatureNotImplementedError` is a
narrow, explicit type, not a blanket reclassification of every exception.

## G5. CAPABILITY UI MATRIX

| Role/Capability | Repair controls | PM controls |
|---|---|---|
| DRIVER (`can_view`, `can_report_repair`, `can_record_inspection`) | Assign/Close cards hidden | Start PM, scope add/approve, Close hidden |
| TECHNICIAN (same 3 as DRIVER) | Assign/Close cards hidden; action/part/evidence controls unchanged (`isOpen`-gated, as before — see limitation below) | Start PM, scope add/approve, Close hidden |
| MAINTENANCE / SUPERVISOR / ADMIN (`can_manage_repair`, `can_close_repair`, `can_manage_pm`, ...) | Assign card shown (`can_manage_repair`); Close card shown (`can_close_repair`) | Start PM shown (`can_manage_pm`); scope add/approve/Close shown (`can_manage_pm`) |

Backend remains authoritative in every case (`require_capability`/
`require_assignment_or_capability` on the actual routes) — this matrix is
UX consistency only, using the existing `useCapabilities()`/
`capabilityNames.ts` infrastructure, never a hardcoded `role === "X"`
check.

**Documented limitation (per task section 18)**: Repair's action/part/
evidence-recording controls and PM's task-result-entry controls remain
gated by `isOpen` only, not by capability/assignment, because the F5 test
matrix (section 19) only requires hiding *management* controls
(Assign/Close/scope-approve) from DRIVER/TECHNICIAN — it does not require
hiding assignment-based work controls, and DEV_AUTH_MODE's fixed-user
model makes a safe, non-regressive assignment-aware gate (comparing the
current actor's `user_id`, now exposed via `useCapabilities().userId`,
against the assigned technician) something the existing frontend test
suite is not shaped to exercise without broader changes than this
targeted pass justifies. Backend enforcement of assignment
(`require_assignment_or_capability`) is unaffected and unchanged.

## G6. SILENT-FAILURE MATRIX

| Path | Before | After |
|---|---|---|
| `RepairDetailPage.closeRepair()` | `if (result.ok) void load()` — no `else` | Sets `closeError`, rendered next to the Close button; repair stays OPEN, no navigation |
| `RepairDetailPage.addEvidence()` | `if (result.ok) setActionAttachments(...)` — no `else` | Sets `formError` (same field the action/part forms already use); upload state cleared, form stays usable |
| `PmWorkOrderDetailPage.addEvidence()` | `if (result.ok) { setEvidenceByTask(...) }` — no `else` | Sets `taskErrors[taskId]` (the same per-task error the task-result submit already renders); submit button stays usable |
| `PmStatusPage.startWorkOrder()` | `if (result.ok) navigate(...)` — no `else` | Sets `openError`, rendered under the "เริ่มทำ PM" button; stays on the PM status page, no navigation |

All four reuse the page's own existing error-display convention
(`describeErrorCode` + a `form-field__error` paragraph) — no new
notification framework was introduced.

## G7. TEST RESULTS

Baseline (this pass's starting HEAD `2a148c3`): backend 466 passed;
frontend typecheck/lint/build PASS, Vitest 54 passed; E2E 135 passed.

After this fix:
- Backend: `python -m pytest -q` → **483 passed** (466 baseline + 17
  new: 8 in `test_pm_assignment_authority.py`, 2 added to
  `test_pm_my_work.py`, 2 in
  `test_pm_attachment_assignment_history_authorization.py`, 5 in
  `test_feature_not_available_error.py`), 0 failed.
- Frontend: `tsc -b` → PASS. `oxlint` → PASS (same pre-existing warning
  set, 0 errors). `vitest run` → **66 passed** (54 baseline + 12 new
  across `RepairDetailPage.test.tsx` (+6), `PmWorkOrderDetailPage.test.tsx`
  (+4), `PmStatusPage.test.tsx` (+2)). `vite build` → PASS.
- E2E: `playwright test` → **145 passed**, 0 failed (135 baseline + 2 new
  specs × 5 viewport projects).

No existing test assertion was weakened. Two existing frontend tests
(`PmStatusPage.test.tsx`'s "opens a new PM work order" test,
`RepairDetailPage.test.tsx`/`PmWorkOrderDetailPage.test.tsx`'s by-source
fetch mocks) were updated to supply the capability/attachment context the
new gating and evidence-reload behavior require — their original
assertions are unchanged or strengthened, never removed.

## G8. FILES CHANGED

| File | Key change |
|---|---|
| `backend/app/domain/assignment.py` | unchanged — reused as-is |
| `backend/app/domain/pm_service.py` | + `get_active_assignment` |
| `backend/app/api/v1/pm.py` | `submit_pm_task_result` uses history, not denormalized fields |
| `backend/app/domain/attachment_service.py` | `PM_WORK_ORDER` branch uses history |
| `backend/app/repositories/mock/repository.py` | `list_pm_work_orders(assigned_to=...)` uses history |
| `backend/app/repositories/base.py` | + `RepositoryFeatureNotImplementedError` |
| `backend/app/repositories/google_sheets/repository.py` | `_require_configured` raises the explicit type |
| `backend/app/errors.py` | + handler mapping it to `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` (501) |
| `backend/tests/test_pm_assignment_authority.py` | new — 8 tests |
| `backend/tests/test_pm_my_work.py` | + 2 stale-history tests |
| `backend/tests/test_pm_attachment_assignment_history_authorization.py` | new — 2 tests |
| `backend/tests/test_feature_not_available_error.py` | new — 5 tests |
| `frontend/src/lib/capabilities.tsx` | `useCapabilities()` exposes `userId` |
| `frontend/src/lib/labels.ts` | + `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` Thai message |
| `frontend/src/pages/RepairDetailPage.tsx` | evidence reload, capability gating, F6 fixes |
| `frontend/src/pages/PmWorkOrderDetailPage.tsx` | evidence reload, capability gating, F6 fix |
| `frontend/src/components/PmTaskCard.tsx` | completed-result view now renders evidence |
| `frontend/src/pages/PmStatusPage.tsx` | capability gating, F6 fix |
| `frontend/src/pages/RepairDetailPage.test.tsx` | + 6 tests |
| `frontend/src/pages/PmWorkOrderDetailPage.test.tsx` | + 4 tests |
| `frontend/src/pages/PmStatusPage.test.tsx` | + 2 tests, 1 updated |
| `frontend/e2e/pm-repair.spec.ts` | + 2 evidence-reload E2E specs |
| `docs/phase-results/core-demo-fixes-result.md` | this section |

## G9. REMAINING KNOWN GAPS (SEPARATED, NOT HIDDEN)

**Code debt / documented limitation**:
- Repair action/part/evidence and PM task-result-entry controls remain
  `isOpen`-gated only (not capability/assignment-gated) on the frontend —
  see G5's limitation note. Backend enforcement is unaffected.

**Governance (unresolved, not silently decided)**:
- **F4 / M02** — `GET /repairs/{id}` and `GET /repair-requests/{id}` still
  lack a read-capability check. Left exactly as found; no new read policy
  was imposed.
- `CHECKLIST_REFERENCE_IMAGE` authoring/upload privilege (`can_view`) —
  open governance item, untouched.
- Real authentication (M01) remains `DEV_AUTH_MODE` only, untouched.

**Sheets stubs (honest, not silently faked)**:
- PM Work Order, Inspection/Finding, and Part/Lifetime Google Sheets I/O
  remain entirely stubbed (`RepositoryFeatureNotImplementedError`) — this
  pass gave them a clear, distinct error surface, not real I/O. PM My Work
  in Sheets mode fails explicitly for the same reason.
- Inspection evidence's asset-level (not Inspection-level) attachment
  binding — LOW, untouched, unchanged from REV06.2.
- PM evidence remains owned by its PM Work Order, not re-parented to
  Repair — untouched by design (task section 10).

**UAT pending**:
- `LIVE GOOGLE SHEETS ACCEPTANCE: PENDING` — no credentialed Google Sheets
  call was made this pass; `MAINTENANCE` (production) sheet remains
  untouched.
- The documented residual simultaneous Repair Request conversion race
  (Google Sheets is non-transactional) is unchanged.
- Checklist authoring governance remains open, untouched.
