# R2 Batch R2f-h4 B3 — U1 V2 Waiting Assignment Read-only APIs — Result

Status: INTEGRITY FIX IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.

**Integrity fix (owner-approved, after the targeted reconciliation audit):**
- **I1:** an invalid in-scope job status is no longer returned verbatim.
- **I1b:** an invalid `opened_at` is no longer returned as null.
- **I2:** a V2 job with unprovable scope is no longer listed in every context.

All three now fail the whole queue closed with counts only. A1-§24 is clarified accordingly (an O2 clarification;
no new owner decision).

Contract: C1 Amendment A1 (`docs/project-governance/c1-amendment-a1-v2-only.md`) §24 / §25, owner decision O2 and the
owner-confirmed U1 queue behaviour.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `1e234eb7a8e68345e7fb5b4a8120707e4ac8322b`
  (tree `65da216fce1c23876abd9a427934ae31d4985da8`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Local branch: `review/r2-batch-r2f-h4-b3-v2-waiting-assignment` (no remote).

Mock / fake only:
- no live Google Sheet was read or written;
- no schema, role, capability or production setting changed;
- the V2 cutover stays OFF by default.

**No frontend change. B4 is not implemented, and no frontend V2 E2E exists.**

## 1. Routes

| Route | Capability |
|---|---|
| `GET /api/v1/repairs/v2-waiting-assignment?page&page_size` | `can_manage_repair` |
| `GET /api/v1/pm/work-orders/v2-waiting-assignment?page&page_size` | `can_manage_pm` |

- **Read only.** Zero writes.
- **Paging:** `page >= 1` (default 1); `page_size` 1–200 (default 50).
- **Routing:** the router is included BEFORE the pm and repairs routers, so these static paths match before the dynamic
  `/{id}` routes (tested: the detail routes still work).
- **Order of checks:**
  1. capability (403, zero repository reads, also when the context is unconfigured);
  2. context (503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`, zero reads; also TEST without a batch);
  3. exactly three reads.
- **Response:** `{data_context, items[], page, page_size, total_items}`. Each item is
  `{work_type, job_id, asset_type, asset_id, status, opened_at, assignment_status, issues}`:
  - `assignment_status` ∈ NONE / AMBIGUOUS / DATA_INVALID;
  - `issues` is a code→count map, empty unless DATA_INVALID;
  - `status` is always exactly `"OPEN"` (response model `Literal["OPEN"]`);
  - `opened_at` is always a valid, timezone-aware timestamp (required in the response model; never null).
- **Ordering:** newest `opened_at` first, ties broken by `job_id` (same direction). Paging applies after the whole
  eligible scope is classified.

## 2. Scope and authorization matrix

| Caller / context | Result |
|---|---|
| lacks the route's capability (TECHNICIAN, DRIVER, DRIVER_DEPARTMENT_MANAGER, MAINTENANCE_MANAGER; or only the other kind's capability) | 403, zero reads |
| holds it (ADMIN, MAINTENANCE, SUPERVISOR — unchanged holders) | proceeds |
| context unconfigured / TEST without batch | 503, zero reads |
| REAL | jobs with `is_test_data` exactly FALSE (and no batch) only |
| TEST | jobs with `is_test_data` exactly TRUE and exactly the server batch only |

- No query parameter selects a scope.
- Other-scope jobs (including another TEST batch) are neither listed nor validated: a defect in another batch's set
  does not affect this scope.

## 3. Classification and integrity

**Population:** jobs whose persisted `assignment_model` is exactly `TECHNICIAN_V2`, in the server scope, with stored
status exactly `OPEN`. CLOSED jobs and legacy jobs are not listed; the legacy queue is unchanged.

**Per-job classification**, using the R2f-h1 validators unchanged:

| Status | Condition |
|---|---|
| `NONE` | no current set |
| `AMBIGUOUS` | `derive_assignment_state` returns AMBIGUOUS (the R2f-h1 same-instant tie rule) |
| `DATA_INVALID` | a job-attributable defect (codes below) |
| VALID | **excluded**. After a successful assignment the job leaves on the next read. It remains in the normal Repair / PM lists, on its detail page, and in the assignees' V2 My Work (tested). |

Job-attributable `DATA_INVALID` codes:
- that job's set integrity from `derive_assignment_state` (with the job's own scope): `SET_INCOMPLETE`,
  `SET_DIGEST_MISMATCH`, `ROW_SCOPE_MISMATCH`, and the other R2f-h1 per-set codes;
- the persisted technician reference proof for that job's stored ids (`TECHNICIAN_REFERENCE_*`).

Job-level cells are NOT job-attributable (integrity fix I1 / I1b / I2). They fail the whole queue (next table).

**Whole-queue fail closed** (never a partial queue):

| Defect | Response |
|---|---|
| R2f-h1 `tab_issues` (any job, any scope), e.g. `RECORD_ID_INVALID`, `DUPLICATE_RECORD_ID` | 500 `TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues}` |
| an in-scope V2 row with no job (`V2_ROW_JOB_MISSING`) | same |
| an in-scope V2 row on a legacy job (`V2_ROW_ON_LEGACY_JOB`) | same |
| a duplicated job id (`JOB_ID_DUPLICATE`), or a V2 job with a blank id (`JOB_ID_BLANK`) | same |
| any job with an unknown `assignment_model` | 500 `ASSIGNMENT_MODEL_DATA_INVALID` (never silently dropped) |
| **I2:** a `TECHNICIAN_V2` job whose scope flags cannot prove its scope (not exactly TRUE / FALSE, or FALSE with a batch), in every context | 500 `TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID {issues: {JOB_SCOPE_FLAG_INVALID: n}}` |
| **I1:** an in-scope `TECHNICIAN_V2` job whose status is neither exactly OPEN nor exactly CLOSED (e.g. `WAITING`, blank, `open`, ` OPEN`) | 500 `TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID {JOB_STATUS_INVALID}` |
| **I1b:** an in-scope OPEN `TECHNICIAN_V2` job without a valid timezone-aware `opened_at` (invalid, blank or naive) | 500 `TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID {JOB_OPENED_AT_INVALID}` |

These errors carry counts only, never a job id, asset id or row detail. A CLOSED job is never failed for its
`opened_at`. A job of a provably different scope or batch is skipped without validating its job-level cells. A naive
timestamp is invalid because it cannot be ordered against the timezone-aware ones that every V2 create writes; this
also removes a sort-time crash path.
| schema problems | 500 `TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID` / `TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID` / `TECHNICIAN_MASTER_SCHEMA_INVALID` |
| read failures | 503 `*_READ_FAILED` |

**Note on duplicate rows:** under the unchanged R2f-h1 validator, assignment record ids are checked tab-wide, so a
duplicated or malformed assignment row fails the whole queue. It is not listed as one job's DATA_INVALID. This follows
the integrated semantics exactly.

**Bounded reads:** exactly three repository reads per request, whatever the number of jobs (tested at 0, 1 and 6+6
jobs):
1. `read_work_order_v2_rows(kind)`;
2. `read_work_assignment_v2_rows(kind)`;
3. `read_technician_master_reference()`.

There are no per-job reads and no writes.

## 4. Changes

| Path | Change |
|---|---|
| `backend/app/domain/v2_waiting_assignment.py` (new) | `V2WaitingAssignmentService` (pure classification over the three reads) |
| `backend/app/api/v1/v2_waiting_assignment_routes.py` (new) | the two routes and response models |
| `backend/app/api/v1/router.py` | includes the new router before pm / repairs |
| `backend/app/repositories/mock/repository.py` | the mock `read_work_order_v2_rows` (R2f-h3) also returns `opened_at` (exact ISO text), which the Sheets implementation already returns as part of the full extended job header. The interface, signature, Sheets code and storage are unchanged. |
| `backend/tests/test_v2_waiting_assignment_batch_r2f_h4_b3.py` (new) | 76 mock tests |
| `backend/tests/test_v2_waiting_assignment_sheets_batch_r2f_h4_b3.py` (new) | 20 fake-Sheets tests |
| `docs/project-governance/c1-amendment-a1-v2-only.md` | A1-§24 clarification (integrity fix) |

**Unchanged:**
- the legacy `/repairs/waiting-assignment`;
- the 7C2 Open Repair Queue;
- R2f-h1 assignment;
- R2f-h2 My Work;
- R2f-h3 readiness;
- the B2 picker;
- roles and capabilities;
- the Repair / PM write routes;
- the shared assignment tab structures.

## 5. Tests

**Mock:**
- Repair / PM NONE and the response shape;
- VALID excluded, leaving after assignment while staying in lists, detail and My Work;
- legacy and CLOSED excluded, with the legacy queue unchanged;
- AMBIGUOUS;
- the job-attributable DATA_INVALID codes (incomplete, digest, row scope, missing technician);
- **integrity fix**, each for Repair and PM:
  - invalid statuses (`WAITING`, blank, `open`, ` OPEN`, `OPEN `, `Closed`) fail the whole queue;
  - an invalid / blank / naive / out-of-range `opened_at` on an OPEN job fails it;
  - a bad `opened_at` on a CLOSED job does not;
  - unprovable scope (`maybe`, blank, `true`, FALSE+batch) fails it in both the TEST and REAL contexts;
  - provably other-scope / other-batch / blank-batch jobs are skipped unvalidated;
  - counts aggregate;
  - no job or asset id appears in any fail-closed body;
  - every success item is OPEN with an aware `opened_at`;
  - the response model rejects a non-OPEN status or a null `opened_at`;
- the whole-queue fail-closed cases (unknown model, orphan row, row on a legacy job, tab-wide record id, duplicated
  row, duplicated job id);
- schema and read failures for each of the three reads;
- the capability matrix derived from `ROLE_CAPABILITIES`, plus per-kind single-capability contexts (403 with zero
  reads);
- 503 with zero reads;
- REAL / TEST / other-batch isolation and the ignored scope-like query parameters;
- ordering, ties and paging after classification, plus the 422 bounds;
- exactly three reads;
- zero writes;
- static paths before `/{id}`, and no new capability.

**Fake Sheets:**
- the current live state (legacy headers) → 500 schema, never empty, zero writes;
- NONE → VALID leaves;
- a damaged set → DATA_INVALID;
- integrity fix over the transport: invalid status (×2), invalid `opened_at`, scope flag `maybe`, FALSE+batch → 500
  with counts only, no ids and zero writes; a CLOSED job with a bad `opened_at` does not block;
- the TEST context never lists REAL jobs;
- 403 with zero requests;
- 503 unconfigured with zero requests;
- a transport failure → 503.

**Fix-removal mutations:** 25 of 26 caught.
- **Caught:** W01–W15 (original behaviour) and I1a–c, I1b-1..3, I2a–d (integrity-fix removals).
- **Survivor I1d** (item status taken from the stored text instead of the constant) is an equivalent mutant. Only jobs
  whose stored status is exactly `OPEN` can reach an item, so the value is identical. The response-model literal (I1c)
  independently enforces `OPEN`.

## 6. Remaining dependencies

- **B4:** the V2 frontend, including the manager waiting page on these routes, and the dedicated mock test process with
  `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` for the real mock E2E.
- **B5:** legacy UI removal.
- **B6:** legacy backend cleanup, separately authorized.
- **Live:** the live V2 columns (live today: 500 schema), R11, links and Go-live each need their own approval.
- **Unchanged:** D5 PENDING; H3-01 fail-closed.
