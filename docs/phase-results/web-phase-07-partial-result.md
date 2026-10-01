# Web/API Phase 7 — Dashboard, Search, Fleet Overview and Reporting Views — Whole-Phase Result (PARTIAL)

PHASE: Web/API Phase 7 — Dashboard, Search, Fleet Overview, and Reporting Views

STATUS: **PARTIAL**

This report records the integrated state of Phase 7 on
`web/phase7-dashboard-search-reporting` at
`5275b8f9708b54baf1f20cab09282c3395f7adb8`, as checked by Batch 7L1
(integrated verification and status reconciliation, 2026-10-01). It is
not a closure report. Phase 7 is **not** complete, CP7 is not frozen, no
production readiness is claimed, and Phase 8 has not started.

## OBJECTIVE

"Create a practical Thai fleet overview based on existing authoritative
services" (`docs/claude-prompts/web-api/07_PHASE7_DASHBOARD_SEARCH_REPORTING_EN.txt`).

## PREREQUISITE CHECK

Phase 6 handoff: `docs/phase-results/web-phase-06-result.md`. Phase 7 was
built incrementally in bounded batches; each batch report records the
decisions approved for that batch. Governance inputs:
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`,
`PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt` and
`CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`. 7L1 did not edit them.
No open decision is treated as approved by this report.

## BATCH PROVENANCE (committed and integrated state)

Every batch below was reviewed as an uncommitted candidate and then
committed to the integration branch. The batch reports keep the candidate
wording as history, plus a 7L1 note giving the integration commit.

| Batch | Commit | Date | Subject | Result report |
| --- | --- | --- | --- | --- |
| 7A | `8173c10` | 2026-09-23 | feat: improve vehicle search pagination and partial states | none (see below) |
| 7B2 | `b7c7487` | 2026-09-23 | feat: add validated fleet status dashboard | `web-phase-07-batch7b2-result.md` |
| 7C2 | `d6de62c` | 2026-09-23 | feat: complete structurally checked open repair report | `web-phase-07-batch7c2-result.md` |
| 7D2 | `e463154` | 2026-09-23 | feat: add read-only certificate expiry report | `web-phase-07-batch7d2-result.md` |
| 7E2 | `eef6a09` | 2026-09-29 | feat: add recorded inspection findings report | `web-phase-07-batch7e2-result.md` |
| 7F2 | `07205fd` | 2026-09-30 | feat: complete equipment search pagination and states | `web-phase-07-batch7f2-result.md` |
| 7G2 | `485c647` | 2026-09-30 | fix: validate vehicle search and prevent stale asset selections | `web-phase-07-batch7g2-result.md` |
| 7H2 | `47dec0a` | 2026-10-01 | fix: preserve vehicle text across validated reads and writes | `web-phase-07-batch7h2-result.md` |
| 7J2 | `66fe2fe` | 2026-10-01 | feat: add flexible vehicle and equipment search | `web-phase-07-batch7j2-result.md` |
| 7K2 | `5275b8f` | 2026-10-01 | fix: preserve equipment text and report status write outcomes | `web-phase-07-batch7k2-result.md` |

Contract and audit batches (for example 7I1, 7J1 and 7K1) changed no
repository files and have no commit.

**7A** is recorded only from its commit. Commit `8173c10` changed four
files:
- `frontend/src/pages/VehicleListPage.tsx`
- `frontend/src/pages/VehicleListPage.test.tsx`
- `frontend/src/index.css`
- `frontend/e2e/vehicle-search-partial-states.spec.ts` (new)

The changes cover:
- vehicle list paging and filters;
- per-vehicle open-work indicators from one list call per category (open repairs, open PM work orders, recorded open findings), where a failed or truncated read is never shown as zero (a successful but false-empty legacy read is not detected; see "Data-quality policies");
- request-generation guards against stale responses.

7A has no batch result report and no CHANGELOG entry of its own; none is
written now. No test run for 7A is recorded in the repository, so none is
claimed. Its code and tests are part of the integrated suites that 7L1 ran.

## FILES ADDED / FILES MODIFIED

The changes from `8173c10~1` to `5275b8f` (excluding docs) touch 69 files.
The per-batch file lists are in each batch report. Main additions:

- **Backend:**
  - `api/v1/dashboard.py`, `reports.py`, `report_schemas.py`, `dashboard_schemas.py`;
  - `domain/fleet_summary.py`, `certificate_expiry_report*.py`, `inspection_finding_report*.py`, `search_match.py`, `equipment_rules.py`, `equipment_errors.py`;
  - validated-read support in `repositories/google_sheets/client.py` and `repository.py`.
- **Frontend:**
  - `FleetStatusPage`, `CertificateExpiryReportPage`, `InspectionFindingReportPage`;
  - reworked `VehicleListPage`, `EquipmentListPage`, `EquipmentDetailPage`, `OpenRepairQueuePage`, `AssetSearchSelect`;
  - link helpers in `lib/`.
- **E2E specs:** nine new specs plus one changed.

## API ROUTES ADDED

New route paths added in Phase 7:
- `GET /api/v1/dashboard/fleet-status` (can_view) — 7B2.
- `GET /api/v1/reports/certificate-expiry` (can_view) — 7D2.
- `GET /api/v1/reports/inspection-findings` (can_view) — 7E2.

Existing routes enhanced in place (the path existed before Phase 7):
- `GET /api/v1/repairs/open-queue` — it existed before Phase 7 (added in
  `e5da7e7`, already gated by `can_manage_repair`). 7C2 kept the path,
  response shape and capability. It added the optional `asset_type`
  filter, structural repair_order validation for this report, coded
  errors and a shared ordering.
- `GET /api/v1/vehicles`:
  - 7G2: whole-population validation and coded errors;
  - 7H2: text-preserving reads;
  - 7J2: flexible `q` including model code/name.
- `GET /api/v1/equipment`:
  - 7F2: paging and states;
  - 7J2: flexible `q`;
  - 7K2: validated text reads and coded errors.
- Vehicle detail, model and status routes (7H2), and equipment detail,
  status and status-history routes (7K2): validated reads, targeted writes
  and documented coded errors. Their paths are unchanged.

## DATABASE / SHEET TABLES USED

Read: vehicle_master, model_master, equipment_master, the status-history
tabs, repairs, pm work orders, vehicle_certificates and
inspection/inspection_findings.

Written: Phase 7 added no new write paths or tables; 7H2 and 7K2 changed
the existing vehicle and equipment status/edit writes into targeted cell
writes.

No Phase 7 batch read or wrote live Google Sheets. Sheets behavior was
tested with gspread 6.2.1 over a fake transport.

## UI PAGES ADDED

New pages, each with one menu item:
- `/dashboard` (ภาพรวมกองรถ) — 7B2.
- `/reports/certificate-expiry` — 7D2.
- `/reports/inspection-findings` — 7E2.

Existing pages enhanced in place (no new route path):
- `/open-repair-queue` (`OpenRepairQueuePage`, existing since `e5da7e7`):
  7C2 turned it into the paginated, filterable open-repair report.
- `/vehicles` (`VehicleListPage`) — 7A, 7G2, 7J2.
- `/equipment` (`EquipmentListPage`) — 7F2.
- `/equipment/:equipmentId` (`EquipmentDetailPage`) — 7K2.
- The shared asset picker (`AssetSearchSelect`) — 7G2.

## REQUIREMENT COVERAGE MATRIX

Gap labels G01-G26 and owner questions Q1-Q10 refer to the Batch 7I1
exit-gate audit evidence (`Phase7_Batch7I1_Exit_Gate_Audit_Evidence_Final.txt`,
kept outside the repository); 7L1 re-checked the cited source locations at
`5275b8f`.

Dashboard items D1-D10 are optional per the prompt ("Dashboard may
include"); search/filter items, reporting views, acceptance tests and the
exit gate are requirements.

Status vocabulary:
- **implemented** — built and tested in the integrated state;
- **partial** — some of the requirement is met;
- **blocked** — needs an owner or business definition, or source data;
- **deferred** — explicitly reassigned by a recorded decision; none exists yet;
- **not verified** — not checked by any run.

| Req. | Requirement | Implementation / source | Batch | Verification evidence | Limitation | Status |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Total fleet and Working/Ready/Maintenance/Out of Service/Long-term Parking counts (K1-K6) | `GET /dashboard/fleet-status`; `domain/fleet_summary.py`; `FleetStatusPage.tsx` | 7B2, 7H2 | 7L1 fresh: backend suite, unit suite, `fleet-status-dashboard.spec.ts` in full e2e run | One invalid vehicle row fails the whole summary (approved fail-closed, G15); live data unverified | implemented |
| D2 | Engine hours, PTO hours, odometer | none in Phase 7 | — | grep: no Phase 7 card | Optional card; needs CP7 KPI decision (G09) | blocked (owner decision) |
| D3 | Online/offline, last seen | none | — | — | A05/I04/I07 undefined; no device data source (device data is Phase 8 scope; reassignment not approved) (G03) | blocked |
| D4 | PM due, PM overdue | none | — | — | E01-E05 thresholds/data not defined (G05); open PM work orders are not PM due | blocked |
| D5 | Lifetime parts due | none | — | — | G01/G02 data not supplied (G06) | blocked |
| D6 | Certificate expiry card | no card; report exists (R3) | — | — | Optional card (CP7, G09) | blocked (owner decision) |
| D7 | Open repair card | no card; report exists (R2) | — | — | Optional card (CP7, G09) | blocked (owner decision) |
| D8 | Inactive vehicle | none | — | — | "Inactive" not defined (G09) | blocked |
| D9 | GPS card | no fleet card (Phase 6 per-vehicle latest location only) | — | — | Optional card (CP7, G09) | blocked (owner decision) |
| D10 | Device/sensor alerts | none | — | — | Needs device telemetry and generation rules (G26) | blocked |
| S1 | Search by machine number | `GET /vehicles?q=`; `vehicle_service.py`, `search_match.py`; `VehicleListPage.tsx` | 7A, 7G2, 7H2, 7J2 | 7L1 fresh: backend suite; `flexible-search`, `vehicle-search-*` specs; owner-reported Windows 7J2 checks | 7J2 rules: all terms as substrings, no numeric conversion/fuzzy/ranking | implemented |
| S2 | Search/filter by model | model filter; model code/name search joined by exact `model_id` | 7A, 7J2 | 7L1 fresh: same as S1 | Search with terms fails if `model_master` is broken/unreadable (coded) | implemented |
| S3 | Filter by type | none | — | — | Meaning of "type" not defined; "type = model" not approved (G01/Q1) | blocked |
| S4 | Filter by status | `status` filter on `GET /vehicles` | 7A, 7G2 | 7L1 fresh: backend suite, `vehicle-search-*` specs | Exact status codes only | implemented |
| S5 | Filter by alert | none | — | — | Scope (vehicle-list filter vs stored-alert report) not approved; no alert generator (G02/Q2). A stored-alert report would not be a vehicle-list alert filter | blocked |
| S6 | Filter by online/offline | none | — | — | As D3 (G03) | blocked |
| S7 | Location when practical | none | — | — | No location field; GPS semantics undefined; "not practical now" must be a recorded finding (G04/Q4) | blocked |
| S+ | Workshop equipment search (supporting; equipment is not fleet vehicles) | `GET /equipment?q=`; `equipment_service.py`; `EquipmentListPage.tsx` | 7F2, 7J2, 7K2 | 7L1 fresh: `equipment-search-completeness`, `flexible-search`, `equipment-status-change` specs, backend suite | Equipment rows with blank/unknown category or status, or unmappable rows, fail the list; blank/duplicate ids are still listed (7K2 DEC-K2(b)) | implemented |
| R1 | PM due report | none | — | — | As D4 (G05/Q5) | blocked |
| R2 | Open repair report | existing `GET /repairs/open-queue` and `/open-repair-queue` page, enhanced in place | 7C2 | 7L1 fresh: `open-repair-report.spec.ts`, backend suite | Structural validation only; legacy record-value defaults retained (e.g. blank status → OPEN). Access is limited to `can_manage_repair` — a pre-existing rule kept by approved 7C2 DEC-1 (G25); an access restriction, not a defect | implemented |
| R3 | Expiring certificate report | `GET /reports/certificate-expiry`; `CertificateExpiryReportPage.tsx` | 7D2 | 7L1 fresh: `certificate-expiry-report.spec.ts`, backend suite | Row-value defects give a disclosed partial result that can hide matching records. The report is read-only, but its linked certificate page writes EXPIRED on read (G14, Phase 6) | implemented |
| R4 | Offline device report | none | — | — | As D3 (G03) | blocked |
| R5 | Lifetime due report | none | — | — | As D5 (G06/Q6) | blocked |
| R6 | Inspection failure report | `GET /reports/inspection-findings`; `InspectionFindingReportPage.tsx` | 7E2 | 7L1 fresh: `inspection-finding-report.spec.ts`, backend suite | Recorded findings history only (the approved R6 scope); a closure lifecycle would be additional scope (G07/Q7). Row-value defects give a disclosed partial result. The `inspection_findings` tab is unconfirmed live | implemented (as the approved recorded-findings report) |
| P1 | Summary endpoints; no unnecessary full-history scans | dashboard summary endpoint; one list call per category (7A); 7J2 fixed request counts | 7A, 7B2, 7J2 | Fake-transport request counts (historical, 7J2 `test_s05_*`, rerun in 7L1 backend suite) | Realistic data volume/timing not measured | implemented (timing not verified) |
| P2 | Frontend does not recalculate PM/lifetime | no PM/lifetime calculation in Phase 7 frontend changes | all | 7L1 grep of `8173c10~1..5275b8f` frontend diff | — | implemented |
| P3 | Responsive desktop/tablet/mobile | CSS + five Playwright Chromium viewport projects | all | 7L1 fresh full e2e run (5 projects) | Chromium viewport emulation only — not five browsers, not real devices | partial |
| A1 | Summary agrees with underlying services | parity-or-fail against `GET /vehicles` | 7B2 | 7L1 fresh backend suite | Live data unverified | implemented |
| A2 | Filters do not mutate data | list/report routes are GET-only | all | 7L1 fresh suites | Navigating from R3 to the certificate page triggers its write-on-read (G14) | implemented (residual G14) |
| A3 | Stable links to Vehicle Detail | report link helpers with conservative eligibility; vehicle list links | 7A, 7D2, 7E2 | 7L1 source check | Vehicle list builds links verbatim (`VehicleListPage.tsx:328-330, 426`, G11); legacy `get_vehicle` on vehicle subpages (12 call sites, G10) | partial |
| A4 | Thai labels | all Phase 7 pages | all | 7L1 fresh unit/e2e suites | — | implemented |
| A5 | No duplicate PM/lifetime formula | as P2 | all | as P2 | — | implemented |
| A6 | Safe partial/empty states | per-path policies (see "Data-quality policies"): whole-population fail-closed lists, structural-only open-repair checks, disclosed partial reports, 7A indicators shown as unknown rather than zero | 7A-7K2 | 7L1 fresh unit/e2e suites | Policies differ by path. Open-repair keeps legacy value defaults; partial reports can hide records (disclosed); 7A indicators cannot detect a false-empty legacy read; legacy and downstream reads unchanged (A-3, A-4) | implemented for the Phase 7 views (per-path policies) |
| A7 | Reasonable performance with prototype fleet data | — | — | none | No live or realistic-volume timing | not verified |
| X1 | Exit gate: find machines and outstanding work without opening Google Sheets | S1/S2/S4, equipment search, R2, R3, R6, per-vehicle open-work indicators | all | as above | No PM due/lifetime due; no fleet-wide open PM work-order view (DEC-PMWO not approved); R2 limited to `can_manage_repair` by approved design; G10 vehicles; G11 links | partial |
| W1 | Whole-phase result report | this report (PARTIAL) | 7L1 | — | Not a closure report | partial |
| W2 | README/CHANGELOG | reconciled in 7L1 | 7L1 | documentation diff | 7A has no CHANGELOG entry of its own | partial |
| W3 | CP7 freeze | — | — | — | Not frozen; KPI set beyond K1-K6 undecided | blocked (owner decision) |

Approved-scope clarifications:
- The findings report shows **recorded** findings history; a closure workflow would be additional scope.
- Open PM work orders are **not** PM due.
- A stored-alert report would **not** be a vehicle-list alert filter.
- Workshop equipment is **not** fleet vehicles.
- Flexible search follows the 7J2 rules: all terms must match, as substrings; there is no numeric conversion, fuzzy matching or ranking.
- The 7K2 new-work guard covers **only** its eight enumerated mutating sites. Downstream `asset_id` writers and readers keep legacy behavior, so not every downstream identifier is preserved.
- The five Playwright projects are Chromium viewport emulations, **not** five browsers.

## IMPLEMENTATION SUMMARY

What users can do now in the integrated mock-mode build:
- See fleet status counts that are checked to agree with the vehicle list.
- Search vehicles by machine number, id and model code/name, and filter by model and status.
- Search equipment by name, id and code, and filter by category.
- Open a vehicle's detail page from the list.
- See open repairs (repair managers only), expiring certificates and recorded inspection findings.
- See per-vehicle open-work indicators.

Data problems are handled by different, per-path policies (next
subsection). Not every Phase 7 path fails closed, and legacy false-empty
risks outside these paths were not removed.

### Data-quality policies (they differ by path)

- **Vehicle list and fleet dashboard** (7B2, 7G2, 7H2) — *whole-population
  validation, fail closed.*
  - The vehicle_master population is checked before any filter or paging:
    blank or unrecognized status, unmappable rows, blank or duplicate
    vehicle ids, and data outside the header.
  - Any one invalid record fails the whole response with a coded error;
    no partial list is shown.
  - A vehicle search with terms also depends on `model_master` (7J2 coded
    errors).
- **Equipment list** (7K2 DEC-K2(b)) — *whole-population validation for
  category and status only.*
  - A blank or unrecognized category or status, or an unmappable row,
    fails the whole list.
  - Blank and duplicate equipment ids are still listed. Detail and lookups
    refuse a duplicate id (409).
- **Open-repair report** (7C2 DEC-2 = S) — *structural validation only.*
  - These fail closed with coded errors: a missing tab or header row,
    missing or duplicate headers, and data outside the header.
  - Record-value semantics are retained unchanged:
    - blank status → OPEN;
    - blank asset type → VEHICLE;
    - blank or unparseable `opened_at` → epoch fallback;
    - invalid enum values or mixed naive/aware timestamps → generic 500;
    - blank or duplicate repair ids are still counted.
- **Certificate expiry report** (7D2 DEC 4 DQ = B) and **inspection
  findings report** (7E2 DEC-C) — *disclosed partial results.*
  - Structural and read failures fail the whole request.
  - Row-value defects do not. Readable rows are returned, defective rows
    are counted by issue code, and the response is marked incomplete with
    a partial notice.
  - A partial result can hide matching records; this is disclosed, not
    prevented.
- **7A vehicle-list open-work indicators** — a failed or truncated category
  read is shown as unknown, not as zero.
  - A read that succeeds but returns wrong data is not detected. The
    indicators use the legacy `/repairs`, `/pm/work-orders` and `/findings`
    list reads.
  - Legacy `/findings` has no structural check, so renamed headers give a
    false empty (7E2 §10). A zero indicator is therefore not proof that
    nothing is open.
- **Legacy and downstream reads** are unchanged by these policies:
  - the other repair list routes keep their legacy read, including the
    renamed-header false-empty risk recorded in 7C2 §4.1;
  - the legacy `/findings` list keeps no structural check (renamed headers
    → false empty), its legacy defaults, and whole-list failure on one bad
    row (7E2 §10, T30/T44);
  - legacy `get_vehicle` callers remain (A-3);
  - downstream `asset_id` readers may omit records stored in altered form
    (A-4, 7K2 §6).

## LOCAL STARTUP COMMANDS

Unchanged from earlier phases (see README "Local development"). Test
runners:
- `./scripts/run_backend_tests.sh`
- `./scripts/run_frontend_tests.sh`
- `./scripts/run_e2e_tests.sh` (starts the mock backend on 4311 and Vite on 4310)

## BUILD / TYPECHECK / LINT RESULT

Fresh in 7L1 at `5275b8f`:
- `npm run build` (`tsc -b && vite build`): exit 0. Only Vite's existing chunk-size advisory was printed.
- `npm run lint` (oxlint): exit 0 with 33 warnings. The warning lines are identical to the 7K2 final run.
- Backend type checking is not part of the repository's scripts and was not run.

## TESTS ACTUALLY PERFORMED

**Fresh in 7L1** (Linux container; Python 3.11.15, Node v22.22.2,
Playwright 1.63.0 with the pre-installed Chromium). Run on the integrated commit
`5275b8f` with a clean tree. Tracked-file hashes and `pip freeze` were
identical before and after.

| Command | Result | Exit |
| --- | --- | --- |
| `./scripts/run_backend_tests.sh -q -p no:cacheprovider` | 2135 passed, 211 warnings (149.67 s) — same counts as the 7K2 record | 0 |
| `./scripts/run_frontend_tests.sh` | 47 files, 374 tests passed | 0 |
| `npm run build` | built | 0 |
| `npm run lint` | 33 warnings, 0 errors | 0 |
| `npx playwright test --list` | 430 tests in 17 files (86 per project x 5 Chromium viewport projects) | 0 |
| `./scripts/run_e2e_tests.sh` (complete suite, repository configuration, 2 workers) | 430 passed (5.7 min), 0 failed, 0 flaky, 0 skipped | 0 |

Each command was run once. There were no failures, so there were no reruns and no failure classification was needed. Ports 4310/4311 were free before the run, so Playwright started its own mock backend and Vite server.

No earlier Phase 7 batch report records a run of all 17 specs together. This run includes `driver-phase6-batch1` and `model-document-revision`, for which no Phase 7 batch report records a run. It closes the 7I1 gap G19 for this commit and this environment only.

**Historical (not rerun as such):** the per-batch runs in each batch
report were made on the uncommitted candidates and keep their original
results, including recorded failures and their stated causes. Example: the
7E2 candidate regression attempt 2 failure, whose cause is unestablished.

**Owner-reported (Windows; recorded separately, not reproduced here):**
- Windows mock-mode smoke checks passed at the 7H2 baseline.
- All nine 7J2 flexible-search checks passed; clearing the filters returned three vehicles.
- Those runs used Python 3.12.4, not the procedure's 3.11.
- They do not verify 7K2 on Windows, live Google Sheets, large datasets or other browsers.

## TEST RESULTS

See the table above. Not performed in any Phase 7 batch, including 7L1:
- live Google Sheets;
- Windows at the integrated commit;
- browser engines other than Chromium;
- realistic data volumes or timing.

## SCREEN / UX NOTES

All new pages use Thai labels. Pages are mobile-first and tested at five
Chromium viewport sizes. Within the Phase 7 views, each path shows its
partial, empty and failed states according to its own policy (see
"Data-quality policies"):
- whole-population pages show an error instead of a list;
- the certificate and findings reports show a partial notice with the
  readable rows;
- the open-repair report fails only on structural problems and keeps the
  legacy value defaults;
- the 7A indicators show a failed or truncated category as unknown, not
  zero, but cannot detect a false-empty legacy read.

This is not a guarantee for every page: legacy and downstream reads keep
their earlier behavior, including possible omissions.

## TBD VALUES REMAINING

These need owner decisions (see the remaining-work register, group C):
- the meaning of "type";
- alert filter scope and generation rules;
- online/offline and last-seen definitions and data source;
- location semantics;
- PM due thresholds and data (E01–E05);
- lifetime due data (G01/G02);
- fleet-wide open PM work-order view and access;
- dashboard cards beyond K1–K6 (CP7);
- whether "outstanding work" needs a finding closure lifecycle.

## KNOWN LIMITATIONS

See the remaining-work register, groups A and B.

## REMAINING-WORK REGISTER

Each item lists: behavior; evidence; impact; smallest next action; owner decision needed?

### A. Implementation defects and limitations in existing functionality

- **A-1 Vehicle-list links are built verbatim (G11).**
  - Behavior: `VehicleListPage.tsx:426` (detail) and `:328-330` (repair/PM/finding indicator links) interpolate `vehicle_id` without encoding or an eligibility check. `VehicleDetailPage.tsx:46-47, 74, 94` also interpolate the route parameter into API paths.
  - Evidence: 7L1 source check at `5275b8f`. Report pages use `isLinkableVehicleId` (`lib/certificateReportLinks.ts`).
  - Impact: an id containing `/ ? # %` would open a wrong or broken page. Mock ids are plain; live ids are unverified.
  - Next action: a bounded correction contract covering link generation, routing and API interpolation together, or adopting the existing no-link rule. Encoding alone is not a proven fix.
  - Owner decision: yes (authorize the batch and choose the approach).
- **A-2 Findings indicator wording (G12).**
  - Behavior: "ข้อบกพร่องที่ค้าง" ("outstanding defects") at `VehicleListPage.tsx:94, 322, 578` counts recorded OPEN findings, but no closure lifecycle exists.
  - Evidence: 7L1 source check.
  - Impact: the label overclaims an "outstanding" state.
  - Next action: a wording-only correction (it does not need a closure lifecycle).
  - Owner decision: yes (approve the wording).
- **A-3 Legacy vehicle lookups on non-VehicleService paths (G10).**
  - Behavior: 12 `get_vehicle(` call sites use the legacy cached-header read without text protection. They are in:
    - `attachment_service.py:341`
    - `lifetime_rule_service.py:57`
    - `vehicle_certificate_service.py:21`
    - `daily_summary_service.py:150`
    - `pm_service.py:76`, `pm_service.py:173`
    - `inspection_service.py:200`
    - `vehicle_event_service.py:86`
    - `driver_service.py:125`
    - `alert_service.py:74`
    - `location_snapshot.py:211`
    - `asset_lookup.py:40`
  - Evidence: 7L1 grep. Historical 7H1 probe: `get_vehicle("0012")` returns None.
  - Impact: a numeric-looking vehicle id can be found and its detail opened, but its PM, inspection, certificate, alert and repair-creation pages return not-found.
  - Next action: first a live read check of whether such ids exist (B-5); then a bounded contract if needed.
  - Owner decision: yes.
- **A-4 Downstream identifier handling (7K2 guard scope).**
  - Behavior: the known-hazard guard covers only the eight enumerated mutating sites. Transfer SOURCE, part removal and other writers are unguarded. Downstream `asset_id` writers and readers keep legacy behavior.
  - Evidence: 7K2 report §2, §6; 7L1 source check of `asset_lookup.py`.
  - Impact: not every downstream identifier is preserved. Read-only views may omit records stored in altered form. Ids such as "2026-01-01" or "5%" are not detected.
  - Next action: an inventory/contract batch for downstream `asset_id` paths, if wanted.
  - Owner decision: yes.
- **A-5 Certificate page writes on read (G14, pre-existing Phase 6).**
  - Behavior: `VehicleCertificateService._reconcile_expiry` marks ACTIVE certificates past expiry as EXPIRED during get/list.
  - Evidence: `vehicle_certificate_service.py:30-47` at `5275b8f`.
  - Impact: navigating from the read-only R3 report to the certificate page can write to storage.
  - Next action: owner accepts it as a documented residual, or asks for a contract.
  - Owner decision: yes (Q10).
- **A-6 7K2 residuals.**
  - Behavior:
    - Date, percent and locale interpretation by Sheets is not detected.
    - A concurrent row/column move can misdirect a targeted write.
    - History ids can collide under concurrency.
    - Unknown write outcomes need a manual check (A09).
    - Already-lost leading zeros are not recovered.
  - Evidence: 7K2 report §6; 7H2 report.
  - Impact: prototype-storage risks.
  - Next action: accept as documented, or address in the storage phase.
  - Owner decision: yes (Q10).

### B. Verification gaps

- **B-1 Live Google Sheets.**
  - Behavior: no Phase 7 batch, including 7L1, has read or written live Sheets.
  - Evidence: every batch report; 7L1 used mock and fake transport only.
  - Impact: schema and data-quality assumptions are unproven live; the `inspection_findings` tab is unconfirmed.
  - Next action: isolated live validation on a dedicated test spreadsheet.
  - Owner decision: yes (B02/B03 decisions first).
- **B-2 Windows at the integrated commit.**
  - Behavior: the owner-reported Windows runs covered mock smoke at 7H2 and the nine 7J2 search checks, on Python 3.12.4. 7K2 and the integrated head `5275b8f` are not verified on Windows.
  - Evidence: owner report (recorded separately).
  - Impact: unverified platform; backend requirements are version ranges with no lockfile.
  - Next action: the owner reruns the Windows smoke at `5275b8f` (ideally with Python 3.11), including the equipment status change.
  - Owner decision: no (owner action only).
- **B-3 Other browser engines and real devices.**
  - Behavior: only Chromium viewport emulation has been used.
  - Evidence: `playwright.config.ts` projects; 7L1 inventory.
  - Impact: Firefox/WebKit/Safari behavior is unknown.
  - Next action: a bounded cross-engine run, or an owner acceptance of Chromium-only.
  - Owner decision: yes.
- **B-4 Realistic data volume and timing (A7).**
  - Behavior: no timing has been measured.
  - Evidence: none.
  - Impact: the "reasonable performance" acceptance test is not verified.
  - Next action: a timed run against a realistic prototype dataset, which needs the owner to supply or approve the size.
  - Owner decision: yes.
- **B-5 Live data quality.**
  - Behavior: one invalid vehicle row fails the list and dashboard for everyone (approved fail-closed, G15). Whether live ids are numeric-looking (A-3) or contain reserved URL characters (A-1) is unknown.
  - Evidence: 7B2/7G2 decisions.
  - Impact: usability depends on live data.
  - Next action: a read-only live data-quality check.
  - Owner decision: yes (as B-1).
- **B-6 Shared mock backend under parallel e2e.**
  - Behavior: all specs share one mock backend (`fullyParallel: true`), and some specs append state (e.g. equipment status history).
  - Evidence: spec comments; 7L1 full run (Section TESTS).
  - Impact: the 7L1 full run (2 workers, `fullyParallel: true`, `retries: 0`) passed 430/430, and specs are written to tolerate one another (per-project unique tags, same-status changes, fresh reads). One passing run is not proof of isolation under other worker counts or orderings.
  - Next action: none required now; if a failure appears later, classify it from its log before rerunning.
  - Owner decision: no.

### C. Owner decisions (from 7I1 Q1-Q10 plus one awareness item; none answered yet)

Not every item here is an unmet original requirement. Each item is labelled:
- **[unmet requirement]** — an original search/report requirement that needs a business definition;
- **[optional scope]** — an optional dashboard feature needing scope selection;
- **[exit-gate interpretation]** — what the exit gate requires;
- **[additional scope]** — beyond the original requirements;
- **[residual acceptance]** — acceptance of a documented limitation;
- **[access awareness]** — an implemented feature with an approved access rule.

- **C-1 (Q1) [unmet requirement] "Type" filter (S3):** define it (model? another attribute?) or record it as not needed.
- **C-2 (Q2) [unmet requirement] Alert filter (S5):** vehicle-list filter, separate stored-alert report, or reassign. No generator exists.
- **C-3 (Q3) [unmet requirement for S6 and R4; optional scope for D3] Online/offline (S6, R4, D3):** approve A05/I04/I07 and a data source, or reassign to Phase 8.
- **C-4 (Q4) [unmet requirement, "when practical"] Location (S7):** is it practical now? If so, which data and semantics.
- **C-5 (Q5) [unmet requirement for R1; optional scope for D4] PM due (R1, D4):** E01-E05 data and approvals, or reassign.
- **C-6 (Q6) [unmet requirement for R5; optional scope for D5] Lifetime due (R5, D5):** G01/G02 data, or reassign.
- **C-7 (Q7) Inspection findings.** R6 is implemented as the approved recorded-findings report; this is not an R6 gap.
  - [exit-gate interpretation] Does "outstanding work" require knowing which findings are unresolved?
  - [additional scope] Is a closure workflow wanted? It would need its own definition and approval.
- **C-8 (Q8) [exit-gate interpretation] Fleet-wide open PM work-order view:** required or not, and with what access rule. It is not PM due.
- **C-9 (Q9) [optional scope] CP7 KPI set:** any cards beyond K1-K6 (D2, D6, D7, D9; D8 is not defined).
- **C-10 (Q10) [residual acceptance]:** A-3 to A-6 and the M02 authorization gaps (D-2). The owner accepts each as a documented limitation or requests a bounded correction.
- **C-11 [access awareness] Open-repair report access (G25):** R2 is implemented. Its `can_manage_repair` restriction is a pre-existing access rule kept by approved 7C2 DEC-1, not an implementation defect. Other roles cannot see outstanding repairs through this report. This is recorded for the owner's view of the exit gate; nothing is proposed for change.

Impact by label:
- [unmet requirement] — the requirement stays unmet until defined and built, or disposed of by a recorded decision.
- [optional scope] — no requirement is unmet; the CP7 feature set stays open.
- [exit-gate interpretation] — the exit-gate assessment depends on the answer.
- [additional scope] — nothing is unmet if declined.
- [residual acceptance] — closure disclosure depends on it.
- [access awareness] — informational.

Next action: one owner decision round recording, per item:
- (a) define/approve;
- (b) an existing capability meets it;
- (c) reassign or defer, with a reason.

Owner decision: yes for C-1 to C-10. C-11 needs only acknowledgement.
No item is approved, deferred or reassigned by this report.

### D. Deferred / out of phase

No Phase 7 item has been reassigned or deferred by a recorded approval.
These are candidates only:

- **D-1 Device telemetry:** online/offline, last seen, offline-device report and device alerts. Device management is Phase 8 scope in the execution order, but a reassignment of D3/S6/R4/D10 is not approved.
- **D-2 Route authorization gaps (M02):**
  - Ungated routes:
    - `GET /vehicles`;
    - `/repairs` lists;
    - certificate routes;
    - `/findings`;
    - `/inspections`;
    - `/pm/work-orders`;
    - alerts and latest location.
  - RBAC is Phase 10 in the execution order; M02 is "TBD-BLOCKING before RBAC approval".
  - Not an original Phase 7 requirement, but must be disclosed at closure.
- **D-3 PostgreSQL production storage:** Phase 10. No production-readiness claim is made.

## RISKS / CONCERNS

- A single invalid vehicle row fails the vehicle list and dashboard for everyone (approved fail-closed design). Live data quality is unverified.
- Route authorization gaps (M02) remain until RBAC (Phase 10).
- Prototype storage concurrency: unknown write outcomes need a person to check the sheet.

## ANY CHANGE TO PREVIOUS FROZEN PHASES

Changes to existing behavior were approved per batch and are recorded in
the batch reports, for example:
- 7G2 validation of `GET /vehicles`;
- 7H2 and 7K2 targeted vehicle and equipment status writes with coded outcomes;
- 7J2 search matching.

7L1 changed no behavior.

## NEXT PHASE READINESS

**NOT READY.** Phase 7 remains PARTIAL. Closure needs work on several
tracks, which can proceed in parallel:
1. owner decisions for the unresolved business definitions and scope
   items (group C);
2. bounded implementation corrections where gaps need no business
   definition — for example A-1 link safety, which affects the "stable
   links" acceptance test and the exit gate, and A-2 wording;
3. verification work (group B), for example the "reasonable performance"
   acceptance test (B-4) and live data checks, and documentation work for
   W1 and W2 (W3, the CP7 freeze, needs C-9 first);
4. any implementation batches that follow from the decisions;
5. an explicit closure review with owner acceptance.

Recommended next bounded batch (not started):
- **A Phase 7 owner scope-decision package** — owner answers to C-1 to C-10 and acknowledgement of C-11, no code. It is needed for every item that depends on a business definition.
- **In parallel, if the owner prefers:** a small correction contract for A-1 (vehicle-list link safety) and A-2 (findings wording). These need no business definitions, and A-1 directly advances the "stable links" acceptance test.
- **Owner action:** the Windows mock smoke at `5275b8f` (B-2).

STOP. Phase 8 is not started.
