# Web/API Phase 7 — Batch 7H2 — Vehicle Text Preservation — Batch Result

BATCH: Phase 7 Batch 7H2 (implementation of the approved 7H1 Final contract)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**
(the 7D2 expectation conflict first reported in section 5.1 was resolved by
a separately authorized test-expectation correction; full backend suite now
passes — see sections 4 and 5.1)

> **7L1 reconciliation note (2026-10-01).** This batch was committed as
> `47dec0aa2c4313657f93d8e1c262b8f5ea9ca41e` and is integrated on `web/phase7-dashboard-search-reporting`
> (checked at `5275b8f9708b54baf1f20cab09282c3395f7adb8`). The BATCH STATUS
> above is the historical status at review time and is kept as written;
> the "WHOLE PHASE 7 STATUS" paragraph lists what remained at that time.
> Verification results in this report are historical runs on the
> uncommitted candidate, not 7L1 runs. Fresh integrated results, the
> current coverage and remaining work are in
> `docs/phase-results/web-phase-07-partial-result.md`. Phase 7 remains
> **PARTIAL**.

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7h2-vehicle-text-preservation` (local), based on
`485c647f9bf0bfc590d61c9cb165264cd36b3fe2` (equal to
`web/phase7-dashboard-search-reporting` at preflight).

Design input: `Phase7_Batch7H1_Vehicle_Text_Preservation_Contract_Review_Evidence_Final.txt`
(SHA-256 `65d21be520421acdbaaa0c4d5e68edb63ff019f1afe627543b26cc4e78234acd`,
219836 bytes, 3170 lines).

## 1. Approved selections

| Decision | Selection | Implemented as |
| --- | --- | --- |
| H1 | Protect vehicle_id, machine_no, model_id, serial_number, operational_status; dates excluded | `_VEHICLE_TEXT_ONLY_HEADERS` on the shared summary read (list + dashboard) and the new locate read |
| H2 | model_id, model_code on VehicleService model reads | `_MODEL_TEXT_ONLY_HEADERS` |
| H3(a) | default_plan_code, plan_code, pm_plan_id in the VehicleService plan map | `_validated_plan_id_by_code`; PM service paths untouched |
| H4(a) | Targeted batch writes, apostrophe + USER_ENTERED | `GoogleSheetsClient.batch_update_cells` (one values:batchUpdate) |
| H5(a)/(b)(i) | Blank/whitespace ids never match; duplicates refused on new reads and writes | `_locate_vehicle` (and mock `_locate_vehicle_key`) |
| H6 | 409 VEHICLE_ID_AMBIGUOUS; 503 VEHICLE_MASTER_WRITE_FAILED with `vehicle_write_outcome` | `vehicle_path_error` |
| H7 | Status before history; no retry/compensation/atomicity | `change_vehicle_status_validated` |
| H8(b) | Whitespace-only machine_no -> 422 before any read; values otherwise unchanged | `UpdateMachineNoRequest._reject_whitespace_only` |
| H9 | Legacy `Repository.list_vehicles` unchanged | — |
| H10 | No repair/reconstruction/migration | — |
| H11 | Only the Final 6.3 expectation updates | 7B2T c8 + fixture, 7G2ST g09 + fixtures (section 5.2); plus one separately authorized 7D2 expectation (section 5.1) |
| H12 | No FAKEWS extension/migration | none made |
| H13 | Frontend unchanged | none |
| H14(a) | Per-tab schema/read/write codes | `_TAB_CODE_PREFIX` |
| H15(a) | New VehicleService-scoped methods; legacy unchanged | 7 new `Repository` methods |
| H16 | Existing `_next_id` history ids; collision risk disclosed | section 6 |
| H17 | No post-write re-read | intended models returned |

## 2. Changed files

Modified: `backend/app/repositories/google_sheets/client.py` (additive:
`_write_failure`, `batch_update_cells`, `append_row_with_header`),
`backend/app/repositories/google_sheets/repository.py` (V5 on the summary
read; new validated methods), `backend/app/repositories/base.py` (four
error types, seven abstract methods), `backend/app/repositories/mock/repository.py`
(mock implementations), `backend/app/domain/vehicle_service.py`,
`backend/app/api/v1/vehicles.py` (OpenAPI responses only),
`backend/app/api/v1/vehicle_schemas.py` (H8(b) validator and docstring),
`backend/tests/test_fleet_status_summary_sheets_batch7b2.py` and
`backend/tests/test_vehicle_search_data_quality_sheets_batch7g2.py`
(approved 6.3 updates),
`backend/tests/test_certificate_expiry_report_sheets_batch7d2.py`
(one separately authorized expectation correction, section 5.1),
`CHANGELOG.md`.

Added: `backend/tests/test_vehicle_text_preservation_batch7h2.py`,
`backend/tests/test_vehicle_text_preservation_sheets_batch7h2.py`, this
report.

Unchanged: generic `read_rows`/`find_row`/`append_row`/`update_row`/
header cache; legacy `get_vehicle`, `get_vehicle_model`,
`list_vehicle_models`, `list_vehicle_components`,
`list_vehicle_status_history`, `update_vehicle_machine_no`,
`change_vehicle_status`, `list_vehicles`; every non-VehicleService caller;
frontend; dependencies; configuration.

## 3. Behavior

**Reads (VehicleService only).** Every read is one `read_header_and_records`
response: protected positions and records come from that same response
after structural validation; canonical phantom rows are skipped; the
header cache is not used. Exact strings are preserved, including leading
zeros, accepted whitespace and literal apostrophes. Status codes are still
classified exactly (blank/whitespace -> BLANK_STATUS; padded, case
variants, unknown, "1" -> UNRECOGNIZED_STATUS). List/dashboard keep one
shared read; list data errors stay issue_counts-only; dashboard keeps
sample ids (now also for text ids such as "0012").

**Identity.** Exact equality; "12" != "0012"; blank/whitespace ids return
404 without any read; duplicates return 409 (detail, components, status
history and both writes). Blank model ids resolve to no model.

**Machine-number update.** 422 for whitespace-only input (no read). Then:
validated locate -> 404 / 409 / 500 SCHEMA_INVALID / 503 READ_FAILED;
source row gates -> 500 VEHICLE_MASTER_DATA_INVALID {issue_counts};
intended Vehicle validated; ONE values:batchUpdate of `machine_no`
(apostrophe-forced) and `updated_at`, addressed from the same response.
Response = the intended model (no re-read).

**Status change.** As above, plus a validated history read BEFORE the
vehicle write (history structural damage -> 500
VEHICLE_STATUS_HISTORY_SCHEMA_INVALID, read failure -> 503
VEHICLE_STATUS_HISTORY_READ_FAILED, zero writes); next history id from
that read; history row (history_id and vehicle_id apostrophe-forced)
serialized in that header's order. Then the vehicle batchUpdate
(`operational_status` forced, `updated_at`), then the append.

**Write outcomes.** HTTP 4xx -> `rejected`; HTTP 5xx, timeout, connection
error or lost response -> `unknown` (the write MAY have been applied).
Vehicle write failure -> 503 VEHICLE_MASTER_WRITE_FAILED
{"vehicle_write_outcome"}; history is not attempted. History failure after
an ACKNOWLEDGED vehicle write -> 503 VEHICLE_STATUS_HISTORY_WRITE_FAILED
{"vehicle_status_updated": true, "history_write_outcome"} —
`vehicle_status_updated` means acknowledged, not re-read; an unknown
outcome never claims the row is absent. No retry, compensation or re-read.
Only repository errors are mapped; programming errors propagate (generic
500).

**Models (H3a).** "01" and "1" are distinct plan codes; a numeric-looking
`pm_plan_id` ("0007") is returned as text. maintenance_plan failures are
reported under MODEL_MASTER_SCHEMA_INVALID / MODEL_MASTER_READ_FAILED
with the tab named in the details (the approved code list has no separate
plan-tab code). Legacy PM paths still numericise these codes.

## 4. Verification

### 4.1 Fresh backend runs after the 7D2 expectation correction

Implementation/test hashes of all 14 candidate files were identical before
and after these runs.

| Command | Result | Exit |
| --- | --- | --- |
| `pytest -q tests/test_certificate_expiry_report_sheets_batch7d2.py::test_existing_7b2_and_7c2_validated_reads_keep_their_behavior` | 1 passed | 0 |
| `pytest -q tests/test_certificate_expiry_report_sheets_batch7d2.py` | 37 passed | 0 |
| `cd backend && .venv/bin/python -m pytest -q` | **1997 passed**, 174 warnings | **0** |

The 174 warnings have the same per-test sources as the earlier candidate
run. Relative to the baseline (1844 passed, 162 warnings), the 12 extra
warnings all come from the new 422 tests (pre-existing deprecated
`HTTP_422_UNPROCESSABLE_ENTITY` in `app/errors.py`). 1997 tests = 1844 +
153 new; the correction changed one existing test and added none.

### 4.2 Historical runs (earlier candidate; NOT rerun)

The correction changed one backend test file and this report only; no
frontend, build, lint or e2e input changed, so these were not rerun.

| Command | Result | Exit |
| --- | --- | --- |
| `cd backend && .venv/bin/python -m pytest -q` (before the correction) | 1996 passed, **1 failed** (the 7D2 expectation in 5.1), 174 warnings | 1 |
| `cd frontend && npm test` | 47 files, 345 tests passed | 0 |
| `cd frontend && npm run build` | built | 0 |
| `cd frontend && npm run lint` | 33 warnings, identical set to baseline | 0 |
| `npx playwright test` vehicle-equipment, equipment-search-completeness, vehicle-search-partial-states, fleet-status-dashboard, vehicle-search-data-quality, parts-lifetime, web-uat-defect-fix, responsive-shell | 200 passed (5 projects) | 0 |

Baseline (scratch copy of `485c647f`, run fresh earlier): backend 1844
passed, 162 warnings.

### 4.3 Test coverage and measured counts

New tests: 51 (mock/service/HTTP) + 102 (Sheets over the fake transport),
covering T01–T21 incl. T11a/b and T12a/b/c, H3(a), H8(b), warm-cache column
reorders on every new path, zero-write preflight, targeted payloads and
honest unknown outcomes. Storage and failure behavior in the Sheets tests
are EMULATION/SIMULATION over a fake transport, not live Sheets.

MEASURED request counts (fake transport, warm): machine-number update =
1 values GET + 1 batchUpdate; status change = 2 values GETs + 1 batchUpdate
+ 1 append (asserted in `test_t13_measured_request_counts_warm`). Before
7H2 (7H1 P7, measured): 3 and 6.

## 5. Approved expectation updates and the open conflict

### 5.1 Additional authorized expectation update (conflict resolved)

`backend/tests/test_certificate_expiry_report_sheets_batch7d2.py::test_existing_7b2_and_7c2_validated_reads_keep_their_behavior`
asserted that the dashboard summary still FAILED on a numeric-looking
vehicle id ("0123" -> UNMAPPABLE_ROW). DEC-H1 deliberately makes that
summary succeed. The 7H1 Final Section 6.3 list did not include this
expectation, so the first candidate left it unchanged and reported it as
the single backend failure (historical run, section 4.2). The owner then
separately authorized correcting this one subcase; no other test function
in that file changed and no product code changed.

The corrected subcase:

- KEEPS the direct default-reader assertion: `read_header_and_records`
  without `text_only_headers` still returns integer `123` for stored
  `"0123"`. The generic client's default numericising is unchanged and
  stays tested; text preservation is an explicit opt-in per caller.
- Asserts the summary now succeeds: `vehicle_total == 1`, READY 1, every
  other status 0 — because the vehicle summary caller explicitly opts in
  (approved H1) for its identifier columns.
- Asserts the repository's protected vehicle-master read keeps
  `vehicle_id == "0123"` with no issues.
- Keeps the fixture (still `"0123"`), the clean-data subcase and the
  repair/7C2 assertions unchanged.

With this update the full backend suite passes (section 4.1).

### 5.2 Applied (approved in Final 6.3)

7B2T `test_c8…` -> summary succeeds (3 vehicles), legacy list still
raises; 7B2T and 7G2ST zero-write "unmappable" fixtures -> numericised
`created_at`; 7G2ST `test_g09` inverted to "preserved as text"; 7G2ST
id-leak fixture SYN-SECRET-3 -> numericised `created_at` (expected counts
unchanged); 7G2ST randomized family re-verified (passes unchanged).

## 6. Limits and deferred items

- Races: between the validated read and the write(s) a concurrent edit,
  row insert/delete or column move can make addresses stale; between the
  history validation and the append the history header can change.
- Uncertain writes: an `unknown` outcome may have been applied; clients and
  operators must check the sheet. No automatic reconciliation.
- History ids: `_next_id` over the read; concurrent status changes can
  produce the same id (DEC-H16).
- Status and history are two requests; a status change can be acknowledged
  while the history outcome is unknown or rejected (DEC-H7).
- Non-VehicleService paths (12 other `get_vehicle` call sites, PM,
  lifetime, model documents, meter, vehicle events) still use the legacy
  numericising, cached-header reads — this batch does not fix every
  numeric-id workflow.
- Dates are unprotected (numericised timestamps fail; non-ISO text falls
  back to the epoch). History `changed_by`/`note` are not text-forced.
- Unencoded `vehicleId` frontend links; authorization (M02: vehicle routes
  ungated) unchanged.
- Already-lost leading zeros are not recovered or detected automatically;
  a stored number 12 reads as "12" and can look valid.
- No live Sheets or Windows validation was performed.

Phase 7 remains **PARTIAL**.
