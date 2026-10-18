# R2-C3 — Legacy Vehicle–Driver Cutover — Result

Status: **IMPLEMENTED AND TESTED — PASS** on the local review branch `review/r2-c3-legacy-cutover`, created from
the integration baseline. The implementation and testing stage created no commit, push, merge or deployment.
Commit, push and integration each need separate owner approval. R2-C4 is not started.

## 1. Baseline and authority

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `3a3d4bf3691884c1a756807001d8435b1c54e9b1` (R2-C2b integrated) |
| Governance | `c1-amendment-a2-driver-responsibility.md` A2-8 (legacy retirement, O2) and A2-10 (R2-C3) |
| Plan | R2-C3 read-only preflight (dependency inventory) and owner decisions D1–D6 |
| Live Sheets (owner-confirmed) | `driver_master` exists, empty; `vehicle_driver` exists, empty. Neither was read, written, renamed, recreated, migrated or seeded. |

## 2. Owner decisions applied

| Decision | Applied as |
|---|---|
| D1 retire legacy Web/API history access | The three routes and the UI are removed; no data is deleted and nothing is migrated into R2f-f or E2 |
| D2 remove `VEHICLE_DRIVER_SHEET` | Removed after proving no runtime use remained (grep: no `app/` reference) |
| D3 remove the static readiness coverage | The `vehicle_driver` `CoverageEntry` in `go_live_readiness.py` is removed |
| D4 remove page, route and link | `VehicleDriverAssignmentsPage`, `/vehicle/:vehicleId/drivers` and the Vehicle Detail "คนขับ/ผู้ควบคุม" button are removed; no redirect or fallback |
| D5 two stale comments | Corrected in `crane_driver_responsibility_routes.py` and `operational_driver_assignment_routes.py` (docstrings only) |
| D6 external API consumers | Accepted as **UNVERIFIED** for review-branch development only, not for production deployment |

## 3. Change inventory (28 paths + this document)

| Status | Path | Classification / change |
|---|---|---|
| M | `backend/app/api/v1/drivers.py` | REMOVE the 3 assignment routes; RETAIN the 4 Driver Master routes |
| M | `backend/app/api/v1/driver_schemas.py` | REMOVE `AssignDriverRequest`, `VehicleDriverAssignmentResponse`; RETAIN the Driver schemas |
| M | `backend/app/domain/driver.py` | REMOVE `VehicleDriverAssignment`; RETAIN `Driver`; docstring updated |
| M | `backend/app/domain/driver_service.py` | REMOVE `assign_driver`, `end_assignment`, `list_vehicle_driver_history`, `_require_vehicle_exists`; RETAIN the Driver Master methods |
| M | `backend/app/repositories/base.py` | REMOVE the 4 abstract assignment methods |
| M | `backend/app/repositories/mock/repository.py` | REMOVE the 4 methods, the store and its sequence |
| M | `backend/app/repositories/mock/seed_data.py` | REMOVE `build_seed_vehicle_driver_assignments` (VDRV-0001/0002 synthetic rows) |
| M | `backend/app/repositories/google_sheets/repository.py` | REMOVE the 4 methods and the row mapper; REMOVE `VEHICLE_DRIVER_SHEET` from `_CORE_SCHEMAS`; RETAIN Driver Master I/O and shared helpers (`_parse_bool`, `_epoch` remain used) |
| M | `backend/app/repositories/google_sheets/schemas.py` | REMOVE `VEHICLE_DRIVER_SHEET`; comments corrected |
| M | `backend/app/domain/go_live_readiness.py` | REMOVE the static `vehicle_driver` coverage row; RETAIN `UNTAGGED` (part of the readiness API response vocabulary) |
| M | `backend/app/api/v1/crane_driver_responsibility_routes.py`, `operational_driver_assignment_routes.py` | Docstring corrections only (D5) |
| M | 7 backend test files (§5) | REMOVE retention tests; REPLACE with cutover / isolation assertions |
| D | `frontend/src/pages/VehicleDriverAssignmentsPage.tsx`, `VehicleDriverAssignmentsPage.test.tsx` | REMOVE |
| M | `frontend/src/App.tsx` | REMOVE the import and the route |
| M | `frontend/src/pages/VehicleDetailPage.tsx` | REMOVE the legacy link button |
| M | `frontend/src/lib/types.ts` | REMOVE `VehicleDriverAssignment` |
| M | `frontend/src/pages/VehicleDetailPage.test.tsx` | REPLACE "link present" with "link absent" |
| M | `frontend/e2e/driver-phase6-batch1.spec.ts` | REMOVE the 3 legacy workflow tests; ADD one cutover test; RETAIN the Driver list / detail test |
| M | `frontend/e2e/r2-c2a-panels.spec.ts`, `r2-c2b-e2-panels.spec.ts` | REPLACE "legacy link kept" / legacy-data reads with "link absent" and "route 404" |

Totals: 26 modified, 2 deleted; +194 / −1261 lines. `git diff --check` clean.

**Deliberately not changed:**
- `frontend/src/lib/labels.ts` still holds the dead message `VEHICLE_DRIVER_ASSIGNMENT_NOT_FOUND` (outside the allowlist; harmless, the code is never raised). **DEFER**.
- Historical phase-result and governance documents keep their historical text (**RETAIN**).
- Docstring and comment mentions of `vehicle_driver` that state it is never read (R2f-f, E2, R2f-e, R2f-a, `authz.py`) remain true (**RETAIN**).

## 4. Preserved (VERIFIED)

- **Driver Master:** the four operations (`GET` / `POST /drivers`, `GET` / `PATCH /drivers/{driver_id}`), `DriverService` master methods, the mock and Google Sheets `driver_master` I/O, `DRIVER_MASTER_SHEET` and its readiness membership. 20 Driver Master tests pass unchanged.
- **Unchanged features and infrastructure:**
  - Personnel–Driver links (R2f-e), the permanent responsible driver (R2f-f) and E2: unchanged source, apart from two route docstrings.
  - Shared authorization, history, readiness and reporting infrastructure, and the TEST/REAL boundaries.
  - The R2-C2a and R2-C2b panels (no source change).
- **Isolation coverage kept, not deleted:** the R2f-f, R2f-e, R2f-a and E2 source guards forbidding legacy symbols remain. The tests that compared the legacy store now assert that the store does not exist, so no legacy source can exist (§5).

## 5. Tests changed

| File | Change |
|---|---|
| `test_driver_phase6_batch1.py` | Removed 10 assignment API tests, the `vehicle_driver` schema test and the Sheets assignment round-trip. Added `test_the_three_phase6_assignment_routes_are_retired` (absent from OpenAPI, 404, Driver Master routes present) and `test_the_retired_assignment_code_is_gone_and_vehicle_driver_is_not_a_readiness_prerequisite`. |
| `test_crane_driver_responsibility_batch_r2f_f.py` | Legacy-rows timeline test → asserts no legacy store exists; snapshot list updated; retention test → `…driver_master_routes_still_work_and_phase6_assignment_routes_are_retired` (legacy GET 404) |
| `test_crane_driver_responsibility_sheets_batch_r2f_f.py` | Readiness assertion inverted: `vehicle_driver` not in `_CORE_SCHEMAS`, Driver Master still in it |
| `test_operational_driver_assignment_batch_r2_c1.py` | Never-read test keeps the call-log guard and asserts no legacy store; routes test inverted (Driver Master present, legacy absent) |
| `test_operational_driver_assignment_sheets_batch_r2_c1.py` | `vehicle_driver` not in the readiness tabs |
| `test_personnel_driver_link_batch_r2f_e.py` | Snapshot list updated; schema / route test → Driver Master headers unchanged, `VEHICLE_DRIVER_SHEET` absent, no legacy route |
| `test_go_live_readiness_batch_r2f_h3.py` | Coverage inventory no longer lists `vehicle_driver` (D3) |

The Sheets fakes that still contain a `vehicle_driver` tab (R2f-f / R2f-e Sheets tests) are kept. They prove the tab is never requested or written.

## 6. Test results (executed on the final code)

| Check | Result |
|---|---|
| Affected backend files (10 files incl. R2f-a / P0 / R2f-e Sheets) | **444 passed** |
| Full backend suite | **4898 passed, 0 failed** (12 min). Collect-only: baseline commit 4908, branch 4898 = −12 retired legacy tests + 2 cutover tests. |
| In-process API check | The 3 retired routes are absent from OpenAPI and answer 404 `NOT_FOUND`; `GET /drivers` 200 |
| Full frontend Vitest | **966 passed** (80 files) = 969 − 3 tests of the deleted legacy page |
| TypeScript (`tsc -b`) | clean |
| Lint (`oxlint`) | exit 0; **30 warnings** (baseline 31; the deleted legacy page carried one) |
| Production build | passed |
| Combined Playwright regression (same 14 specs, `--grep-invert @mutation`, fresh backend) | **365 passed, 0 failed** = 375 − 15 (3 retired legacy tests × 5 viewports) + 5 (cutover test × 5) |
| R2-C2a `@mutation`, isolated fresh backend | **5 passed** |
| R2-C2b `@mutation`, isolated fresh backend | **5 passed** |

The browser cutover test proves:
- Vehicle Detail shows the permanent-responsible-driver panel and the E2 panel, with no legacy link;
- the old URL renders no legacy page and calls no legacy route;
- the three retired routes answer 404.

## 7. Limitations and risks

- **External API consumers: UNVERIFIED (D6).** A caller outside this repository (firmware, scripts, another service) would now get 404 and nothing would be written. Production access logs should be checked before any deployment.
- **Legacy history is no longer viewable in the app (D1).** The live `vehicle_driver` tab is currently empty (owner-confirmed) and is left as it is.
- **Readiness:** a workbook without a `vehicle_driver` tab is now ready (intended by A2-10).
- **Dead label:** `VEHICLE_DRIVER_ASSIGNMENT_NOT_FOUND` remains in `labels.ts` (DEFER, outside the allowlist).
- **Not run:** the full Playwright suite (all specs) and browsers other than Chromium.

## 8. Live Sheets and REAL data

No live Google Sheets access and no REAL data operation. The code no longer references the `vehicle_driver` tab; the
live tab and its rows (none) are untouched. All browser runs used dedicated in-memory Mock/TEST backends.

## 9. Next owner approval checkpoint

Each separately authorized: commit and push of the R2-C3 change set to `review/r2-c3-legacy-cutover`; fast-forward
integration; R2-C4 (complete regression and R2 acceptance).
