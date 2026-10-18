# R2-C4 — Final Acceptance Corrections — Result

Status: **IMPLEMENTED AND TESTED — PASS** on the local review branch `review/r2-c4-final-acceptance`, created from
the integration baseline. The implementation and testing stage created no commit, push, merge or deployment.
**R2 is not declared accepted here:** final owner acceptance is a separate decision after integration and evidence
review.

## 1. Baseline and authority

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `19a9a3d66a6c00c71663959a7c49f1e413a46041` (R2-C3 integrated) |
| Acceptance matrix | REV5 `R2_Temporary_Driver_Contract_Amendment_REV5_OWNER_REVIEW_DRAFT.txt` (owner-supplied, not in the repository), SHA-256 `f15415d63936539546723c75dbb421e64edce7e8ba6e2d90cd9de7177a03dc35`; the hash matches the one cited in `r2-c1-e2-backend-result.md` |
| Governance | `c1-amendment-a2-driver-responsibility.md` (A2-10 carries B01–B30 into R2-C4) |
| Plan | R2-C4 read-only preflight; owner decisions D1–D6 |

## 2. Corrections completed

| Item | Change | File |
|---|---|---|
| B02 (REV5 A6.3) | The no-permanent-driver warning now starts with the exact text **"ยังไม่ได้กำหนดผู้รับผิดชอบประจำรถ"** and keeps the existing explanation that it is a warning only and never blocks saving | `frontend/src/lib/labels.ts` |
| B06 (REV5 A3.5) | **"ยังไม่ได้ระบุผู้ได้รับมอบหมาย"** (with the shift and date) appears only when all of the following hold: one Bangkok date (`from === to`); DAY_SHIFT or NIGHT_SHIFT; a loaded, scope-proven, VALID schedule; no UNKNOWN span; no conflict on that date; no unit of that shift labelled with that date. Nothing is inferred from permanent responsibility, and there is no new backend field. | `E2VehicleAssignmentsPanel.tsx`, `labels.ts` (`E2_UNASSIGNED_SHIFT`) |
| B29 | The shared E2 note (Vehicle and Driver panels) now reads "เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง — ระบบ E2 แสดงผู้ขับที่ได้รับมอบหมายเท่านั้น ไม่มีข้อมูลยืนยันผู้ขับจริง" | `labels.ts` (`E2_NOTE`) |
| B25 / B26 | Frontend tests prove both warning codes render, and that the assignment and its history stay | `E2VehicleAssignmentsPanel.test.tsx` |
| Deferred cleanup | `VEHICLE_DRIVER_ASSIGNMENT_NOT_FOUND` removed. A repository-wide check found no consumer: the only reference was the label itself; historical documents are unchanged. | `labels.ts` |
| Browser evidence | The shared note constant is updated, and one read-only B06 check runs in 5 viewports | `frontend/e2e/r2-c2b-e2-panels.spec.ts` |

Changed files: 4 modified (`labels.ts`, `E2VehicleAssignmentsPanel.tsx`, `E2VehicleAssignmentsPanel.test.tsx`,
`r2-c2b-e2-panels.spec.ts`) plus this document; +189 / −4 lines. E2 write semantics, backend, R2-C2a and the
historical R2-C1 result document are unchanged.

## 3. Test results (executed on the final code)

| Check | Result |
|---|---|
| Focused Vitest `E2VehicleAssignmentsPanel.test.tsx` | **21 passed**: 13 existing + 8 new. The new tests cover B02, B29, B25/B26, B06 positive (including a previous-day night unit that does not count), B06 with an assigned shift, and B06 negatives (several dates, all modes, FULL_DAY, UNKNOWN, CONFLICTED, conflict on the date, read failure 503, out-of-scope 422, pending read) |
| Full frontend Vitest | **974 passed** (80 files) = 966 + 8 |
| TypeScript (`tsc -b`) | clean |
| Lint (`oxlint`) | exit 0; 30 warnings = the R2-C3 figure, none new |
| Production build | passed |
| Playwright read-only, 5 viewports: `r2-c2a-panels`, `r2-c2b-e2-panels`, `driver-phase6-batch1` | **75 passed** (35 + 30 + 10) |
| Playwright `r2-c2b-e2-panels` `@mutation`, isolated fresh backend | **5 passed** (re-run because one assertion reads the B02 warning text) |

**Not re-run, with reasons:**
- **R2-C2a mutation run:** no R2-C2a code or asserted text changed.
- **Full combined 14-spec regression:** the change is confined to the E2 panel and E2 labels, and every spec that renders them was run.
- **Backend suite:** there is no backend change. The R2-C3 figure of 4898 passed still applies.

## 4. B01–B30 acceptance matrix (final evidence)

| B | REV5 requirement (short) | Evidence | Status |
|---|---|---|---|
| B01 | Permanent change on V1 leaves V2 unaffected | backend `test_b01_*` | PASS |
| B02 | No permanent driver: warn but save, with the A6.3 wording | backend `test_b02_*`; R2-C4 Vitest (exact wording, non-blocking); R2-C2b mutation run (warning on CREATE) | PASS |
| B03 | No automatic daily E2; no verified-driver claim | backend `test_b03_*`; E2 note | PASS |
| B04–B05 | Day and night shifts on the same date, different drivers | backend `test_b04_*`, `test_b05_*` | PASS |
| B06 | Unassigned shift clearly labelled; never filled from the permanent driver | backend `test_b06_*` (no autofill); R2-C4 Vitest (positive and negative cases); Playwright B06 check (5 viewports) | PASS |
| B07–B14 | Transitions, H2 and H3 handovers, overlap refusals | backend `test_b07`–`test_b14_*`; R2-C2b mutation run (H2) | PASS |
| B15 | Adjacency warning, not a safety approval | backend `test_b15_*`; frontend label | PASS |
| B16–B19 | Simultaneous refusal, split, atomic refusal, whole-shift substitution | backend tests; R2-C2b mutation run (split, substitute) | PASS |
| B20 | No mid-shift handover | backend `test_b20_*` | PASS (out of scope, enforced) |
| B21–B23 | Cancellation with audit; cancel before/after a handover; UNKNOWN | backend tests; R2-C2b Vitest and mutation run | PASS |
| B24 | Back-dated correction with a reason | backend `test_b24_*`; frontend back-dated reason rule | PASS |
| B25 | Future-inactive driver retained and flagged | backend `test_b25_*`; R2-C4 Vitest | PASS |
| B26 | Current-inactive driver retained, flagged, needs action | backend `test_b26_*`; R2-C4 Vitest | PASS |
| B27 | Duplicate shows the existing one; exact replay | backend `test_b27_*`; R2-C2b mutation run | PASS |
| **B28** | Production concurrency: one winner | backend `test_b28_*` proves **one mock process only** | **DEFERRED to R11** |
| B29 | Search by vehicle, time and driver; permanent vs assigned vs verified actual (unavailable) | backend `test_b29_*`; per-vehicle and per-driver range filters; separate panels; R2-C4 note (B29 Vitest) | PASS (fleet-wide date-only search outside the approved scope, D4) |
| B30 | Safe cutover | R2-C3 backend and browser cutover tests; `_CORE_SCHEMAS`; OpenAPI | PASS |

Totals: **29 PASS, 1 DEFERRED (B28 → R11), 0 BLOCKED, 0 UNVERIFIED.**

## 5. Acceptance restrictions and remaining risks

- **B28 is DEFERRED to R11.** The mock version guard is a single-process guarantee, not production atomicity.
- **E2 REAL and production operations remain unavailable before R11.** REAL writes are refused (409), Google Sheets mode answers 501, and no REAL or production E2 use is approved.
- **External consumers of the retired legacy APIs remain UNVERIFIED** and must be investigated (for example production access logs) before any deployment.
- **Pending UNKNOWN / CONFLICT requests** may require an authorized manual investigation (by design: they fail closed).
- **Fleet-wide date-only search** remains outside the approved R2 scope; per-vehicle and per-driver range search only.
- **Not run:** the full Playwright suite (all specs) and browsers other than Chromium.
- **Future phases:** B7 readiness, D5 and H3 (A2-10), and R3, which is next after R2.

## 6. Live Sheets and REAL data

No live Google Sheets access and no REAL data operation; all browser runs used dedicated in-memory Mock/TEST
backends.

## 7. Next owner checkpoints

Each separately authorized:
1. Commit and push of this change set to `review/r2-c4-final-acceptance`.
2. Fast-forward integration.
3. Owner review of the integrated evidence and the formal R2 final acceptance decision.
