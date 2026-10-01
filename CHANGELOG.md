# Changelog

## Web/API Phase 7 Batch 7L1 — Integrated verification and PARTIAL status reconciliation (documentation only; uncommitted candidate)

Phase 7 remains **PARTIAL**; this is not a closure. See
`docs/phase-results/web-phase-07-partial-result.md`.

- **Fresh integrated verification** at `5275b8f` (mock repository; Linux;
  Python 3.11.15; Chromium only): backend 2135 passed; frontend unit 374
  passed; build and lint exit 0 (33 lint warnings, same set as 7K2); full
  Playwright suite 430 passed (17 specs x 5 Chromium viewport projects).
  No live Google Sheets, Windows, other browser engines or realistic data
  volumes.
- **Documentation reconciliation**: batch report and CHANGELOG headings
  for 7B2-7K2 now name their integration commits (historical candidate
  wording kept); statements superseded by later batches are annotated;
  README points to the current phase reports.
- **Batch 7A** is recorded from its commit `8173c10` (vehicle list paging,
  filters and open-work indicators; four frontend files). It has no batch
  result report and no recorded test run of its own.
- No application, test, configuration or dependency file changed.

## Web/API Phase 7 Batch 7K2 — Equipment text preservation and safe status writes (committed `5275b8f`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. Implements the approved 7K1 corrected contract
with DEC-K1(b), K2(b), K3(a) (prefixes `=` `+` `-` `@` `'`), K4(a)-K8(a),
K9(b) and K10(a). See `docs/phase-results/web-phase-07-batch7k2-result.md`.

- **Reads** (equipment list, detail, status history and the equipment branch
  of every shared asset lookup): one single-response validated read; ids,
  codes, names, serials, category/status codes and the start date are read as
  text (e.g. "0012" stays "0012"); exact id matching; blank ids are never
  read; duplicate ids -> 409 `EQUIPMENT_ID_AMBIGUOUS`. A row with a
  blank/unrecognized category or status fails the whole list with per-row
  `issue_counts` (`EQUIPMENT_MASTER_DATA_INVALID`); blank and duplicate ids are
  still listed. Structural and read failures have their own codes. 7J2
  matching, filters, ordering, totals and paging are unchanged.
- **Status change**: validates the row, the response and the history tab
  structure first, then writes ONLY the `equipment_status` cell and appends
  history with forced-text fields (other cells and formulas untouched).
  Failures report `rejected` vs `unknown` outcomes; nothing is retried,
  compensated or re-read. History rows with bad status codes, and mixed
  naive/timezone-aware times (no reinterpretation), are coded errors.
- **New-work guard**: the eight enumerated mutating sites (PM work order,
  repair, part install, part transfer target, material request, position
  lifetime, inspection submit, inspection-equipment attachment upload) refuse
  an equipment id with a KNOWN text hazard (422
  `EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK`) before their first write. Read-only
  lookups are not guarded. The guard does not cover every application write
  (e.g. transfer SOURCE, part removal), and "not detected" is not "safe".
- **Frontend**: the equipment status dialog shows pre-write/rejected errors
  inline (values kept); unknown or partial outcomes show a persistent page
  warning and one separate refresh (failed refresh keeps the data with a
  stale notice and manual reload); a failed history load is shown as an
  error; Thai messages for every new code. No automatic retry.
- **Unchanged**: legacy repository equipment methods, generic Sheets client,
  vehicle paths, downstream writers/readers, authorization, dependencies.

## Web/API Phase 7 Batch 7J2 — Flexible vehicle and equipment search (committed `66fe2fe`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. Implements the approved 7J1 Final contract with
the owner's D-1..D-11 choices. See
`docs/phase-results/web-phase-07-batch7j2-result.md`.

- **Matching** (`app/domain/search_match.py`, one pure rule for both lists and
  both repositories): whitespace-separated terms, all of which must match
  (case-insensitive substrings, any order, each term may match a different
  field); identifier fields also match with spaces and `-` ignored ("TC13"
  finds "TC-13"); a Thai+ASCII-digit term such as "กลึง1" may match when all
  its parts occur in ONE name field ("เครื่องกลึงเบอร์ 1", and also "เบอร์ 10");
  a query of only `-` terms matches nothing. No numeric conversion ("0012"
  stays "0012"), fuzzy matching, transliteration or ranking.
- **Vehicles**: also searchable by model code and model name (model joined by
  exact `model_id`). A query with usable terms reads `model_master` once after
  the unchanged 7G2 validation (one extra values read on Sheets; never
  `maintenance_plan`); its failures return `MODEL_MASTER_SCHEMA_INVALID` /
  `MODEL_MASTER_READ_FAILED` without ids. Duplicate model ids: the whole query
  must match the vehicle plus ONE model row (D-8 RC).
- **Equipment**: also searchable by `equipment_id`; matching, category,
  ordering and paging now in `EquipmentService` over an unpaged read of the
  UNCHANGED legacy equipment read (D-6(a)): numeric-looking equipment values
  still fail the list as before (documented limitation; separate follow-up).
  *(7L1 note: superseded by 7K2, `5275b8f`.)*
- **Unchanged**: API paths/parameters/response shapes, ordering, totals,
  dashboard, 7H2 identity/writes, permissions, AssetSearchSelect behavior.
  The vehicle search label now mentions model search.

## Web/API Phase 7 Batch 7H2 — Vehicle text preservation (committed `47dec0a`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. Implements the approved 7H1 Final contract
(DEC-H1–H17 recommended package, DEC-H3(a), DEC-H8(b)). See
`docs/phase-results/web-phase-07-batch7h2-result.md`.

- **Reads** (VehicleService only — list, dashboard, detail, models,
  components, status history): one single-response validated read per tab;
  `vehicle_id`, `machine_no`, `model_id`, `serial_number`,
  `operational_status`, `model_id`/`model_code` and the model -> PM plan
  codes (`default_plan_code`, `plan_code`, `pm_plan_id`) are kept as exact
  text ("0012" stays "0012"; "01" and "1" are different plan codes).
  Dates are not protected. Status codes are still accepted only exactly.
- **Identity**: exact string match; blank/whitespace ids are not found;
  duplicate ids return 409 `VEHICLE_ID_AMBIGUOUS` on these paths.
- **Writes** (`PATCH /vehicles/{id}`, `PATCH /vehicles/{id}/status`):
  validated locate, source-row and intended-model validation and (for
  status) history-tab validation before ONE targeted batch update of only
  the changed cells (text forced); the history row is appended using the
  validated history header. Failures report `rejected` vs `unknown`
  outcomes; nothing is retried, compensated or re-read. A whitespace-only
  `machine_no` is rejected with 422; other values are stored unchanged.
- **Unchanged**: legacy repository methods and every non-VehicleService
  caller, frontend, authorization, date handling. Already-lost leading
  zeros are not recovered.

## Web/API Phase 7 Batch 7G2 — Vehicle search validation and asset picker hardening (committed `485c647`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**; N2 is **not** fully remediated. Approved
decisions DEC-1, DEC-2(a), DEC-3 (deferred), DEC-4–DEC-6, DEC-7(b),
DEC-8(b), DEC-9, DEC-10 of the 7G1 audit. See
`docs/phase-results/web-phase-07-batch7g2-result.md`.

- **API** (`GET /api/v1/vehicles`, same query parameters and
  `Page[VehicleResponse]`): the list now uses the fleet status summary's
  single validated vehicle-master read and whole-population gates before
  any filter or paging (shared private helper in `VehicleService`). One
  invalid record fails every list request: 500
  `VEHICLE_MASTER_DATA_INVALID` (details `issue_counts` only — no vehicle
  ids on this ungated route), 500 `VEHICLE_MASTER_SCHEMA_INVALID`
  (`tab`, `problem`, `headers`), 503 `VEHICLE_MASTER_READ_FAILED`. A blank
  status is no longer listed as READY; renamed/missing headers, stray data
  and an empty tab no longer give a false empty or all-READY list. The
  dashboard keeps its details, including `sample_vehicle_ids`. Numeric-
  looking `machine_no`/`vehicle_id`/`model_id` still fail (DEC-3 deferred).
  *(7L1 note: superseded for VehicleService paths by 7H2, `47dec0a`.)*
- **Web**: the vehicle list shows "ไม่แสดงรายการยานพาหนะ" with list wording for
  the data/schema codes (read failures keep "โหลดรายการยานพาหนะไม่สำเร็จ"); retry
  and stale-response guards unchanged. `AssetSearchSelect` (part install
  and transfer pickers): earlier options disappear as soon as the query or
  asset type changes, only the latest response is applied, a failed search
  shows a Thai error with "ลองค้นหาอีกครั้ง" (one request, no automatic retry), and
  an empty result is shown as such. Endpoints, `page_size=10` and the
  300 ms debounce are unchanged.
- **Unchanged**: repositories, Sheets client, legacy
  `Repository.list_vehicles`, vehicle detail and write paths, model reads,
  dates, authorization, shared labels/styles.

## Web/API Phase 7 Batch 7F2 — Equipment search completeness (committed `07205fd`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. Approved scope: option N1 of the 7F1 audit
only. See `docs/phase-results/web-phase-07-batch7f2-result.md`.

- **Web** (`/equipment`, frontend only): the existing
  `GET /api/v1/equipment` is now paged explicitly (50 per page) with
  "ก่อนหน้า"/"ถัดไป", backend `total_items`, range and applied-criteria echo;
  draft and applied filters are separate ("ค้นหา" applies q + category from
  page 1 — the category select no longer searches on change); "ล้างตัวกรอง";
  retry repeats the failed applied request; separate empty and out-of-range
  states; a request-generation guard; stale rows/totals hidden while loading
  or on error.
- **Links**: equipment detail links use the unchanged 7D2 whole-string
  ASCII-unreserved rule; unsafe, blank and in-page duplicate ids keep their
  text without a link; rows keyed by position.
- **Unchanged**: backend, API contract, shared components, other pages.
  Does not approve "type = model", any stored-alert decision, vehicle-search
  hardening or Phase 7 closure.

## Web/API Phase 7 Batch 7E2 — Recorded inspection findings report (committed `eef6a09`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. See
`docs/phase-results/web-phase-07-batch7e2-result.md` for the approved
decisions (DEC-A–G from the 7E1 Final contract), one menu-wording
deviation awaiting confirmation, and verification.

- **API**: new `GET /api/v1/reports/inspection-findings` (`asset_type`,
  inclusive Asia/Bangkok `created_from`/`created_to`, `page`, `page_size`
  1..200). One row per RECORDED finding (history — not outstanding work,
  unresolved defects, inspection or asset counts). Requires the existing
  `can_view` before any read. Disclosed partial results (`complete`,
  whole-read `population`, diagnosed-occurrence `data_issues`); 422
  `VALIDATION_ERROR` (`INVALID_DATE`, `AFTER_CREATED_TO`), 500
  `INSPECTION_FINDING_SCHEMA_INVALID`, 503 `INSPECTION_FINDING_READ_FAILED`
  carry no report data. `created_at` is returned as a UTC instant;
  `is_critical` is never returned.
- **Read-only**: one validated `inspection_findings` values read with the
  existing `text_only_headers` option (ids and titles keep leading zeros);
  no joins, writes, clock or lifecycle change. Row classification follows
  the approved contract exactly, including unrepresentable timestamps as
  row defects and the unchanged legacy mapper as a gate on field-clean rows.
- **Web**: new `/reports/inspection-findings`
  ("รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)") and a `can_view` menu item
  "ประวัติข้อบกพร่องที่บันทึกไว้"; separate draft/applied/response state,
  generation guard, Bangkok-time display, partial/empty/out-of-range/
  denied/error states, conservative inspection and asset links.
- **Unchanged**: legacy `/findings` and `/inspections`, inspection
  submission, the shared Sheets reader, readiness scope, repair linkage and
  the 7A indicator; their known gaps are characterized, not approved.

## Web/API Phase 7 Batch 7D2 — Read-only certificate expiry report (committed `e463154`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. See
`docs/phase-results/web-phase-07-batch7d2-result.md` for the approved
decisions (DEC 1–10, limited to this report) and verification.

- **API**: new `GET /api/v1/reports/certificate-expiry` (`mode`
  RANGE/MISSING_EXPIRY_DATE, inclusive `expiry_from`/`expiry_to`,
  `effective_status`, `page`, `page_size` 1..200). One row per certificate
  RECORD; stored ACTIVE/EXPIRED in scope, REPLACED and blank status
  excluded and counted. Omitted `expiry_to` = today's Bangkok date,
  resolved once per request. Requires the existing `can_view` before any
  read. Disclosed partial results (`complete`, whole-read `population`,
  occurrence-counted `data_issues`) for row-value defects; 422
  `VALIDATION_ERROR`, 500 `VEHICLE_CERTIFICATE_SCHEMA_INVALID`, 503
  `VEHICLE_CERTIFICATE_READ_FAILED` carry no report data.
- **Read-only**: one validated `vehicle_certificate` values read; no
  vehicle joins, no expiry reconciliation, no writes. Effective status is
  a pure predicate with parity tests against the existing service.
- **Shared reader**: `GoogleSheetsClient.read_header_and_records` gains an
  optional `text_only_headers` (default unchanged for 7B2/7C2), resolved
  on the same response's header; identifiers and document numbers keep
  leading zeros.
- **Web**: new `/reports/certificate-expiry` ("รายงานใบรับรองตามวันหมดอายุ")
  and a `can_view` menu item after "ภาพรวมกองรถ"; separate draft/applied/
  response state, dynamic blank end date, generation guard, partial/empty/
  out-of-range/denied/error states, Thai observation-only flags,
  UTC-explicit report date formatting, conservative vehicle links with the
  existing certificate page's read-side-write disclosure.
- **Known, unchanged gaps** (characterized, not approved): the existing
  per-vehicle certificate page and certificate get/create paths write
  EXPIRED on read, and the certificate routes are not capability-gated
  (M02 open).

## Web/API Phase 7 Batch 7C2 — Structurally checked open-repair report (committed `d6de62c`; reviewed as an uncommitted candidate)

Phase 7 remains **PARTIAL**. See
`docs/phase-results/web-phase-07-batch7c2-result.md` for the approved
decisions (DEC-1, DEC-2 = option S, DEC-3) and verification.

- **API**: the existing `GET /api/v1/repairs/open-queue` keeps its
  `Page[RepairSummaryResponse]` shape and `can_manage_repair` gate
  (checked before any read) and gains an optional `asset_type`
  (`VEHICLE`/`EQUIPMENT`) filter. It now goes through
  `RepairService.list_open_repairs_for_report`. New whole-response errors
  with no rows or totals: 500 `REPAIR_ORDER_SCHEMA_INVALID`
  (`details: {tab, problem, headers}`) and 503 `REPAIR_ORDER_READ_FAILED`.
- **Google Sheets**: the report reads repair_order with the 7B2
  `read_header_and_records` (header validated on the same values
  response before filtering), so renamed/missing/duplicate headers and
  data under unnamed columns fail instead of producing a false empty list
  or CLOSED rows defaulting to OPEN. Record-value defaults are unchanged
  (blank status → OPEN, blank asset_type → VEHICLE). Legacy repair list
  routes keep their current read behavior.
- **Ordering (compatibility)**: `list_repairs` in both repositories now
  orders by `(opened_at, repair_id)` descending; the repair_id string
  breaks equal-time ties on every legacy caller too. Membership, totals,
  assignment-history filtering and response shapes are unchanged.
- **Web**: `OpenRepairQueuePage` ("งานซ่อมค้าง") modified in place: page
  size 50, asset-type filter, pager/range/out-of-range state, latest-
  request guard, work-order units and scope notes, encoded repair/asset
  links with blank- and duplicate-id guards, Asia/Bangkok opened-at
  display for this report only. No new route, page, card or menu item.
- **Known, unchanged authorization gaps** (characterized, not approved):
  `GET /repairs?status=OPEN` is ungated and `GET /repairs/my-work` with no
  user exposes the OPEN population; remediation deferred to the
  authorization/M02 work.

## Web/API Phase 7 Batch 7B2 — Validated fleet status dashboard (committed `b7c7487`; reviewed as an uncommitted candidate)

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
  default is changed). *(7L1 note: superseded by 7G2, `485c647` — a blank
  status is no longer listed as READY.)*
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
