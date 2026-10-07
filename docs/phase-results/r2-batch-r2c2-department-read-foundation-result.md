# R2 Batch R2c-2 — Department Read Foundation — Result

Status: **candidate, uncommitted** on local branch `review/r2-batch-r2c2-department-read-foundation`,
created from integration HEAD `ed19160900f9f8af4ef1cef684d4cf32072840a7`.

| Item | Status |
|---|---|
| Department backend read implementation | **DONE (candidate)** — verified on MockRepository and the fake Sheets transport, synthetic data only |
| Live Department UAT | **BLOCKED — OWNER BUSINESS DATA / LIVE TAB CREATION** |
| Personnel ↔ department migration | DEFERRED |
| Workshop modelling | DEFERRED |
| R2d / R2e / R2f | NOT STARTED |

## 1. Scope

A standalone, read-only `department_master` (Option A of the R2c-2 readiness report, locked in the R2c-2
contract lock). This batch adds:

- `GET /api/v1/departments` and `GET /api/v1/departments/{department_id}` (existing `can_view`);
- a dedicated Department domain model and service;
- one repository read, `read_department_master_validated()`, on the mock and Google Sheets repositories;
- the frozen schema declarations and synthetic mock seed rows.

Not in this batch: no write route, no new capability, no personnel / branch / workshop / account / technician /
driver read or join, no R2a `MasterReferenceResolver` change (no `DEPARTMENT` kind), no personnel change, no
frontend change, no PostgreSQL.

## 2. Locked Department schema

Tab `department_master`, frozen header in this exact order:

```
department_id | department_name_th | is_active | is_test_data | test_batch_id
```

- `DEPARTMENT_MASTER_SHEET` declares all five columns.
- `DEPARTMENT_MASTER_READ_SHEET` (the bounded read) requires only `department_id`, `department_name_th`,
  `is_active`, `is_test_data`, all read as exact text. A missing `test_batch_id` does not block the read.
- `test_batch_id` is known schema metadata only: not required, not exposed, not interpreted, not used for any test
  batch selection.
- At R2c-2 candidate review time, `department_master` is not in `_CORE_SCHEMAS`, so the absent live tab does not
  affect startup/readiness. A later separately-approved deployment/cutover batch may change readiness membership
  after the live tab exists (see §9: this is one-off review evidence, not a permanent test). Until the tab exists, both department routes answer
  `500 DEPARTMENT_MASTER_SCHEMA_INVALID` (`problem: TAB_MISSING`) — never `200 []`, a default or a 404.

**The live `department_master` tab does not exist yet. No live tab was created and no live row was written.**

## 3. Field semantics

**`department_id`** — the only Department identity. Exact source text: no trim, case folding, numeric
normalization or leading-zero handling; never derived from the display name; no prefix enforced. **No production
department id format was chosen.** The synthetic `DEPT-TEST-…` ids in fixtures are TEST-ONLY and are NOT a
production convention.

**`department_name_th`** — required display text, returned exactly as stored (not trimmed, never substituted or
generated). Not identity, not required to be unique: two ids may share a name. A blank or whitespace-only name on
an operational row is `BLANK_DEPARTMENT_NAME`.

**`is_active`** — required; exact `TRUE` / `FALSE`, no default. Both are valid and both are returned; inactive
departments stay readable. Returned as a JSON boolean, losslessly mapped from the validated exact text — the same
representation as the existing branch/province/part master APIs. Blank or anything else (`true`, `1`, `YES`,
`" TRUE"`, …) is `ACTIVE_FLAG_INVALID`; it is never defaulted or normalized.

**`is_test_data`** — required; exact `FALSE` (operational, included) / `TRUE` (test, excluded from the
operational API everywhere: list, `total_items`, detail). Blank or anything else is `TEST_FLAG_INVALID`.

## 4. Processing order and the final list / detail rule

One `department_master` read per request, then:

1. **Phantom rows:** a row whose three business columns (`department_id`, `department_name_th`, `is_active`) are
   all blank is skipped, whatever its checkbox says (a checkbox can keep `FALSE` in an otherwise empty row). The
   Sheets repository also drops rows with no required cell filled. A row with content in any of the three business
   columns always goes through strict classification.
2. **Classification** of `is_test_data` on every remaining row. **Any** blank/invalid flag fails the **whole
   source**, for both list and detail: `500 DEPARTMENT_MASTER_DATA_INVALID`, `issues: {TEST_FLAG_INVALID: n}`.
3. `TRUE` rows are removed. They are never validated, so they can never cause an operational blank-id, duplicate,
   blank-name or invalid-active failure, nor a detail match.
4. Only `FALSE` rows are validated as operational departments.

**List** (`GET /departments`): any operational defect fails the whole list with `500
DEPARTMENT_MASTER_DATA_INVALID` and issue counts: `BLANK_DEPARTMENT_ID`, `DUPLICATE_DEPARTMENT_ID` (every row
sharing the id is counted, the R1 rule), `BLANK_DEPARTMENT_NAME`, `ACTIVE_FLAG_INVALID`. Otherwise sorted by
`department_id` in exact Python string order, then paginated (`page ≥ 1`, `page_size` 1..200, default 20, the
R2c-1 convention). No search, no active filter, no test filter.

**Detail** (`GET /departments/{department_id}`), target-focused after classification (the R2c-1 distinction:
source-classification defect = whole-source failure; exact-detail identity logic = target-focused):

- a blank requested id, or no exact operational match → `404 DEPARTMENT_NOT_FOUND`;
- more than one exact operational match → `409 DEPARTMENT_ID_AMBIGUOUS` (`details: {match_count}`);
- exactly one match → that row's name and `is_active` must be valid, else `500 DEPARTMENT_MASTER_DATA_INVALID`
  with that row's issue counts; otherwise `200`.

Unrelated malformed operational rows (blank id, other duplicate ids, blank name or invalid active flag on another
row) do not block a valid exact detail. A `TRUE` row sharing an id with a `FALSE` row creates no ambiguity.

**Errors** (all additive, Department-specific):

| Code | Status | Details |
|---|---|---|
| `DEPARTMENT_MASTER_SCHEMA_INVALID` | 500 | `tab`, `problem`, `headers` |
| `DEPARTMENT_MASTER_READ_FAILED` | 503 | `tab` |
| `DEPARTMENT_MASTER_DATA_INVALID` | 500 | `tab`, `issues` (counts only) |
| `DEPARTMENT_NOT_FOUND` | 404 | none |
| `DEPARTMENT_ID_AMBIGUOUS` | 409 | `match_count` |

Error details never contain a department id, name, test batch id or row number.

## 5. Public read shape

`DepartmentResponse` (`extra="forbid"`): exactly `department_id`, `department_name_th`, `is_active`.
`is_test_data` and `test_batch_id` are never exposed. Both routes call `require_capability(context, CAN_VIEW, …)`
before any read: an unauthorized caller gets `403` with zero repository reads.

## 6. Files

New:

- `backend/app/domain/department.py` — schema constants, `DepartmentRecord`, classification, validation, errors,
  `DepartmentService`;
- `backend/app/api/v1/department_routes.py` — the two GET routes and `DepartmentResponse`;
- `backend/tests/test_department_read_batch_r2c2.py` — mock / domain / API tests;
- `backend/tests/test_department_read_sheets_batch_r2c2.py` — fake Sheets transport tests;
- this document.

Additive edits:

- `backend/app/api/v1/router.py` — include the department router;
- `backend/app/repositories/base.py` — abstract `read_department_master_validated()`;
- `backend/app/repositories/google_sheets/repository.py` — `_registry_table(DEPARTMENT_MASTER_READ_SHEET)`;
- `backend/app/repositories/google_sheets/schemas.py` — `DEPARTMENT_MASTER_SHEET`, `DEPARTMENT_MASTER_READ_SHEET`;
- `backend/app/repositories/mock/repository.py` — `_department_master` seed and the read;
- `backend/app/repositories/mock/seed_data.py` — `SEED_DEPARTMENT_MASTER`.

No R1 inventory test needed an exception: none rejected the new routes or names. `master_reference.py`,
`personnel.py`, `personnel_routes.py`, `authz.py`, `context.py`, `config.py` and all frontend files are unchanged.

## 7. Synthetic data

All committed fixtures and seed rows are synthetic, with invented, labelled Thai names
(`แผนกสังเคราะห์…`, `… (สังเคราะห์)`). Mock seed: `DEPT-TEST-001` (FALSE, active TRUE), `DEPT-TEST-002` (FALSE,
active FALSE), `DEPT-TEST-901` (TRUE, excluded). `is_test_data = FALSE` in fixtures means "synthetic fixture
simulating an operational-scope row", not a real department. No live department label is used in code, tests or
fixtures.

## 8. External evidence (not used as data)

Owner-supplied evidence from an inspection outside Claude, recorded here only as context: the live workbook has no
`department_master` tab; `personnel_master.department` is legacy free text; the label `ซ่อมบำรุง` occurs in
operational personnel rows, while `ระบบ` and `ปฏิบัติการ` occur only in test rows. None of these labels or counts
appears in code or tests. They are not departments of this system until the owner approves the operational set.

## 9. Test ids (batch-local PROPOSED)

| Id | Covered by |
|---|---|
| R2C2-01 | valid list, paging/bounds, exact-text sort, synthetic seed |
| R2C2-02 | exact operational detail |
| R2C2-03 | unknown / non-exact id → 404; numeric-looking ids exact |
| R2C2-04 | duplicate id: list DATA_INVALID, detail 409, unaffected id 200 |
| R2C2-05 | blank operational id → DATA_INVALID; detail target-focused |
| R2C2-06 | blank operational name → DATA_INVALID; names exact, non-unique |
| R2C2-07 / 08 | `is_active` TRUE / FALSE both readable |
| R2C2-09 | blank / invalid `is_active` → ACTIVE_FLAG_INVALID |
| R2C2-10 | mixed FALSE + TRUE; `total_items` after exclusion |
| R2C2-11 | TRUE-only id → 404 |
| R2C2-12 | FALSE + TRUE same id: no ambiguity; two FALSE keep duplicate behaviour |
| R2C2-13 | malformed TRUE rows do not invalidate the operational scope |
| R2C2-14 | blank / invalid `is_test_data` → TEST_FLAG_INVALID on list and detail |
| R2C2-15 | checkbox-only phantom rows skipped (mock and fake, reordered header) |
| R2C2-16 | missing required read header / tab / header row → SCHEMA_INVALID |
| R2C2-17 | missing `test_batch_id` does not block the read |
| R2C2-18 | read failure → 503, never an empty success |
| R2C2-19 | `can_view`: 403 with zero reads; ADMIN / TECHNICIAN allowed |
| R2C2-20 | public response exactly three fields; OpenAPI `additionalProperties: false` |
| R2C2-21..23 | only the department read: no personnel, branch, workshop, account, technician or driver read |
| R2C2-24 | mock / fake parity (9 cases × 3 paths) |
| R2C2-25 | fake-transport cost: cold 2 metadata + 1 values, warm 0 + 1 |
| R2C2-26 | R2c-1 personnel contract unchanged |
| R2C2-27 | PERMANENT: Department schema declarations (frozen five-column header, four required read columns); existing R2a BRANCH / MODEL / PART kinds and resolvers remain present (subset check) |
| R2C2-28 | routes exist; no DELETE; R1 capability holders intact — future lifecycle writes and capabilities are NOT frozen out |

Facts at this candidate (not permanent tests): R2c-2 adds exactly two GET operations, no department mutation route
and no capability. R2e may add Department lifecycle writes after its own approved design review without violating
R2c-2.

R2C2-27 one-off review evidence (independent-review fix R1), verified at this candidate but deliberately NOT
asserted by a long-lived test:

- this R2c-2 candidate adds no `DEPARTMENT` MasterReference kind and no `resolve_departments` (R2a
  `master_reference.py` is unchanged);
- this candidate does not put `department_master` in `GoogleSheetsRepository._CORE_SCHEMAS`.

These absence facts are NOT permanent tests because later approved relationship or deployment/cutover batches may
add them: a `DEPARTMENT` kind when a personnel/department relationship stores a `department_id`, and readiness
membership after the live tab exists.

## 10. Verification

| Suite | Result |
|---|---|
| A. New R2c-2 tests | 152 passed |
| B. R2c-1 personnel tests | 122 passed |
| C. Master / repository / API suites (mock, Sheets repository, part master, 7O2a registry read) | 128 passed |
| D. Legacy technician guards (core demo fixes delta, rev05) | 32 passed |
| E. Repair / PM assignment authority | 83 passed |
| F. Driver Phase 6 | 32 passed |
| G. R1 7O2 suites | 932 passed |
| H. R2a | 63 passed |
| I. R2b | 59 passed |
| J. Complete backend suite | **3463 passed** (= 3311 baseline + 152 new) |
| K. Ruff `--select E4,E7,E9,F` | 13 findings (baseline 13, unchanged); new files clean except the existing `B008` FastAPI `Depends` pattern under default rules, as in R2c-1 |
| L. Frontend unit (vitest) | 645 passed (58 files) |
| M. Typecheck / build (`tsc -b && vite build`) | passed |
| N. Frontend lint (oxlint) | 33 warnings (baseline), 0 errors |
| O. Playwright inventory | 565 tests in 23 files (unchanged) |
| P. Full Playwright | **565 passed** |

Note on P: a first full Playwright run, executed while the backend suites were running at the same time, had one
timeout in `e2e/inspection.spec.ts:90` (tablet-portrait, a 5 s `toBeEnabled` wait). This batch changes no
frontend file. That spec passed 35/35 in isolation, and the test passed 5/5 repeats. A clean full re-run with
nothing else running passed **565/565**.

## 11. Live Google Sheets

This batch, its tests and its verification read and wrote no live Google Sheets workbook. All Sheets behaviour
runs on the fake HTTP transport with the frozen header and synthetic rows.

Live Department UAT remains **blocked** until the owner supplies the authoritative operational department set and a
separately authorized step:

1. creates `department_master`;
2. writes the exact header from §2;
3. assigns approved stable `department_id` values (format: owner decision);
4. fills the approved operational rows with `is_active = TRUE`, `is_test_data = FALSE`;
5. optionally adds separately labelled `TRUE` test rows.

## 12. Open decisions (not taken here)

1. The authoritative operational department set (owner business data).
2. The production `department_id` format and values.
3. Personnel ↔ department authoritative relationship and migration of the legacy `personnel_master.department`
   text (the original text must be kept), including a `DEPARTMENT` MasterReference kind when something stores a
   `department_id`.
4. Department lifecycle writes (deactivate / reactivate) — R2e.
5. Workshop modelling — deferred; R2c-2 makes no claim about whether a future workshop is a separate master, a
   location, related to a branch or department, or another concept. Department has no branch relation.
