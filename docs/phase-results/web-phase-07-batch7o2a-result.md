# Web/API Phase 7 — Batch 7O2a — Registry and Branch Read Foundation — Batch Result

BATCH: Phase 7 Batch 7O2a (R1 registry/branch slice, read foundation only), implementing the 7O2a row of
`Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2.md` §11 and acceptance rows R-01 to R-12.
The binding Outcome Classification Addendum applies to the later write batches (7O2b/7O2c); nothing in it is
implemented here.

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7o2a-registry-read-foundation` (local), created from
`1d8e3beb62cafc36b0427c4434dddeac556c6748` (equal to `web/phase7-dashboard-search-reporting` at preflight).

Owner decisions A1–A6 (approved) are used as written. No live Google Sheets workbook was read or written. Only
synthetic mock data and a fake Sheets transport were used.

**Revision R1 (independent review fixes).** The first candidate (patch SHA-256 `7cf19081…a8ca8f`) received two
bounded findings. Both are fixed in this revision, and nothing else changed:
1. **Frontend response shape:** the history panels and the reference lists now validate every nested element and
   finite vocabulary of a 200 body. Before, only the top level was checked, so `events: [{}]` was accepted. See
   §3.5 and §7.3.
2. **Baseline on the first record only:** a later `ASSIGNMENT` that repeats a baseline, even the same one, is now
   `BRANCH_HISTORY_DATA_INVALID`. See §3.3.

## 1. What users can do now, and what comes later

**Now (read-only):**
- **Vehicle list:**
  - see each vehicle's registration number, registration province and responsible branch;
  - filter the list by responsible branch (an exact branch id, combined with status, model and search).
- **Vehicle detail:**
  - see the same three registry fields;
  - read two history panels: responsible-branch history, with its timeline, notes and all records with their
    request ids, and registration history.
- **Reference lists:** names come from `GET /branches` and `GET /provinces`.

**Later (not in this batch):**
- editing a registration (7O2b);
- branch transfer, insertion, correction, cancellation and reconciliation (7O2c);
- request ids on writes, the pending-intent store and settlement (7O2b/7O2c);
- integrated Playwright cost measurement (7O2d).

No write route, editor, dialog or active control for these exists in the candidate.

## 2. Trace and file plan (read-only subset of Rev2 §12)

The source trace covered:
- the validated vehicle reads (`read_vehicle_master_for_summary` and `_locate_vehicle` in the Sheets repository);
- the 7G2/7J2 list path (`VehicleService.list_vehicles`);
- the detail path (`get_vehicle_detail`);
- the error mappers (`vehicle_master_read_error`, `vehicle_path_error`);
- the `can_view` route pattern (`dashboard.py`, `reports.py`);
- the mock seams existing tests rely on: 7G2/7J2 override `read_vehicle_master_for_summary`, and 7H2 overrides
  `get_vehicle_validated`.

### Design choice for those seams

The mock's new registry reads go through the existing methods, so every existing seam keeps driving the list and
the detail. The Sheets repository gets its own single validated read, whose record loop matches the summary read
exactly; a parity test pins this.

### Added

**Backend domain** (`backend/app/domain/`):
- `registration.py`: RK1 and the pair rules; registration-history validation, consistency and the RHR1 token.
- `branch_timeline.py`: branch record validation (the §5.1 per-kind matrix and §5.2 rules), the BHR1 token and
  timeline derivation.
- `effective_time.py`: the §3.6 rules. They are defined now, but no 7O2a endpoint accepts an effective time.
- `vehicle_registry.py`: the `{state, value}` field model and reference parsing.
- `registry_errors.py`: coded registry errors.
- `registry_service.py`: the read service.

**Backend API** (`backend/app/api/v1/`):
- `registry_schemas.py`;
- `reference_data.py` (`GET /branches`, `GET /provinces`);
- `registry_routes.py` (the two history GETs).

**Backend tests** (`backend/tests/`):
- `test_registry_domain_batch7o2a.py`;
- `test_registry_read_api_batch7o2a.py`: HTTP only; it imports only modules that existed before 7O2a, so it also
  runs against the baseline;
- `test_registry_read_sheets_batch7o2a.py`: real gspread over the fake transport.

**Frontend:**
- `frontend/src/lib/referenceResolution.ts`, with a test;
- `frontend/src/components/RegistryHistoryPanels.tsx`, with a test;
- `frontend/src/pages/VehicleListPage.registry.test.tsx` and `VehicleDetailPage.registry.test.tsx`;
- `frontend/e2e/vehicle-registry-read.spec.ts`.

### Modified

**Backend:**
- `config.py`: `REGISTRY_DATA_CONTEXT` and `REGISTRY_TEST_BATCH_ID`; mock combined with REAL is refused.
- `vehicle_service.py`:
  - the shared gate helper;
  - `list_vehicles_with_registry` and `branch_id`;
  - detail through `get_vehicle_with_registry_validated`.
- `vehicles.py`: the `branch_id` query parameter and `registry` on list items and the detail vehicle.
- `vehicle_schemas.py`: the additive `VehicleWithRegistryResponse`. `VehicleResponse` and the PATCH responses are
  unchanged.
- `router.py`.
- `repositories/base.py`, `google_sheets/schemas.py` (four read schemas) and `google_sheets/repository.py`.
- `mock/repository.py` and `mock/seed_data.py`.

**Frontend:** `lib/types.ts`, `lib/labels.ts`, `pages/VehicleListPage.tsx` and `pages/VehicleDetailPage.tsx`.

**Tests:** two documented expectation updates (§6).

**Docs:** `CHANGELOG.md`, this report, and narrow updates to `web-phase-07-partial-result.md`.

### Unchanged

- `errors.py`, `client.py`, `authz.py` (`can_view` only), `search_match.py`, `fleet_summary.py` and the dashboard
  code;
- `_vehicle_from_row` and every legacy vehicle read and write;
- equipment paths;
- dependencies and lockfiles, build/lint/test configuration, governance documents and the roadmap.

## 3. Behavior

### 3.1 Vehicle list and detail (§7.1, §7.3, §7.6)

**Registry fields:**
- List items and the detail's `vehicle` gain `registry: {registration_no, registration_province,
  responsible_branch}`. Each is `{state, value}`:
  - `NOT_IN_SCHEMA`: the column is absent from the validated header;
  - `NOT_RECORDED`: the cell is blank or whitespace-only;
  - `RECORDED`: `value` is the stored text exactly, never trimmed or numericised (`0012` stays `0012`).
- Registry text is read text-only and never fails mapping. The whole-population gates, list totals and dashboard
  K1–K6 are therefore unchanged. The dashboard read does not map registry fields at all.
- A seven-column `vehicle_master` keeps working. Every field is `NOT_IN_SCHEMA`, and the full detail page loads.

**Branch filter (`branch_id`):**
- one value, 1–100 characters; an empty value gives 422 `VALIDATION_ERROR`;
- exact, case-sensitive match on the stored cell, with no trim and no reference lookup;
- ANDed with `status`, `model_id` and `q`, after the unchanged gates;
- sort by `vehicle_id`; `total_items` after all filters; paging after filtering;
- given while `responsible_branch_id` is not in the header → 409 `VEHICLE_BRANCH_FILTER_UNAVAILABLE`
  (details: `column`);
- the 7J2 `q` rules and the model-read rule are unchanged, and read failures map exactly as before.

### 3.2 Reference lists (§7.2)

- `GET /branches` → `{"items": [{branch_id, branch_name, is_active}]}`.
- `GET /provinces` → `{"items": [{province_code, province_name_th, is_active}]}`.
- Both require `can_view` and return items sorted by code.
- Errors:
  - 500 `<BRANCH|PROVINCE>_MASTER_SCHEMA_INVALID` (details: tab, problem, headers);
  - 500 `_DATA_INVALID` (details: tab, issues). The issues are `BLANK_CODE`, `DUPLICATE_CODE`, `BLANK_NAME` and
    `INVALID_ACTIVE_FLAG` (anything other than exactly `TRUE`/`FALSE`);
  - 503 `_READ_FAILED`.
- `branch_master.is_active` is an optional column. When it is absent, every branch is active.

### 3.3 Histories (§4.5, §7.4)

- `GET /vehicles/{id}/branch-history` and `GET /vehicles/{id}/registration-history` (`can_view`) return the exact
  Rev2 envelopes, including:
  - correlation fields (`request_id`, `record_id`, `event_id`, `revision_no`);
  - notes (`RECORDED_SOURCE_DIFFERS`, `REDUNDANT`, `SAME_INSTANT`, `CANCELLED`);
  - the baseline, `timeline_status` (`VALID`/`AMBIGUOUS_ORDER`), consistency and the revision tokens;
  - `excluded_test_rows: 0` and `issues: {}`.
- **Order of checks:**
  1. the context check;
  2. a validated vehicle locate, with the same errors as the detail page (404/409/500/503);
  3. one read of the history tab;
  4. this vehicle's rows: exact id; for branch history, `asset_type` other than `EQUIPMENT`, so a malformed type is
     reported rather than hidden;
  5. validation and derivation.
- **Errors:** 500 `<BRANCH|REGISTRATION>_HISTORY_DATA_INVALID` (details: tab, issues), 500 `_SCHEMA_INVALID` and
  503 `_READ_FAILED`. A failed read is never answered with an empty list.
- **Baseline fields (§5.1 matrix; review fix R1):**
  - they are required on the asset's first record in recorded order only, and must be blank on every later record;
  - a later `ASSIGNMENT` carrying `baseline_branch_id` or `baseline_source` is reported as
    `FIELD_MUST_BE_BLANK:baseline_branch_id` / `FIELD_MUST_BE_BLANK:baseline_source`, even when it repeats the same
    baseline. This is the matrix's own vocabulary; no new issue code was added;
  - a different baseline still also gives `BASELINE_CONFLICT`;
  - `CORRECTION`, `CANCELLATION` and reconciliation rows were already held to blank by the row matrix and are
    unchanged.
- **Validation is total:** malformed cells become issue codes, never exceptions. This includes non-ASCII digits such
  as `²`, and trailing newlines, which `$` would otherwise accept.

### 3.4 Data context (§8.1)

- **Mock:** always `TEST`. `REGISTRY_DATA_CONTEXT=REAL` with mock fails settings validation, so the app does not
  start.
- **Sheets:**
  - unset → the four new routes return 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any repository call;
  - every existing route keeps working. There is no new global startup prerequisite.
- **Reads:**
  - `TEST` includes every row;
  - `REAL` refuses any `TRUE` or blank row of the vehicle with `CUTOVER_INCOMPLETE`, one count per row.
- `REGISTRY_TEST_BATCH_ID` is defined for the 7O2b writes and is unused by reads.

### 3.5 UI (§7.2, §10)

**Resolution:** the same vocabulary everywhere:
- `RESOLVED`: the name, plus "(ไม่ใช้งาน)" when inactive;
- `UNKNOWN_CODE`: "รหัสไม่อยู่ในทะเบียน (<code>)", only when the list loaded;
- `REFERENCE_UNAVAILABLE`: "<code> (ไม่สามารถโหลดชื่อได้)", never "unknown";
- "ยังไม่ได้บันทึก" (not recorded) versus "แหล่งข้อมูลยังไม่มีช่องนี้" (not in the source).
- While a list is still loading, the code is shown with "กำลังโหลดชื่อ...".

**List page:**
- a "ทะเบียน / สาขา" column;
- a "สาขาที่รับผิดชอบ" select that applies on change and resets to page 1;
- the applied summary names the branch;
- `/branches` and `/provinces` are requested once each per page view. Their failure shows a non-blocking
  `role="status"` note and a retry; the applied filter is never changed or cleared, and no vehicle request is made;
- 409 shows "กรองตามสาขาไม่ได้" and keeps the filter until it is cleared.

**Detail page:**
- `VehicleDetailView key={vehicleId}` (§10.6 named effect: navigating to another vehicle resets an open
  machine-number editor or status dialog);
- `readGeneration` guards every read, and `routeEpoch` guards the UI updates from the two existing PATCH results;
- a "ทะเบียนและสาขาที่รับผิดชอบ" card;
- two independent, read-only history panels, each keyed by vehicle id with its own generation guard. A failed read
  shows a coded error, the request id and a panel-named retry, never "ยังไม่มีประวัติ". "ยังไม่มีประวัติ" appears
  only for a successful response with no rows;
- **response shape (review fix R1):** a 200 body is shown only when every field the panels read has its contracted
  type. This covers:
  - the top level;
  - `current`, `master` and `baseline`;
  - every element of `events`, `records` and `items`: required strings are strings, nullable fields are
    string/null, and `revision_no` is an integer ≥ 1 (null allowed on records);
  - every finite vocabulary: `timeline_status`, both consistency sets, `current.source`, `baseline.source`,
    `record_kind`, `entry_operation`, `notes`, `effective_precision`, recorded sources, `change_kind`,
    `accepted_exceptions` and registry `state`.

  Anything else is the "รูปแบบไม่ถูกต้อง" error state of that panel. Nothing is coerced, and the other panel is
  unaffected;
- **reference lists (review fix R1):** a 200 `{"items": [...]}` is used only when every item has string code and name
  fields and a boolean `is_active`. Otherwise the list is `REFERENCE_UNAVAILABLE`, exactly like an outage, and is
  never a partial name map;
- history paths use `encodeURIComponent`.

**Unchanged detail behavior:** the machine-number trim, the silent status failure and the status-history `[]`
fallback, with a test that pins the fallback.

### 3.6 Engineering choices (labelled; review only)

- **E-a Registration consistency `UNDETERMINED`.** It is returned when a registration column is not in the master
  schema, so there is no master pair to compare. Rev2 §4.5 lists three values and does not cover this case.
- **E-b Context check on the reference lists.** The unset-context 503 also applies to `/branches` and `/provinces`,
  read as "every registry endpoint" (§8.1).
- **E-c Response types:**
  - `revision_no` is returned as an integer (null when blank on reconciliation records);
  - `accepted_exceptions` is a list of codes;
  - blank optional cells are null.
- **E-d Additive response type.** `VehicleWithRegistryResponse` is used only for list items and the detail
  vehicle, so the PATCH response shapes are unchanged.
- **E-e Mock seed coverage.** The mock seed covers:
  - recorded values, a leading-zero registration, an unknown province code and blank values;
  - a transfer, an insertion, a correction and a cancellation;
  - no-history and consistent states.

  `AMBIGUOUS_ORDER`, mismatches, `NOT_IN_SCHEMA` and data errors are exercised through tests: injected repositories,
  the fake transport and e2e route interception. This avoids adding seed vehicles, which would change existing K1
  totals and e2e expectations.
- **E-f Registration revision order.** RHR1 hashes the rows in recorded order (§4.5); BHR1 sorts by `assignment_id`
  (§5.5).

## 4. Contract-to-test mapping (R-01 … R-12)

| Row | Tests |
| --- | --- |
| R-01 8 column combinations, list + detail; totals and K1–K6 | sheets `test_r01_each_column_combination_*` (8 cases: list states, detail == list item, filter 200/409, dashboard counts), `test_r01_seven_column_sheet_detail_is_complete`; API `test_list_items_*`, `test_detail_vehicle_*`, `test_dashboard_totals_equal_list_totals_*` |
| R-02 numeric-looking text; legacy callers | sheets `test_r02_numeric_looking_and_odd_registry_text_*` (`0012`, `1,234`, `1e3`, `=1+1`, …), `test_r02_legacy_reads_on_the_same_tab_are_unchanged`, `test_r02_phantom_rule_ignores_registry_only_rows`; domain `test_registry_states_and_exact_text` |
| R-03 reference success / unknown / outage / invalid | API `test_branch_and_province_lists`, `test_reference_outage_*`, `test_reference_data_invalid_*`; sheets `test_branch_master_without_is_active_*`, `test_history_structure_errors_*`; frontend `referenceResolution.test.ts`, list/detail registry tests |
| R-04 branch filter | API `test_branch_filter_exact_and_variants` (case, padding, prefix, unknown, empty 422, 101 chars 422), `test_branch_filter_ands_with_status_model_q_and_pages`, `test_branch_filter_reads_no_reference_tab`; sheets R-01 409 cases; frontend list tests; e2e filter spec |
| R-05 filter while `/branches` fails | frontend `a reference retry keeps the applied branch filter…`, `a branch list failure never blocks…`; e2e outage spec |
| R-06 branch envelope, notes, baseline, ambiguity, every §5.2 issue | domain (24 per-row rules, baseline/duplicates, dangling/fork/gap/cancellation-not-last, malformed revisions incl. `²`/`๒`, reconciliation matrix, totality fuzz 600×, recorded-order baseline); API envelope/cancellation/no-history/invalid/ambiguous/mismatch tests; panel tests |
| R-07 registration envelope and consistency | domain registration rule table, cross-row rules, consistency states and RHR1; API envelope, mismatch and invalid tests |
| R-08 contexts | domain REAL/TEST tests; API `test_unset_context_*` (zero repository calls), `test_real_context_*`, `test_mock_with_real_context_refuses_to_start`; sheets `test_unset_context_reads_nothing_over_sheets` (zero requests) |
| R-09 effective time | domain `test_effective_*` (NOW, DATE Bangkok, offset, precision, future, lower bound, same instant) |
| R-10 RK1 | domain `test_rk1_*` (owner examples, engineering removals, negatives incl. `0012`≠`12`, NFC, empty key) |
| R-11 UI read states | detail registry tests (error ≠ empty, wrong shape, independent panels, unavailable ≠ not recorded, read-only, keyed remount, delayed detail/history/PATCH after navigation, encoded paths); panel tests; e2e |
| R-12 mock/fake parity | sheets `test_r12_mock_and_fake_sheets_responses_are_identical` (both histories × 3 vehicles, both reference lists, list incl. branch and q), `test_r12_error_semantics_match_*`, `test_r12_registry_read_gates_equal_summary_read` (5 populations) |
| Authorization and boundary | API `test_can_view_refusal_reads_nothing` (4 routes, zero repository calls), `test_every_can_view_role_reads`, `test_no_registry_mutation_route_exists` (POST/PATCH/PUT/DELETE → 404/405; OpenAPI shows GET only) |
| Request counts and no writes | sheets `test_request_counts_cold_and_warm_for_every_new_get`, `test_list_request_count_is_unchanged_by_the_registry_columns`, `test_history_tabs_survive_warm_cache_and_header_reorder`, `writes == []` throughout |

## 5. Measured request counts (fake transport, not live Sheets)

These counts are (metadata reads, values reads) per request through real gspread 6.2.1 over the fake session. They
are not live latency or quota figures, and the comparison with §6.8 belongs to 7O2d.

| Request | Cold | Warm |
| --- | --- | --- |
| `GET /branches` | (2, 1) | (0, 1) |
| `GET /provinces` | (2, 1) | (0, 1) |
| `GET /vehicles/{id}/branch-history` | (3, 2) | (0, 2) |
| `GET /vehicles/{id}/registration-history` | (3, 2) | (0, 2) |
| `GET /vehicles?branch_id=…` | (2, 1) | (0, 1) |

- The vehicle list stays at one values read with or without registry columns.
- No new GET issued a write request.

## 6. Existing expectation updates (identified before changing them)

1. **`backend/tests/test_vehicle_search_data_quality_batch7g2.py::test_http_success_shape_and_dashboard_agreement_on_seed_data`.**
   The exact key set of a list item gains `"registry"`. Rev2 §7.1 makes it an additive field. The totals and the
   dashboard agreement assertions are unchanged.
2. **`frontend/src/pages/VehicleListPage.test.tsx` › "keeps the request count independent of the number of visible
   vehicles".** The sorted endpoint list gains `/api/v1/branches` and `/api/v1/provinces`. Rev2 §7.2 and §10.5
   require one call each per page view. The test's purpose (no per-row requests) is unchanged.

Five other existing tests failed during development. They were fixed in the UI, not in the tests:
- **Reference-failure note role:** the four list error-wording tests found a second `role="alert"`, so the
  non-blocking reference note now uses `role="status"`.
- **Retry button names:** the GPS-card test found duplicate "ลองใหม่อีกครั้ง" buttons, so the history panels now have
  panel-named retry buttons.

## 7. Verification

### 7.1 Environment

- Linux 6.18; Python 3.11.15; FastAPI 0.141.1; gspread 6.2.1.
- Node 22.22.2; Playwright 1.63.0 with Chromium only.
- Mock repository for the HTTP and e2e runs; fake Sheets transport for the Sheets tests.

### 7.2 Baseline demonstration

The new test files that import only pre-existing modules were run against a clean worktree at `1d8e3be`:

**Backend: `test_registry_read_api_batch7o2a.py`: 30 failed, 1 passed.**
- Behavioural failures:
  - 404 for the new routes;
  - no `registry` key;
  - `branch_id` ignored (3 items instead of 1);
  - the `REGISTRY_DATA_CONTEXT=REAL` + mock setting not refused.
- Four tests fail at fixture setup because the baseline has no registry seed builders.
- The one pass is the dashboard/list totals agreement, which is unchanged by design.

**Frontend: the two page-level registry test files: 19 failed, 1 passed.**
- Missing column, select and panels.
- No keyed remount: an open editor survives navigation.
- A real stale read: a slow detail for the previous vehicle replaced the current vehicle's page with SYN-M1 data.
- The one pass is the unchanged status-history fallback.

Files that import new modules (domain, sheets, panel, resolution) are not counted as baseline demonstrations.

### 7.3 Final candidate (2026-10-05, on stable code; code hashes identical before and after)

**Revision R1 re-verification** (after the two review fixes, on the final R1 code; code hashes identical before
and after the runs):

| Check | Result |
| --- | --- |
| Backend suite | 2272 passed, exit 0 (one new baseline test) |
| Frontend unit | 51 files, 435 tests passed, exit 0 (28 new shape tests) |
| Typecheck + build | exit 0; the chunk-size warning pre-exists (557.53 kB) |
| Lint | exit 0; 33 warnings, the same set as the baseline (file + rule) |
| Playwright inventory | 485 tests in 19 files |
| Playwright full | 485 passed, exit 0 |

Further checks:
- no registry mutation route exists (`test_no_registry_mutation_route_exists`; no POST/PATCH/PUT/DELETE decorator
  in the registry route files);
- the fixes add no write call;
- the only files changed for R1 are `branch_timeline.py`, `test_registry_domain_batch7o2a.py`,
  `RegistryHistoryPanels.tsx`, `RegistryHistoryPanels.test.tsx`, `referenceResolution.ts`,
  `VehicleListPage.registry.test.tsx` and this report.

The table below is the first candidate's verification and is kept as history.

| Check | Command | Result |
| --- | --- | --- |
| Backend suite | `scripts/run_backend_tests.sh -q -p no:randomly` | 2271 passed, exit 0 (baseline 2135) |
| Frontend unit | `scripts/run_frontend_tests.sh` | 51 files, 407 tests passed, exit 0 (baseline 47 / 377) |
| Typecheck + build | `npm run build` (`tsc -b && vite build`) | exit 0; chunk-size warning pre-exists (baseline 535.83 kB, now 555.02 kB) |
| Lint | `npm run lint` | exit 0; 33 warnings, the same set as the baseline (file + rule); only VehicleDetailPage's existing warning moved from line 68 to 86 |
| Playwright inventory | `npx playwright test --list` | 485 tests in 19 files, exit 0 (baseline 450 in 18) |
| Playwright full | `scripts/run_e2e_tests.sh` | 485 passed, exit 0 |

The Playwright projects are five Chromium viewport projects (smartphone portrait/landscape, tablet
portrait/landscape, desktop). They are viewport emulations, not different browser engines.

Documentation was written after these runs. No code or test input changed afterwards, so nothing was rerun.

## 8. Limitations

- **No live data:**
  - no live Google Sheets workbook was read;
  - the observed nine-column `asset_branch_history` format answers `BRANCH_HISTORY_SCHEMA_INVALID` until the proposed
    columns exist (§15.1 prerequisite);
  - `province_master` and `vehicle_registration_history` are PROPOSED tabs.
- **Fake transport only:** request counts are fake-transport counts.
- **Not verified:** no Windows run, other browser engines, realistic data volumes or physical devices.
- **Writes:** nothing in this batch writes registry data. The `is_test_data` context only scopes reads.
- **Mock states:** the mock seed does not contain every state (E-e); the remaining states are covered by tests.
- **Untouched existing gaps:**
  - the legacy status-history `[]` fallback;
  - the silent status failure;
  - the legacy `get_vehicle` subpage reads (G10);
  - the `/findings` false-empty limitation.

## 9. Stop state

- **Candidate state:** uncommitted, with an empty index.
- **Not done:** no commit, push, merge, pull request or tag, and 7O2b has not been started.
- **Phase 7:** remains **PARTIAL**.
