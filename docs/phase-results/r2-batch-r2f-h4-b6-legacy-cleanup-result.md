# R2 Batch R2f-h4 B6 — Technician V2 Only: Legacy Assignment Backend Cleanup + Owner Policy Enforcement — Result (Rev2)

Status: B6 REV2 CANDIDATE / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified, and production
readiness is not claimed. This document replaces the original B6 candidate result (patch `f8ca64fd…`, tree
`ceddda55…`); the Rev2 patch is one complete candidate relative to the B5 Integration baseline.

Contract:
- C1 Amendment A1 (`docs/project-governance/c1-amendment-a1-v2-only.md`) §3 (safe legacy removal, groups B and C),
  §24–§26, §31;
- the B4 and B5 results;
- owner authorization "R2f-h4 B6 — OWNER AUTHORIZATION: GO — LOCAL IMPLEMENTATION CANDIDATE ONLY" (decisions D1, D2,
  D3);
- owner authorization "R2f-h4 B6 Rev2 — Final Owner Decision: Technician V2 ONLY — Remove ON/OFF and Legacy
  Creation — OWNER AUTHORIZATION: GO — LOCAL CANDIDATE REVISION ONLY".

Baseline:
- Integration `web/phase7-dashboard-search-reporting` @ `83665121119af8762e7c4979af0f91ce7a12bf0c`
  (tree `9493015d1323877630a9f0674fada77b01dc85e0`; B5 integrated);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged).

Local branch: `review/r2-batch-r2f-h4-b6-legacy-cleanup` (no remote, no upstream). Nothing is staged, committed or
pushed.

Scope boundaries:
- no schema migration: no tab, header or column is added, removed or reordered;
- no live Google Sheets access: Sheets behaviour is proven with fake transports only;
- no data conversion, deletion or rewrite: every stored legacy and V2 row stays byte-identical;
- no role or capability change;
- D5 stays PENDING; H3-01 stays fail-closed.

## 1. Owner decisions implemented

| Decision | Rule | Where |
| --- | --- | --- |
| V2-only (Rev2) | Technician V2 is the only assignment model. Every new Repair and PM job, including a Repair Request conversion, is a `TECHNICIAN_V2` job. There is no ON/OFF setting, no legacy creation and no legacy fallback. | `repair_service.create_repair`, `pm_service.open_work_order`, `config.py`, `technician_assignment.AssignmentCutover`, `/me`, readiness report, frontend |
| D1 | A Repair / PM job that is not exactly `OPEN` accepts no technician assignment change (no new set, no withdrawal). | `require_open_job` in `app/domain/technician_assignment.py` |
| D2 | On an OPEN job a manager may replace the PRIMARY, change the COLLABORATORs (the existing V2 assignment route) or withdraw the WHOLE current set; a withdrawn job stays OPEN, shows as NONE in U1, leaves V2 My Work and keeps its immutable history. | `TechnicianAssignmentService.withdraw`; `POST /{job}/technician-assignment-withdrawals`; frontend panel |
| D3 | The legacy (user_id-based) assignment write paths and legacy-only queues are retired; legacy storage, history and identity are kept. | `app/domain/legacy_assignment_retired.py`; `repairs.py`, `pm.py`, services |

## 2. V2-only creation (Rev2)

### Behaviour

- **Direct Repair creation** (`POST /repairs`), **PM opening** (`POST /pm/work-orders`) and **Repair Request
  conversion** (`POST /repair-requests/{id}/convert`, which calls the same `create_repair`) always pass the V2 job
  marker: `assignment_model = TECHNICIAN_V2` plus the job's scope flags. These are all the creation entry points; the
  audit found no other caller of the repository create methods.
- **Order of checks in a creation:**
  1. capability (route);
  2. inline legacy assignee refused (422);
  3. input validation (asset, source, plan, revision, scope tasks);
  4. the V2 data-context proof and the extended-header proof (`v2_job_marker`);
  5. the first write (the automatic meter snapshot), then the job.

  Input validation comes before the V2 proof because that was the order under the former default, so input errors keep
  their existing codes. Both proofs run before any write.
- **Fail-closed, no legacy fallback:** when the data context is not configured, a TEST context has no batch id, the
  context is live TEST, or the extended job header is missing, creation fails with zero writes. It is never turned
  into a LEGACY job. The proof is the B6 Rev2 tests b6r2_08 and b6r2_10, and mutations R03–R05.
- **Unchanged:** authentication, capabilities, input validation, the conversion's idempotency (a repeated conversion
  returns the same job) and its integrity guard, and TEST/REAL isolation. In mock mode a job is TEST-scoped (mock
  batch); in a REAL context it is REAL-scoped.
- **Repair Request submission** (`POST /repair-requests`) does not create a job and was never gated; it is unchanged.

### Obsolete ON/OFF dependencies removed

| Dependency | Change |
| --- | --- |
| `Settings.technician_assignment_v2_enabled` (`TECHNICIAN_ASSIGNMENT_V2_ENABLED`) | Removed. A leftover environment variable or settings value is ignored (`extra="ignore"`) and changes nothing (b6r2_01, h1 cut_01). |
| `AssignmentCutover.enabled` | Removed. The type keeps its name and now carries only the server's data context (context, TEST batch, live flag). |
| `repair_service` / `pm_service` creation branch | The `if self._cutover.enabled` branch is removed; the V2 marker is always computed and passed. |
| `GET /me` field `technician_assignment_v2_enabled` | Removed (`MeResponse` = `user_id`, `roles`, `capabilities`, `data_context`). Every consumer was updated first: frontend `serverSignals.ts`, `types.ts`, `V2ContextBanner`, the three creation pages and the tests. |
| Readiness report `cutover_enabled` (response field, `environment` key, service argument) | Removed. It was informational only; no check depended on it, and H3-01 is unchanged. |
| Frontend `signals.v2Enabled`, the "การมอบหมายช่างยังไม่เปิดใช้งาน" state (`V2_DISABLED_MESSAGE`, `V2CreationDisabled`, `v2-cutover-state`, `v2-creation-disabled`) | Removed. Repair create, PM start and conversion are offered by capability alone, as before B5. The B5 double-submit guards are kept. The data-context banner stays and blocks nothing. |
| Playwright `cutover-off-*` projects, their isolated backend/frontend pair, and `technician-v2-off.spec.ts` | Retired with the setting. The suite backend starts without the variable, which is the former default-OFF condition, and creates V2 jobs. The OFF spec is replaced by `technician-v2-only.spec.ts`. |

Not removed:
- unrelated feature flags;
- the data-context signal;
- capability checks;
- the historical phase-result documents and the governance amendment text, which still describe the former setting
  as history (section 10).

## 3. D1 — CLOSED enforcement

- Error: `409 TECHNICIAN_ASSIGNMENT_JOB_CLOSED`, details `{status}`.
- Order of checks, for both assign and withdraw: capability (route) → `X-Request-Id` → body → context → job →
  model / scope → one validated tab read → **replay** → **OPEN (D1)** → ambiguity → stale → write.
- Replay comes first on purpose: a request that was applied while the job was OPEN still replays its stored outcome
  after the job is closed (nothing new is written). Every other request on a CLOSED job is refused before any write.
- Reads are not affected: the current set and the complete history of a CLOSED job stay readable.
- Any status other than the exact string `OPEN` is refused (fail closed).

## 4. D2 — direct replacement, withdrawal, reassignment, U1 and My Work

- **Direct replacement:** the existing V2 assignment route (`POST /{job}/technician-assignments`) replaces the PRIMARY
  and/or the COLLABORATORs of an OPEN job in one append-only set, with the exact `expected_current`. No intermediate
  withdrawal or legacy step is needed.
- **Withdrawal:** ONE appended row in the job's existing shared assignment tab, using only columns that already exist
  for V2 sets.

| Column | Value |
| --- | --- |
| record id | `<RTA|PTA>-<digest>-1-1`, digest = `set_digest(kind, job, request_id, [("WITHDRAWAL", "")])` |
| `assignment_role` | `WITHDRAWAL` (`ROLE_WITHDRAWAL`) |
| `assignee_type` | `TECHNICIAN` (marks the row as V2) |
| `assignee_id` | blank |
| `assigned_at` / `assigned_by_user_id` | the withdrawal instant and the actor |
| `request_id` / `request_fingerprint` | idempotency (fingerprint op `<kind>_withdrawal`) |
| `reason_th` | the optional reason |
| `is_test_data` / `test_batch_id` | the job's scope (TEST / REAL isolation) |
| `user_id`, `ended_at`, `active_status` | blank, as for every V2 row |

Why this representation:
- **Append-only:** the previous set is never ended, deleted or rewritten.
- **No schema change.**
- **Same integrity discipline as a set:** the digest binds the job, the request id and the content.
- **Same concurrency and idempotency discipline:** `expected_current` must name the exact current set (with no current
  set every withdrawal is stale); replay and request-id reuse work as for assignment.
- **Rejected alternatives:**
  - an empty set would break the one-PRIMARY invariant;
  - ending the previous rows would rewrite stored rows;
  - a new tab or column would be a schema migration;
  - a synthetic PRIMARY would be fabricated data.

Derivation (`derive_assignment_state`):
- Sets and withdrawals form one event stream.
- If the latest event is a withdrawal, the status is `NONE` with no current set. It is never `DATA_INVALID`.
- A later set is the normal reassignment, which makes the job `VALID` again.
- Fail-closed codes:
  - `WITHDRAWAL_ASSIGNEE_NOT_BLANK`;
  - `WITHDRAWAL_INVALID`;
  - `WITHDRAWAL_WITHOUT_CURRENT_SET`;
  - `WITHDRAWAL_ORDER_AMBIGUOUS`.
- A tie at the latest instant gives `AMBIGUOUS`.

Effects, all derived from the same state:
- U1 lists a withdrawn OPEN job (and every new job) as `NONE`;
- both former members lose it from V2 My Work and lose V2 recording rights;
- reassignment uses `expected_current: null`.

Frontend (`TechnicianAssignmentV2Panel`, `lib/technicianV2.ts`):
- **Action:** "ถอนการมอบหมายช่างทั้งหมด", shown only to a manager, on an exactly-OPEN job with a non-AMBIGUOUS current
  set and no pending request.
- **Confirmation dialog:** names the PRIMARY and COLLABORATORs and has an optional reason.
- **Same R2e intent store:** the intent is stored before sending and records `operation: 'withdraw'`; a resend goes to
  the withdrawal route with the same id and body.
- **Outcomes:** `withdrawn` / `replayed` (reload through the normal reads); `stale` (reload, controls disabled);
  refusals with the Thai message, code and request id; UNKNOWN never shown as success.
- **History:** a separate withdrawal history section.
- **Reassignment:** after withdrawal, the standard picker form is offered.

## 5. Dependency and deletion-safety matrix (D3 + Rev2)

| Path / artifact | Verdict | Reason / evidence |
| --- | --- | --- |
| `TECHNICIAN_ASSIGNMENT_V2_ENABLED`, `AssignmentCutover.enabled`, the creation branch, `/me` flag, readiness `cutover_enabled`, frontend V2-OFF states, E2E OFF projects | REMOVE (Rev2) | Owner final decision: V2 only. Section 2. |
| Legacy (marker-less) job creation from any service or route | REMOVE (Rev2) | Every creation passes the V2 marker; mutations R01 / R02 caught. |
| `POST /repairs/{id}/assign`, `POST /pm/work-orders/{id}/assign` | REMOVE (410 tombstone) | No frontend caller since B5. The handlers take only the path id and raise `410 LEGACY_ASSIGNMENT_RETIRED` before any read or write. |
| `GET /repairs/my-work`, `GET /pm/work-orders/my-work`, `GET /repairs/waiting-assignment` | REMOVE (410 tombstone) | Replaced by V2 `/my-work` and the U1 V2 queues. |
| `RepairService.assign`, `RepairService._notify_assignment`, `PmService.assign`, `AssignRepairRequest`, `AssignPmWorkOrderRequest` | REMOVE | Reachable only from the retired routes. |
| Inline `primary_technician` / `collaborators` on Repair create and Repair Request convert | ADAPT (refuse) | 422 `LEGACY_ASSIGNMENT_RETIRED` before any read or write. The request fields are kept so the refusal is explicit, never a silent drop. |
| Sheets legacy readers of the shared assignment tabs (5 sites) | ADAPT (required fix) | They skip V2 rows (non-blank `assignee_type`); a `WITHDRAWAL` row would otherwise break them, including every PM detail read. |
| V2 assign route; V2 assignment read | ADAPT | D1 added; additive `withdrawals` field. |
| Creation order in both services | ADAPT (Rev2) | Input validation before the V2 proof (the former default order); both precede any write. Mutation R06 caught. |
| Repository `create_repair` / `create_pm_work_order` `assignment_marker=None` signature | RETAIN | Shared repository contract (mock and Sheets). No service passes `None`; it remains only for test fixtures of historical LEGACY jobs. Docstrings updated. |
| Repository legacy writers `assign_repair` / `assign_pm_work_order` | RETAIN | Unreachable from the API. Shared contract. Used only by the test seed helper. |
| LEGACY-job read and authorization handling (`assignment_model` signal `LEGACY`, read-only legacy display, `/{job}/assignment-history`, legacy recording / attachment authorization, `ASSIGNMENT_MODEL_MISMATCH`) | RETAIN | Fail-closed handling of a stored LEGACY marker. Production starts with no LEGACY jobs, but the stored-row shape, shared tabs and history readers remain shared dependencies. Removing them is not needed for V2-only creation. |
| Header mirror `primary_technician` / `collaborators`; `AssignmentRole`; `GET /repairs?assigned_to=` and the repository filters | RETAIN | Read-only over stored legacy data; used by retained reads and tests. |
| `NotificationPort` and its wiring | RETAIN (dormant) | Removing it is unrelated cleanup. |
| Shared assignment tabs, every row, columns `user_id` / `ended_at` / `active_status`, identities, audit | RETAIN | Deletion or migration is prohibited. |
| Automatic conversion of stored LEGACY jobs; dropping legacy columns or rows | BLOCKED | Prohibited (no data migration, no destructive change). |
| Live Sheets prerequisites for creation (REAL data context, additive V2 job headers) | DEPENDENCY (deployment) | See section 10.1. Not a code change; no schema change is made here. |

## 6. History and audit preservation

- Withdrawal appends one row. Every existing row stays byte-identical, proven at the Sheets transport (B6 s01).
- Assignment sets, withdrawals (actor, instant, reason, record id) and legacy history stay readable.
- No row is ended, deleted or converted.
- V2-only creation changes no stored job: a job's model is its persisted marker, and a stored LEGACY job (fixture) is
  never relabelled (h1 cut_03).

## 7. Authentication, capability and scope safeguards

- Creation still needs `can_manage_repair` / `can_manage_pm`; TECHNICIAN, DRIVER and MAINTENANCE_MANAGER are refused
  (403) with zero writes (b6r2_06). Repair Request submission still needs `can_report_repair`.
- V2 assignment and withdrawal still need the per-kind manage capability (h1, B6 d2_06 / d2_15).
- TEST/REAL isolation:
  - the creation marker comes from the server's data context only (b6r2_09);
  - live TEST is refused;
  - V2 reads and writes keep their scope checks (h1, B6 d2_08, b3, h2).
- No new role, capability, setting or admin control was added.

## 8. API compatibility

- **Removed (owner-authorized, consumers updated first):** `/me` `technician_assignment_v2_enabled`; readiness
  `cutover_enabled` and `environment.cutover_enabled`.
- **Behaviour (owner-authorized):**
  - every created job is `TECHNICIAN_V2`;
  - the five retired legacy routes answer 410;
  - an inline legacy assignee gets 422;
  - assignment on a non-OPEN job gets 409.
- **Additive:**
  - the two withdrawal routes;
  - the `withdrawals` read field;
  - error codes `TECHNICIAN_ASSIGNMENT_JOB_CLOSED` and `LEGACY_ASSIGNMENT_RETIRED`.
- **Storage:** unchanged.

## 9. Test migration matrix (deliberate, marked)

Each migrated test keeps its invariant. Migrations are marked "R2 Batch R2f-h4 B6 (deliberate test migration)" or
"… B6 Rev2 (deliberate test migration)".

| Mechanism | Used by |
| --- | --- |
| `legacy_assign(client, path, json)`: gives the freshly created synthetic job the historical LEGACY marker in the mock store (Rev2: no route can create one; refused if V2 rows exist), seeds the legacy rows through the retained writer, and returns the GET detail | `test_core_demo_fixes_delta`, `_rev05`, `test_defect_provenance`, `test_pm_assignment_authority`, `test_pm_attachment_assignment_history_authorization`, `test_pm_close_assignment_termination`, `test_pm_my_work`, `test_repair_assignment_and_queues`, `test_repair_close_assignment_and_awaiting_parts`, `test_repair_pm_work_authorization`, `test_rev061_assignment_authority`, `test_rev062_attachment_authorization`, `test_rev062_queue_derivation`, `test_rev063_attachment_purpose_binding`, `test_web_uat_defect_fix` |
| `seed_historical_legacy_repair` / `_pm` (Rev2): a LEGACY job through the repository with no V2 marker; h1 `new_repair(repo, legacy=True)` replaces the former `enabled=False` | h1, b3, h2, h3, pre, B6 d3_05 |
| `mark_historical_legacy(...)` in the job-opening helpers of legacy-authority tests, with `mock_test_cutover()` (Rev2) | `test_rev061_assignment_authority`, `test_rev062_queue_derivation`, `test_pm_assignment_authority`, `test_pm_my_work` |
| `tests/v2_only_support.py` (Rev2): explicit `mock_test_cutover()` / `live_real_cutover()` for hand-built services (the application wires the context from settings; a service without one fails closed) | the above, `test_google_sheets_repair_real_io`, `test_rev061_conversion_recovery` |
| Fake-Sheets conversion fixtures with the additive V2 job and assignment headers, and a minimal faithful `FakeWorksheet.get` (full tab and `"1:1"` only; any other range refused) (Rev2) | `test_google_sheets_repair_real_io`, `test_rev061_conversion_recovery` (`test_google_sheets_real_io` fake) |
| `legacy_queue(...)` / `legacy_queue_page(...)`: the retained `list_repairs` / `list_pm_work_orders` derivation | as in B6, plus h2, 7c2, b3, h1 |
| Expectation changed to the retirement or to V2-only | h1 cut_01 (setting unconfigurable) / cut_02 (always V2) / cut_03 / cut_04 / cut_05 / sep_01; h1-sheets s02 (asset lookup stubbed so the schema proof is reached; zero writes) and s06; h2 ro_02; h3 overall_01 / ctx_02 and h3-sheets s02 (no `cutover_enabled`); pre model_04 / me_01 / safe_01 / safe_02 / safe_04; B6 d3_03 (always V2) / d3_04 / d3_05; rev05 (a new job waits in U1 as NONE); rev061 (historical-LEGACY fixture); 7c2; b3 valid_02 |
| Frontend unit tests (Rev2) | `TechnicianV2Cutover.test.tsx` (the OFF gate is replaced by "no leftover flag value blocks an authorized creation"), `technicianV2.test.ts` (`serverSignalsFrom` parses only the data context and ignores a leftover flag), `/me` stubs without the flag in five test files |
| E2E (Rev2) | `technician-v2.spec.ts` (`/me` has no flag; no `v2-cutover-state`); `technician-v2-off.spec.ts` retired with the OFF projects; new `technician-v2-only.spec.ts` |

## 10. Risks, dependencies and owner items

1. **Live Sheets prerequisites for creation (deployment dependency).** Under V2-only, creating ANY job in Google
   Sheets mode requires:
   - (a) `REGISTRY_DATA_CONTEXT` configured: REAL for production. If it is unset, creation fails closed with 503
     `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`.
   - (b) The additive V2 job headers on `repair_order` / `pm_work_order`, and the V2 assignment headers for
     assignment. Otherwise creation fails closed with 500 `TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID`.

   Under the former default-OFF, legacy creation needed neither. The new Production spreadsheet must therefore be
   provisioned with these already-defined columns. No schema change is made here; the live schema and settings stay
   separate approvals.
2. **Live TEST context refuses creation.** A Sheets-backed TEST deployment (for example a staging spreadsheet in the
   TEST context) cannot create jobs: 409 `TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED`, the existing H1 fail-closed
   rule, because no TEST-scoped technician master exists live. Mock TEST is unaffected. Changing this needs an owner
   decision.
3. **Governance and historical documents.** `c1-amendment-a1-v2-only.md` and the earlier phase results describe the
   former setting. They were not edited (historical records and the governance contract); the owner may want the
   amendment updated to the final decision.
4. **TOCTOU between the status read and the append (residual).** Google Sheets has no transactions. A close that lands
   between the job-status read and an assignment or withdrawal append can still be followed by that one append. It is
   recorded, audited and readable.
5. **Equivalent mutant F13.** The confirm button is disabled while submitting, so the `inFlight` ref is a second guard;
   removing both is caught (F13b).
6. **Pre-existing E2E flake `vehicle-registration-write` I-OC-01** (B5 report, unrelated). It did not recur in the
   Rev2 full run (654 / 654).
7. **Unchanged:** link population, R11, the live V2 schema and Go-live each need their own approval. D5 stays PENDING;
   H3-01 stays fail-closed.

## 11. Gates

| Gate | Result |
| --- | --- |
| Backend full `python -m pytest -q` | 4704 passed, exit 0 (first Rev2 run before the test migration: 414 failed / 4260 passed; then 1 failed / 4703 passed, fixed by migrating h1-sheets s02; final run clean) |
| Named R2f suites (`tests/test_*r2f*.py`) | 27 files, 1052 passed, exit 0 |
| Fake-Sheets suites (`tests/test_*sheets*.py`, `tests/test_google_sheets*.py`) | 37 files, 953 passed, exit 0 |
| Ruff delta vs base (51 touched / new backend files) | 179 → 165 findings; the only new findings are 4 × B008 (FastAPI `Depends`, existing pattern) on the two withdrawal routes |
| `npx tsc -b --noEmit` | exit 0 |
| `npx vitest run` | 66 files, 798 tests passed, exit 0 |
| `npx oxlint` | exit 0; 31 warnings, identical to base by file and rule |
| `npm run build` | exit 0 |
| `npx playwright test` | 654 passed, exit 0, first attempt, no retries (B6 Rev1 647 − 8 retired cutover-OFF runs + 15 new V2-only runs) |
| Mutations | Rev2: backend 10 / 10, frontend 5 / 5 caught. B6: backend 17 / 17, frontend 16 / 16 behavioural caught (+1 equivalent, F13), re-run on the Rev2 tree |

Rev2 mutations (each restored and hash-verified after its run):

| Mutant | What was broken | Caught by (first failures) |
| --- | --- | --- |
| R01 / R02 | Repair / PM created without the V2 marker (legacy) | b6r2_02 / b6r2_03 and many more |
| R03 / R04 | Repair / PM: a failed V2 proof silently falls back to legacy | b6r2_08 |
| R05 | the Repair V2 proof after the snapshot write | b6r2_08 (a snapshot was written) |
| R06 | input validation after the V2 proof | ks02 D1b |
| R07 | `/me` flag restored | b6r2_11, pre safe_01 / me_01 |
| R08 | the setting restored | b6r2_01, h1 cut_01 |
| R09 | readiness `cutover_enabled` restored | h3-sheets s02 |
| R10 | `AssignmentCutover.enabled` restored | h1 cut_01, b6r2_01 |
| F01 | `serverSignalsFrom` requires the old flag | `technicianV2.test.ts` |
| F02 / F03 / F04 | Repair create / PM start / conversion gated on the old flag again | 14 / 9 / 6 failing tests, including `TechnicianV2Cutover.test.tsx` page tests |
| F05 | the V2-OFF state shown again | `TechnicianV2Cutover.test.tsx` |

B6 mutations (unchanged set, re-run on this tree):
- B01–B03: D1.
- B04–B06: stale, no current set, AMBIGUOUS.
- B07–B10: withdrawal integrity.
- B11: Sheets readers skip V2 rows.
- B12: per-kind capability.
- B13: replay before CLOSED.
- B14–B16: legacy retirement.
- B17: append-only.
- F01–F16: the withdrawal UI.

New tests:
- backend `test_v2_only_creation_batch_r2f_h4_b6r2.py` (b6r2_01–11, Rev2);
- backend `test_v2_policy_batch_r2f_h4_b6.py` (D1 01–06, D2 01–15, D3 01–06);
- backend `test_v2_policy_sheets_batch_r2f_h4_b6.py` (s01–s04, fake Sheets transport);
- frontend `TechnicianAssignmentV2Panel.withdrawal.test.tsx` and the B6 blocks of `technicianV2.test.ts`;
- E2E `technician-v2-withdrawal.spec.ts` and `technician-v2-only.spec.ts`, on every main viewport project.
