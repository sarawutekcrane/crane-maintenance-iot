# R2 — Batch R2b — Equipment Branch History Read — Batch Result

BATCH: R2 Batch R2b, one backend-only read endpoint, `GET /api/v1/equipment/{equipment_id}/branch-history`, built on
the reviewed R2b readiness report (Option C).

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE (REVISION R1), AWAITING INDEPENDENT REVIEW**

**Revision R1 (independent review fix, tests and documentation only).** The first candidate (patch SHA-256
`a0e86504…2800`, 72,682 bytes) passed review with one future-compatibility fix.

- **Kept, approved:** the three one-line additions to the R1 inventory tests (§2).
- **R2B-17** no longer asserts that every role holds `can_view`. It proves only R2b's requirement: a caller without
  `can_view` gets 403 with zero repository reads, and explicit callers with it (ADMIN, MAINTENANCE_MANAGER) succeed.
- **R2B-20** no longer asserts these as permanent rules:
  - that the equipment branch route set is exactly the one GET;
  - that no equipment branch capability exists;
  - that no DELETE exists anywhere under `/equipment`.

  It now pins only:
  - the R2b GET;
  - the frozen vehicle GET;
  - no DELETE on the equipment master resources (`/equipment`, `/equipment/{equipment_id}`);
  - the frozen R1 capability memberships;
  - the vehicle and equipment response contracts (`test_r2b_20_vehicle_response_contract_is_not_widened`, unchanged).
- The candidate-only absence facts moved to §13 as one-off review evidence. **R2d may later add equipment branch
  mutations and capabilities, after its own approved design review, without violating R2b.**
- No production file changed in R1. `equipment_branch_history.py`, `equipment_branch_routes.py` and `router.py` are
  byte-identical to the reviewed candidate.

R1 is closed and frozen. R2a is integrated and accepted. WHOLE PHASE 7: **PARTIAL**. Nothing here changes those
statuses.

This batch has no UI, no frontend change, no write, no new capability, no projection column or migration, and no
live Google Sheets access. No PostgreSQL. No R2c or R2d work.

## 1. Baseline

| Item | Value |
| --- | --- |
| Integration branch `web/phase7-dashboard-search-reporting` (local = origin) | `6d35709598455ea6ed171dfe2c26d2a83f8ea8d4` (R2a) |
| Review branch (local only) | `review/r2-batch-r2b-equipment-branch-history-read`, created from exactly that SHA |
| `main` | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (untouched) |
| Candidate | uncommitted; full `candidate.patch` against the base SHA |

## 2. Scope

| File | Change |
| --- | --- |
| `backend/app/domain/equipment_branch_history.py` | **new**: `equipment_history_rows`, `equipment_timeline` (no-history adaptation), `EquipmentBranchHistoryService` |
| `backend/app/api/v1/equipment_branch_routes.py` | **new**: the route, `EquipmentBranchHistoryResponse`, the equipment mapper |
| `backend/app/api/v1/router.py` | additive: one import and one `include_router` |
| `backend/tests/test_equipment_branch_history_batch_r2b.py` | **new**: mock and domain tests |
| `backend/tests/test_equipment_branch_history_sheets_batch_r2b.py` | **new**: fake Google Sheets transport tests |
| this document | **new** |
| `backend/tests/test_branch_write_batch7o2c.py`, `test_registration_write_batch7o2b.py`, `test_registry_read_api_batch7o2a.py` | **one added expected line each** (flagged for review, see below) |

**Flagged for review: three accepted R1 inventory tests needed one expected entry each.** Each of these R1 tests
pins the exact set of OpenAPI paths whose text contains `branch` (or `province` / `registration`):

- `test_exactly_five_branch_mutation_routes_and_strict_bodies`;
- `test_only_the_two_registration_mutations_exist`;
- `test_no_registry_mutation_route_exists`.

The approved R2b path `/equipment/{equipment_id}/branch-history` contains `branch`, so with no test change all three
fail (3 failed, 3186 passed). No route renaming is allowed, so I followed the repository's own precedent: 7O2b and
7O2c updated these same tests by adding their routes with a batch comment. Each test now gets exactly one entry,
`f"{API}/equipment/{{equipment_id}}/branch-history": {"get"},  # R2b (read only)`.

- Nothing was removed or loosened. Every R1 entry, the request-body assertions and the vehicle mutation probes are
  unchanged.
- The tests still fail if any R1 route disappears or changes method, and if any other `branch` route appears,
  including an equipment branch mutation.

No other production file changed. In particular, none of these was modified:

- R1 domain: `branch_timeline.py`, `vehicle_history_rows`, `registry_service.py`;
- R1 API: `registry_routes.py`, `registry_schemas.py`;
- authz and repositories: `authz.py`, `repositories/base.py`, the mock and Google Sheets repositories;
- equipment: `EQUIPMENT_SHEET` and the equipment domain;
- R2a: `master_reference.py`;
- the frontend.

## 3. Option C — frozen semantics

R2b uses the R1 branch-history envelope with the equipment projection explicitly `NOT_IN_SCHEMA`. The frozen R1
functions are reused **unchanged**: `validate_branch_row`, `derive_timeline`, `history_revision` (BHR1),
`TimelineEvent` and `BranchTimeline`.

The service calls `derive_timeline(rows, master_branch_id=None, master_available=False, context)`. That gives:

- `master` is always `{"state": "NOT_IN_SCHEMA", "value": null}`.
- **With history**, consistency is always `UNDETERMINED`. It is never `CONSISTENT` or `PROJECTION_MISMATCH`: there
  is nothing to compare against. The current branch is derived from history as R1 derives it: `EVENT`, `BASELINE`,
  `UNDETERMINED` for an ambiguous order, or `NONE` only when the recorded baseline itself says `NONE`.
- A baseline already recorded in history is read and serialized exactly as recorded. It does **not** establish an
  equipment projection. No baseline is ever derived from `equipment_master`.

## 4. No-history semantics

R1's derivation with no records and no master gives `current={null, "NONE"}`. That would claim the equipment
authoritatively has no branch. `equipment_timeline` changes **only** that case:

- `current = {"branch_id": null, "source": "UNDETERMINED"}`;
- `consistency = "NO_HISTORY"` (the history fact);
- every other field is unchanged, including the BHR1 revision of the empty set.

R2B-02 pins that the adapter differs from `derive_timeline` only in this case.

## 5. Equipment selector

`equipment_history_rows(rows, equipment_id)` includes a row when `text(asset_id) == equipment_id` and
`asset_type != "VEHICLE"`. Matching is exact text: no trim, normalization or case folding.

- EQUIPMENT rows are included.
- VEHICLE rows are excluded.
- Blank or malformed `asset_type` rows for this ID are included, so the frozen validator reports
  `ASSET_TYPE_INVALID`. A blank type also gives `FIELD_REQUIRED:asset_type`.

This is the mirror image of `vehicle_history_rows`, which is unchanged; R2B-06 pins both on the same rows.

## 6. 7K2 lookup and error reuse

Order:

1. `can_view`;
2. registry data context;
3. `EquipmentService.get_equipment` (the accepted 7K2 validated locate, unchanged);
4. one `asset_branch_history` read;
5. selection;
6. frozen validation and derivation;
7. the no-history adaptation;
8. serialization.

Equipment errors are preserved unchanged: `EQUIPMENT_NOT_FOUND` (404), `EQUIPMENT_ID_AMBIGUOUS` (409, `match_count`),
`EQUIPMENT_MASTER_SCHEMA_INVALID` / `EQUIPMENT_MASTER_DATA_INVALID` (500) and `EQUIPMENT_MASTER_READ_FAILED` (503).
History is read only after a successful lookup; R2B-03 checks this on mock and fake.

History errors reuse the R1 `registry_tab_error` and `data_invalid`:

- `BRANCH_HISTORY_SCHEMA_INVALID` (500, `{tab, problem, headers}`);
- `BRANCH_HISTORY_READ_FAILED` (503, `{tab}`);
- `BRANCH_HISTORY_DATA_INVALID` (500, `{tab, issues}`) with the frozen issue vocabulary (`ASSET_TYPE_INVALID`,
  `CUTOVER_INCOMPLETE`, revision, baseline and event issues).

A failed read is never an empty success.

## 7. Shared data context

R2b reuses `settings.registry_context_effective`; there is no new setting. Vehicle and equipment rows share one
`asset_branch_history` table, so they need one TEST/REAL interpretation.

- Mock mode is TEST.
- Google Sheets mode with the context unset gives 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any repository
  read (mock and fake: zero requests).
- REAL keeps the frozen behaviour: TEST-flagged rows give `CUTOVER_INCOMPLETE`.

## 8. API response contract

`GET /api/v1/equipment/{equipment_id}/branch-history`, gated by `can_view`, returns `EquipmentBranchHistoryResponse`.

| Field | Value | Class |
| --- | --- | --- |
| `asset_type` | `Literal["EQUIPMENT"]` | equipment wrapper |
| `asset_id` | the located `equipment_id` | equipment wrapper |
| `timeline_status` | `VALID` / `AMBIGUOUS_ORDER` | R1, unchanged |
| `current` | `BranchCurrentResponse`; `UNDETERMINED` when there is no history | equipment wrapper over R1 |
| `master` | `RegistryFieldResponse`, always `NOT_IN_SCHEMA` | no projection |
| `consistency` | `NO_HISTORY` / `UNDETERMINED` | no projection |
| `history_revision` | BHR1 over this equipment's selected rows | R1, unchanged |
| `baseline` / `events` / `records` | `BranchBaselineResponse` / `BranchEventResponse` / `BranchRecordResponse` | R1 sub-models, unchanged |
| `excluded_test_rows` / `issues` | `0` / `{}` | R1, unchanged |

The R1 `BranchHistoryResponse` is **not** widened: its `asset_type` stays `const: "VEHICLE"`, pinned by R2B-20. The
equipment mapper repeats the R1 vehicle mapping in its own module, so the vehicle route is untouched. R2B-18 pins
parity for identical rows: `timeline_status`, `baseline`, `events`, `records`, `excluded_test_rows` and `issues` are
equal, and the current source is the same. The only differences are `asset_type`, `asset_id`, `master`,
`consistency` and the no-history current.

## 9. No-projection proof

- No projection-like column is read. The route has no `equipment_master` reader of its own; it only uses the 7K2
  locate, which maps the declared columns.
- R2B-19 (fake Sheets) adds an unapproved `responsible_branch_id` column with a value to `equipment_master`:
  - `master` stays `NOT_IN_SCHEMA`;
  - `current` comes from history, or is `UNDETERMINED`;
  - the body is identical to the one without the column.
- `EQUIPMENT_SHEET` is unchanged, and no column name is assumed.

## 10. Mock / fake parity

R2B-14 compares the mock and fake-Sheets HTTP results on six scenarios: mixed assets, no history, all cancelled,
recorded imported baseline, ambiguous order and malformed type. Status codes and bodies are identical, apart from the
per-request `request_id` inside error envelopes. All fixtures are synthetic.

## 11. Request-cost measurements (fake transport, not live Sheets)

| Request | Cold (metadata, values) | Warm (metadata, values) |
| --- | --- | --- |
| `GET /equipment/{id}/branch-history` | **(3, 2)** | **(0, 2)** |

These are the same as the R1 vehicle branch-history route.

- The 2 values reads are `equipment_master` (locate) and `asset_branch_history`.
- There are **0** `branch_master` and **0** `maintenance_plan` reads. The test backend has no `branch_master` tab at
  all, and the route still answers 200 (R2B-13).
- There are **0** writes.
- In mock mode, the only repository calls are `get_equipment_validated` and `read_asset_branch_history_validated`
  (R2B-16).
- R2a's `MasterReferenceResolver` is not called: history is authoritative by stable branch ID, so a `branch_master`
  outage cannot hide it.

## 12. Test matrix and results

All IDs are batch-local PROPOSED identifiers. There are **59 R2b tests**: 39 mock/domain and 20 fake-Sheets.

| ID | Test(s) |
| --- | --- |
| R2B-01 valid EQUIPMENT history | `test_r2b_01_valid_equipment_history` |
| R2B-02 no history → UNDETERMINED / NO_HISTORY, never NONE | `test_r2b_02_no_history_*` (empty table; only vehicle rows with the same id), `test_r2b_02_adapter_changes_only_the_no_history_current` |
| R2B-03 lookup errors, no history read | `test_r2b_03_equipment_lookup_errors_stop_before_history` (mock), `test_r2b_03_unknown_or_non_exact_equipment_id_is_404`, `test_r2b_03_equipment_lookup_errors_over_sheets` (not found, ambiguous, tab/header missing, record invalid, read failed), `test_r2b_03_context_unset_*` |
| R2B-04 history schema/read failure coded | `test_r2b_04_r2b_15_history_failure_*` (mock), `test_r2b_04_history_failure_over_sheets_*` (tab missing, no header row, live-style 9-column header, read failed) |
| R2B-05 vehicle route excludes EQUIPMENT rows | `test_r2b_05_*` |
| R2B-06 equipment route excludes VEHICLE rows | `test_r2b_06_*` (route + selector mirror) |
| R2B-07 malformed type surfaced | `test_r2b_07_*` (blank, lower case, mixed case, foreign value, leading space) |
| R2B-08 correction/cancellation = frozen timeline | `test_r2b_08_*` |
| R2B-09 same-instant ambiguity | `test_r2b_09_*` |
| R2B-10 all cancelled → recorded baseline only | `test_r2b_10_*` |
| R2B-11 TEST/REAL incl. CUTOVER_INCOMPLETE | `test_r2b_11_*` |
| R2B-12 BHR1 stable and scoped | `test_r2b_12_*` |
| R2B-13 no `branch_master` read | `test_r2b_13_*` (mock failure fixture never requested; fake with no tab) |
| R2B-14 mock/fake parity | `test_r2b_14_*` (6 scenarios) |
| R2B-15 read failure ≠ empty | in R2B-04 |
| R2B-16 zero writes; warm cost 2 values reads | `test_r2b_16_*`, `test_r2b_13_r2b_16_request_cost_cold_and_warm` |
| R2B-17 `can_view` | `test_r2b_17_*`: the route enforces `can_view`. A caller without it gets 403 with zero repository reads; explicit callers holding it (ADMIN, MAINTENANCE_MANAGER) succeed. Other or future roles are not constrained. |
| R2B-18 serialization parity with the vehicle route | `test_r2b_18_*` (3 scenarios × 2 baselines) |
| R2B-19 extra projection-like column ignored | `test_r2b_19_*` (fake; with and without history) |
| R2B-20 permanent guardrails and R1/R2a regression | `test_r2b_20_*`: the R2b GET exists; the frozen vehicle branch-history GET exists; no DELETE on the equipment master resources; the R1 registry capabilities are held by exactly ADMIN + MAINTENANCE_MANAGER; `BranchHistoryResponse` stays VEHICLE-only; `EquipmentBranchHistoryResponse` stays EQUIPMENT-only with consistency `NO_HISTORY` / `UNDETERMINED`. It does **not** freeze future equipment branch routes or capabilities (R2d). Plus §13. |

### Results (2026-10-06, on the candidate)

| Check | Result |
| --- | --- |
| A. New R2b tests | **59 passed** (39 mock/domain + 20 fake Sheets); R1 revision: **59 passed** (R2B-17 and R2B-20 edited, none added) |
| B. Directly affected suites (every 7O2a–d, equipment/7K2, 7B2, R2a and R2b suite) | **1254 passed** |
| C. Backend full suite | **3189 passed** (accepted baseline 3130 + 59 R2b) |
| D. Backend ruff, accepted rule set (`E4,E7,E9,F`) | **13 findings, identical to the base**; none in R2b files |
| D'. Backend ruff, installed ruff 0.16.8 default rules | 692 (base 688): the only additions are 4 `B008` (`Depends(...)` in route defaults) in `equipment_branch_routes.py`, the pattern every FastAPI route here already uses (234 `B008` in the base, 12 in the R1 `branch_routes.py`) |
| E. Frontend unit suite | 58 files, **645 passed** |
| F. Typecheck + build | exit 0 |
| G. Frontend lint | exit 0; **33 warnings**, as the baseline |
| H. Playwright inventory | **565 tests in 23 files**, unchanged; the frontend tree is byte-identical to the base |
| I. Playwright full suite | **565 passed** (5 Chromium viewport projects), first run |

**Revision R1 re-run (tests and documentation only):**

- the 59 R2b tests plus the 3 R1 inventory tests: **62 passed**;
- the affected suites: **1254 passed**;
- the full backend suite: **3189 passed**;
- ruff, accepted rule set: **13, identical to the base**; the ruff 0.16.8 default rules give the same 692 findings as
  the reviewed candidate.

No production or frontend file changed in R1, so the frontend and Playwright results above (645 / build / 33 / 565 /
565) stand unchanged, and Playwright was not re-run for this fix.

Before the three R1 inventory-test entries were added (§2), the full backend suite gave 3186 passed and 3 failed:
those three tests, which pin every path containing `branch`. With one added entry each, everything is green.

## 13. R1 / R2a compatibility

- **R1:** the vehicle branch routes, `BranchHistoryResponse`, `vehicle_history_rows`, the timeline validation and
  event model, BHR1, the TEST/REAL rules and the R1 capabilities are unchanged. R1 files are not modified; R2b only
  imports from them.
- **R2a:** `MasterReference` and `MasterReferenceResolver` are unchanged and unused by the route. The R2a route and
  capability guardrails stay green: R2A-17 (no DELETE on branch/model/part), R2A-18 (R1 subset present; new routes
  allowed) and R2A-19 (R1 capability membership).
- **Not frozen:** the whole API inventory and the future equipment branch surface. R2b's committed tests protect only
  R2b itself and the frozen prior contracts. R2d may later add approved equipment branch mutations and capabilities
  without violating R2b.

**One-off review evidence for this candidate (facts at the candidate, not permanent tests).** These were checked on
the candidate tree:

- only the new equipment branch GET was added;
- there are **no equipment branch mutation routes**: the only `/equipment/{equipment_id}/branch*` operation is the
  GET;
- **no equipment branch capability** was added, and `ALL_CAPABILITIES` is unchanged;
- `backend/app/domain/authz.py` is **byte-identical to the base**;
- there are **no write routes** and **no writes**: the fake transport records zero writes, and the mock calls only
  the two reads;
- no DELETE route exists anywhere under `/equipment`.

## 14. Live-UAT blocker

The live `asset_branch_history` still has the old 9-column schema. Against it, this route answers 500
`BRANCH_HISTORY_SCHEMA_INVALID`, as the vehicle route already does (reproduced in R2B-04 with a 9-column header). This
is a **LIVE UAT BLOCKER** shared with R1.

Nothing was migrated or created live. R2b's mock and fake acceptance is independent of it. No live Google Sheets
workbook was read or written.

## 15. Explicitly out of scope (not done)

- **Mutations:** branch transfer, insertion, correction, cancellation, projection reconciliation and equipment
  projection writes.
- **Mutation machinery:** request-id mutation workflow, pending-intent family, outcome classification and an equipment
  branch capability.
- **Elsewhere:** UI or frontend panel, equipment projection column, migration, live Sheets, PostgreSQL, and R2c/R2d.

## 16. Open decisions for R2d

1. Whether `equipment_master` stores a current projection, and its exact column name.
2. Equipment branch mutation capabilities and their role mapping (must not broaden the R1 vehicle capabilities).
3. How an equipment baseline is created, including whether `IMPORTED_MASTER` is meaningful without a projection. R2b
   only reads a recorded baseline as recorded.
4. Thai copy for an equipment branch panel (no Screen Register ID is available).
