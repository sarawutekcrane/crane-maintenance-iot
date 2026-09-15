# WEB UAT DEFECT FIX

Targeted correction of the three concrete defects discovered during the
Web UAT session (`WEB UAT PASS WITH KNOWN ISSUES`, operational decision
`FIX BEFORE GOOGLE SHEETS TEST-COPY UAT`). This is not a redesign — no
accepted system (Repair Request → Repair conversion, provenance
encoding/decoding, attachment purpose/source authorization, Repair/PM
assignment history authority, Waiting Assignment, My Work, F1/F2/F3/F5/F6
integration fixes, CORE-G01, vehicle/component identity) was touched
beyond the additive changes described below.

## UAT-F1 (HIGH) — Inspection Finding source lost on Repair Request submission

**Status: RESOLVED**

**Root cause**: `RepairCreatePage.tsx`'s `submit()` function, in the
`useRepairRequestFlow` branch (reached by any actor without
`can_manage_repair` — i.e. exactly DRIVER/TECHNICIAN, the roles that
normally discover a defect during an Inspection), posted only
`{ vehicle_id, symptom_th }` to `POST /repair-requests`, even though the
page already read and displayed `source_type`/`source_id` from the URL
query string (the "รายการนี้เชื่อมโยงมาจาก..." banner). The backend's
`SubmitRepairRequestRequest` schema and `RepairRequestService` already
fully supported and validated these fields — confirmed working correctly
on the sibling PM-defect path (`PmWorkOrderDetailPage.tsx`) which always
forwarded them.

**Fix**: forward `source_type`/`source_id` on the Repair-Request POST
whenever the page is in the locked-source state for one of the two
backend-approved defect source types (`FINDING`, `PM_RESULT` — mirrors
`REPAIR_REQUEST_DEFECT_SOURCE_TYPES` in
`app/domain/repair_request.py`), else sends `null`/`null` exactly as
before. No backend change was required for this half of the fix — the
contract already existed and is backend-authoritative
(`RepairRequestService._require_defect_source_exists` still validates
the source is real; a spoofed/nonexistent Finding/PM Result is still
rejected with `REPAIR_REQUEST_SOURCE_NOT_FOUND`).

**Regression coverage**:
- `frontend/src/pages/RepairCreatePage.test.tsx` — new: a TECHNICIAN-shaped
  actor reaching this page from a Finding link now sends
  `source_type: 'FINDING', source_id: 'FND-0001'`; a plain manual report
  (no query params) still sends `null`/`null`.
- `frontend/e2e/web-uat-defect-fix.spec.ts` — new, real browser: Inspection
  → Finding → click "แจ้งซ่อม" → submit as a TECHNICIAN → open the
  resulting Request's own detail page → reload → source remains
  `ข้อบกพร่องจากการตรวจเช็ค (FND-...)`. This is the scenario the original
  E2E suite's own Finding test (`pm-repair.spec.ts`, "a Finding on an
  inspection can link to a new repair...") did **not** cover, because it
  runs as the default ADMIN dev-user (`can_manage_repair`), which never
  goes through the Repair-Request flow at all.
- `backend/tests/test_defect_provenance.py` (pre-existing, unmodified) —
  already proved the backend contract this fix now actually uses.

## UAT-F2 (MEDIUM) — Reporter cannot re-open their own submitted Repair Request

**Status: RESOLVED**

**Audit finding**: `GET /repair-requests/{repair_request_id}` already had
no ownership/capability check at all (M02 read-governance remains
explicitly open — see Known Items). So the backend already permitted a
reporter to read their own Request by ID; the only gap was UI
discoverability — there was no page to view one, and no list a reporter
could browse to find the ID.

**Fix** (uses only existing/extended read permissions, decides nothing
about M02):
- New read-only page `RepairRequestDetailPage.tsx` at
  `/repair-requests/:repairRequestId`, calling the existing,
  already-unrestricted `GET /repair-requests/{id}`. Links to the
  converted Repair once one exists.
- The Repair-Request submission success screen now links directly to
  this detail page.
- New backend endpoint `GET /repair-requests/mine` — every Repair
  Request the current actor reported, any status. Requires
  `can_report_repair` (the same capability needed to create one) and is
  **strictly narrower** than the pre-existing unrestricted single-ID
  `GET`: it always filters to `reported_by_user_id == context.user_id`.
  This is additive read surface, not an expansion of what was already
  readable, and it makes no new decision about M02's broader
  DEPARTMENT/ALL-scope question.
- `MyWorkPage.tsx` ("งานของฉัน") gained a third, existing-pattern section
  ("คำขอแจ้งซ่อมของฉัน") listing these, satisfying the master test plan's
  preferred option ("submitted request appears in an existing
  list/history suitable for the reporter") rather than inventing a new
  screen.

**Regression coverage**:
- `backend/tests/test_web_uat_defect_fix.py` — `GET /repair-requests/mine`
  scoping (own rows only, both PENDING/CONVERTED, empty for a reporter
  who never submitted, 403 without `can_report_repair`).
- `frontend/src/pages/RepairRequestDetailPage.test.tsx`,
  `frontend/src/pages/MyWorkPage.test.tsx` (extended) — new unit coverage.
- `frontend/e2e/web-uat-defect-fix.spec.ts` — new, real browser: a DRIVER
  submits, navigates all the way away (home), returns via the normal
  "งานของฉัน" nav route, finds their request, opens it, reloads — status
  and symptom persist throughout.

## UAT-F3 (MEDIUM) — PM-defect "already reported" was client-only state

**Status: RESOLVED** (extended to the Inspection-Finding path per
section 15 — see below)

**Root cause**: `PmWorkOrderDetailPage.tsx` tracked "already reported"
in a local `defectSubmitted: Record<string, string>` React state,
populated only by the success handler of the POST that created it.
Reloading the page (or leaving and returning) reset this to empty even
though the Repair Request still existed server-side, and the "แจ้งซ่อม
(พบข้อบกพร่องระหว่าง PM)" button would reappear, inviting a duplicate
report for the same PM defect.

**Fix — derived from persisted data, no new flag/table**: new backend
endpoint `GET /repair-requests/by-source/{source_type}/{source_id}`
(mirrors `GET /attachments/by-source/...`'s existing shape), returning
every Repair Request whose *decoded* provenance
(`app.domain.repair_request.decode_provenance_note` — the one existing,
centrally-parsed mechanism; no repository schema change) matches. Backed
by two new repository methods,
`list_repair_requests_by_reporter`/`list_repair_requests_by_source`
(mock + Google Sheets), mirroring the existing `find_repairs_by_source`
precedent for Repairs. `PmWorkOrderDetailPage.tsx`'s `load()` now
queries this for every recorded task result on every load (mount,
reload, and after a successful report), replacing `defectSubmitted`
entirely with `existingDefectRequestsByResult` derived from the response.

**Section 15 — extended to Finding, since the identical mechanism now
exists**: `RepairCreatePage.tsx`'s Repair-Request flow, when reached with
a locked `FINDING`/`PM_RESULT` source, now checks
`GET /repair-requests/by-source/...` before showing the submission form.
If a Request already exists for that exact source, the page shows an
"already reported" card (linking to the existing Request, via UAT-F2's
new detail page) instead of a fresh form — deriving the same
one-report-per-defect-source UX as the PM path, from the same persisted
data, with no separate governance decision required (the mechanism and
its authorization level are identical to the already-implemented
PM-side check).

**Backend duplicate prevention — audited, not added**: `POST
/repair-requests` itself does **not** reject a second submission for the
same `source_type`/`source_id` at the API level; only the UI now avoids
offering the option once one exists. This is a conscious choice, not an
oversight: the master test plan explicitly asks to report rather than
invent a new business rule "unless current architecture already clearly
defines one Request per PM_RESULT/FINDING" — no such rule is defined
anywhere in the accepted REV05/REV06 design, and a backend-level guard
would be a real, independent business-rule decision (does a second
report ever legitimately make sense — e.g., a worsening defect, a
different reporter noticing the same fault independently?) that this
targeted defect-fix task should not make unilaterally. **Recorded as an
open follow-up, not silently decided.**

**Regression coverage**:
- `backend/tests/test_web_uat_defect_fix.py` — by-source lookup for both
  `FINDING` and `PM_RESULT`, empty-when-none, no cross-match on a
  different `source_id`, a `MANUAL` (un-sourced) request never
  spuriously matches, 403 without `can_report_repair`.
- `frontend/src/pages/PmWorkOrderDetailPage.test.tsx` (updated),
  `frontend/src/pages/RepairCreatePage.test.tsx` (new case) — unit
  coverage of the derived "already reported" UI state.
- `frontend/e2e/web-uat-defect-fix.spec.ts` — new, real browser: report a
  PM defect, leave the page entirely (not just reload in place), return
  — "แจ้งซ่อมแล้ว" and the link to the existing Request are still shown,
  and the report button does not reappear; a further `page.reload()`
  confirms the same.

## Source/Manual/PM Matrix (unchanged contract, now correctly reached)

| Flow | source_type | source_id |
|---|---|---|
| Manual report | `null` | `null` |
| Inspection defect (Finding) | `FINDING` | `finding_id` |
| PM defect | `PM_RESULT` | `pm_work_result_id` |

## Test Baseline

| Suite | Before | After |
|---|---|---|
| Backend (`pytest`) | 483 passed | **493 passed** (+10 new, 0 regressed) |
| Frontend typecheck (`tsc -b`) | PASS | PASS |
| Frontend lint (`oxlint`) | PASS (pre-existing warnings only) | PASS (unchanged) |
| Frontend unit (`vitest`) | 66 passed | **71 passed** (+5 new, 0 regressed) |
| Frontend build (`vite build`) | PASS | PASS |
| E2E (`playwright test`, 5 viewport projects) | 145 passed | **160 passed** (+15 new = 3 new specs × 5 viewports, 0 regressed) |

## Remaining Known Issues (unchanged / explicitly out of scope here)

- F4/M02 read-access governance remains open — this fix deliberately
  adds no new final data-access policy (UAT-F2's `/mine` endpoint is
  strictly narrower than the pre-existing unrestricted single-ID `GET`;
  UAT-F3's `/by-source/...` endpoint is gated by `can_report_repair`,
  the same capability already required to create a Repair Request).
- No backend-level duplicate-submission guard for the same
  Finding/PM Result source (see UAT-F3 above) — a real, independent
  business-rule decision, left open rather than invented.
- The "known LOW UX debt" items observed during UAT (work controls
  visible to an unassigned technician before a correct backend
  rejection; a CLOSED PM Work Order's task-result form remaining
  visible for incomplete tasks) are unrelated to UAT-F1/F2/F3 and were
  intentionally left untouched per this task's scope.
- Live Google Sheets acceptance remains `PENDING` — this session ran
  entirely against `DATA_REPOSITORY=mock`; the new
  `list_repair_requests_by_reporter`/`list_repair_requests_by_source`
  repository methods were also implemented for the Google Sheets
  adapter (same `read_rows` + decode-and-filter pattern as
  `list_pending_repair_requests`) but were exercised only through the
  mock repository's unit/integration tests in this session, per the
  explicit instruction not to start Google Sheets UAT here.
