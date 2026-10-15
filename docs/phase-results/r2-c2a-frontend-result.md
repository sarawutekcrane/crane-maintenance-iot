# R2-C2a — Frontend Relationships, Histories, Caretaker and Permanent Driver Responsibility — Result

Status: **IMPLEMENTED AND TESTED** on the local review branch `review/r2-c2a-frontend-relationships-history`, created
from the integration baseline. The implementation and testing stage created no commit, push, merge or deployment.
Commit, push and integration each need separate owner approval. R2-C2b (E2 day / shift driver assignment) is NOT
implemented.

## 1. Baseline

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `d09d89588a33b8c98da99e86151a8feca964b99a` (P0, P0b and Personnel Scope Option S integrated) |
| Tree | `d9d8e12fd83fa76c985a92054ee3ca1d902548c5` |
| Main | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged) |
| Earlier accepted figures (not re-run as a whole here) | backend 4908 passed; frontend Vitest 798; relevant Playwright 105 |

## 2. Owner approvals

C2a-1 … C2a-8 (R2-C2a final read-only preflight decisions), with two safety corrections (§3), and DQ-C1 … DQ-C5
unchanged:
- explicit driver identity, never auto-selected (DQ-C2);
- R2f-f permanent responsibility separate from E2 (DQ-C3);
- final personnel acceptance on the real Mock/TEST backend (DQ-C4);
- the integrated equipment fixture used unchanged (DQ-C5).

The approved Thai labels are used:
- ความเชื่อมโยงข้อมูลบุคลากร (personnel links)
- ประวัติการสังกัดแผนก (department history)
- ผู้ดูแลอุปกรณ์และประวัติ (equipment caretaker)
- ผู้รับผิดชอบรถประจำ (permanent responsible driver)
- รถที่รับผิดชอบประจำ (driver → vehicles)

The permanent-driver panels state "ผู้รับผิดชอบรถประจำ ไม่ได้ยืนยันว่าเป็นผู้ขับรถจริงในแต่ละวัน". The R2-C2b label
(การมอบหมายผู้ขับรถตามวัน/กะ) is reserved and not shown.

## 3. The two safety corrections

**C2a-2 — strict, family-aware write outcomes.** The rejected rule was "every 4xx is a confirmed zero-write"; see §8.

**C2a-3 — isolated browser writes.**
- Real writes run only in a dedicated, fresh Playwright invocation: `R2_C2A_MUTATION=1`, `--project=desktop`,
  `--workers=1`, `--grep @mutation`, with its own new backend because `reuseExistingServer` is false.
- The tests refuse to run otherwise.
- They first prove the backend is Mock/TEST and untouched (empty histories).
- They never describe TRANSFER → END as restoring history: the append-only records are expected, kept and checked.
- See §15.

## 4. Changed files (28)

**Modified (8)**

| Path | +/− | Why |
|---|---|---|
| `frontend/src/pages/PersonnelDetailPage.tsx` | +10 / −3 | Mounts the personnel links and department history panels. |
| `frontend/src/pages/EquipmentDetailPage.tsx` | +4 | Mounts the caretaker panel. |
| `frontend/src/pages/VehicleDetailPage.tsx` | +5 | Mounts the permanent-driver panel. The legacy driver link is untouched. |
| `frontend/src/pages/DriverDetailPage.tsx` | +4 | Mounts the driver → vehicles panel. |
| `frontend/src/lib/labels.ts` | +144 / −0 | Purely additive: approved labels and error messages. No existing message changed (checked). |
| `frontend/src/lib/capabilityNames.ts` | +8 / −0 | The five existing backend capability names. |
| `frontend/src/pages/EquipmentDetailPage.test.tsx` | +23 / −2 | Optional; see §17. |
| `frontend/src/pages/VehicleDetailPage.test.tsx` | +5 | Optional; see §17. |

**New (20)**

| Group | Files |
|---|---|
| Shared modules | `frontend/src/lib/r2History.ts`, `frontend/src/lib/r2HistoryWrites.ts` |
| Components | `frontend/src/components/PersonnelLinksPanel.tsx`, `DepartmentHistoryPanel.tsx`, `TimelineEventDialog.tsx`, `TimelineHistoryTable.tsx`, `CaretakerPanel.tsx`, `ResponsibleDriverPanel.tsx`, `DriverVehiclesPanel.tsx` |
| Unit tests | one per module above (9 files) |
| Browser test | `frontend/e2e/r2-c2a-panels.spec.ts` |
| Document | this file |

**Not changed:** backend, mock seeds, Google Sheets code, `App.tsx`, `playwright.config.ts`, `lib/types.ts`,
`lifecycle.ts`, `registryPending.ts`, `technicianV2.ts`, the legacy vehicle–driver page, the department pages, and
governance documents.

## 5. Components

**Shared modules**
- **`lib/r2History.ts`**: the exact response contracts (strict parsers) and a read hook.
  - A body of the wrong shape is an error, never "no data".
  - A re-read keeps the last good data visible until the new answer arrives.
  - Failures are classified as forbidden, not found, out of scope, conflict, unavailable or invalid.
- **`lib/r2HistoryWrites.ts`**: pending intents and outcome classification, exact resend, settlement against the
  history, and the shared panel write hook (`useR2Writes`).

**Components**
- **`TimelineHistoryTable`**: the shared read-only effective-dated history.
  - Effective time and recorded time are separate.
  - DATE precision is shown as a date only, in Bangkok time.
  - Shows the revision, recorder, cancelled / not-in-force state and system notes. No reason column, because the
    reads return none.
  - Exports the shared read-failure view.
- **`TimelineEventDialog`**: the five operations (TRANSFER, INSERTION, END, CORRECTION, CANCELLATION).
  - NOW is offered only for TRANSFER and END. DATE is 00:00 Bangkok. DATETIME carries an explicit +07:00 offset.
  - Corrections are prefilled from the chosen event and carry its `event_id` and `expected_revision_no`.
  - A correction of an END sends no target.
  - Cancellation warns that the original record is kept.
  - The target is never pre-selected. Also exports the shared write notice.
- **`PersonnelLinksPanel`**: three sections (technician, account, driver).
- **`DepartmentHistoryPanel`**, **`CaretakerPanel`**, **`ResponsibleDriverPanel`**, **`DriverVehiclesPanel`**.

**Where they are mounted**

| Page | Panels |
|---|---|
| Personnel detail | links panel, then department history (after the existing lifecycle panel) |
| Equipment detail | caretaker panel (after the details card) |
| Vehicle detail | permanent-driver panel (after the registry history panels) |
| Driver detail | driver → vehicles panel (after the driver card) |

Each panel does its own reads and refreshes only itself, not the whole page.

## 6. API bindings (existing routes only; no backend change)

| Panel | Reads | Writes |
|---|---|---|
| Personnel links | GET `/personnel/{id}/relationships`; GET `/personnel/{id}/{technician\|account\|driver}-links/history` | POST `/personnel/{id}/{x}-links` (`{operation: LINK\|UNLINK\|RELINK, expected_<x>_id, new_<x>_id?, reason_th}`); POST `…/reconcile` (`{expected_<x>_id, related_request_id, reason_th}`) |
| Department history | GET `/personnel/{id}/department-history` | none |
| Caretaker | GET `/equipment/{id}/caretakers`; GET `/technicians?page_size=200` (names / picker) | POST `/equipment/{id}/caretaker-events` (five operations) |
| Permanent driver | GET `/vehicles/{id}/responsible-drivers`; GET `/drivers?page_size=200` (names / explicit picker) | POST `/vehicles/{id}/responsible-driver-events` (five operations) |
| Driver → vehicles | GET `/drivers/{id}/vehicles` (current responsibilities only) | none |

- Every write sends `X-Request-Id` (UUID v4) through the existing `apiMutation`.
- No E2 route, department-detail route or user-account list is called.
- The browser test asserts there are no `operational-driver` or `/departments` requests on these pages.

## 7. Capabilities and redaction

| Action | Capability | Holders |
|---|---|---|
| Technician link | `can_link_personnel_technician` | ADMIN, MAINTENANCE_MANAGER |
| Account link | `can_link_personnel_account` | ADMIN, MAINTENANCE_MANAGER |
| Driver link | `can_link_personnel_driver` | ADMIN, MAINTENANCE_MANAGER, DRIVER_DEPARTMENT_MANAGER |
| Caretaker events | `can_assign_equipment_caretaker` | ADMIN, MAINTENANCE_MANAGER |
| Permanent-driver events | `can_assign_crane_driver` | ADMIN, MAINTENANCE_MANAGER, DRIVER_DEPARTMENT_MANAGER |

- Capabilities come from `/me`.
- Write controls are hidden without the capability. Histories stay readable with `can_view`.
- A 403 after sending is shown as a confirmed refusal. The backend remains the authority.
- No department-move control exists, because no role holds that capability.
- **Account redaction.** Without `can_link_personnel_account` the server omits or nulls every account `user_id`.
  The UI shows "ซ่อนไว้ (ไม่มีสิทธิ์ดูรหัสบัญชีผู้ใช้)" in the current link and the history, and never
  reconstructs an id. This is verified with the DRIVER role on the real backend.

## 8. Pending-intent contract (`r2HistoryWrites.ts`)

**Before sending**
- A UUID v4 is generated from `crypto.getRandomValues`.
- The exact path and serialized body are stored under
  `crane.r2HistoryPending.v1:<userId>:<family>:<entityId>` and read back before sending.
- No user id, no secure random source, or no working storage means nothing is sent ("blocked", fail closed).
- One unresolved intent per user / family / entity, and one request in flight. A double click sends one request
  (browser-verified).

**First attempt**
- Removed only on:
  - a correlated (body `request_id` and, when present, the `X-Request-Id` header) and shape-validated success; or
  - a refusal whose (status, code) is on the family's explicit pre-write list.
- The pre-write lists were taken from the backend sources: `personnel_link.py`, `equipment_caretaker.py`,
  `crane_driver_responsibility.py`, `effective_time.py`, the request-id dependency and the write-context check.
  Every listed code is raised before the single history append (W1).
- Special outcomes:
  - 409 `REQUEST_ID_REUSED` keeps the intent as CONFLICT.
  - A W1 failure is removed only when `history_write_outcome` is exactly "rejected"; otherwise it is kept.
  - A link projection (W2) failure with the event recorded is kept as RECORDED until the link history shows the
    request, which then offers Reconcile.
  - A stale code means a confirmed refusal plus a reload.
  - A first-attempt link MISMATCH is a zero-write that leads to Reconcile.
  - Everything else is UNKNOWN: unlisted 4xx, 5xx, a transport failure or timeout, a malformed body, or missing
    correlation.

**After an uncertainty** (as corrected by the final safety closure, §24)
- No response removes the intent, as in `registryPending.ts`.
- A success or a replay keeps it for settlement against the authoritative read:
  - link history: an event carrying this request id;
  - caretaker / permanent-driver timeline: a record id proven by a correlated response.
- A refusal of the resend (any status and code, including those the backend raises after its request-id replay
  lookup) and a no-op of the resend keep the intent as UNKNOWN. The message says the refusal does not prove that
  the earlier attempt was not recorded.
- 409 `REQUEST_ID_REUSED` keeps it as CONFLICT.
- A CONFLICT intent is never resent and never settled by a read.

**Resend:** only by an explicit user action, with the same id, path and stored body. No automatic retry and no
replacement id.

## 9. Replay and uncertain-write evidence

**Unit tests (`r2HistoryWrites.test.ts`, 37 after §24)**
- Confirmed change, no-op, refusal and stale.
- Unlisted 4xx stays uncertain, including cross-family codes.
- `REQUEST_ID_REUSED`; W1 rejected and unknown; W2 recorded.
- Missing or mismatched correlation; malformed bodies; network failure, timeout and 5xx.
- Replay leads to settlement.
- After an uncertainty, no refusal (pre- or post-replay, arbitrary 4xx, unknown code) and no no-op removes the
  intent (§24).
- Both timeline families against a fake append-only backend (§24).
- Exact resend (same id, URL and body); no automatic retry; a new write blocked while one is pending; concurrent
  submission blocked.
- Settlement by record id and by link request id; no settlement without evidence.
- Storage failure, missing crypto and missing user (nothing sent); a corrupt stored intent; an orphaned
  SUBMITTING intent.

**Browser, read-only run** (the write is intercepted and never reaches the backend):
- A transport failure leaves the intent pending.
- The resend carries the identical id and body.
- After a reload it is still pending, never assumed successful.

**Browser, mutation run:** an exact replay of a real caretaker TRANSFER (same id and body) returns `replayed: true`
and the history count is unchanged.

## 10. Personnel Mock/TEST acceptance (DQ-C4)

Verified in all 5 viewports, on the real mock backend:
- The list shows only PER-TEST-911 / 912; PER-TEST-001 is not listed and its detail is "not found".
- List → detail navigation works.
- Relationships: technician TEC-TEST-911 with name, account USR-TEST-911, driver unset.
- Three empty link histories and the department-history empty state; the TEST context banner is shown.
- No horizontal overflow; no writes.

Mutation run: the PER-TEST-912 driver link LINK → UNLINK through the UI. The history keeps both events, and their
request ids equal the ids the browser sent. The technician and account links of PER-TEST-911 / 912 are byte-for-byte
unchanged (checked before and after).

## 11. Equipment caretaker acceptance

- EQP-0002 (TEST) is readable, with controls for ADMIN.
- EQP-0001 (REAL) shows the out-of-scope state (`role="status"`) and no controls.
- Mutation run:
  - TRANSFER to TEC-TEST-912 with an explicit choice, the exact body, and exactly one request despite a double click;
  - END (after the whole-second boundary);
  - the history retains TRANSFER and END (two table rows);
  - the exact replay of the TRANSFER (see §9).

## 12. Permanent responsible-driver acceptance

- VEH-1048 (TEST) shows the not-driving note and an empty state.
- VEH-1046 (REAL) shows the out-of-scope state.
- The legacy `/vehicle/VEH-1048/drivers` link is still present.
- No E2 text or request.
- Mutation run:
  - TRANSFER to an explicitly chosen DRV-TEST-901;
  - the vehicle shows DRV-TEST-901, linked to the driver page;
  - END;
  - the history retains both events;
  - the inactive driver DRV-TEST-903 is refused (unit-tested).

## 13. Driver → vehicles acceptance (both directions)

- DRV-TEST-901 has no current vehicle in a fresh backend; DRV-0001 (REAL) is out of scope.
- Mutation run: vehicle → driver page lists VEH-1048 → back to the vehicle. After END the reverse lookup is empty
  (checked by API and on the driver page).
- One driver with many vehicles is unit-tested.
- The panel shows current responsibilities only, which is all the endpoint returns. History is on each vehicle's page.

## 14. Department history limitations

- Read-only.
- Ids exactly as returned, with no name, no link and no department-detail read (the department master is
  operational-only).
- No move control.
- In mock TEST the history is always empty: no history seed, no role holds the move capability, and no department
  is in the server batch. Non-empty rendering is covered by Vitest with the API's real field schema.

## 15. Isolated browser-write evidence

- **Invocation:** `R2_C2A_MUTATION=1 npx playwright test e2e/r2-c2a-panels.spec.ts --project=desktop --workers=1 --grep @mutation`.
- **Isolation:**
  - Before and after every run, ports 4310 / 4311 were free and no backend or vite process existed.
  - The run started its own backend (`reuseExistingServer: false`) and Playwright ended it afterwards.
  - The read-only and regression invocations ran strictly one after another, never at the same time.
- **First test:** the backend is Mock/TEST (`/me` `data_context` is TEST), and the EQP-0002, VEH-1048 and
  PER-TEST-912 driver-link histories are empty.
- **Result on the final code:** **5 passed**.
- **Earlier attempts** during development, each on its own dedicated backend that then ended:
  - One stopped in the guard before any write.
  - One failed after a real TRANSFER, because its immediate END was correctly refused as the same whole-second
    instant. The test now waits past the second boundary.
- No history was cleared, truncated or rewritten.

## 16. Unit test results (executed)

| File | Tests |
|---|---|
| `r2HistoryWrites.test.ts` | 37 |
| `r2History.test.ts` | 13 |
| `TimelineEventDialog.test.tsx` | 9 |
| `CaretakerPanel.test.tsx` | 9 |
| `PersonnelLinksPanel.test.tsx` | 7 |
| `ResponsibleDriverPanel.test.tsx` | 7 |
| `TimelineHistoryTable.test.tsx` | 6 |
| `DepartmentHistoryPanel.test.tsx` | 5 |
| `DriverVehiclesPanel.test.tsx` | 4 |
| **New total** | **97 passed** (88 before §24) |

## 17. Frontend regression (executed on the final code)

| Check | Result |
|---|---|
| Full Vitest | **895 passed** (75 files) = 798 earlier + 97 new; 0 failed (886 before §24) |
| TypeScript (`tsc -p tsconfig.app.json`) | clean |
| Lint (`oxlint`) | exit 0; 31 warnings = baseline 31, none new |
| Production build (`npm run build`) | passed |
| Backend smoke (backend unchanged): R2f-a/b/c/d/e/f/g, P0, P0b, Option S tests | **495 passed** |

**Deliberately updated existing tests (2 of the 8 allowed):**
- `EquipmentDetailPage.test.tsx`: the page now also mounts the caretaker panel. Its own reads (caretaker timeline,
  technician list) are answered with valid empty data, and in the deferred-fetch test they are answered at once, so
  these status tests keep testing only the status flow. No assertion changed.
- `VehicleDetailPage.test.tsx`: in the GPS-failure test, the generic `/vehicles/VEH-1046` stub also matched the new
  panel's URL and produced a second retry button. The panel's own read gets a valid empty answer. No assertion
  changed.

**Bugs found and fixed during implementation:**
- Generated link-error messages had overridden the existing `DRIVER_NOT_FOUND` text. They are now ordered so
  existing messages always win; `labels.ts` is verified purely additive.
- A new settlement callback caused panels to re-read (now held in a ref).
- A relationships re-read unmounted the link sections (now keeps the last good data).
- A `datetime-local` ".000" fraction (now dropped when zero).
- The out-of-scope view used `role="alert"` (now `role="status"`, an expected, informational state).

## 18. Browser results (executed)

**Read-only R2-C2a spec:** 7 tests × 5 projects (smartphone portrait / landscape, tablet portrait / landscape,
desktop) = **35 passed**.

**Mutation R2-C2a spec:** **5 passed** (desktop, one worker, dedicated backend).

**Combined regression invocation** on the final read-only code: **350 passed, 0 failed**.

| Spec | Passed |
|---|---|
| r2-c2a-panels | 35 |
| responsive-shell | 20 |
| technician-v2-only | 15 |
| technician-v2 | 45 |
| technician-v2-withdrawal | 25 |
| vehicle-equipment | 30 |
| vehicle-registry-read | 35 |
| equipment-status-change | 25 |
| driver-phase6-batch1 | 20 |
| vehicle-branch-write | 20 |
| vehicle-registration-write | 35 |
| vehicle-registry-integration | 20 |
| equipment-search-completeness | 25 |

**Not run:** the full Playwright suite (28 specs) and the full backend suite. The backend code is unchanged.

## 19. Known limitations

- **Personnel picker.** There is no account-list endpoint: an account is linked by typing its `user_id`, and the
  backend proves it. The driver picker lists the (unscoped) driver master; the backend refuses an out-of-scope or
  inactive driver.
- **No reason text** in the department, caretaker and permanent-driver histories: the reads do not return one.
- **CONFLICT intents.** An intent in CONFLICT (`REQUEST_ID_REUSED`) has no in-app way to clear it, and none was
  added: no read shows which body was recorded under the id. It blocks new writes on that entity for that user in
  that browser. The panel tells the user to report the request id to an administrator. The recovery is a manual,
  authorized investigation of the history by request id, outside the app. This is practically unreachable with
  random UUIDs.
- **Settling timeline intents.** An uncertain caretaker or permanent-driver intent can be settled only through a
  proven record id: these reads carry no request id. The safe path is the explicit resend, which is answered as a
  replay (with record ids) or applied (with a record id). Either is then settled by the history read.
- **Unresolvable uncertain intents.** If the earlier attempt was not recorded and every resend is refused (for
  example the timeline changed meanwhile, which gives STALE), the intent stays UNKNOWN. It keeps blocking new
  writes on that entity for that user in that browser. The current API offers no authoritative proof that the
  earlier attempt was not recorded. The recovery is the same manual, authorized escalation as for CONFLICT.
- **Live Google Sheets:** the relationships read needs the `personnel_master.driver_id` column (deployment gate).
  Live TEST lists nothing (C1 §15).

## 20. Unverified items

- **"Not recorded" proof:** withdrawn in §24. No response is treated as proof any more.
- Settlement of a CANCELLATION by record id assumes the cancelled event's `head_record_id` is the cancellation
  record (not separately verified).
- Browser behaviour outside Chromium.
- The full Playwright suite.

## 21. Backend

No backend file, route, schema, authority, seed or Google Sheets code was modified.

## 22. Live Sheets and REAL data

No live Google Sheets access and no REAL data operation. Every browser write went to a dedicated, in-memory mock
(TEST) backend that ended with its run.

## 23. Next owner approval checkpoint

Owner review of the R2-C2a change set (28 paths) on `review/r2-c2a-frontend-relationships-history`. Then, each
separately authorized:
1. commit and push to the review branch;
2. fast-forward integration;
3. R2-C2b (E2 frontend);
4. R2-C3 legacy cutover.

## 24. Final pending-intent safety closure

**Scope:** a focused review of `r2HistoryWrites.ts` against the R2f backend replay contracts and against
`registryPending.ts`. `registryPending.ts` and the backend are unchanged.

**Finding C (defect, corrected).** After an uncertain attempt, the classifier removed the intent as "not recorded"
in two cases:
- a refusal on the family's POST_REPLAY list;
- a no-op.

That proof did not hold, as the backend source shows:
- `record_event` reads the history once (`equipment_caretaker.py` `ctx = await self._read(...)`, then
  `self._replay(ctx, ...)`). The same pattern applies to responsibility and links.
- It then checks and appends, and no write lock exists.
- So an earlier attempt still running on the server (for example after a client timeout) can append after the
  resend's read. The resend is then refused, for example as STALE, although the earlier attempt is recorded.

Correction, in `r2HistoryWrites.ts` only:
- after an uncertainty, every refusal and every no-op keeps the intent as UNKNOWN, as `registryPending.ts` does;
- the message says the refusal does not prove the earlier attempt was not recorded;
- the `not-recorded` result kind, its message and the `postReplay` family field were removed;
- the POST_REPLAY code lists still confirm a first attempt's zero-write.

**Finding A (gap, corrected).** CONFLICT was already never resent, never given a new id, and kept with a message.
Two gaps were closed:
1. `settleR2Intent` could settle a CONFLICT. For a link family that happened through a history event carrying the
   same id, and that event may carry a different body. A CONFLICT is now never settled.
2. After a reload, the pending banner showed only "รหัสคำขอขัดแย้ง". It now also states the escalation: report the
   request id to an administrator. This is the `TimelineEventDialog.tsx` `R2WriteNotice`, an existing R2-C2a file.

No clear-conflict control was added. The recovery path is documented in §19: a manual, authorized investigation.

**Finding B (already safe; now tested for both families).**
- An uncertain caretaker or permanent-driver intent keeps its id and serialized body.
- It is resent only by the user, with the same id, path and body.
- A replay (`replayed: true`, `record_ids`) only asks for settlement. The intent is removed only when the
  authoritative timeline read shows that record id.
- No `request_id` field is assumed in the timeline reads.

**Tests added or changed (deliberate behaviour change, not to make tests pass)**

`r2HistoryWrites.test.ts`:
- post-replay refusals of all families stay UNKNOWN with the refusal reported;
- arbitrary 4xx, unknown codes and a no-op after an uncertainty are kept;
- REUSED after an uncertainty stays CONFLICT;
- a refused resend keeps the same id and body and blocks new writes;
- a CONFLICT is never resent, gets no new id, and is never settled by a timeline or link read;
- the orphaned-SUBMITTING resend no-op is now kept;
- for caretaker and responsibility, against a fake append-only backend:
  - recorded, then response lost: the resend is replayed, settled only by the history, and there is no second
    history event;
  - not recorded, then response lost: the resend records it once and is settled by its record id;
  - a refused resend never clears the intent and never appends.

`CaretakerPanel.test.tsx`: a refused resend keeps the intent, keeps the same id, and explains why.

`ResponsibleDriverPanel.test.tsx`:
- unknown, then resend with the same id and body, then replay, settled by the history read;
- the CONFLICT escalation text is shown.

**Executed after the correction**

| Check | Result |
|---|---|
| Focused tests: pending intent plus the three write panels | 60 passed |
| Full Vitest | 895 passed (75 files), 0 failed |
| TypeScript | clean |
| `oxlint` | exit 0; 31 warnings = baseline |
| Production build | passed |
| Playwright `r2-c2a-panels`, read-only (5 projects) | 35 passed |
| Playwright `r2-c2a-panels`, `@mutation` (isolated, desktop, 1 worker) | 5 passed |
| `git diff --check` | clean |

The mutation run includes a real exact replay: the same id and body return `replayed: true`, and the caretaker
history count stays at 2, so no duplicate audit history is written.

**Not re-run after the correction:** the combined 13-spec Playwright regression (350 before) and the backend smoke
(495 before; the backend is unchanged). The changed files are used only by the R2-C2a panels.

**Accepted limitations:**
- a CONFLICT intent and an uncertain intent whose every resend is refused stay pending (fail closed) until a manual,
  authorized investigation;
- the intent lives in one browser's localStorage, which is not a security boundary.
