# Web/API Phase 7 — Batch 7M1 — Vehicle-List Link Safety and Recorded-Findings Wording — Batch Result

BATCH: Phase 7 Batch 7M1 (bounded correction of remaining-work items A-1 / G11 and A-2 / G12 from `web-phase-07-partial-result.md`)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7m1-vehicle-list-links-wording` (local), based on
`e71991c259fe924ce1d924a91245e30bb6cb2dce` (equal to
`web/phase7-dashboard-search-reporting` at preflight).

Out of scope, and unchanged:
- finding closure;
- downstream identifier repair (A-3, A-4);
- authorization (M02);
- business-definition decisions (group C);
- Phase 7 closure.

## 1. Trace (before editing)

- **Vehicle-list links** (`VehicleListPage.tsx` at `e71991c`):
  - the vehicle-id cell (`/vehicle/${vehicle_id}`, line 426);
  - the repair, PM and findings indicator badges (`/vehicle/${id}/repairs`, `/pm` and `/inspections`, lines 328-330).

  Both interpolated the id verbatim. Desktop and mobile layouts share one
  table DOM (`ResponsiveTable`; CSS restyles it on narrow screens), so these
  are the only link locations.
- **Destinations** read the decoded `:vehicleId` route parameter and
  interpolate it into API paths without encoding:
  - `VehicleDetailPage` (`/vehicles/${vehicleId}`, status history, PATCH);
  - `RepairHistoryPage`, `PmStatusPage` and `InspectionHistoryPage` (`asset_id=${assetId}` in query strings).

  URL encoding alone would therefore not be safe, so ineligible ids get no
  link.
- **Existing rule:** `isLinkableVehicleId` (`lib/certificateReportLinks.ts`,
  7D2), with tests in `certificateReportLinks.test.ts`. It accepts only ids
  made entirely of ASCII unreserved characters `A-Z a-z 0-9 . _ ~ -`,
  excluding "." and "..". The rule is reused unchanged (it was already
  reused by the 7E2 and 7F2 link helpers).
- **Findings wording** "ข้อบกพร่องที่ค้าง" ("outstanding defects") appeared in:
  - the category label (zero, unknown and failed lines);
  - the all-zero line;
  - the summary note.

  The counts come from the legacy `GET /findings?asset_type=VEHICLE&status=OPEN`
  list. No closure lifecycle exists, so these are recorded findings, not
  outstanding ones.

## 2. Behavior

| Case | Vehicle-id cell | Indicator badges |
| --- | --- | --- |
| Id accepted by `isLinkableVehicleId` (e.g. `VEH-1046`, `0012`, `a.b_c~d`, `...`) | link to `/vehicle/<id>` (unchanged) | links to `/vehicle/<id>/repairs`, `/pm`, `/inspections` (unchanged) |
| Id rejected (e.g. `VEH/1`, `VEH?1`, `VEH#1`, `VEH%201`, `%2E%2E`, `.`, `..`, `VEH 1`, leading/trailing whitespace, tab, `รถ-1`, `Café`, blank) | stored text exactly as received (whitespace preserved visually) plus "(ไม่มีลิงก์: ใช้รหัสนี้เปิดหน้าข้อมูลรถไม่ได้ เพราะมีอักขระที่ยังรองรับไม่ได้)" | same badge text and counts, without links |

- Ids are not trimmed, normalized, encoded or otherwise changed. API
  requests and destination pages are unchanged.
- An accepted id is placed into the path verbatim. This does not guarantee
  that the vehicle exists or that its page loads.

Wording changes (vehicle list only):

| Where | Before | After |
| --- | --- | --- |
| Category label (zero line "ไม่พบ…", unknown line "ยังไม่ทราบจำนวน: …", failed line "…: โหลดข้อมูลไม่สำเร็จ") | ข้อบกพร่องที่ค้าง | ข้อบกพร่องที่บันทึกไว้ |
| All-zero line | ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่ค้าง | ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่บันทึกไว้ |
| Summary note | …และข้อบกพร่องที่ค้าง | …และข้อบกพร่องที่บันทึกไว้ในระบบ ข้อบกพร่องที่บันทึกไว้ไม่ได้บอกว่าแก้ไขแล้วหรือยัง และการไม่พบรายการไม่ได้ยืนยันว่าไม่มีข้อบกพร่อง … |

- **Badge** "ข้อบกพร่อง N": reviewed and kept. It states a count without
  implying an unresolved state.
- **Accessible names:** the links' accessible names are their visible text;
  no separate tooltips or aria-labels exist.
- **Unchanged behavior:**
  - counts;
  - the `/findings` request;
  - filters, ordering and paging;
  - unknown/failed handling (a failed or truncated category is still never shown as zero);
  - the retry button.
- **Not fixed by this batch:** the legacy `/findings` read keeps its
  false-empty limitation (7E2 §10). A zero is still not proof that no
  defects exist, and the note now says so. The 7E2 report is unchanged.

## 3. Changed files

- **New:**
  - `frontend/e2e/vehicle-list-links-wording.spec.ts`;
  - this report.
- **Modified:**
  - `frontend/src/pages/VehicleListPage.tsx`;
  - `frontend/src/pages/VehicleListPage.test.tsx` — three new tests, plus the six existing assertion strings updated to the new wording;
  - `frontend/src/index.css` — three new scoped selectors `.vehicle-list__id*`; no existing rule changed;
  - `frontend/e2e/vehicle-search-partial-states.spec.ts` — one zero-wording string updated so its negative check stays meaningful;
  - `CHANGELOG.md`;
  - `docs/phase-results/web-phase-07-partial-result.md` — A-1/A-2 marked addressed; matrix A3/X1 and next-step lines updated.
- **CHANGELOG provenance:** the 7L1 CHANGELOG heading now names its
  integration commit `e71991c`, following the 7L1 convention.
- **Unchanged:**
  - `isLinkableVehicleId` and its tests;
  - destination pages;
  - API client;
  - backend;
  - dependencies, lockfiles and configuration.

## 4. Verification

### 4.1 Baseline demonstration (fresh)

- **Unit:** the three new unit tests were added first and run against the
  unchanged `e71991c` page. Two failed as expected:
  - rejected ids had no stored-text rendering;
  - the new wording was absent.

  The safe-id preservation test passed, as intended: accepted-id behavior
  must not change.
- **E2e:** the new e2e spec was run against an export of `e71991c` (shared
  `node_modules` and backend venv; `pip freeze` unchanged). All 20 failed
  (4 tests × 5 projects).

### 4.2 Final candidate (fresh, 2026-10-01)

Environment: Linux, Node v22.22.2, Playwright 1.63.0, Chromium only, mock backend.

| Command | Result | Exit |
| --- | --- | --- |
| `./scripts/run_frontend_tests.sh` | 47 files, 377 tests passed (374 + 3 new) | 0 |
| `npm run build` | built (existing chunk-size advisory only) | 0 |
| `npm run lint` | 33 warnings — line-for-line identical to the 7L1 baseline; no new warnings | 0 |
| `npx playwright test --list` | 450 tests in 18 files (430 + 20 new) | 0 |
| `./scripts/run_e2e_tests.sh` (complete suite, repository configuration, 2 workers) | 450 passed, 0 failed/flaky/skipped | 0 |

- **Hashes:** candidate code hashes and git status were identical before
  and after the runs.
- **Shared CSS:** only new selectors were added. The complete suite covers
  the report and layout specs that share the stylesheet.
- **Backend suite:** not rerun, because no backend file changed.

### 4.3 Development attempts (preserved in the evidence)

Two failures during development were caused by test-side text matchers, not
by the page. Both were fixed in the tests:
- **Unit:** a `/ไม่พบ.*ข้อบกพร่อง/` regex also matched the new explanatory
  note. It was anchored to lines that start with "ไม่พบ".
- **E2e:** Playwright's regex text match selected the whole table cell. That
  cell's combined text starts with a repair/PM zero line and contains the
  findings unknown line. The check now targets `.vehicle-indicators__none`
  elements.

### 4.4 Historical (not rerun here)

The 7L1 integrated results at `5275b8f` (backend 2135, frontend 374,
Playwright 430) are historical and recorded in the Phase 7 PARTIAL report.

Not performed: live Google Sheets, Windows, other browser engines, realistic
data volumes.

## 5. Remaining limitations

- Accepted ids are not proof that the destination exists or loads. Legacy
  `get_vehicle` callers on vehicle subpages remain (A-3 / G10).
- Downstream identifier handling (A-4), the certificate page's write-on-read
  (A-5), and authorization gaps (M02) are unchanged.
- Recorded-findings counts still come from the legacy `/findings` read,
  with no structural check. Its false-empty risk remains, and a zero is not
  proof that no defects exist.
- Whether live vehicle ids contain characters the rule rejects is
  unverified (B-5). Such vehicles are now listed without links rather than
  with broken ones.

Phase 7 remains **PARTIAL**.
