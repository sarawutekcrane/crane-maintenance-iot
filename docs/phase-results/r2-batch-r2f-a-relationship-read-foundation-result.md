# R2 Batch R2f-a — Relationship Read Foundation — Result

Authority: R2f Final Contract Consolidation — Corrected C1 (§5, §6, §15, §16, §20, §23, §24, §27–§30).
Baseline: `web/phase7-dashboard-search-reporting` @ `240d85692a0c43f47fc4eb63c7e18ea0b6139e6d`
(tree `deec874eb960c8dcdb350410a9751f57609073b2`); `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

R2f-a is **read only**. It adds no write method, route, tab, column or live access.

## 1. Scope

Delivered:

1. bounded read of `technician_master` (technician_id, first_name, last_name, active_status);
2. bounded read of `user_account` (user_id only);
3. Personnel ↔ Technician resolution (authority `personnel_master.technician_id`);
4. Personnel ↔ User Account resolution (authority `personnel_master.user_id`);
5. exact TEST / REAL scope handling (OD-13 as clarified by C1);
6. explicit TEST-scoped synthetic references in the mock / fakes;
7. deliberate amendment of the two legacy "no technician_master" guards;
8. contract-evolution comments for the superseded Delta §G statement;
9. four read-only `can_view` routes.

Not delivered (later batches): any relationship write, Driver ↔ Personnel, `driver_id`, crane responsibility,
equipment caretaker, department history, Repair/PM V2 assignment, V2 My Work, Go-live setting, history tabs,
live schema change, PostgreSQL, R2g, R3.

## 2. Repository read surface

| Method | Reads | Notes |
|---|---|---|
| `read_personnel_relationship_master()` | `personnel_master`: personnel_id, first_name, last_name, active_status, technician_id, user_id, is_test_data, test_batch_id | all required, exact text, phantom rows dropped |
| `read_technician_master_reference()` | `technician_master`: the 4 bounded columns | returns `ReferenceMasterRead` |
| `read_user_account_reference()` | `user_account`: `user_id` | returns `ReferenceMasterRead` |

**Transport (independent-review fix R1):** on Google Sheets all three reads are TRULY column-limited
(`GoogleSheetsClient.read_bounded_columns`, used only through `GoogleSheetsRepository._bounded_table`): one request for
the header row (`'tab'!1:1`, metadata only), validated and used to resolve each declared column BY NAME, then ONE
`values:batchGet` with a single-column range per declared column (`'tab'!C2:C`, ...). Non-adjacent columns are never
merged into a wider range, so no other column's data is requested. Values are formatted text and never numericised
(ids stay exact). Missing tab / blank header row / missing declared header / duplicated header name ->
`RepositorySchemaError`; any other failure -> read error. The legacy whole-tab readers (`read_header_and_records`,
`_validated_read`, `_registry_table`) are unchanged and unused by R2f-a.

`ReferenceMasterRead` carries `ScopedReferenceRow(values, scope, test_batch_id)` and `test_scope_supported`. The
Google Sheets repository marks every live row `REAL` and `test_scope_supported=False` (the live tabs carry no test
metadata). Only the mock / fakes supply explicitly TEST-scoped synthetic records; the scope is never derived from
a cell value (id prefix, name, email, ...). No technician_master / user_account write method exists.

## 3. Resolution model

One shared pure resolver (`personnel_relationship.resolve_link`) for both links:

| State | Meaning |
|---|---|
| `UNSET` | the personnel cell is blank |
| `RESOLVED` | exactly one same-scope target with exactly this id, and no other in-scope personnel holds the link |
| `AMBIGUOUS` | the id matches more than one same-scope target, or more than one in-scope personnel holds it (0..1 violated); nothing is selected |
| `SCOPE_UNPROVEN` | TEST only: no same-scope target, and the repository cannot supply TEST scope or the id exists only outside the request's TEST scope (REAL row or another batch) |
| `MISSING` | a nonblank id with no target in scope (REAL: a TEST fixture never counts) |

A repository / schema / read failure is an error (`<PREFIX>_SCHEMA_INVALID` 500, `<PREFIX>_READ_FAILED` 503 for
`PERSONNEL_MASTER`, `TECHNICIAN_MASTER`, `USER_ACCOUNT`), never a state, never an empty list.

Scope (server data context + test batch, the R2e rule): REAL = exact-FALSE personnel and REAL-scope references;
TEST = exact-TRUE personnel of the server batch and TEST-scoped references of that batch. An unclassifiable test
flag fails the personnel source closed (`PERSONNEL_MASTER_DATA_INVALID`, `TEST_FLAG_INVALID`). An unconfigured
context answers `503 REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any read.

## 4. API (all `GET`, `can_view`, zero reads on 403)

- `GET /api/v1/technicians` — REAL-scope technicians, sorted; fails closed on blank / duplicate ids (counts only).
- `GET /api/v1/technicians/{technician_id}` — exact id; `404 TECHNICIAN_NOT_FOUND`, `409 TECHNICIAN_ID_AMBIGUOUS`.
- `GET /api/v1/personnel/{personnel_id}/relationships` —
  `{personnel_id, technician: {resolution, technician_id, technician}, account: {resolution}}`.
- `GET /api/v1/technicians/{technician_id}/personnel` — `{technician_id, resolution (RESOLVED | UNSET | AMBIGUOUS),
  personnel_id, match_count}`; the technician must exist in the request's scope.

**Raw `user_id` decision:** the account link returns its resolution state only. Contract C1 §16 reserves the raw
linked `user_id` for the future Personnel ↔ Account relationship-management capability (R2f-c); it does not exist
yet, so R2f-a redacts the value and widens no role. No capability was added.

The R2c-1 `GET /personnel` routes are unchanged and join-free. No Driver relationship is handled.

## 5. Legacy guard amendments (deliberate, not deleted)

- `test_core_demo_fixes_delta.py::test_technician_identity_is_a_plain_opaque_user_id_no_technician_master`
- `test_personnel_read_batch_r2c1.py::test_r2c1_20_legacy_technician_identity_rules_are_intact`
- **Deviation (third guard, not listed in C1 §23):** `test_core_demo_fixes_delta_rev05.py::
  test_no_waiting_parts_status_and_no_duplicate_tables_introduced` forbade any tab name containing
  `technician_master`. Minimal amendment: that one fragment now asserts `technician_master` exists only as the
  bounded read schema (`TECHNICIAN_MASTER_READ_SHEET`) with no write path; its other four forbidden fragments and
  the `RepairStatus` assertion are unchanged.

Both keep their names for traceability and now prove: legacy `/assign` stores opaque strings verbatim; old
assignment rows are ended in place and never rewritten; legacy assignment-based authorization still compares the
actor's `user_id`; the R2c-1 personnel read stays join-free; technician_master / user_account READ support may
exist; no technician_master or user_account write method exists (shared assertion
`assert_reference_surface_is_read_only`).

## 6. Explicitly unchanged

Repair / PM legacy assignment writes, `repair_assignment.user_id` / `pm_work_assignment.user_id` semantics, legacy
My Work and waiting-assignment, `require_assignment_or_capability`, the `primary_technician` / `collaborators`
mirrors, Phase 6 Driver routes, `vehicle_driver`, Driver statuses and assignment behaviour,
`asset_responsibility_history`, personnel and department lifecycle, branch history, inspection, capabilities and
roles.

## 7. Mock limitation (documented)

Mock mode is always the TEST context (as in R2e). The synthetic operational-scope seed personnel are therefore not
in scope for the relationship routes (404 by design); the technician list shows the REAL-scope synthetic seed
technicians. TEST relationship resolution in mock needs TEST personnel of the mock server batch.

## 8. Verification (after independent-review fix R1)

| Check | Result |
|---|---|
| R2f-a focused (mock/service 36 + Sheets fake 23) | 59 passed |
| Amended guard suites (Delta, REV05, R2c-1) | 110 passed |
| Related Sheets suites (R2c-1, R2c-2, R2e, repository) | 141 passed |
| Full backend | **3711 passed** (R1 candidate 3703; +8 transport-privacy tests; R2e baseline 3652) |
| Ruff `E4,E7,E9,F` | 13 (accepted baseline); changed files clean |
| Full vitest | 667 passed (61 files), unchanged |
| Typecheck / build | pass |
| Lint (oxlint) | 33 warnings / 0 errors (baseline) |
| Playwright inventory | 565 / 23 files, unchanged |
| Full Playwright (run alone) | 565 passed |

Fix-removal checks: scope ignored -> 7 failures; 0..1 holder check removed -> 2; SCOPE_UNPROVEN collapsed to
MISSING -> 4; duplicate target picks first -> 2; Sheets mode claiming TEST scope -> 1; **bounded read replaced by the
old whole-tab read -> 7 transport-privacy failures**. Every mutated file was restored hash-identically.

