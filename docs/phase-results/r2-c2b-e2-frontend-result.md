# R2-C2b — E2 Operational Driver Assignment Frontend — Result

Status: **IMPLEMENTED AND TESTED — PASS** on the local review branch `review/r2-c2b-e2-frontend`, created from
the integration baseline. The implementation and testing stage created no commit, push, merge or deployment. The
one combined-regression item first reported as blocked (an obsolete R2-C2a "R2-C2b is not implemented" guard) was
corrected under a separate owner authorization (§9); the combined regression then passed 375 / 0.

## 1. Baseline

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `f931f2db29d0e2a8875a5f841758c85fd7a01c82` |
| Main | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` |
| Local review branch | `review/r2-c2b-e2-frontend`, created at the exact baseline after a clean-tree check |
| Governance | `c1-amendment-a2-driver-responsibility.md` (A2-2 to A2-6, A2-10, O1–O4); R2-C2b preflight decisions D1–D8 (owner-approved) |
| Backend contract | R2-C1: `operational_driver_assignment_routes.py`, `_schemas.py`, `operational_driver_assignment.py`, `operational_driver_timeline.py` (unchanged) |
| Earlier accepted figures | frontend Vitest 895; combined Playwright regression 350 (13 specs) |

## 2. Changed files (19: 18 of the 19 originally authorized paths + 1 separately authorized test file)

| Kind | Paths |
|---|---|
| New libraries | `frontend/src/lib/e2Assignments.ts`, `frontend/src/lib/e2Writes.ts` |
| New components | `frontend/src/components/E2VehicleAssignmentsPanel.tsx`, `E2OperationDialog.tsx`, `E2HistoryTable.tsx`, `E2DriverAssignmentsPanel.tsx` |
| New unit tests | `e2Assignments.test.ts`, `e2Writes.test.ts`, `E2VehicleAssignmentsPanel.test.tsx`, `E2OperationDialog.test.tsx`, `E2HistoryTable.test.tsx`, `E2DriverAssignmentsPanel.test.tsx` |
| New browser spec | `frontend/e2e/r2-c2b-e2-panels.spec.ts` |
| New document | `docs/phase-results/r2-c2b-e2-frontend-result.md` |
| Modified (required) | `frontend/src/pages/VehicleDetailPage.tsx` (mount, +5), `frontend/src/pages/DriverDetailPage.tsx` (mount, +3), `frontend/src/lib/labels.ts` (+133, additive only) |
| Modified (guard correction, separately authorized) | `frontend/e2e/r2-c2a-panels.spec.ts` (+30 / −2, one test only; §9) |
| Modified (optional, 1 of 2) | `frontend/src/pages/VehicleDetailPage.test.tsx`: the GPS-failure test's catch-all vehicle stub also matched the new E2 URLs; the two E2 reads get valid empty answers. No assertion changed. |

Not modified: the backend, `r2HistoryWrites.ts`, `registryPending.ts`, `lifecycle.ts`, `technicianV2.ts`, all
R2-C2a panels, the legacy `VehicleDriverAssignmentsPage.tsx`, routing (`App.tsx`), `playwright.config.ts`,
dependencies. `DriverDetailPage.test.tsx` needed no change.

## 3. Implemented features

**Vehicle Detail — "การมอบหมายผู้ขับรถตามวัน/กะ"** (mounted after the R2f-f permanent responsible-driver panel):
- current operational status (ASSIGNED with the assigned driver, UNKNOWN, NONE, CONFLICTED);
- schedule in a Bangkok date window (default today −7 to +30, adjustable) with a mode filter (G-1 `from` / `to` /
  `mode`; a reversed or invalid range is refused before any read);
- derived units with Bangkok spans: FULL_DAY ends "24:00" of its date, a night shift keeps its start date and
  shows "(+1 วัน)", a handover-clipped unit ends at the handover instant;
- conflicts on both axes, UNKNOWN spans, all five warning codes (non-blocking; the adjacency warning states that
  saving is not a safety clearance);
- the assignment list (latest state of every ASSIGNMENT event, lifecycle ACTIVE / CANCELLED / VOIDED, relations
  SPLIT / SUBSTITUTION) and the full immutable history (originals, revisions, HANDOVER rows, cancellations,
  reason, actor, recorded time, request id);
- with `can_assign_crane_driver`: CREATE, and per ACTIVE assignment REVISE / SUBSTITUTE / CANCEL / EARLY_END.

**Operation variants** (exact `OperationRequest` schemas; only that operation's fields are sent):

| Operation | Variants and body |
|---|---|
| CREATE | explicit driver and mode (no defaults), inclusive dates, explicit applied shift `{start_time, end_time, end_day_offset 0/1}` for DAY_SHIFT / NIGHT_SHIFT, optional `handover {predecessor_event_id, expected_revision_no}` (H2 / H3), `reason_th` required only for a back-dated start (A2-5.4) |
| REVISE | full-state correction / extension (driver, dates, shift; never the mode); shift-time split (`split_from_date` + new shift, current driver and dates unchanged); `exclude_dates`; `void_elapsed: true` |
| SUBSTITUTE | whole days / shifts by labelled `dates[]`, another explicit driver, reason |
| CANCEL | event, `expected_revision_no`, reason (backend: only before the start) |
| EARLY_END | `end {mode: NOW}` or `{mode: AFTER_DATE, date}`, reason (backend: only after the start) |

**Driver Detail — "การมอบหมายขับรถตามวัน/กะ (ทุกคัน)"** (read only, after the R2f-f panel): the driver's units
across vehicles in an adjustable window with a mode filter, conflicts, warnings and a link to each Vehicle Detail.

Both panels state "เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง". Historical search uses the existing
per-vehicle and per-driver range reads only; no fleet-wide search and no new endpoint.

## 4. API, permissions and authority separation (VERIFIED)

| Route (existing, R2-C1) | Used for | Capability |
|---|---|---|
| `GET /vehicles/{id}/operational-driver-assignments?from&to&mode` | vehicle schedule | `can_view` |
| `GET /vehicles/{id}/operational-driver-assignment-history` | history + settlement evidence | `can_view` |
| `GET /drivers/{id}/operational-driver-assignments?from&to&mode` | driver axis | `can_view` |
| `POST /vehicles/{id}/operational-driver-assignment-operations` | the five operations | `can_assign_crane_driver` |

- Controls render only with `can_assign_crane_driver`; the backend stays authoritative (403 otherwise).
- The E2 panels never read `responsible-drivers` (R2f-f) or `/vehicles/{id}/driver-assignments` (legacy Phase 6),
  verified in Vitest and in the browser. The mutation run proves the R2f-f history and the legacy data of VEH-1048
  are byte-identical before and after all E2 writes.
- The R2-C2a panels and the legacy page / link are unchanged. To keep the page's existing test contract, the E2
  panel does not render a second data-context banner (the page already shows one) and its out-of-scope state uses
  its own test id `e2-scope-unproven`.

## 5. Pending intent (`e2Writes.ts`, owner decision D1)

- Own module and storage key `crane.e2Pending.v1:<userId>:<vehicleId>`; only the UUID generator `newR2RequestId`
  is reused (identical contract). One unresolved intent per user / vehicle, one request in flight.
- The exact request id and serialized body are stored and read back BEFORE sending; no user id / secure random /
  working storage → nothing is sent.
- **First attempt**, removed only on: a correlated, shape-valid `changed: true` (warnings shown); a correlated
  `changed: false` (B27 duplicate: `existing_event_id` shown); a refusal on the explicit pre-write list (every code
  raised before the single append W1, plus `E2_CONCURRENT_CHANGE`, which the version guard raises with nothing
  written); W1 `history_write_outcome: "rejected"`. Stale and concurrent-change refusals reload; vehicle / driver
  overlap refusals show both intervals. Everything else (unlisted codes, 500s, 5xx, transport failure, timeout,
  malformed body, missing correlation) is UNKNOWN.
- **After any uncertain attempt** nothing removes the intent — no refusal (including post-replay ones), no no-op,
  no `E2_CONCURRENT_CHANGE`: the backend looks the id up in a history snapshot and holds no production lock, so an
  earlier attempt can still append after a resend's read. A success or replay only asks for settlement.
- **Settlement**: the vehicle history read contains a row with this exact `request_id` (the E2 history returns it
  per row — stronger evidence than R2-C2a's timeline record ids). Missing evidence keeps the intent.
- **CONFLICT** (409 `REQUEST_ID_REUSED`): kept, never resent, never given a new id, never settled by a read; the
  banner tells the user to report the request id to an administrator. No manual clear control exists.
- Resend is an explicit user action with the same id, path and body; there is no automatic retry.

## 6. TEST / REAL and isolation

- Google Sheets mode answers 501 `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` for every E2 route: both panels show an
  informational "not available before R11 (Mock/TEST only)" state with no controls and no workaround (Vitest).
- REAL writes: 409 `E2_REAL_WRITES_NOT_ENABLED` is a confirmed refusal shown in the dialog with the R11 explanation
  (Vitest; mock mode cannot be REAL by configuration, so not reachable in the browser).
- Out-of-scope ids (VEH-1046, DRV-0001) show the scope state and no controls (Vitest and browser).
- **Mutation isolation (D6):** `R2_C2B_MUTATION=1 npx playwright test e2e/r2-c2b-e2-panels.spec.ts --project=desktop
  --workers=1 --grep @mutation`; the tests refuse to run otherwise, use a fresh backend (`reuseExistingServer:
  false`), first prove `data_context` TEST and an empty E2 history, and use Bangkok-relative date windows per test.
  The history is append-only: CANCEL / EARLY_END / VOID add rows; nothing is described as restoring history.

## 7. Test results (executed on the final code)

| Check | Result |
|---|---|
| New unit tests | **74 passed**: e2Assignments 13, e2Writes 19, E2OperationDialog 21, E2VehicleAssignmentsPanel 13, E2DriverAssignmentsPanel 5, E2HistoryTable 3 |
| Full frontend Vitest | **969 passed** (81 files) = 895 earlier + 74 new; 0 failed |
| TypeScript (`tsc -b`) | clean |
| Lint (`oxlint`) | exit 0; 31 warnings = baseline, none new |
| Production build (`npm run build`) | passed |
| Playwright `r2-c2b-e2-panels`, read-only, 5 projects | **25 passed** (5 tests × 5 viewports) |
| Playwright `r2-c2b-e2-panels`, `@mutation` (isolated) | **5 passed** |
| Playwright `r2-c2a-panels`, `@mutation` (isolated; its host pages changed) | **5 passed** |
| Combined regression: the 13 earlier specs + `r2-c2b-e2-panels`, `--grep-invert @mutation` (before the guard correction) | 370 passed, 5 failed — see §9 |
| Corrected R2-C2a test (`r2-c2a-panels.spec.ts:117`), 5 projects (after the correction) | **5 passed** |
| Combined regression, same 14 specs (after the correction, fresh backend) | **375 passed, 0 failed** |
| `r2-c2a-panels` and `r2-c2b-e2-panels` `@mutation`, isolated (after the correction) | **5 passed** each |
| Backend E2 smoke (backend unchanged): R2-C1 E2 + Sheets + timeline + P0 fixture tests | **141 passed** |

**Mutation run evidence:** CREATE today (assigned now, NO_PERMANENT warning), duplicate → no-op with the existing
event id, exact replay (same id + body) → `replayed` with the original record ids and no new row, vehicle-axis
overlap refused with details and nothing written, INACTIVE driver refused; a future day shift split from a date,
an excluded unit, a whole-shift substitution, an extension and a cancellation (original rows retained:
CREATE, REVISE, REVISE, CANCEL); an H2 handover (the FULL_DAY ends at the night shift's start); a back-dated create
with a reason; EARLY_END now and VOID; every recorded request id was sent by this run and maps to one
`operation_id`; R2f-f and legacy data unchanged; the driver axis lists the units with vehicle links.

**Bugs found and fixed during implementation:** helpers exported from a component file raised three new lint
warnings (moved to `e2Writes.ts`); the E2 panel's second data-context banner and second `r2-scope-unproven` element
broke strict locators in existing specs (16 failures in the first combined run; the banner was dropped and the E2
scope state got its own test id); test-only locator and stub fixes in the new tests.

## 8. Known limitations

- **Pending intents:** a CONFLICT, or an UNKNOWN intent whose every resend is refused, stays pending for that user,
  vehicle and browser until a manual, authorized investigation (fail closed, as in R2-C2a).
- **Driver picker:** the driver master list is unscoped; the backend proves scope and eligibility.
- **No fleet-wide date search** (G-1 gap, accepted by D4); per-vehicle and per-driver range search only.
- **Rule hints only:** started / not-started, handover conditions, unit wholeness and the 366-day limits are
  decided by the backend; the UI offers the operations of every ACTIVE assignment and shows the backend's answer.
- **E2 is Mock/TEST only before R11**; the mock version guard is a single-process guarantee, not production
  atomicity. REAL-write refusal is verified in Vitest only (mock mode cannot be REAL).
- **Not run:** the full Playwright suite (all specs) and the full backend suite; browsers other than Chromium.

## 9. Obsolete R2-C2a guard — corrected (separately authorized)

**Cause.** `frontend/e2e/r2-c2a-panels.spec.ts:117` ("permanent responsible driver: VEH-1048 …") was written before
R2-C2b and asserted, page-wide, that Vehicle Detail shows no "การมอบหมายผู้ขับรถตามวัน/กะ" text (line 124) and makes no
`operational-driver` request (line 128). Both were valid then and false by design once E2 became a sibling panel on
the same page: 5 failures (one per project) in the first post-implementation combined run. The guard was not
edited, and the E2 heading was not renamed, until the owner authorized this one-file correction.

**Replacement (only those two lines changed; every other assertion of the test is kept).** A page-wide request log
cannot tell which sibling made a call, so the test now checks observable UI structure and the data contract:
- the permanent panel's own read `GET /vehicles/VEH-1048/responsible-drivers` answers 200 with exactly the R2f-f
  keys (`vehicle_id`, `timeline_status`, `current_status`, `current_driver_id`, `current_since`, `events`) and no
  E2 field (`assigned_driver_id`, `intervals`, `label_date`, `operational…`), and its `current_driver_id: null` /
  `NONE` is what the panel shows ("ยังไม่มีข้อมูล");
- the permanent card is not the E2 card, contains no `e2-*` element and no E2 heading text; the E2 card contains no
  `responsible-driver*` element; neither card contains the other;
- the E2 panel exists separately, with its own heading, and its own backend route was read;
- kept: the heading, the not-driving note, the current state, the legacy `/vehicle/VEH-1048/drivers` link, no
  horizontal overflow, VEH-1046 failing closed (`r2-scope-unproven`), plus no permanent-panel controls there, and
  no write at all.

Isolation stays protected: the unit tests of `ResponsibleDriverPanel` (R2-C2a) still prove that panel reads no E2
data, and the E2 panel tests prove it never reads the R2f-f or legacy routes; the R2-C2b mutation run proves the
R2f-f and legacy data are unchanged by E2 writes. No product code changed in this correction (checksums of all 17
R2-C2b product and test files were identical before and after).

## 10. Backend, Live Sheets and REAL data

No backend file, route, schema, authority or Google Sheets code was modified. No live Google Sheets access and no
REAL data operation: every browser write went to a dedicated, in-memory Mock/TEST backend that ended with its run.
R2-C3 (legacy cutover) was not started.

## 11. Next owner approval checkpoint

Each separately authorized: commit and push of the R2-C2b change set (19 paths) to `review/r2-c2b-e2-frontend`;
fast-forward integration; R2-C3 legacy cutover.
