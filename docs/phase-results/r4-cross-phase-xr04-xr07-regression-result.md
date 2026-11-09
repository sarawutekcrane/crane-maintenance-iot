# R4 / TASK-010 — Cross-Phase Regression Contract: R4-XR-04 / R4-XR-07 Evidence — Result

**Status:** TESTS-ONLY CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is
Mock/Fake evidence only. It is not a PostgreSQL PASS, not Production readiness, not R4 acceptance and not R11 security
acceptance. No Git write action was taken.

**Authorization:** Owner-approved bounded tests-only batch on `feature/r4-pm-readiness-reconciliation-b1`, exact base
`b05436a5bf086ad752eeafab5e1d84bdff614750` (RT4-A). It closes the two open test-evidence rows of the Owner-approved
`docs/project-governance/r4-cross-phase-regression-contract.md` §3 (R4-XR-04, R4-XR-07). No application behavior was
changed, and no defect was found.

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-readiness-reconciliation-b1` = `b05436a…614750` (exact base, fetched) |
| Isolated checkout | A fresh clone of the remote branch in the session scratchpad, at the base, with push disabled. The earlier session checkout (holding the byte-identical RT4-A working copy) was not touched. |
| HEAD after work | Unchanged at the base; every change unstaged |

## 2. R4-XR-04 — exact-source identity, never symptom-text identity
**Contract:** two different `PM_RESULT` source ids with identical symptom text stay independent; each exact source
still blocks its own second request (`REPAIR_REQUEST_SOURCE_ALREADY_REPORTED`), whatever the text; a refusal leaves no
orphan.

**Source checked:**
- `RepairRequestService.create` validates the source (`_require_defect_source_exists`, a real `find_pm_work_result`)
  and calls `_require_source_not_already_reported` (an exact `list_repair_requests_by_source`, any status) **before**
  the meter/location capture.
- No symptom comparison exists.

**New evidence** (`test_repair_request_duplicate_source_prevention.py`, real HTTP, Mock repository):
- `_two_pm_results` produces two **legitimate** PM Work Results through the existing Technician V2 / E01 flow
  (the `_open_pm_result` pattern):
  - open PMP-0001 on VEH-1047;
  - assign the seeded V2 team and START;
  - save PMT-0002 Performed, then PMT-0001 Not Performed.
- Both results are re-read from storage: distinct ids, same Work Order, their own task ids. Nothing is inserted
  directly, and the retired legacy `/results` route is not used.

| Test | Proves |
|---|---|
| `test_xr04_distinct_pm_results_with_identical_symptoms_stay_independent` | Both requests are accepted (distinct RRQ ids), each with its own exact `PM_RESULT` id and the identical symptom. Re-reading each, and `GET /repair-requests/by-source/PM_RESULT/{id}`, return only its own request. No Repair Work Order or PM Work Order is created. A MANUAL report with the same text is still accepted. |
| `test_xr04_each_exact_pm_result_still_blocks_its_own_duplicate_whatever_the_text` | Re-reporting A, and independently B, with the same text **and** with different text gives 422 `REPAIR_REQUEST_SOURCE_ALREADY_REPORTED`. The details name **that** source and **its own** request (never the other). Repair Requests, meter snapshots, location snapshots, Repairs and PM Work Orders are all unchanged. |

**Reused, unchanged:**
- `test_manual_reports_with_identical_symptom_text_remain_allowed` (MANUAL);
- `test_second_rrq_from_same_finding_is_rejected` and the cancel/convert-then-retry Finding cases (FINDING exact-source
  dedup);
- the Mock and fake-Sheets orphan-free rejection tests (R4-XR-05).

## 3. R4-XR-07 — Finding-only L11 authority isolation
**Contract:** `can_manage_finding_repair` authorizes Finding-provenance work only. It never implies `can_manage_pm`,
PM_RESULT Repair Request management, `can_manage_repair` or any PM Master write.

**Source checked:**
- **Conversion:** `POST /repair-requests/{id}/convert` passes the route gate with either `can_manage_repair` or
  `can_manage_finding_repair`. The service then applies `authz.require_source_scoped_repair_authority`, using
  **server-built** provenance (`r3_finding_id`, never a client flag): a Finding target needs the Finding capability,
  and anything else needs `can_manage_repair`.
- **PM routes** require `can_manage_pm`.
- **PM Master writes** go through `MasterAuthorizer`. The application one, `deny_unproven_master_authority`, refuses
  everyone (VAL-AM).
- **Delegation:** `can_manage_finding_repair` is delegable (not in `SENSITIVE`); a delegate may hand on only its list,
  only inside its department, and never onward.

All four tests run in Access Management mode on the synthetic AM seed, through the real HTTP stack. Capabilities come
only from the audited grant and delegation API.
- **Shared world (`_xr07_world`):** a real R3 Finding request and a real **PM_RESULT** request. The PM result comes
  from a V2 Work Order opened by a root-granted PM manager, the team is assigned, and the primary technician starts it
  and saves an item. Both requests are PENDING.
- **Refusal checks:** each refusal asserts 403 **and the exact capability it names**:
  - `requires the 'can_manage_repair' capability` from the service predicate;
  - `requires the 'can_manage_pm' capability` from the PM routes;
  - or, for an actor holding neither, the route gate `requires one of [...]`.
  So a fixture failure cannot pass as a denial.
- **No writes:** Repairs, PM Work Orders, PM results and request statuses are byte-identical after every refusal.
- **Positive controls:** each refused target is shown to exist and to be served to an authorized actor:
  - the PM_RESULT request converts for a `can_manage_repair` holder;
  - an authorized PM manager reaches the business rules (409 job-state errors, never 403);
  - a new PM Work Order opens for the PM manager.
- **Master checks (`_refuse_master_writes`):**
  - A TEST-scope Master is **legitimately seeded and published by the TEST persona** (`TEST_PM_MASTER_EDITOR`). The
    Finding-only actor is never given a persona.
  - The actor's **real effective context**, built exactly as `dependencies.get_current_context` builds it
    (`AccessService(..., cutover.data_context, cutover.test_batch_id).effective_context`), calls preview, review,
    publish, assign, approve and revoke under **both** the application authorizer and the TEST persona authorizer.
  - Every call returns 403 `PM_MASTER_AUTHORITY_UNPROVEN`. Revisions, assignments, previews, resolutions, approvals
    and audit events are unchanged, and the head stays revision 1.

**Authorization matrix:**

| Actor (capabilities) | Finding RRQ convert | PM_RESULT RRQ convert | PM WO open / assign / cancel / close | Master preview, review, publish, assign, approve, revoke |
|---|---|---|---|---|
| CLERK: `can_manage_finding_repair` + `can_view` (direct grant) | **200** | **403** `can_manage_repair` | **403** `can_manage_pm` ×4 | **403** `PM_MASTER_AUTHORITY_UNPROVEN` ×6 ×2 authorizers |
| DRV2: `can_manage_finding_repair` only, granted by delegate OPM | — | **403** | **403** ×4 | **403** ×12 |
| OPM: delegate of [`can_manage_finding_repair`] for OPS | — | — | — | grants Finding to DRV2 **200**; `can_manage_pm`, `can_manage_repair` or both **403**; onward delegation **403**; own capabilities stay `[]` |
| MGR: root holder with only `can_manage_finding_repair` + `can_view` | — | **403** | **403** ×4 | **403** ×12 |
| MGR after a **separate** explicit `can_manage_pm` grant | — | — | open **200** (independent right honoured) | (still VAL-AM) |
| CLERK after revocation (`can_view` only) | **403** (route gate) | **403** (route gate) | **403** ×4 | — |
| OPM after delegation revocation | — | — | — | grant **403**; DRV2 and OPM capabilities `[]` |
| MGR + `can_manage_repair` (control) | — | **200** | — | — |
| TECH2: PM manager (control) | — | — | business 409s, never 403 | — |

| Test | Scenarios |
|---|---|
| `test_xr07_01_02_a_finding_only_grantee_converts_finding_work_but_never_pm_result_work` | XR07-01, XR07-02 |
| `test_xr07_03_04_finding_authority_opens_no_pm_work_and_writes_no_pm_master` | XR07-03, XR07-04 |
| `test_xr07_05_neither_root_nor_a_finding_delegate_manufactures_pm_or_master_rights` | XR07-05 (delegation path and root; the separate PM grant is honoured) |
| `test_xr07_06_revoking_the_finding_grant_or_its_delegation_takes_effect_on_the_next_request` | XR07-06 (grant and delegation revocation; nothing inherited) |

**Reused, unchanged:**
- `test_am_16_17_*` (Finding delegate runs Finding work; MANUAL repair and PM open 403; revocation for Repair
  opening);
- `test_am_16b_*` (MANUAL request convert 403; Finding convert 200);
- `test_am_08_19_*` and `test_am_09_10_11_*` (delegation confinement and revocation);
- `test_b1_13_*` and `test_b1_fix_03_*` (Master denial for root or `can_manage_pm`).

The new tests add only what those lacked: a PM_RESULT target, PM Work Order management, Master writes by a
Finding-only AM context, the Finding-only delegation path, and revocation of the Finding grant.

## 4. Mutation checks (disposable copies under the session scratchpad; the repository was never mutated)
| Mutant | Where (disposable copy) | Killed by (reason) |
|---|---|---|
| X1 symptom-text dedup of PM_RESULT requests | `repair_request_service.create` | `xr04_distinct…` (second distinct result refused 422), `xr04_each…` |
| X2 exact PM_RESULT duplicate not rejected | `_require_source_not_already_reported` | `xr04_each…` (200 instead of 422) |
| X3 Finding accepted as general repair authority | `authz.require_source_scoped_repair_authority` | `xr07_01_02`, `xr07_03_04`, `xr07_05` (PM_RESULT conversion 200, Repair created) |
| X4 Finding accepted as PM authority | `authz.require_capability` | `xr07_01_02`, `xr07_03_04`, `xr07_05` (PM Work Order opened, 200) |
| X5 Finding accepted as Master write authority | `pm_master.deny_unproven_master_authority` | `xr07_03_04`, `xr07_05` (Master write did not raise) |
| X6a Finding grant revocation ignored | `access_management.AccessState.grants` | `xr07_06` (revoked capability still listed) |
| X6b delegation revocation ignored | `access_management.AccessState.delegations` | `xr07_06` (revocation not effective) |

**7 / 7 killed**, each by the escalation or duplicate actually happening (200, or DID NOT RAISE), never by a crash or
import error. A first X1 formulation compared the stored `source_type`, which is always empty: provenance is encoded
in `note_th` and decoded by `_with_decoded_provenance`. That mutant could never trigger. It survived for that reason
and was replaced with the decoded comparison before counting. It is not a test gap.

## 5. Test results (synthetic Mock / Fake data only; `pytest -q -rs -p no:cacheprovider`, scratch venv from `pyproject.toml` `[dev]` + `requirements.txt`)
| Run (from `backend/`) | Result |
|---|---|
| New XR-04 + XR-07 tests | **6 passed** |
| `test_repair_request_duplicate_source_prevention.py` + `test_access_management.py` | **33 passed** |
| Affected (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_r3_*`, `test_access_management*`, `test_repair_request*`, `test_defect_provenance`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_rev062_queue_derivation`, `test_rev06_identity_and_core_g01_regression`; 56 files) | **1414 passed, 0 failed, 4 skipped** (4m25s) |
| Full backend `pytest -q -rs tests` | **5910 passed, 0 failed, 4 skipped** (16m43s; RT4-A was 5904, plus the 6 new tests). Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and 3 live Google Sheets tests. |
| Firewall tests (`test_23`, `f24`, `f25`, `b1_13`, `b1_17`, `r2_07`) and RT1–RT4-A suites | inside the runs above, unchanged |
| Final-bytes re-run | After both runs, one whitespace-only import-block change (a blank line, for the lint rule) was made in `test_access_management.py`. Both touched modules were re-run on the final bytes: **33 passed**. The SHA-256 values in the manifest are those final bytes. |
| `git diff --check` | clean |
| ruff (`--isolated` defaults; changed files vs. the base file at the same path) | no new findings |
| Secret scan | no matches |

## 6. Files (4 allowed, 3 changed)
| Path | Status | Change |
|---|---|---|
| `backend/tests/test_repair_request_duplicate_source_prevention.py` | M | XR-04: `_two_pm_results`, `_report`, `_stored_counts`, 2 tests; one import |
| `backend/tests/test_access_management.py` | M | XR-07: `_xr07_world`, `_work_state`, `_refuse_pm_and_repair_management`, `_effective_context`, `_refuse_master_writes`, 4 tests |
| `docs/phase-results/r4-cross-phase-xr04-xr07-regression-result.md` | A | This report |
| `backend/tests/test_pm_master_b1_mock.py` | not changed | Not necessary: its existing fixtures are imported, not modified |

No application, route, adapter, Sheets, frontend, schema or governance file was touched.

## 7. Mandatory Cleanup Review
| Item | Class | Evidence / impact |
|---|---|---|
| New XR-04 tests | RETAIN (new) | The only proof of identical-text independence for **PM_RESULT** ids (the existing test covers different FINDINGs with different text) |
| `_two_pm_results` | RETAIN (new) | Reuses `http_start` / `http_save` and the `_open_pm_result` flow. It needs both result ids, which `_open_pm_result` (returns one) does not expose; no parallel fixture framework. |
| New XR-07 tests and helpers | RETAIN (new) | Reuse `http`, `grant`, `delegate`, `caps`, `_r3_finding` and the B1 Master fixtures. They add only the rows existing AM tests lack (§3). |
| `test_am_16_17_*`, `test_am_16b_*` | RETAIN | Still the Finding-positive evidence. Their PM-open 403 overlaps XR07-03 by design; XR07-03 adds the existing-Work-Order actions and the exact-capability assertion. |
| `_effective_context` vs `test_access_management_identity._am_context` | RETAIN | `_am_context` hard-codes a batch id. The new helper follows `dependencies.get_current_context` exactly (cutover settings); not merged, to avoid touching an unrelated test module. |
| Existing MANUAL / FINDING dedup tests | RETAIN | Reused as evidence; not duplicated |
| `RepairRequestService._require_source_not_already_reported` docstring ("PENDING or already CONVERTED") | DEFER | Pre-existing wording noted by the contract (XPR-03); behavior is status-independent; production code is out of scope |
| Route gate vs service predicate double check for conversion | RETAIN | Two layers by design (L11); both proven by the exact refusal messages |

No destructive cleanup.

## 8. Remaining R4 / R11 limitations
- **Mock only.** AM authorization, the event log and Repair Request dedup are proven on the Mock repository. The
  Sheets AM mode answers 501. PostgreSQL needs a unique key on (`source_type`, `source_id`) for FINDING / PM_RESULT
  Repair Requests, and the AM grant fold and Master authority in the database (R11).
- **The Master stays dormant and VAL-AM stays fail-closed for every actor.** XR-07 proves the Finding capability adds
  nothing; it does not establish any Master authority (OPEN-005).
- **Provenance encoding.** Repair Request provenance is still encoded in `note_th` (fixed Sheets schema). A
  PostgreSQL schema should carry real source columns (R11).
- Not changed: OPEN-012, OPEN-016, E02, R11 durability, the D-2 Fleet Due snapshot (RT4-B) and the D-3 orphan open
  snapshot.
- **R4 remains PARTIAL.**
