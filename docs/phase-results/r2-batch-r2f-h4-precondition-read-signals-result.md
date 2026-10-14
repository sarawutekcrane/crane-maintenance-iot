# R2 Batch R2f-h4 Precondition — Backend Read-only Signals and Legacy My Work Impact Analysis — Result

Status: IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.
This is a precondition for the R2f-h4 frontend. The frontend itself is NOT implemented, and R2f-h is not complete.

**Documentation correction (batch B1, 2026-10-14):** the owner's V2-only decisions O1–O4 and the cutover-OFF rule
(owner governance approval "R2f-h4 — B0 C1 Amendment A1 + B1 Read-signals Documentation Correction") are recorded in
C1 Amendment A1 (`docs/project-governance/c1-amendment-a1-v2-only.md`). This revision is documentation only. The candidate's CODE and tests are
byte-for-byte unchanged, including the R2f-h1 test amendment (section 4). Superseded analysis below is kept and
marked, not deleted.

**Baseline** (verified after a fresh fetch; no drift):
- `web/phase7-dashboard-search-reporting` @ `3fbaad4633659bd84c2b17393aee6b2b23459b4a`
  (tree `599c2b2fa26330372bfc7c825689951c45f1dfa2`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

**Local branch:** `review/r2-batch-r2f-h4-precondition-read-signals`, with no remote branch.

**Read only and mock / fake only:**
- no live Google Sheet was read or written;
- no write path, assignment storage, role, capability, setting or route authorization changed;
- the V2 cutover stays OFF (default) and is only reported.

## 1. Owner decisions applied

| Decision | Applied as |
|---|---|
| D-H4-1 | additive read-only signals: `assignment_model` (detail surfaces) and `/me` `technician_assignment_v2_enabled` + `data_context` |
| D-H4-2 | the two R2f-h1 V2 GET routes are APPROVED as integrated, and unchanged |
| D-H4-3 | **SUPERSEDED by O4** (A1-§15). The scope-aware `GET /technicians` / `GET /technicians/{id}` (REAL → REAL only, TEST → TEST of the server batch, UNCONFIGURED → 503; no client scope) is batch **B2, pending**. Unchanged in this candidate: `GET /technicians` is still REAL-only. *Original text, kept for the record:* "`GET /technicians` stays REAL-only (unchanged). Mock TEST V2 assignment cannot be exercised end to end through the picker, so the future UI tests use synthetic route stubs." |
| D-H4-4 | the R2f-a…g panels are recorded as a mandatory separate backlog (section 6); not implemented |
| D-H4-5 | no readiness-report UI; R2f-h3 unchanged |
| D-H4-6 | the `data_context` semantics are documented (section 3); no banner implemented |
| D-H4-7 | **RESOLVED by O1** (A1-§12, §26): V2-only My Work at first launch; no migration and no drain (owner-confirmed pre-operational state); a separately authorized read-only pre-launch verification may identify unexpected legacy assignments. The section 5 analysis is kept; its options and recommendation are superseded. *Original status:* "analysis only (section 5); BLOCKING for the My Work wiring of R2f-h4". |
| D5 | unchanged and PENDING: absent tagged sources stay BLOCKED |

## 2. New response-field contracts

### 2.1 `assignment_model` (D-H4-1)

`RepairResponse` (inside every `RepairDetailResponse`) and `PmWorkOrderResponse` (inside every
`PmWorkOrderDetailResponse`) gain `assignment_model: "LEGACY" | "TECHNICIAN_V2" | "INVALID"`.

The value is derived ONLY from the job's PERSISTED marker (`Repair.assignment_model` /
`PmWorkOrder.assignment_model`, as already read by the repositories), never from the cutover setting.

| Stored marker (exact text) | Signal |
|---|---|
| blank | `LEGACY` |
| `TECHNICIAN_V2` | `TECHNICIAN_V2` |
| anything else (case or space variants, `LEGACY`, other text) | `INVALID` — fail closed: never reported as either model |

**Why `INVALID` and not an error.** Before this batch, `GET /repairs/{id}` and the other legacy reads returned
such a job normally. Raising here would change existing legacy read error semantics, which the authorization forbids.
The fail-closed refusal stays where R2f-h1 put it: every V2 and legacy write and recording path still answers 500
`ASSIGNMENT_MODEL_DATA_INVALID` (tested). A client must offer neither model's actions for `INVALID`.

**Where it appears.** Every endpoint that returns a Repair detail carries it: `GET /repairs/{id}`, `POST /repairs`,
`/assign`, `/actions`, `/parts`, `/close`, and `POST /repair-requests/{id}/convert`. The same holds for every
endpoint that returns a PM detail. No job is read differently and nothing is written: the conversion happens in
the two existing response helpers (`_repair_response`, `_work_order_response`).

**Summary and list surfaces are deliberately unchanged.** These are `RepairSummaryResponse` /
`PmWorkOrderSummaryResponse`: `/repairs`, `/repairs/my-work`, `/repairs/waiting-assignment`, `/repairs/open-queue`,
`/pm/work-orders`, `/pm/work-orders/my-work`.
- `/repairs/open-queue` is the frozen 7C2 report. It reuses `RepairSummaryResponse`, pins its exact key set, and
  asserts item parity with `GET /repairs` (`test_open_repair_report_batch7c2.py::test_api_defaults_shape_and_parity_with_legacy_route`).
  Exposing the field on summaries would require amending that frozen R1-era test.
- The frontend's model routing needs only the detail pages. Today no list page except the Open Repair Queue report
  renders the assignee mirror.
- **Decision for review:** if the Open Repair Queue page must label V2 rows, a summary exposure plus a deliberate 7C2
  test amendment is a separate, explicit choice.
  - *Superseded by O2 (A1-§24):* manager visibility of V2 work needing assignment is the future U1 V2
    waiting-assignment routes (batch **B3, not implemented**). Summaries stay unchanged.

### 2.2 `/me` additions (D-H4-1, D-H4-6)

`GET /me` (no capability required, unchanged) gains two fields:

- **`technician_assignment_v2_enabled: bool`** — the ACTUAL server setting `TECHNICIAN_ASSIGNMENT_V2_ENABLED`, read
  through `cutover_from_settings` (the same accessor every V2 route uses). It is not hard-coded, and no route can
  write it. It says which model NEW jobs receive; an existing job's model is its own `assignment_model`.
- **`data_context: "REAL" | "TEST" | "UNCONFIGURED"`** — from `Settings.registry_context_effective`:

  | Server state | Value |
  |---|---|
  | configured exactly REAL | `REAL` |
  | configured exactly TEST | `TEST` |
  | mock mode | `TEST` (always) |
  | unset, or any other value | `UNCONFIGURED` |

  It is never REAL unless the setting is exactly REAL. A mock repository configured as REAL is still refused at
  startup (existing guard, tested). No credential, spreadsheet id, batch id or other internal setting is exposed.

### 2.3 Compatibility matrix

| Consumer | Effect |
|---|---|
| Existing frontend (`MeResponse`, Repair / PM detail types) | additive JSON fields, ignored by the current code; no frontend file changed |
| Legacy Repair / PM reads, queues, My Work, reports | unchanged response shapes (summaries untouched); unchanged errors |
| Legacy create / assign / history / recording | behaviour and errors unchanged; the response gains `assignment_model` |
| R2f-h1 V2 routes (assign, GET) | unchanged (D-H4-2) |
| R2f-h2 `GET /my-work` | unchanged |
| R2f-h3 readiness report | unchanged; D5 still PENDING / fail closed |
| Authorization | no route added, no capability or role changed, no gate moved |

## 3. Frontend semantics of the signals (for R2f-h4)

- **`assignment_model`:**
  - `LEGACY` → **read-only legacy display** (`LEGACY_USER_ID` with raw string); the intended V2-only production UI
    presents no legacy assignment controls (O1, A1-§13 / §25). *Superseded text:* "the unchanged legacy UI";
  - `TECHNICIAN_V2` → the V2 panel (GET / POST `technician-assignments`);
  - `INVALID` → an explicit error notice and no assignment controls.
- **`technician_assignment_v2_enabled`:** decides only what applies to NEW jobs. It never re-labels an existing job.
  - `true` → Repair / PM creation is available (new jobs are `TECHNICIAN_V2`).
  - `false` → the V2-only UI does **not** create Repair or PM jobs. It shows an explicit not-enabled state and never
    falls back to legacy assignment controls (Additional Owner Decision, A1-§25). Backend historical compatibility
    is unchanged.
  - *Superseded text:* "for example hiding the free-text assignee on Repair create".
- **`data_context`:**
  - `TEST` is shown clearly as TEST;
  - `REAL` is shown only because the backend says exactly REAL;
  - `UNCONFIGURED` is shown as unknown, never as REAL.

  It is informational: the server's TEST / REAL isolation and authorization remain authoritative.

## 4. Deliberate test amendment

The R2f-h1 test `test_technician_assignment_batch_r2f_h1.py::test_r2fh1_cut_02_off_creates_legacy_jobs_exactly_as_before`
pins the exact key set of the legacy create response. It gains exactly the key `"assignment_model"`, plus an assertion
that its value is `"LEGACY"`, marked "R2 Batch R2f-h4 precondition (deliberate evolution, owner decision D-H4-1)".

This is unavoidable once the approved field is on the detail surface. The test's intent is kept: the stored job is
still asserted byte-legacy (`assignment_model`, `is_test_data` and `test_batch_id` all blank) with no V2 row.

**This deviates from governance test item 13 ("legacy tests remain unchanged")** and is flagged for review. No other
existing test changed. The frozen 7C2 tests are unchanged (that is why the summaries are unchanged).

## 5. D-H4-7 — Legacy My Work transition analysis (ANALYSIS ONLY; no decision made)

> **Status (B1 correction): RESOLVED by owner decision O1** (A1-§12, §26) — V2-only My Work at first launch; no
> migration, no drain; legacy My Work UI not presented in production. Items 1–5 remain the factual analysis of the
> integrated code. Items 6–8 (options and recommendation) are **SUPERSEDED** and kept only as the historical record.

**1. What Legacy My Work shows today.** `MyWorkPage` makes three calls:
- `GET /repairs/my-work`: OPEN repairs where the caller's `user_id` is an ACTIVE legacy PRIMARY or COLLABORATOR in
  `repair_assignment` history;
- `GET /pm/work-orders/my-work`: OPEN PM work orders, the same rule on `pm_work_assignment`;
- `GET /repair-requests/mine`: every Repair Request the caller reported.

No capability is required beyond being the caller. V2 rows (blank `user_id`) never match, so V2 jobs never appear
there.

**2. What disappears under literal V2-only My Work.** If the page showed only `GET /my-work` after Go-live, every
OPEN legacy Repair and PM work order actively assigned to the technician at cutover would leave their My Work. That is
exactly the set the two legacy routes return at that moment, plus any legacy job (re)assigned later through the
unchanged legacy `/assign`.

The count cannot be stated here: it needs a live read, which is not authorized. Repair Requests (`/mine`) are not
assignment work and are not affected by the V2 rule.

**3. Whether legacy jobs stay reachable elsewhere.** Yes:
- by detail URL `/repairs/{id}` / `/pm/work-orders/{id}` (`can_view`);
- through the asset Repair / PM history pages (`can_view`);
- through `GET /repairs?assigned_to=<user>&status=OPEN`, an existing API with no UI for technicians;
- for managers, through the Open Repair Queue and the waiting-assignment queue (`can_manage_repair`).

Legacy recording on legacy jobs is unchanged after Go-live. A technician without a manager-shared link has no
in-app list of their own legacy jobs except asset browsing.

**4. Whether the backend can support parallel visibility unchanged.** Yes. The backend has no V2-only switch: the
legacy My Work routes and `GET /my-work` are independent and stay available whatever the cutover setting. Parallel
display would be purely a frontend composition; no assignment would be rewritten or migrated.

**5. Conflict with C1.** C1 §12 says "after Go-live, My Work serves V2 only", and §26 says "No import and no dual
My Work". Showing the legacy lists inside My Work after Go-live would contradict these literally. A separately
labelled legacy list outside My Work is a grey area and needs an owner ruling.

**6–7. Options** — *SUPERSEDED by O1; historical record only* (none approved; each needs the owner):

| Option | What | Benefit | Risk | Owner decision needed |
|---|---|---|---|---|
| A. Literal V2-only | My Work = `GET /my-work` only after Go-live | contract-exact; simplest | in-flight legacy jobs vanish from technicians' My Work; reliance on managers / asset pages | confirm acceptance of the visibility loss |
| B. Drain before Go-live | operational precondition: no OPEN, actively assigned legacy job at cutover (closed, completed or explicitly accepted) | contract-exact; no dual view; no code | may delay Go-live; needs an owner procedure and a count (a live read under its own authorization) | approve the precondition and its evidence |
| C. Separate legacy list outside My Work | a distinct, clearly labelled, read-only "legacy jobs still open" page from the unchanged legacy routes, with an exit criterion | preserves visibility; My Work itself stays V2-only | may be ruled "dual My Work"; two lists for technicians | rule whether C is compatible with §12 / §26, plus the exit criterion |
| D. Time-boxed dual section in My Work | V2 list plus a labelled legacy section until a date or zero legacy jobs | best continuity | contradicts §12 / §26 literally | a contract amendment to §12 / §26 |

**8. Recommendation** — *SUPERSEDED by O1 (the owner chose V2-only with no drain); historical record only*
(not an approval): prefer **B**, which keeps the frozen contract exact, with **A** as its
fallback for any residue the owner accepts. Consider **C** only under an explicit owner ruling. **D** requires a
contract amendment. Until D-H4-7 is decided, R2f-h4 must not wire My Work's Go-live behaviour. The pre-Go-live
behaviour (cutover OFF: legacy sections unchanged) needs no decision.

## 6. D-H4-4 — Mandatory separate UI backlog (R2f-a…g; not waived, not implemented)

Proposed boundary: **R2f-UI**, a separate frontend batch after R2f-h4 (after the V2-only UI and legacy-UI removal,
A1-§25). It touches no backend, and every route below already exists. The backlog remains **mandatory**.

| Panel | Page | Existing routes | Capabilities |
|---|---|---|---|
| Personnel relationships (technician, account, driver; resolution states incl. scope-unproven; `user_id` only for `can_link_personnel_account`) | `PersonnelDetailPage` | `GET /personnel/{id}/relationships`, `POST …/technician-links` / `account-links` / `driver-links` (+ `/history`, `/reconcile`) | `can_view`; link writes `can_link_personnel_*` |
| Department history (current vs history, effective vs recorded) | `PersonnelDetailPage` | `GET /personnel/{id}/department-history`, `POST …/department-events` | `can_view`; `can_manage_personnel_department_history` |
| Equipment caretaker history | `EquipmentDetailPage` | `GET /equipment/{id}/caretakers`, `POST …/caretaker-events`; `GET /technicians/{id}/equipment` | `can_view`; `can_assign_equipment_caretaker` |
| Vehicle responsible driver | `VehicleDetailPage` / `VehicleDriverAssignmentsPage` | `GET /vehicles/{id}/responsible-drivers`, `POST …/responsible-driver-events`; `GET /drivers/{id}/vehicles` | `can_view`; `can_assign_crane_driver` |
| Legacy `vehicle_driver` labelling | `VehicleDriverAssignmentsPage` | unchanged Phase 6 routes | unchanged |

- **Dependencies:** the R2f-h4 shared pieces (labels, pending-intent module, exact-id pickers) and the D-H4-6 context
  signal.
- **Gap noted:** C1 §24 lists `GET /personnel/{id}/department?as_of=`, which is not present in the integrated routes.
  The history route exists; an as-of view would be derived client-side from it or added by its own authorization.
- **Live:** these flows are blocked until their tabs and data exist (C1 §27). Live TEST stays fail-closed.

## 7. Tests

`backend/tests/test_read_signals_batch_r2f_h4_pre.py` adds 34 tests (mock), covering governance items 1–16:

- legacy / V2 / INVALID across six unknown marker spellings;
- the V2 GET still returning 500 for invalid markers;
- independence from the cutover setting, toggled OFF, ON, OFF;
- consistency across every Repair detail surface (create, GET, assign, action, part, close) and the PM detail
  surfaces;
- summaries proven unchanged;
- V2 set reads unchanged;
- `/me` cutover true / false;
- `/me` context TEST (mock), TEST, REAL and UNCONFIGURED;
- TEST, case or space variants, and unknown values never REAL;
- mock+REAL refused;
- exact field sets (existing fields kept, only the signals added);
- no new write route and unchanged 403s;
- read-only (state snapshot, write log, read-only repository calls);
- cutover default OFF.

Item 13 is evidenced by the diff: one deliberate amendment (section 4).

Fix-removal mutations: 8 of 8 caught (P01–P08). They cover:
- unknown → LEGACY;
- case folding of the marker;
- unknown context → REAL;
- case folding of the context;
- a hard-coded cutover;
- a hard-coded context;
- the Repair signal not taken from the marker;
- the PM signal not taken from the marker.

## 8. Limitations

1. **Summaries carry no model signal** (section 2.1). Manager visibility of V2 work is the future U1 waiting
   routes (O2, batch B3, not implemented).
2. **`INVALID` is a value, not an HTTP error,** on legacy reads (section 2.1). Writes still refuse.
3. **The picker in mock** cannot drive a TEST V2 assignment end to end in this candidate (still REAL-only).
   Superseded by O4. Mock E2E needs batch B2 (scope-aware picker plus synthetic TEST Personnel / Technician /
   Account records of the mock's own batch) and a dedicated mock test process with
   `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` (batch B4). No mock E2E exists or has passed yet.
4. *(Removed: D-H4-7 is resolved by O1.)* *Original text:* "D-H4-7 blocks the R2f-h4 My Work wiring."
5. **Still PENDING:** D5 (absent tagged sources stay BLOCKED; H3-01 unchanged), V2 unassignment, V2 on CLOSED jobs,
   recording or My Work after inactivation, the H1-01 residual. The V2 waiting queue is now owner-approved as a
   contract (O2) but not implemented (B3).
6. **Separate approvals still required** (A1-§26): R11 production authentication, real link population, live schema
   additions, the live V2 setting / Go-live, and the pre-launch verification. Legacy backend removal (B6) is not
   authorized.
