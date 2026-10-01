# Web/API Phase 7 — Batch 7G2 — Vehicle Search Validation and Asset Picker Hardening — Batch Result

BATCH: Phase 7 Batch 7G2 (first slice A0 of option N2, plus the DEC-8(b)
asset picker extension)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**

> **7L1 reconciliation note (2026-10-01).** This batch was committed as
> `485c647f9bf0bfc590d61c9cb165264cd36b3fe2` and is integrated on `web/phase7-dashboard-search-reporting`
> (checked at `5275b8f9708b54baf1f20cab09282c3395f7adb8`). The BATCH STATUS
> above is the historical status at review time and is kept as written;
> the "WHOLE PHASE 7 STATUS" paragraph lists what remained at that time.
> Verification results in this report are historical runs on the
> uncommitted candidate, not 7L1 runs. Fresh integrated results, the
> current coverage and remaining work are in
> `docs/phase-results/web-phase-07-partial-result.md`. Phase 7 remains
> **PARTIAL**.

WHOLE PHASE 7 STATUS: **PARTIAL**. N2 is **not** fully remediated:
numeric-looking `machine_no`, `vehicle_id` and `model_id` still fail
under A0 (DEC-3 deferred).
*(7L1 note: superseded for the VehicleService list and dashboard by 7H2,
`47dec0a`; legacy `get_vehicle` callers outside VehicleService are
unchanged — see the Phase 7 partial result report.)*

Branch: `review/phase7-batch7g2-vehicle-search-hardening` (local), based on
`07205fd257e480b9a1b94e770a176773a01acc82` (equal to
`web/phase7-dashboard-search-reporting` and
`review/phase7-batch7f2-equipment-search-completeness` at preflight).

Design input: `Phase7_Batch7G1_Vehicle_Search_Data_Quality_Contract_Review_Evidence_Corrected.txt`
(SHA-256 `d8c22303b32de2a8435b17668d92f56f4a579aa8d09a90a480331f4dd429a0b0`,
121555 bytes, 1885 lines).

## 1. Approved decisions

| Decision | Approved choice | Where |
| --- | --- | --- |
| DEC-1 | A0: structural-validation and failure-reporting hardening of `GET /vehicles` | `VehicleService.list_vehicles` |
| DEC-2(a) | Blank status fails validation (`BLANK_STATUS`); never READY | unchanged `classify_raw_status` via the shared read |
| DEC-3 | Text preservation DEFERRED to a coordinated read/detail/write batch | nothing changed in reads |
| DEC-4 | Existing `VEHICLE_MASTER_*` codes; list-specific Thai wording in `VehicleListPage` | `VehicleListPage.tsx` |
| DEC-5 | Vehicle detail and all write paths unchanged | — |
| DEC-6 | Existing date handling unchanged (non-ISO text still falls back) | — |
| DEC-7(b) | List `DATA_INVALID` details are `{"issue_counts": {...}}` only; the gated dashboard keeps `sample_vehicle_ids` | shared helper flag |
| DEC-8(b) | `AssetSearchSelect`: stale options, error presentation, response ordering including the debounce interval | `AssetSearchSelect.tsx` |
| DEC-9 | `/models` text preservation and list-link guarding out of scope | — |
| DEC-10 | Legacy `Repository.list_vehicles` and its tests retained (no longer used by the service) | — |

## 2. Behaviour changes

**`GET /api/v1/vehicles`** (query parameters, 422 behaviour and the
`Page[VehicleResponse]` success shape unchanged; still not capability-gated):

1. Exactly one `read_vehicle_master_for_summary` call per request (the 7B2
   validated read: header checked on the same response, same phantom-row
   rule, same `_vehicle_from_row` mapper; no text-only columns, no
   normalization, no writes, no per-row reads).
2. The 7B2 record and identity gates run over the WHOLE vehicle master
   before any filter or paging (`BLANK_STATUS` for None/""/whitespace-only;
   `UNRECOGNIZED_STATUS` for padded, case-variant, unknown and non-string
   values; `UNMAPPABLE_ROW` only for `ValueError`/`TypeError` from the
   unchanged mapper; `BLANK_VEHICLE_ID`; `DUPLICATE_VEHICLE_ID` counting
   every occurrence). Any issue fails every list request, whatever q,
   status, model or page.
3. Errors: `RepositorySchemaError` → 500 `VEHICLE_MASTER_SCHEMA_INVALID`
   `{tab, problem, headers}`; other `RepositoryError` → 503
   `VEHICLE_MASTER_READ_FAILED` (no details); record/identity issues → 500
   `VEHICLE_MASTER_DATA_INVALID` with details exactly
   `{"issue_counts": {...}}` and a fixed message ("vehicle_master contains
   records that cannot be listed exactly") — no vehicle id anywhere in the
   list error. Unexpected exceptions keep the generic 500 `INTERNAL_ERROR`.
4. On success: q = case-insensitive substring of `machine_no` or
   `vehicle_id` after `q.strip().lower()`; exact status and `model_id`;
   sorted by `vehicle_id`; `total_items` is the filtered count before
   slicing; a page beyond the end returns `[]` with the true total.

**Shared validation, different details.** `VehicleService` has one
private helper, `_read_validated_vehicle_master`, used by both
`get_fleet_status_summary` and `list_vehicles`; the only difference is
whether `sample_vehicle_ids` is added (dashboard: yes, unchanged; list:
no) and the fixed message wording. The repository-error mapping is one
module-level function, `vehicle_master_read_error`, used by the dashboard
method (identical results to before) and by the `GET /vehicles` route.

**Why the list's repository-error mapping sits in the route.** The
existing test
`backend/tests/test_google_sheets_repository.py::test_vehicle_domain_methods_report_not_configured_until_credentials_exist`
requires `VehicleService.list_vehicles` to raise a controlled
`RepositoryError` when Sheets is unconfigured. To keep that test
unchanged, the service lets `RepositoryError`/`RepositorySchemaError`
propagate and `backend/app/api/v1/vehicles.py` maps them with the shared
function (a `try/except RepositoryError` around the service call, plus
OpenAPI `responses=` for 500/503). This is the only handler-logic change;
reviewers may prefer the mapping inside the service with that test
updated under separate approval.

**Vehicle list page** (`VehicleListPage.tsx`): `VEHICLE_MASTER_DATA_INVALID`
and `VEHICLE_MASTER_SCHEMA_INVALID` show the title "ไม่แสดงรายการยานพาหนะ" with
the audit 5.2 list messages; `VEHICLE_MASTER_READ_FAILED` and every other
failure keep "โหลดรายการยานพาหนะไม่สำเร็จ" with the shared `describeErrorCode`
message (for READ_FAILED the unchanged `labels.ts` text). Request IDs,
retry of the applied request, pagination, filters, indicators and the
request-generation guard are unchanged; `labels.ts` is unchanged.

**Asset picker** (`AssetSearchSelect.tsx`, install and transfer panels of
the part instance page; vehicle and equipment):

- Each result is tagged with the search cycle it belongs to. A new cycle
  starts in the same render as every input transition (query edit, asset
  type change, selection made or cleared, including by the parent), and
  only a result from the current cycle is shown, so options disappear at
  once — during the 300 ms debounce, not only when the next request
  starts — and are never revived by returning to an earlier query or
  asset type (see the review correction below).
- A request generation counter is advanced on every input change, retry,
  selection and unmount; only the latest request's success or failure is
  applied (an older success cannot overwrite a newer success or failure;
  an older failure cannot clear a newer success; an old vehicle response
  cannot populate equipment options).
- States: "กำลังค้นหา..." (debounce or in flight); failure → "ค้นหายานพาหนะไม่สำเร็จ
  จึงไม่แสดงรายการให้เลือก" (or "ค้นหาเครื่องมือ/อุปกรณ์ไม่สำเร็จ ...") with a "ลองค้นหาอีกครั้ง"
  button (one immediate request for the current input; any pending
  debounce is cancelled; no automatic retry); empty success → "ไม่พบยานพาหนะที่ตรงกับคำค้น"
  / "ไม่พบเครื่องมือ/อุปกรณ์ที่ตรงกับคำค้น".
- Unchanged: endpoints, `page_size=10`, query trimming, 300 ms debounce,
  props, `onChangeAssetId(originalId)`, existing CSS classes only.
- Minor compatibility notes: no search runs while an asset is selected
  (previously a hidden search for "" ran after each selection); after
  "เปลี่ยน" a fresh search is made. The asset-type reset of the query now
  happens during render instead of in an effect.

## 3. Changed files

Modified: `backend/app/domain/vehicle_service.py`,
`backend/app/api/v1/vehicles.py`, `frontend/src/pages/VehicleListPage.tsx`,
`frontend/src/pages/VehicleListPage.test.tsx` (existing cases unchanged;
cases appended), `frontend/src/components/AssetSearchSelect.tsx`,
`CHANGELOG.md`.

Added: `backend/tests/test_vehicle_search_data_quality_batch7g2.py`,
`backend/tests/test_vehicle_search_data_quality_sheets_batch7g2.py` (imports
the unchanged 7B2 fake-transport harness), `frontend/src/components/AssetSearchSelect.test.tsx`
(did not exist before), `frontend/e2e/vehicle-search-data-quality.spec.ts`,
this report.

Unchanged: repositories, Sheets client, schemas, `fleet_summary.py`,
dashboard route/page, `labels.ts`, `apiClient`, App, NavBar, styles,
dependencies, lockfiles, configs, seeds, governance, earlier reports and
existing e2e specs.

**Review correction (asset picker stale state).** The reviewed candidate
rendered a stored result whenever its (asset type, query) text matched the
current input, so returning to an earlier query or asset type before a
replacement response (for example A → B → A within the debounce, or
VEHICLE → EQUIPMENT → VEHICLE with an empty query) revived the old options
as selectable, and an old failure reappeared as the current one. The
corrected component tags stored results with the current search cycle
(see above) instead of relying on text equality. Seven unit regression
tests (both asset types; query return, failure return, type round trips,
parent-driven selection) and one browser regression were added; they
failed on the reviewed component and pass on the corrected one. Only
`AssetSearchSelect.tsx`, its unit tests, the 7G2 e2e spec and this report
changed in the correction; the backend and the route error mapping are
unchanged.

## 4. Verification

Fresh on the corrected code (code hashes identical before and after):

| Command (working directory) | Result | Exit |
| --- | --- | --- |
| `npx vitest run src/components/AssetSearchSelect.test.tsx` (frontend) | 21 passed | 0 |
| `npm test` (frontend) | 47 files, 345 tests passed (baseline 46 / 319) | 0 |
| `npm run build` (tsc -b + vite build) | built; same >500 kB chunk notice as baseline | 0 |
| `npm run lint` (oxlint) | 0 errors; 33 warnings, identical set to baseline | 0 |
| `npx playwright test e2e/vehicle-search-data-quality.spec.ts` | 40 passed (8 tests × 5 projects) | 0 |
| `npx playwright test e2e/parts-lifetime.spec.ts` (install/transfer) | 25 passed | 0 |

Historical (reviewed candidate; the backend files are byte-identical, so
not rerun):

| Command (working directory) | Result | Exit |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q` (backend) | 1844 passed, 162 warnings (baseline 1763 passed, 158 warnings) | 0 |
| `npx playwright test` vehicle-search-partial-states, fleet-status-dashboard, vehicle-equipment, responsive-shell, parts-lifetime | 120 passed | 0 |

The 4 extra backend warnings are all from the new 422 test
(`StarletteDeprecationWarning` for the pre-existing
`HTTP_422_UNPROCESSABLE_ENTITY` constant in `app/errors.py`). Run against
the unchanged baseline code in a scratch copy, the new tests fail as
intended (backend 49 of 81; frontend 14 of 33 in the two touched files,
historical run before the correction).
No live Sheets, production data or Windows testing was performed.

Test coverage by plan item: G01 golden mock comparison (1,458 combinations; Sheets G04 540)
and query/order/paging semantics; G02 list ungated / dashboard gated; G03
one validated read, no legacy or per-row reads, no writes; G04 clean
120-row Sheets dataset equal to the legacy list; G05 ten structural
cases (never a false empty or all-READY list, same error as the
dashboard); G06 values-read failure, warm tab loss, unconfigured; G07
blank/whitespace/missing status; G08 padded/case/unknown/non-string and
all exact codes; G09 numeric-looking machine_no/vehicle_id/model_id
(still UNMAPPABLE_ROW); G10 blank and duplicate ids; G11 unexpected
exceptions propagate / generic 500; G12 80 seeded random datasets
(dashboard total vs unfiltered list, each status count vs status-only
list, or the same failure code and issue_counts); G12b filtered request,
counts only, audit 5.3 worked example (q=veh-2 → 1, unfiltered → 4,
status=READY → 2, dashboard 4); G13 cold 2 metadata + 1 values, warm 1
values; zero writes in eleven scenarios; G15 HTTP envelopes without page
data or ids; G16 list wording, retry of the applied request, stale
response guard; G17 browser: mocked error codes with recovery on five
viewports and one unmocked mock-backend smoke; G19–G22 picker: success →
failure, immediate hide before 300 ms, old response during debounce,
out-of-order success/success, success/failure and failure/success, type
switch, both asset types, one-request retry, original id on selection,
empty vs failure, GET-only, no write submission in the browser tests.

## 5. Remaining defects and limits (not addressed by this batch)

- Numeric-looking text (`machine_no`, `vehicle_id`, `model_id`, e.g. "12",
  "1046", "1,234") is still numericised by gspread and fails the whole
  list and dashboard (`UNMAPPABLE_ROW`) — the N2 text-preservation work
  (DEC-3) needs a coordinated read/detail/write batch.
  *(7L1 note: superseded for VehicleService paths by 7H2, `47dec0a`.)*
- Date fallback unchanged: non-ISO text timestamps still map to the epoch
  in both list and dashboard (DEC-6).
- Vehicle detail (`get_vehicle`/`find_row`) and vehicle writes are
  unchanged, including the recorded write hazard (audit 4.4) (DEC-5).
- `/models` reads and list link guarding unchanged (DEC-9).
- Authorization gaps unchanged: `GET /vehicles` remains ungated (M02); a
  single invalid record now blocks vehicle search for every caller until
  the data is fixed (only counts by issue code are shown; administrators
  use the gated dashboard for sample ids).
- Whole-Phase-7 items (DEC-T, alerts, PM due, lifetime due, offline,
  CP7 KPI freeze, live-Sheets and Windows validation) remain open.

Phase 7 remains **PARTIAL**.
