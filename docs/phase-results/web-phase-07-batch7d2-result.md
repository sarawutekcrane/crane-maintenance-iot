# Web/API Phase 7 — Batch 7D2 — Read-Only Certificate Expiry Report — Batch Result

BATCH: Phase 7 Batch 7D2 (certificate expiry reporting view)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED CANDIDATE, CORRECTED FOR ONE REVIEW FINDING (Section 11), AWAITING RE-REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL** (this batch adds only the certificate
expiry report; PM due, offline device, lifetime due and inspection failure
reports remain, the CP7 dashboard checkpoint is not completed, and no open
decision is closed)

Branch: `review/phase7-batch7d2-certificate-expiry-report`, based on
`d6de62c84f1ebd47b082a560e9b75cb6b5004cb9` (Batch 7C2 integrated; equal to
`web/phase7-dashboard-search-reporting` at preflight).

Design input: the reviewed 7D1 contract evidence
(`Phase7_Batch7D1_Certificate_Report_Contract_Review_Evidence_Final.txt`)
was **not available** in this environment and was not inspected. The
implementation follows the self-contained 7D2 implementation prompt, which
records the selected decisions, and the repository source.

## 1. Approved decisions (this report only)

| Decision | Approved choice | Where implemented |
| --- | --- | --- |
| DEC 1 SCOPE | One row per certificate record. Stored ACTIVE/EXPIRED in scope when readable; REPLACED and blank status excluded and counted; duplicates preserved | `certificate_expiry_report.classify_bucket`, `build_report` |
| DEC 2 HIST | Historical EXPIRED rows are never hidden; observations are flags only | `_flags`; no row is removed because another ACTIVE exists |
| DEC 3 WIN | User-selected inclusive range; omitted end = Bangkok today per request; no fixed window; `alert_lead_days` unused | `CertificateExpiryReportService.get_report` |
| DEC 4 DQ = B | Disclosed partial results for row-value defects; structural/read failures fail the whole request | `complete`, `population`, `data_issues`; 500/503 envelopes |
| DEC 5 AUTH | Existing `can_view` before any repository or Sheets read | `reports.get_certificate_expiry_report` (first statement) |
| DEC 6 NAV | New route + menu item; conservative links to the existing vehicle and vehicle-certificate pages, with the read-side-write disclosure | `App.tsx`, `NavBar.tsx`, `certificateReportLinks.ts` |
| DEC 7 CP7 | Population/data-issue counts are report disclosures, not KPIs; no dashboard card | page wording; `FleetStatusPage` untouched |
| DEC 8 READ | Optional `text_only_headers` on the shared validated reader; default unchanged for 7B2/7C2 | `GoogleSheetsClient.read_header_and_records` |
| DEC 9 REUSE | Pure effective-status predicate with parity tests; the reconciliation path is neither refactored nor invoked | `report_effective_status` |
| DEC 10 DQ-BLANK | Report-only absence: `None`/`""` absent; numeric zero, booleans, whitespace-only, unparseable dates invalid | `classify_status`, `classify_expiry` |

This approval does **not** freeze the wider M02 permission matrix, change
existing certificate route permissions, define a certificate legal-validity
or compliance rule, a required-certificate matrix, or an "expiring soon"
window.

## 2. API

`GET /api/v1/reports/certificate-expiry`

| Parameter | Rule |
| --- | --- |
| `mode` | `RANGE` (default) or `MISSING_EXPIRY_DATE` |
| `expiry_from` | optional `YYYY-MM-DD`, inclusive, RANGE only; omitted = no lower bound |
| `expiry_to` | optional `YYYY-MM-DD`, inclusive, RANGE only; omitted = `as_of_date` |
| `effective_status` | optional `ACTIVE` or `EXPIRED` |
| `page` | integer ≥ 1, default 1 |
| `page_size` | integer 1..200, default 50 |

Order inside the handler: `can_view` → mode conflict and strict date
parsing (no clock) → the injectable Bangkok clock is evaluated **exactly
once** → `expiry_from > resolved expiry_to` check → one repository read →
pure build. Date text must fully match `YYYY-MM-DD` and be a real calendar
date (compact, week, time-bearing, padded or newline-terminated forms are
422). Invalid enum/int values are rejected by FastAPI before the handler
(existing convention).

Success body: exactly the approved shape (`as_of_date`, `timezone`
`"Asia/Bangkok"`, `filter` echo, `items`, `page`, `page_size`,
`total_items`, `complete`, `population`, `data_issues`). For
`MISSING_EXPIRY_DATE` all date echo fields are null and
`expiry_to_is_default` is false. Items carry exactly `certificate_id`,
`vehicle_id`, `certificate_type_code`, `certificate_type_name_th`,
`document_no`, `expiry_date`, `stored_status`, `effective_status`,
`expiry_position`, `flags`. Every response model forbids extra fields;
`storage_ref`, `alert_lead_days`, notes, creator ids and raw invalid cells
are never returned (tested).

Errors (existing envelope with `request_id`; no rows, totals, population or
data_issues in any error):

| HTTP | `error.code` | When |
| --- | --- | --- |
| 403 | `HTTP_ERROR` | caller lacks `can_view` (before any read and before the clock) |
| 422 | `VALIDATION_ERROR` | invalid query; `details.errors[0]` carries `loc`, `msg`, `type`, `input` and, for report checks, `field` + `reason` (`INVALID_DATE`, `NOT_ALLOWED_FOR_MODE`, `AFTER_EXPIRY_TO` with `resolved_expiry_to` and `expiry_to_is_default`) |
| 500 | `VEHICLE_CERTIFICATE_SCHEMA_INVALID` | proven structural problem; `details: {tab, problem, headers}` (7B2 problem codes) |
| 503 | `VEHICLE_CERTIFICATE_READ_FAILED` | not configured, read/API failure, warm cached-worksheet failure |
| 500 | `INTERNAL_ERROR` | unexpected faults (existing generic handler) |

The unselected strict-data-error mode was not implemented.

## 3. Repository read and classification

`Repository.read_vehicle_certificates_for_report()` (new abstract method)
returns one `CertificateReportRow` per non-phantom record: `read_index`
(per-read position only), raw certificate/vehicle/type code/type name/
document/replacement texts, the original status and expiry inputs,
`status_class`, `stored_status`, `expiry_class`, parsed `expiry_date`,
`mapping_ok` and the mapped certificate.

- **Google Sheets**: `_ensure_configured` → `read_header_and_records(
  VEHICLE_CERTIFICATE_SHEET, text_only_headers=_CERTIFICATE_TEXT_ONLY_HEADERS)`
  (one values response; all 14 headers validated on it before phantom
  filtering or mapping; existing missing/duplicate/unnamed-column rules,
  single unused unnamed column tolerated, cold `TAB_MISSING` vs warm
  `READ_FAILED`) → the canonical phantom rule → per-row classification
  with the **unchanged** `_vehicle_certificate_from_row` and `_parse_date`.
  Only the `vehicle_certificate` tab is read; no vehicle join,
  reconciliation or write. One response is not claimed to be a
  transactional snapshot.
- **Shared reader (DEC 8)**: `text_only_headers` defaults to `()` (the
  exact previous call `numericise_all(row, False, "", False, [])`).
  Protected positions come from the header of the same response via the
  existing `_numericise_ignore_columns` (1-indexed, matching installed
  gspread 6.2.1 `numericise_all(..., ignore)` — verified by test).
  `read_rows`, the header cache and legacy callers are unchanged.
- **Mock**: iterates stored certificates in storage order, taking field
  values as stored (`None` → `""`, never `"None"`; enum → its value), and
  re-validates a copy through the unchanged model as its "mapper". It uses
  the same unchanged `GoogleSheetsRepository._parse_date` (lazy import), so
  mock and Sheets classify expiry identically.

Raw text: `None`→`""`; enum→stored value (checked before `str`, because
`str(CertificateStatus.ACTIVE)` is not `"ACTIVE"`); strings unchanged;
bool→`TRUE`/`FALSE`; int→decimal; float→`repr`; date/datetime→ISO;
anything else is a mapping defect with no invented identifier.

Status: BLANK only for `None`/`""`; VALID only for exact
`ACTIVE`/`REPLACED`/`EXPIRED`; everything else UNRECOGNIZED. Expiry: BLANK
only for `None`/`""`; booleans INVALID; otherwise VALID only when the
unchanged `_parse_date` returns a date (legacy-accepted compact/week ISO
forms, and a compact date numericised by gspread into an int, stay
valid); `0`, `0.0`, `"0"`, whitespace and unparseable text are INVALID.
Status, expiry and mapping are evaluated independently on every row; the
mapper runs on a copy in which only an unrecognized status is blanked; its
silent invalid-date→None behavior never overrides the report expiry class.
Mapper exceptions of type `ValueError`/`TypeError` (pydantic's
`ValidationError` is a `ValueError`) and `OverflowError` make the row
`UNMAPPABLE_ROW`; every other exception type propagates to the existing
error handling. Row defect codes are `UNRECOGNIZED_STATUS`,
`INVALID_EXPIRY_DATE` and `UNMAPPABLE_ROW`. (`OverflowError` was added by
the review correction in Section 11.)

## 4. Accounting, effective status, flags and order

Exclusive buckets (first match wins): ISSUE_UNKNOWN_STATUS →
EXCLUDED_REPLACED → EXCLUDED_STATUS_BLANK → ISSUE_IN_SCOPE_DEFECT →
IN_SCOPE. REPLACED/blank rows with other defects stay excluded and are
counted in `excluded_rows_with_other_defects`. Tested equations:
`read_record_count = in_scope + excluded_replaced + excluded_status_blank + issue_row_count`,
`in_scope = with_expiry + without_expiry`, `complete = (issue_row_count == 0)`.
Population and data issues describe the whole read, independent of
filters and paging; `total_items` counts matching readable IN_SCOPE rows
before pagination. `issue_defect_counts` counts occurrences among issue
rows only (codes overlap; never a record count). Samples: distinct,
plain-string-sorted non-blank original ids, max 20; blank/whitespace ids
are counted in `issue_rows_without_usable_id`.

Effective status (readable IN_SCOPE only): stored ACTIVE with expiry
strictly before `as_of` → EXPIRED; stored ACTIVE with today/future/no
expiry → ACTIVE; stored EXPIRED → EXPIRED. `expiry_position`:
BEFORE_TODAY / TODAY / AFTER_TODAY / NO_EXPIRY_DATE.

Groups use all readable IN_SCOPE rows before filters/pages (no-expiry rows
included) and only when the original vehicle id and type code are both
non-blank; original values are compared exactly (narrower than the legacy
exclusivity check, which also groups a `None` type code). Flags:
`SAME_TYPE_ACTIVE_EXISTS`, `MULTIPLE_ACTIVE_SAME_TYPE`,
`STORED_ACTIVE_PAST_EXPIRY`, `STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY`,
`LINK_PRESENT_ON_NON_REPLACED`, `DUPLICATE_CERTIFICATE_ID` (exact non-blank
id seen twice across ALL buckets), `BLANK_CERTIFICATE_ID`,
`BLANK_VEHICLE_ID`. `replaced_link_observations` counts excluded REPLACED
rows whose replacement reference is blank or absent from all non-blank raw
ids — an observation, not proof of a valid or invalid successor. When data
is incomplete, a missing group flag is not conclusive.

Order: RANGE — expiry, vehicle id, type code, certificate id, read_index;
MISSING — vehicle id, type code, certificate id, read_index; plain string
comparison; duplicates retained. Out-of-range pages return 200 with no
items and unchanged totals. Offset paging is not a snapshot.

## 5. Web

`/reports/certificate-expiry` → `CertificateExpiryReportPage`; menu item
"ใบรับรองตามวันหมดอายุ" right after "ภาพรวมกองรถ", shown only with
`can_view` (UX only; the backend enforces). `HomePage`,
`VehicleCertificatesPage`, `VehicleDetailPage` and `formatThaiDate` are
unchanged.

- Three separate states: draft form (editing sends nothing), applied
  request (set only by "แสดงรายงาน", which resets to page 1; reused by
  "โหลดข้อมูลใหม่", paging and retry), backend response (rows, totals,
  flags, disclosures, `as_of` and filter echo applied together). The
  echoed resolved end date is never copied into draft or applied state;
  "ใช้วันนี้อัตโนมัติ" only clears the end-date draft. MISSING submissions
  omit dates but keep the date drafts for later RANGE use.
- A request-generation guard applies only the newest request's success or
  error; loading and errors hide every part of an older response; refresh
  is never disabled.
- If a paging response has a different `as_of_date` than the page it came
  from, a notice says records may shift, repeat or disappear and offers
  "กลับไปหน้าแรก"; consistency across concurrent edits or midnight is not
  claimed.
- States: loading, denied ("ไม่มีสิทธิ์ดูรายงานนี้"), schema/read/
  validation errors (approved Thai texts; `AFTER_EXPIRY_TO` explained with
  the backend-resolved end date), partial banner + defect heading
  "ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)", partial-empty,
  complete-empty per mode/status filter, out-of-range. All approved scope
  disclosures are shown. Population counts are in a collapsible
  "จำนวนที่ใช้ประกอบรายงาน … ไม่ใช่ตัวชี้วัด" section.
- Dates use the new report-only `formatReportCalendarDate` (UTC-explicit;
  impossible dates shown as text). Thai labels for every flag, defect and
  position; stored/computed statuses reuse `certificateStatusLabel`.
- Links (`certificateReportLinks.ts`): only when the ORIGINAL vehicle id
  fully matches `^[A-Za-z0-9._~-]+$` (no multiline flag, so trailing
  newlines fail) and is not `.`/`..`: `/vehicle/<id>` "ดูรายละเอียดรถ"
  and `/vehicle/<id>/certificates` "ดูใบรับรองของรถคันนี้", no query
  strings. Otherwise the stored text is shown with
  "(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)". The
  destination disclosure "หน้าใบรับรองของรถเป็นหน้าที่มีอยู่เดิม เมื่อเปิด
  ระบบอาจบันทึกสถานะใบรับรองที่วันหมดอายุอยู่ก่อนวันนี้ให้เป็น 'หมดอายุ'"
  is always shown. Destination existence and global id uniqueness are not
  promised. Row keys are page positions.

## 6. Legacy / report differences and known gaps (unchanged by this batch)

- **Existing destination writes**: `GET /vehicles/{id}/certificates` (the
  "ดูใบรับรองของรถคันนี้" target), `GET /certificates/{id}` and ACTIVE
  creates reconcile stale ACTIVE rows by WRITING `EXPIRED`. Characterized
  by new tests (per-vehicle list writes; a truly past-expiry REPLACED row
  stays REPLACED; a missing vehicle is 404 before any reconciliation) and
  by a Playwright destination test. The report itself never writes.
- **Authorization gap**: the existing certificate routes are not
  capability-gated (a caller without `can_view` still gets — and can
  trigger writes through — `GET /vehicles/{id}/certificates`). Recorded
  and tested as a characterization, not changed (DEC 5; M02 remains open).
- Legacy reads treat `0`, `"0"`, `False` and unparseable dates as no
  expiry and whitespace/invalid status silently; the report classifies
  them as defects (DEC 10). Legacy grouping includes a `None` type code;
  the report does not group blank type codes.
- Numeric-looking values in unprotected columns (e.g. a type name `12`,
  `created_at` `2026`) are numericised by gspread and fail the unchanged
  mapper → `UNMAPPABLE_ROW` in the report (the legacy per-vehicle list
  would fail the whole request on such a row).
- Default validated-read behavior for 7B2/7C2 is unchanged: e.g. a
  numeric-looking vehicle id still makes the 7B2 dashboard fail closed.

## 7. Files

Added: `backend/app/domain/certificate_expiry_report.py`,
`backend/app/domain/certificate_expiry_report_service.py`,
`backend/app/api/v1/reports.py`, `backend/app/api/v1/report_schemas.py`,
`backend/tests/test_certificate_expiry_report_batch7d2.py`,
`backend/tests/test_certificate_expiry_report_sheets_batch7d2.py`,
`frontend/src/pages/CertificateExpiryReportPage.tsx`,
`frontend/src/pages/CertificateExpiryReportPage.test.tsx`,
`frontend/src/lib/certificateReportLinks.ts`,
`frontend/src/lib/certificateReportLinks.test.ts`,
`frontend/src/lib/labels.certificateReport.test.ts`,
`frontend/e2e/certificate-expiry-report.spec.ts`, this document.

Modified (additive): `backend/app/repositories/base.py`,
`backend/app/repositories/mock/repository.py`,
`backend/app/repositories/google_sheets/repository.py`,
`backend/app/repositories/google_sheets/client.py`,
`backend/app/api/v1/router.py`, `backend/app/dependencies.py`,
`frontend/src/App.tsx`, `frontend/src/components/NavBar.tsx`,
`frontend/src/components/NavBar.test.tsx` (two new cases; existing cases
unchanged), `frontend/src/lib/labels.ts`, `frontend/src/lib/types.ts`,
`frontend/src/index.css` (scoped `.certificate-expiry-report__*` styles),
`CHANGELOG.md`.

No additional test paths beyond the expected list were needed. Not
changed: legacy certificate domain/service/routes/schemas/pages, vehicle
detail, 7A/7B2/7C2 behavior, parsers/mappers (`_parse_date`,
`_vehicle_certificate_from_row`), seeds, API client, dependencies,
lockfiles, configs, governance files, hooks, README files.

## 8. Verification

**Freshness after the review correction (Section 11):** only the backend
was re-verified fresh on the corrected content. The backend row below is
superseded by Section 11.3. The frontend unit, build, lint and Playwright
rows are **historical** results from the reviewed candidate (2026-09-23,
before the correction). They were not re-run, because the correction
changes no frontend, API schema, dependency or configuration file (proven
byte-identical, Section 11.4).

Installed from the existing manifests/lockfile without upgrades
(`pip install -r requirements.txt`, `npm ci`): Python 3.11.15, gspread
6.2.1, pydantic 2.13.5, fastapi 0.141.1, starlette 1.7.0 (the unpinned
range resolved to 1.7.0 here; 7C2 recorded 1.6.0), pytest 9.1.1; Node
22.22.2, vitest 5.0.0, Playwright Chromium (pre-installed).

| Check | Result |
| --- | --- |
| Backend `./scripts/run_backend_tests.sh` (full pytest) — reviewed candidate, superseded by Section 11.3 | PASS — 1436 passed (HEAD baseline 1266 + 170 new: 137 mock/service/API/unit, 33 fake-Sheets). Warnings 158 vs 140 at baseline; the 18 extra all come from the new test file and are the pre-existing `StarletteDeprecationWarning` (`HTTP_422_UNPROCESSABLE_ENTITY`) raised by the existing `RequestValidationError` handler for FastAPI-level invalid queries. The new report code itself uses `HTTP_422_UNPROCESSABLE_CONTENT` and emits no warning |
| Frontend `./scripts/run_frontend_tests.sh` (full vitest) | PASS — 42 files, 260 tests (baseline 39 / 228; +20 page, +4 links, +6 labels/formatter, +2 NavBar) |
| Frontend `npm run build` (tsc -b + vite build) | PASS (the existing chunk-size advisory is unchanged) |
| Frontend `npm run lint` (oxlint) | PASS — 0 errors; 33 warnings, the identical file/rule set to the HEAD baseline. A draft of the page introduced one `set-state-in-effect` warning; fixed by the 7A/7C2 single-`setState` load pattern before the final run |
| Playwright `certificate-expiry-report` (new), `vehicle-search-partial-states` (7A), `fleet-status-dashboard` (7B2), `open-repair-report` (7C2), `responsive-shell`, `vehicle-equipment` × 5 viewport projects | PASS — 145/145 (new spec 30 = 4 mocked + 1 unmocked smoke + 1 destination characterization × 5; 7A 20, 7B2 25, 7C2 20, responsive-shell 20, vehicle-equipment 30), 0 failed, 0 flaky, 0 retries |
| Backend lint | none configured in the repository (not added) |

Frontend mutation checks (not part of the suite; each restored
byte-for-byte): removing the generation guard, keying rows by certificate
id, copying the resolved end date into the draft, making the menu item
unconditional, and adding the multiline flag to the link regex each make
the corresponding tests fail.

Measured fake-transport request counts (real gspread 6.2.1 client over the
7B2 fake session; counts only, **no latency measured**; test
`test_measured_request_counts_cold_spreadsheet_cached_and_warm`):

| Path | Expected | Measured |
| --- | --- | --- |
| cold process | 2 metadata + 1 values | 2 metadata + 1 `vehicle_certificate` values |
| spreadsheet cached, worksheet not | 1 metadata + 1 values | 1 metadata + 1 `vehicle_certificate` values |
| fully warm | 1 values | 1 `vehicle_certificate` values |

No other tab is read and no non-GET request is sent on any path. Live
Google Sheets performance, live error shapes and the consistency of one
values response under concurrent edits were **not** measured or
validated; no live Sheets or credentials were used. Dev-mode Playwright
first load (unmocked smoke, every viewport): shell `GET /me` = 2 and
`GET /reports/certificate-expiry` = 2 — both doubled by React StrictMode's
development mount repetition (only the latest response is applied).

## 9. Windows / PowerShell manual smoke test (mock data only)

**NOT RUN ON WINDOWS.** Derived from the repository setup instructions
(root README, `backend/README.md`, `frontend/README.md`, `.env.example`).
The Linux automation and fake-Sheets tests above do not validate a Windows
installation or live Google Sheets.

```powershell
# Terminal 1 — backend (mock data, dev auth)
cd <repo>\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATA_REPOSITORY = "mock"; $env:DEV_AUTH_MODE = "true"; $env:APP_ENV = "development"
uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — frontend
cd <repo>\frontend
npm ci
npm run dev   # http://127.0.0.1:5173

# Terminal 3 — optional API checks
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/certificate-expiry" | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/certificate-expiry?mode=MISSING_EXPIRY_DATE"
try { Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/certificate-expiry" -Headers @{ "X-Dev-Role" = "UNKNOWN" } } catch { $_.Exception.Response.StatusCode }  # expect 403
```

In the browser: open "ใบรับรองตามวันหมดอายุ" from the menu; the seed data
has no certificates, so expect the complete-empty message. Create one via
a vehicle's "เอกสาร/ใบรับรอง" page (this is a write, done only as setup),
reload the report, try both modes, a date range, the status filter,
refresh and paging, and confirm the links and Thai disclosures. Use mock
data only; do not point this procedure at the live spreadsheet.

## 10. Limitations and remaining Phase 7 gaps

- Partial results can hide matching records (disclosed); group flags are
  not conclusive when data is incomplete.
- Offset paging is not a snapshot; midnight between page requests is
  surfaced as a notice, not prevented.
- Existing destination read-side writes and the certificate-route
  authorization gap remain (M02 open).
- No live Sheets/latency/Windows validation (Section 8, 9).
- Remaining Phase 7 reporting views: PM due, offline device, lifetime due,
  inspection failure; CP7 is not complete. Phase 7 remains **PARTIAL**.

## 11. Review correction — non-finite `alert_lead_days` (finding 1)

### 11.1 Defect

`build_report_row` treated only `ValueError`/`TypeError` from the unchanged
certificate mapper as row defects. The unchanged legacy helper
`GoogleSheetsRepository._certificate_alert_lead_days_from_cell` raises
`OverflowError` for a non-finite value (`int(float("inf"))`,
`int(float("-inf"))`, `int(float("1e309"))`, or `int(inf)` for an input
that is already a float). Over Google Sheets, gspread numericises the
cells `"inf"`, `"-inf"` and `"1e309"` into float infinities, so one such
`alert_lead_days` cell aborted the whole report with HTTP 500
`INTERNAL_ERROR`. This happened even when the row's status was REPLACED or
blank. That contradicts DEC 4 (disclosed partial results for row-value
defects).

### 11.2 Narrow fix

`certificate_expiry_report.build_report_row` now also catches
`OverflowError` at the row-mapping boundary
(`except (ValueError, TypeError, OverflowError)`). Its docstring and
Section 3 now say so. The row becomes `UNMAPPABLE_ROW`, and the existing
exclusive bucket precedence applies unchanged:
- ACTIVE/EXPIRED → `ISSUE_IN_SCOPE_DEFECT`
- REPLACED → `EXCLUDED_REPLACED`, counted in `excluded_rows_with_other_defects`
- blank status → `EXCLUDED_STATUS_BLANK`, counted the same way
- unrecognized status → `ISSUE_UNKNOWN_STATUS` with both defect
  occurrences, counted as one issue row

Not changed:
- the legacy helper, the mapper, `_parse_date` and the certificate endpoints
- reconciliation, the shared Sheets reader and gspread numericising
- buckets, the API schema and the frontend

Invalid `alert_lead_days` values are not ignored or sanitized. Every other
exception type (programming faults such as `RuntimeError`, `KeyError`,
`AttributeError`, and transport errors) still propagates to the existing
500/503 handling.

### 11.3 Regression coverage and fresh backend results

New tests: 40 in `test_certificate_expiry_report_batch7d2.py` and 4 in
`test_certificate_expiry_report_sheets_batch7d2.py`.

- **Legacy helper (characterization, unchanged):** raises `OverflowError`
  for `inf`, `-inf`, `1e309` and the strings `"inf"`, `"-inf"`, `"1e309"`.
- **Focused row-mapping boundary:** already-numeric non-finite floats and
  the same strings × ACTIVE/EXPIRED/REPLACED/blank/unrecognized status,
  using the real repository mapper. Checks: `mapping_ok=False`, the correct
  bucket, the expected defect codes, and the raw id `0042` preserved.
- **Other exceptions still propagate:** `RuntimeError`, `KeyError`,
  `AttributeError` and `ZeroDivisionError` from the mapper still raise.
- **Real Sheets path through the report API** (installed gspread over the
  fake transport). Cells `"inf"`, `"-inf"`, `"1e309"`:
  - Mixed fixture (a valid row plus malformed ACTIVE, EXPIRED, REPLACED,
    blank and unrecognized-status rows): HTTP 200; only the valid row is
    shown; `complete=false`; `issue_row_count=3`;
    `excluded_rows_with_other_defects=2`; defects `UNMAPPABLE_ROW: 3`,
    `UNRECOGNIZED_STATUS: 1`; raw sample ids `00101`, `00102`, `00105`;
    equations reconcile; no writes; exactly one values read, of
    `vehicle_certificate` only.
  - All-unreadable in-scope fixture: `items=[]`, `total_items=0`,
    `complete=false`.
  - Excluded-only malformed fixture: `complete=true` in both modes.
  - A mapper `RuntimeError` still gives 500 `INTERNAL_ERROR` with no
    report data.

Fresh runs (commands, timestamps and logs are in the corrected evidence
file):

| Run | Code state | Result |
| --- | --- | --- |
| Targeted regression (`-k 'overflow or non_row_value or unexpected_mapper or all_unreadable_in_scope or excluded_only'`) | reviewed candidate + new tests, before the fix | FAIL, as intended — 33 failed, 11 passed (30 escaping `OverflowError`, 3 API responses 500 instead of 200) |
| Same targeted command | after the fix | PASS — 44 passed |
| Both 7D2 backend test files | final | PASS — 214 passed (170 + 44), 18 warnings |
| Full backend `./scripts/run_backend_tests.sh` | final | PASS — 1480 passed (1436 + 44), 158 warnings |

The warnings summary is identical to the reviewed run. The new
overflow tests add no warnings. The 18 warnings in the 7D2 file are still
the pre-existing `StarletteDeprecationWarning` from the existing
validation-error handler.

### 11.4 Scope of the correction

Relative to the reviewed candidate, only these files differ:
- `backend/app/domain/certificate_expiry_report.py`
- `backend/tests/test_certificate_expiry_report_batch7d2.py`
- `backend/tests/test_certificate_expiry_report_sheets_batch7d2.py`
- this document

The other 22 candidate files, including every frontend file, the API
schemas, the repositories and the client, are byte-identical to the
reviewed evidence (verified by extracting the reviewed blobs and comparing
bytes). No live Google Sheets was accessed; there is no Windows validation.
Phase 7 remains **PARTIAL**.
