# R2f — C1 Amendment A1 — Technician V2-only First Launch

Status: PREPARED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW (batch B0, documentation only).

**What A1 does.** A1 SUPPLEMENTS the frozen Corrected C1 contract. It does not rewrite, replace or edit C1. Where A1
and C1 differ, A1 states the exact clause it amends; every other C1 clause stays in force unchanged.

**Authority.** The owner governance approval "R2f-h4 — B0 C1 Amendment A1 + B1 Read-signals Documentation
Correction — OWNER GOVERNANCE APPROVAL CONFIRMED" (this session, 2026-10-14). It records owner decisions O1–O4 and the
Additional Owner Decision on cutover OFF, cited below as **[APPROVAL]**.

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

**Additional Owner Decision — cutover OFF**
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
  - legacy backend compatibility is retained (routes, readers, rows, tests);
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
2. **R2f-h1 `test_technician_assignment_batch_r2f_h1.py::test_r2fh1_cut_02_*`** — the exact-response key set gains
   `assignment_model` with value `LEGACY`. This is already in the read-signals candidate (B1); the storage assertions
   are unchanged.
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
  - Items are sorted newest first, with ties broken by job id; paging applies after classification.
- **Population:** OPEN jobs whose persisted marker is exactly `TECHNICIAN_V2`, in the server scope (REAL: flags
  exactly FALSE; TEST: TRUE plus the server batch). Jobs of the other scope are neither listed nor validated.
- **Statuses:**
  - `NONE` — no current set;
  - `AMBIGUOUS` — the current set cannot be determined;
  - `DATA_INVALID` — job-attributable defects only: that job's set integrity (H1-01 completeness / digest /
    duplicate / row-scope), the persisted technician reference proof for that job's stored ids, and that job's scope
    flags.
  - `VALID` jobs are excluded. After a successful assignment the job leaves the queue on the next successful
    refresh. It remains in the normal Repair / PM lists, on its detail page, and in the assigned technicians' V2 My
    Work when eligible under the existing contract. No job record is removed or changed.
- **Fail closed for the whole route** (never a partial queue):
  - tab-wide issues, orphan V2 rows (`V2_ROW_JOB_MISSING`) or V2 rows on legacy jobs (`V2_ROW_ON_LEGACY_JOB`) → 500
    `TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues}`;
  - a job with an unknown `assignment_model` → 500 `ASSIGNMENT_MODEL_DATA_INVALID` [O2: fail closed, never silently
    dropped];
  - a schema problem → 500 `*_SCHEMA_INVALID`;
  - any read failure → 503 `*_READ_FAILED`.
- **Bounded reads [O2: no N+1]:** exactly three repository reads per request, whatever the page:
  - the V2 job rows (`read_work_order_v2_rows`);
  - the V2 assignment rows (`read_work_assignment_v2_rows`);
  - one technician master read for the persisted reference proof.

  There are no per-job reads.
- **Unchanged:**
  - the legacy `GET /repairs/waiting-assignment`;
  - the 7C2 Open Repair Queue report;
  - R2f-h1, h2 and h3 behaviour;
  - no role or capability change.

**Unchanged C1 §24 Q4 (backend):** Phase 6 Driver routes, legacy `/assign`, the legacy queues and the R2c / R2e GET
schemas stay available in the backend. After B5 they are no longer frontend dependencies. **No DELETE** (unchanged).

### A1-§25 — UI boundary (supplements C1 §25)

**V2-only UI behaviour [O1, Additional Owner Decision].** Routing follows `GET /me` and the job's persisted signal:

| Signal | UI |
|---|---|
| job `assignment_model = TECHNICIAN_V2` | V2 assignment panel (stable-ID picker, current set and history separated, `expected_current`, R2e pending-intent pattern) |
| job `assignment_model = LEGACY` | read-only legacy display (`LEGACY_USER_ID` with raw string); no assignment control |
| job `assignment_model = INVALID` | explicit error; no assignment control |
| `technician_assignment_v2_enabled = true` | Repair / PM creation available (new jobs are `TECHNICIAN_V2`); My Work = `GET /my-work` only; manager waiting view = the U1 routes |
| `technician_assignment_v2_enabled = false` | the V2-only UI does NOT create Repair or PM jobs; explicit "การมอบหมายช่างยังไม่เปิดใช้งาน" state; no legacy assignment control, no legacy My Work, no legacy waiting queue |

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
  - enabling `TECHNICIAN_ASSIGNMENT_V2_ENABLED` in any live environment (Go-live);
  - the live schema additions (C1 §27);
  - real Personnel ↔ Technician and Personnel ↔ Account link population;
  - production authentication (R11);
  - the read-only pre-launch legacy verification.
- **The pre-Go-live report** (R2f-h3) is unchanged. READY describes findings only and enables nothing. Owner decision
  **D5 remains PENDING**: an absent tagged R2f source stays BLOCKED, and the H3-01 fail-closed protection is unchanged.
- **Test-only setting [O4]:** `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` is permitted only in a dedicated mock test
  process. It is not a Go-live and never applies to a live environment.

### A1-§31 — Regression suites (supplements C1 §31)

- Every batch keeps the C1 §31 suites and baselines.
- From B4, a Playwright suite runs against a dedicated mock backend process with
  `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` and the synthetic TEST fixtures [O4]. It exercises:
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
| B. Legacy backend write paths (`POST /repairs/{id}/assign`, `POST /pm/work-orders/{id}/assign`, inline assignee on create / convert, assign notification) and legacy-only reads (legacy My Work, legacy waiting queue) | DEFER: removable only after a separate dependency review and owner authorization; NOT authorized by A1 |
| C. Shared storage and identity: `repair_assignment` / `pm_work_assignment` tabs (V2 rows share them), stored history, `assignment-history` reads, header mirror fields, `AssignmentRole`, model separation, authentication / audit `user_id`, V2 readers and validators, operational reference data | RETAIN |
| D. Temporary test scaffolding (route stubs used only until the scope-aware mock E2E exists) | may be removed once no longer necessary |
| E. Permanent automated tests and TEST/REAL isolation protections | RETAIN |

## 4. Approved policy vs implementation vs deployment

| Kind | Items | Status |
|---|---|---|
| Approved policy | O1–O4, cutover-OFF rule | recorded by A1 [APPROVAL] |
| Technical implementation | B1 read-signals (candidate), B2 scope-aware picker + synthetic fixtures, B3 U1 routes, B4 V2 frontend, B5 legacy UI removal, B6 legacy backend cleanup | each needs its own implementation authorization and independent review; B6 additionally needs the separate dependency review |
| Live deployment | V2 setting in live, live schema additions, real link population, R11, pre-launch verification, Go-live | each needs its own separate approval; none granted |

## 5. Unchanged and still PENDING

- D5 (absent tagged sources BLOCKED; H3-01 fail-closed unchanged).
- V2 empty-set unassignment.
- V2 assignment on CLOSED jobs.
- Recording / My Work after inactivation.
- The H1-01 residual-forgery limitation.
- C1 CC-5 (R1 precedent) unchanged.
