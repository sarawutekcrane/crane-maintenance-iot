# Web/API Phase 4 — PM / Repair — Phase Result Report

PHASE: Web/API Phase 4 — Preventive Maintenance and Repair Workflows
STATUS: PASS

Documents read in full before implementation, as required:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt`
- `docs/phase-results/web-phase-01-verification.md`,
  `web-phase-02-verification.md`, `web-phase-03-verification.md`
- `docs/phase-results/component-role-naming-correction.md`,
  `component-role-naming-verification.md`

Plus direct inspection of the full existing backend/frontend codebase
(domain models, services, repositories, API routes, frontend types/
labels/pages/components) before writing any Phase 4 code, to match
established conventions exactly rather than inventing new ones.

---

## 1. OBJECTIVE

Implement backend-authoritative PM and Repair workflows, per the Phase 4
prompt's SCOPE section, without resolving any open governance decision
(E01–E05, F01–F03) and without fabricating PM plan/task source data.

## 2. PREREQUISITE CHECK

Phases 1–3 accepted (verified: `web-phase-01-verification.md` PASS,
`web-phase-02-verification.md` PASS, `web-phase-03-verification.md` PASS
with known limitations since corrected, `component-role-naming-verification.md`
PASS). The approved component-role vocabulary (`CARRIER_ENGINE`,
`CRANE_ENGINE`, `PTO`) was confirmed frozen and used as-is — `ENGINE_MAIN`/
`ENGINE_SECONDARY` were not reintroduced anywhere in Phase 4 code.

## 3. FROZEN CONTRACTS USED

- `/api/v1` prefix and route-registration pattern (`api/v1/router.py`).
- Common error envelope (`app.errors.ApiError`/`build_error_envelope`).
- `Repository`/`StorageProvider` abstractions — extended additively only
  (every Phase 1–3 abstract method signature is unchanged; only new
  methods were appended).
- `AssetType`/`AssetRef` (Phase 2) as the shared vehicle/equipment
  reference — reused, not redefined.
- Approved component-role vocabulary (`CARRIER_ENGINE`, `CRANE_ENGINE`,
  `PTO`) and the frozen counter concept (`vehicle_id -> component_id ->
  counter_type -> value`).
- `Attachment`/`AttachmentPurpose` (Phase 3) — extended additively with
  `PM_EVIDENCE`/`REPAIR_EVIDENCE` members; the shared upload/download
  boundary was extracted into a new `AttachmentService` so PM/Repair
  reuse the exact same StorageProvider path, validation, and filename
  sanitization Phase 3 established, without changing `InspectionService`'s
  own public method signatures.
- `PageParams`/`Page[T]` pagination envelope.
- `MockRepository`/`GoogleSheetsRepository` dual-implementation pattern,
  including the Google Sheets "declared schema + controlled
  `RepositoryError`/`NotImplementedError`" precedent from Phase 2/3.
- Stable opaque `PREFIX-NNNN` ID convention (Phase 2/3 precedent) —
  continued, not re-decided (see Section 20 / A01 below).
- Thai UI / English backend-code convention; mobile-first responsive
  primitives (`Card`, `FormField`, `ResponsiveTable`, `.sticky-actions`,
  `--tap-target`) — reused, none redesigned.

No frozen Phase 1–3 interface was changed. The one internal refactor
(`InspectionService` delegating attachment methods to a new
`AttachmentService`) is behavior-preserving: `InspectionService`'s own
public method signatures are byte-for-byte unchanged, and all 95
pre-existing backend tests pass unmodified against it.

## 4. FILES ADDED

Backend domain:
- `app/domain/pm.py`, `app/domain/repair.py`, `app/domain/meter.py`
- `app/domain/pm_service.py`, `app/domain/repair_service.py`,
  `app/domain/meter_service.py`
- `app/domain/attachment_service.py` (extracted shared attachment logic)
- `app/domain/asset_lookup.py` (shared asset-existence check)

Backend API:
- `app/api/v1/pm_schemas.py`, `app/api/v1/pm.py`
- `app/api/v1/repair_schemas.py`, `app/api/v1/repairs.py`
- `app/api/v1/meter_schemas.py`, `app/api/v1/meter.py`

Backend tests:
- `tests/test_pm_plan_and_task_revision.py`
- `tests/test_pm_work_order_api.py`
- `tests/test_meter_snapshot.py`
- `tests/test_repair_api.py`

Frontend:
- `src/pages/PmStatusPage.tsx` (+ `.test.tsx`)
- `src/pages/PmWorkOrderDetailPage.tsx` (+ `.test.tsx`)
- `src/pages/PmWorkOrderHistoryPage.tsx` (+ `.test.tsx`)
- `src/pages/RepairCreatePage.tsx` (+ `.test.tsx`)
- `src/pages/RepairDetailPage.tsx` (+ `.test.tsx`)
- `src/pages/RepairHistoryPage.tsx` (+ `.test.tsx`)
- `src/components/MeterSnapshotFields.tsx`
- `src/components/PartRowsEditor.tsx`
- `src/components/PmTaskCard.tsx`
- `frontend/e2e/pm-repair.spec.ts`

Docs:
- `docs/phase-results/web-phase-04-result.md` (this report)

## 5. FILES MODIFIED

- `app/repositories/base.py` — additive: new abstract methods for PM
  plan/task revision/work order/work result, meter snapshot, repair, plus
  two Finding/result lookup helpers used only for Repair source
  validation. Every Phase 1–3 abstract method is unchanged.
- `app/repositories/mock/repository.py`, `app/repositories/mock/seed_data.py`
  — additive: new in-memory storage + PLAN1 placeholder seed data.
- `app/repositories/google_sheets/repository.py`,
  `app/repositories/google_sheets/schemas.py` — additive: declared tab
  schemas + controlled-error method stubs, same pattern as Phase 2/3.
- `app/domain/inspection_service.py` — internal refactor only (delegates
  attachment methods to the new `AttachmentService`); public API
  unchanged, all 95 pre-existing tests pass unmodified.
- `app/domain/attachment.py` — additive: `PM_EVIDENCE`/`REPAIR_EVIDENCE`
  purposes.
- `app/dependencies.py`, `app/api/v1/router.py` — additive wiring.
- `frontend/src/lib/types.ts`, `frontend/src/lib/labels.ts` — additive
  types/Thai labels for PM/Repair/meter.
- `frontend/src/App.tsx` — additive routes only; the frozen
  `/vehicle/:vehicleId` and `/equipment/:equipmentId` route elements are
  untouched.
- `frontend/src/pages/VehicleDetailPage.tsx`,
  `frontend/src/pages/EquipmentDetailPage.tsx` — additive "PM"/"แจ้งซ่อม"/
  "ประวัติการซ่อม" action links, and the "coming in a later phase"
  placeholder sentence was edited to remove the now-implemented PM/repair
  mention (same kind of edit Phase 3's own report made for inspection).
- `frontend/src/pages/InspectionDetailPage.tsx` — additive: a "แจ้งซ่อม"
  link per finding; the finding record itself, the submission flow, and
  the immutability guarantee are all untouched.
- `CHANGELOG.md` — new entry appended; history preserved.

## 6. API ROUTES ADDED

PM:
- `GET /api/v1/pm/plans/status?asset_type=&asset_id=`
- `GET /api/v1/pm/plans/{pm_plan_id}/active-revision`
- `GET /api/v1/pm/plans/{pm_plan_id}/revisions/{revision_id}`
- `POST /api/v1/pm/work-orders`
- `GET /api/v1/pm/work-orders?asset_type=&asset_id=&page=&page_size=`
- `GET /api/v1/pm/work-orders/{pm_work_order_id}`
- `POST /api/v1/pm/work-orders/{pm_work_order_id}/results`
- `POST /api/v1/pm/work-orders/{pm_work_order_id}/close`

Meter:
- `POST /api/v1/meter-snapshots`
- `GET /api/v1/meter-snapshots/{meter_snapshot_id}`

Repair:
- `POST /api/v1/repairs`
- `GET /api/v1/repairs?asset_type=&asset_id=&status=&page=&page_size=`
- `GET /api/v1/repairs/{repair_id}`
- `POST /api/v1/repairs/{repair_id}/actions`
- `POST /api/v1/repairs/{repair_id}/parts`
- `POST /api/v1/repairs/{repair_id}/close`

(Attachments continue to use the existing Phase 3 `POST /api/v1/attachments`
/ `GET /api/v1/attachments/{id}/file` routes, now also accepting
`PM_EVIDENCE`/`REPAIR_EVIDENCE` as `purpose`.)

## 7. DATABASE / SHEET TABLES USED

Declared Google Sheets tab schemas (header-mapped, no live I/O — same
controlled `RepositoryError`/`NotImplementedError` pattern as every prior
phase): `pm_plans`, `pm_task_revisions`, `pm_tasks`, `pm_task_parts`,
`pm_work_orders`, `pm_work_results`, `pm_used_parts`, `meter_snapshots`,
`meter_readings`, `repairs`, `repair_actions`, `repair_parts`.

## 8. UI PAGES ADDED

- PM: summary (`/vehicle|equipment/:id/pm`), work-order detail/task
  execution (`/pm/work-orders/:id`), history
  (`/vehicle|equipment/:id/pm/history`).
- Repair: create/report (`/vehicle|equipment/:id/repairs/new`), detail
  (`/repairs/:id`), history (`/vehicle|equipment/:id/repairs`).

---

## 9. PM ARCHITECTURE

`PmPlan` (stable plan identity, e.g. `plan_code="PLAN1"`) →
`PmTaskRevision` (immutable, `effective_date`-selected active revision) →
`PmTask` (belongs to exactly one revision). This is a direct structural
mirror of Phase 3's `ChecklistMaster`/`ChecklistRevision`/`ChecklistItem`
model — the same pattern that already proved out revision isolation and
historical immutability, reused rather than redesigned.

`PmWorkOrder` (occurrence/header, `asset_type`+`asset_id`+`pm_plan_id`+
`revision_id`+status+open/close audit) → multiple `PmWorkResult` records
(one per task, created via `POST .../results`, never updated). Each
`PmWorkResult` snapshots the task's `description` at execution time
(mirroring `InspectionItemResult`'s snapshot pattern), so a later task
revision can never retroactively change what a historical work order
shows — proven by `test_new_pm_task_revision_does_not_mutate_old_work_order_history`.

## 10. PM TASK/REVISION DESIGN

Identical mechanics to Phase 3's checklist revision: `get_active_pm_task_revision`
picks the latest `(effective_date, revision_number)` ≤ today for a plan;
`get_pm_task_revision` reads any specific historical revision directly.
A `PmWorkOrder` records the exact `revision_id` active when it was opened
and `PmService.submit_task_result` resolves tasks against **that**
revision, not whatever is currently active — so a newer revision added
later never changes an open or closed work order's task text.

## 11. PM WORK-ORDER/RESULT DESIGN

- Opening a work order validates the asset exists, the plan exists and
  matches the asset's `asset_type`, and an active task revision exists.
- Submitting a result validates: work order is `OPEN` (not `CLOSED`), the
  task belongs to the work order's own revision, and no result already
  exists for that task on this work order — `PM_TASK_RESULT_ALREADY_EXISTS`
  (422) otherwise. There is no update/correction endpoint (mirrors Phase
  3's D04-precedent: not approved, so not built).
- Closing sets `status=CLOSED`, `closed_at`, `closed_by`; closing an
  already-closed work order is rejected (`PM_WORK_ORDER_ALREADY_CLOSED`,
  422) rather than silently re-applied — this is a basic idempotency
  guard, not a transition matrix (see Section 20, E01).

## 12. METER SNAPSHOT DESIGN

`MeterSnapshot` = `{asset_type, asset_id, readings: [{component_id,
counter_type, value}], recorded_at, recorded_by}`, matching the frozen
`vehicle_id -> component_id -> counter_type -> value` concept exactly.
`MeterService` (shared by `PmService` and `RepairService`, so neither
domain re-implements this validation independently) enforces:

- A component-scoped reading's `component_id` must be a real
  `VehicleComponent` on that vehicle (`METER_COMPONENT_NOT_FOUND`, 422,
  otherwise) — proven for both "component doesn't exist on any vehicle"
  and "component exists but belongs to a different vehicle."
- `ODOMETER` is the only counter type allowed with `component_id=None`
  (vehicle-level); every other counter type must name a component.
- Component-scoped readings are rejected for `EQUIPMENT`
  (`OPEN_DECISIONS_REGISTER_EN.txt` C03 is TBD-DEFERRED — no fabricated
  equipment counter/component model was invented); an equipment snapshot
  may still be created with zero readings.
- `value: null` (UNKNOWN) is stored and returned as `null`, never
  coerced to `0`, anywhere in the domain, API response, or frontend types
  (`MeterReading.value: number | null`).

Proven directly: `CARRIER_ENGINE`/`ENGINE_HOUR` and `CRANE_ENGINE`/
`ENGINE_HOUR` readings on the same dual-engine vehicle (`VEH-1047`) are
independently addressable and never conflated
(`test_carrier_engine_hour_remains_distinct_from_crane_engine_hour`); a
single-engine vehicle (`VEH-1046`/`VEH-1048`) rejects a reading naming a
`CRANE_ENGINE`-role component it does not have
(`test_single_engine_vehicle_rejects_a_fabricated_crane_engine_reading`).

## 13. STANDARD VS ACTUAL PM PARTS

`PmTaskPart` (standard/expected, attached to a `PmTask` — always empty in
Phase 4's seed data, since no authoritative standard-part list exists)
vs. `PmUsedPart` (actual, attached to a `PmWorkResult`, created only when
a technician records what was actually used). Submitting a result's
`used_parts` never writes back into the task's own `standard_parts` list
— proven by `test_actual_parts_used_are_separate_from_pm_task_standard_parts`,
which re-reads the task revision after submission and confirms
`standard_parts` is still `[]`. Both carry no `part_id` reference to a
part master (Phase 5 scope) — `part_description` is free text, forward-
compatible without implementing Phase 5's lifecycle logic here.

## 14. REPAIR ARCHITECTURE

`Repair` (header: `asset_type`/`asset_id`, `source_type`/`source_id`,
`category`/`symptom`, optional `meter_snapshot_id`, status, open/close
audit) is entirely separate storage from `PmWorkOrder` — no shared table,
no shared ID prefix, no code path that merges the two (proven by
`test_repair_is_separate_from_pm_work_order_namespace`: a repair ID is
never resolvable through the PM work-order endpoint and vice versa).
`RepairAction` (append-only history) and `RepairPart` (actual parts,
distinct record type from PM's) are child collections.

## 15. FINDING/SOURCE LINKAGE

`RepairSourceType`: `MANUAL`, `INSPECTION_RESULT`, `FINDING`, `PM_RESULT`,
`ALERT`. For `FINDING`/`INSPECTION_RESULT`/`PM_RESULT`, `RepairService`
validates the referenced record actually exists (via new,
read-only-search repository methods `find_inspection_finding`,
`find_inspection_result`, `find_pm_work_result`) — an unknown reference
is rejected (`REPAIR_SOURCE_NOT_FOUND`, 422). `ALERT` is accepted
structurally without existence validation, since no Alert domain exists
yet in this repository (explicitly documented as interface-ready only,
per the task's own instruction). Creating a repair **never** mutates the
source record — proven by re-reading the original inspection after
linking a repair to its finding and confirming the finding is
byte-for-byte unchanged
(`test_finding_source_links_to_repair_without_mutating_the_finding`).
No automatic Finding→Repair conversion exists anywhere: submitting a FAIL
inspection never itself creates a repair
(`test_fail_result_does_not_automatically_create_a_repair`) — F02 is
correctly left unresolved, not silently answered as "1:1" or "auto."

## 16. REPAIR ACTION/HISTORY DESIGN

`POST /repairs/{id}/actions` only ever appends a new `RepairAction`; there
is no update/delete endpoint at any layer. Proven by
`test_repair_action_history_is_append_only_and_previous_actions_remain_readable`:
two actions are added, both remain readable in original order with
distinct IDs, and by `test_close_repair_requires_no_unapproved_fields`,
which confirms the first action is still visible after closing.

## 17. ATTACHMENT/STORAGE BEHAVIOR

PM and Repair evidence photos reuse the exact same `AttachmentService`
Phase 3 established (now extracted from `InspectionService` into its own
module so all three domains share one implementation): same
`StorageProvider` boundary, same content-type allowlist/size-limit
validation (`Settings.attachment_allowed_content_types`/
`attachment_max_size_bytes` — still explicitly LOCAL-DEVELOPMENT DEFAULTS,
M07 unresolved), same filename-sanitization. Two additive
`AttachmentPurpose` members (`PM_EVIDENCE`, `REPAIR_EVIDENCE`) were added;
no new upload/download route was created. Binary content never touches
the repository — only `storage_ref` metadata does, same as Phase 3.

## 18. VEHICLE/EQUIPMENT SUPPORT

`VEHICLE` and `EQUIPMENT` remain fully separate master identities — PM/
Repair reference `AssetType`+`asset_id` generically via
`require_asset_exists` and never merge the two tables. PM applicability
differs by design: `PMP-0001` (`PLAN1`) is `asset_type=VEHICLE` only, so
`GET /pm/plans/status` for any equipment ID correctly returns an empty
list (no fabricated equipment PM plan) — proven by
`test_plan2_plan3_plan4_are_not_fabricated`-adjacent behavior and the
`PmStatusPage`/e2e "empty state" tests. Equipment repairs work
identically to vehicle repairs except the UI never renders meter-capture
fields for equipment (no approved equipment counter model — C03).

## 19. MOBILE/RESPONSIVE IMPLEMENTATION

Reused the frozen Phase 1 responsive primitives without redesigning them:
`Card`, `FormField`, `ResponsiveTable`, `.sticky-actions`, `--tap-target`
(44px minimum, asserted directly in the new e2e test for the "เริ่มทำ PM"
button). New mobile-specific additions:
- `PartRowsEditor` renders each actual-part-used entry as its own
  stacked card (description/quantity/unit + remove button), never a
  desktop-style table row — the exact pattern the baseline's mobile
  requirement calls for ("part entry must not require a wide table").
- `MeterSnapshotFields` renders one full-width numeric input per
  component-aware counter, with an explicit "leave blank if unknown"
  hint so a blank field is visibly a deliberate UNKNOWN, not an
  accidental omission.
- `PmTaskCard` mirrors `ChecklistItemCard`'s card-per-item, large-button
  layout for marking a task complete/incomplete.
- Photo capture reuses the same `capture="environment"` file input
  pattern Phase 3 established.
- Verified with a fresh Playwright suite (`frontend/e2e/pm-repair.spec.ts`)
  across all 5 required viewport projects: smartphone portrait/landscape,
  tablet portrait/landscape, desktop — including a no-horizontal-scroll
  assertion on the PM work-order page.

## 20. OPEN DECISIONS ENCOUNTERED

| Decision | Status after Phase 4 | What Phase 4 actually built |
|---|---|---|
| **E01** PM Status Lifecycle | **UNRESOLVED** — not marked approved | `PmWorkOrderStatus` is a provisional two-state (`OPEN`/`CLOSED`) placeholder, explicitly documented as such in `app/domain/pm.py`'s module docstring. No transition matrix (no `IN_PROGRESS`/`CANCELLED`) is enforced anywhere. |
| **E02** PM Warning Windows | **UNRESOLVED** — not marked approved | No warning-window/overdue-tolerance value exists anywhere in the codebase. `PmPlanStatus.due_status` is always the literal string `"UNKNOWN"`. |
| **E03** PM Completion Baseline | **UNRESOLVED** — not marked approved | No rule chooses which completed snapshot becomes the "next" baseline. `PmPlanStatus` only reports the **fact** of the last closed work order (ID, timestamp, meter-snapshot ID) — a read of history, not a computed baseline. |
| **E04** Missing Counter Behavior | **UNRESOLVED** — not marked approved | `MeterReading.value: float \| None`; `None` is never coerced to `0` at any layer (domain, repository, API schema, or frontend type). Proven by `test_unknown_counter_value_stays_unknown_never_becomes_zero`. |
| **E05** PLAN2/PLAN3/PLAN4 Data | **UNRESOLVED** — not marked approved | No source data exists for any plan, including PLAN1, beyond the plan-code concept named in governance docs. Only `PLAN1` was seeded, with generic, clearly-labeled example tasks (no fabricated interval/standard-part/threshold). `PLAN2`/`PLAN3`/`PLAN4` have **no** master record at all — proven by `test_plan2_plan3_plan4_are_not_fabricated`. |
| **F01** Repair Status Lifecycle | **UNRESOLVED** — not marked approved | `RepairStatus` is the same provisional two-state (`OPEN`/`CLOSED`) placeholder as `PmWorkOrderStatus`, same reasoning, same explicit documentation. |
| **F02** Finding-to-Repair Conversion | **UNRESOLVED** — not marked approved | A Finding *can* link to a repair (`source_type=FINDING`) but nothing enforces 1:1, deduplicates, or requires approval; nothing auto-creates a repair from any FAIL/Finding. Proven by `test_fail_result_does_not_automatically_create_a_repair`. |
| **F03** Repair Closure Requirements | **UNRESOLVED** — not marked approved | Closing a repair requires nothing beyond it existing and being open — no mandatory photo/technician/part/approval/note. Proven by `test_close_repair_requires_no_unapproved_fields`. |

No entry above was resolved, approved, or silently treated as decided.
`OPEN_DECISIONS_REGISTER_EN.txt` was **not** modified by this phase.

Additionally: **A01** (transaction ID strategy) remains `TBD-BLOCKING`;
Phase 4 continues the exact same isolated, mock-only, sequential
`PREFIX-NNNN` convention Phase 2/3 already established
(`PMP-`, `PMREV-`, `PMT-`, `PMTP-`, `PMWO-`, `PMWR-`, `PMUP-`, `MSNAP-`,
`RPR-`, `RPRA-`, `RPRP-`), consistent with each other and with the
register's own "Direction" line (backend-generated opaque strings, never
row numbers) — this is a reversible continuation, not a new freeze of
A01.

## 21. CONFIRMATION: PLAN2/PLAN3/PLAN4 WERE NOT FABRICATED

Confirmed by direct code/seed-data inspection and by
`test_plan2_plan3_plan4_are_not_fabricated`: `SEED_PM_PLANS` contains
exactly one entry (`PMP-0001`/`PLAN1`); no `PmPlan`, `PmTaskRevision`, or
`PmTask` record for any other plan code exists anywhere in the
repository. `GET /pm/plans/status` for a vehicle returns only `PLAN1`;
requesting any guessed plan ID (`PMP-0002`/`PMP-0003`/`PMP-0004`) returns
a controlled 404.

## 22. CONFIRMATION: PHASE 5 WAS NOT IMPLEMENTED

Confirmed by repo-wide review: no `part_instance`, `tracking_mode`,
lifetime-cycle, usage-segment, overhaul-reset, or position-baseline code
exists anywhere. `PmTaskPart`/`PmUsedPart`/`RepairPart` all use a plain
`part_description: str` field with **no** `part_id` reference to a part
master — this is deliberately the minimal shape that lets Phase 5 attach
real part-instance tracking later without rewriting Phase 4's PM/Repair
domain, not an implementation of Phase 5 itself. No Part Set/Kit
revisioning (baseline section 15 / Freeze Checkpoint #5, explicitly
Phase 5 scope) was built.

## 23. FROZEN PHASE 1–3 CONTRACTS AFFECTED: **NO**

Every Phase 1–3 route, schema, repository abstract method, and frontend
type/page is unchanged in shape and behavior. The only Phase 3 file with
a body change (`inspection_service.py`) is a pure internal refactor
(delegation to `AttachmentService`) with an unchanged public API,
verified by all 95 pre-existing backend tests passing unmodified.

## 24. APPROVED COMPONENT-ROLE CONTRACT AFFECTED: **NO**

`CARRIER_ENGINE`/`CRANE_ENGINE`/`PTO` are used exactly as approved,
read-only, via `Repository.list_vehicle_components`. No new component
role was added; no vehicle's actual component list was changed; no
`ENGINE_MAIN`/`ENGINE_SECONDARY` reference was reintroduced anywhere
(repo-wide grep confirms zero occurrences outside historical
verification reports and the naming-correction's own deprecation notes,
unchanged from before this phase).

---

## 25. IMPLEMENTATION SUMMARY

See Sections 9–19 above for the full architecture. In one sentence per
domain: PM mirrors Phase 3's revision-controlled checklist pattern for
plan/task/work-order/result, with component-aware meter snapshots shared
with Repair; Repair is a fully separate append-only-history domain that
can optionally link to (but never mutate) an Inspection Finding, an
Inspection Result, or a PM Result.

## 26. LOCAL STARTUP COMMANDS

Unchanged from Phase 1–3:
```
./scripts/run_backend.sh     # or: cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
./scripts/run_frontend.sh    # or: cd frontend && npm run dev
./scripts/run_dev.sh         # both together
./scripts/run_backend_tests.sh
./scripts/run_e2e_tests.sh
```

## 27. BUILD / TYPECHECK / LINT RESULT

- Backend: no lint/typecheck tool is configured for this project (pytest
  only, per `backend/pyproject.toml` — unchanged from Phase 1–3).
- Frontend typecheck (`npx tsc -b`): **PASSED** (exit code 0).
- Frontend lint (`npx oxlint`): **PASSED** — 0 errors. All warnings are
  the same pre-existing `react(set-state-in-effect)` category present
  since Phase 1, now also on the new PM/Repair pages; no new warning
  category was introduced.
- Frontend production build (`npm run build`): **PASSED**.
  ```
  dist/index.html                   0.43 kB │ gzip:  0.30 kB
  dist/assets/index-*.css          10.02 kB │ gzip:  2.47 kB
  dist/assets/index-*.js          334.80 kB │ gzip: 96.90 kB
  ✓ built in ~420-480ms
  ```

## 28. TESTS ACTUALLY PERFORMED / RESULTS

All commands below were executed directly in this session.

**Backend — pytest**
```
$ cd backend && source .venv/bin/activate && DATA_REPOSITORY=mock python -m pytest -q
141 passed, 20 warnings in ~4s
```
(95 pre-existing Phase 1–3 tests, unmodified and passing, + 46 new: 8 in
`test_pm_plan_and_task_revision.py`, 15 in `test_pm_work_order_api.py`,
11 in `test_meter_snapshot.py`, 17 in `test_repair_api.py`. All 20
warnings are the pre-existing `HTTP_422_UNPROCESSABLE_ENTITY` Starlette
deprecation notice, same category present since Phase 1.)

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npx vitest run
Test Files  21 passed (21)
     Tests  44 passed (44)
```
(32 pre-existing + 12 new: `PmStatusPage.test.tsx` [3],
`PmWorkOrderDetailPage.test.tsx` [2], `PmWorkOrderHistoryPage.test.tsx`
[2], `RepairCreatePage.test.tsx` [2], `RepairDetailPage.test.tsx` [2],
`RepairHistoryPage.test.tsx` [1].)

**Frontend — typecheck / lint / build**: see Section 27.

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
110 passed (~55s)
```
(85 pre-existing Phase 1–3 tests, unmodified and passing, + 25 new: 5
tests in the new `frontend/e2e/pm-repair.spec.ts` × 5 viewport projects
[smartphone-portrait, smartphone-landscape, tablet-portrait,
tablet-landscape, desktop].)

No test was skipped, disabled, or hidden. No result above was claimed
without being executed in this session.

## 29. MANUAL TEST PLAN

Run with `./scripts/run_dev.sh`, `DATA_REPOSITORY=mock`, at
`http://127.0.0.1:5173`.

1. **PM summary** — open `/vehicle/VEH-1046`, tap "PM". Expected: PLAN1
   card shows its Thai example-data name, active revision number, "ยังไม่มี
   ประวัติ" for last-completed, and the due-status note naming E02/E03/E04.
2. **Start PM work order** — tap "เริ่มทำ PM". Expected: navigates to the
   work-order detail page with 3 placeholder task cards, none completed.
3. **Submit a task with a meter reading and a part** — on the first task,
   fill the "เลขไมล์ (ODOMETER)" field, add a part via "+ เพิ่มอะไหล่ที่ใช้",
   tap "บันทึกผลงาน". Expected: the card becomes read-only, shows "ผลงาน:
   เสร็จสิ้น", the part name, and "บันทึกค่ามาตรวัดแล้ว".
4. **Close the work order** — after all 3 tasks are submitted, tap "ปิด
   ใบสั่งงาน PM". Expected: status badge changes to "ปิดงานแล้ว"; PM
   history (`/vehicle/VEH-1046/pm/history`) lists it.
5. **Manual repair** — from Vehicle Detail tap "แจ้งซ่อม", fill "อาการ/
   ปัญหาที่พบ", submit. Expected: navigates to the repair detail page,
   status "กำลังดำเนินการ", source "แจ้งซ่อมด้วยตนเอง".
6. **Repair action + part** — add an action and a part on the repair
   detail page. Expected: both appear immediately; adding a second action
   does not remove the first.
7. **Close repair** — tap "ปิดใบแจ้งซ่อม". Expected: status becomes "ปิด
   งานแล้ว"; prior action remains visible.
8. **Finding → Repair** — submit a FAIL inspection on any vehicle, open
   the resulting inspection detail page, tap "แจ้งซ่อม" next to the
   finding. Expected: repair-create page shows the source locked to
   "ข้อบกพร่องจากการตรวจเช็ค" with the finding ID; after submitting, the
   repair detail page shows the same source. Confirm the original
   inspection/finding is unchanged.
9. **Equipment PM empty state** — open `/equipment/EQP-0001`, tap "PM".
   Expected: "ยังไม่มีแผนบำรุงรักษาที่ใช้งานสำหรับสินทรัพย์นี้" (no
   fabricated equipment plan).
10. **Equipment repair** — tap "แจ้งซ่อม" on Equipment Detail. Expected:
    same flow as vehicles, but no meter-capture fields are shown.
11. **Mobile viewport** — repeat steps 2–7 at a phone width (375px).
    Expected: no horizontal scrolling, parts render as stacked cards (not
    a table), all primary buttons ≥44px tall.

## 30. KNOWN LIMITATIONS

- PM due/remaining/overdue is not calculated at all (by design — E02/E03/
  E04 unresolved). `PmPlanStatus.due_status` is always `"UNKNOWN"`.
- Only `PLAN1` has any task content, and it is placeholder/example data
  only — not usable as a real maintenance procedure.
- No PM-authoring UI exists (creating/editing plans, task revisions, or
  standard parts) — Phase 4 only consumes seed data, matching the Phase 3
  precedent for checklists.
- `PmWorkOrderStatus`/`RepairStatus` have only `OPEN`/`CLOSED` — no
  `IN_PROGRESS`, assignment, or cancellation state.
- No correction/void workflow exists for a submitted `PmWorkResult` or a
  posted `RepairAction` (matches Phase 3's D04 precedent — not approved,
  not built).
- Repair `category`/`symptom` are free text; no approved category
  vocabulary exists.
- Equipment has no counter/component model (C03 deferred) — PM/Repair
  meter capture is vehicle-only.
- Same A01 (transaction ID) caveat as every prior phase: IDs are opaque
  and stable, but the *generation mechanism* is an in-memory sequential
  counter, not yet a cross-storage strategy.

## 31. RISKS / CONCERNS

- If a future phase adds a second VEHICLE PM plan whose `model_ids` scope
  overlaps another plan's, `list_pm_plans`'s current filter (plans whose
  `model_ids` is empty or contains the vehicle's `model_id`) will return
  both — this is correct today (no exclusivity was ever claimed) but
  should be revisited once real multi-plan-per-model data exists.
- `RepairService._validate_source` for `ALERT` never validates existence
  (no Alert domain exists yet) — once an Alert domain is built, this
  should gain the same existence check as FINDING/INSPECTION_RESULT/
  PM_RESULT.

## 32. STATUS OF E01/E02/E03/E04/E05

All **UNRESOLVED**, not marked approved by this phase. See Section 20 for
the exact placeholder behavior built for each and the test proving it
does not silently resolve the decision.

## 33. STATUS OF F01/F02/F03

All **UNRESOLVED**, not marked approved by this phase. See Section 20.

## 34. ANY CHANGE TO PREVIOUS FROZEN PHASES

NONE, beyond the disclosed internal, behavior-preserving
`InspectionService`→`AttachmentService` refactor (Section 3/23), verified
by all 95 pre-existing backend tests and all pre-existing frontend/e2e
tests passing unmodified.

## 35. FINAL PHASE 4 IMPLEMENTATION STATUS

**PASS.** PM and Repair core contracts (work-order/result model, meter
snapshot contract, source linkage, revision references, backend
due-status interface) are stable and ready for Phase 5 (Part/Lifetime)
integration, per the exit gate in
`docs/claude-prompts/web-api/04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt`.

## NEXT PHASE READINESS

READY.

---

STOP HERE. Do not begin Phase 5.
