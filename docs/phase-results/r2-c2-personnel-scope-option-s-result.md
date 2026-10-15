# R2-C2 — Personnel Scope Closure (Option S) — Result

Status: **IMPLEMENTED AND TESTED.** The implementation stage completed on the local branch
`review/r2-c2-personnel-scope-option-s` without commit or push. The owner subsequently authorized a single
review-branch commit/push. Integration requires separate owner approval. No push, integration, merge or deployment
happened during the implementation stage.
Governance: `docs/project-governance/r2-c2-personnel-scope-option-s-amendment.md` (owner decisions S1–S4).
R2-C2a and R2-C2b have NOT started.

## 1. Baseline

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `d7659186f98c1a6b7e2685e17fa2f39b8a2df528` (P0 + P0b integrated) |
| Tree | `4b32cfbb658761807eb62bf55a17bf3187c98755` |
| Main | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged) |
| Review branch | created locally from that HEAD; during the implementation and testing stage, the local review branch HEAD remained at the approved integration baseline; no commit was created in that stage |
| Backend suite at the baseline (executed in this step, on an exact `git archive` snapshot of the HEAD) | **4859 passed, 0 failed**, 919 warnings |

## 2. Changed files (13 — the authorized allowlist exactly)

| Status | Path | +/− |
|---|---|---|
| M | `backend/app/domain/personnel.py` | +52 / −24 |
| M | `backend/app/api/v1/personnel_routes.py` | +24 / −7 |
| M | `backend/app/repositories/google_sheets/repository.py` | +3 / −1 |
| M | `backend/tests/test_personnel_read_batch_r2c1.py` | +80 / −43 |
| M | `backend/tests/test_personnel_read_sheets_batch_r2c1.py` | +7 / −4 |
| M | `backend/tests/test_department_read_batch_r2c2.py` | +3 / −1 |
| M | `backend/tests/test_personnel_lifecycle_batch_r2e.py` | +6 / −2 |
| M | `backend/tests/test_relationship_read_batch_r2f_a.py` | +4 / −1 |
| M | `backend/tests/test_personnel_department_history_batch_r2f_g.py` | +12 / −4 |
| M | `backend/tests/test_technicians_scope_batch_r2f_h4_b2.py` | +7 / −2 |
| A | `backend/tests/test_personnel_scope_option_s.py` | 364 lines, 49 tests |
| A | `docs/project-governance/r2-c2-personnel-scope-option-s-amendment.md` | governance amendment |
| A | `docs/phase-results/r2-c2-personnel-scope-option-s-result.md` | this document |

Unchanged: Google Sheets schema declarations (`PERSONNEL_MASTER_READ_SHEET` keeps its five required columns), the
mock repository and seeds, the department domain / routes / schema / seeds, the R2e / R2f / E2 / R2f-f / Technician V2
/ legacy driver code, authorization, frontend and all existing governance documents.

## 3. Root cause

R2c-1 `PersonnelService._read` applied `operational_rows()` — keep exactly-`FALSE` rows — in EVERY server context,
while the R2e / R2f personnel reads use the server context (`master_lifecycle.in_scope`). Mock mode is always TEST, so
(measured before the change on the live mock app):

| ID | Seed flag / batch | Personnel detail | R2e / R2f personnel reads (6) |
|---|---|---|---|
| PER-TEST-001..003 | FALSE / blank | 200 (and listed) | 404 |
| PER-TEST-901 | TRUE / `MOCK-SEED-R2C1` | 404 | 404 |
| PER-TEST-911 / -912 | TRUE / mock batch | **404, not listed** | **200** |

## 4. Implementation

- **`personnel.py`.**
  - `PersonnelService(repository, context, batch_id)` proves the context first with the shared
    `require_write_context` (503 before any read).
  - It then runs the existing validated read and error mapping. In TEST only, it checks that `test_batch_id` is in
    the read header (otherwise 500 `PERSONNEL_MASTER_SCHEMA_INVALID` `{tab, problem: MISSING_HEADERS, headers:
    ["test_batch_id"]}`).
  - `scoped_rows()`, which replaces `operational_rows()`, skips rows with no personnel content, fails closed on any
    flag other than exact `TRUE` / `FALSE`, and keeps the rows matching the shared `master_lifecycle.in_scope` — the
    same scope authority R2e / R2f use, not a new one.
  - Identity checks, sorting, paging and the public record are unchanged.
- **`personnel_routes.py`.** `get_personnel_service` injects `settings.registry_context_effective` and
  `effective_test_batch_id(settings)`, as in the O4 technician routes. `can_view` is still checked in the handler
  before the service runs, so 403 comes before 503 with zero reads. Route documentation now lists the
  503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` and the TEST missing-column 500. No route, parameter or model is added.
- **Google Sheets repository.** `read_personnel_master_validated()` passes `("test_batch_id",)` as a text-only
  column to the existing `_registry_table`. The same single request is made; the column is not required (a missing
  text-only column is skipped by `_numericise_ignore_columns`), and numeric-looking batches stay exact text.

## 5. Behaviour after the change

| Server context | `GET /personnel`, `GET /personnel/{id}` |
|---|---|
| REAL | exact-`FALSE` rows only; output identical to before (all 122 R2c-1 tests pass with every assertion unchanged in an explicit REAL context) |
| TEST | exact-`TRUE` rows whose `test_batch_id` is exactly the server batch; other-batch / blank-batch / REAL rows excluded (detail 404) |
| UNCONFIGURED, or TEST without a batch | 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any repository read (`{setting: REGISTRY_TEST_BATCH_ID}` for the missing batch) |
| No `can_view` | 403 before the context check, zero reads |

Mock after the change (in-process tests and a live `uvicorn` mock server on 127.0.0.1, executed):

| ID | List | Detail and all six R2e / R2f personnel reads |
|---|---|---|
| PER-TEST-911 / -912 | listed (total 2) | 200 on all seven |
| PER-TEST-001..003 | not listed | 404 on all seven |
| PER-TEST-901 (other batch) | not listed | 404 on all seven |

Client-supplied `context`, `scope`, `test_batch_id`, `is_test_data` query parameters and `X-Data-Context`-style
headers are ignored (live server and test `OPS-CFG`). `/me` still reports `data_context: TEST`.

## 6. Five-column Sheets compatibility and text preservation (fake transport only)

- REAL with the five-column header (no `test_batch_id`) → 200, the REAL rows (`OPS-SHEETS`). The original
  "only the five used columns are required" R2c-1 test passes unchanged in an explicit REAL context.
- TEST with the five-column header → 500 `PERSONNEL_MASTER_SCHEMA_INVALID`, `headers: ["test_batch_id"]`, never an
  empty list.
- Batches `"007"`, `"0012"` and `"7"` each select exactly their own rows; the read returns `test_batch_id` values
  `"", "007", "0012", "7"` exactly. Before the change the probe showed `"007"` read back as `7`, losing the row.
- Request cost is unchanged in REAL and TEST: cold 2 metadata + 1 values request, warm 0 + 1, only `personnel_master`.
- The fake transport and the mock agree in REAL and TEST for the list and three detail ids.

## 7. Deliberately updated existing tests (S3)

| File | Change | Why |
|---|---|---|
| `test_personnel_read_batch_r2c1.py` | Tests call `real_get` (the original `get` with an explicit REAL server context; `get` gains an optional `settings` and keeps its default behaviour for the modules that import it). `test_r2c1_01_seeded_mock_is_synthetic_and_served` expects PER-TEST-911 / -912 in mock (TEST) and still checks the REAL listing of the same seed. The pure helper test uses `scoped_rows(rows, "REAL", "")`. | These tests pin the REAL contract; mock is TEST. Every original assertion is kept. |
| `test_personnel_read_sheets_batch_r2c1.py` | `Settings` override gains `registry_data_context=REAL`; parity uses `real_get`. | Without a context the read is now 503 (S1). Assertions unchanged. |
| `test_department_read_batch_r2c2.py::test_r2c2_26` | mock personnel total 3 → 2 | scope change; no-department-leak guard unchanged |
| `test_personnel_lifecycle_batch_r2e.py::test_r2e_36` | total 3 → 2; the blank-status probe blanks PER-TEST-911 in its isolated mock instance (PER-TEST-003 is out of the TEST scope) | scope change; "blank still null" guard unchanged |
| `test_relationship_read_batch_r2f_a.py::test_r2fa_10` | the probed person P-1 becomes a TEST row of the mock batch | scope change; join-free / single-read guard unchanged |
| `test_personnel_department_history_batch_r2f_g.py::test_r2fg_legacy_personnel_read_and_lifecycle_are_unchanged` | its personnel GET runs in an explicit REAL context (new optional `settings` on the module's `http` helper; default unchanged) | P-1 and its seeded history are REAL-scope; guard unchanged |
| `test_technicians_scope_batch_r2f_h4_b2.py::test_r2fh4b2_fix_04` | mock list expects PER-TEST-911 / -912; the REAL listing still has 3 | scope change; seed-preservation guard unchanged |

No test was deleted, skipped or weakened.

**Helper-sharing caught during implementation.** `test_relationship_read_batch_r2f_a.py` imports the R2c-1 `get`
helper. Defaulting that helper to REAL would have silently moved the R2f-a tests into a REAL context. So `get` keeps
its default, and the R2c-1 file uses an explicit `real_get`.

## 8. New focused tests — `test_personnel_scope_option_s.py` (49)

| Group | Proves |
|---|---|
| OPS-REAL | FALSE rows only, sorted and paged; exact id (`0012` ≠ `12`, `012`); source text preserved; a TEST id is 404 in REAL |
| OPS-TEST | server batch only, sorted and paged; other / blank batch and REAL rows excluded (404); the same id in REAL and TEST is not ambiguous; duplicate in scope → 500 list / 409 detail; blank id in scope → 500; another scope's identity defects ignored; no flag / batch in responses |
| OPS-CFG | unconfigured → 503 with zero reads (list, detail); TEST with blank batch → 503 `{setting: REGISTRY_TEST_BATCH_ID}` with zero reads; client query / headers never select a scope |
| OPS-SCHEMA | read columns remain the five; invalid flag fails closed in TEST (list, detail); classification before identity |
| OPS-SHEETS | five-column header serves REAL; TEST without the column → controlled 500; numeric-looking batches exact; request cost unchanged; fake = mock in both contexts |
| OPS-AUTH | 403 with zero reads before the context check (TEST and UNCONFIGURED); TECHNICIAN (can_view) reads |
| OPS-XSYS | PER-TEST-911 / -912 resolve on list, detail and all six R2e / R2f personnel reads, with their technician / account links and the reverse technician → personnel read; PER-TEST-001..003 and -901 excluded everywhere; one store read in both contexts has no overlap and nothing is written |

Mutation check (runtime patch, scratchpad only): ignoring the batch fails 11 of these tests; falling back to REAL
when unconfigured fails 6.

## 9. Test results (all executed in this step)

| Run | Result |
|---|---|
| Baseline full backend (exact HEAD snapshot) | **4859 passed, 0 failed**, 919 warnings |
| New Option S tests | **49 passed** |
| R2c-1 mock + Sheets (updated) | **122 passed** |
| Five cross-batch guard files (complete files) | **260 passed** (85 warnings, identical to the baseline snapshot) |
| Full backend after the change (run twice) | **4908 passed, 0 failed** (= 4859 + 49 new), 920 warnings; 15:09 and 15:27 |
| Frontend Vitest | **798 passed** (66 files) |
| Frontend lint (`oxlint`) | exit 0 (pre-existing warnings only) |
| Frontend build (`npm run build`: `tsc -b && vite build`) | passed |
| Playwright on the live mock backend: `responsive-shell`, `technician-v2-only`, `technician-v2`, `technician-v2-withdrawal`; 5 viewport projects | **105 passed, 0 failed** |
| Live `uvicorn` mock server HTTP checks (section 5) | as tabulated |

Warning delta (+1). The extra warning is the pre-existing `RuntimeWarning: coroutine 'Spy.__getattribute__.<locals>
.wrapper' was never awaited`, reported at garbage-collection time inside the go-live readiness failure-path tests
(16 baseline vs 17 in the full run). Run alone, those two readiness files give 16 warnings on both the baseline
snapshot and the change, in two runs each. The readiness report does not call the R2c-1 read. Classification:
garbage-collection attribution of an existing warning, not a new warning source (INFERRED).

Not run:
- the remaining Playwright specs (28 in total);
- a UI-level personnel page E2E: no Playwright spec covers the personnel pages, which is UNVERIFIED at the browser
  level and covered by the live HTTP checks and Vitest.

The frontend source is unchanged.

## 10. Limitations and unverified conditions

- **Department scope (unchanged).** The R2c-2 Department Master list / detail remain operational-only. In mock, the
  department pages do not show TEST departments. R2-C2a must not present Department Detail resolution as supported in
  TEST. A separate impact analysis and owner authorization are required.
- **Unconfigured deployments (UNVERIFIED).** A Google Sheets deployment without `REGISTRY_DATA_CONTEXT` now answers
  503 on the personnel pages instead of REAL rows. The R2e / R2f personnel and technician routes already do. Whether
  any deployment leaves it unset is a deployment verification item.
- **Live TEST.** The live master carries no TEST rows of a configured batch today, so live TEST lists nothing and
  never a REAL row (C1 §15).
- TEST rows with a blank or other batch are silently out of scope (not an error), matching R2e / R2f.

## 11. Safety confirmation

- No live Google Sheets access: all Sheets behaviour uses the fake transport.
- No REAL data read or changed.
- No Google Sheets header, schema or data change.
- No change to the mock seed data, R2e / R2f / E2 / R2f-f authorities, Technician V2, the Department Master, legacy
  driver assignments or the frontend.
- No commit, push, merge or deployment occurred during the separately authorized implementation and testing stage.

## 12. Next owner approval checkpoint

Owner review and verification of the 13-file Option S change set and its review-branch commit. Fast-forward
integration requires separate owner approval. Then, each separately authorized:
1. R2-C2a frontend;
2. any Department scope analysis.
