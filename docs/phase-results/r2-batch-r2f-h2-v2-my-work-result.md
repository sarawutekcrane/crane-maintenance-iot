# R2 Batch R2f-h2 — V2 My Work — Result

Status: IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.
R2f-h is NOT complete: R2f-h3 (pre-Go-live report) and R2f-h4 (frontend, required) remain.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `b91eb382758b3a0aa6588867a3f9c0784d76dc36`
  (tree `7bf3fdbc7d64c1409539b3489a63a1892dd9b1ea`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only: no live Google Sheet was read or written; no account, personnel or technician link was created; no
role or capability changed; the cutover setting stays OFF and is neither read nor needed by My Work.

## 1. Route

`GET /api/v1/my-work` (C1 §24) returns `{resolution, technician_id, items}` for the AUTHENTICATED caller only.

- No route parameter can name another user. No capability is required beyond being the caller, exactly like the
  unchanged legacy `GET /repairs/my-work` and `GET /pm/work-orders/my-work`; a capability never widens the list.
- `items` is a list only when `resolution` is `RESOLVED` (possibly empty). Every other resolution returns
  `items: null` — never an empty list.
- Each item: `work_type` (REPAIR / PM), `job_id`, `asset_type`, `asset_id`, `status`, `opened_at`, `assignment_role`
  (PRIMARY / COLLABORATOR in the CURRENT set), `assignment_set_id`, `assigned_at`. Newest job first.

## 2. Identity chain (exact text, in the server's scope)

| Step | Unresolved resolution |
|---|---|
| Caller has no user id | `UNAUTHENTICATED` (no read at all) |
| User Account exactly once in scope | `ACCOUNT_MISSING`, `ACCOUNT_AMBIGUOUS`, `ACCOUNT_SCOPE_UNPROVEN` |
| Exactly one in-scope Personnel holds the user id | `PERSONNEL_UNLINKED`, `PERSONNEL_AMBIGUOUS`, `PERSONNEL_SCOPE_MISMATCH` (held only out of scope) |
| That Personnel's technician id: set, held by no other in-scope Personnel, exactly once in scope | `TECHNICIAN_UNLINKED`, `TECHNICIAN_AMBIGUOUS`, `TECHNICIAN_MISSING`, `TECHNICIAN_SCOPE_UNPROVEN` |

- Scope comes only from the frozen R2f-a proof (row flags / `same_scope`), never from an id or text. No folding,
  trimming, name, email, phone or prefix matching. A parity test pins the chain to the R2f-h1 recording chain: My
  Work lists a job exactly when recording on it is authorized.
- No lifecycle gate: an inactivated Personnel / Technician still sees assigned work (owner decision on recording
  remains PENDING; My Work follows the same literal reading).

## 3. Work lookup

- Source: the integrated R2f-h1 V2 assignment rows only (`read_work_assignment_v2_rows`), through the R2f-h1
  validator unchanged (`derive_assignment_state`, H1-01 completeness, ambiguity, row scope) plus the persisted
  reference proof.
- A job is listed when it is a TECHNICIAN_V2 job of the request's scope, still OPEN (the legacy My Work rule), and
  the technician is a member of its CURRENT set. Superseded sets and closed jobs are excluded.
- Fail closed (no list): ONE shared validation path runs for EVERY in-scope V2 job on each assignment tab BEFORE the
  list is filtered by the caller's technician — job existence, TECHNICIAN_V2 model, job scope = row scope, set
  integrity (H1-01), persisted Technician reference proof and current-set ambiguity (independent-review finding
  H2-01: the first candidate checked only set integrity for jobs not involving the caller). A lost row of this
  technician in another job would otherwise silently hide that job. Defects are 500
  `TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues}` (including `V2_ROW_JOB_MISSING`, `V2_ROW_ON_LEGACY_JOB`); an
  ambiguous current set is 409 `TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS`; a read failure is 503 `*_READ_FAILED`; an
  invalid personnel flag is 500 `PERSONNEL_MASTER_DATA_INVALID`; an unconfigured context is 503.
- Legacy jobs, legacy rows and legacy `user_id` values are never read; legacy My Work routes are unchanged.
- Read only: zero writes (spy-proven).

## 4. TEST / REAL

- Mock is TEST with synthetic TEST-scoped fixtures. REAL and TEST never see each other's rows, jobs or references;
  another batch is unresolvable.
- Live TEST: the live masters are untagged REAL, so the chain resolves `ACCOUNT_SCOPE_UNPROVEN` (fail closed).

## 5. Known limitations

1. Until the additive V2 columns exist live on BOTH assignment tabs, My Work answers 500
   `TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID` (never an empty list). The live schema step is separate.
2. One malformed V2 set anywhere in the request's scope fails every caller's My Work closed (by design: a lost row
   cannot be attributed to a technician).
3. Cost: one read per assignment tab plus one job read per in-scope V2 job on the tab (every V2 job is validated).
   Jobs of the other scope are neither validated nor listed, so a defect there never blocks this scope.
4. The H1-01 residual (a deliberate, consistent forgery of every row) applies unchanged.

## 6. PENDING governance (not decided here)

- Recording / My Work for a member inactivated after assignment (owner); V2 empty-set unassignment (owner); the
  "new assignee" reading; V2 assignment on a CLOSED job; the two R2f-h1 V2 GET routes.
- Out of h2: V2 waiting-assignment queue (contract amendment), pre-Go-live report (h3), frontend (h4, required),
  Go-live, R11 production authentication, the live schema step, account-link population.
