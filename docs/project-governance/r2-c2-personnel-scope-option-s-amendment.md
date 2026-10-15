# R2 — Governance Amendment — Personnel Scope Option S (R2c-1 Personnel Read in the Server Data Scope)

Status: **OWNER-APPROVED (S1–S4).** Implementation and testing completed under the original coding-only
authorization on the local branch `review/r2-c2-personnel-scope-option-s`. The owner subsequently authorized
review-branch commit/push. Integration requires separate owner authorization.

**Authority.**
- the read-only "Personnel Scope Closure (Option S) — Final Contract Impact Review" (this session, 2026-10-15);
- "R2-C2 Personnel Scope Closure (Option S) — Owner Authorized — Implementation & Testing Only" (this session,
  2026-10-15), which approves the owner decisions S1–S4 recorded in §1.

**Nature.** ADDITIVE. Like A1 and A2, this amendment supplements the frozen Corrected C1 contract. It does not edit
C1, A1 or A2, and it supersedes only the single R2c-1 rule quoted in §2. Every other C1 / A1 / A2 obligation is
unchanged.

## 1. Owner decisions

| Id | Decision |
|---|---|
| S1 | An unconfigured server data context answers 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any personnel repository read. TEST without a server batch id is treated the same way. |
| S2 | The original five-column REAL read contract is preserved. In TEST, the `test_batch_id` metadata column is required, the batch must match the server-owned batch exactly, and numeric-looking batch values are preserved as exact text. |
| S3 | Existing test assertions and settings invalidated by this accepted contract change are deliberately updated, preserving each test's original purpose and safety coverage. |
| S4 | This additive governance amendment and a phase-result document record the intentional supersession of the R2c-1 operational-only rule. |

## 2. Superseded rule

The R2c-1 independent-review fix R1 (`docs/phase-results/r2-batch-r2c1-personnel-read-foundation-result.md`, §6
"Operational data scope (TEST / REAL)", and the `backend/app/domain/personnel.py` module docstring) stated:

> R2c-1 is the **operational** personnel read. … `TRUE` | explicitly test row | **excluded** from the list,
> `total_items` and detail … `test_batch_id` stays internal and is not interpreted; there is no TEST personnel view.

That rule applied in every server context. In the mock (always TEST) it made the Personnel Master pages list the
`FALSE` seed rows, which the R2e / R2f personnel reads treat as out of scope (404), while the TEST personnel those
reads resolve could not be opened from the Personnel Master pages. Only this rule is superseded.

## 3. New rule — Personnel read in the server data scope

`GET /api/v1/personnel` and `GET /api/v1/personnel/{personnel_id}` read in the SERVER-DERIVED scope: the registry data
context (`REGISTRY_DATA_CONTEXT`; always TEST in mock mode) and the effective test batch (`REGISTRY_TEST_BATCH_ID`, or
the labelled mock batch in mock mode). It is the same rule as the R2e / R2f personnel reads
(`master_lifecycle.in_scope`) and the O4 technician list.

| Server context | Personnel list and detail |
|---|---|
| REAL | rows whose `is_test_data` is exactly `FALSE` — unchanged from R2c-1 |
| TEST | rows whose `is_test_data` is exactly `TRUE` **and** whose `test_batch_id` is exactly the server batch |
| UNCONFIGURED, or TEST without a batch | 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`, before any repository read (S1) |

- **Order.** `can_view` is checked first (403 with zero reads). Then the context is proven, the single validated
  `personnel_master` read runs, and in TEST the `test_batch_id` column is checked. Every row with personnel content
  then has its flag classified: any value other than exact `TRUE` / `FALSE` fails the read closed (500
  `PERSONNEL_MASTER_DATA_INVALID`, `TEST_FLAG_INVALID`). Finally the rows are filtered to the scope, and the
  existing identity checks and list / detail logic run on the in-scope rows only.
- **TEST batch isolation.** A `TRUE` row of another batch, or with a blank batch, is out of scope (list exclusion;
  detail 404), as in R2e / R2f. A REAL row never appears in TEST and a TEST row never appears in REAL.
- **TEST-only batch column (S2).** In TEST, a read whose header lacks `test_batch_id` fails as 500
  `PERSONNEL_MASTER_SCHEMA_INVALID` `{tab, problem: MISSING_HEADERS, headers: ["test_batch_id"]}`. It is never
  answered with an empty list.
- **Five-column REAL compatibility (S2).** The required read columns stay exactly `personnel_id`, `first_name`,
  `last_name`, `active_status`, `is_test_data`. `test_batch_id` is not a universally required sheet header. The
  Google Sheets repository reads it, when present, as exact text (no numeric conversion) within the same single
  request, so `"007"` stays `"007"`.
- **No client-selectable scope.** No query parameter, header or body selects or widens the scope. Scope is never
  inferred from a personnel id, name or prefix.
- **Unchanged.** Routes and methods, `can_view`, the public response (`personnel_id`, `first_name`, `last_name`,
  `active_status`), paging, ordering, exact-text identity, blank / duplicate identity fail-closed behaviour (now
  evaluated over the returned scope), active-status and name text preservation, and the read / schema error codes.

## 4. Relationship to A1, A2 and the O4 precedent

- This applies the A1-§15 / O4 technician rule (server-derived scope; 503 before any read when unconfigured; TEST rows
  of exactly the server batch; no client scope) to the personnel list and detail.
- It closes the personnel half of the R2-C2 mock-fixture scope gap recorded in the R2-C2-P0 / P0b results. DQ-C4
  (R2-C2a personnel panels may be route-mocked; final C2a acceptance needs the personnel scope fix) is satisfied for
  the personnel pages once this change is integrated.
- A2 (R2f-f permanent driver, E2 operational assignments, legacy cutover) is unaffected. C1 §15 fail-closed rules are
  unchanged. This includes "live TEST relationship and responsibility UAT is impossible until explicitly TEST-scoped
  reference masters exist": with the live master untagged, live TEST lists nothing and never a REAL row.

## 5. R2e / R2f compatibility

No R2e lifecycle, R2f relationship, link-history, reconciliation, department-history, Technician Master, Technician V2,
E2 or R2f-f authority, history or audit rule changes. The personnel read now selects the same identities those reads
already resolve. In mock: PER-TEST-911 / -912 resolve on the list, the detail and all R2e / R2f personnel reads;
PER-TEST-001..003 and the other-batch PER-TEST-901 are excluded from all of them.

## 6. Deliberately updated test contracts (S3)

Recorded as deliberate evolutions in the same way as A1-§23. Each test keeps its intent; only its scope expectation
or its explicit context changes.
1. `tests/test_personnel_read_batch_r2c1.py`: the REAL-contract tests call `real_get`, the original `get` with an
   explicit REAL server context; every assertion is unchanged. `test_r2c1_01_seeded_mock_is_synthetic_and_served`
   now expects the mock batch's TEST personnel in mock (TEST) and still checks the REAL listing of the same seed.
   The pure helper test uses `scoped_rows(rows, "REAL", "")`, the successor of `operational_rows`.
2. `tests/test_personnel_read_sheets_batch_r2c1.py`: the fake-transport `Settings` override gains
   `registry_data_context=REAL`; the mock / fake parity uses `real_get`. All assertions are unchanged, including the
   "only the five used columns are required" test.
3. Five cross-batch "personnel GET unchanged" guards:
   - `test_department_read_batch_r2c2.py::test_r2c2_26`;
   - `test_personnel_lifecycle_batch_r2e.py::test_r2e_36`;
   - `test_relationship_read_batch_r2f_a.py::test_r2fa_10`;
   - `test_personnel_department_history_batch_r2f_g.py::test_r2fg_legacy_personnel_read_and_lifecycle_are_unchanged`;
   - `test_technicians_scope_batch_r2f_h4_b2.py::test_r2fh4b2_fix_04`.

   Each now expects the server-scoped identities, or runs its personnel GET in an explicit REAL context. Their
   guards (response shape, no joins, no department / lifecycle leak, single personnel read) are unchanged.

## 7. Data and schema

No REAL record, Google Sheets header, Google Sheets data or production schema is changed, and live Google Sheets is
never accessed. Mock seed data is unchanged.

## 8. Remaining limitations

- **Department scope.** The R2c-2 Department Master list / detail remain operational-only (`department.py`). This
  amendment does not change them. R2-C2a must not present Department Detail resolution as supported in TEST. Any
  department scope change needs its own impact analysis and owner authorization.
- **Unconfigured deployments.** A Google Sheets deployment without `REGISTRY_DATA_CONTEXT` now answers 503 on the
  personnel pages instead of REAL rows. The R2e / R2f personnel routes and the technician routes already behave this
  way. Whether any deployment leaves the context unset is UNVERIFIED and is a deployment verification item, not a
  change made here.
- **Live TEST.** Live TEST personnel are listed only if the live tab carries `TRUE` rows of the configured batch
  (C1 §15 unchanged).
