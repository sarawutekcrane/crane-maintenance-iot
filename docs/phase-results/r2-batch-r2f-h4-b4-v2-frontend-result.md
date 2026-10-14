# R2 Batch R2f-h4 B4 — Technician V2-only Frontend + Dedicated Mock E2E — Result

Status: IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.

Contract: C1 Amendment A1 (`docs/project-governance/c1-amendment-a1-v2-only.md`) §12, §13, §15, §23–§26, §31.

**Owner decision applied (B4 scope, Option 1):** parallel V2 routes for B4 only. The V2-only UI lives on separate
`/v2/...` routes as a temporary development and testing arrangement. On every V2 route, when the cutover flag is OFF,
Repair / PM creation is blocked with no legacy fallback. The legacy UI and its baseline tests are preserved during
B4 solely for compatibility; Legacy is NOT exposed as an approved production workflow. B5 handles the navigation
cutover, the removal of the legacy assignment UI, and the deliberate amendment of existing tests.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `5d97afc0743072f5c0a69d284bd3f0e33a2f6b30`
  (tree `fba411bd62b634ae337758ccd89e8160d3951eaf`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged).

Local branch: `review/r2-batch-r2f-h4-b4-v2-frontend` (no remote). Nothing is staged, committed or pushed.

Mock / fake only:
- no live Google Sheet was read or written;
- **no backend change** (zero diff under `backend/`); no schema, role, capability or setting changed;
- the V2 cutover stays OFF by default. `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` is set only in the dedicated mock E2E
  backend process (O4).

## 1. Routes and workflows

All routes render inside the existing `AppLayout`. They are not linked from the main navigation (`NavBar` is
unchanged; navigation cutover is B5).

| Route | Page | Backend calls |
|---|---|---|
| `/v2` | index (context banner, links) | `GET /me` |
| `/v2/vehicle/:vehicleId/repairs/new`, `/v2/equipment/:equipmentId/repairs/new` | V2 Repair creation (MANUAL source; category, symptom) | `GET /me`; flag ON only: `POST /repairs` |
| `/v2/vehicle/:vehicleId/pm`, `/v2/equipment/:equipmentId/pm` | V2 PM work-order creation (plan list) | `GET /me`; flag ON only: `GET /pm/plans/status`, `POST /pm/work-orders` |
| `/v2/repairs/:repairId`, `/v2/pm/work-orders/:workOrderId` | job summary + assignment area by `assignment_model` | `GET /repairs/{id}` / `GET /pm/work-orders/{id}`; V2 only: `GET …/technician-assignments`, `GET /technicians`, `POST …/technician-assignments` |
| `/v2/my-work` | V2 My Work | `GET /my-work` only |
| `/v2/waiting-assignment` | U1 queues (Repair, PM) | `GET /repairs/v2-waiting-assignment`, `GET /pm/work-orders/v2-waiting-assignment` |

No V2 page calls a legacy assignment route (`/assign`, `/assignment-history`, `/repairs/my-work`,
`/pm/work-orders/my-work`, `/repairs/waiting-assignment`). Tested by unit tests and E2E.

## 2. API compliance (no guessed contract, no backend change)

Every contract was read from the backend source and confirmed against a running mock backend with the flag ON before
implementation:
- create bodies are exactly the existing request models, without the inline technician fields (with the flag ON the
  backend refuses them with 409 `ASSIGNMENT_MODEL_MISMATCH`);
- the assignment POST body is exactly `TechnicianAssignmentRequest` (`extra="forbid"`): `primary_technician_id`,
  `collaborator_technician_ids`, `expected_current` (always sent; null = no current set), optional `reason_th`; the
  `X-Request-Id` header is always sent;
- `GET /technicians` is walked with the existing `page` / `page_size` (200) only. No search parameter is invented;
  the filter box filters locally what is displayed;
- the U1 response, My Work resolutions and assignment read shapes are typed exactly as the B2 / B3 / R2f-h1 / R2f-h2
  response models.

## 3. Creation and the cutover signal

- `GET /me` signals are parsed fail-closed (`src/lib/serverSignals.ts`): V2 is enabled only when `/me` succeeded,
  `technician_assignment_v2_enabled` is exactly boolean `true` and `data_context` is a known value. A failed `/me`, a
  missing flag, `"true"`, `1`, `null`, or a missing / unknown context all mean disabled. There is no frontend-local
  toggle.
- Disabled → the create page shows "การมอบหมายช่างยังไม่เปิดใช้งาน", renders no form, and makes no request except
  `GET /me` (no plan read, no create, no legacy fallback form).
- Enabled → `POST /repairs` / `POST /pm/work-orders` with no technician field; the server marks the job
  `TECHNICIAN_V2` (verified by readback in E2E); the user lands on the V2 detail page.
- The create button is disabled while in flight and guarded by an in-flight ref (one request on a double click).

## 4. Picker and write safeguards

**Picker (`TechnicianV2Picker`):**
- data: everything the server returns for its own scope (all pages; any failed page fails the whole read; the walk
  is bounded at 50 pages, beyond which it fails closed);
- selection by stable `technician_id`; the name is shown separately (or "ไม่มีชื่อในข้อมูลหลัก"); the raw status is
  shown when not `ACTIVE`; the server's BOTH-ACTIVE gate stays authoritative;
- exactly one PRIMARY (select) plus zero or more COLLABORATORs (checkboxes that never include the PRIMARY);
  choosing a PRIMARY removes it from the collaborators; a client check refuses no PRIMARY, duplicates, PRIMARY as
  COLLABORATOR and any id the server did not list (no name, `user_id` or free text can be submitted);
- states: loading; error (`ErrorState` with code and request id; no form); empty ("ไม่มีช่างในขอบเขตข้อมูลนี้"; no
  form); unresolved (a stored id not in the server-scope list is shown as "ไม่พบรหัสช่างนี้ในขอบเขตข้อมูลปัจจุบัน
  (ยืนยันชื่อ/ขอบเขตไม่ได้)"); invalid selection (explicit message, no request).

**Detail panel by `assignment_model`:**
- `TECHNICIAN_V2` → `TechnicianAssignmentV2Panel`: current PRIMARY / COLLABORATORs (id + name), the recorded time and
  recorder, and the set history in a separate table ("เวลาที่บันทึก" = recorded time);
- `LEGACY` → read-only display of the legacy header mirror, labelled `LEGACY_USER_ID` and shown raw; no control and
  no V2 read;
- anything else (including a lower-case or blank marker) → `INVALID`: an explicit error, no control, no V2 read.

**Save (`src/lib/technicianV2.ts`, R2e request-intent pattern):**
- the intent (request id + exact body) is stored before sending under
  `crane.technicianAssignmentPending.v1:<userId>:<kind>:<jobId>`;
- proven outcomes clear it:
  - 200 changed / no-op / replayed;
  - 409 `TECHNICIAN_ASSIGNMENT_STALE`;
  - 403 / 404 / 409 / 422 refusals;
  - the listed pre-write 500 / 503 codes, including `*_READ_FAILED`;
  - `WRITE_FAILED {write_outcome: "rejected"}`;
- anything else stays UNKNOWN (transport failure or timeout, `write_outcome: "unknown"`, an unlisted 5xx, a
  non-envelope body). The intent is kept, survives a reload, blocks a new submission, and can only be resent with the
  SAME request id and body. There is no automatic retry;
- stale → explicit conflict message; the form is locked until "โหลดข้อมูลล่าสุด"; the reload keeps the selection,
  which the user must submit again against the new `expected_current`. Nothing is overwritten silently (E2E: the
  first writer's set stays current after the conflict);
- duplicate submit prevented (disabled button plus an in-flight ref);
- no empty-set unassignment (a PRIMARY is always required; there is no clear control);
- no assignment control on a job that is not exactly `OPEN`, on an `AMBIGUOUS` current set, without the kind's
  management capability, or while an unknown intent is pending;
- every failure is shown with its code and request id (`ErrorState` gained an optional, additive `code` prop).

## 5. My Work and U1

- **My Work:** `GET /my-work` only. PRIMARY and COLLABORATOR sections, each item linking to the V2 detail. Every
  non-`RESOLVED` resolution (including an unknown one) is an explicit message with the raw resolution, never an
  empty list. Loading, empty and `ErrorState` states. No legacy fallback request.
- **U1:** separate Repair and PM queues, each shown only with `can_manage_repair` / `can_manage_pm` (neither →
  permission denied, no request). NONE / AMBIGUOUS / DATA_INVALID are distinct badges; issue codes are shown raw with
  counts (`CODE × n`), never reinterpreted; an unknown status is shown as unknown. Every item links to its V2 detail.
  Loading; an explicit empty state; any failure replaces the rows with `ErrorState` (code + request id), never a stale
  queue; changing the page shows loading, never the previous page's rows. A manual refresh, plus a fresh read on every
  visit (after an assignment the job is gone on the next visit: E2E).

## 6. TEST / REAL labelling and cutover state

`V2ContextBanner` on every V2 page:
- `TEST` → "TEST — ข้อมูลทดสอบ";
- `REAL` → "REAL — ข้อมูลจริง", only when the server says exactly `REAL`;
- `UNCONFIGURED` → "ยังไม่ได้กำหนดขอบเขตข้อมูล";
- anything else → "ไม่ทราบขอบเขตข้อมูล", never REAL.

The banner also shows the cutover state ("เปิดใช้งาน" / "การมอบหมายช่างยังไม่เปิดใช้งาน"). It is informational
only; server authorization and TEST/REAL isolation stay authoritative.

## 7. Changed paths

| Path | Change |
|---|---|
| `frontend/src/lib/serverSignals.ts` (new) | fail-closed `/me` signal parsing |
| `frontend/src/lib/capabilities.tsx` | additive: exposes `signals` (no behaviour change for existing consumers) |
| `frontend/src/lib/types.ts` | additive optional `MeResponse` fields |
| `frontend/src/lib/technicianV2.ts` (new) | V2 types, reads, selection rules, request-intent store, outcome classifier, V2 error messages |
| `frontend/src/components/ErrorState.tsx` | additive optional `code` prop |
| `frontend/src/components/V2ContextBanner.tsx` (new) | context / cutover banner; cutover-OFF state |
| `frontend/src/components/TechnicianV2Picker.tsx` (new) | stable-ID picker |
| `frontend/src/components/TechnicianAssignmentV2Panel.tsx` (new) | V2 assignment panel |
| `frontend/src/pages/v2/*.tsx` (new, 7 files) | create gate, Repair create, PM start, job detail, My Work, U1 queues, index |
| `frontend/src/App.tsx` | adds the nine `/v2/...` routes only |
| `frontend/src/index.css` | three additive classes |
| `frontend/vite.config.ts` | vitest also excludes `e2e-v2/**` (Playwright specs) |
| `frontend/src/lib/technicianV2.test.ts`, `frontend/src/pages/v2/V2Pages.test.tsx` (new) | 73 unit tests |
| `frontend/playwright.v2.config.ts`, `frontend/e2e-v2/*` (new) | the dedicated mock E2E |
| `docs/phase-results/r2-batch-r2f-h4-b4-v2-frontend-result.md` (new) | this document |

**Unchanged:** every backend file; every legacy page (`RepairDetailPage`, `RepairCreatePage`, `MyWorkPage`,
`WaitingAssignmentQueuePage`, `OpenRepairQueuePage`, …); `NavBar`; `playwright.config.ts`; every existing unit and E2E
test.

## 8. Dedicated mock E2E architecture

`frontend/playwright.v2.config.ts`, `testDir ./e2e-v2`. It starts four processes and Playwright stops them at the end
(`reuseExistingServer: false`, `--strictPort`, so a stray server is never reused):

| Pair | Backend | Frontend |
|---|---|---|
| ON | 4321: `DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` | 4320 → proxy to 4321 |
| OFF | 4331: same, without the flag (the variable is explicitly unset, so the default OFF applies) | 4330 → proxy to 4331 |

- The baseline suite (4310 / 4311, flag OFF) is a different config and untouched.
- Start command: `cd frontend && npx playwright test -c playwright.v2.config.ts`. Optional trace evidence:
  `V2_E2E_TRACE_DIR=<dir>`.
- Projects:
  - `v2-on-desktop` (1280×800), `v2-on-tablet` (768×1024, touch) and `v2-on-mobile` (375×667, touch) run
    `v2-on.spec.ts` (8 tests);
  - `v2-off-desktop` and `v2-off-mobile` run `v2-off.spec.ts` (3 tests);
  - 30 executions per run.
- Isolation: mock repository only; synthetic B2 fixtures (`TEC-TEST-911` / `-912`, `USR-TEST-911` / `-912`; batch
  `MOCK-7O2B-SYNTHETIC`); in-memory state discarded on shutdown; each test asserts on the jobs it created itself.
- Route stubs only for error injection: AMBIGUOUS read, unknown `assignment_model`, whole-queue 500, DATA_INVALID
  item, transport abort. Every happy-path step hits the real backend.

Coverage of the required items:

| # | Item | Test |
|---|---|---|
| 1 | `/me` TEST + flag | on: `/me reports TEST…`; off: `/me reports the flag OFF` |
| 2 | Repair V2 create | on: Repair flow (body keys asserted; `TECHNICIAN_V2` readback) |
| 3 | PM V2 create | on: PM flow |
| 4 | picker = in-batch TEST only | on: Repair flow (options exactly 901 / 911 / 912; REAL 001 / 002 absent) |
| 5 | PRIMARY + COLLABORATOR | on: Repair (911 + 912) and PM (912 + 911) |
| 6 | readback + history | UI current set and history row + API readback (`VALID`, one set) |
| 7 | U1 NONE before | queue row `data-status=NONE` |
| 8 | excluded after | the row is gone on the next visit |
| 9 | My Work, both accounts | `X-Dev-Role: TECHNICIAN`, `USR-TEST-911` / `-912` → PRIMARY / COLLABORATOR sections |
| 10 | TEST label | banner on V2 pages (ON and OFF) |
| 11 | flag OFF blocks creation, no create request | off: Repair and PM (only GET `/me` observed) |
| 12 | access denied + corrupted data fail closed | on: TECHNICIAN (UI denied, read-only panel, server 403 on direct POST and queue); stubs for AMBIGUOUS / INVALID / 500 / DATA_INVALID |
| 13 | stale `expected_current` | on: two contexts; 409, no overwrite, reload + reconfirm → 200 with the new `expected_current` |
| 14 | desktop / tablet / mobile | three ON projects + two OFF projects; no horizontal overflow; primary buttons ≥ 44 px |

Also covered: a CLOSED job offers no control; transport failure → UNKNOWN, intent survives reload, same-id resend
(one set recorded); LEGACY job read-only (OFF backend, created legacy).

## 9. Gates (tested state = the candidate tree)

| Gate | Result |
|---|---|
| backend full pytest | 4583 passed, exit 0 (backend unchanged) |
| named R2f suites (24 files) | 931 passed, exit 0 |
| ruff | identical to base: `app` 550, `app tests` 933. Zero backend diff. The "13" recorded in earlier batches used a narrower invocation not reproduced here. |
| vitest | 63 files, 740 tests passed, exit 0 (baseline 667 + 73 new) |
| tsc (`tsc -b --noEmit`) | exit 0 |
| oxlint | 33 warnings / 0 errors, exit 0 (= baseline; the warning set is unchanged) |
| build | exit 0 (only the existing chunk-size notice) |
| baseline Playwright (unchanged config, ports 4310/4311, flag OFF) | 565 passed, exit 0, no retries |
| V2 mock E2E (`playwright.v2.config.ts`) | 30 passed in each of 3 consecutive runs on the final tree, exit 0, no retries, no flake |
| frontend fix-removal mutations | 28 of 28 caught (F01–F28), hash-checked restore |

**Mutations (each removes or weakens one safeguard; caught = a unit test fails):**

| Area | Mutations |
|---|---|
| cutover and labelling | F01 OFF gate removed; F02 truthy flag; F03 unknown context as REAL; F04 UNCONFIGURED shown REAL |
| selection | F05 duplicates; F06 PRIMARY as COLLABORATOR; F07 free-text ids |
| write body | F08 `expected_current` dropped |
| outcome classification | F09 transport as success; F10 stale not distinguished; F11 unlisted 5xx as refused; F12 write-unknown as refused |
| intent handling | F13 intent cleared on unknown; F14 intent written after send; F15 resend with a new id |
| form locking | F16 double submit; F17 stale form not locked; F18 reload drops the selection |
| control gating | F19 CLOSED assignable; F20 AMBIGUOUS assignable; F21 invalid model as V2 |
| legacy fallbacks | F22 legacy create field; F23 My Work legacy fallback; F24 unresolved shown as empty |
| queue and picker | F25 queue keeps stale rows; F26 queue without capability gate; F27 partial picker; F28 unbounded picker walk |

**Test-side corrections during development (reported, not concealed):**
1. **E2E locator:** "ไม่มีสิทธิ์เข้าถึง" matched two elements; the locator is now `exact`.
2. **E2E timing:** the option values were read before the picker rendered; the test now waits for the option count.
3. **E2E OFF assertion:** the dev build (React StrictMode) issues `GET /me` twice; the assertion is now "only GET
   `/me`" instead of a fixed count.
4. **Unit test:** the order of the `/me` and `/my-work` calls is not deterministic; the URLs are compared as a set.

One product defect found by the unit tests and fixed: during a normal in-flight save the pending-intent banner
replaced the form. It now shows only for a left-over unknown intent.

## 10. Observations for review (not changed in B4)

- **CLOSED jobs:** the backend V2 POST accepts an assignment on a CLOSED job (observed on the mock). "V2 assignment on
  CLOSED jobs" is PENDING (A1 §5), so the B4 UI offers no control. The backend behaviour is unchanged (backend changes
  are out of B4 scope) and is flagged for the owner.
- **Fail-closed strictness:** V2 creation also needs a known `data_context` (a flag `true` with a missing context is
  treated as disabled). This is stricter than the minimum "missing flag → fail closed".

## 11. Remaining dependencies

- **B5:** navigation cutover to the V2 routes; removal of the legacy assignment UI (RepairDetail free-text assign,
  RepairCreate inline technician, legacy My Work, legacy waiting page and nav, legacy-mirror assignee column);
  deliberate amendment of the baseline tests that create legacy jobs with the flag OFF (`pm-repair.spec.ts`,
  `web-uat-defect-fix.spec.ts` F2 / F3, `parts-lifetime.spec.ts`); folding the V2 suite into the regular E2E.
- **B6:** legacy backend cleanup, separately authorized.
- **Owner:** V2 assignment on CLOSED jobs (backend accepts it; see section 10); empty-set unassignment.
- **Live:** the live V2 columns, R11, link population, `REGISTRY_DATA_CONTEXT` in live, and Go-live each need their
  own approval.
- **Unchanged:** D5 PENDING; H3-01 fail-closed.
