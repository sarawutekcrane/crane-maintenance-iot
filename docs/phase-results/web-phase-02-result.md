PHASE: Web/API Phase 2 — Vehicle, Model, Workshop Equipment, Asset References, and QR Detail
STATUS: PASS

OBJECTIVE:
Implement machine master data (vehicle model, physical vehicle, vehicle
component read model, workshop equipment) and stable QR-based detail
pages (`/vehicle/{vehicle_id}`, `/equipment/{equipment_id}`) on top of
the Phase 1 foundation, preserving `vehicle_id` as the stable identity
even when the operational `machine_no` changes, keeping status history
append-only, and establishing the shared asset-reference pattern that
later inspection/repair/attachment records will reuse — while keeping
every new page mobile-first per the frozen Phase 1 responsive foundation.

PREREQUISITE CHECK:
- `00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt` — read in full (vehicle/model
  separation, component roles, part-tracking/asset-reference principles,
  workshop equipment, QR routing, mobile-first requirement).
- `00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt` — read in full
  (repository modes, Google Sheets schema-validation principles, QR
  testing on the local network).
- `02_PHASE2_VEHICLE_MODEL_EQUIPMENT_QR_EN.txt` — read in full; this
  report follows its required structure.
- `docs/phase-results/web-phase-01-result.md` — read in full. Phase 1 is
  accepted; its contracts (API versioning, error envelope, pagination,
  stable-ID convention, `Repository`/`StorageProvider` interfaces,
  request/user context, and the mobile-first responsive UI foundation —
  `Card`/`ResponsiveTable`/`FormField`/`ConfirmDialog`/mobile nav) are
  treated as frozen and were extended, never altered.
- Toolchain re-verified: Python 3.11.15, Node 22.22.2, npm 10.9.7,
  pre-installed Chromium at `/opt/pw-browsers/chromium` (used by the
  existing Playwright config, unchanged).
- No Google Sheets credentials or network path to the Google Sheets API
  exist in this environment — consistent with Phase 1, this limits what
  can be exercised for `GoogleSheetsRepository` (see TBD/Known Limitations).

FROZEN CONTRACTS USED:
- `/api/v1` versioning, the error envelope, `Page`/`PageParams`
  pagination, the `VEH-`/`DEV-`-style stable ID convention, ISO-8601 UTC
  timestamps (`docs/architecture/API_CONVENTIONS.md`) — all reused
  unchanged for the new vehicle/model/equipment routes.
- `Repository` ABC (`backend/app/repositories/base.py`) — extended with
  new abstract methods, exactly as its Phase 1 docstring anticipated
  ("domain-entity repository methods... are added starting Phase 2 as
  extensions of `Repository`, without changing this base shape"). No
  existing method (`mode`, `check_ready`) was touched.
- `RequestContext` (`app.context`) — `changed_by` on a vehicle status
  change is taken from the existing `RequestContext.user_id`, unchanged.
- Frontend: `Card`, `ResponsiveTable`, `FormField`, the `.dialog`/
  `.dialog-overlay` bottom-sheet pattern, `StatusBadge`, `LoadingState`/
  `ErrorState`, mobile nav, and `apiGet`/`ApiError` from `apiClient.ts`
  (extended with `apiPatch`, same `ApiResult<T>` shape) — no new layout
  primitive was introduced; every new page composes existing ones.

No frozen Phase 1 contract needed to change. No STOP was required.

FILES ADDED:
Backend:
- `backend/app/domain/asset.py` — `AssetType`, `AssetRef` (shared
  asset-reference pattern for Phase 3+ inspection/repair/attachments).
- `backend/app/domain/vehicle_model.py` — `ComponentRole`, `VehicleModel`.
- `backend/app/domain/vehicle.py` — `Vehicle`, `VehicleComponent`,
  `VehicleStatusHistoryEntry`.
- `backend/app/domain/equipment.py` — `EquipmentCategory`, `Equipment`.
- `backend/app/domain/vehicle_service.py`, `equipment_service.py` —
  domain/service layer assembling the Vehicle Detail view and
  translating not-found into the frozen `ApiError` envelope.
- `backend/app/repositories/mock/seed_data.py` — seed models/vehicles/
  components/status-history/equipment for `MockRepository`.
- `backend/app/repositories/google_sheets/schemas.py` — declared
  tab/header schema for the five new Google Sheets tables.
- `backend/app/api/v1/vehicle_schemas.py`, `equipment_schemas.py` — API
  request/response Pydantic models.
- `backend/app/api/v1/vehicles.py`, `equipment.py` — routers.
- Tests: `test_asset.py`, `test_vehicle_models_api.py`,
  `test_vehicles_api.py`, `test_equipment_api.py`,
  `test_mock_repository_vehicle.py` (28 new tests total).

Frontend:
- `frontend/src/lib/types.ts` — TypeScript types mirroring the backend
  schemas.
- `frontend/src/lib/labels.ts` — Thai label maps for
  `OperationalStatus`/`ComponentRole`/`EquipmentCategory` and a stable
  error-code -> Thai-message mapping (`describeErrorCode`), plus a Thai
  date/time formatter.
- `frontend/src/components/ChangeVehicleStatusDialog.tsx` (+ test) —
  status-change form dialog, built on the frozen dialog CSS pattern.
- `frontend/src/pages/VehicleListPage.tsx` (+ test),
  `VehicleDetailPage.tsx` (+ test) — the stable QR route
  (`/vehicle/:vehicleId`).
- `frontend/src/pages/EquipmentListPage.tsx` (+ test),
  `EquipmentDetailPage.tsx` (+ test) — the stable QR route
  (`/equipment/:equipmentId`).
- `frontend/e2e/vehicle-equipment.spec.ts` — 6 new Playwright test cases
  (18 runs across the 3 existing viewport projects).

FILES MODIFIED:
- `backend/app/domain/common.py` — added `OperationalStatus` (shared by
  Vehicle and Equipment); existing `utc_now`/`Page`/`PageParams` untouched.
- `backend/app/repositories/base.py` — added the Phase 2 abstract methods
  described above; `mode`/`check_ready` untouched.
- `backend/app/repositories/mock/repository.py` — full in-memory
  implementation of the new methods plus seed-data wiring.
- `backend/app/repositories/google_sheets/repository.py` — implements the
  same new methods, reporting a controlled not-configured/not-implemented
  error (see Known Limitations) instead of leaving them unimplemented.
- `backend/app/dependencies.py` — added `get_vehicle_service`/
  `get_equipment_service` composition-root providers.
- `backend/app/api/v1/router.py` — registers the two new routers.
- `frontend/src/lib/apiClient.ts` — added `apiPatch<T>` (same
  `ApiResult<T>`/error-envelope handling as `apiGet`, shared via a new
  internal `performRequest` helper — no change to the exported `apiGet`
  behavior or `ApiError` shape).
- `frontend/src/App.tsx` — added the four new routes.
- `frontend/src/components/NavBar.tsx` — added "ยานพาหนะ"/"เครื่องมือ"
  links.
- `README.md`, `CHANGELOG.md` — document the new routes/pages and the
  Phase 2 summary.

API ROUTES ADDED:
- `GET /api/v1/models` — paginated list, `q` free-text filter.
- `GET /api/v1/models/{model_id}` — 404 `MODEL_NOT_FOUND` if missing.
- `GET /api/v1/vehicles` — paginated list, `q`/`status`/`model_id` filters.
- `GET /api/v1/vehicles/{vehicle_id}` — Vehicle Detail (vehicle + model +
  components); 404 `VEHICLE_NOT_FOUND` if missing.
- `PATCH /api/v1/vehicles/{vehicle_id}` — update `machine_no` only;
  `vehicle_id` is never part of the request body and never changes.
- `GET /api/v1/vehicles/{vehicle_id}/components`.
- `GET /api/v1/vehicles/{vehicle_id}/status-history` — newest first.
- `PATCH /api/v1/vehicles/{vehicle_id}/status` — appends a history entry
  (`changed_by` from `RequestContext`) and updates current status; never
  rewrites a previous entry.
- `GET /api/v1/equipment` — paginated list, `q`/`category` filters.
- `GET /api/v1/equipment/{equipment_id}` — 404 `EQUIPMENT_NOT_FOUND` if
  missing.

DATABASE / SHEET TABLES USED:
- Mock mode (in-memory, seeded): `vehicle_models`, `vehicles`,
  `vehicle_components`, `vehicle_status_history`, `equipment`.
- Google Sheets mode: the same five tab names/header schemas are declared
  in `app/repositories/google_sheets/schemas.py` (columns mapped by
  header name, never row position, per the local-dev doc) but are not
  yet read/written against a real spreadsheet — see Known Limitations.

UI PAGES ADDED:
- `/vehicles` — Vehicle list/search (Thai, mobile-first).
- `/vehicle/:vehicleId` — Vehicle Detail: the stable QR entry point.
  Shows machine identity, model/brand, serial number, operational status
  with a "เปลี่ยนสถานะ" action, an editable machine number
  (vehicle_id-stable), components, and status history. Explicitly notes
  in Thai that PM/inspection/repair/documents arrive in later phases,
  rather than showing empty or fabricated sections for them.
- `/equipment` — Equipment list/search.
- `/equipment/:equipmentId` — Equipment Detail: the stable QR entry point
  for workshop machinery, kept separate from vehicle data end-to-end
  (separate domain model, repository methods, API routes, and page).

IMPLEMENTATION SUMMARY:
Domain identity is modeled with `vehicle_id` as the immutable primary
key and `machine_no` as mutable text (`PATCH /vehicles/{id}` only ever
touches `machine_no`); this is exercised by both a backend test
(`test_machine_no_change_does_not_change_vehicle_identity`) and a
Playwright test. `VehicleModel.component_roles` drives the
`VehicleComponent` read model — one seeded model
(`MODEL-0002`/`XCT80`) declares `ENGINE_MAIN` + `ENGINE_SECONDARY` + `PTO`
to prove the component-role design supports multi-engine vehicles without
any API shape change (baseline section 16). Status changes always go
through `MockRepository.change_vehicle_status`, which appends a new
`VehicleStatusHistoryEntry` and never mutates or removes a previous one;
every seeded vehicle starts with one history entry from its "import",
so the very first status change already proves append-only behavior
(2 entries, both present). Workshop equipment is a fully separate domain
entity/table/service/route/page from Vehicle — proven by a backend test
that equipment IDs never appear in the vehicle list. Missing source
values (e.g. `VEH-1048`'s serial number) are returned as `null`/blank,
never fabricated. The shared `AssetRef`/`AssetType` pattern is
established now (with its own unit tests) for Phase 3+ (inspection,
repair, attachments) to compose into their own records, the same way
Phase 1 established `FormField`/`ConfirmDialog` ahead of a real form.

`VehicleService`/`EquipmentService` are the single place that assembles
a detail view and turns "not found" into the frozen error envelope, so
a later Dashboard/alerts phase reuses them instead of querying the
repository directly (baseline section 3).

On the frontend, every new page/dialog is built from the Phase 1
primitives (`Card`, `ResponsiveTable`, `FormField`, the dialog CSS
pattern, `StatusBadge`) — no new layout primitive was added. The status
change action opens a dedicated confirmation dialog (not a one-tap
control), matching the baseline's mobile-first principle that
status-changing actions must not be easy to trigger accidentally. Thai
label maps (`lib/labels.ts`) keep raw English enum/error codes out of
user-facing text, per baseline section 1.

LOCAL STARTUP COMMANDS:
```
cp .env.example .env

./scripts/run_backend.sh     # http://127.0.0.1:8000
./scripts/run_frontend.sh    # http://127.0.0.1:5173
# or both together:
./scripts/run_dev.sh

./scripts/run_backend_tests.sh
./scripts/run_frontend_tests.sh
./scripts/run_e2e_tests.sh
```
Try the QR flow once both are running: open
http://127.0.0.1:5173/vehicle/VEH-1046 directly, or from
http://127.0.0.1:5173/vehicles search for "TC-12"/"TC-13"/"TC-14".
OpenAPI docs: http://127.0.0.1:8000/docs.

BUILD / TYPECHECK / LINT RESULT:
- Backend: `python -m pytest` — all tests import and run cleanly; no
  separate backend typecheck/lint tool is configured (unchanged from
  Phase 1 — `pyproject.toml` defines only `pytest`).
- Frontend typecheck: `npx tsc -b` — PASSED, no errors.
- Frontend production build: `npm run build` — PASSED.
  `dist/index.html` 0.43 kB, `dist/assets/*.css` 7.75 kB (2.10 kB gzip,
  unchanged — no new CSS was added), `dist/assets/*.js` 284.89 kB
  (88.00 kB gzip, up from 267.27 kB/84.82 kB gzip in Phase 1's report,
  for the four new pages/one new component/two new lib modules).
- Frontend lint: `npx oxlint` — PASSED. Same pre-existing
  `react/set-state-in-effect` warning as Phase 1's report (on
  `SystemStatusPage.tsx`'s data-fetch effect), now also present on
  `VehicleDetailPage.tsx` and `EquipmentDetailPage.tsx` for the identical
  reason (calling `setState` from inside a data-loading effect); no new
  warning category was introduced. Zero errors.

TESTS ACTUALLY PERFORMED:
Backend (`./scripts/run_backend_tests.sh` / `python -m pytest -v`,
`DATA_REPOSITORY=mock`): **37 passed, 0 failed** (9 from Phase 1 + 28 new):
- `test_vehicle_models_api.py` (4): list, free-text search, dual-engine
  model's component roles, controlled 404.
- `test_vehicles_api.py` (13): list + status filter, known vehicle opens
  by `vehicle_id`, multi-engine vehicle exposes both engine components,
  missing source value stays blank, controlled 404 (get/patch
  machine_no/patch status/components), machine_no change does not change
  vehicle identity, status change creates append-only history (asserts
  the original entry is still present, unmodified, plus the new one,
  newest-first), components endpoint.
- `test_equipment_api.py` (5): list + category filter, equipment route
  works, equipment never appears in the vehicle list, controlled 404.
- `test_mock_repository_vehicle.py` (3): repository instances don't share
  mutable state, status-change history is append-only at the repository
  level, pagination.
- `test_asset.py` (2): `AssetRef` construction, empty `asset_id` rejected.
- `test_google_sheets_repository.py` (+2 new): `VehicleService`/
  `EquipmentService` against an unconfigured `GoogleSheetsRepository`
  raise a controlled `RepositoryError` rather than crashing or returning
  a silently wrong result — the practical form the "same service works
  with mock and Google Sheets repositories" acceptance test can take
  without real credentials (see Known Limitations).
- Full Phase 1 regression (`test_health.py`, `test_error_envelope.py`,
  `test_local_storage.py`, `test_mock_repository.py`,
  `test_not_ready_when_unconfigured`): all still pass unmodified.

Frontend unit/component (`./scripts/run_frontend_tests.sh` /
`npx vitest run`): **18 passed, 0 failed**, 11 files (9 tests / 6 files
in Phase 1's report):
- `VehicleListPage.test.tsx`, `EquipmentListPage.test.tsx`: renders
  seeded rows with Thai labels and a working link to the detail route.
- `VehicleDetailPage.test.tsx` (3 tests): renders identity/model/
  components/status-history in Thai; shows a controlled Thai 404 message
  for a missing vehicle; opens the status-change dialog and issues the
  `PATCH .../status` request.
- `EquipmentDetailPage.test.tsx` (2 tests): renders identity fields in
  Thai; shows a controlled Thai 404 message for missing equipment.
- `ChangeVehicleStatusDialog.test.tsx` (2 tests): submits the selected
  status + note; renders nothing when closed.
- All 9 Phase 1 tests (`App.test.tsx`, `StatusBadge.test.tsx`,
  `FormField.test.tsx`, `ResponsiveTable.test.tsx`, `NavBar.test.tsx`,
  `SystemStatusPage.test.tsx`) still pass unmodified.

Frontend end-to-end viewport tests (`./scripts/run_e2e_tests.sh` /
`npx playwright test`, real Chromium against the actual Vite dev server +
FastAPI backend): **30 passed, 0 failed** across the 3 existing viewport
projects (smartphone-portrait 375×667, tablet-portrait 768×1024, desktop
1280×800) — 12 Phase 1 tests unmodified/still passing, plus 6 new test
cases × 3 projects = 18 new runs in `e2e/vehicle-equipment.spec.ts`:
- scanning the QR route (`/vehicle/VEH-1046`) opens Vehicle Detail
  directly, with no unintended horizontal scrolling.
- Vehicle Detail shows model/components/status-history (multi-engine
  vehicle: both engine labels visible).
- the status-change dialog's "เปลี่ยนสถานะ" button meets the 44px touch
  target, the dialog never exceeds the viewport at any tested size, and
  submitting it is reflected on the page afterward.
- vehicle list search by machine number finds the seeded vehicle with the
  blank serial number and navigates to its detail page (`Link`-based
  client-side navigation).
- Equipment Detail is reachable at its own stable QR route with no
  horizontal scrolling.
- a non-existent vehicle_id renders a controlled Thai not-found message,
  not a crash or blank page.

TEST RESULTS:
- Backend: 37 passed, 0 failed.
- Frontend unit/component: 18 passed, 0 failed.
- Frontend e2e (Playwright): 30 passed, 0 failed.
- Frontend typecheck + production build: passed.
- Frontend lint: passed (pre-existing warning only, no new category).

SCREEN / UX NOTES:
- All new user-facing text is Thai; raw English codes
  (`OperationalStatus`, `ComponentRole`, `EquipmentCategory`, error
  `code`s) are mapped to Thai via `lib/labels.ts` and never shown
  directly, per baseline section 1.
- Vehicle Detail deliberately does not show PM/inspection/repair/
  document/GPS/IoT sections yet — a one-line Thai note says these arrive
  in later phases, rather than fabricating empty placeholders or
  guessing at data that does not exist yet (baseline section 16 /
  "PHASE WORKFLOW" — implement only this phase).
- Status change is a separate confirmation dialog (select + optional
  note, explicit "ยืนยันเปลี่ยนสถานะ" button), not a one-tap toggle —
  matches the baseline's mobile-first principle that status-changing
  actions must not be easy to trigger by accident.
- Verified at smartphone/tablet/desktop widths via the Playwright suite:
  no horizontal scrolling on any new page, the status-change button and
  dialog meet touch-target/viewport-fit requirements, and the list-page
  search form and result table both use the frozen mobile-first
  `FormField`/`ResponsiveTable` patterns (stacked cards on phones, table
  from tablet width up).

TBD VALUES REMAINING:
- Real Google Sheets credentials, PostgreSQL, RBAC enforcement, and
  every domain area not in this phase's scope (PM, inspection, repair,
  parts/lifetime, IoT/devices, certificates, GPS, alerts, dashboard,
  OTA, safety commands, audit log) remain out of scope until their
  respective phases, unchanged from Phase 1's report.
- `AssetRef`/`AssetType` is defined but not yet consumed by any endpoint
  — established now for Phase 3+ (inspection/repair/attachments) to
  build on, the same way Phase 1 established `FormField`/`ConfirmDialog`
  ahead of a real form.

KNOWN LIMITATIONS:
- All Phase 1 limitations still apply unchanged (no RBAC yet, no CI
  pipeline, Playwright emulates mobile/tablet viewports on Chromium
  rather than WebKit device presets).
- `GoogleSheetsRepository`'s Phase 2 domain methods (vehicles, models,
  components, status history, equipment) declare their intended tab/
  header schema (`app/repositories/google_sheets/schemas.py`) but raise
  a controlled `RepositoryError` ("not configured", pointing at the
  local-dev setup doc) or `NotImplementedError` beyond that point,
  rather than performing real Google Sheets I/O. This environment has no
  Google Sheets credentials and no network path to the Google Sheets
  API, so live connectivity/read/write cannot be exercised here — the
  same constraint Phase 1 already documented for `check_ready`/
  `validate_schema`. The Phase 2 prompt anticipates this sequencing
  explicitly (scope item 14: "Implement repository mappings first in
  MockRepository, then GoogleSheetsRepository when local Google
  credentials are available"); real Sheets I/O should be implemented and
  tested on the developer's machine once `GOOGLE_SHEET_ID`/
  `GOOGLE_APPLICATION_CREDENTIALS` are set, following the schema
  declared here.
- Vehicle/Model/Equipment creation and deletion are not implemented —
  only what the phase's acceptance tests require (read/list/search,
  `machine_no` update, and status change with history) was built, to
  avoid speculative admin CRUD surface the phase does not ask for. Mock
  data is seeded in code; there is no create-vehicle UI/endpoint yet.
- Equipment has no status-history/append-only tracking (the baseline
  requires this specifically for vehicles; equipment status changes are
  out of scope for this phase since no acceptance test requires them).
- Vehicle list/equipment list pagination is implemented on the API
  (page/page_size) but the UI does not yet render pager controls — the
  seeded datasets are small enough that this does not affect the
  acceptance tests; add pager UI when a phase introduces a larger
  fleet/equipment dataset.
- The pre-existing `react/set-state-in-effect` lint warning (Phase 1) now
  also appears on `VehicleDetailPage.tsx`/`EquipmentDetailPage.tsx` for
  the same reason; not a new category of issue.

RISKS / CONCERNS:
- None identified that block Phase 3. `VehicleService`/`EquipmentService`
  give later phases (inspection, repair, PM, Dashboard) a single place to
  extend rather than re-querying the repository directly, and `AssetRef`
  gives them a ready-made way to reference "this vehicle or this
  equipment" without re-deriving that branching logic.
- The Google Sheets domain mapping is architecturally complete (interface
  + declared schema) but functionally unverified against a real
  spreadsheet, since this sandboxed environment cannot reach Google's
  API or hold real credentials. This should be the first thing verified
  on the developer's local machine before Phase 2's Google Sheets mode
  is considered done end-to-end.

ANY CHANGE TO PREVIOUS FROZEN PHASES:
NONE. `Repository`/`StorageProvider` interfaces, the error envelope, API
versioning, pagination, stable-ID convention, `RequestContext`, and the
mobile-first responsive UI foundation (breakpoints, `Card`/
`ResponsiveTable`/`FormField`/dialog patterns, mobile nav) are all reused
exactly as frozen in Phase 1. `Repository` gained new abstract methods,
which its own Phase 1 docstring explicitly anticipated as the intended
Phase 2+ extension mechanism — no existing method's behavior changed.

NEXT PHASE READINESS:
READY

STOP HERE.
DO NOT IMPLEMENT THE NEXT PHASE.
