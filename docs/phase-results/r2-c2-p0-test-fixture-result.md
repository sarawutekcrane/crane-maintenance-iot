# R2-C2-P0 — Mock/TEST Vehicle and Driver Fixtures — Result

Status: **IMPLEMENTED AND TESTED ON LOCAL BRANCH `review/r2-c2-p0-test-fixtures` — UNCOMMITTED, AWAITING OWNER REVIEW.**
Mock / tests only. No API, route, schema, authorization, scope rule, Google Sheets, production or REAL-data change.

## 1. Baseline

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `b885bffb93d2edd169c948e9f01b8090ceed6b8d` (R2-C1 integrated) |
| Tree | `3bd2b5563df2303aa78f246d97dc342c1d456e9f` |
| Backend suite before any edit | **4827 passed, 0 failed** |
| Frontend Vitest before any edit | **798 passed** (66 files) |

## 2. Root cause (from the P0 preflight)

The Vehicle Master (Phase 3) and Driver Master (Phase 6) list / detail paths are unscoped (the live tabs carry no
test metadata), while the bounded R2 reference reads used by R2f-f and E2 are scoped. The mock projected every
master vehicle and driver as REAL and offered the TEST-only references `VEH-TEST-901` / `DRV-TEST-901` that have no
master row. Mock mode is always the TEST context, so every page-reachable identity was `*_SCOPE_UNPROVEN` and the
only TEST identities had no page.

## 3. Fixture changes

`backend/app/repositories/mock/seed_data.py` (additions):
- `SEED_TEST_SCOPED_VEHICLE_IDS = frozenset({"VEH-1048"})` — explicit classification of the EXISTING mock vehicle;
  no vehicle added (the master still lists exactly VEH-1046, VEH-1047, VEH-1048).
- `SEED_DRIVERS_TEST` — three fictional, clearly labelled TEST drivers: `DRV-TEST-901` ACTIVE (the existing reference
  id, not duplicated), `DRV-TEST-902` ACTIVE, `DRV-TEST-903` INACTIVE.

`backend/app/repositories/mock/repository.py` (fixture initialization and reference projection only):
- the TEST drivers join the mock Driver Master AFTER `_driver_seq` is taken (a created driver is still `DRV-0003`);
- `read_vehicle_reference`: a vehicle in `SEED_TEST_SCOPED_VEHICLE_IDS` is TEST-scoped (mock batch), every other
  vehicle stays REAL;
- `_driver_reference_rows` (shared by the R2f-e and R2f-f driver readers): a driver of `SEED_DRIVERS_TEST` is
  TEST-scoped, every other master driver stays REAL; a TEST reference-seed entry already in the master is not
  projected again (no duplicate, so no false AMBIGUOUS).

Scope is never derived from id spelling. Every scope check, the Google Sheets repository and production behaviour
are unchanged (mock mode cannot be REAL by configuration).

## 4. Scope classification after P0

| Identity | Master list / detail | R2 reference scope (mock) | In the TEST context |
|---|---|---|---|
| VEH-1046, VEH-1047 | yes | REAL | `VEHICLE_SCOPE_UNPROVEN` (fail closed) |
| **VEH-1048** | yes (unchanged) | **TEST** | resolves (R2f-f, E2) |
| VEH-TEST-901 | no (reference only, unchanged) | TEST | resolves via API only |
| DRV-0001, DRV-0002 | yes (unchanged) | REAL | `DRIVER_SCOPE_UNPROVEN` |
| **DRV-TEST-901 / -902** | **yes (new)** | **TEST**, ACTIVE | resolves; eligible |
| **DRV-TEST-903** | **yes (new)** | **TEST**, INACTIVE | resolves; `DRIVER_NOT_ACTIVE` for new / future work |

## 5. Tests

`backend/tests/test_r2_c2_p0_test_fixtures_batch.py` — 18 tests:

| Group | Proves |
|---|---|
| P0-MASTER | vehicle list is exactly the 3 seed vehicles and VEH-1048 detail resolves; TEST drivers listed and resolve (statuses ACTIVE / ACTIVE / INACTIVE, clearly TEST-named); original drivers unchanged; a created driver is `DRV-0003` |
| P0-PROJ | explicit vehicle and driver scope; each driver id projected once (both driver readers) |
| P0-R2FF | R2f-f write + vehicle view + driver→vehicles view with TEST identities; the INACTIVE TEST driver refused |
| P0-E2 | CREATE, SUBSTITUTE (DRV-TEST-902) and H2 handover with TEST drivers; history shows the HANDOVER; the INACTIVE driver refused; an assignment whose driver becomes INACTIVE (isolated repository instance) is retained with `FUTURE_ASSIGNMENT_DRIVER_NOT_ACTIVE_PENDING_REVIEW` |
| P0-BIDIR | the driver view lists its assignments with the vehicle id (vehicle↔driver both directions) |
| P0-ISO | VEH-1046 / VEH-1047 stay `VEHICLE_SCOPE_UNPROVEN`; DRV-0001 / DRV-0002 refused for E2 and R2f-f writes and the E2 driver view, nothing written; TEST identities never resolve in the REAL context; a duplicated reference still fails closed (`DRIVER_ID_AMBIGUOUS`); no driver is ever chosen automatically (missing `driver_id` → 422) |

| Run | Result |
|---|---|
| P0 tests | 18 passed |
| Groups B–G: Vehicle / Driver Master, R2f-f (+Sheets), Personnel–Driver links (+Sheets), E2 (+Sheets), go-live readiness (+Sheets), health, dev-auth, technician scope, Technician V2-only creation (17 files incl. P0) | **527 passed, 0 failed** |
| Full backend suite | **4845 passed, 0 failed** (= 4827 baseline + 18 P0; 0:15:46) |
| Frontend Vitest | **798 passed** (66 files) — unchanged |
| Playwright (live mock backend), `driver-phase6-batch1`, `vehicle-registry-read`, `vehicle-equipment`, all 5 viewport projects | **85 passed, 0 failed** |

Commands (from `backend/`): `python -m pytest -q tests/test_r2_c2_p0_test_fixtures_batch.py`; the group run above;
`python -m pytest -q`. From `frontend/`: `npx vitest run`;
`npx playwright test e2e/driver-phase6-batch1.spec.ts e2e/vehicle-registry-read.spec.ts e2e/vehicle-equipment.spec.ts`.
The full Playwright suite (28 specs) was not run; only the specs that read the changed mock data.

## 6. Regression guards

- Vehicle Master still lists exactly 3 seed vehicles; no vehicle added; VEH-1046 / VEH-1047 not reclassified.
- Original Driver Master ids and records unchanged; `DRV-000N` generation unchanged.
- No API endpoint added or changed; R2f-f, E2, Driver / Vehicle Master, authorization, TEST/REAL configuration,
  readiness, health, Google Sheets repository, frontend, governance and legacy code untouched.
- E2 over Google Sheets still makes zero transport requests (existing R2-C1 Sheets tests, run in groups B–G).
- No REAL write path enabled; Technician V2-only behaviour unchanged.

## 7. Limitations

- The Driver Master list now shows five drivers in mock mode (three clearly labelled TEST). The master pages have no
  scope column; the TEST label is in the synthetic names and the page-level data-context banner (R2-C2).
- VEH-1048 keeps its existing registration / branch history; only its R2 reference scope is TEST.
- VEH-TEST-901 remains a reference-only TEST vehicle (unchanged; used by existing R2f-f tests).

## 8. Next

Owner review. Commit / push to `review/r2-c2-p0-test-fixtures` needs separate authorization; integration, R2-C2a and
R2-C2b each need their own.
