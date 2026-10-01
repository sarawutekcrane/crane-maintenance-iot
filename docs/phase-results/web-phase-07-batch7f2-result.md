# Web/API Phase 7 — Batch 7F2 — Equipment Search Completeness — Batch Result

BATCH: Phase 7 Batch 7F2 (option N1 of the 7F1 audit: the existing
`/equipment` page only)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**

> **7L1 reconciliation note (2026-10-01).** This batch was committed as
> `07205fd257e480b9a1b94e770a176773a01acc82` and is integrated on `web/phase7-dashboard-search-reporting`
> (checked at `5275b8f9708b54baf1f20cab09282c3395f7adb8`). The BATCH STATUS
> above is the historical status at review time and is kept as written;
> the "WHOLE PHASE 7 STATUS" paragraph lists what remained at that time.
> Verification results in this report are historical runs on the
> uncommitted candidate, not 7L1 runs. Fresh integrated results, the
> current coverage and remaining work are in
> `docs/phase-results/web-phase-07-partial-result.md`. Phase 7 remains
> **PARTIAL**.

WHOLE PHASE 7 STATUS: **PARTIAL** (this batch completes access to the
existing equipment search results only; it closes no open decision and
does not complete the Phase 7 search/report list)

Branch: `review/phase7-batch7f2-equipment-search-completeness`, based on
`eef6a0913855d4c047dbbbab6036927bed5c3a66` (equal to
`web/phase7-dashboard-search-reporting` at preflight).

Design input: the reviewed audit
`Phase7_Batch7F1_Remaining_Search_Contract_Review_Evidence_Corrected.txt`
(SHA-256 `252e35491ee8b63ba0dee04ac9a65a13eaa5b900fd8c6381e4975c8d57c4da96`,
126744 bytes, 2439 lines), findings G-E1–G-E5 and option N1. Its
stored-alert contract is not part of this batch.

## 1. Approved scope and what it does not approve

Approved (N1): complete access to paginated equipment search results,
accurate totals and applied-filter disclosure, draft/applied separation,
stale-response protection, loading/error/empty/out-of-range states and
conservative equipment-detail links, including the narrowly scoped change
to the page's previous interaction (the category select no longer searches
on change).

Not approved by this batch: "type = model" as the Phase 7 interpretation
(DEC-T), DEC-AL0–AL5 or any stored-alert report, vehicle-search hardening
(N2), PM/offline/location/lifecycle/authorization changes, whole-Phase-7
closure, Phase 8.

## 2. Traceability to the 7F1 findings

| Finding | Before | After (where) |
| --- | --- | --- |
| G-E1 page_size 50, items only | metadata ignored | `page`, `page_size`, `total_items` drive range, totals and pager (`EquipmentListPage.tsx` `renderResults`) |
| G-E2 no pager / no "more rows" disclosure | silent truncation after 50 | "พบ {n} รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ {first}–{last} จาก {total} รายการ", "หน้า {page} จาก {pages}", "ก่อนหน้า"/"ถัดไป" (disabled at the ends) |
| G-E3 no generation guard | older response could overwrite newer | `generation` ref; only the latest request's success or error is applied, atomically, with the request that produced it |
| G-E4 draft/applied mixing | category change and retry used the unsent text box | draft vs applied request; "ค้นหา" applies q + category from page 1; paging/retry/"กลับไปหน้าแรก" reuse the applied request; "ล้างตัวกรอง" clears both and requests unfiltered page 1 |
| G-E5 unguarded detail link | `/equipment/${id}` for any id | `equipmentDetailLink` (unchanged 7D2 rule); unsafe/blank/in-page-duplicate ids keep their text with a Thai reason and no link |

## 3. Changed files

Added: `frontend/src/lib/equipmentListLinks.ts`,
`frontend/src/lib/equipmentListLinks.test.ts`,
`frontend/e2e/equipment-search-completeness.spec.ts`, this report.

Modified: `frontend/src/pages/EquipmentListPage.tsx` (rewritten in place;
title, route, intro text, category codes/labels and columns preserved),
`frontend/src/pages/EquipmentListPage.test.tsx` (the existing test is kept
unchanged; new cases appended), `frontend/src/index.css` (one scoped
`equipment-list__*` block appended; no existing rule changed),
`CHANGELOG.md` (one entry prepended).

Unchanged: backend, `GET /api/v1/equipment` contract, `lib/types.ts`,
`apiClient`, `App.tsx`, `NavBar`, `ResponsiveTable` and other shared
components, `certificateReportLinks.ts` behavior, existing e2e specs, seed
data, dependencies, lockfiles, configs, governance, earlier reports.

## 4. Reused API and link policy

- `GET /api/v1/equipment?page=&page_size=50[&q=][&category=]` — the backend
  filters the whole population, orders by `equipment_id` and returns
  `total_items` before slicing (mock and Sheets repositories). The page
  never filters/sorts a page client-side, never fetches all pages and never
  issues per-row requests. `q` is trimmed before sending (as before).
- Links: `equipmentDetailLink(id)` = the unchanged 7D2 `isLinkableVehicleId`
  (whole original id matches `^[A-Za-z0-9._~-]+$`, not "." or ".."), placed
  verbatim. `EquipmentDetailPage` interpolates the decoded route parameter
  into its API paths, so ids with "/", "\", "%", "?", "#", whitespace or
  non-ASCII characters get no link. Ids repeated within the returned page
  get no link (duplicates on other pages are not detected). Rows are keyed
  by position, never by id. A permitted link does not guarantee that the
  destination exists or loads; no lookup verifies it.
- Totals count equipment records returned by the backend — not vehicles,
  and not verified unique assets (shown on the page).

## 5. States

Loading and error hide the previous rows, totals, criteria echo and pager;
the form stays usable so a newer search supersedes a slow one. Error shows
"โหลดรายการเครื่องมือไม่สำเร็จ", the reference id and "ลองใหม่อีกครั้ง" (repeats
the failed applied request). `total_items = 0` → "ไม่พบเครื่องมือที่ตรงกับเงื่อนไข".
`total_items > 0` with no items → "ไม่มีรายการในหน้านี้" + "ขณะนี้ระบบส่งกลับ {n}
รายการตามเงื่อนไขนี้" + "กลับไปหน้าแรก" (keeps the applied filters). No automatic
retry, clamping or page reset.

## 6. Verification actually performed (2026-09-30, candidate code)

Final run (code hashes recorded before the run; logs kept outside the
repository; each exit code captured immediately after its command):

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Frontend unit suite | `npx vitest run` | 46 files, 319 tests passed | 0 |
| Typecheck + build | `npm run build` (`tsc -b && vite build`) | built; existing Vite chunk-size warning (index chunk 524.03 kB; 519.66 kB in 7E2) | 0 |
| Lint | `npm run lint` (oxlint) | 0 errors, 33 warnings — identical findings to an untouched copy of the base commit (33); none in the files changed by this batch | 0 |
| New e2e ×5 projects | `npx playwright test e2e/equipment-search-completeness.spec.ts` | 25 passed | 0 |
| Regression e2e ×5 projects | vehicle-search-partial-states, vehicle-equipment, responsive-shell, and (because `index.css` changed) fleet-status-dashboard, open-repair-report, certificate-expiry-report, inspection-finding-report | 175 passed | 0 |

Development iterations (kept): one lint precheck found a new
`set-state-in-effect` warning in the new page (34 warnings); the response
handling was restructured to one `setState` of a prebuilt state and the
warning disappeared (33). A mutation check that removed the generation
guard made exactly the three stale-ordering unit tests fail; the file was
restored byte-identically.

No backend suite was rerun (frontend-only batch). No live Google Sheets,
no Windows validation.

### Request-count evidence

- Unit (jsdom, no StrictMode): one `GET /api/v1/equipment` per load,
  submit, page change, clear and retry; editing sends none; all list
  requests are GETs; count independent of row count (50-row pages).
- Browser measurement (scratch Playwright config against the real mock
  backend and Vite dev server, desktop; counts only, no latency):
  initial load 2 list GETs for unfiltered page 1 (development StrictMode
  mount repeat; the older response is discarded by the guard) plus 2
  `GET /api/v1/me` owned by the app shell, not the page; editing q and
  category 0 requests; submit 1; clear 1; no non-GET requests. These are
  not whole-app or production figures, and no live-Sheets performance was
  measured.

## 7. Known limitations

- Offset paging is not a snapshot; rows can shift between pages if data
  changes (noted on the page).
- Duplicate ids are detected only within the returned page.
- A syntactically permitted link does not guarantee the detail page loads.
- The backend equipment list itself (legacy `read_rows`) is unchanged;
  its data-quality behavior is outside N1.
- The pre-existing `set-state-in-effect` warning in `EquipmentDetailPage`
  is unchanged.

## 8. Remaining Phase 7 gaps (unchanged by this batch)

DEC-T (type meaning), DEC-AL0–AL5 (alert), DEC-LOC, DEC-PMWO, finding
closure semantics, vehicle-search data quality (N2), PM due (E02–E05),
lifetime due (G01/G02), online/offline and offline-device report (A05, D26
item 5, I04, I07), inactive vehicle, CP7 KPI freeze beyond K1–K6, the
whole-Phase-7 result report, CHANGELOG/README staleness, Windows smoke,
live-Sheets validation, recorded authorization gaps (M02). Phase 7 remains
**PARTIAL**; no unrelated 7F1 candidate decision is approved.
