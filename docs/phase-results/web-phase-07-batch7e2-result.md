# Web/API Phase 7 — Batch 7E2 — Recorded Inspection Findings Report — Batch Result

BATCH: Phase 7 Batch 7E2 (inspection-failure reporting view, as a recorded
inspection findings report)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**
(one wording deviation from the approved contract needs confirmation —
Section 2, DEC-E)

> **7L1 reconciliation note (2026-10-01).** This batch was committed as
> `eef6a0913855d4c047dbbbab6036927bed5c3a66` and is integrated on `web/phase7-dashboard-search-reporting`
> (checked at `5275b8f9708b54baf1f20cab09282c3395f7adb8`). The BATCH STATUS
> above is the historical status at review time and is kept as written;
> the "WHOLE PHASE 7 STATUS" paragraph lists what remained at that time.
> Verification results in this report are historical runs on the
> uncommitted candidate, not 7L1 runs. Fresh integrated results, the
> current coverage and remaining work are in
> `docs/phase-results/web-phase-07-partial-result.md`. Phase 7 remains
> **PARTIAL**.

WHOLE PHASE 7 STATUS: **PARTIAL** (this batch adds only the recorded
inspection findings report; PM due, offline device and lifetime due
reports remain, the CP7 dashboard checkpoint is not completed, and no open
decision is closed)

Branch: `review/phase7-batch7e2-inspection-findings-report`, based on
`e463154553eaa67e14e699208d9ec0bc58fa098e` (7D2 integrated; equal to
`web/phase7-dashboard-search-reporting` at preflight).

Design input: the approved 7E1 Final contract evidence
`Phase7_Batch7E1_Inspection_Findings_Contract_Review_Evidence_Final.txt`
(SHA-256 `66d74fc6e84a36ca439a77f0c6b6cd82a7471abd96daff0400a1c25728310192`,
129299 bytes, 2262 lines), verified before editing.

This report is **recorded history**. Nothing here verifies that a recorded
defect is still open, was fixed, or is outstanding work.

## 1. What the report is

`GET /api/v1/reports/inspection-findings` and the page
`/reports/inspection-findings` ("รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)")
list **one row per recorded inspection finding record** — the finding the
system wrote when an inspection item was submitted as FAIL. It is not a
count of failed inspections, assets, unresolved defects or inspection
coverage, and not a KPI. There is no finding closure path in the system
(FindingStatus has only OPEN; D04/F01/F02 remain TBD-BLOCKING), so
`recorded_status` is always `OPEN` as recorded at creation.

## 2. Approved decisions and traceability

| Decision | Approved choice | Where implemented |
| --- | --- | --- |
| DEC-A | One row per recorded finding record; finding records, not a joined FAIL-result population; `is_critical` never exposed or filtered | `app/domain/inspection_finding_report.py` (`build_report`), `report_schemas.py` (no `is_critical` field, `extra="forbid"`) |
| DEC-B | Existing `can_view` before any report read; legacy routes and auth unchanged; does not resolve M01/M02 | `reports.get_inspection_findings_report` (first statement) |
| DEC-C | Disclosed partial result with the Final 5.3 row algorithm; schema/read failures fail the whole request | `build_report_row`, `build_report`; 500 `INSPECTION_FINDING_SCHEMA_INVALID`, 503 `INSPECTION_FINDING_READ_FAILED` |
| DEC-D | Optional inclusive Asia/Bangkok calendar dates on `created_at`; no default range; no clock; date comparison with no next-day arithmetic | `inspection_finding_report_service._parse_query_date`, `inspection_finding_report._matches` |
| DEC-E | New API, new page, one `can_view` menu item, links only to inspection detail and vehicle/equipment detail with the unchanged 7D2 ID rule | `App.tsx`, `NavBar.tsx`, `lib/inspectionFindingReportLinks.ts` |
| DEC-F | Reuse `read_header_and_records(text_only_headers=...)` protecting finding_id, inspection_id, result_id, asset_id, item_title; shared reader unchanged | `GoogleSheetsRepository._INSPECTION_FINDING_TEXT_ONLY_HEADERS`, `read_inspection_findings_for_report` |
| DEC-G | Counts are report disclosures, not KPIs; no dashboard card, no Phase 7 closure | page wording "(ไม่ใช่ตัวชี้วัด)"; `FleetStatusPage` untouched |

**Deviation needing confirmation (DEC-E wording).** The Final contract
(4.4) names the menu item "ข้อบกพร่องจากการตรวจเช็ค". That exact text is
already the FINDING source label on the repair pages (`labels.ts`
`FINDING: 'ข้อบกพร่องจากการตรวจเช็ค'`). With the approved label, the
existing regression spec `e2e/pm-repair.spec.ts:124/129`
(`getByText('ข้อบกพร่องจากการตรวจเช็ค').first()`) resolved to the hidden,
collapsed menu link on the two smartphone projects and failed (initial run,
preserved in the review evidence). Rather than edit or weaken that existing
test, the menu item is **"ประวัติข้อบกพร่องที่บันทึกไว้"** ("recorded defect
history"); the page title and every other approved text are unchanged. If
the approved label is required, the alternative is to adjust the existing
pm-repair spec selector, which is outside this batch's file boundary.

## 3. API

| Parameter | Rule |
| --- | --- |
| `asset_type` | optional `VEHICLE` / `EQUIPMENT` (enum; invalid → FastAPI 422) |
| `created_from` | optional, inclusive Asia/Bangkok calendar date `YYYY-MM-DD` |
| `created_to` | optional, inclusive Asia/Bangkok calendar date `YYYY-MM-DD` |
| `page` | integer ≥ 1, default 1 |
| `page_size` | integer 1..200, default 50 |

Order: `can_view` → strict date parsing (whole string `[0-9]{4}-[0-9]{2}-[0-9]{2}`
and `date.fromisoformat`; accepted range 0001-01-01..9999-12-31; everything
else, including year 0000, compact/week/time-bearing/newline forms, is 422
`VALIDATION_ERROR` reason `INVALID_DATE`) → `created_from > created_to` →
422 reason `AFTER_CREATED_TO` → ONE repository read → pure build. The date
checks are done by the service (no FastAPI pattern) so every invalid date
carries the same machine-readable reason. No clock is read.

Response: `timezone` ("Asia/Bangkok"), `filter` echo, `items`
(finding_id, inspection_id, result_id, asset_type, asset_id, item_title —
original text, untrimmed; `recorded_status` "OPEN"; `created_at` as a UTC
instant; `flags` ⊆ DUPLICATE_FINDING_ID, BLANK_FINDING_ID,
BLANK_INSPECTION_ID, BLANK_RESULT_ID), `page`, `page_size`, `total_items`
(filtered, pre-page), `complete` (= no issue rows), `population`
(read_record_count = readable_count + issue_row_count, whole read), and
`data_issues` (diagnosed defect occurrences in canonical key order, rows
without usable id, ≤ 20 sorted distinct sample ids). Errors: 403
`HTTP_ERROR` (no read), 422, 500 `INSPECTION_FINDING_SCHEMA_INVALID`
(`details.tab/problem/headers`), 503 `INSPECTION_FINDING_READ_FAILED`, 500
`INTERNAL_ERROR` (unexpected). No error carries report data.

## 4. Row, date and mapper semantics (Final 5.3, implemented exactly)

- Only `inspection_findings` is read (one validated values response,
  headers checked on that same response before phantom filtering). No
  joins, per-row requests, writes, reconciliation or lifecycle change.
- Per non-phantom record: `read_index` = position among non-phantom rows;
  text fields converted with `text_value` (enum → value; `None` → "";
  strings unchanged; bool/int/float/date/datetime/other → unsupported);
  `asset_type`/`status` classified on original values (only `None`/"" are
  blank; anything but the exact allowed string is unrecognized);
  blank asset_id (""/whitespace/None) → `BLANK_ASSET_ID`; `created_at`:
  None/"" → MISSING; bool, whitespace, unparseable text, date, numbers →
  INVALID; naive → WITHOUT_TIMEZONE; aware but UTC or Asia/Bangkok
  conversion raises OverflowError → UNREPRESENTABLE.
- Field defects are unique, in canonical order. Only when a row has no
  field defect is the **unchanged** legacy mapper called once on
  `copy.deepcopy` of the original record (Sheets:
  `_inspection_finding_from_row`; mock: `InspectionFinding.model_validate`);
  its output is discarded. `ValueError`/`TypeError`/`OverflowError` →
  `UNMAPPABLE_ROW` (never co-occurring with field codes); anything else
  propagates to the generic 500. Explicit `None` in finding_id /
  inspection_id / result_id / item_title therefore becomes `[UNMAPPABLE_ROW]`
  via the real pydantic str check; ""/whitespace stay readable with blank
  flags / "(ไม่มีชื่อรายการ)"; `asset_id=None` is `BLANK_ASSET_ID` and skips
  the mapper; mapper-skipped rows carry only field-level codes.
- Partition by `read_index`; no deduplication by id; duplicate
  observations over all non-phantom rows (both buckets); samples are
  distinct usable ids of issue rows.
- Order: UTC instant DESC, finding_id text ASC, read_index ASC. Offset
  paging is not a snapshot. Out-of-range page → 200, empty items, totals
  unchanged.
- Dates: a readable row matches when `created_from <= bangkok_date <=
  created_to` (calendar-date comparison, zoneinfo conversion — historic
  LMT offsets apply to very old instants), so 9999-12-31 bounds never
  overflow.

## 5. Web

`/reports/inspection-findings` → `InspectionFindingReportPage`; menu item
"ประวัติข้อบกพร่องที่บันทึกไว้" after "ใบรับรองตามวันหมดอายุ", shown only with
`can_view` (UX only). Approved Thai title and seven scope notes, filters
(ประเภททรัพย์สิน; บันทึกตั้งแต่วันที่ / ถึงวันที่ — Thai calendar dates), buttons
แสดงรายงาน / ล้างเงื่อนไข (draft only) / โหลดข้อมูลใหม่, columns วันที่บันทึก
(เวลาไทย) | ประเภททรัพย์สิน | รหัสทรัพย์สิน (+ดูรายละเอียด) | รายการตรวจที่ไม่ผ่าน |
รหัสข้อบกพร่อง | ผลการตรวจ (ดูผลการตรวจ) | สถานะที่บันทึก | หมายเหตุข้อมูล.
Draft / applied / response states are separate; a request-generation guard
applies only the newest success or error; loading and errors hide every
part of an older response; refresh stays enabled. Times use an explicit
Asia/Bangkok formatter (`formatReportInstantBangkok`). Links use the
unchanged 7D2 rule; blank/ineligible ids are shown as stored with the
approved explanation; row keys are page positions. No repair action,
export, dashboard card, bulk action or mutation control. A small,
page-scoped CSS block was added to `index.css` because the only existing
report styles are prefixed with the 7D2 page's own block name.

## 6. Files

Classification derived from `git diff --name-status` against the base
commit and `git cat-file -e <base>:<path>` for each untracked path: 24
paths = 11 added (absent at the base) + 13 modified.

Added (11): `backend/app/domain/inspection_finding_report.py`,
`backend/app/domain/inspection_finding_report_service.py`,
`backend/tests/test_inspection_finding_report_batch7e2.py`,
`backend/tests/test_inspection_finding_report_sheets_batch7e2.py`,
`frontend/src/pages/InspectionFindingReportPage.tsx` (+ `.test.tsx`),
`frontend/src/lib/inspectionFindingReportLinks.ts` (+ `.test.ts`),
`frontend/src/lib/labels.inspectionFindingReport.test.ts`,
`frontend/e2e/inspection-finding-report.spec.ts`, this report.

Modified (13, additive): `backend/app/repositories/base.py`,
`backend/app/repositories/mock/repository.py`,
`backend/app/repositories/google_sheets/repository.py`,
`backend/app/api/v1/reports.py`, `backend/app/api/v1/report_schemas.py`,
`backend/app/dependencies.py`, `frontend/src/App.tsx`,
`frontend/src/components/NavBar.tsx`, `frontend/src/components/NavBar.test.tsx`,
`frontend/src/lib/types.ts`, `frontend/src/lib/labels.ts`,
`frontend/src/index.css`, `CHANGELOG.md`.

Unchanged by design: legacy `/findings` and `/inspections` routes,
inspection submission/finding creation, `_inspection_finding_from_row`,
`_parse_datetime`, `GoogleSheetsClient` (shared reader and defaults),
`schemas.py`, `_CORE_SCHEMAS` readiness, repair linkage/authorization, 7A
indicator wording, all other pages, dependencies, lockfiles, config, seed
data, governance and prompt files.

## 7. Verification (fresh, on the final candidate code)

Installed from existing manifests (`pip install -r requirements.txt`,
`npm ci`, no lockfile change): Python 3.11.15, gspread 6.2.1, pydantic
2.13.5, fastapi 0.141.1, starlette 1.7.0, pytest 9.1.1, tzdata 2026.4;
Node 22.22.2, npm 10.9.7, Playwright Chromium (pre-installed).

| Check | Result |
| --- | --- |
| Baseline before edits (HEAD) | backend 1480 passed, 158 warnings; frontend 42 files / 260 tests |
| Backend full pytest | PASS — 1763 passed (1480 + 283 new: 218 mock/service/API/unit, 65 fake-Sheets), 158 warnings (identical count to baseline; none from the new code) |
| Frontend vitest | PASS — 45 files, 286 tests (+3 files, +26 tests: page 17, links 2, labels 5, NavBar 2) |
| Frontend build (`tsc -b && vite build`) | PASS (existing chunk-size advisory unchanged) |
| Frontend lint (oxlint) | PASS — 0 errors, 33 warnings, findings identical to a lint run of the untouched HEAD copy |
| Playwright new spec × 5 projects | PASS — 30/30 |
| Playwright regression (7A, 7B2, 7C2, 7D2, inspection, responsive-shell, vehicle-equipment, pm-repair, web-uat-defect-fix) × 5 | Attempt 1: 2 failed (pm-repair, menu-label collision — fixed, Section 2). Attempt 2: 1 failed (inspection.spec FAIL-submit, smartphone-portrait; see below). Attempts 3 and 4: PASS 230/230 each |

Attempt-2 failure (existing test `e2e/inspection.spec.ts` "marking an item
FAIL…", smartphone-portrait), stated with its limits:

- One failure occurred, in candidate regression attempt 2 only; its log is
  preserved unchanged.
- The failure snapshot shows item 1's PASS selection absent while items
  2–5 were recorded, so the submit button stayed disabled.
- Source inspection shows an existing load path that can reset answers
  after a late response: `InspectionFormPage.load()` has no stale-response
  guard and calls `setAnswers(initialAnswers)` on every completion, and the
  development mount effect can run twice. This is a plausible explanation
  only; the causal sequence was not directly demonstrated (no request
  timing or render trace was captured).
- It did not reproduce in 15 isolated runs on the untouched baseline copy
  nor in 15 isolated runs on the candidate. One full baseline regression
  run and candidate attempts 3 and 4 passed.
- Therefore neither reproduction on the baseline nor independence from
  this candidate has been established.
- The existing page and test remain unchanged; no test was weakened.

Mutation checks (each restored byte-identically): calling the mapper on
defective rows, removing the text-only headers, removing the OverflowError
catch, removing the `can_view` check and removing the frontend generation
guard each make the corresponding tests fail.

Measured fake-transport request counts (real gspread 6.2.1 over the 7B2
fake session; counts only, **no latency**):

| Path | Metadata | Values (full-tab) | Tabs |
| --- | --- | --- | --- |
| cold process | 2 | 1 | inspection_findings |
| spreadsheet cached, worksheet not | 1 | 1 | inspection_findings |
| warm | 0 | 1 | inspection_findings |

Zero writes on every path; the process header cache is untouched. For
comparison the unchanged legacy `/findings` read is 2 metadata + 1
header-row read + 1 full-tab read cold, 1 full-tab read warm. Browser
(development server, unmocked smoke, every viewport): `GET /me` = 2 and
`GET /reports/inspection-findings` = 2 on first load — both doubled by
React StrictMode's development mount repetition; afterwards exactly one
report GET per submit/refresh/retry/page change. Live Google Sheets
requests, timing and error shapes were **not** measured.

## 8. T01–T70 traceability (7E1 Final Section 6.3)

Backend file A = `test_inspection_finding_report_batch7e2.py`, B =
`test_inspection_finding_report_sheets_batch7e2.py`; frontend page/unit
tests in `InspectionFindingReportPage.test.tsx` (P),
`inspectionFindingReportLinks.test.ts` (L),
`labels.inspectionFindingReport.test.ts` (Lb), `NavBar.test.tsx` (N);
Playwright `inspection-finding-report.spec.ts` (E). All listed tests pass
in the fresh runs above.

| ID | Test(s) |
| --- | --- |
| T01 | A `test_t01_one_fail_item_gives_one_report_row_pass_and_na_give_none` |
| T02 | A `test_t02_equipment_fail_gives_an_equipment_row` |
| T03 | A `test_t03_characterize_resubmission…`; B `test_t03_characterize_a_retried_sheets_submission…` |
| T04 | B `test_t04_characterize_failure_after_header_append_leaves_no_report_row` |
| T05 | B `test_t05_characterize_failure_after_result_append…` |
| T06 | A `test_t06_repair_from_a_finding_then_closed_leaves_the_row_unchanged` |
| T07 | A `test_t07_later_all_pass_inspection_leaves_earlier_rows_unchanged` |
| T08 | A `test_t08_repair_request_from_a_finding_leaves_the_row_unchanged` |
| T09 | B `test_t09_final_examples_are_reproduced_exactly` (EX1, 2A, 2B, 3–8), `test_t09_example_row_partition_by_read_index` |
| T10 | B `test_t10_mock_and_sheets_agree_on_genuine_data` (3 queries) |
| T11 | A `test_t11_partition_by_read_index_for_generated_mixes` (20 seeds) |
| T12 | A `test_t12_defects_are_unique_canonically_ordered_and_groups_exclusive` |
| T13 | A `test_t13_duplicates_span_both_buckets…` |
| T14 | A `test_t14_text_conversion_stage` |
| T15 | A `test_t15_unsupported_text_values_are_one_row_defect` (45 cases) |
| T16 | A `test_t16_code_field_classification`, `test_t16_enum_instances…` |
| T17 | A `test_t17_created_at_matrix` (19 cases) |
| T18 | A `test_t18_mapper_called_once_per_field_clean_row_and_never_otherwise` |
| T19 | A `test_t19_mapper_gets_an_unmodified_deep_copy_and_its_output_is_ignored` |
| T20 | A `test_t20_narrow_mapper_exceptions…`, `test_t20_other_mapper_exceptions_propagate`, `test_t20_other_mapper_exceptions_are_generic_500…` |
| T21 | A `test_t21_is_critical_never_changes_the_report_through_the_sheets_mapper`; renamed `is_critical` header in B `test_t31_t39…[is_critical]`. Scope: the Sheets mapper; T70b shows `model_validate` differs for injected dicts |
| T22 | A `test_t22_unrepresentable_timestamps_are_row_defects_not_request_failures` |
| T23 | A `test_t23_representable_extremes…`, `test_t23_extreme_readable_timestamps_serialize_as_utc_instants`; display in Lb |
| T24 | A `test_t24_all_rows_unreadable…`; B EX7; P all-unreadable state; E partial states |
| T25 | A `test_t25_extreme_query_dates_do_not_overflow` (5); B EX8 |
| T26 | A `test_t26_year_zero_is_invalid_date` |
| T27 | A `test_t27_overflow_outside_the_defined_catches_is_not_swallowed` |
| T28–T30 | B `test_t28…`, `test_t29…`, `test_t30…` (also pins the legacy false empty) |
| T31–T39 | B `test_t31_t39_each_single_required_header_renamed_is_schema_invalid` (9) |
| T40–T42 | B `test_t40…`, `test_t41…`, `test_t42…` |
| T43 | B `test_t43_text_only_columns_keep_leading_zeros_and_numeric_text`, `test_t43_unprotected_numericised_cells_are_classified` (7); B `test_shared_reader_default_and_legacy_reads_are_unchanged` |
| T44 | B `test_t44_characterize_legacy_findings_defaults…`, `test_t44_characterize_legacy_findings_whole_list_failure_on_one_row` (3) |
| T45 | B `test_t45_blank_inspection_id_is_flagged_and_only_the_findings_tab_is_read` |
| T46 | A `test_t46_bangkok_calendar_date_boundaries` (4) |
| T47 | A `test_t47_strict_date_parsing` (16), `test_t47_created_from_after_created_to` |
| T48 | A `test_t48_no_clock_is_read` |
| T49 | A `test_t49_denied_role_reads_nothing`, `test_t49_anonymous_context_reads_nothing`, `test_t49_every_can_view_role_is_allowed`; B `test_t49_denied_request_performs_zero_transport_requests` |
| T50 | A `test_t50_report_never_writes_or_uses_other_reads` (12 scenarios × 3 retries); B `test_t50_report_never_writes_and_reads_only_the_findings_tab` (8 × 6 queries) |
| T51 | A `test_t51_characterize_existing_ungated_inspection_routes` (characterization only) |
| T52 | A `test_t52_fixed_dataset_pages_cover_readable_rows_exactly_once` |
| T53 | A `test_t53_tie_order_instant_desc_then_finding_id_then_read_index` |
| T54 | P initial request/echo, editing/submit, refresh/retry/paging, clear-draft cases |
| T55 | P stale success, stale error cases; E slow-older-response |
| T56 | E `[destination characterization] …send no non-GET request on load` (×5) |
| T57 | L (2); P link rendering and suppression cases |
| T58 | P title/notes, rows/labels, partial, empty states, denied, errors, validation; Lb (5) |
| T59 | N `offers the recorded inspection findings report…`, `hides the recorded inspection findings report…` |
| T60 | E `[mocked]` menu/paging, partial/empty/out-of-range/links, errors/denied (×5, no horizontal overflow) |
| T61 | E `[unmocked smoke] … links round-trip to the same ids` (×5) |
| T62 | E `[mocked]` request-parameter sequence; smoke request counts (×5) |
| T63 | Regression Playwright run (attempts 3 and 4: 230/230) |
| T64 | Full backend pytest, vitest, build, lint (Section 7) |
| T65 | B `test_t65_measured_request_counts_cold_spreadsheet_cached_and_warm` + measurement log |
| T66–T69 | A `test_t66…`–`test_t69…` with the real mapper (3 values each) and `test_t66_real_pydantic_rejects_none_for_the_str_field`; B `test_t66_t69_blank_text_cells_over_sheets_are_readable_with_flags` (8) |
| T70 | A `test_t70a…`, `test_t70b…` (4), `test_t70c…` (3), `test_t70d…`, `test_t70_injected_none_through_the_mock_model_gate_is_unmappable` |

Coverage notes: T04/T05 use the existing in-memory `FakeWorksheet` with
injected failures for the writes and the real gspread fake transport for
the read-back; they characterize existing behavior, not live Sheets.
Counting parameterized cases does not add coverage beyond the listed
behaviors.

## 9. Windows / PowerShell manual smoke test (mock data only)

**NOT RUN** — this environment is Linux. The Linux tests and fake Sheets do
not establish Windows or live-Sheets readiness.

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
npm run dev

# Terminal 3 — API checks
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/inspection-findings" | ConvertTo-Json -Depth 6
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/inspection-findings?asset_type=EQUIPMENT"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/inspection-findings?created_from=0001-01-01&created_to=9999-12-31"
try { Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/inspection-findings" -Headers @{ "X-Dev-Role" = "UNKNOWN" } } catch { $_.Exception.Response.StatusCode }  # expect 403
try { Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/inspection-findings?created_from=2026-10-02&created_to=2026-10-01" } catch { $_.Exception.Response.StatusCode }  # expect 422
```

Browser: the mock starts empty → "ยังไม่มีข้อบกพร่องที่บันทึกไว้". As setup only
(a write), submit one FAIL inspection from a vehicle and one from an
equipment page; open "ประวัติข้อบกพร่องที่บันทึกไว้" from the menu; use the
filters, refresh, paging and both links at phone and tablet widths. Use
mock data only; never point this at the live spreadsheet.

## 10. Known, unchanged legacy exposures and data limitations

- Legacy `/findings`: no structural check (renamed headers → false empty),
  blank status → OPEN, blank/falsy asset_type → VEHICLE, blank/falsy
  created_at → epoch, one bad row fails the whole list (characterized by
  T30/T44; unchanged; the 7A indicator still uses it).
- Ungated legacy routes: `GET /findings`, `GET /inspections`,
  `GET /inspections/{id}`, `POST /inspections` (no capability check),
  checklists, `GET /repair-requests/{id}` (E1–E5; T51 characterization).
- Non-atomic inspection writes and no idempotency key (T03–T05); findings
  whose append failed are not visible to this report (disclosed on page).
- `inspection_findings` tab name is unconfirmed against the live sheet
  (B01) and not in readiness; the report fails honestly (TAB_MISSING) if
  absent. USER_ENTERED handling of `created_at` is unverified live.
- 7A indicator wording "ข้อบกพร่องที่ค้าง" still overclaims (not changed).
- Reference existence is not checked (no joins); links may reach an
  existing not-found state; duplicate inspection ids may merge on the
  destination.
- One unexplained intermittent failure of the existing
  `inspection.spec.ts` FAIL-submit test in candidate attempt 2; a plausible
  but undemonstrated cause is an existing `InspectionFormPage` load path that
  can reset answers after a late response. Baseline reproduction and
  independence from this candidate are not established (Section 7).
- Production authentication/RBAC (M01/M02) is not implemented; dev-auth
  headers are not production authentication.

## 11. Status

Uncommitted review candidate; empty index; no commit, push, merge, PR or
tag. CP7 not triggered; Phase 7 remains **PARTIAL**.

*(7L1 note: status at authoring time. The batch was later committed as
`eef6a09` and integrated; Phase 7 remains **PARTIAL**. Whether the DEC-E
wording deviation (Section 2) was confirmed is not recorded in the
repository.)*
