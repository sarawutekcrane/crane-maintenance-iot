# R2 Batch R2f-g — Personnel Department Movement History — Result

Status: IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `6f311e8e234a8d246d872e4adc5c9df7075de0a9`
  (tree `3d7056b79602388d290a2c4012b7f16863fefa74`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only:
- no live Google Sheet was read or written;
- `personnel_department_history` and `department_master` were not created;
- no real Personnel was moved;
- no department master data was created. All department rows are synthetic, inside test fixtures only.

## 1. Authority

- `personnel_department_history` is the ONLY authority for department movement. It is append-only, with immutable
  revisions, and the current department is DERIVED from it.
- There is no projection column, no W2 and no reconciliation.
- The legacy `personnel_master.department` text is never read, written, used as a baseline or projected.
- A personnel with no history has a derived department of NONE.

## 2. History schema

`personnel_department_history` has 21 columns, the R2f-d / R2f-f analogue:

| Group | Columns |
|---|---|
| Identity | `record_id`, `personnel_id`, `department_id` |
| Event | `record_kind`, `entry_operation` |
| Revision chain | `event_id`, `revision_no`, `supersedes_record_id` |
| Effective time | `effective_at`, `effective_precision`, `effective_source` |
| Source | `recorded_from_department_id`, `recorded_from_source` |
| Audit | `recorded_at`, `recorded_by` |
| Request | `request_id`, `request_fingerprint`, `reason_th`, `related_request_id` (reserved, blank) |
| Scope | `is_test_data`, `test_batch_id` |

The tab is not live, never auto-created, and not in `_CORE_SCHEMAS`. A missing tab fails closed with
`PERSONNEL_DEPARTMENT_HISTORY_SCHEMA_INVALID`.

## 3. Operations and period semantics

**TRANSFER (a movement):**
- the latest event; the first movement is from NONE;
- the previous derived period ENDS at exactly the new effective instant, and the new period OPENS there;
- NOW is allowed; the reason is optional.

**INSERTION (a backdated movement):**
- must fall before a later in-force event; NOW is not allowed; a reason is required;
- the surrounding periods are re-derived: the earlier period now closes at the inserted instant, and the inserted
  period closes at the next event.

**CORRECTION:**
- a new revision of `event_id`, guarded by `expected_revision_no`;
- may change the department and/or the effective time;
- a new department is proven again.

**CANCELLATION:**
- a terminal revision;
- the remaining periods are re-derived (for example, the previous department re-opens).

**Invariants:**
- No overlap is possible: periods are derived from the effective-time order, so each event ends exactly where the
  next begins.
- Original rows are never rewritten. Recorded time is kept separate from effective time, and the actor
  (`recorded_by`) is the authenticated user.

**As-of lookup:** `GET …/department-history?as_of_date=YYYY-MM-DD` (00:00 Asia/Bangkok) or `?as_of_at=<ISO>` returns
the department in force at that instant (an event effective exactly at the instant applies):
- EVENT, NONE, or UNDETERMINED when a same-instant tie decides the answer;
- never a guessed answer;
- future instants are refused (the effective-time rule).

## 4. Department reference proof (same-scope)

**Reader:** `read_department_reference()` reads `department_id`, `is_test_data` and `test_batch_id` only, as a
bounded read.

**Scope comes only from each row's own flags:**

| Flags | Scope |
|---|---|
| Exactly `FALSE`, no batch | REAL |
| Exactly `TRUE` | TEST of its batch |
| Anything else on a content row | Fails closed: `DEPARTMENT_MASTER_DATA_INVALID` |

Scope is never inferred from an id, name, prefix or description.

**A new target department must resolve exactly once in scope:**
- `DEPARTMENT_NOT_FOUND` (422);
- `DEPARTMENT_ID_AMBIGUOUS` (409);
- `DEPARTMENT_SCOPE_UNPROVEN` (422), when it exists only out of scope or in another batch.

**Persisted history:** every stored `department_id` / `recorded_from_department_id` is proven the same way before the
timeline is trusted. A defect is 500 `PERSONNEL_DEPARTMENT_HISTORY_DATA_INVALID` with `DEPARTMENT_REFERENCE_*` issue
counts.

**Personnel:** must be located exactly once in the request's scope (R2f-a bounded relationship read).

## 5. API

| Route | Capability |
|---|---|
| `GET /api/v1/personnel/{personnel_id}/department-history` | `can_view` |
| `POST /api/v1/personnel/{personnel_id}/department-events` | `can_move_personnel_department` (PENDING, held by no role) |

- The POST takes one strict, operation-discriminated body (TRANSFER / INSERTION / CORRECTION / CANCELLATION). Every
  server-set field is a 422.
- There is no END and no DELETE.

## 6. PENDING governance (owner decisions not taken here)

1. **Write authorization.**
   - `can_move_personnel_department` is a ZERO-HOLDER, fail-closed gate.
   - It is NOT in `ALL_CAPABILITIES`, so ADMIN does not inherit it, and it is in no `ROLE_CAPABILITIES` entry. It is
     listed in `authz.PENDING_CAPABILITIES`.
   - Every DEV role is refused with 403 and zero repository calls.
   - Tests exercise the write path by injecting the capability directly into the request context, never through a
     role.
   - PENDING: which roles may move Personnel between departments.
2. **END (leaving every department).** Not in the frozen scope, so not offered. PENDING whether an explicit "no
   department" period is needed.
3. **Lifecycle gates.**
   - No gate on department `is_active` and no gate on personnel `active_status`.
   - PENDING whether moving into an inactive department, or moving an inactive personnel, must be refused.
4. **Legacy text.** PENDING whether `personnel_master.department` is ever reconciled or migrated. It is untouched.
5. **Live schema.** `department_master` and `personnel_department_history` do not exist live; a separate live schema
   step is required.

## 7. Known limitation (unchanged)

Google Sheets has no cross-row compare-and-set or unique constraint. Stale and replay checks run before the single
append, so truly concurrent writers could race. This is accepted for the prototype, with no lock, lease or retry.
