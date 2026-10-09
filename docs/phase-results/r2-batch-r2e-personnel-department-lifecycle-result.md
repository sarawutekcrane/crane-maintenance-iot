# R2 Batch R2e — Personnel / Department Lifecycle + Stale + UI — Result

Status: **candidate, uncommitted** on local branch `review/r2-batch-r2e-personnel-department-lifecycle`, created
from integration HEAD `5cd7cbe0709a63a6ba9261cdf7b1457334d01fc5`.

| Item | Status |
|---|---|
| Personnel lifecycle backend (deactivate / reactivate / reconcile / history) | **DONE (candidate)** — mock + fake Sheets, synthetic data |
| Department lifecycle backend | **DONE (candidate)** — mock + fake Sheets only |
| Separate durable lifecycle histories, stale protection, replay, reconciliation | **DONE (candidate)** |
| Personnel and Department UI (list / detail / lifecycle / stale / unknown outcome) | **DONE (candidate)** |
| Live Personnel lifecycle UAT | **BLOCKED** (history tab, auth cutover, context-safe verification, UAT authorization) |
| Live Department lifecycle UAT | **BLOCKED** (owner department data, department_master + history tab creation, auth cutover) |
| R2f (relationships / assignments) | NOT STARTED |

## 1. Owner approvals implemented

1. **Personnel lifecycle vocabulary `ACTIVE` / `INACTIVE`.** INACTIVE means the record is inactive but preserved — not
   deleted. No row is deleted, no `personnel_id` is reused, reactivation keeps the same id. The vocabulary is used by
   the lifecycle WRITE logic only: the R2c-1 read keeps `active_status` as raw source text (blank still null). A
   lifecycle write on a row whose current value is blank or anything else is refused with
   `422 PERSONNEL_LIFECYCLE_STATE_INVALID` — never normalised, defaulted or repaired.
2. **Separate capabilities `can_manage_personnel` and `can_manage_department`.** Dev holders: ADMIN (through
   `ALL_CAPABILITIES`) and MAINTENANCE_MANAGER (explicit). Not granted to MAINTENANCE, SUPERVISOR, TECHNICIAN or
   DRIVER. `can_manage_user` is not reused (personnel / department management is not login-account management). No
   live `role_permission` edit: a future production-auth cutover must add the approved mapping; today they are
   DEV_AUTH-backed.
3. **A reason (`reason_th`) is mandatory** for personnel and department deactivate, reactivate and reconciliation.
   Blank / whitespace-only is `422 REASON_REQUIRED` (max 500 characters); no default reason exists.

## 2. Scope and boundaries

Implemented: deactivate, reactivate, reconcile and lifecycle-history reads for existing records, plus the UI. Not
implemented: create, rename/edit, hard delete, personnel ↔ department migration, technician / driver / account
linking, responsibility assignment, personnel branch assignment, workshop modelling, user-account management, R2f.

**Domain separation.** A personnel lifecycle write changes ONLY `active_status` of the one located row and appends
ONE `personnel_lifecycle_history` row. It never touches `user_account` (login, role, MFA), `technician_master`,
driver data, `asset_responsibility_history`, PM / repair assignments, branch data, the legacy free-text
`personnel_master.department`, Part or vehicle data. A department lifecycle write changes ONLY `is_active` (never
`department_id`, `department_name_th`, `is_test_data`, `test_batch_id`) and never rewrites any personnel row.
Reactivation restores nothing else (no account, technician, driver or assignment state).

**R2f boundary.** No relationship route or logic was added; personnel ↔ department, technician / driver / account
links and assignments remain R2f. No test forbids future creation, relationship, account-linking or lifecycle
capabilities (only the approved "no hard delete" principle is asserted).

## 3. Durable lifecycle histories (separate, append-only)

Two SEPARATE tabs (no shared table), frozen headers in exact order:

- `personnel_lifecycle_history`: `lifecycle_event_id, personnel_id, event_kind, previous_state, new_state,
  recorded_at, recorded_by, request_id, request_fingerprint, reason_th, is_test_data, test_batch_id,
  related_request_id`
- `department_lifecycle_history`: the same with `department_id`.

`event_kind`: `DEACTIVATE`, `REACTIVATE`, `RECONCILIATION`. Normal events have a blank `related_request_id`; a
reconciliation's `related_request_id` is the `request_id` of the latest event whose desired state it applies
(server-derived). All audit cells are server-set (`recorded_by` = the authenticated `user_id`, `recorded_at` =
server UTC time, `request_id` = `X-Request-Id`, fingerprint, test flags); a body carrying any of them is a 422.
History rows are never edited or deleted; a mistaken deactivate is corrected by a later REACTIVATE (and vice versa),
each with a reason. Personnel states are stored as `ACTIVE` / `INACTIVE`, department states as `TRUE` / `FALSE`.

**The tabs do not exist live and were not created.** A missing tab fails closed with
`<ENTITY>_LIFECYCLE_HISTORY_SCHEMA_INVALID` (tested; never auto-created, no fallback). They are deliberately not in
`_CORE_SCHEMAS`, so readiness of the deployed workbook is unaffected.

**History validation (fail closed).** The entity's in-scope history is validated on every lifecycle read and before
every mutation; any issue is `500 <ENTITY>_LIFECYCLE_HISTORY_DATA_INVALID` with issue counts only (no entity id,
request id, name or row number). Besides the field, state, transition, fingerprint, timestamp and duplicate-request
checks, **reconciliation audit references are verified (independent-review fix R1)**, processing the rows in
physical / history order:

- `related_request_id` must be non-blank (`FIELD_REQUIRED:related_request_id`) and must reference a PRIOR event of
  the SAME entity history and the SAME data-context scope — never itself, a later row, a missing request, another
  entity or another scope: `RELATED_REQUEST_DANGLING`;
- the referenced event's `new_state` must equal the reconciliation's `new_state`: `RELATED_STATE_MISMATCH`;
- a reconciliation must repair a real difference — `previous_state == new_state` is `TRANSITION_INVALID`.

The referenced event need not be the immediately preceding row: Google Sheets appends are not transactional, so a
concurrent append may land between the service's read and its W1; the permanent rule is only "earlier, same scoped
entity history, same new_state". DEACTIVATE / REACTIVATE keep a blank `related_request_id`
(`FIELD_MUST_BE_BLANK:related_request_id`). The generated row is also validated against the scoped prior history
before W1 (a failure is a programming error and nothing is written).

## 4. Write order and failure semantics (history-first)

Order of every mutation, all coded refusals before W1:

1. capability → 2. `X-Request-Id` → 3. body (incl. reason) → 4. server data context → 5. exact locate with
   test/real classification first → 6. lifecycle-history read and validation → 7. replay → 8. current lifecycle
   value valid → 9. consistency gate → 10. **stale** → 11. **no-op** → 12. **W1** history append → 13. **W2**
   lifecycle cell.

- W2 writes one targeted cell (`active_status` or `is_active`) of the located row, never a whole row.
- W1 rejected / unknown → `503 <ENTITY>_LIFECYCLE_HISTORY_WRITE_FAILED {history_write_outcome, request_id}`; no
  master write, no retry.
- W2 failed after W1 → `503 <ENTITY>_LIFECYCLE_STATE_WRITE_FAILED {event_recorded: true, record_id, request_id}`;
  no retry, no compensation; the history stays durable and the record reads `MISMATCH`.

**Consistency** (in the new lifecycle-history endpoints only): `NO_HISTORY` (no lifecycle event — valid for pre-R2e
records), `CONSISTENT` (latest `new_state` == current master state), `MISMATCH`. Normal deactivate / reactivate are
refused while `MISMATCH` (`409 <ENTITY>_LIFECYCLE_MISMATCH`).

**Reconciliation** (`.../lifecycle-reconciliations`, same entity capability, reason mandatory): the body carries
only the expected current state and the reason — the target is the latest history `new_state`, never from the
client. After the stale check, `NO_HISTORY` / `CONSISTENT` → `200 changed:false`; `MISMATCH` → W1 `RECONCILIATION`
(previous = current master state, new = latest desired state, related = that event's request id) then W2, with
the same failure semantics. Nothing reconciles automatically.

## 5. Stale protection and no-op

Expected-current-value guards only (no revision token, no `updated_at`, no schema change): personnel
`expected_active_status` (`ACTIVE` / `INACTIVE`), department `expected_is_active` (strict boolean). Unrelated
display / name changes do not invalidate a lifecycle write. Stale → `409 PERSONNEL_LIFECYCLE_STALE` /
`409 DEPARTMENT_LIFECYCLE_STALE` `{field: active_status | is_active}`. **Stale is checked before no-op**: expected
ACTIVE, current INACTIVE, requested INACTIVE is a 409, never a successful no-op. A correct expectation whose target
already equals the current state returns `200 {request_id, changed: false}` with no write.

## 6. Request id, replay and idempotency

`X-Request-Id` (UUID) is required before any read. The frozen `request_fingerprint` helper is reused with the
entity id in its frozen `vehicle_id` slot and additive operation names `personnel_deactivate`,
`personnel_reactivate`, `personnel_lifecycle_reconcile`, `department_deactivate`, `department_reactivate`,
`department_lifecycle_reconcile` (existing vehicle / equipment op values unchanged).

**Corrected scope:** replay lookup searches the entity's OWN history tab only. Within one tab: same request + same
entity + same operation + same body → REPLAYED (`{request_id, replayed: true, record_ids}`); another entity,
operation or body → `409 REQUEST_ID_REUSED`. The same UUID may legitimately appear once in each of the two tabs —
**no cross-tab REQUEST_ID_REUSED detection is claimed** (tested).

**Replay after an incomplete write (independent-review fix R2).** Exact replay is successful only when the entity
is not in lifecycle MISMATCH. When an earlier W1 exists but its W2 is incomplete, a same-request resend returns
`409 <ENTITY>_LIFECYCLE_MISMATCH` — never replay success — and recovery remains an explicit reconciliation (a new,
user-confirmed request with a reason). W2 is never retried and nothing reconciles automatically. Order of the
replay step:

- request id reused with a different fingerprint → `409 REQUEST_ID_REUSED` (unchanged, still first);
- exact replay + consistency `CONSISTENT` (or `NO_HISTORY`) → `200 replayed`, no write;
- exact replay + consistency `MISMATCH` → `409 <ENTITY>_LIFECYCLE_MISMATCH`, no W1, no W2, no retry, no
  compensation;
- no replay hit → the normal flow (current value, consistency gate, stale, no-op, W1, W2).

Cases this distinguishes (the backend only knows persisted history):

- **unknown, applied** (the W1 row was appended but the outcome was unknown, so W2 was not attempted): the record
  reads MISMATCH and the same-id resend is `409 MISMATCH`;
- **unknown, not applied** (no history row): the same-id resend has no replay hit and proceeds normally — W1 then
  W2, `200 changed`, `CONSISTENT`;
- **known W2 failure** (`STATE_WRITE_FAILED`, event recorded): the same-id resend of the original mutation is also
  `409 MISMATCH`, so known and unknown-applied partial failures converge on the same recovery rule. A
  reconciliation whose own W2 failed is treated the same way. Once reconciled, the original request replays
  normally again.

## 7. TEST / REAL mutation safety

Context scope, applied before identity matching:

- REAL targets only rows with `is_test_data` exactly `FALSE`;
- TEST targets only rows with `is_test_data` exactly `TRUE` **and** `test_batch_id` exactly the server-configured
  batch — a TEST write never changes an operational row;
- a blank / invalid flag on any content-bearing master row fails the request closed
  (`<ENTITY>_MASTER_DATA_INVALID / TEST_FLAG_INVALID`);
- a row outside the scope (e.g. a TRUE row in REAL) never matches and never creates ambiguity;
- phantom rows (R2c-1: four public columns blank; R2c-2: three business columns blank) are never targeted.

The lifecycle history is scoped the same way (`is_test_data` and batch). Exact identity: 0 matches →
`404 <ENTITY>_NOT_FOUND`; more than one → `409 <ENTITY>_ID_AMBIGUOUS {match_count}` (no ids or names in details).
The shared `require_write_context` helper is reused unchanged (no context → `503
REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`; TEST without a batch → the same).

**Consequence (by design):** the mock repository is always the TEST context, and the R2c-1 / R2c-2 operational
GETs list only `FALSE` rows, so in mock development the operational records shown in the UI are not targetable by
lifecycle writes (404 in the history panel and the actions). TEST-context behaviour is exercised by the backend and
fake-Sheets tests, not by operational UI visibility; the existing GETs were not changed to expose TEST rows.

## 8. Routes and contracts

| Route | Capability |
|---|---|
| `POST /api/v1/personnel/{personnel_id}/deactivations` | `can_manage_personnel` |
| `POST /api/v1/personnel/{personnel_id}/reactivations` | `can_manage_personnel` |
| `POST /api/v1/personnel/{personnel_id}/lifecycle-reconciliations` | `can_manage_personnel` |
| `GET /api/v1/personnel/{personnel_id}/lifecycle-history` | `can_view` |
| `POST /api/v1/departments/{department_id}/deactivations` | `can_manage_department` |
| `POST /api/v1/departments/{department_id}/reactivations` | `can_manage_department` |
| `POST /api/v1/departments/{department_id}/lifecycle-reconciliations` | `can_manage_department` |
| `GET /api/v1/departments/{department_id}/lifecycle-history` | `can_view` |

Bodies (`extra="forbid"`): `{expected_active_status, reason_th}` / `{expected_is_active, reason_th}`. Changed
response: `{request_id, changed: true, record_id, previous_state, new_state, lifecycle_consistency_after}`
(department states as booleans; `CONSISTENT` after W1 + W2). History response: `{entity_id, current_state,
latest_history_state, lifecycle_consistency, events[]}` with events `{lifecycle_event_id, event_kind,
previous_state, new_state, recorded_at, recorded_by, reason_th}` — no fingerprint, test batch, test flag or request
id is exposed. Personnel `current_state` is the raw source text (null when blank); department `current_state` is a
boolean (null unless exactly TRUE / FALSE).

**Existing GETs unchanged:** `GET /personnel`, `GET /personnel/{id}` (exactly `personnel_id, first_name,
last_name, active_status`) and `GET /departments`, `GET /departments/{id}` (exactly `department_id,
department_name_th, is_active`) gained no field (tested). No hard-delete route exists.

## 9. UI

New pages within the existing app shell (`AppLayout`, `NavBar`, `ResponsiveTable`, `ErrorState`, the
`alertdialog` pattern): `/personnel`, `/personnel/:personnelId`, `/departments`, `/departments/:departmentId`; nav
links "บุคลากร" and "แผนก" for `can_view`.

- Lists: stable id shown as code, distinct from the name; inactive records visible; personnel null / unknown
  status shown as "ไม่ทราบสถานะ" (never as active); search text and page in URL query parameters, and the detail
  page's back link returns to the exact list URL. Test rows never appear (operational GETs).
- Detail: identity, name, status, lifecycle status and history. Actions only for a valid known state: "ปิดใช้งาน"
  (ACTIVE) or "เปิดใช้งานอีกครั้ง" (INACTIVE); unknown state → actions disabled with a data-state warning. No
  department / branch / account / technician / driver editing; no create or delete.
- Dialog (project `alertdialog`, never `window.confirm`): id, name, current and target state, "nothing is
  deleted", for personnel an explicit note that deactivation does **not** disable the login account, change
  permissions, or change technician / driver / assignment data; reason required in both directions (and for
  reconciliation). No page-level unsaved warning.
- Controls are hidden without the capability (usability only); a backend 403 is still shown.
- `409` stale: "ข้อมูลถูกเปลี่ยนโดยผู้ใช้อื่น กรุณาโหลดข้อมูลล่าสุดก่อนดำเนินการอีกครั้ง" with a reload action; no
  automatic retry or overwrite.
- `MISMATCH`: explicit warning; normal actions hidden; "ซิงก์สถานะให้ตรงกับประวัติล่าสุด" with confirmation and
  reason for capability holders; never automatic.
- Outcome classification (review fix R2): unknown → the intent stays pending; a proven `409 *_LIFECYCLE_MISMATCH`
  (its own result kind, never success, replay or stale) → the pending intent is cleared, the dialog closes, an
  explicit warning ("พบว่าประวัติการเปลี่ยนสถานะถูกบันทึกแล้ว แต่สถานะข้อมูลหลักยังไม่ตรงกัน
  กรุณาตรวจสอบข้อมูลล่าสุดและซิงก์สถานะให้ตรงกับประวัติ") is shown, the lifecycle history and the record are
  reloaded, and the MISMATCH UI offers the explicit reconciliation (never automatic); a consistent `200 replayed`
  stays a completed replay; `409 *_LIFECYCLE_STALE` stays stale with its reload action; a known state-write failure
  stays "recorded, state pending".
- Request intent (`src/lib/lifecycle.ts`, the `registryPending` discipline in its own module): intent stored
  before sending; unknown outcomes (other 5xx, unknown history write, transport / timeout) are neither success nor
  failure and are kept; resend only by explicit user action with the SAME request id and body.
- Read failures (500 / 503 / schema invalid / read failed) are `ErrorState`, never "no personnel", "no
  departments" or "no history". The absent live department source is shown as data unavailable.

## 10. Narrow R1 test amendments

| Test | Amendment |
|---|---|
| `test_branch_write_batch7o2c.py::test_branch_capabilities_and_roles` | `MAINTENANCE_MANAGER` expected set + `can_manage_personnel`, `can_manage_department` (`# R2e`) |
| `test_registration_write_batch7o2b.py::test_capability_and_dev_role_mapping` | the same two additions |

No other existing test changed; no assertion was loosened (the exact branch-capability inventory is untouched).

## 11. Files

New backend: `app/domain/lifecycle_schema.py` (frozen constants), `app/domain/master_lifecycle.py` (shared
engine), `app/domain/personnel_lifecycle.py`, `app/domain/department_lifecycle.py`,
`app/api/v1/lifecycle_schemas.py`, `app/api/v1/lifecycle_route_support.py`,
`app/api/v1/personnel_lifecycle_routes.py`, `app/api/v1/department_lifecycle_routes.py`; tests
`test_personnel_lifecycle_batch_r2e.py`, `test_department_lifecycle_batch_r2e.py`,
`test_lifecycle_sheets_batch_r2e.py`, `test_lifecycle_audit_integrity_batch_r2e.py` (review fix R1), `test_lifecycle_replay_recovery_batch_r2e.py` (review fix R2).

Edited backend (additive): `app/domain/authz.py`, `app/api/v1/router.py`, `app/repositories/base.py`
(`LifecycleMasterRead` + four abstract methods), `app/repositories/google_sheets/repository.py`,
`app/repositories/google_sheets/schemas.py`, `app/repositories/mock/repository.py`, and the two R1 tests in §10.

New frontend: `src/lib/lifecycle.ts`, `src/lib/lifecycleAdapters.ts`, `src/lib/listQuery.ts`,
`src/components/LifecycleActionDialog.tsx`, `src/components/LifecyclePanel.tsx`, four pages; tests
`src/lib/lifecycle.test.ts`, `src/pages/PersonnelPages.test.tsx`, `src/pages/DepartmentPages.test.tsx`.
Edited frontend (additive): `src/App.tsx`, `src/components/NavBar.tsx`, `src/lib/capabilityNames.ts`,
`src/lib/labels.ts`, `src/lib/types.ts`.

Unchanged: `personnel.py`, `personnel_routes.py`, `department.py`, `department_routes.py`, `request_replay.py`,
`registry_write_support.py`, `registry_errors.py`, all R1 / R2a / R2b / R2d modules, `context.py`, `config.py`,
`registryPending.ts`.

## 12. Test ids (batch-local PROPOSED)

| Ids | Covered by |
|---|---|
| R2E-01..05, 09..11 | personnel transitions, unknown state refused, no-op, stale-before-no-op, reasons, same id |
| R2E-06..08, 12 | department transitions, stale-before-no-op, strict boolean, id/name/flags unchanged |
| R2E-13 | no DELETE; the six POST + two GET routes exist |
| R2E-14..18 | capability holders, independence, `can_manage_user` insufficient, inventory |
| R2E-19 | `X-Request-Id` before any read |
| R2E-20..25 | replay, reuse within each tab, the same UUID once per tab |
| R2E-26..33 | W1 rejected / unknown, W2 failure → MISMATCH, mismatch gate, reconciliation, no-op, server `related_request_id` |
| Review fix R2 (`test_lifecycle_replay_recovery_batch_r2e.py`, personnel + department) | 1: unknown-applied W1 → 503, one event, master unchanged, MISMATCH; same-id resend → `409 MISMATCH`, no new W1, no W2; 2: unknown-not-applied → same-id resend completes (W1 + W2, CONSISTENT); 3: known W2 failure → resend `409 MISMATCH`, then explicit reconciliation, then the original request replays; reconciliation replay while MISMATCH is not success; 4: a completed request still replays; 5: `REQUEST_ID_REUSED` still first (consistent and mismatch) |
| Review fix R2 (frontend) | `lifecycle.test.ts`: MISMATCH is its own kind for both entities; unknown → same-id resend → MISMATCH clears the intent (department); `PersonnelPages.test.tsx`: unknown → same-id resend → MISMATCH (no success text, intent cleared, dialog closed, warning, reload, reconciliation offered, nothing automatic); consistent replay is still success; known state-write failure is not success |
| Review fix R1 (`test_lifecycle_audit_integrity_batch_r2e.py`, personnel + department) | A: a generated reconciliation stays valid, and a non-adjacent earlier reference is valid; B/C: nonexistent, self, future, other-scope and other-entity references → `RELATED_REQUEST_DANGLING`, blank → `FIELD_REQUIRED`; D: `RELATED_STATE_MISMATCH`; E: same-state reconciliation → `TRANSITION_INVALID`; normal events keep a blank reference — each fails closed on the read and on all three mutations before any write, with issue counts only |
| R2E-34..37 | lifecycle-history responses; R2c GET contracts unchanged |
| R2E-38..44 | REAL FALSE-only (fake), TEST batch scope (mock + fake), invalid flags, no ambiguity, phantoms, exact identity |
| R2E-45..50 | spy call set, untouched mock state, fake request log over a workbook with user_account / technician / driver / responsibility tabs; department never rewrites personnel; no relationship routes |
| R2E-51..62 | frontend lists / details, inactive visible, unknown status, reason dialog, permission UI + 403, stale UI without retry, MISMATCH reconciliation, read error ≠ empty, URL state, responsive table labels, no login-disable wording |
| R2E-63 | subset-only route checks; no permanent freeze of future creation / relationship / account work |
| (fake) | missing history tab fail-closed, absent live department_master, literal department flag write, request counts |

## 13. Verification

| Suite | Result |
|---|---|
| A. R2e backend tests | **134 passed** (66 personnel + 19 department + 11 fake Sheets + 22 audit integrity + 16 replay recovery) |
| B. R2c-1 personnel | 122 passed |
| C. R2c-2 department | 152 passed |
| D. R2d equipment branch writes | 55 passed |
| E. R2b equipment branch read | 59 passed |
| F. R1 branch / registration capability + route inventory | 764 passed (7O2b / 7O2c mock + Sheets, incl. the two amended capability tests) |
| G. Replay / registry shared suites | 168 passed (7O2a read API / Sheets / domain, 7O2d costs) |
| H. Full backend | **3652 passed** (= 3518 baseline + 134 R2e) — run against the exact final candidate code |
| I. Ruff `--select E4,E7,E9,F` | 13 findings (baseline 13, unchanged); new modules clean apart from the existing FastAPI `B008` and `UP017` patterns |
| J. R2e frontend unit tests | **22 passed** (`lifecycle.test.ts` 5, `PersonnelPages.test.tsx` 12, `DepartmentPages.test.tsx` 5) |
| K. Full frontend unit | **667 passed** (61 files; = 645 + 22) |
| L. Typecheck / build | passed (`tsc -b && vite build`) |
| M. Frontend lint | 33 warnings (baseline), 0 errors — no new warning |
| N. Playwright inventory | 565 tests in 23 files (unchanged; no e2e spec added) |
| O. Full Playwright | **565 passed** (run alone, after review fix R2) |

## 14. Live Google Sheets

No live workbook was read or written by this batch, its tests or its verification. `department_master`,
`personnel_lifecycle_history` and `department_lifecycle_history` were NOT created. All Sheets behaviour runs on the
writable fake transport with synthetic rows; a passing fake run does not mean live UAT is ready.

**Live Personnel lifecycle UAT — BLOCKED** until a separately approved live step: `personnel_lifecycle_history`
creation, the production-auth capability mapping / cutover, verification of context-safe writes against the live
`personnel_master` (it holds both operational and TEST rows), and live UAT authorization. No live personnel row was read or
changed.

**Live Department lifecycle UAT — BLOCKED** until the owner supplies the operational department data and separate
approved steps create `department_master` and `department_lifecycle_history` and complete the auth cutover.
