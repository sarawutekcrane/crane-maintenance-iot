# R2f — C1 Amendment A1 — Technician V2-only First Launch

Status: PREPARED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW (batch B0, documentation only).

**What A1 does.** A1 SUPPLEMENTS the frozen Corrected C1 contract. It does not rewrite, replace or edit C1. Where A1
and C1 differ, A1 states the exact clause it amends; every other C1 clause stays in force unchanged.

**Authority.** The owner governance approval "R2f-h4 — B0 C1 Amendment A1 + B1 Read-signals Documentation
Correction — OWNER GOVERNANCE APPROVAL CONFIRMED" (this session, 2026-10-14). It records owner decisions O1–O4 and the
Additional Owner Decision on cutover OFF, cited below as **[APPROVAL]**.

**Current status (2026-10-14).** A1 was integrated with batch B0. It is now further amended by **A1-R1** (the next
section), which records the owner's final Technician V2-only decisions as implemented and integrated in B5 and B6 Rev2.
Where A1-R1 and an earlier A1 statement differ, **A1-R1 governs**. The earlier statements stay below, marked
SUPERSEDED, for historical rationale and approval traceability.

## A1-R1 — Superseding policy: Technician V2 only (owner final decision, 2026-10-14)

**Authority.** No business decision is added here; A1-R1 only records decisions the owner has already made and that
are implemented in integrated code. Cited below as **[R1-AUTH]**:
- "R2f-h4 B6 — Legacy Assignment Backend Cleanup + Owner Policy Enforcement — OWNER AUTHORIZATION: GO", owner
  decisions **D1** (CLOSED jobs), **D2** (whole-assignment withdrawal) and **D3** (legacy backend cleanup);
- "R2f-h4 B6 Rev2 — Final Owner Decision: Technician V2 ONLY — Remove ON/OFF and Legacy Creation";
- the owner's authorization to commit B6 Rev2 and its integration.

**Integration evidence.**

| Batch | Integration commit | Tree | Result document |
|---|---|---|---|
| B5 — frontend V2 cutover, legacy assignment UI removed | `83665121119af8762e7c4979af0f91ce7a12bf0c` | `9493015d1323877630a9f0674fada77b01dc85e0` | `docs/phase-results/r2-batch-r2f-h4-b5-v2-cutover-result.md` |
| B6 Rev2 — V2-only backend cutover, D1 / D2 / D3 | `f14e01c037f7494afb821b1969dd4ebaaccfc378` | `651dc1ca8ba6a0afd934a48bccdad6a54cc57471` | `docs/phase-results/r2-batch-r2f-h4-b6-legacy-cleanup-result.md` |

`main` remains frozen at `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

### R1 — Active requirements

1. **Sole model.** Technician V2 is the sole operational technician-assignment model.
2. **Every new job is V2.** Every new Repair job, PM work order and Repair Request conversion is created as
   `TECHNICIAN_V2` by the backend, unconditionally.
3. **No ON/OFF, no legacy fallback.** There is no operational Technician V2 ON/OFF setting and no legacy job
   creation. If a V2 creation precondition is not met (data context, TEST batch, extended job headers), creation
   fails closed with zero writes. It is never turned into a legacy job.
4. **Direct replacement.** On an OPEN job an authorized manager (`can_manage_repair` / `can_manage_pm`) may replace
   the PRIMARY and update the COLLABORATORs directly through the V2 assignment route, under the existing V2 rules
   (exact `expected_current`, one PRIMARY, stable `technician_id`, the §7 gate per new assignee).
5. **Whole withdrawal.** On an OPEN job an authorized manager may withdraw the complete current assignment (D2).
6. **Effect of withdrawal.** A withdrawn job stays OPEN, returns to U1 with status `NONE`, and leaves the former
   technicians' V2 My Work. It can be assigned again through the standard picker.
7. **History preserved.** Assignment and withdrawal histories are append-only and preserved, with actor and timestamp.
   No set is ended, deleted or rewritten by a withdrawal.
8. **Reasons optional.** A reason for changing or withdrawing technicians is optional.
9. **CLOSED jobs.** A job that is not exactly `OPEN` rejects every new assignment mutation (assignment and withdrawal;
   409 `TECHNICIAN_ASSIGNMENT_JOB_CLOSED`) (D1). A previously successful request still replays safely (same request
   id, same body; nothing new is written). Reads of its current set and history stay available.
10. **Legacy writes retired.** The legacy assignment write endpoints and legacy-only queues are retired (D3):
    - `POST /repairs/{id}/assign`, `POST /pm/work-orders/{id}/assign`, `GET /repairs/my-work`,
      `GET /pm/work-orders/my-work` and `GET /repairs/waiting-assignment` answer 410 `LEGACY_ASSIGNMENT_RETIRED`;
    - an inline legacy assignee on creation or conversion is refused (422).

    Shared assignment tabs, stored history, history reads, header mirrors, `AssignmentRole`, model separation and
    authentication / audit `user_id` are preserved (group C below, unchanged).
11. **Mandatory protections.** TEST/REAL scope isolation (server-derived only), authentication, authorization,
    idempotency (request id, replay, pending intent) and audit remain mandatory.
12. **No migration.** No data migration is planned for initial Production. A stored legacy job is never converted,
    rewritten or relabelled.
13. **No selectors in the UI.** The normal UI has no V2 ON/OFF control and no TEST/REAL selector. The data context is
    shown as an informational label only.

### R2 — Superseded statements

| Earlier statement | Status under A1-R1 |
|---|---|
| O4: `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` only in a dedicated mock test process | SUPERSEDED: the setting no longer exists (R1-3). The mock E2E backend runs without it. |
| Additional Owner Decision — cutover OFF (UI blocks creation when OFF; backend historical compatibility unchanged) | SUPERSEDED: there is no OFF state (R1-2, R1-3); the backend legacy write paths are retired (R1-10). |
| A1-§13: legacy backend compatibility is retained (routes, readers, rows, tests) | SUPERSEDED for routes and write paths (R1-10). Readers, rows, display and the C1 §13 [APPROVED] storage rules are retained. |
| A1-§24 read signal `technician_assignment_v2_enabled` on `GET /me` | SUPERSEDED: removed (`/me` carries `user_id`, `roles`, `capabilities`, `data_context`). |
| A1-§24 "Unchanged: the legacy `GET /repairs/waiting-assignment`" and C1 §24 Q4 "legacy `/assign`, the legacy queues … stay available in the backend" | SUPERSEDED: retired (410) under D3 (R1-10). Phase 6 Driver routes, the R2c / R2e GET schemas and "No DELETE" are unchanged. |
| A1-§25 rows keyed on `technician_assignment_v2_enabled` (true / false) | SUPERSEDED: creation is offered by capability alone; there is no "การมอบหมายช่างยังไม่เปิดใช้งาน" state (R1-2, R1-13). |
| A1-§26: enabling `TECHNICIAN_ASSIGNMENT_V2_ENABLED` in a live environment as a Go-live approval item; the test-only setting | SUPERSEDED: there is no setting to enable. Go-live and the other §26 approvals remain separately required (R4). |
| A1-§31: Playwright against a mock backend with `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true`; the dedicated cutover-OFF test mode | SUPERSEDED: the suite runs V2-only, with no OFF projects (B6 Rev2). The C1 §31 suites, baselines and synthetic fixtures are unchanged. |
| A1-§23 item 2: the R2f-h1 `cut_02` key set with value `LEGACY` | SUPERSEDED: under V2-only that test proves a new job is `TECHNICIAN_V2` (deliberate, marked test migration in B6 Rev2). |
| §3 group B: DEFER, not authorized by A1 | SUPERSEDED: authorized by D3 and implemented in B6 / B6 Rev2 (R1-10). |
| §5 PENDING "V2 assignment on CLOSED jobs" | DECIDED: D1 (R1-9). |
| §5 PENDING "V2 empty-set unassignment" | DECIDED: D2 whole-assignment withdrawal (R1-5, R1-6). It is a recorded withdrawal event, not an empty set. |

### R3 — Amended C1 clauses (by the decisions above; no new decision)

- **C1 §12:** the job marker is now unconditional for every new job. The other §12 locks are unchanged, including
  model separation.
- **C1 §13 ENGINEERING LOCK:** "legacy code paths unchanged for legacy jobs" no longer covers the retired write
  paths and legacy-only queues (D3). The §13 [APPROVED] storage rules and the read-only legacy display are unchanged.
- **C1 §24 Q4:** the legacy `/assign` routes and the legacy queues are retired (410) (D3). Everything else in Q4 is
  unchanged.

### R4 — Deployment prerequisites (not feature flags)

These are environment facts for a live deployment. Each still needs its own separate approval; A1-R1 grants none.
- **Data context:** creating any job in Google Sheets mode requires the server's REAL data context
  (`REGISTRY_DATA_CONTEXT`) to be configured. Otherwise creation fails closed (503
  `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`).
- **Live schema (C1 §27):** creation requires the additive V2 job headers on `repair_order` / `pm_work_order`, and V2
  assignment requires the V2 assignment headers. Otherwise it fails closed (500
  `TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID`). Adding them is the separately approved live schema change.
- **Live TEST context:** a Sheets-backed TEST context refuses V2 creation and assignment (409
  `TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED`), the existing fail-closed rule under C1 §15, unchanged.
- **Still separately approved:** real Personnel ↔ Technician / Account link population, production authentication
  (R11), the read-only pre-launch legacy verification, and Go-live.

### R5 — Unchanged

- **D5 remains PENDING**; **H3-01 remains fail-closed**.
- The pre-Go-live report (R2f-h3) still enables nothing. It no longer reports the removed setting.
- Still PENDING: recording / My Work after inactivation; the H1-01 residual-forgery limitation; C1 CC-5.
- Known residual: Google Sheets has no transactions, so a close landing between the status read and an assignment
  append can still be followed by that one append. It is recorded and auditable (B6 Rev2 result).

## 0. Authoritative source and identity

| Item | Value |
|---|---|
| Frozen contract | "R2f — Final Contract Consolidation — Corrected C1" (the C1 governance record of this R2 session; it is not a repository file) |
| C1 record SHA-256 | `94e942a4a8fd3c13f564f97849c0fc293c43c0fb6a5e33a2669553ccc2a96f97` |
| C1 order of authority | OD-1..OD-13 (final) > R2e > R2c > R2a/R2b/R2d > R1 (7O2) > Phase 6 > Core Demo Delta REV03–REV06 (C1 §2) |
| Integration baseline at A1 preparation | `web/phase7-dashboard-search-reporting` @ `3fbaad4633659bd84c2b17393aee6b2b23459b4a` (tree `599c2b2fa26330372bfc7c825689951c45f1dfa2`); `main` frozen @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` |

A1 adds no owner decision beyond those confirmed in [APPROVAL]. It grants no role, capability, live access or
deployment permission.

## 1. Owner decisions recorded [APPROVAL]

**O1 — V2-only operational model**
- The system has not yet entered operational technician-assignment use.
- First production launch uses only Technician V2. New Repair and PM jobs must be `TECHNICIAN_V2`.
- Assignment is by stable `technician_id`, with PRIMARY and COLLABORATOR.
- No legacy assignment UI in production: no legacy My Work and no legacy waiting-assignment UI.
- Machine registry and maintenance reference data are preserved.
- No legacy data migration or drain process is required, based on owner-confirmed facts.
- A separately authorized, read-only pre-launch verification may identify unexpected legacy assignments.

**O2 — V2 waiting assignment**
- Separate read-only Repair and PM queue contracts, with `can_manage_repair` / `can_manage_pm`.
- Include OPEN V2 jobs whose assignment status is NONE, AMBIGUOUS or DATA_INVALID. Exclude VALID assignments.
- After a successful assignment, a job leaves the waiting queue on the next successful refresh.
- Assigned jobs remain in the normal job lists and in My Work.
- Unattributable or tab-wide corruption blocks the whole queue.
- An unknown `assignment_model` must fail closed, not silently disappear.
- No N+1 reads.

**O3 — Safe removal**
- Remove the legacy assignment UI after the V2 replacement passes acceptance tests.
- Remove genuinely obsolete legacy backend code only after a separate dependency review and owner authorization.
  *[A1-R1: met for the B6 scope by D3 (R1-10). The rule still governs any further removal.]*
- Retain the shared assignment tabs, storage, history, and authentication and audit `user_id`.
- Retain permanent tests and TEST/REAL isolation protections.
- Do not remove operational reference data.

**O4 — Scope-aware technician picker** (supersedes the earlier REAL-only picker decision D-H4-3)
- `GET /technicians` and `GET /technicians/{id}` use the server-derived context.
  - REAL returns only REAL technicians.
  - TEST returns only TEST technicians of the server's batch.
  - UNCONFIGURED returns 503 before any repository read.
- No client-selectable scope.
- Existing authorization, pagination and fail-closed integrity are preserved.
- Approved for when B2 is implemented:
  - a deliberate R2f-a test amendment;
  - synthetic TEST Personnel, Technician and Account records for the mock's own batch, solely for repeatable E2E
    testing;
  - `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` only in a dedicated mock test process, never in a live environment.
    *[SUPERSEDED by A1-R1 — see the superseding policy section; kept for traceability.]*

**Additional Owner Decision — cutover OFF** *[SUPERSEDED by A1-R1 — see the superseding policy section; kept for traceability.]*
- The V2-only UI MUST NOT create Repair or PM jobs when the cutover is OFF.
- It displays an explicit not-enabled state and never falls back to legacy assignment controls.
- Backend historical compatibility remains unchanged until separately authorized.

## 2. Clause amendments

Each entry gives the approved **policy** first, then the **technical specification** that implements it. The
technical specifications are the contract that later batches implement; they are not implemented by A1.

### A1-§12 — Repair / PM new assignee (supplements C1 §12)

- **Policy [O1]:** first production launch is the Go-live. Every Repair and PM job created for operational use is
  `TECHNICIAN_V2`, assigned only by stable `technician_id`: exactly one PRIMARY plus zero or more COLLABORATORs.
  There is no import, no migration and no drain.
- **Unchanged:** the C1 §12 engineering locks — the job marker, V2 rows with blank `user_id`, the expected-current set,
  the §7 gate per new assignee, V2 recording authorization, and model separation (409 `ASSIGNMENT_MODEL_MISMATCH` in
  both directions).
- **Pre-launch verification [O1]:** a separately authorized, read-only check may identify unexpected OPEN legacy jobs
  carrying an active legacy assignment. Any finding is returned to the owner; A1 decides nothing about such jobs.

### A1-§13 — Legacy Repair / PM preservation (amends the C1 §13 ENGINEERING LOCK)

- **Policy [O1, O3]:**
  - legacy backend compatibility is retained (routes, readers, rows, tests); *[SUPERSEDED for routes and write paths
    by A1-R1 (D3); readers, rows and display retained.]*
  - the intended V2-only production UI presents NO legacy assignment control: no free-text or `user_id` assignee
    entry, no legacy assign, no legacy My Work list, no legacy waiting-assignment queue;
  - these controls are removed from the frontend after the V2 replacement passes acceptance tests.
- **Amended text:** C1 §13 "Legacy code paths (authorization, queues, free-text UI) are unchanged for legacy jobs"
  now applies to the BACKEND only. The C1 §13 display rule is kept: a legacy row is shown read-only as
  `LEGACY_USER_ID` with its raw string, and an unresolvable reference as "unresolved".
- **Unchanged:** C1 §13 [APPROVED] — `repair_assignment.user_id`, `pm_work_assignment.user_id`, the header mirrors
  and all legacy rows are never migrated, rewritten or reinterpreted as `technician_id`.

### A1-§15 — TEST / REAL (supplements C1 §15)

- **Policy [O4]:** the technician list and detail routes use the server-derived context. The client can never choose a
  scope.
- **Technical specification:**

  | Server context | `GET /technicians` (paged) and `GET /technicians/{id}` |
  |---|---|
  | REAL | REAL-scope rows only (unchanged) |
  | TEST | rows the repository proves TEST-scoped AND of the server batch only. Live TEST: the live master is untagged REAL, so the result is empty and never a REAL row. |
  | UNCONFIGURED | 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`, before any repository read |

  - No query or body parameter selects a scope.
  - Unchanged: authorization (`can_view`), paging, sort order, response shape, and the identity-integrity fail-closed
    behaviour (evaluated over the returned scope).
  - A TEST row is never returned in REAL, another batch's TEST row never in TEST, and scope is never inferred from
    an id, name or prefix (C1 §15 unchanged).
- **Synthetic mock fixtures [O4]:** the mock may carry synthetic TEST Personnel, Technician and Account records of the
  mock's own batch, linked to each other. They exist solely for repeatable E2E testing, carry no real personnel data,
  and never appear in REAL.
- **Unchanged:** C1 §15 fail-closed rules, including "live TEST relationship and responsibility UAT is impossible until
  explicitly TEST-scoped reference masters exist".

### A1-§23 — Legacy tests / contracts to amend (supplements C1 §23)

Deliberate, documented amendments are allowed. None deletes a test's intent.
1. **R2f-a `test_relationship_read_batch_r2f_a.py::test_r2fa_01_*`** (TEST fixture listing) for A1-§15 — in B2 [O4].
   Also **`test_r2fa_09_every_r2f_a_route_performs_zero_writes`**, the same O4 consequence: its detail probe used the
   REAL-scoped seed technician `TEC-TEST-001`, which is correctly 404 under the A1-§15 scope rule in the mock's TEST
   context. Its single probe id changes to `TEC-TEST-901`, the existing seed TEST technician of the mock server batch.
   The zero-write and read-only assertions and the test's intent are unchanged. *(Clarification recorded with the B2
   governance correction; no new behaviour, requirement, decision or permission.)*
2. **R2f-h1 `test_technician_assignment_batch_r2f_h1.py::test_r2fh1_cut_02_*`** — the exact-response key set gains
   `assignment_model` with value `LEGACY`. This is already in the read-signals candidate (B1); the storage assertions
   are unchanged. *[SUPERSEDED by A1-R1: under V2-only this test proves a new job is `TECHNICIAN_V2`.]*
3. **Frontend legacy-assignment tests**, on removal of the legacy UI (B5) [O3]: `MyWorkPage.test.tsx`,
   `OpenRepairQueuePage.test.tsx`, `e2e/web-uat-defect-fix.spec.ts`, `e2e/open-repair-report.spec.ts` (or as the B5
   audit identifies).

The C1 §23 "Not amended" list is unchanged, as are the backend legacy suites.

### A1-§24 — API boundary (supplements C1 §24)

**Approved routes (unchanged):** the two R2f-h1 V2 GET routes (owner decision D-H4-2):
- `GET /api/v1/repairs/{repair_id}/technician-assignments`
- `GET /api/v1/pm/work-orders/{pm_work_order_id}/technician-assignments`

They are read-only, require `can_view`, and are not rewritten.

**Read signals (batch B1 candidate, D-H4-1):**
- `assignment_model` (`LEGACY` | `TECHNICIAN_V2` | `INVALID`) on the Repair and PM detail responses, from the
  persisted marker only;
- `technician_assignment_v2_enabled` and `data_context` (`REAL` | `TEST` | `UNCONFIGURED`) on `GET /me`.
  *[SUPERSEDED by A1-R1: `technician_assignment_v2_enabled` is removed; `data_context` remains.]*

**U1 V2 waiting-assignment routes [O2]** — a proposed contract, implemented only in batch B3:

| Route | Capability |
|---|---|
| `GET /api/v1/repairs/v2-waiting-assignment?page&page_size` | `can_manage_repair` |
| `GET /api/v1/pm/work-orders/v2-waiting-assignment?page&page_size` | `can_manage_pm` |

- **Parameters:** `page >= 1`; `page_size` 1–200, default 50.
- **Read only:** zero writes. Each route is registered before the `/{id}` route of its family.
- **Order of checks:**
  1. capability (403, zero reads);
  2. data context (503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`, zero reads);
  3. reads.
- **Response:**
  `{data_context, items[], page, page_size, total_items}`. Each item is
  `{work_type, job_id, asset_type, asset_id, status: "OPEN", opened_at, assignment_status, issues}`.
  - `assignment_status` ∈ {`NONE`, `AMBIGUOUS`, `DATA_INVALID`};
  - `issues` is a code→count map, non-empty only for `DATA_INVALID`.
  - `status` is always exactly `"OPEN"` and `opened_at` is always a valid, timezone-aware timestamp. Neither is ever
    fabricated or null. *(B3 integrity clarification of O2.)*
  - Items are sorted newest first, with ties broken by job id; paging applies after classification.
- **Population:** OPEN jobs whose persisted marker is exactly `TECHNICIAN_V2`, in the server scope (REAL: flags
  exactly FALSE; TEST: TRUE plus the server batch). Jobs of the other scope are neither listed nor validated.
- **Statuses:**
  - `NONE` — no current set;
  - `AMBIGUOUS` — the current set cannot be determined;
  - `DATA_INVALID` — job-attributable defects only: that job's set integrity (H1-01 completeness / digest /
    duplicate / row-scope) and the persisted technician reference proof for that job's stored ids. *(B3 integrity
    clarification of O2: a job's scope flags are no longer job-attributable. A job whose scope cannot be proven cannot
    be attributed to this scope, so it fails the whole route below.)*
  - `VALID` jobs are excluded. After a successful assignment the job leaves the queue on the next successful
    refresh. It remains in the normal Repair / PM lists, on its detail page, and in the assigned technicians' V2 My
    Work when eligible under the existing contract. No job record is removed or changed.
- **Fail closed for the whole route** (never a partial queue):
  - tab-wide issues, orphan V2 rows (`V2_ROW_JOB_MISSING`) or V2 rows on legacy jobs (`V2_ROW_ON_LEGACY_JOB`) → 500
    `TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues}`;
  - a job with an unknown `assignment_model` → 500 `ASSIGNMENT_MODEL_DATA_INVALID` [O2: fail closed, never silently
    dropped];
  - *(B3 integrity clarification of O2)* → 500 `TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID {issues}`, with issue counts
    only and never a job id, asset id or stored row detail:
    - a `TECHNICIAN_V2` job whose scope flags cannot prove its scope (`JOB_SCOPE_FLAG_INVALID`: `is_test_data` not
      exactly `TRUE` / `FALSE`, or `FALSE` with a batch — the R2f-h1 `require_v2_job_in_scope` rule), in every
      context;
    - a `TECHNICIAN_V2` job proven in the server scope whose status is neither exactly `OPEN` nor exactly `CLOSED`
      (`JOB_STATUS_INVALID`);
    - a `TECHNICIAN_V2` job proven in the server scope with status exactly `OPEN` and no valid, timezone-aware
      `opened_at` (`JOB_OPENED_AT_INVALID`). A `CLOSED` job is never failed for its `opened_at`.

    A job of a provably different scope or batch is skipped without validating its job-level cells.
  - a schema problem → 500 `*_SCHEMA_INVALID`;
  - any read failure → 503 `*_READ_FAILED`.
- **Bounded reads [O2: no N+1]:** exactly three repository reads per request, whatever the page:
  - the V2 job rows (`read_work_order_v2_rows`);
  - the V2 assignment rows (`read_work_assignment_v2_rows`);
  - one technician master read for the persisted reference proof.

  There are no per-job reads.
- **Unchanged:**
  - the legacy `GET /repairs/waiting-assignment`; *[SUPERSEDED by A1-R1: retired, 410 (D3).]*
  - the 7C2 Open Repair Queue report;
  - R2f-h1, h2 and h3 behaviour;
  - no role or capability change.

**Unchanged C1 §24 Q4 (backend):** Phase 6 Driver routes, legacy `/assign`, the legacy queues and the R2c / R2e GET
schemas stay available in the backend. After B5 they are no longer frontend dependencies. **No DELETE** (unchanged).
*[SUPERSEDED by A1-R1 for legacy `/assign` and the legacy queues: retired, 410 (D3). The rest is unchanged.]*

### A1-§25 — UI boundary (supplements C1 §25)

**V2-only UI behaviour [O1, Additional Owner Decision].** Routing follows `GET /me` and the job's persisted signal:

| Signal | UI |
|---|---|
| job `assignment_model = TECHNICIAN_V2` | V2 assignment panel (stable-ID picker, current set and history separated, `expected_current`, R2e pending-intent pattern) |
| job `assignment_model = LEGACY` | read-only legacy display (`LEGACY_USER_ID` with raw string); no assignment control |
| job `assignment_model = INVALID` | explicit error; no assignment control |
| *[SUPERSEDED by A1-R1: creation by capability alone, no ON/OFF signal]* `technician_assignment_v2_enabled = true` | Repair / PM creation available (new jobs are `TECHNICIAN_V2`); My Work = `GET /my-work` only; manager waiting view = the U1 routes |
| *[SUPERSEDED by A1-R1: no OFF state exists]* `technician_assignment_v2_enabled = false` | the V2-only UI does NOT create Repair or PM jobs; explicit "การมอบหมายช่างยังไม่เปิดใช้งาน" state; no legacy assignment control, no legacy My Work, no legacy waiting queue |

**TEST labelling (D-H4-6):**
- `data_context = TEST` → clearly labelled TEST;
- `REAL` → shown only because the backend says exactly REAL;
- `UNCONFIGURED` → shown as unknown, never as REAL.

The signal is informational; server authorization and TEST/REAL isolation stay authoritative.

**U1 waiting view:** loading state; `ErrorState` with code and request id on any failure (never partial rows); an
explicit empty state; rows with distinct NONE / AMBIGUOUS / DATA_INVALID indicators (DATA_INVALID shows its issue
codes), each linking to the job detail.

**Unchanged C1 §25 rules:**
- stable ID separate from name;
- unknown, unresolved and scope-unproven shown explicitly;
- current vs history separated;
- effective vs recorded time;
- failed read → `ErrorState`;
- stale → reload;
- no delete;
- no auto-link suggestions;
- backend authorization authoritative;
- TEST never shown as REAL;
- responsive;
- the explicit My Work unresolved message.

**Mandatory separate UI backlog (C1 §25, D-H4-4; not waived):**
- personnel relationships and department history;
- equipment caretaker history;
- vehicle responsible driver;
- legacy `vehicle_driver` labelling.

This is a separate frontend batch after the V2-only UI.

### A1-§26 — Go-live / cutover (supplements C1 §26)

- **Policy [O1]:** first production launch = Go-live. My Work is Technician V2-only and there is no dual My Work
  (C1 §26 unchanged).
- **Each requires its own separate approval** (A1 grants none):
  - enabling `TECHNICIAN_ASSIGNMENT_V2_ENABLED` in any live environment (Go-live); *[SUPERSEDED by A1-R1: the
    setting no longer exists. Go-live itself remains separately approved, and the deployment prerequisites are in
    A1-R1 R4.]*
  - the live schema additions (C1 §27);
  - real Personnel ↔ Technician and Personnel ↔ Account link population;
  - production authentication (R11);
  - the read-only pre-launch legacy verification.
- **The pre-Go-live report** (R2f-h3) is unchanged. READY describes findings only and enables nothing. Owner decision
  **D5 remains PENDING**: an absent tagged R2f source stays BLOCKED, and the H3-01 fail-closed protection is unchanged.
- **Test-only setting [O4]:** `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` is permitted only in a dedicated mock test
  process. It is not a Go-live and never applies to a live environment. *[SUPERSEDED by A1-R1 — see the superseding policy section; kept for traceability.]*

### A1-§31 — Regression suites (supplements C1 §31)

- Every batch keeps the C1 §31 suites and baselines.
- From B4, a Playwright suite runs against a dedicated mock backend process with
  `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` and the synthetic TEST fixtures [O4]. *[SUPERSEDED by A1-R1 for the
  setting: from B6 Rev2 the dedicated mock backend runs V2-only without it, and there are no cutover-OFF projects. The
  synthetic fixtures and the scope below are unchanged.]* It exercises:
  - V2 Repair and PM creation;
  - assignment through the scope-aware picker;
  - the U1 queue (the job leaves after assignment);
  - V2 My Work;
  - TEST labelling.
- Route stubs remain only for error-state injection (5xx, AMBIGUOUS, DATA_INVALID, transport-unknown).
- The existing mock suite continues unchanged until B5.

## 3. Safe legacy removal boundaries [O3]

| Group | Treatment |
|---|---|
| A. Legacy frontend assignment controls (RepairDetail free-text assign, RepairCreate inline technician, legacy My Work sections, legacy waiting-assignment page and nav, legacy-mirror assignee column) | REMOVE / REPLACE after the V2 replacement passes acceptance (B5) |
| B. Legacy backend write paths (`POST /repairs/{id}/assign`, `POST /pm/work-orders/{id}/assign`, inline assignee on create / convert, assign notification) and legacy-only reads (legacy My Work, legacy waiting queue) | DEFER: removable only after a separate dependency review and owner authorization; NOT authorized by A1. *[SUPERSEDED by A1-R1: the dependency review and owner authorization (D3) took place, and these were retired in B6 / B6 Rev2 (410 / 422). The notification port is retained but dormant.]* |
| C. Shared storage and identity: `repair_assignment` / `pm_work_assignment` tabs (V2 rows share them), stored history, `assignment-history` reads, header mirror fields, `AssignmentRole`, model separation, authentication / audit `user_id`, V2 readers and validators, operational reference data | RETAIN |
| D. Temporary test scaffolding (route stubs used only until the scope-aware mock E2E exists) | may be removed once no longer necessary |
| E. Permanent automated tests and TEST/REAL isolation protections | RETAIN |

## 4. Approved policy vs implementation vs deployment

| Kind | Items | Status |
|---|---|---|
| Approved policy | O1–O4, cutover-OFF rule | recorded by A1 [APPROVAL]. *A1-R1: the cutover-OFF rule and the O4 setting clause are superseded; D1, D2, D3 and V2-only are recorded [R1-AUTH].* |
| Technical implementation | B1 read-signals (candidate), B2 scope-aware picker + synthetic fixtures, B3 U1 routes, B4 V2 frontend, B5 legacy UI removal, B6 legacy backend cleanup | each needs its own implementation authorization and independent review; B6 additionally needs the separate dependency review. *A1-R1: B5 is integrated at `83665121…` and B6 Rev2 (including the dependency review) at `f14e01c0…`.* |
| Live deployment | V2 setting in live, live schema additions, real link population, R11, pre-launch verification, Go-live | each needs its own separate approval; none granted. *A1-R1: there is no V2 setting; the deployment prerequisites are in A1-R1 R4; none is granted.* |

## 5. Unchanged and still PENDING

- D5 (absent tagged sources BLOCKED; H3-01 fail-closed unchanged).
- V2 empty-set unassignment. *[DECIDED by A1-R1: D2 whole-assignment withdrawal.]*
- V2 assignment on CLOSED jobs. *[DECIDED by A1-R1: D1 — rejected; safe replay retained.]*
- Recording / My Work after inactivation.
- The H1-01 residual-forgery limitation.
- C1 CC-5 (R1 precedent) unchanged.
