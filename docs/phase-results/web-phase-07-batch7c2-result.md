# Web/API Phase 7 — Batch 7C2 — Structurally Checked Open-Repair Report — Batch Result

BATCH: Phase 7 Batch 7C2 (open-repair reporting view on the existing
"งานซ่อมค้าง" page and endpoint)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED CANDIDATE, AWAITING INDEPENDENT REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL** (this batch does not complete the Phase 7
reporting views — PM due, expiring certificate, offline device, lifetime
due and inspection failure remain — and closes no open decision)

Branch: `review/phase7-batch7c2-open-repair-report`, based on
`b7c74875b105bb9e47fec79f85e6ff78e722c66b` (Batch 7B2 integrated).

## 1. Requirement and implemented behavior

The Phase 7 prompt lists an "open repair" reporting view and requires that
users can find outstanding work without opening Google Sheets, with safe
partial/empty states, filters that do not mutate data, stable links and
Thai labels. This batch turns the existing `OpenRepairQueuePage`
(`/open-repair-queue`) and `GET /api/v1/repairs/open-queue` into a complete,
paginated, filterable report of OPEN repair **work orders**, and makes the
Google Sheets read fail closed on a broken repair_order structure instead
of silently returning a wrong list.

No new page, route path, dashboard card, KPI or navigation item was added.

## 2. Approved decisions (this batch only)

| Decision | Approved choice | Where implemented |
| --- | --- | --- |
| DEC-1 | Keep the existing `can_manage_repair` capability; no widening to `can_view`, no new roles | `list_open_repair_queue` — `require_capability(... CAN_MANAGE_REPAIR ...)` is still the handler's first statement |
| DEC-2 = **S** | Narrow structural validation of repair_order for this report only, reusing the 7B2 `GoogleSheetsClient.read_header_and_records` | `GoogleSheetsRepository.list_open_repairs_for_report` |
| DEC-3 | Record existing authorization gaps on other routes; do not change them; remediation deferred to authorization/M02 | characterization test + Section 7 |

DEC-2 = S consequences accepted by the user: every required repair_order
header must exist by exact name; data under an unnamed column blocks this
report; other legacy repair list routes keep their current read behavior;
record-value defaults are unchanged. This is **not** the 7B2
parity-or-fail identity/status policy (blank/duplicate ids and blank
status do not block this report).

## 3. API

`GET /api/v1/repairs/open-queue` — response shape unchanged:
`Page[RepairSummaryResponse]` (`items`, `page`, `page_size`, `total_items`).

| Parameter | Rule |
| --- | --- |
| `page` | integer ≥ 1, default 1 |
| `page_size` | integer 1..200, default 50 |
| `asset_type` | optional, `VEHICLE` or `EQUIPMENT` (new, additive) |

Population: repair work orders the existing mapper classifies OPEN, both
asset types unless filtered; `asset_type` is applied after the existing
mapping/defaults; CLOSED work orders excluded; Repair Requests, repair
actions, findings and distinct-vehicle counts are never combined with it
(a converted Repair Request contributes only its actual work order);
blank or duplicate repair ids stay counted (no deduplication);
`total_items` is computed before pagination. `action_count` and the
repair_action read are preserved.

Errors (existing envelope with `request_id`; no rows or totals in any error):

| HTTP | `error.code` | When |
| --- | --- | --- |
| 403 | `HTTP_ERROR` | caller lacks `can_manage_repair` (checked before any read) |
| 422 | `VALIDATION_ERROR` | invalid query (FastAPI validation, before the handler) |
| 500 | `REPAIR_ORDER_SCHEMA_INVALID` | proven repair_order structural problem; `details: {tab, problem, headers}`, `problem` ∈ `TAB_MISSING`, `NO_HEADER_ROW`, `MISSING_HEADERS`, `DUPLICATE_HEADERS`, `DATA_OUTSIDE_HEADER` (existing 7B2 constants/representation) |
| 503 | `REPAIR_ORDER_READ_FAILED` | not configured, read/API failure, warm cached worksheet failure, or a repair_action read failure |
| 500 | `INTERNAL_ERROR` | existing invalid enum/mapping errors, naive/aware timestamp sort failure, unexpected bugs (existing generic handler) |

`RepositorySchemaError` is handled before `RepositoryError` (it is a
subclass). The OpenAPI operation now also documents the 403/500/503
responses.

## 4. Implementation

Web → API → `RepairService` → Repository; the browser never touches Sheets.

- `Repository.list_open_repairs_for_report(asset_type, params)` (new,
  abstract, `base.py`).
- `MockRepository`: delegates to its existing `list_repairs` with
  `status=OPEN`, the optional `asset_type`, no `asset_id`, normal
  pagination.
- `GoogleSheetsRepository`: `_ensure_configured` →
  `read_header_and_records(REPAIR_SHEET)` (one values response; header
  validated on it before anything is filtered) → the canonical
  phantom-row predicate `_has_any_canonical_value` → the new private
  `_repair_summaries_from_rows` helper. `list_repairs` now calls the same
  helper after its unchanged `read_rows`, so mapping (`_repair_from_row`,
  unchanged), filtering, the assignment-history filter (legacy callers
  only), ordering, action-count hydration, summary construction and
  pagination cannot diverge between the two paths.
- `RepairService.list_open_repairs_for_report` (thin): error mapping only.
- Route: adds `asset_type`, calls the new service method.
- Not changed: `GoogleSheetsClient` (`read_rows`,
  `read_header_and_records`, `_validate_raw_structure`, header cache),
  `_repair_from_row` and its defaults, `RepairSummaryResponse`, every
  other route handler, App routes, NavBar, apiClient, dependencies,
  lockfiles, configuration, seeds and governance documents. No
  repair_assignment, repair_part, vehicle-master or equipment-master read
  was added to the report path.

### 4.1 Structural checks versus record-value defaults

| Checked structurally (report only, fail closed) | Unchanged record-value behavior (report and legacy) |
| --- | --- |
| tab present on a cold open | blank `status` → OPEN |
| a header row exists | blank `asset_type` → VEHICLE |
| all 17 repair_order headers present by exact name | invalid enum values (e.g. `Open`, `TRUCK`) fail the whole response (500 `INTERNAL_ERROR`) |
| no duplicate header names | blank / unparseable `opened_at` → 1970-01-01T00:00:00Z fallback |
| no non-blank data under an unnamed header cell or beyond the header width (one unused blank header tolerated, as gspread does) | naive and aware timestamps mixed → existing sort `TypeError` (500) |
| | numeric-looking `opened_at` (e.g. `2026`) numericised by gspread → existing `TypeError` (500) |

Why: with the legacy read, renaming every canonical header makes a
populated sheet look empty (false empty), and renaming only `status`
turns CLOSED work orders into OPEN ones through the blank-status default.
Both fixtures are now rejected by the report with
`REPAIR_ORDER_SCHEMA_INVALID` and no totals (tests
`test_all_canonical_headers_renamed_legacy_false_empty_report_rejects`,
`test_status_header_renamed_legacy_turns_closed_into_open_report_rejects`).

## 5. Ordering and compatibility

Both repositories' `list_repairs` now sort by `(opened_at, repair_id)`
descending, and the report shares that ordering.

- The tie-breaker also changes the order of equal-`opened_at` rows on
  legacy callers (`GET /repairs`, my-work, waiting-assignment, vehicle
  repair history, 7A indicators). Membership, totals, assignment-history
  filtering and response shapes are unchanged (tests
  `test_legacy_list_my_work_and_waiting_assignment_are_unchanged`,
  `test_legacy_assignment_history_filtering_is_preserved_over_sheets`,
  and the unchanged pre-existing suites).
- String ordering is intentional: numeric id suffixes are not
  interpreted (`SYN-RPR-2` sorts above `SYN-RPR-10`).
- Identical `(opened_at, repair_id)` pairs (duplicate ids at the same
  time) have no identity-based order.
- Offset pagination is not a snapshot: concurrent edits between page
  requests can shift rows across pages; the out-of-range state covers a
  page that became empty.
- No deduplication, no row-number identity, no timestamp normalization.

## 6. Web (`OpenRepairQueuePage`, modified in place)

- Title "งานซ่อมค้าง", the approved description and five scope notes
  (work-order units, system classification, blank-status / blank-asset-type
  defaults, Repair Requests excluded with a link to `/repair-request-queue`,
  time display rule).
- Filter "ประเภทสินทรัพย์" (ทั้งหมด | ยานพาหนะ | เครื่องมือ/อุปกรณ์); page size
  50; range "แสดงรายการที่ a–b จาก N ใบงานที่ระบบส่งกลับ"; pager
  ก่อนหน้า / หน้า p จาก P / ถัดไป (`aria-label` "เปลี่ยนหน้ารายการงานซ่อมค้าง");
  filter changes reset to page 1, page changes keep the filter; refresh
  "โหลดข้อมูลใหม่" is never disabled.
- Columns: เลขที่ใบงานซ่อม, วันที่เปิดใบงาน, สินทรัพย์, อาการ/ปัญหาที่พบ,
  ผู้รับผิดชอบ (ตามที่บันทึกในใบงาน). The existing assignment-field rendering
  is kept (primary technician `+n`, else "ยังไม่มอบหมาย"); the header says
  it is what the work order records, not an assignment-history
  projection. The constant OPEN status column was removed on this page
  only; shared `repairStatusLabel` and other screens are unchanged.
- Empty (unfiltered), empty (filtered), out-of-range (with
  "กลับไปหน้าแรก"), 403 (existing `PermissionDeniedState`), schema error
  ("ไม่แสดงรายการงานซ่อมค้าง") and other errors ("โหลดงานซ่อมค้างไม่สำเร็จ")
  with retry and request id; two additive `describeErrorCode` entries.
- Loading and errors hide all rows and totals; a request-generation guard
  applies only the newest request's success or error. No automatic retry.
- Links: `/repairs/{encodeURIComponent(repair_id)}`,
  `/vehicle/{…asset_id}`, `/equipment/{…asset_id}` from the original
  value. Blank/whitespace repair id → "(ไม่มีเลขที่ใบงาน)" without a link;
  blank asset id → "(ไม่มีรหัสสินทรัพย์)" without a link. A repair id
  repeated within the displayed page renders every row, suppresses each
  duplicate's repair link and shows "เลขที่ใบงานซ้ำในข้อมูล —
  เปิดรายละเอียดจากรายการนี้ไม่ได้"; rows and totals are never altered.
  Render keys are page positions via `ResponsiveTable.getRowKey`, not
  record ids. Duplicates across pages cannot be detected from one page.
  A referenced asset or repair that is missing from master data leads to
  the existing not-found states; no master-data lookup was added.
- Opened-at display (`formatRepairReportOpenedAt`, used only here):
  offset-bearing timestamps in `th-TH` with explicit `Asia/Bangkok`;
  timezone-less ISO text shown as stored plus "(ไม่ระบุเขตเวลา)"; the exact
  instant 1970-01-01T00:00:00Z shown as "ไม่มีวันที่เปิดใบงานที่อ่านได้" — a
  display convention only (the response cannot prove whether that value
  was the fallback or an explicitly stored date, and such rows are not
  guaranteed to sort last for arbitrary data); unparseable or impossible
  text shown raw (as text). `formatThaiDateTime` is unchanged. No age,
  days-open, overdue or duration is computed.
- Scoped CSS (`.open-repair-report__*`): long unbroken values wrap, so no
  horizontal overflow at any configured viewport.

Requests: one page-owned `GET /repairs/open-queue` per load, filter
change, page change, refresh or retry; no per-row calls. Measured in the
unmocked Playwright smoke on a first load in development mode: shell
`GET /me` = 2 and `GET /repairs/open-queue` = 2 in every viewport — both
doubled by React StrictMode's development mount repetition (only the
latest result is applied).

## 7. Known authorization gaps (DEC-3 — recorded, not remediated)

With dev auth disabled (anonymous context) on valid data:

- `GET /repairs?status=OPEN` is ungated and returns the OPEN population;
- `GET /repairs/my-work` passes `assigned_to=None` and so exposes the whole
  OPEN population through pagination;
- `GET /repairs/open-queue` returns 403.

`test_known_authorization_gaps_are_characterized_not_approved` pins this
as characterization of **existing gaps, not desired contracts**. Their
remediation is deferred to the authorization/M02 work (M02 remains
TBD-BLOCKING). Production authentication (M01) does not exist; the
capability checks pin current dev-auth behavior only.

## 8. Reads, writes and cost

- No writes: success, empty, filtered, out-of-range, validation,
  permission, schema-error, read-failure and mapping-failure paths were
  checked with zero repository write calls (mock spy), unchanged mock
  stored state, and zero non-GET transport requests with unchanged fake
  spreadsheet contents (Sheets). Filters, paging and refresh never write.
- A denied request performs zero transport requests (Sheets) and zero
  repository calls (mock).
- Existing action-history cost: every report page still reads the whole
  repair_action tab once to hydrate `action_count` (as `list_repairs`
  always has).
- Measured fake-transport request counts (real gspread 6.2.1 over a fake
  session; counts only, **no latency measured**):

| Path | Cold process | Warm process |
| --- | --- | --- |
| report | 3 metadata + 1 repair_order values + 2 repair_action values (header `row_values(1)` + `get_all_records`) | 1 repair_order values + 1 repair_action values |
| legacy `list_repairs(OPEN)` (comparison) | 3 metadata + 2 repair_order values + 2 repair_action values | 1 repair_order values + 1 repair_action values |

No other tab is read by the report. Live Google Sheets performance, live
error shapes and the consistency of one values response under concurrent
edits were **not** measured or validated (no live credentials used).

## 9. Files

Modified: `backend/app/api/v1/repairs.py`,
`backend/app/domain/repair_service.py`,
`backend/app/repositories/base.py`,
`backend/app/repositories/google_sheets/repository.py`,
`backend/app/repositories/mock/repository.py`,
`frontend/src/pages/OpenRepairQueuePage.tsx`,
`frontend/src/lib/labels.ts`, `frontend/src/index.css` (scoped report
styles; existing styles unchanged), `CHANGELOG.md`.

Added: `backend/tests/test_open_repair_report_batch7c2.py`,
`backend/tests/test_open_repair_report_sheets_batch7c2.py`,
`frontend/src/pages/OpenRepairQueuePage.test.tsx`,
`frontend/src/lib/labels.bangkok.test.ts`,
`frontend/e2e/open-repair-report.spec.ts`, this document.

## 10. Verification (fresh runs on the candidate working tree)

Installed versions (from the existing manifests/lockfiles, unchanged):
Python 3.11.15, gspread 6.2.1, pydantic 2.13.5, fastapi 0.141.1,
starlette 1.6.0, pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1;
Node 22.22.2, react 19.3.0, react-router-dom 7.18.3, vitest 5.0.0,
@playwright/test 1.63.0 (Chromium 141), typescript 6.0.3, vite 8.3.0,
oxlint 1.82.0.

| Check | Result |
| --- | --- |
| Backend `./scripts/run_backend_tests.sh` (full pytest) | PASS — 1266 passed (HEAD baseline 1171 + 95 new: 39 mock/service/API, 56 fake-Sheets); 140 warnings vs 130 at baseline — the 10 extra are the pre-existing `StarletteDeprecationWarning` (`HTTP_422_UNPROCESSABLE_ENTITY`) emitted by the existing validation-error handler for the 10 new invalid-query requests; no new application code emits a warning |
| Frontend `./scripts/run_frontend_tests.sh` (full vitest) | PASS — 39 files, 228 tests (baseline 37 / 208; +12 `OpenRepairQueuePage`, +8 formatter) |
| Frontend `npm run build` (tsc -b + vite build) | PASS on rerun. The first run failed (`TS2591: Cannot find name 'process'` in the new `labels.bangkok.test.ts`); fixed in that test file only by reaching `process` through a typed `globalThis` cast (no tsconfig/dependency change) |
| Frontend `npm run lint` (oxlint) | PASS — 0 errors; 33 warnings vs 34 at baseline; the only difference is the removal of the old `OpenRepairQueuePage` `set-state-in-effect` warning; no new warning |
| Playwright `open-repair-report`, `vehicle-search-partial-states` (7A), `fleet-status-dashboard` (7B2), `responsive-shell`, `vehicle-equipment` × 5 viewport projects | PASS — 115/115 (20 new: 3 mocked + 1 unmocked smoke × 5), 0 failed, 0 flaky, 0 retries |
| Backend lint | none configured in the repository (not added) |

Mutation checks (not part of the suite): replacing the position render key
with `repair_id`, or removing the generation guard, makes the
corresponding Vitest case fail.

Timezone coverage: the formatter tests run with the process zone set to
`America/Los_Angeles` inside the test file (UTC 02:15 → Bangkok 09:15,
date/year rollover, explicit offsets, naive values, epoch variants,
unparseable text); the Playwright spec runs the browser in
`America/New_York` (asserted) and checks Thai time is still shown. The
Playwright project list is unchanged.

## 11. Limitations and deferrals

- Blank or whitespace-only repair ids and duplicate repair ids detected
  within the displayed page have no repair-detail link. Duplicates across
  pages are not detected, so their links may remain available and may
  resolve to a different record sharing that id. Missing referenced
  records may lead to the existing not-found states.
- Timestamp limits listed in Section 4.1 remain (mixed naive/aware and
  numeric-looking `opened_at` fail the whole response; blank/unparseable
  values fall back to the epoch display).
- Legacy repair routes keep their unvalidated read (by decision).
- Authorization gaps in Section 7 remain open (DEC-3, M02).
- PM due, lifetime due, offline calculations, generated alerts,
  certificate reports, uploads, IoT and production authentication were
  not implemented. Phase 7 remains **PARTIAL**.
