# R2 — Batch R2c-1 — Personnel Read Foundation — Batch Result

BATCH: R2 Batch R2c-1. A backend-only, read-only personnel master with two routes, `GET /api/v1/personnel` and
`GET /api/v1/personnel/{personnel_id}`.

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE (REVISION R1), AWAITING INDEPENDENT REVIEW**

**Revision R1 (independent review fix: operational data boundary).** The first candidate (patch SHA-256
`dde19b4f…7736`, 60,044 bytes) returned every row and did not interpret `is_test_data`. Review required
R2c-1 to be the **operational** personnel read:

- `FALSE` rows are included;
- `TRUE` rows are excluded;
- a blank or any other flag value fails closed.

The classification runs before identity validation (§6). Nothing else in the accepted design changed: identity,
response shape, routes, `can_view`, pagination, isolation and `active_status` semantics are all as before.

R1 is closed and frozen. R2a and R2b are integrated and accepted. WHOLE PHASE 7: **PARTIAL**. Nothing here changes
those statuses.

What this batch does not do:

- no write, lifecycle or deactivation;
- no account, technician, driver, department or assignment join;
- no frontend change;
- no new capability;
- no authentication change;
- no live Google Sheets access or change;
- no PostgreSQL;
- no R2c-2, R2d, R2e or R2f work.

## 1. Baseline

| Item | Value |
| --- | --- |
| Integration branch `web/phase7-dashboard-search-reporting` (local = origin) | `562a1543bcf21ea74954aa4d6f33adaae7d00fdd` (R2b) |
| Review branch (local only) | `review/r2-batch-r2c1-personnel-read-foundation`, created from exactly that SHA |
| `main` | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (untouched) |
| Candidate | uncommitted; full `candidate.patch` against the base SHA |

## 2. Schema evidence

The earlier R2c-0A NO-GO was superseded. The owner explicitly authorized an independent, **schema-only** inspection
of the `MAINTENANCE` workbook, done outside this session. Row 1 of the `personnel_master` tab (sheetId `90000100`)
gave the verified header row, in source order:

```
personnel_id, first_name, last_name, department, position, branch_id,
active_status, technician_id, user_id, is_test_data, test_batch_id, note_th
```

- The stable person identity is `personnel_id`.
- The operational display fields are `first_name` and `last_name`.
- The only nonblank `active_status` value observed is `ACTIVE`, and no validation or dropdown rule exists on that
  column.
- **This session did not access the live workbook.**
- No personnel row value (name, ID, phone, email, account, employee number) is copied into the code, tests or this
  document.

## 3. Scope (changed files)

| File | Change |
| --- | --- |
| `backend/app/domain/personnel.py` | **new**: verified columns, `PersonnelRecord`, identity validation, the 5 personnel errors, `PersonnelService` |
| `backend/app/api/v1/personnel_routes.py` | **new**: the two `can_view` GET routes and `PersonnelResponse` |
| `backend/app/api/v1/router.py` | additive: one import and one `include_router` |
| `backend/app/repositories/base.py` | additive: abstract `read_personnel_master_validated()` |
| `backend/app/repositories/mock/repository.py` | additive: synthetic personnel rows and the mock read |
| `backend/app/repositories/google_sheets/repository.py` | additive: the Sheets read (existing `_registry_table` helper) |
| `backend/app/repositories/google_sheets/schemas.py` | additive: `PERSONNEL_MASTER_SHEET` (the 12 verified headers) and `PERSONNEL_MASTER_READ_SHEET` (the 5 used columns: `personnel_id`, `first_name`, `last_name`, `active_status`, `is_test_data`) |
| `backend/app/repositories/mock/seed_data.py` | additive: 4 **synthetic** personnel rows in total: 3 `FALSE` rows (`PER-TEST-001..003`) simulating operational-scope personnel, and 1 `TRUE` row (`PER-TEST-901`) that proves exclusion from the operational view. `FALSE` in these fixtures does **not** mean they are real people; all four rows are invented synthetic test data. |
| `backend/tests/test_personnel_read_batch_r2c1.py` | **new**: mock, domain and API tests |
| `backend/tests/test_personnel_read_sheets_batch_r2c1.py` | **new**: fake Google Sheets transport tests |
| this document | **new** |

No other file changed. These are all untouched:

- auth and roles: `authz.py`, `context.py`, `DEV_AUTH_MODE`, `/me`, `role_permission` runtime behaviour;
- technician and assignments: no technician schema or method; `repair_assignment` / `pm_work_assignment`;
- drivers: `driver_master` / `vehicle_driver`;
- earlier batches: R1, R2a (`master_reference.py`), R2b;
- the frontend;
- the existing tests.

## 4. Identity

- `personnel_id` is the only person identity.
- It is matched as **exact text**: no trim, case folding, numeric normalization or leading-zero change. For example,
  `0012`, `012` and `12` are three different people.
- It is never mapped to `user_id`, `technician_id`, a driver ID, a name, an email, a phone number or an employee
  number.
- **List:** a blank (whitespace-only) or duplicated `personnel_id` fails the **whole** list with 500
  `PERSONNEL_MASTER_DATA_INVALID {tab, issues}`. The issue codes are `BLANK_PERSONNEL_ID` and
  `DUPLICATE_PERSONNEL_ID`, counting every row that shares a duplicated ID. This follows the R1 reference-list and 7K2
  convention. A list never returns ambiguous identity.
- **Detail:** no exact match gives 404 `PERSONNEL_NOT_FOUND`; more than one gives 409 `PERSONNEL_ID_AMBIGUOUS
  {match_count}`. Like 7K2's equipment lookup, a defect in another row does not block an unaffected ID. A blank
  requested ID never matches.
- `PER-TEST-…` is a **TEST-ONLY** synthetic form. It is **not** a production ID-format decision.

## 5. Public record

`PersonnelResponse` has `extra="forbid"` and exactly four fields: `personnel_id`, `first_name`, `last_name`,
`active_status`.

| Field | Semantics |
| --- | --- |
| `personnel_id` | exact source text |
| `first_name`, `last_name` | exact source text; a blank cell gives `null` |
| `active_status` | **raw nullable source text, not an enum**; a blank cell gives `null` (unknown) |

**Blank names.** A blank name is `null` and does not invalidate the record. The source has no rule requiring names,
and the identity is `personnel_id`, not the name, so a transparent `null` is safer than rejecting the person or
fabricating a value. Names are never concatenated, substituted, or replaced by the ID.

**active_status.** Any nonblank text is returned exactly, including future values such as `INACTIVE` or Thai text,
and is never rejected. A blank is **never defaulted to `ACTIVE`**. The lifecycle vocabulary belongs to R2e.

**Not exposed:** `department`, `position`, `branch_id`, `technician_id`, `user_id`, `is_test_data`, `test_batch_id`,
`note_th`.

- `department`, `position` and `branch_id` are source fields, but the approved relationship model is separate
  linked or history data that is not frozen yet. A later slice may expose them after review.
- `technician_id` and `user_id` would settle the R2f link decisions.

## 6. Operational data scope (TEST / REAL)

R2c-1 is the **operational** personnel read. `is_test_data` is classified on every personnel row **before** any
identity logic:

| `is_test_data` (exact formatted text) | Meaning | Effect |
| --- | --- | --- |
| `FALSE` | operational row | **included** in the list, `total_items` and detail |
| `TRUE` | explicitly test row | **excluded** from the list, `total_items` and detail |
| blank, whitespace-only, or any other text (`true`, `false`, `YES`, `0`, ` FALSE`, …) | classification unknown | **fail closed**: 500 `PERSONNEL_MASTER_DATA_INVALID`, issue `TEST_FLAG_INVALID` (counts only), for both list and detail |

Order of operations:

1. read `personnel_master`;
2. classify the flag on every row that holds personnel content;
3. any unknown flag → `DATA_INVALID`;
4. drop `TRUE` rows;
5. validate blank or duplicate `personnel_id` on the remaining `FALSE` rows only;
6. run the list or detail logic;
7. serialize the public response.

So a test row can never create an operational duplicate, an operational blank-ID failure, or a detail match:

- an ID that exists only in a `TRUE` row gives 404;
- one `FALSE` row and one `TRUE` row with the same ID gives the `FALSE` row, with no ambiguity;
- two `FALSE` rows with the same ID still give 409.

Pagination and `total_items` apply after the exclusion.

**Rows with no personnel content.** A row whose four public columns are all blank is not a personnel record, and is
skipped whatever its flag says. This is the pre-existing phantom-row rule kept intact now that `is_test_data` is a
read column. A boolean checkbox column can leave `FALSE` in otherwise empty rows, and such a row must neither appear
as a person nor fail the list with a blank ID. **Flagged for review.**

What R2c-1 does not do:

- **No test personnel browsing.** There is no `PERSONNEL_DATA_CONTEXT`, no reuse of `REGISTRY_DATA_CONTEXT`, no
  `config.py` change and no TEST query parameter.
- **`test_batch_id`** stays known source metadata. It is non-public, not read, not interpreted, and has no matching
  logic.

A future approved batch may design an explicit TEST personnel view if one is needed.

**Independent review evidence (observed at review time, not a business invariant).** An owner-authorized inspection
of the `is_test_data` column only (cited by the reviewer as `personnel_master!J2`), with no names or IDs inspected,
found:

- 17 rows with `FALSE`;
- 5 rows with `TRUE`, all with `test_batch_id` `TEST-20261002-STAFF`.

The cells are underlying booleans whose formatted values are exactly `FALSE` / `TRUE`. None of these counts or IDs is
hard-coded in production code.

## 7. Repository and schema

- `read_personnel_master_validated()` is one read through the existing `_registry_table` helper.
  - It requires and validates only the five columns it uses (`PERSONNEL_MASTER_READ_SHEET`: the four public columns
    plus `is_test_data`). All five are read as exact text, so the flag is its formatted `TRUE` / `FALSE`.
  - `test_batch_id` and the other non-public columns are not required.
  - Every cell is returned as exact text, and phantom rows are dropped.
  - A missing, empty-header or duplicate-header tab raises `RepositorySchemaError`; any other failure raises a
    `RepositoryError`.
- `PERSONNEL_MASTER_SHEET` records the full verified 12-column header.
- Neither schema is in `_CORE_SCHEMAS`, so readiness is unaffected.
- No method or tab name contains "technician", so the legacy technician guard tests stay green.
- The mock serves the same exact-text rows with the 12-column header.

## 8. Errors

All personnel errors are new and additive. None leaks names or IDs in its details.

| Case | Response |
| --- | --- |
| Tab missing, no header row, missing or duplicate header | 500 `PERSONNEL_MASTER_SCHEMA_INVALID {tab, problem, headers}` |
| Read failure | 503 `PERSONNEL_MASTER_READ_FAILED {tab}` |
| Blank or invalid `is_test_data` on any personnel row (list **and** detail) | 500 `PERSONNEL_MASTER_DATA_INVALID {tab, issues: {TEST_FLAG_INVALID: n}}` |
| Blank or duplicate ID among operational rows (list) | 500 `PERSONNEL_MASTER_DATA_INVALID {tab, issues}` (counts only) |
| Detail with no match | 404 `PERSONNEL_NOT_FOUND` |
| Detail with more than one match | 409 `PERSONNEL_ID_AMBIGUOUS {match_count}` |
| No `can_view` | 403 `HTTP_ERROR`, with **zero** repository reads |

A failed read never becomes `200 []`, a whole-source 404, or a default person. Error details never contain a
`personnel_id`, a name, a row number or a `test_batch_id`.

## 9. API

| Route | Response | Notes |
| --- | --- | --- |
| `GET /api/v1/personnel?page&page_size` | `Page[PersonnelResponse]` | The existing master-list `Page` convention (`page` ≥ 1; `page_size` 1–200, default 20), sorted by `personnel_id`. No search or filter: none is required. |
| `GET /api/v1/personnel/{personnel_id}` | `PersonnelResponse` | exact-text lookup |

Both routes require the existing `can_view` capability.

## 10. Request cost (fake transport, not live Sheets)

| Request | Cold (metadata, values) | Warm (metadata, values) |
| --- | --- | --- |
| `GET /personnel` | **(2, 1)** | **(0, 1)** |
| `GET /personnel/{id}` | **(2, 1)** | **(0, 1)** |

- The only values read is `personnel_master`.
- The test backend has no `user_account`, `role_permission`, `technician_master`, `driver_master`, `branch_master` or
  assignment tab, and none is requested.
- In mock mode the only repository call is `read_personnel_master_validated`.
- There are zero writes.

## 11. Test matrix and results

All IDs are batch-local PROPOSED identifiers. There are **122 R2c-1 tests**: 78 mock/domain/API and 44 fake-Sheets. R0 had 77; R1 adds the data-scope tests and
updates the required-header cases.

| ID | Test(s) |
| --- | --- |
| R2C1-01 valid list | `test_r2c1_01_*` (sorted list, paging, synthetic seed) |
| R2C1-02 exact detail | `test_r2c1_02_*` |
| R2C1-03 unknown ID → 404 | `test_r2c1_03_*` (unknown, case, leading or trailing space, zero padding, blank; numeric-looking IDs match exactly) |
| R2C1-04 duplicate ID | `test_r2c1_04_*` (list → DATA_INVALID; detail → 409; unaffected ID still readable; no names or IDs in details) |
| R2C1-05 blank ID → DATA_INVALID | `test_r2c1_05_*`, `test_r2c1_04_05_identity_issue_counting` |
| R2C1-06 read failure ≠ empty | `test_r2c1_06_07_*` (mock and fake) |
| R2C1-07 missing or invalid header → SCHEMA_INVALID | `test_r2c1_07_*` (each of the 5 required headers on list and detail: `personnel_id`, `first_name`, `last_name`, `active_status`, `is_test_data`; tab missing; no header row; duplicate header; only the 5 used columns required; phantom row; reordered header) |
| R2C1-08 / 10 `active_status` exact; future text kept | `test_r2c1_08_10_*` (8 values) |
| R2C1-09 blank status → null, never ACTIVE | `test_r2c1_09_*` |
| R2C1-11 names exact | `test_r2c1_11_*` (odd text, numeric-looking text over Sheets, blank → null, mapping) |
| R2C1-12..15 no user_account / technician / driver / branch_master read | `test_r2c1_12_15_*` (mock call log; fake: personnel_master is the only values tab) |
| R2C1-16 `can_view` | `test_r2c1_16_*`: 403 with zero reads for a caller without it; explicit ADMIN and TECHNICIAN callers succeed; other or future roles are not constrained |
| R2C1-17 mock/fake parity | `test_r2c1_17_*` (5 scenarios × 3 paths, request_id excluded) |
| R2C1-18 read cost | `test_r2c1_12_15_18_request_cost_and_no_other_tab` |
| R2C1-19 non-public fields excluded | `test_r2c1_19_*` (synthetic "LEAK" markers in all 8 non-public columns never appear; OpenAPI schema has exactly 4 properties and `additionalProperties: false`) |
| R2C1-20 legacy technician contract intact | `test_r2c1_20_*`, plus the unchanged legacy tests in §12 |
| R2C1-21 R1 / R2a / R2b regression | §12 |
| R2C1 scope A: mixed FALSE + TRUE → only FALSE rows, `total_items` after exclusion | `test_r2c1_scope_a_*` |
| R2C1 scope B: TRUE-only ID → 404 | `test_r2c1_scope_b_*` |
| R2C1 scope C: one FALSE + one TRUE row with the same ID → FALSE row, no ambiguity | `test_r2c1_scope_c_*` |
| R2C1 scope D: two FALSE rows with the same ID → unchanged duplicate behaviour | `test_r2c1_scope_d_*` |
| R2C1 scope E/F: blank or invalid flag → DATA_INVALID / TEST_FLAG_INVALID (list and detail) | `test_r2c1_scope_e_f_*` (12 values × 2 paths) |
| R2C1 scope G: TRUE rows with a blank or duplicated ID don't affect the operational list | `test_r2c1_scope_g_*` |
| R2C1 scope H: `is_test_data` / `test_batch_id` never exposed | `test_r2c1_scope_h_*`, `test_r2c1_19_*` |
| R2C1 scope I: mock/fake parity | `test_r2c1_17_*` (now 8 scenarios incl. mixed scope, invalid flag, test row with blank ID) |
| R2C1 scope J: read cost one values read warm | `test_r2c1_12_15_18_*` (unchanged) |
| R2C1 scope: flag read as text over Sheets; content-less rows skipped; classification before identity | `test_r2c1_scope_flag_is_read_as_text_*`, `test_r2c1_scope_rows_without_personnel_content_*`, `test_r2c1_scope_classification_happens_before_identity_checks` |
| R2C1-22 future personnel surface not frozen | `test_r2c1_22_*`: pins only that the two GETs exist, no DELETE on a personnel record, and the R1 registry capability holders. It does not freeze future personnel routes or capabilities (R2e). |

## 12. Regression

Run on the Revision R1 candidate, 2026-10-06. R0 values are shown for comparison.

| Check | R1 result | R0 |
| --- | --- | --- |
| A. R2c-1 tests | **122 passed** (78 + 44) | 77 |
| B–H. Affected suites (R2c-1; legacy technician `test_core_demo_fixes_delta*`; repair/PM assignment and authority suites; `test_driver_phase6_batch1`; every R1 7O2 suite; R2a; R2b; `test_dev_auth_fail_closed`; Google Sheets repository suites; 7B2) | **1491 passed** | 1446 |
| I. Backend full suite | **3311 passed** (accepted baseline 3189 + 122 R2c-1) | 3266 |
| Re-run on the final files after an import-order-only reformat of the two R2c-1 test files | R2c-1 + legacy technician guards: **154 passed** | — |
| J. Ruff, accepted rule set (`E4,E7,E9,F`) | **13 findings, identical to the base**; none in R2c-1 files | 13 |
| J'. Ruff, installed ruff 0.16.8 default rules | 697 (base 692). The only additions are 5 `B008` (`Depends(...)` in route defaults) in `personnel_routes.py`, the pattern every FastAPI route here already uses. | 697 |
| K. Frontend unit suite | 58 files, **645 passed** | 645 |
| L. Typecheck + build | exit 0 | exit 0 |
| M. Frontend lint | exit 0; **33 warnings**, as the baseline | 33 |
| N. Playwright inventory | **565 tests in 23 files**, unchanged; the frontend tree is byte-identical to the base | 565 |
| O. Playwright full suite | **565 passed** (5 Chromium viewport projects), first run | 565 |

**Proof against the previous candidate.** The R1 test files were run against the R0 code, with the one direct import
of the new `operational_rows` helper removed. Every new data-scope test fails there and passes on R1: scope A–G, the
invalid-flag cases, the flag-over-Sheets test, and the new `is_test_data` required-header case.

All existing tests are unchanged and green, including:

- the legacy technician = `user_id` guards;
- the repair/PM assignment authority suites;
- the driver Phase 6 suite;
- the R1, R2a and R2b suites.

## 13. One-off review evidence and open decisions

Facts at this candidate, not permanent tests:

- R2c-1 adds exactly two personnel operations, both GET;
- no personnel mutation route and no personnel capability exist;
- `authz.py` and `context.py` are byte-identical to the base;
- no frontend file changed.

Later batches (R2e lifecycle writes, R2f links) may add personnel routes and capabilities after their own approved
design review without violating R2c-1.

Open decisions (not taken here):

1. The `active_status` vocabulary and lifecycle (R2e).
2. Contracts for `department`, `position` and `branch_id` as organizational relationships, and the department master
   (R2c-2).
3. Technician representation and links between `technician_id`, `personnel_id` and `user_id`, given the legacy
   technician = `user_id` contract and guard tests (R2f).
4. The driver ↔ personnel link (R2f).
5. The production `personnel_id` format.
6. Whether an explicit TEST personnel view (browsing `TRUE` rows or a test batch) is needed at all. The operational
   separation itself is **frozen for R2c-1** (§6) and is no longer an open decision.

## 14. Live Google Sheets

This batch, its tests and its verification read and wrote no live Google Sheets workbook. All Sheets behaviour runs
on the fake HTTP transport with the verified header and **synthetic** rows. No live tab, column or row was created
or changed, and no production data was imported.
