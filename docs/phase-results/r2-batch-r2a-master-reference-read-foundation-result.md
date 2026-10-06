# R2 — Batch R2a — Shared Master-Reference Read Foundation — Batch Result

BATCH: R2 Batch R2a, the first R2 implementation batch: a read-only foundation that resolves stored stable IDs of
three existing masters (branch, model, part) to one small backend/domain shape. Scope is the approved R2a batch
prompt, built on the reviewed R2 readiness report REV1.

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE (REVISION R1), AWAITING INDEPENDENT REVIEW**

**Revision R1 (independent review fixes).** The first candidate (patch SHA-256 `beec1030…831828`, 56,802 bytes)
passed review with two targeted fixes. R1 changes only these:

1. **`part_master.is_active` is required.**
   - The bounded part-reference read now requires exactly `part_id`, `name` and `is_active`; no other Phase 5
     column is required.
   - A part source without `is_active` is `REFERENCE_UNAVAILABLE / SCHEMA_INVALID`. R0 had wrongly returned
     `RESOLVED / NOT_IN_SCHEMA`.
   - Unlike `branch_master.is_active`, which is optional by the frozen R1 contract, this column is existing required
     part metadata (the Phase 5 `PART_MASTER_SHEET` declares it).
   - The domain enforces the same rule (`part_table` returns `None`), so it holds for any adapter.
2. **R2A-17/18/19 no longer freeze the whole system.** The committed tests now pin only R2a's master scope and the
   frozen R1 surface:
   - R2A-17: no DELETE on the branch/model/part resources;
   - R2A-18: the 13 accepted R1 registry/branch operations still exist, and other routes may be added;
   - R2A-19: the three R1 registry capabilities stay ADMIN + MAINTENANCE_MANAGER only, and new capabilities may be
     added.
   - The whole-API and whole-mapping checks are kept as one-off review evidence in §5, not as tests.

Unchanged by R1: the `MasterReference` shape; branch and model semantics; exact-text matching; duplicate handling;
the unavailable-reason vocabulary; inactive references staying `RESOLVED`; one read per resolve; mock/fake parity.

R1 STATUS: closed and frozen at `a78b64373da7b3bbf562be71c2fdb6ad639fdef5` (accepted with the recorded live-UAT
blocker). WHOLE PHASE 7: **PARTIAL**. Nothing here changes either status.

No new endpoint, UI, frontend change, write route, capability, pending-intent family or allowlist change. No live
Google Sheets workbook was read or written. No PostgreSQL. No R2b.

## 1. Baseline

| Item | Value |
| --- | --- |
| Integration branch `web/phase7-dashboard-search-reporting` (local = origin) | `a78b64373da7b3bbf562be71c2fdb6ad639fdef5` |
| Review branch (local only) | `review/r2-batch-r2a-master-reference-read-foundation`, created from exactly that SHA |
| `main` | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (untouched) |
| Candidate | uncommitted; full `candidate.patch` against the base SHA |

## 2. Scope

In scope: branch, model and part reference resolution (identity + existing label + active metadata where the source
has it), mock and Google Sheets parity, focused tests, this document.

Out of scope: see §11.

## 3. Domain contract (`backend/app/domain/master_reference.py`)

`MasterReference` (frozen dataclass):

| Field | Meaning |
| --- | --- |
| `master_kind` | `BRANCH` / `MODEL` / `PART` |
| `reference_id` | the requested id, exact text |
| `state` | `RESOLVED` / `UNKNOWN_CODE` / `REFERENCE_UNAVAILABLE` (accepted R1 vocabulary) |
| `label` | the master's existing name column, verbatim (`branch_name`, `model_name`, part `name`); only when RESOLVED |
| `active_state` | `ACTIVE` / `INACTIVE` / `NOT_IN_SCHEMA`; only when RESOLVED |
| `unavailable_reason` | only when REFERENCE_UNAVAILABLE: `READ_FAILED`, `SCHEMA_INVALID`, `DATA_INVALID`, `DUPLICATE_ID` |

Rules:

- **A.** The id is not in a successfully read source → `UNKNOWN_CODE`. A successfully read empty master is still a
  read, so its ids are `UNKNOWN_CODE`, not unavailable.
- **B.** The source could not be read → `REFERENCE_UNAVAILABLE`:
  - `RepositorySchemaError` (missing tab, missing or duplicate header) → `SCHEMA_INVALID`;
  - any other `RepositoryError` → `READ_FAILED`.
- **C.** Active metadata depends on the master:
  - **branch:** `is_active` is optional (frozen R1). If the column is absent, `active_state = NOT_IN_SCHEMA` for that
    metadata only, and the reference stays `RESOLVED`.
  - **model:** no approved active semantics, so it is always `NOT_IN_SCHEMA`.
  - **part:** `is_active` is required. If the column is absent, the read is a structural problem:
    `REFERENCE_UNAVAILABLE / SCHEMA_INVALID`.
- **D.** Exactly one row has the id → `RESOLVED`. An inactive row is still `RESOLVED` with `active_state = INACTIVE`,
  never `UNKNOWN_CODE`: historical references stay valid.
- More than one row with the id → `REFERENCE_UNAVAILABLE / DUPLICATE_ID`. The row is never guessed.
- Ids are matched as exact text (no trim or case change). A blank id never matches a row, including a row with a
  blank id.
- Every requested id gets exactly one answer, deduplicated and in request order. Unavailable results carry no label
  and no active state: nothing is replaced by an empty value, a zero, a default or "inactive".

Pieces:

- pure helpers: `resolve_ids`, `unavailable`, and one table builder per kind (`branch_table`, `model_table`,
  `part_table`);
- `MasterReferenceResolver`, a thin read-only adapter that makes **one** repository read per call (`resolve_branches`,
  `resolve_models`, `resolve_parts`).

There is no registry of kinds, no dynamic schema and no CRUD layer.

## 4. Repository implementation

| Kind | Read used | New? |
| --- | --- | --- |
| Branch | `read_branch_master_validated()` (R1, unchanged) | reused |
| Model | `read_vehicle_model_search_index()` (7J2: one validated text read of `model_id`/`model_code`/`model_name`; no PM-plan read) | reused |
| Part | `read_part_master_reference()` | **new**, additive |

**Why the part read is new.** The existing Sheets `get_part_master` / `list_part_masters` mapper (`_part_master_from_row`)
does three things a reference resolver must not inherit:

- it reads a blank or missing `is_active` as TRUE;
- it maps a blank `tracking_mode` to `NONE`;
- it raises a non-repository error on an unknown `tracking_mode`.

The new method is one bounded text read, with no row mapping:

- **Interface:** an abstract method on `Repository`.
- **Mock:** the typed parts as exact-text rows, with `is_active` `TRUE`/`FALSE`.
- **Google Sheets:** the existing R1 helper `_registry_table` with a private
  `SheetTabSchema("part_master", ("part_id", "name", "is_active"))`.
  - It requires exactly the columns the resolver needs. Unrelated Phase 5 columns (`tracking_mode`, `metadata`,
    timestamps, …) are not required.
  - A missing `part_id`, `name` or `is_active` header raises `RepositorySchemaError`, which gives `SCHEMA_INVALID`.
  - It is not a new tab.
  - It is not added to `schemas.py`.
  - It is not in `_CORE_SCHEMAS`, so readiness is unaffected (pinned by a test).

Changed production files (all purely additive):

- `repositories/base.py`: +10 lines;
- `repositories/mock/repository.py`: +9 lines;
- `repositories/google_sheets/repository.py`: +12 lines, plus `SheetTabSchema` added to an existing import line.

No existing method body changed.

R1 production files were not modified. R2a only *imports* from them:

- `parse_reference_rows` and `STATE_NOT_IN_SCHEMA` from `vehicle_registry.py`;
- `text` from `registration.py`.

The three repository files above were extended additively, as the batch prompt allows for those areas.

## 5. Branch compatibility proof

`branch_table` calls the frozen R1 `parse_reference_rows` exactly as the R1 readers do (`branch_id`, `branch_name`,
optional `is_active`). Any parser issue makes the whole tab unusable, as in R1 (`BRANCH_MASTER_DATA_INVALID`), so
every requested branch is `REFERENCE_UNAVAILABLE / DATA_INVALID`.

The R1 rule is "no `is_active` column means every branch is active" (C-c8). R2a reports `NOT_IN_SCHEMA` instead,
which equally never makes a branch inactive. The mapping is:

- R1 `is_active=False` ⇔ `INACTIVE`;
- R1 `is_active=True` ⇔ `ACTIVE`, or `NOT_IN_SCHEMA` when the column is absent.

R2A-06 checks the new resolver against **both accepted R1 readers**:

- `RegistryReadService.list_branches` (backs `GET /branches`);
- the 7O2c destination check `BranchWriteService._check_destination`, which gives OK, `BRANCH_NOT_FOUND`,
  `BRANCH_INACTIVE` or `BRANCH_MASTER_DATA_INVALID`.

It covers 9 `branch_master` shapes (active+inactive, no active column, numeric-looking codes, duplicate code, blank
code, blank name, invalid flag, blank flag, empty) × 8 probe ids × mock and fake Sheets, plus read and schema
failures.

Further pins:

- the exact `GET /branches` response bytes on the mock seed;
- R2A-18: the 13 accepted R1 registry/branch operations still exist with their paths and methods;
- R2A-19: the three R1 registry capabilities are held by ADMIN and MAINTENANCE_MANAGER only.

**One-off review evidence (not committed tests).** These were computed on the untouched base and recomputed on this
R1 candidate:

| Evidence | Base `a78b643` | Candidate |
| --- | --- | --- |
| Documented operations (OpenAPI `paths` × methods) | 118 | 118 |
| SHA-256 of `repr(sorted((METHOD, path)))` | `d15dbb0d…7813f6c` | identical |
| SHA-256 of the whole OpenAPI document (`json.dumps`, `sort_keys`) | `867b04a9…9f4251c` | identical |
| DELETE operations anywhere | 0 | 0 |
| `authz.ALL_CAPABILITIES` and `authz.ROLE_CAPABILITIES` | 9 capabilities, 6 roles | identical (no production authz change) |

Full hashes:

- route inventory: `d15dbb0d14131f4549248a37f49f007e8b4f7e48ae51cec2996c4c30f7813f6c`;
- OpenAPI document: `867b04a9de975187155e66406b1382c3e8f2ce0bf10d35b2f10f5c85d9f4251c`.

## 6. Model semantics

- Identity is `model_id` only, and the label is `model_name`.
- `model_code` is not an id: `SYN-QY` is `UNKNOWN_CODE`.
- There is no active semantics: `active_state` is always `NOT_IN_SCHEMA`. A stray `is_active` cell on `model_master`
  is ignored, and the model is never invalid because of it.
- The read validates `model_master` with its existing schema, as the vehicle search does. A duplicate `model_id` is
  `DUPLICATE_ID` for that id only.
- No PM-plan read, no write, no deactivation.

## 7. Part semantics

- Identity is `part_id`, and the label is `name`.
- `part_code` is not an id.
- `is_active` is used only as the exact text `TRUE` (`ACTIVE`) or `FALSE` (`INACTIVE`). An inactive part stays
  `RESOLVED`.
- Any other flag value (blank, `yes`, lower-case `false`) makes **that** reference `REFERENCE_UNAVAILABLE /
  DATA_INVALID`. It is never guessed. This is per row, so one bad part does not hide the others.
- `is_active` is a **required** column, unlike branch's optional one. A source without it (or without `part_id` or
  `name`) gives `REFERENCE_UNAVAILABLE / SCHEMA_INVALID` for every requested part. It is never `RESOLVED /
  NOT_IN_SCHEMA`.
- A duplicate `part_id` gives `DUPLICATE_ID`. An unknown `part_id` in a structurally valid source gives
  `UNKNOWN_CODE`.
- No edit, deactivate/reactivate, lifetime, installation, replacement or R6 logic.

## 8. Mock / fake parity

R2A-15 resolves the same synthetic data through `MockRepository` and `GoogleSheetsRepository` on the 7B2 fake HTTP
transport (real gspread; no credentials, no network). It covers all three kinds, including unknown and blank ids, and
asserts identical results.

Every single-kind test runs in both modes.

- The fake transport refuses any non-GET request and records it; R2a's fake tests assert zero recorded writes.
- Each resolve is exactly one values request (pinned for branch, model and part).
- A model reference reads no `maintenance_plan`.

## 9. Tests

`backend/tests/test_master_reference_batch_r2a.py`: **63 tests** (R0: 57). R2A ids are batch-local PROPOSED identifiers.

| ID | Test(s) |
| --- | --- |
| R2A-01 branch known → RESOLVED + label | `test_r2a_01_*` (mock, fake) |
| R2A-02 branch unknown → UNKNOWN_CODE | `test_r2a_02_*` |
| R2A-03 branch read failure → REFERENCE_UNAVAILABLE | `test_r2a_03_*` (tab read, unconfigured, schema; fake 500, missing tab, missing header) |
| R2A-04 no is_active column → RESOLVED, not inactive | `test_r2a_04_*` |
| R2A-05 is_active FALSE → RESOLVED + INACTIVE | `test_r2a_05_*` |
| R2A-06 equivalent to accepted R1 | `test_r2a_06_branch_resolution_is_equivalent_to_accepted_r1` (18 cases), `..._read_failures_match_r1_unavailability`, `..._get_branches_response_is_byte_compatible` |
| R2A-07 model known → RESOLVED | `test_r2a_07_*` (incl. unmodified mock seed) |
| R2A-08 model unknown → UNKNOWN_CODE | `test_r2a_08_*` |
| R2A-09 model read failure → REFERENCE_UNAVAILABLE | `test_r2a_09_*` |
| R2A-10 model invents no active semantics | `test_r2a_10_*` (+ stray column ignored) |
| R2A-11 part active → RESOLVED + ACTIVE | `test_r2a_11_*` |
| R2A-12 part inactive → RESOLVED + INACTIVE | `test_r2a_12_*` |
| R2A-13 part unknown → UNKNOWN_CODE | `test_r2a_13_*` |
| R2A-14 part read failure → REFERENCE_UNAVAILABLE | `test_r2a_14_part_read_failure_*` (mock error, fake 500, missing tab); R1: `test_r2a_14_part_missing_required_header_is_schema_invalid_fake[part_id/name/is_active]`, `..._full_phase5_sheet_without_is_active_*`, `..._part_table_without_is_active_column_*_mock` |
| R2A-15 mock/fake parity | `test_r2a_15_*` |
| R2A-16 never empty / zero / default | `test_r2a_16_*` |
| R2A-17 no DELETE on the branch/model/part resources | `test_r2a_17_*` (master collection/item paths only; the existing reads and `POST /parts` still exist) |
| R2A-18 accepted R1 registry/branch operations still exist | `test_r2a_18_accepted_r1_registry_and_branch_operations_still_exist` (13-operation subset; additional routes allowed) |
| R2A-19 R1 registry capability membership not widened | `test_r2a_19_r1_registry_capability_membership_is_not_widened` (three capabilities × ADMIN/MAINTENANCE_MANAGER in, MAINTENANCE/SUPERVISOR/TECHNICIAN/DRIVER out; new capabilities allowed) |
| R2A-20 R1 registry/branch regression green | the unchanged R1 suites, §10 |

Additional tests:

- `test_r2a_model_duplicate_id_*`
- `test_r2a_part_minimal_reference_columns_resolve_true_and_false_fake` (R1)
- `test_r2a_part_active_metadata_edge_cases_fake` (blank / `yes` / lower-case `false` → `DATA_INVALID`; duplicate)
- `test_r2a_part_reference_read_is_one_request_and_not_a_core_schema`
- `test_r2a_resolver_is_read_only_and_reads_each_source_once`

## 10. Regression

Run on the Revision R1 candidate, 2026-10-06. The R0 values are shown for comparison.

| Check | R1 result | R0 |
| --- | --- | --- |
| A. Directly affected backend tests (every 7O2a–d, 7B2, 7H2, 7J2, part, model and REV05 suite + R2a) | 1426 passed | 1420 |
| B. R2a tests | **63 passed** | 57 |
| C. Backend full suite | **3130 passed** (accepted baseline 3067 + 63 R2a) | 3124 |
| D. Backend ruff, accepted rule set (`E4,E7,E9,F`) | **13 findings, identical to the base**; none in R2a files | 13 |
| D'. Backend ruff, installed ruff 0.16.8 default rules | 688 on base and on candidate, identical ignoring line numbers; R2a files: `All checks passed` | 688 |
| E. Frontend unit suite | 58 files, **645 passed** | 645 |
| F. Typecheck + build | exit 0 | exit 0 |
| G. Frontend lint | exit 0; **33 warnings**, as the baseline | 33 |
| H. Playwright inventory | **565 tests in 23 files**, unchanged; the frontend tree is byte-identical to the base | 565 |
| I. Playwright full suite | **565 passed** (5 Chromium viewport projects), first run | 565 |

The R1 fix tests were also run against the previous candidate (`beec1030…`):

- the three `is_active` tests fail there (`[is_active]`, `full_phase5_sheet_without_is_active`,
  `part_table_without_is_active_column`);
- all three pass on R1.

R2A-20 is satisfied: every unchanged R1 suite is green inside A and C.

Note on D: the ruff installed in this environment (0.16.8) enables more rules by default than the run that recorded
the accepted 13. The accepted figure is reproduced exactly with the classic default rules. Under both rule sets, the
base and the candidate are identical.

## 11. Explicitly out of scope (not done)

- **Endpoints and UI:** no new endpoint, frontend change, UI, mutation/write route, capability, role-mapping
  change, pending-intent family or outcome-allowlist change.
- **R1:** no change to `parse_reference_rows`, `GET /branches`, the registry response shape, branch filtering,
  branch mutations, timeline/`BHR1`, settlement, or `asset_branch_history` (the R1 Rev2 contract stays frozen).
- **Other masters:** none of personnel, technician representation, driver/person link, department, workshop or
  position, and none of their schemas.
- **Model and part:** no model writes or active semantics; no part edit/deactivate/lifetime/installation/replacement
  (R6).
- **Elsewhere:** no equipment-branch work (R2b), repair, PM, permissions, live Sheets tabs or columns, `_CORE_SCHEMAS`
  change, or PostgreSQL.

## 12. Live Google Sheets

No live Google Sheets workbook was read or written by this batch, its tests or its verification. All Sheets
behaviour was exercised on the fake HTTP transport. No live tab or column was created. All fixtures are synthetic
(`SYN-` ids and labelled names), and no real personnel, technician, account or employee data is used.

## 13. R2b readiness note

R2b (equipment branch read) can use `MasterReferenceResolver.resolve_branches` to resolve the branch ids on
`asset_branch_history` rows with `asset_type=EQUIPMENT`. The R1 timeline module stays untouched. R2b still needs its
own decisions, recorded in the readiness report REV1 §17:

- the equipment projection column;
- capabilities, if writes follow;
- whether the current-branch display needs a projection at all.

R2a takes none of these decisions.
