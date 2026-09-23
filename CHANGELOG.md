# Changelog

## Web/API Phase 7 Batch 7B2 — Validated fleet status dashboard (uncommitted review candidate)

Phase 7 remains **PARTIAL**. See
`docs/phase-results/web-phase-07-batch7b2-result.md` for the approved
KPI/validation/error/auth/navigation policies and verification. (Batch 7A
added no changelog entry; it is recorded in its own commit.)

- **API**: new `GET /api/v1/dashboard/fleet-status` (global, no query
  parameters) returns only `population`, K1 `vehicle_total` and the five
  K2–K6 recorded `status_counts` (all keys always present;
  `vehicle_total` = their sum). Requires the existing `can_view`
  capability before any read. Whole-response errors with no counts:
  500 `VEHICLE_MASTER_SCHEMA_INVALID`, 500 `VEHICLE_MASTER_DATA_INVALID`,
  503 `VEHICLE_MASTER_READ_FAILED`.
- **Parity-or-fail**: counts are returned only when they equal the
  `GET /vehicles` totals for the same stored data. One validated
  vehicle_master values read checks the header of that same response
  before any filtering; blank/unrecognized statuses, unmappable rows,
  blank/duplicate vehicle ids and data outside the header fail the whole
  summary. A single blank status therefore blocks the dashboard while the
  legacy list still shows that row as READY (accepted; no data or
  default is changed).
- **Web**: new Thai mobile-first page `/dashboard` ("ภาพรวมกองรถ") and one
  menu item; one plain link to the unfiltered vehicle list; status cards
  are not filtered links. `HomePage` and `VehicleListPage` are unchanged.
- Additive only: `read_rows`, `validate_schema`, the header cache,
  `_vehicle_from_row`, list/detail routes and all other callers are
  unchanged. Verified with the real installed gspread over a fake
  transport; no live Google Sheets validation was performed.

## Web/API Phase 6 — Driver, Certificates, Documents, Work History, GPS, and Alerts (closure documentation)

Documentation-only closure of an already-implemented and merged Phase 6
(commits `3e54e60`..`0efa124`, 32 commits, Driver/Operator Batch 1 through
Batch 6F model-document revision UI). See
`docs/phase-results/web-phase-06-result.md` (Phase Result Report,
including the per-category alert-generation table) and
`docs/phase-results/web-phase-06-verification.md` (verification report,
nine-row acceptance matrix, and closure recommendation:
**ACCEPTABLE WITH DOCUMENTED DEFERRED/BLOCKED ITEMS**) for full detail,
including exactly which Open Decisions (A01, A04, A05, A06, A09, A11/D26,
B04, E01–E04, F01, G01/G02, H02, H03, M02, M07) remain deferred/blocked
and why — D26/A11's own register text explicitly names certificate-
expiry calculation, inactive-vehicle calculation, and MODEL/VEHICLE
`AlertSetting` precedence among the things it does not define, so these
are tracked, named decision dependencies, not ungoverned gaps.

- **Driver/Operator**: master record's optional fields are PATCH-updated
  in place via a service-layer partial-update (omitted vs. explicit-null
  resolution) over a repository-layer full-replace call — not versioned;
  vehicle↔driver assignment history is append-only with idempotent
  ending.
- **Certificates**: renewal is a non-atomic two-write operation; when a
  prior partial failure already left two ACTIVE rows in the same
  vehicle/type group, a subsequent renewal attempt is rejected (creating
  no further row) rather than compounding the corruption — the underlying
  orphan from that earlier failure still requires manual reconciliation.
  **Model documents**: revision is also a non-atomic two-write operation
  but has no equivalent guard — if an earlier attempt's link write failed,
  a retry does not detect it and proceeds normally, leaving that earlier
  row permanently unlinked alongside the now-successfully-linked revision
  (one leftover row, not two). These two risks are distinct, not
  identical, and both exist today (not only after a future PostgreSQL
  migration). Certificate expiry reconciliation is lazy/read-triggered,
  not scheduled.
- **Work history / events**: exact device-supplied fields are
  `event_time`, `device_event_id`, `sequence`, `device_id`,
  `created_offline`, `time_quality`; duplicate ingestion is idempotent by
  `(device_id, device_event_id)`; history orders by `event_time`, never
  `received_at`.
- **GPS**: latest-valid-location projection and per-event GPS are
  separate; `gps_valid` is never inferred from coordinate presence; a
  genuine zero coordinate is rendered as a valid value, not as missing
  (dedicated frontend tests on both the latest-location card and the
  work-history page).
- **Alerts**: read-only public API (D24 severity vocabulary); D25's
  full lifecycle (acknowledge/mute/resolve, with a caller-supplied, not
  backend-generated, `alert_id`) and D26's effective-GLOBAL-setting/
  `DEVICE_OFFLINE`-suppression policy are internal-only, with no HTTP
  mutation endpoint (blocked by M02) and **no automatic alert-generation
  code path for any category** (PM/lifetime/certificate/repair/device-
  offline/inactive-vehicle/sensor/OTA/safety — see the result report's
  per-category table for the exact blocker or phase boundary named for
  each, including D26/A11's own explicit "does NOT define" list, which
  covers certificate expiry and inactive vehicle specifically). The mock
  test environment's seed data starts with
  zero Alert rows; this reflects the seed data and the absence of a
  generator, not a system-wide guarantee that alert reads are always
  empty.
- `storage_ref` (certificates/model documents) is opaque metadata only —
  no upload/download mechanism; distinct from the separate, pre-existing
  Phase 3 inspection-attachment upload/download endpoints, which are
  unaffected. Model-document revision never inherits `storage_ref` when
  omitted from a revise request (must be re-supplied to carry it
  forward).
- This closure task itself added only the two phase-result documents and
  this entry — no source, test, dependency, config, or governance file
  was changed. Full regression executed fresh once, in the original
  closure session: backend 1080/1080, frontend unit 177/177,
  typecheck/build exit 0, lint exit 0 with 0 errors/34 pre-existing-
  category warnings, focused Batch 6F Playwright spec 20/20 across all 5
  viewports. (Two later reviewer-requested correction passes fixed
  several factual errors in the two phase-result documents — including
  this commit-range figure itself, a false claim about missing
  certificate `storage_ref` test coverage, and an incorrect reading of
  D26/A11's governance scope — without any source/test change and without
  re-running the suites; see the verification report's Sections 14–15
  for the itemized correction checklists.)

## Web/API Phase 5 — Parts, Part Sets, Lifetime, Incremental Tracking, and Component Transfer

Scalable parts/lifetime tracking that never requires pre-registering every
physical part on every vehicle. See
`docs/phase-results/web-phase-05-result.md` for the full Phase Result
Report, including exactly which Open Decisions (G01–G06, A01–A03) remain
unresolved and why.

- **Part Master**: `tracking_mode` (`NONE`/`CONSUMABLE`/`POSITION_LIFETIME`/
  `INSTANCE_TRACKED`) as a first-class, distinct field per part; created
  on demand, never pre-loaded as a full company catalog. Different
  specifications get different `part_id`s even with an identical display
  name (seeded proof: two "ไส้กรองน้ำมันเครื่อง" parts, different
  specification, different `part_id`).
- **Part Set / Kit**: revision-controlled (mirrors the Phase 3 checklist/
  Phase 4 PM-task revision pattern exactly); items carry
  `REQUIRED`/`OPTIONAL`/`ALTERNATIVE`. A later revision is an entirely new
  item list — never an edit of a previous revision's items.
- **INSTANCE_TRACKED**: on-demand `PartInstance` enrollment with stable
  identity, append-oriented `InstallationSegment` history (install/
  remove/transfer), and a `PartLifecycle` boundary for an explicitly
  caller-approved overhaul (never auto-detected). A removed/IN_REPAIR
  instance has no ACTIVE segment, so it cannot accumulate a host
  vehicle's ENGINE_HOUR/PTO_HOUR/ODOMETER. Transfer between vehicles
  preserves the previous segment (still readable) and never resets
  accumulated usage or prior_usage.
- **POSITION_LIFETIME**: asset+position+rule/baseline tracking with no
  serialized instance required; `position_code` remains free text (G03
  unresolved — no company position-code vocabulary invented).
- **Lifetime rule**: structural `LifetimeRule` (trigger type +
  component-role-aware counter reference + model-rule/vehicle-override
  scope) with no real interval/threshold ever seeded (G01/G02
  SOURCE-DATA-REQUIRED).
- **Prior usage**: `KNOWN`/`PARTIAL`/`UNKNOWN` on both `PartInstance` and
  `PositionLifetimeRecord`; `UNKNOWN` is never coerced to `0` at any
  layer.
- **Phase 4 integration**: `PmUsedPart`/`RepairPart` gained additive,
  optional `part_id`/`part_instance_id`/`action`
  (`CONSUMED`/`INSTALLED`/`REMOVED`/`SERVICED`) fields — standard PM task
  parts (`PmTaskPart`) are untouched, and no completed Phase 4 history is
  rewritten.
- Frontend: Part Master catalog list/detail, on-demand instance
  registration, instance detail with install/remove/transfer/lifecycle-
  history actions, an asset-scoped "อะไหล่/อายุการใช้งาน" page for
  POSITION_LIFETIME enrollment, and part-instance linking surfaced on the
  PM/Repair actual-parts entries.
- G01–G06 (real lifetime rules, warning windows, position code master,
  overhaul reset rules, instance status transitions, usage adjustment
  approval) all remain explicitly unresolved — not marked approved by
  this phase.

## Web/API Phase 4 — Preventive Maintenance (PM) and Repair Workflows

Backend-authoritative PM and Repair domains, separate from each other and
from Phase 1–3 (inspection remains untouched). See
`docs/phase-results/web-phase-04-result.md` for the full Phase Result
Report, including exactly which Open Decisions (E01–E05, F01–F03) remain
unresolved and why.

- **PM**: revision-controlled `PmPlan`/`PmTaskRevision`/`PmTask` (mirrors
  the Phase 3 checklist revision model exactly); `PmWorkOrder` occurrence
  header with append-only, immutable `PmWorkResult` records (one per task,
  never overwritten); standard parts (`PmTaskPart`) kept separate from
  actual parts used (`PmUsedPart`). Only `PLAN1` is seeded, with clearly
  labeled example/placeholder tasks (no interval/standard-part values
  fabricated) — `PLAN2`/`PLAN3`/`PLAN4` are not created at all
  (OPEN_DECISIONS_REGISTER_EN.txt E05: no source data exists for any
  plan). PM due/remaining calculation is not implemented: `due_status` is
  always `"UNKNOWN"` with a note naming the blocking decisions (E02, E03,
  E04).
- **Meter snapshot**: component-aware `vehicle_id -> component_id ->
  counter_type -> value` capture, validated against the vehicle's actual
  components (a reading for a component the vehicle does not have, e.g. a
  fabricated `CRANE_ENGINE` on a single-engine vehicle, is rejected). An
  unknown reading (`value: null`) is never coerced to `0`.
- **Repair**: separate domain from PM, with `MANUAL`/`INSPECTION_RESULT`/
  `FINDING`/`PM_RESULT`/`ALERT` source types (`ALERT` is interface-ready
  only — no Alert domain exists yet). A Finding can link to a repair
  on request; nothing auto-creates one, and creating a repair never
  mutates the source Finding (F02 unresolved). Repair actions are
  append-only history; repair parts are a distinct record type from PM's
  parts. Closing requires nothing beyond the repair being open (F03
  unresolved).
- **Status lifecycles**: `PmWorkOrderStatus`/`RepairStatus` are
  provisional two-state (`OPEN`/`CLOSED`) placeholders with no transition
  matrix — E01/F01 remain unresolved and are not marked approved by this
  phase.
- Frontend: PM summary/work-order/history pages and Repair create/detail/
  history pages, reachable from Vehicle/Equipment Detail ("PM",
  "แจ้งซ่อม", "ประวัติการซ่อม") and from a Finding on the inspection
  detail page. Mobile-first: parts entry uses stacked cards, not tables.
- New backend tests (46) and Playwright e2e tests (5 × 5 viewports) prove
  revision isolation, task-result immutability, component/counter
  correctness, source linkage without mutation, and append-only action
  history. Full regression: 141/141 backend, 44/44 frontend unit,
  110/110 Playwright, typecheck/lint/build clean.

## Component Role Naming Correction — CARRIER_ENGINE/CRANE_ENGINE replace ENGINE_MAIN/ENGINE_SECONDARY

Cross-phase contract correction after approved Web/API Phase 3, before
Phase 4. Approved decision: the component-role vocabulary is now
`CARRIER_ENGINE`, `CRANE_ENGINE`, `PTO`. `ENGINE_MAIN`/`ENGINE_SECONDARY`
are deprecated legacy names and are no longer valid `ComponentRole`
values.

- `ComponentRole` enum (`backend/app/domain/vehicle_model.py`) renamed;
  no legacy-compatibility parsing was added, since no write endpoint ever
  accepted a client-supplied `component_role` and no persisted/historical
  record ever stored the old names (Phase 1–3 use only in-memory
  `MockRepository` seed data).
- Mock seed data migrated with a known, non-ambiguous mapping: the
  Thai description of the one dual-engine seed model
  (MODEL-0002/XCT80) already states "เครื่องยนต์คู่ (ขับเคลื่อน + ยกเครน)"
  (drive/carrier + crane-lift), so `ENGINE_MAIN → CARRIER_ENGINE`,
  `ENGINE_SECONDARY → CRANE_ENGINE` is a direct, non-guessed migration.
  Single-engine seed models (MODEL-0001, MODEL-0003) keep only
  `CARRIER_ENGINE` + `PTO` — no `CRANE_ENGINE` was fabricated for them.
- Frontend `ComponentRole` type/labels updated to the approved Thai
  wording ("เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง",
  "เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน").
- `vehicle_id`/`component_id`/`model_id` values are unchanged — only the
  `component_role` values were corrected.
- Recorded as decision C04 in `OPEN_DECISIONS_REGISTER_EN.txt`
  (APPROVED/FROZEN, vocabulary only). See
  `docs/phase-results/component-role-naming-correction.md` for the full
  impact analysis and regression results. Phase 4 was not started.

## Web/API Phase 3 correction — remark-on-FAIL made item-level, attachment upload boundary, unknown-asset entry check

`docs/phase-results/web-phase-03-verification.md` flagged one unapproved
permanent decision and two minor limitations. This correction addresses
all three without resolving any open decision (D01–D04, M07 remain
exactly as they were) and without starting Phase 4:

- **Unapproved FAIL-requires-remark rule (fixed):** a FAIL result was
  unconditionally required to carry a remark, with no source authorizing
  it as a global rule. `ChecklistItem` gains `required_remark_on_fail`
  (default `False`), mirroring `required_photo_on_fail`'s existing
  item-level, source-data-driven design exactly. Backend
  (`InspectionService.submit_inspection`) and frontend
  (`InspectionFormPage`/`ChecklistItemCard`) both check the new flag
  independently of the photo flag. All placeholder/seed checklist items
  remain `False` for both flags — the seed data was also corrected to
  stop setting `required_photo_on_fail=True` on the last item of each
  checklist, since no authoritative source names that item as requiring a
  photo either; the item-level mechanism itself is now proven by
  dedicated tests that inject a synthetic item rather than by an invented
  seed-data rule.
- **Attachment upload safety boundary (added, not frozen):** the upload
  endpoint now validates content type against an allowlist and enforces a
  size limit (`Settings.attachment_allowed_content_types` /
  `attachment_max_size_bytes`), and sanitizes the stored filename/
  extension. These are explicit **local-development defaults**, not a
  production policy — `OPEN_DECISIONS_REGISTER_EN.txt` M07 remains
  unresolved, and the values are configurable via environment variables
  precisely so an explicitly-approved production policy can replace them
  later without a code change.
- **Unknown-asset direct-URL behavior (fixed):** `InspectionFormPage` now
  validates the vehicle/equipment exists before rendering the checklist,
  showing the existing controlled Thai not-found state immediately
  instead of only discovering an invalid asset at final submission. The
  frozen `/vehicle/{vehicle_id}` and `/equipment/{equipment_id}` QR routes
  are unchanged.
- Tests: 10 new backend tests (`test_inspection_item_level_rules.py`,
  `test_attachment_upload_validation.py`, plus one in
  `test_inspections_api.py`), 3 new frontend unit tests, 2 new Playwright
  tests × 5 viewports. Full regression re-run: backend 82/82, frontend
  unit 32/32, typecheck/lint/build clean, Playwright 85/85.

See `docs/phase-results/web-phase-03-verification.md`'s correction
addendum for full detail.

## Web/API Phase 3 — Inspection, Checklist Revision, History, and Abnormal Findings

- Domain: revision-controlled `ChecklistMaster`/`ChecklistRevision`/
  `ChecklistItem` (`app.domain.checklist`), a shared `Attachment`/
  `AttachmentPurpose` model separating checklist reference images from
  inspection evidence photos (`app.domain.attachment`), and immutable
  `InspectionHeader`/`InspectionItemResult`/`InspectionFinding`
  (`app.domain.inspection`) — item results snapshot the checklist item's
  display text at submission time, so a later revision can never change
  history.
- `InspectionService` (`app.domain.inspection_service`) resolves "the"
  active checklist revision per `AssetType`, validates a submission
  against it (every item answered exactly once, FAIL requires a remark
  and — where the item requires it — an evidence photo), creates an OPEN
  finding for every FAIL, and never updates/voids a previously submitted
  inspection.
- `Repository` extended with checklist/attachment/inspection methods;
  `MockRepository` gets a full in-memory implementation with clearly
  placeholder seed checklists (5 items for VEHICLE, 4 for EQUIPMENT — see
  governance note below); `GoogleSheetsRepository` declares the Phase 3
  tab/header schemas and reports the same controlled not-configured error
  as Phase 2 until real credentials exist.
- API: `GET /api/v1/checklists/active`, `GET
  /api/v1/checklists/{id}/revisions/{id}`, `POST /api/v1/attachments`
  (multipart upload), `GET /api/v1/attachments/{id}/file`, `POST
  /api/v1/inspections`, `GET /api/v1/inspections`,
  `GET /api/v1/inspections/{id}`.
- Frontend: `ChecklistItemCard` (large PASS/FAIL/N/A controls, remark and
  evidence-photo controls appear immediately on FAIL, reference image
  shown separately from evidence), `InspectionFormPage`
  (`/vehicle/{id}/inspect`, `/equipment/{id}/inspect` — same component
  drives both asset types), `InspectionHistoryPage`
  (`/vehicle/{id}/inspections`), `InspectionDetailPage`
  (`/inspections/{id}`, read-only/immutable). "ตรวจเช็ค"/
  "ประวัติการตรวจเช็ค" entry points added to `VehicleDetailPage`/
  `EquipmentDetailPage`; the frozen `/vehicle/{id}`/`/equipment/{id}` QR
  routes themselves are unchanged.
- Backend tests (pytest, 72 total, 25 new), frontend unit tests (Vitest,
  29 total, 11 new), and 20 new Playwright inspection tests across all 5
  viewport projects (75 e2e tests total).
- **Governance**: `OPEN_DECISIONS_REGISTER_EN.txt` decisions D01
  (checklist assignment), D02 (daily/weekly scheduling), D03 (critical
  items), and D04 (correction/void policy) remain unresolved — none were
  approved or silently decided. See
  `docs/phase-results/web-phase-03-result.md` for how each was handled
  with a documented, reversible placeholder instead.

See `docs/phase-results/web-phase-03-result.md` for the full Phase Result
Report.

## Web/API Phase 2 correction — Equipment status vocabulary (resolves C02)

- `docs/phase-results/web-phase-02-verification.md` flagged an unapproved
  permanent decision: `Equipment.operational_status` had reused `Vehicle`'s
  `OperationalStatus` enum wholesale, contrary to
  `OPEN_DECISIONS_REGISTER_EN.txt` decision C02 ("Do not automatically
  reuse all vehicle statuses" for equipment).
- The user has now explicitly approved a separate equipment status
  vocabulary: `READY`, `IN_USE`, `MAINTENANCE`, `OUT_OF_SERVICE`
  (decision C02 in the register is updated from `TBD-BLOCKING` to
  approved/frozen for the status-code vocabulary only — transition rules
  remain undefined).
- Added `app.domain.equipment.EquipmentOperationalStatus` (backend) and
  `EquipmentOperationalStatus` (frontend `lib/types.ts`); `Equipment`/
  `EquipmentResponse` now use it instead of `OperationalStatus`. Vehicle's
  `OperationalStatus` (`WORKING`, `READY`, `MAINTENANCE`,
  `OUT_OF_SERVICE`, `LONG_TERM_PARKING`) is unchanged.
- Added Thai labels (`equipmentStatusLabel`/`equipmentStatusTone` in
  `frontend/src/lib/labels.ts`) and updated `EquipmentDetailPage`/
  `EquipmentListPage` to use them instead of the vehicle status label map.
- Updated `MockRepository` seed data (`EQP-0001` now seeded as `IN_USE`
  instead of the no-longer-valid `WORKING`; `EQP-0002`/`EQP-0003` were
  already valid values under the new vocabulary) and the declared Google
  Sheets `equipment` tab schema comment.
- New backend tests (`backend/tests/test_equipment_status.py`) prove
  equipment accepts all four approved statuses and rejects vehicle-only
  statuses (`WORKING`, `LONG_TERM_PARKING`) at the schema level, and that
  vehicle status behavior (including `LONG_TERM_PARKING`) is unchanged.
- Added Playwright `smartphone-landscape` (568×320) and `tablet-landscape`
  (1024×768) viewport projects, closing the responsive-coverage gap noted
  in the Phase 2 verification, without weakening the existing
  smartphone-portrait/tablet-portrait/desktop projects.
- See `docs/phase-results/web-phase-02-verification.md` for the full
  re-verification.

## Web/API Phase 2 — Vehicle, Model, Workshop Equipment, Asset References, and QR Detail

- Domain: `VehicleModel`/`ComponentRole` (with a dual-engine model
  demonstrating multi-engine support), `Vehicle`/`VehicleComponent`/
  `VehicleStatusHistoryEntry`, `Equipment`/`EquipmentCategory`, and the
  shared `AssetRef`/`AssetType` pattern for later inspection/repair/
  attachment records. `OperationalStatus` added to the shared domain
  conventions (`app.domain.common`).
- `Repository` extended (per its Phase 1 freeze note) with vehicle/model/
  component/status-history/equipment methods; `MockRepository` gets a
  full in-memory implementation and seed data (`VEH-1046`, matching the
  local-dev doc's QR example, plus a dual-engine vehicle and one with a
  deliberately blank serial number). `GoogleSheetsRepository` declares
  the Phase 2 tab/header schemas and implements the same interface,
  reporting a controlled not-configured/not-implemented error until real
  credentials exist (no Google credentials or network path exist in this
  environment to test live Sheets I/O).
- `VehicleService`/`EquipmentService` (domain/service layer) assemble the
  Vehicle Detail view and translate "not found" into the frozen error
  envelope, so later phases (Dashboard, alerts) can reuse them.
- API: `GET/{id} /api/v1/models`, `GET /api/v1/vehicles`,
  `GET/PATCH /api/v1/vehicles/{vehicle_id}` (machine_no — vehicle_id never
  changes), `PATCH .../status` (append-only history),
  `GET .../status-history`, `GET .../components`,
  `GET/{id} /api/v1/equipment`.
- Frontend: `VehicleListPage`/`VehicleDetailPage` (`/vehicle/:vehicleId` —
  the stable QR route) and `EquipmentListPage`/`EquipmentDetailPage`
  (`/equipment/:equipmentId`), a status-change dialog reusing the frozen
  dialog pattern, and Thai label/error-code mapping helpers
  (`lib/labels.ts`) — all built on the `Card`/`ResponsiveTable`/
  `FormField` primitives frozen in Phase 1, with no new layout patterns.
- Backend tests (pytest, 37 total, 28 new) and frontend tests (Vitest, 18
  total, 9 new) plus 18 new Playwright viewport tests (smartphone/tablet/
  desktop) covering the QR route, status change, search, and controlled
  404s.

See `docs/phase-results/web-phase-02-result.md` for the full Phase Result
Report.

## Web/API Phase 1 — Foundation, Local Development Stack, API Contracts, Repository Abstraction, Thai UI Shell

- Backend: FastAPI application (`backend/`) with `/api/v1/health` and
  `/api/v1/readiness`, a shared error envelope, request-id middleware,
  a development request/user context (`DEV_AUTH_MODE`), and OpenAPI docs.
- Repository abstraction (`Repository` interface) with a working
  `MockRepository` (fully offline) and a `GoogleSheetsRepository` base
  adapter (connectivity/config check only; no domain tables yet).
- `StorageProvider` abstraction with a working `LocalFileStorageProvider`.
- Frontend: React + TypeScript + Vite app (`frontend/`) with a Thai UI
  shell (nav, loading/empty/error/permission-denied states, confirm
  dialog, status badge, responsive layout) and a System Status page that
  calls the backend through the `/api` dev proxy.
- Backend tests (pytest, 9 tests) and frontend tests (Vitest + Testing
  Library, 3 test files) — both run fully offline.
- `docs/architecture/API_CONVENTIONS.md` documents the frozen API
  version/error-envelope/pagination/ID/date-time conventions and the
  Google Sheets -> PostgreSQL swap boundary.
- `scripts/` for local backend/frontend/test startup.

See `docs/phase-results/web-phase-01-result.md` for the full Phase Result
Report.

### Update: mobile-first / responsive foundation

Following a baseline/phase-file update mandating a mobile-first UI, added
to the same Phase 1:

- `frontend/src/index.css` rewritten mobile-first (base rules target
  smartphone portrait; `min-width` breakpoints at 481/641/1024/1280px
  only add rules for larger screens), with a `--tap-target: 44px`
  minimum touch target, 16px base font, and Thai text wrapping.
- `NavBar` gains a collapsible mobile menu toggle; always shown inline
  from tablet width up.
- New reusable components: `Card`, `ResponsiveTable` (CSS-only
  table-on-tablet+/stacked-cards-on-phone), `FormField` (full-width,
  touch-sized inputs) — documented in
  `docs/architecture/RESPONSIVE_UI.md`.
- `ConfirmDialog` is now a bottom sheet on phones and a centered dialog
  from tablet width up, always fitting the viewport.
- New Playwright suite (`frontend/e2e/`, `npm run test:e2e` /
  `./scripts/run_e2e_tests.sh`) verifies the shell at smartphone,
  tablet, and desktop viewports (no horizontal scrolling, 44px+ touch
  targets, working mobile nav, dialog fits viewport).
