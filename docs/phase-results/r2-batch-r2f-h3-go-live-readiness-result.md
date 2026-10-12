# R2 Batch R2f-h3 — Pre-Go-live Verification Report — Result

Status: IMPLEMENTED / UNCOMMITTED / AWAITING INDEPENDENT RE-REVIEW (after finding H3-01). This is not
self-certified.
R2f-h is NOT complete: R2f-h4 (frontend, required) remains.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `b056bdc2699b0f9bea8a4c1b39ed3485bcd7ffe4`
  (tree `931c5cb7c5103c5c19df6a806993f2c3e1ac8484`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only and STRICTLY READ ONLY: no live Google Sheet was read or written; no schema, master, relationship,
configuration or audit row was created; no role or capability changed; the V2 cutover setting stays OFF and is only
reported.

## 1. Route and authorization (owner decision D1)

`POST /api/v1/technician-assignment/go-live-readiness` — read only (POST carries the owner lists; no
`X-Request-Id`, nothing written).

- Requires BOTH existing capabilities `can_link_personnel_technician` AND `can_link_personnel_account` (no role
  name, no new capability or grant; today ADMIN and MAINTENANCE_MANAGER hold both).
- The gate is a route dependency that runs before the body is parsed and before any repository read: a caller
  missing either capability gets 403 with zero reads and zero writes (even a malformed body is 403, not 422).
- Authorized callers see linked `user_id` values in the informational population (D1).
- REAL context only: a TEST context is 409 `GO_LIVE_READINESS_REQUIRES_REAL_CONTEXT`, an unconfigured context 503,
  both before any read. Mock mode is always TEST, so report content is tested at service level and over the fake
  Sheets transport.

## 2. Owner input (D2)

Body: `intended_recipient_personnel_ids`, `intended_my_work_personnel_ids` — exact `personnel_id` strings, never
inferred, never stored.

- Omitted, `null` and `[]` are distinguished (`OMITTED` / `NULL` / `EMPTY`) and each makes the dependent checks
  BLOCKED (`INPUT_<state>`), never PASS.
- Every supplied id is echoed exactly (`inputs`). Duplicates (`INPUT_DUPLICATE`), blank ids, unknown
  (`PERSONNEL_NOT_FOUND`, including case / whitespace variants), ambiguous (`PERSONNEL_AMBIGUOUS`), out-of-scope
  (`PERSONNEL_SCOPE_MISMATCH`) and invalid-flag (`PERSONNEL_SCOPE_INVALID`) ids are reported as FAIL issues — never
  dropped.

## 3. The six C1 §26 checks

| Check | Source(s) | PASS only when |
|---|---|---|
| C1-26-1 Personnel ↔ Technician | `personnel_master` (R2f-a bounded read), `technician_master` | every listed recipient is exactly one REAL Personnel and its `technician_id` link is RESOLVED (R2f-a `resolve_link`, holders counted among REAL Personnel) |
| C1-26-2 Personnel ↔ Account | `personnel_master`, `user_account` | the same for every listed My Work user, `user_id` link |
| C1-26-3 ACTIVE (D4) | the same | for every unique person in EITHER list: exactly one REAL Personnel with `active_status` exactly `ACTIVE`, Technician RESOLVED and exactly `ACTIVE`; an unresolved Technician is UNDETERMINED; a person in both lists is evaluated once (`groups` shows both) |
| C1-26-4 TEST segregation (D3) | every tagged R2f source (section 4) | every tagged source is present and validated; every flag exact; every TEST row has a batch; every populated TEST reference is PROVEN to resolve to exactly one TEST record of the row's own batch in a validated target master (C1 §15; section 4a) |
| C1-26-5 REAL integrity (D3) | the same, plus R2f-h1 V2 sets | every populated REAL reference resolves exactly once in REAL (UNSET is not a reference); no shared REAL links / duplicate personnel ids; every REAL V2 set passes the R2f-h1 validator unchanged (H1-01 completeness, digest, scope, ambiguity, job existence and model) |
| C1-26-6 schema (D3) | validated reads | the extended headers of `repair_order`, `pm_work_order`, `repair_assignment`, `pm_work_assignment`, and the bounded-read headers of `personnel_master`, `technician_master`, `user_account`, `driver_master` are all present |

Overall: READY only when all six PASS; NOT_READY when any FAILs or one is UNDETERMINED; otherwise BLOCKED. READY is a
finding, not authorization: the setting stays OFF.

## 4. Coverage (D3)

Every source is listed in `coverage` with `EXAMINED` / `ABSENT` / `NOT_ASSESSABLE` / `EXCLUDED_BY_CONTRACT` /
`UNTAGGED`, computed row counts and the reference types verified.

| Source | References verified |
|---|---|
| `personnel_master` | technician_id→technician, user_id→account, driver_id→driver |
| `department_master` | flags only |
| `personnel_technician_link_history` / `_account_` / `_driver_` | personnel_id→personnel, previous/new id→master |
| `personnel_lifecycle_history`, `department_lifecycle_history` | personnel_id / department_id |
| `equipment_caretaker_history` | equipment_id, technician_id, recorded_from_technician_id |
| `crane_driver_responsibility_history` | vehicle_id, driver_id, recorded_from_driver_id |
| `personnel_department_history` | personnel_id, department_id, recorded_from_department_id |
| `repair_assignment`, `pm_work_assignment` (V2 rows) | job id→job, assignee_id→technician |
| `repair_order`, `pm_work_order` (V2 / flagged rows) | asset_id→vehicle / equipment by asset_type |

- Scope comes only from each row's own flags, or for untagged live masters from the repository's proven scope; never
  from an id or text. Matching is exact.
- `TAB_MISSING` = `ABSENT`; any other structural problem = `NOT_ASSESSABLE`. Both are listed in `coverage` and `gaps`.
  Neither ever proves anything (H3-01): an absent or unassessable tagged source keeps C1-26-4 BLOCKED, and a required
  one also keeps C1-26-5 BLOCKED.
- Untagged legacy rows (legacy jobs and assignment rows, `vehicle_driver`) carry no TEST metadata and are operational
  by contract (C1 §14 / §15): listed as `UNTAGGED`, never counted as TEST.
- `asset_branch_history` and `vehicle_registration_history` are listed `EXCLUDED_BY_CONTRACT` (C1 CC-5: the accepted
  R1 precedent, whose TEST rows target real vehicles, is not reopened and is not an R2f relationship). This is an
  explicit, reviewable boundary — see section 7.

### 4a. Reference outcomes (after H3-01)

Only a successfully validated target master proves anything.

| Situation | TEST row (C1-26-4) | REAL row (C1-26-5) |
|---|---|---|
| exactly one TEST target of the row's own batch | clean | `REFERENCE_SCOPE_UNPROVEN` (FAIL) |
| a REAL (or untagged legacy) target | `TEST_REFERENCES_REAL` (FAIL) | exactly one: clean; more: `REFERENCE_AMBIGUOUS` (FAIL) |
| a target of invalid / unknown scope | `TEST_REFERENCE_SCOPE_UNPROVEN` (FAIL) | `REFERENCE_SCOPE_UNPROVEN` (FAIL) |
| a TEST target of another batch | `TEST_REFERENCE_BATCH_MISMATCH` (FAIL) | — |
| two or more TEST targets | `TEST_REFERENCE_AMBIGUOUS` (FAIL) | — |
| id not in a validated master | `TEST_REFERENCE_MISSING` (FAIL) | `REFERENCE_MISSING` (FAIL) |
| target master tab ABSENT | BLOCKED, gap `<tab>.<column>: target <master> ABSENT (TAB_MISSING)` | BLOCKED, same gap |
| target master schema invalid | BLOCKED, gap `... NOT_ASSESSABLE (<problem>)` | BLOCKED, same gap |
| TEST row without `test_batch_id` | `TEST_BATCH_MISSING` (FAIL) | — |
| tagged source tab ABSENT | BLOCKED, gap `<tab>: tab absent (TAB_MISSING)` | BLOCKED when required for C1-26-5 |

Blank reference cells are UNSET, not references. Nothing is created, mapped or repaired.

## 5. Read and error semantics

- Each source is read once (19 bounded / validated reads; no per-job reads). One new read-only repository method,
  `read_work_order_v2_rows(kind)`, gives the job rows in one validated extended-header read.
- A transport failure of any source is 503 `GO_LIVE_READINESS_READ_FAILED {source, tab}` — no partial report and
  never an empty result. Missing headers are a failed schema requirement (C1-26-6) and block the dependent checks.

## 6. Deliberate test amendment

`test_relationship_read_batch_r2f_a.py::test_r2fa_09_reference_surface_is_read_only_and_routes_are_get_only` gains
exactly `("POST", "/api/v1/technician-assignment/go-live-readiness")` (the owner-approved path contains
"technician"), marked "R2 Batch R2f-h3 (deliberate evolution)". No other existing test changed.

## 6a. Finding H3-01 (independent review) — correction

Defect, confirmed by reproduction against the unchanged candidate (tree `70e52d6c…`):
- `_judge()` treated an ABSENT target master as an empty match set: a TEST row naming any id was "clean"
  (C1-26-4 PASS, no gap);
- related gaps were also confirmed: a TEST reference to a TEST record of another batch, a TEST reference to an id
  absent from a validated master, and an ABSENT tagged source all reached PASS.

Correction (in `go_live_readiness.py` only):
- any target that is not a successfully validated master (ABSENT or NOT_ASSESSABLE) is unprovable and blocks the
  checking row's check, with a gap naming the target and its problem;
- a TEST reference is clean only on exactly one TEST-scoped match of the row's own batch (C1 §15 "a tagged master with
  a `TRUE` row of the same batch" / fake records with an explicit TEST scope and batch);
- an ABSENT tagged source now blocks C1-26-4 (it was listed but treated as proven empty).

Contract classification of ABSENT tagged sources. C1 §27 lists every R2f history tab and `department_master` as a
live schema blocker that "needs its own later authorization", and no clause states that an absent tab is
optional or that its absence proves the absence of TEST rows. (Code evidence: no application path creates a
worksheet.) So, failing closed, absence is not treated as proof, and the decision is submitted as **D5 (PENDING)** —
see section 7. Consequence: until every tagged tab exists (or D5 decides otherwise), C1-26-4 is BLOCKED and the report
cannot be READY.

CC-5 evidence (unchanged boundary, not broadened): C1 §2 "R1 branch-history TEST rows target real vehicles. That
accepted R1 behaviour is not changed by R2f, but it is **not** a precedent for R2f"; C1 §32 CC-5 "Smallest migration:
none to R1. It is an accepted earlier contract and is not reopened." Only the two R1 tabs, `asset_branch_history` and
`vehicle_registration_history`, are excluded.

Tests amended for H3-01 (this batch's own, not yet approved, tests): `test_r2fh3_test_04` (an absent history tab is now
BLOCKED, not PASS) and `test_r2fh3_s02` (READY now requires every tagged tab to be present).

## 7. Known limitations and remaining blockers

1. Live: the V2 columns and the R2f history tabs do not exist, so the live report today is NOT_READY (C1-26-6 FAIL,
   C1-26-4 / -5 BLOCKED);
   account links are unpopulated per C1; production authentication (R11) does not exist. The report states these;
   none is presented as PASS.
2. R1 exclusion (CC-5) and the untagged legacy sources are explicit boundaries; if governance wants R1 TEST rows to
   block readiness, C1-26-4 could never PASS without reopening R1 — a governance decision, not made here.
3. The mock still lets a TEST V2 job be opened on a REAL-scoped asset (R2f-h1 does not check asset scope; live TEST V2
   is refused). The report detects it as `TEST_REFERENCES_REAL`; R2f-h1 is unchanged.
4. **D5 (PENDING, new — H3-01):** may an ABSENT tagged R2f tab that is not yet authorized live (C1 §27) count as
   proven to hold no TEST rows for C1-26-4, given that no application path creates worksheets? Today: no (fail closed).
   If the owner says yes, only that one rule changes; the target-master rules in section 4a stay fail-closed.
5. Owner decisions outside D1-D5 remain PENDING (recording / My Work after inactivation, V2 empty-set unassignment,
   "new assignee" reading, V2 on CLOSED jobs, the R2f-h1 V2 GET routes, My Work with no capability, the H1-01
   residual-forgery limitation); a report UI is not in scope (R2f-h4 decides).
