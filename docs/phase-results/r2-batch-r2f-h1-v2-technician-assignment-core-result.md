# R2 Batch R2f-h1 — V2 Technician Assignment Core — Result

Status: IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.
R2f-h is NOT complete: R2f-h2 (V2 My Work), R2f-h3 (pre-Go-live report) and R2f-h4 (frontend, required) remain.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `f32f76beef69edcbef7a9423ddef8d1d2d6fd891`
  (tree `f2265f2384b245efcee51dba47ce23c9fb93fdee`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only:
- no live Google Sheet was read or written;
- no live column was added to `repair_order`, `pm_work_order`, `repair_assignment` or `pm_work_assignment`;
- no real Personnel / Technician / account link was created; no role or capability grant changed;
- the cutover setting is OFF by default and was not enabled anywhere.

## 1. Storage — Option A (governance-approved)

The EXISTING tabs carry the additive columns; no separate V2 tab exists.

| Tab | Additive columns |
|---|---|
| `repair_order`, `pm_work_order` | `assignment_model`, `is_test_data`, `test_batch_id` |
| `repair_assignment`, `pm_work_assignment` | `assignee_type`, `assignee_id`, `request_id`, `request_fingerprint`, `reason_th`, `is_test_data`, `test_batch_id` |

- The legacy schema declarations (`REPAIR_SHEET`, `PM_WORK_ORDER_SHEET`, `REPAIR_ASSIGNMENT_SHEET`,
  `PM_WORK_ASSIGNMENT_SHEET`) are byte-unchanged. The extended headers are separate declarations
  (`*_V2_SHEET`) used only by V2 paths, so every legacy read, write and readiness check is unchanged whether or not
  the live columns exist.
- Every V2 write first makes ONE validated read of the extended header. A missing column fails closed with zero
  writes (`TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID`, `TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID`). The append follows the
  header of that same read, never the header cache, so a V2 cell can never be silently dropped.

## 2. V2 rows and sets

- `assignee_type=TECHNICIAN`, `assignee_id=technician_id` (forced text), `user_id` BLANK, `assignment_role`
  PRIMARY / COLLABORATOR, legacy `ended_at` / `active_status` / `note_th` BLANK. Record ids
  `RTA-<digest>-<i>-<n>` / `PTA-<digest>-<i>-<n>` (never the legacy `RASG-` / `PASG-` sequences; see section 2a).
- One V2 write appends ONE set — exactly one PRIMARY plus zero or more COLLABORATORs, no duplicate assignee — in ONE
  append request. Every row of a set shares the client request id, recorded time, actor, fingerprint, reason and
  scope.
- No V2 row is ever updated. The current set is the set with the latest recorded time; a same-instant tie of the
  latest sets is AMBIGUOUS and never guessed.
- Integrity is validated before any decision (500 `TECHNICIAN_ASSIGNMENT_DATA_INVALID` with issue counts):
  - tab-wide: record ids present / in the V2 id format / unique; a request id present and naming ONE job and ONE
    scope;
    exact scope flags;
  - per job: no legacy row on a V2 job; `assignee_type` exactly TECHNICIAN; blank `user_id` and legacy status
    cells; valid role and time; audit fields present; row scope = job scope; per set uniform fields, exactly one
    PRIMARY, no duplicates, and the set COMPLETE (section 2a);
  - persisted reference proof: every stored `assignee_id` resolves exactly once in scope (`TECHNICIAN_REFERENCE_*`).
- Empty-set (unassignment) is not offered.

## 2a. Set completeness (independent-review finding H1-01)

Finding: a set written as PRIMARY A + COLLABORATOR B whose stored rows later held only PRIMARY A was accepted as a
VALID set of A alone (reproduced against the first candidate). Nothing in the stored rows recorded how many rows the
set had.

Correction (no new column, table, transaction, lock or compensation): the record id VALUE carries the evidence. Each
row of a set of n rows is `<prefix>-<digest>-<i>-<n>`, where `digest` is the first 32 hex characters of SHA-256 over
the job id, the request id and the ordered (role, technician_id) members (index 1 = the PRIMARY). For every set the
validator requires one digest and one n on all rows, indices exactly 1..n, and the digest recomputed from the rows
present. A lost row (`SET_INCOMPLETE`), an id that is not in this format (`SET_COMPLETENESS_UNPROVEN`,
`RECORD_ID_INVALID`), an altered assignee or role, a consistently shrunk size (`SET_DIGEST_MISMATCH`), a row moved in
from another set and a duplicated row all fail closed (500 `TECHNICIAN_ASSIGNMENT_DATA_INVALID`) for reads, writes
and recording. The record id format is an engineering choice (C1 §33, ID prefixes).

Write path: `append_rows_with_header` sends the whole set as ONE `values.append` request. That is one request, not
a documented atomicity guarantee: an unknown outcome (timeout or 5xx after the request was applied) is reported and
never retried, and replay of the same `X-Request-Id` recovers it; a partially persisted or externally damaged set is
now detected by the stored rows themselves.

Residual limitation (inherent to the Google Sheets prototype): the digest is not secret. A deliberate, consistent
rewrite of every remaining row (new digest and n computed from the altered membership) cannot be told apart from a
genuine set. Detecting that would need signatures or a database constraint, which the frozen contract does not
include; it is listed for the PostgreSQL phase.

## 3. Job model separation and the cutover setting

- `TECHNICIAN_ASSIGNMENT_V2_ENABLED` (`Settings.technician_assignment_v2_enabled`), default OFF.
- OFF: every create path is exactly the legacy create.
- ON: `POST /repairs`, repair-request convert and `POST /pm/work-orders` create the job with
  `assignment_model=TECHNICIAN_V2` and the job's own scope flags. Before ANY write (asset check, snapshot, append):
  the write context (503), live TEST refusal (409 `TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED`) and the
  extended-header proof. An inline legacy assignee on such a create is refused (422 `ASSIGNMENT_MODEL_MISMATCH`).
- An existing job never changes model when the setting changes; a blank marker is legacy, an unknown marker fails
  closed (500 `ASSIGNMENT_MODEL_DATA_INVALID`).
- Legacy `/assign` and `/assignment-history` (Repair and PM) refuse V2 jobs; the V2 routes refuse legacy jobs —
  409 `ASSIGNMENT_MODEL_MISMATCH`, before any assignment read or write.

## 4. API

| Route | Capability |
|---|---|
| `POST /api/v1/repairs/{repair_id}/technician-assignments` | `can_manage_repair` (unchanged holders) |
| `POST /api/v1/pm/work-orders/{pm_work_order_id}/technician-assignments` | `can_manage_pm` (unchanged holders) |
| `GET` on the same two paths (current set + set history) | `can_view` |

- Body (strict): `primary_technician_id`, `collaborator_technician_ids`, `expected_current` (REQUIRED; null = expect
  no current set), optional `reason_th`.
- Order: capability (403) -> `X-Request-Id` (422) -> body (422) -> context -> job -> model -> job scope -> validated
  read -> integrity -> persisted reference proof -> replay (`REQUEST_ID_REUSED`) -> ambiguity -> stale -> no-op ->
  gate per NEW assignee -> W1. Stale is checked before no-op. No retry after an unknown outcome.
- The GET routes are an addition for review: the legacy history view refuses V2 jobs, so a V2 read is needed.

## 5. Gate and authorization

- Gate (C1 §7): every NEW assignee (not already in the current set) passes the existing R2f-d BOTH-ACTIVE rule with
  the same codes (`TECHNICIAN_NOT_FOUND`, `TECHNICIAN_SCOPE_UNPROVEN`, `TECHNICIAN_ID_AMBIGUOUS`,
  `TECHNICIAN_NOT_ACTIVE`, `TECHNICIAN_PERSONNEL_UNRESOLVED`, `TECHNICIAN_PERSONNEL_AMBIGUOUS`,
  `PERSONNEL_NOT_ACTIVE`); a parity test pins it to the R2f-d gate. R2f-d itself is unchanged.
- Recording (Repair actions / parts, PM results, Repair and PM attachments):
  - legacy job: the unchanged REV06.1 / F1 path (legacy history, opaque `user_id` compare, or the capability);
  - V2 job: the capability (no V2 read), or the actor resolves in scope User Account -> Personnel -> Technician to a
    member of the CURRENT set. No lifecycle gate applies to recording.
- No role, capability or grant was added or changed.

## 6. TEST / REAL

- Mock is TEST: synthetic TEST-scoped personnel / technicians / accounts only.
- A request of one scope never touches a job of the other (409 `TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH`); REAL never
  resolves TEST fixtures; TEST never resolves REAL or other-batch references.
- Live (non-mock) TEST V2 fails closed (create and assign).

## 7. Legacy consumers

| Consumer | Behaviour |
|---|---|
| Repair / PM `/assign` | legacy jobs unchanged; V2 jobs 409 |
| Repair / PM `/assignment-history` | legacy jobs unchanged; V2 jobs 409 |
| Repair actions / parts, PM results | per job model (section 5); legacy path's repository calls identical |
| Repair / PM attachment source authorization | per job model |
| `GET /repairs/waiting-assignment` | legacy jobs only (V2 jobs excluded; C1 §24 Q4) |
| `GET /repairs/my-work`, `GET /pm/work-orders/my-work`, `assigned_to` filters | unchanged; a blank V2 `user_id` never matches |
| `GET /repairs`, Open Repair Queue report | unchanged; V2 jobs listed like any job |
| Sheets PM detail loader | unchanged; V2 rows read as inactive (blank `user_id` / status) |

## 8. Deliberate test amendment

- `test_relationship_read_batch_r2f_a.py::test_r2fa_09_reference_surface_is_read_only_and_routes_are_get_only`:
  marked "R2 Batch R2f-h1 (deliberate evolution)" — the route set whose path contains "technician" gains exactly the
  four C1 §24 `technician-assignments` routes.
- The two legacy identity guards (`test_core_demo_fixes_delta.py` and `test_personnel_read_batch_r2c1.py`) and the
  shared read-only surface guard are NOT amended: the new repository methods are named
  `read_work_assignment_v2_rows`, `append_work_assignment_v2_rows`, `verify_work_order_v2_schema`.

## 9. PENDING governance (not decided here)

1. Recording by a member whose Personnel / Technician became inactive after assignment: allowed (literal reading;
   owner decision PENDING, narrowing would be additive).
2. V2 unassignment (empty set): not offered (owner decision PENDING).
3. "New assignee" read as a technician not in the current set (a retained member is not re-gated; re-adding a
   removed technician is gated).
4. A V2 assignment on a CLOSED job is not refused, mirroring legacy `/assign` (no status gate was invented).
5. The two V2 GET routes (section 4) are an addition for review.
6. V2 waiting-assignment queue (R2f-h2, contract amendment), V2 My Work (R2f-h2), pre-Go-live report (R2f-h3),
   frontend (R2f-h4, required), Go-live date / enablement / rollback, production authentication (R11), live
   schema step for the additive columns, account-link population: all outside h1.
