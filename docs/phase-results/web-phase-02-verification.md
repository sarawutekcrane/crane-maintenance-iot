# WEB/API PHASE 2 — POST-PHASE VERIFICATION REPORT

Scope: audit only. No Phase 3 work performed. No code changed as part of
this verification.

Branch verified: `web/phase-02-vehicle-qr` @ `0ed7260`
(`git pull origin web/phase-02-vehicle-qr` performed first; branch was
fast-forwarded from `a4f847b` to `0ed7260`, which added the governance
docs this verification was asked to read).

Documents read in full before verification, as instructed:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/02_PHASE2_VEHICLE_MODEL_EQUIPMENT_QR_EN.txt`
- `docs/phase-results/web-phase-01-result.md`
- `docs/phase-results/web-phase-02-result.md`

All automated test/build/lint commands below were re-executed directly in
this session (not copied from the Phase 2 report). Exact commands and
exact results are reported in Section H.

======================================================================
## A. REQUIREMENT TRACEABILITY
======================================================================

| # | Requirement (Phase 2 scope) | Implemented | Evidence file/module | Automated test evidence | Manual test needed | Notes |
|---|---|---|---|---|---|---|
| 1 | Model management (list/get) | YES | `backend/app/api/v1/vehicles.py` (`/models`, `/models/{id}`), `domain/vehicle_model.py` | `test_vehicle_models_api.py` (4 tests, re-run PASSED) | No | Create/update/delete not implemented — correctly out of scope (no acceptance test requires it) |
| 2 | Vehicle management (list/get/update machine_no) | YES | `vehicles.py`, `domain/vehicle.py`, `domain/vehicle_service.py` | `test_vehicles_api.py` (13 tests, re-run PASSED) | No | |
| 3 | `vehicle_component` read model | YES | `domain/vehicle.py:VehicleComponent`, `GET /vehicles/{id}/components` | `test_multi_engine_vehicle_exposes_both_engine_components`, `test_vehicle_components_endpoint` | No | Component roles only; counters not yet attached (correct — counters are a later IoT phase) |
| 4 | Workshop equipment master | YES | `domain/equipment.py`, `equipment.py` router, `equipment_service.py` | `test_equipment_api.py` (5 tests, re-run PASSED) | No | See Section B — `operational_status` reuses `Vehicle`'s `OperationalStatus` enum verbatim (open-decision issue, see below) |
| 5 | Shared asset-reference pattern | YES | `domain/asset.py` (`AssetRef`, `AssetType`) | `test_asset.py` (2 tests, re-run PASSED) | No | Not consumed by any endpoint yet — correctly scoped as a Phase 3+ building block only |
| 6 | Stable route `/vehicle/{vehicle_id}` | YES | `frontend/src/App.tsx`, `VehicleDetailPage.tsx` | Playwright: "scanning the QR route opens Vehicle Detail page directly" (re-run PASSED × 3 viewports) | Yes — real QR label / real phone scan | Manually curled `GET /api/v1/vehicles/VEH-1046` directly; confirmed working |
| 7 | Stable route `/equipment/{equipment_id}` | YES | `App.tsx`, `EquipmentDetailPage.tsx` | Playwright: "equipment detail is reachable at its own stable QR route" (re-run PASSED × 3 viewports) | Yes — real QR label / real phone scan | |
| 8 | One crane = one permanent QR (route contains only `vehicle_id`) | YES | Route pattern is exactly `/vehicle/:vehicleId`, no other path segment | Manually inspected `App.tsx`; confirmed no checklist/work-order/inspection ID in the path | No | |
| 9 | `vehicle_id` stable when `machine_no` changes | YES | `MockRepository.update_vehicle_machine_no` never touches the dict key; `PATCH` body schema (`UpdateMachineNoRequest`) has no `vehicle_id` field | `test_machine_no_change_does_not_change_vehicle_identity` (re-run PASSED); manually verified live via `curl` (see Section I item 4) | No | |
| 10 | Status history append-only | YES | `MockRepository.change_vehicle_status` appends, never mutates/removes | `test_change_vehicle_status_appends_history_without_removing_previous_entries`, `test_status_change_creates_append_only_history` (re-run PASSED) | No | |
| 11 | Thai Vehicle Detail sections | YES | `VehicleDetailPage.tsx`, `lib/labels.ts` | `VehicleDetailPage.test.tsx` (3 tests, re-run PASSED); Playwright viewport tests | Yes — visual read-through by a Thai-speaking reviewer | All labels/status/error text confirmed Thai in source; no raw English enum values found rendered directly |
| 12 | Thai Equipment Detail | YES | `EquipmentDetailPage.tsx` | `EquipmentDetailPage.test.tsx` (2 tests, re-run PASSED) | Yes | |
| 13 | Search/list endpoints | YES | `GET /vehicles` (`q`, `status`, `model_id`), `GET /equipment` (`q`, `category`), `GET /models` (`q`) | `test_list_vehicles_filters_by_status`, `test_list_equipment_filters_by_category`, `test_list_models_supports_free_text_search` (re-run PASSED) | No | List UI has no pager control despite API pagination existing (documented limitation, small seed dataset masks it) |
| 14 | Mock first, then Google Sheets mapping | PARTIAL | `repositories/mock/repository.py` (full), `repositories/google_sheets/repository.py` + `schemas.py` (interface + declared schema only) | `test_google_sheets_repository.py`: 3 tests confirming controlled `RepositoryError` when unconfigured (re-run PASSED) | Yes — real Sheets I/O once `GOOGLE_SHEET_ID`/credentials exist (cannot be exercised in this sandboxed environment, no network path to Google API) | Correctly matches the phase prompt's own sequencing (scope item 14); `GoogleSheetsClient.validate_schema` still raises `NotImplementedError` unconditionally — schema *validation* itself is not implemented yet, only declared |
| 15 | `machine_no` remains text | YES | `Vehicle.machine_no: str`, `UpdateMachineNoRequest.machine_no: str` | `test_machine_no_change_does_not_change_vehicle_identity` asserts `isinstance(machine_no, str)` after a numeric-looking update (re-run PASSED) | No | |
| 16 | Missing values stay blank, not fabricated | YES | `Vehicle.serial_number: str | None`, seed data leaves `VEH-1048.serial_number = None` | `test_missing_source_value_stays_blank` (re-run PASSED) | No | |

**Acceptance tests from the Phase 2 prompt — explicit check:**

| Acceptance test | Result | Evidence |
|---|---|---|
| Known vehicle opens by `vehicle_id` | PASS | `test_known_vehicle_opens_by_vehicle_id`; manual `curl GET /vehicles/VEH-1046` |
| Machine number change does not change vehicle identity | PASS | `test_machine_no_change_does_not_change_vehicle_identity`; manual `curl PATCH` verified live |
| QR route remains stable | PASS | Route is a static path template; no workflow/temporary ID in it |
| Workshop equipment is separate from vehicle master | PASS | Separate Pydantic model, table, service, router, page; `test_equipment_is_not_present_in_vehicle_list` |
| Equipment route works | PASS | `test_equipment_route_works`; Playwright e2e |
| Status change creates history | PASS | `test_status_change_creates_append_only_history` |
| Missing vehicle returns controlled 404 | PASS | `test_missing_vehicle_returns_controlled_404`; manual `curl` returned `{"error":{"code":"VEHICLE_NOT_FOUND",...}}` with HTTP 404 |
| Thai UI labels display correctly | PASS | Source inspection + component/e2e tests |
| Same service works with mock and Google Sheets repositories when configured | PARTIAL | Proven only for the "not configured" path (`RepositoryError`); real Sheets I/O is unverifiable in this environment (no credentials/network) — this is a pre-existing, disclosed constraint of the sandbox, not a defect introduced by Phase 2 |

======================================================================
## B. OPEN-DECISION / GUESSING AUDIT
======================================================================

Compared every new enum, schema, default, and workflow against
`OPEN_DECISIONS_REGISTER_EN.txt`.

### FINDING — Decision ID **C02 (Equipment Status Codes)** — UNAPPROVED PERMANENT DECISION

- Register status: `TBD-BLOCKING` — "Do not automatically reuse all vehicle statuses."
- Also restated in `CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt` §2: "Do not invent equipment status codes."
- **What the current implementation does:** `Equipment.operational_status` (`backend/app/domain/equipment.py:37`) is typed as the exact same `OperationalStatus` enum used by `Vehicle` (`WORKING, READY, MAINTENANCE, OUT_OF_SERVICE, LONG_TERM_PARKING`), defined once in `app/domain/common.py`. This is not a placeholder — it is baked into:
  - the domain model (`Equipment.operational_status: OperationalStatus`),
  - the API response schema (`EquipmentResponse.operational_status: OperationalStatus`, `backend/app/api/v1/equipment_schemas.py`),
  - the `MockRepository`/seed data (all three seeded equipment rows use vehicle status values),
  - the frontend (`operationalStatusLabel`/`operationalStatusTone` maps and `EquipmentDetailPage.tsx` import the exact same maps used for vehicles).
  - the declared Google Sheets schema (`EQUIPMENT_SHEET` reuses the `operational_status` column with no distinct vocabulary).
- **Was it explicitly approved?** NO. Nothing in `docs/phase-results/web-phase-02-result.md` flags this as a decision requiring approval; it is presented as settled fact ("Shares the `OperationalStatus` vocabulary with `Vehicle`... but has its own identity, category, and QR route" — the code comment argues this is fine, but the register explicitly forbids exactly this reuse without a decision being made).
- **Risk:** Workshop equipment (lathes, welders, compressors, forklifts) does not obviously map to vehicle-oriented states like `LONG_TERM_PARKING`; Phase 3+ (inspection/repair) will likely branch logic or alerts on equipment status, compounding the cost of unwinding this later. Because it is now embedded in the API response schema and the Google Sheets column declaration, changing it after real spreadsheet data exists becomes a breaking/migration change instead of a clean addition.
- **Required action:** Before Phase 3 builds anything that reads/writes equipment status (inspection results, alerts, repair workflow), either (a) obtain explicit approval to intentionally reuse `OperationalStatus` for equipment as a permanent decision (closing C02 in the register with that resolution), or (b) introduce a distinct `EquipmentOperationalStatus` enum with its own vocabulary. Do not let a third module (Phase 3) start depending on the current shape before this is resolved.

### Checked and found compliant (no unapproved permanent decision):

| Register ID | Status | What Phase 2 did | Verdict |
|---|---|---|---|
| C01 Vehicle Status Transition Rules | TBD-BLOCKING | `change_vehicle_status` accepts any `OperationalStatus` value with no transition matrix; `ChangeVehicleStatusDialog.tsx` offers all 5 statuses unconditionally, no client-side restriction either | Compliant — no strict transition rule was invented |
| C03 Equipment Counter Model | TBD-DEFERRED | Not touched — no counters attached to equipment at all | Compliant — correctly deferred |
| A01 Transaction ID Generation | TBD-BLOCKING (for inspection/repair/work-order/alert/command/attachment IDs specifically) | `VehicleStatusHistoryEntry.history_id` uses a simple in-process sequence (`STH-0001`, ...) scoped to `MockRepository`; no inspection/repair/PM/alert/command ID scheme was introduced | Not yet in scope for A01's named domains; the `STH-` scheme is a local, mock-only convenience, not presented as a frozen production ID strategy. Acceptable for Phase 2, but flag for whoever designs the final backend-generated opaque-ID strategy that this ad hoc sequence should not be silently treated as that answer |
| A08 Soft Delete / Archive | TBD-BLOCKING | No delete endpoint implemented for vehicle/model/equipment | Compliant — not touched |
| A09 Concurrency / Optimistic Locking | TBD-BLOCKING (before multi-user writes to Google Sheets) | `PATCH` endpoints have no version/`updated_at` precondition check | Compliant for this phase — Google Sheets writes are not implemented yet, so the register's stated trigger condition has not occurred; must be revisited before Google Sheets write support ships |
| B01 Exact Sheet Schema Version | TBD-BLOCKING per domain integration | `GoogleSheetsClient.validate_schema()` still unconditionally raises `NotImplementedError`; `schemas.py` only *declares* an intended header set, not validated against a live spreadsheet | Compliant — correctly left unresolved/undone rather than guessed, and disclosed as a known limitation |
| G05 Part Instance Status Transitions | PARTIALLY FROZEN | Not touched | Compliant — out of scope |
| D01–D04, E01–E05, F01–F03, G01–G06, H01–H03, I01–I07, J*, K*, L*, M01–M08 | various | Not touched by Phase 2 at all | Compliant — none of these domains were implemented, so nothing was guessed |

**Conclusion for Section B:** one unapproved permanent decision was found (C02). Per
the verification instructions, this means the phase is **not read** to
be waved through without this being surfaced and resolved — see Final
Verdict.

======================================================================
## C. PREVIOUS-PHASE REGRESSION REVIEW
======================================================================

| File/interface | Why it changed | Backward compatible | Test evidence | Explicitly permitted? |
|---|---|---|---|---|
| `backend/app/domain/common.py` | Added `OperationalStatus` enum, shared by Vehicle/Equipment | YES — `utc_now`, `Page`, `PageParams` untouched; purely additive | Full original Phase 1 suite (`test_health.py`, `test_error_envelope.py`, `test_local_storage.py`, `test_mock_repository.py`) re-run and still passes inside the 37-test run | YES — Phase 1 did not freeze a closed enum set; adding shared vocabulary is normal Phase 2+ extension |
| `backend/app/repositories/base.py` | Added 9 new abstract methods (models/vehicles/components/history/equipment) | Technically a breaking change to the ABC (any third-party subclass must implement the new methods) but... | N/A (interface, not directly tested) | YES, explicitly — Phase 1's own docstring on this file states domain-entity methods "are added starting Phase 2 as extensions of `Repository`, without changing this base shape"; `mode`/`check_ready` themselves are byte-for-byte unchanged |
| `backend/app/repositories/mock/repository.py` | Implements the new abstract methods + seed wiring | YES — existing `mode`/`check_ready` behavior unchanged | `test_mock_repository.py::test_mock_repository_is_always_ready` still passes | Implied by base.py's freeze note |
| `backend/app/repositories/google_sheets/repository.py` | Implements the new abstract methods (as controlled errors) | YES — existing `check_ready`/`mode` unchanged | `test_google_sheets_repository.py::test_not_ready_when_unconfigured` still passes | Implied by base.py's freeze note |
| `backend/app/dependencies.py` | Added `get_vehicle_service`/`get_equipment_service` providers | YES — additive only | Exercised indirectly by every new API test (dependency injection used throughout) | Normal composition-root extension, not a frozen contract |
| `backend/app/api/v1/router.py` | Registers 2 new routers | YES — additive only | All new route tests pass; `/api/v1/health`/`/readiness` untouched | Normal |
| `frontend/src/lib/apiClient.ts` | Added `apiPatch`, refactored shared logic into `performRequest` | YES — verified by direct code read: `apiGet`'s public behavior (`ApiResult<T>` shape, error envelope handling) is identical, only internally reshared | Frontend unit suite (18 tests) includes pages that still use `apiGet` unchanged (e.g. `SystemStatusPage.test.tsx`) and passes | Additive; `ApiError`/`ApiResult<T>` shapes unchanged |
| `frontend/src/App.tsx` | Added 4 routes | YES — existing `/` and `/system-status` routes untouched | `App.test.tsx` still passes | Normal |
| `frontend/src/components/NavBar.tsx` | Added 2 nav links | YES | `NavBar.test.tsx` (Phase 1's own test, re-run) still passes unmodified | Normal — mobile nav toggle behavior itself not touched |

**No frozen Phase 1 contract (API versioning, error envelope shape,
pagination shape, stable-ID convention, `RequestContext`, `StorageProvider`,
mobile-first CSS/breakpoints/`Card`/`ResponsiveTable`/`FormField`/dialog
pattern) was altered.** All Phase 1 automated tests (backend 9/9,
frontend unit 9/9, e2e 12/12) still pass unmodified as a subset of the
current totals (37/18/30) — verified by re-running the full suites, not
by re-reading the prior report's claim.

======================================================================
## D. API CONTRACT REVIEW
======================================================================

| Check | Result | Evidence |
|---|---|---|
| `/api/v1` conventions preserved | YES | All new routes registered under `api_v1_router`, verified via `curl http://127.0.0.1:8999/api/v1/vehicles/...` |
| Stable `vehicle_id` | YES | Confirmed live: PATCH-ing `machine_no` on `VEH-1046` left `vehicle_id` unchanged in the subsequent GET |
| `machine_no` not used as identity | YES | All routes key on `vehicle_id` in the path; `machine_no` only ever appears in the request/response body |
| No Google Sheets row-number IDs | YES | All IDs are prefixed opaque strings (`VEH-`, `MODEL-`, `CMP-`, `STH-`, `EQP-`); Google Sheets I/O itself is not implemented yet so no row-number dependency could have been introduced |
| Typed request/response schemas | YES | Dedicated Pydantic schemas in `vehicle_schemas.py`/`equipment_schemas.py`, distinct from domain models |
| Common error envelope preserved | YES | Manually confirmed live: 404 responses use the exact `{"error":{"code","message","details","request_id"}}` shape; `test_error_envelope.py` (Phase 1) still passes |
| Timezone-aware timestamps | YES | `utc_now()` returns `tzinfo=UTC`; observed live response `"changed_at": "...Z"`-style ISO 8601 |
| English stable backend/domain codes | YES | `VEHICLE_NOT_FOUND`, `MODEL_NOT_FOUND`, `EQUIPMENT_NOT_FOUND`, enum values — all English |
| Thai user-facing UI | YES | Confirmed by source read of all 4 new pages + `labels.ts`; no raw enum/error code found rendered directly to the user |
| Repository abstraction preserved | YES | `VehicleService`/`EquipmentService` depend only on the `Repository` ABC, never on `MockRepository`/`GoogleSheetsRepository` directly |
| Browser does not access Google Sheets directly | YES | No Google API client code exists in `frontend/` at all |
| Browser does not access ESP32 directly | YES | Not applicable to this phase; no such code path exists |
| Frontend does not duplicate authoritative backend business logic | YES | Frontend pages render backend-returned values as-is; the one client-side rule (required-machine_no non-empty before submit) is input validation, not a business rule, and the backend independently validates via `Field(min_length=1)` |
| Phase 2 backward-compatible with Phase 1 | YES | See Section C |

======================================================================
## E. DATA INTEGRITY REVIEW
======================================================================

| Check | Result | Evidence |
|---|---|---|
| `vehicle_id` stable if `machine_no` changes | YES | Live-verified via `curl` PATCH + GET; `test_machine_no_change_does_not_change_vehicle_identity` |
| Unknown/missing values not fabricated or zeroed | YES | `VEH-1048.serial_number` is `None` end-to-end (domain → API → UI shows "ไม่มีข้อมูล", never `0` or `""`) |
| Vehicle status history is append-oriented | YES | `MockRepository.change_vehicle_status` only appends to the list; confirmed by `test_change_vehicle_status_appends_history_without_removing_previous_entries` and live `curl` (original `WORKING` entry with its original note was still present, unmodified, after two live status changes performed during this verification) |
| Component records support >1 engine/PTO | YES | `MODEL-0002` declares `ENGINE_MAIN + ENGINE_SECONDARY + PTO`; `VEH-1047` (that model) exposes all 3 components; live-verified via `curl GET /vehicles/VEH-1047/components`-equivalent detail call |
| Workshop equipment not stored in `vehicle_master` | YES | Fully separate Pydantic model/table/dict/router; `test_equipment_is_not_present_in_vehicle_list` and live `curl "/equipment?q=VEH"` returned 0 items |
| Equipment and vehicle identities remain distinct | YES | Separate ID prefixes (`EQP-` vs `VEH-`), separate services, separate routes; `AssetType` enum exists precisely to distinguish them for future shared references |
| No history silently overwritten | YES | Same evidence as "append-oriented" above |
| No Google Sheets row-number dependency | YES | N/A currently — no live Sheets I/O implemented; the declared schema maps by header name only (`schemas.py`), consistent with the local-dev doc's requirement |
| Google Sheets mappings validate expected headers before writes | **NOT YET FUNCTIONAL** | `GoogleSheetsClient.validate_schema()` unconditionally raises `NotImplementedError` — the header/tab schema is *declared* (`schemas.py`) but not *validated* against any real spreadsheet, and no write path exists yet at all. This matches the phase's own documented sequencing (mock first) and is not a defect, but it means this specific checklist item cannot be marked YES yet — it is NOT_APPLICABLE until Google Sheets mode is actually exercised with real credentials |

======================================================================
## F. SECURITY / SECRETS REVIEW
======================================================================

No secret **values** are reproduced below.

| Check | Result | Evidence |
|---|---|---|
| Committed `.env` files | NONE FOUND | `git ls-files | grep -iE "\.env$\|credential\|service-account\|\.pem$\|\.key$\|secret"` → no matches; `.env.example` (no real values, all fields blank/development placeholders) is the only committed env-shaped file |
| Credentials JSON | NONE FOUND | Same search; `.gitignore` explicitly excludes `credentials.json`, `service-account*.json` |
| API keys / access tokens / passwords / private keys | NONE FOUND | No such files tracked; `.gitignore` excludes `*.pem`, `*.key` |
| Unsafe development authentication presented as production authentication | GUARDED | `DEV_AUTH_MODE=true` injects a fixed `dev-user`/`ADMIN` context; `main.py` raises `RuntimeError` at startup if `APP_ENV=production` **and** `DEV_AUTH_MODE=true`; a runtime warning is logged whenever dev-auth is active in non-production. This is the exact behavior the local-dev doc §9 requires ("production startup must fail or warn strongly") |
| Missing input validation on new write APIs | MOSTLY OK, ONE GAP | `UpdateMachineNoRequest.machine_no` has `min_length=1, max_length=100`; `ChangeVehicleStatusRequest.status` is a strict enum (invalid values rejected with 422 by Pydantic); `note` capped at `max_length=500`. **Gap:** neither write endpoint has any authorization/role check beyond the fixed dev-auth context — anyone who can reach the API can change any vehicle's status or machine number. This is consistent with the baseline's own statement that "Final RBAC/security is implemented in the later hardening phase" (local-dev doc §9, baseline §31) and is not a Phase 2 scope item, but it should be listed as a standing risk, not silently assumed acceptable indefinitely |

No committed secrets found. No hard-coded production credentials found.

======================================================================
## G. MOBILE / RESPONSIVE REVIEW
======================================================================

Automated coverage (Playwright, real Chromium, re-run in this session —
see Section H for exact command/output):

| Viewport | Covered by automated e2e? | Result |
|---|---|---|
| Smartphone portrait (375×667) | YES | 10/10 tests passed (4 shell + 6 vehicle/equipment) |
| Smartphone landscape | **NO — GAP** | No Playwright project exists for a landscape viewport (only `smartphone-portrait`, `tablet-portrait`, `desktop` are defined in `playwright.config.ts`). This is a real automated-coverage gap against the baseline's FROZEN guardrail #4 ("Must support smartphone portrait, **smartphone landscape**, tablet, and desktop") and against this verification's own required checks. The CSS itself is fluid/relative (no fixed-portrait-only breakpoint logic was found in `index.css`), so landscape is *plausibly* fine, but it has not been verified, automated or manual, on this branch |
| Tablet (portrait) | YES | 10/10 tests passed |
| Tablet landscape | **NO — not separately covered** | Same gap as above; tablet-landscape would sit inside the same "desktop-style" CSS branch (`min-width: 1024px` etc. per `RESPONSIVE_UI.md`) as tablet-landscape width is typically ≥1024px, but this has not been explicitly tested either |
| Desktop (1280×800) | YES | 10/10 tests passed |

Specific checks:

| Check | Result | Evidence |
|---|---|---|
| No unintended horizontal scrolling | YES (tested viewports) | `document.documentElement.scrollWidth <= clientWidth` asserted on Home/System Status pages at all 3 tested viewports (pre-existing Phase 1 test, still passing); Phase 2 pages' own e2e tests separately assert no horizontal scroll after navigating to `/vehicle/VEH-1046` and `/equipment/EQP-0001` |
| Touch targets remain usable | YES (spot-checked) | Global `.button` CSS enforces `min-height/min-width: var(--tap-target)` = 44px (`index.css`); the vehicle-status-change button is explicitly asserted ≥44px by the e2e suite; the inline "แก้ไข" (edit machine_no) button and list-page "ค้นหา" button inherit the same `.button` class so structurally meet the same minimum, though not individually asserted by a Playwright bounding-box check |
| No required hover-only interaction | YES | All new interactive elements are `<button>`/`<a>`/form controls; no `:hover`-only affordance introduced |
| Thai text wraps correctly | YES (structural) | Global `overflow-wrap: break-word` from Phase 1 is unchanged and applies to all new pages; long Thai model names (e.g. "XCMG XCT80 รถเครนล้อยาง 80 ตัน (สองเครื่องยนต์)") were not specifically screenshotted, but no `white-space: nowrap` or fixed-width text container was introduced in the new pages |
| Dialogs/forms fit the viewport | YES | `ChangeVehicleStatusDialog` reuses the frozen `.dialog`/`.dialog-overlay` pattern; e2e test explicitly asserts the dialog's bounding box never exceeds the viewport at all 3 tested sizes |
| Vehicle Detail usable on mobile | YES (tested sizes) | e2e: renders identity/model/components/status-history, status-change flow works, at smartphone-portrait |
| Equipment Detail usable on mobile | YES (tested sizes) | e2e: reachable and rendered with no horizontal scroll at smartphone-portrait |
| List/search pages usable on smaller screens | YES (tested sizes) | `VehicleListPage`/`EquipmentListPage` use the same `ResponsiveTable` (stacked cards below tablet width) and `FormField` patterns as Phase 1; search-by-machine-number e2e test passes at smartphone-portrait |

**Conclusion for Section G:** solid coverage for portrait phone, portrait
tablet, and desktop. **Smartphone-landscape (and tablet-landscape) have
no automated or documented manual verification on this branch** — flag
as a manual test item (see Section J) and a gap against the FROZEN
guardrail wording, not a proven defect.

======================================================================
## H. AUTOMATED VERIFICATION
======================================================================

All commands below were executed directly in this verification session
against the checked-out branch; none of these results are copied from
the Phase 2 report.

### Backend

Command:
```
cd backend && python3 -m venv .venv && source .venv/bin/activate \
  && pip install -e ".[dev]" \
  && DATA_REPOSITORY=mock python -m pytest -v
```
Result: **37 passed, 0 failed** in 0.90s. Full list of test IDs matches
the Phase 2 report's claimed breakdown (asset: 2, equipment_api: 5,
error_envelope: 2, google_sheets_repository: 3, health: 3,
local_storage: 2, mock_repository: 1, mock_repository_vehicle: 3,
vehicle_models_api: 4, vehicles_api: 12 — 37 total). No test was skipped
or hidden.

### Frontend

Command: `cd frontend && npm install && npx vitest run`
Result: **11 test files, 18 tests, 18 passed, 0 failed.**

Command: `npx tsc -b`
Result: **exit 0, no type errors.**

Command: `npx oxlint`
Result: **3 warnings** (`react/set-state-in-effect` on
`SystemStatusPage.tsx`, `EquipmentDetailPage.tsx`, `VehicleDetailPage.tsx`
— all data-fetch-in-`useEffect` pattern, pre-existing category from
Phase 1, no error-level lint finding). **0 errors.**

Command: `npm run build`
Result: **PASSED.** `dist/index.html` 0.43 kB, `dist/assets/*.css` 7.75 kB
(2.10 kB gzip), `dist/assets/*.js` 284.89 kB (88.00 kB gzip).

Command: `bash scripts/run_e2e_tests.sh`
Result: **30 passed, 0 failed** (21.6s), across `smartphone-portrait`,
`tablet-portrait`, `desktop` × (4 Phase 1 shell tests + 6 Phase 2
vehicle/equipment tests).

### Manual live-server verification (this session)

Started `uvicorn app.main:app` on a scratch port (`DATA_REPOSITORY=mock`)
and issued direct `curl` calls (see Sections D/E/I for the specific
requests/responses); server was stopped afterward. This independently
confirmed the error envelope shape, 404 codes, `vehicle_id` stability
across a live `PATCH`, and equipment/vehicle separation, rather than
relying solely on the test suite's own assertions.

### Repository/data

- `MockRepository` tests: covered above (`test_mock_repository.py`,
  `test_mock_repository_vehicle.py`) — **4 tests passed** total across
  both files.
- Google Sheets mapping/schema tests: `test_google_sheets_repository.py`
  — **3 tests passed**, but these only test the "not configured" path;
  no test exercises real header/schema validation against a live sheet,
  because that capability is not implemented yet (see Sections B, E).

No test was skipped, disabled, or hidden in this verification. No claimed
result in the Phase 2 report was found to be false.

======================================================================
## I. PHASE 2 SPECIFIC VERIFICATION
======================================================================

1. **Model management works.** YES — `curl`/pytest confirm list+get+404 for `/models`.
2. **Vehicle list/detail works.** YES — confirmed via pytest, e2e, and live `curl`.
3. **Known vehicle opens by stable `vehicle_id`.** YES — live `curl GET /api/v1/vehicles/VEH-1046` returned the expected detail payload.
4. **Changing `machine_no` does not change `vehicle_id`.** YES — live-verified in this session:
   ```
   PATCH /api/v1/vehicles/VEH-1046 {"machine_no":"TC-99-CHANGED"}
   → {"vehicle_id":"VEH-1046","machine_no":"TC-99-CHANGED",...}
   GET  /api/v1/vehicles/VEH-1046 → vehicle_id: VEH-1046, machine_no: TC-99-CHANGED
   ```
5. **`machine_no` remains text.** YES — schema-typed `str`; changed to a numeric-looking string in the live test above and remained a JSON string.
6. **`vehicle_component` supports multi-engine/PTO structures.** YES — `VEH-1047`/`MODEL-0002` exposes `ENGINE_MAIN`, `ENGINE_SECONDARY`, `PTO` simultaneously.
7. **Workshop equipment is separate from `vehicle_master`.** YES — separate model/table/service/route; live `curl "/equipment?q=VEH"` → 0 items.
8. **Shared asset-reference abstractions do not merge vehicle/equipment identities.** YES — `AssetRef.asset_type` is a required discriminator (`VEHICLE`/`EQUIPMENT`); not yet consumed by any endpoint so no merging has actually occurred anywhere yet.
9. **Vehicle status history is retained.** YES — append-only, verified live (see Section E) and by two dedicated tests.
10. **Permanent vehicle QR resolves to `/vehicle/{vehicle_id}`.** YES — exact route in `App.tsx`.
11. **Permanent equipment QR resolves to `/equipment/{equipment_id}`.** YES — exact route in `App.tsx`.
12. **Permanent QR does not contain checklist revision / inspection ID / PM work order ID / repair ID / temporary workflow IDs.** YES — the route has exactly one path parameter (`vehicleId` or `equipmentId`); no other phase's entities exist yet to leak into it.
13. **Vehicle Detail works on mobile and desktop.** YES for smartphone-portrait/tablet-portrait/desktop (tested); landscape not verified (see Section G).
14. **Equipment Detail works on mobile and desktop.** Same as above.
15. **Search/list endpoints work.** YES — `q`, `status`, `model_id`, `category` filters all covered by passing tests.
16. **Controlled 404 behavior works for unknown IDs.** YES — verified for vehicle, model, equipment, components, status-history, and machine_no/status PATCH targets, both by pytest and by a live `curl` in this session.
17. **Thai UI is preserved.** YES — confirmed by source read; no regression to Phase 1's Thai shell.
18. **Same service/domain flow works through MockRepository.** YES.
19. **GoogleSheetsRepository remains behind the repository abstraction.** YES — `VehicleService`/`EquipmentService` never import `GoogleSheetsRepository` or `MockRepository` directly; only `app/dependencies.py` (composition root) chooses.
20. **No equipment status code was invented unless explicitly approved.** LITERALLY TRUE (no *new* status value was invented) but see the Section B finding: the existing vehicle status vocabulary was reused wholesale for equipment, which the register explicitly prohibits doing "automatically." Treat this as an open item, not a clean pass.
21. **No strict vehicle status transition rules were invented unless explicitly approved.** YES — confirmed no transition matrix exists anywhere (backend accepts any status, frontend offers all statuses unconditionally).

======================================================================
## J. MANUAL ACCEPTANCE PLAN
======================================================================

Run these yourself against `./scripts/run_dev.sh` (or
`run_backend.sh` + `run_frontend.sh` separately) with
`DATA_REPOSITORY=mock`.

1. **Vehicle list**
   - Prerequisite: dev servers running, browser at `http://127.0.0.1:5173/vehicles`.
   - Action: view the page, then search `TC-12` in the search box and press "ค้นหา".
   - Input: `TC-12`.
   - Expected: exactly one row, `VEH-1046`, links to its detail page.
   - If it fails: screenshot the page + browser devtools Network tab showing the `/api/v1/vehicles?...` response.

2. **Vehicle detail**
   - Prerequisite: same as above.
   - Action: open `http://127.0.0.1:5173/vehicle/VEH-1046` directly (simulating a QR scan).
   - Expected: Thai-labeled machine identity, model name, status badge, component list (เครื่องยนต์หลัก, ระบบส่งกำลัง), and status history table, all in Thai.
   - If it fails: screenshot the page; save the browser console log.

3. **Equipment list/detail**
   - Prerequisite: same.
   - Action: open `http://127.0.0.1:5173/equipment`, click "เครื่องกลึงเบอร์ 1".
   - Expected: navigates to `/equipment/EQP-0001`, shows category "เครื่องกลึง", location "โรงซ่อมกลาง".
   - If it fails: screenshot + Network tab for `/api/v1/equipment/EQP-0001`.

4. **Unknown vehicle 404**
   - Prerequisite: same.
   - Action: open `http://127.0.0.1:5173/vehicle/VEH-9999`.
   - Input: a `vehicle_id` known not to exist.
   - Expected: a Thai "ไม่พบข้อมูลยานพาหนะนี้" message, not a blank page or crash.
   - If it fails: screenshot + full page HTML source.

5. **QR route behavior**
   - Prerequisite: phone and dev computer on the same Wi-Fi; `PUBLIC_BASE_URL` set to the LAN IP per the local-dev doc §10.
   - Action: generate/scan a QR encoding `http://<LAN-IP>:5173/vehicle/VEH-1046`.
   - Expected: opens directly to Vehicle Detail, no intermediate page.
   - If it fails: note the phone model/browser and screenshot what appeared instead.

6. **`machine_no` change while `vehicle_id` remains unchanged**
   - Prerequisite: on `/vehicle/VEH-1046`.
   - Action: click "แก้ไข" next to เลขเครื่องจักร, change the value, click "บันทึก".
   - Input: any new machine number, e.g. `TC-12-TEST`.
   - Expected: page reloads showing the new machine number; the URL and "รหัสยานพาหนะ: VEH-1046" text do not change.
   - If it fails: screenshot before/after, and the `/api/v1/vehicles/VEH-1046` PATCH request/response from devtools.

7. **Mobile phone test**
   - Prerequisite: real phone (or Chrome DevTools device emulation as a fallback) at a portrait width (~375–414px) and rotated to landscape.
   - Action: open Vehicle Detail and Equipment Detail in both orientations; open the "เปลี่ยนสถานะ" dialog.
   - Expected: no horizontal scrolling in either orientation, all buttons easily tappable, dialog fits the screen without needing to zoom/scroll.
   - If it fails: screenshot in the failing orientation, and note whether it's portrait or landscape specifically (landscape has no automated coverage yet — see Section G).

8. **Desktop test**
   - Prerequisite: standard desktop browser window (≥1280px wide).
   - Action: repeat items 1–4 at desktop width.
   - Expected: layout switches from stacked cards to a real table on the list pages; everything else behaves the same as mobile.
   - If it fails: screenshot + note the exact window width.

======================================================================
## K. FINAL VERDICT
======================================================================

# PASS WITH KNOWN LIMITATIONS

**Blocking defects:**
None. Every automated test suite claimed in the Phase 2 report was
independently re-executed in this session and passed with identical
counts (backend 37/37, frontend unit 18/18, e2e 30/30, typecheck/build
clean, lint 0 errors). Every Phase 2 acceptance test from the phase
prompt was verified, most of them both by automated test and by a live
manual `curl` session against a freshly started server. No frozen Phase 1
contract was broken.

**Known limitations (disclosed, acceptable for this phase's scope):**
- `GoogleSheetsRepository` has no real Google Sheets I/O yet; only the
  interface and declared tab/header schema exist (`validate_schema`
  still raises `NotImplementedError` unconditionally). This exactly
  matches the phase prompt's own sequencing instruction (scope item 14)
  and cannot be exercised in this sandboxed environment (no credentials,
  no network path to Google's API).
- No automated or manual verification of **smartphone-landscape** or
  **tablet-landscape** exists on this branch (only portrait phone,
  portrait tablet, and desktop are covered by the Playwright config).
  This is a real gap against the FROZEN guardrail wording ("smartphone
  portrait, smartphone landscape, tablet, and desktop").
- No pager UI on the vehicle/equipment list pages despite the API
  supporting pagination (masked by the small seeded dataset).
- No RBAC/authorization beyond the fixed dev-auth context on the new
  write endpoints (`PATCH machine_no`, `PATCH status`) — consistent with
  the baseline's stated hardening-phase timeline, but a standing risk
  that should not be forgotten once real users exist.
- Equipment has no status-history/append-only tracking (only vehicles do)
  — acceptable since no acceptance test requires it this phase.

**Open decisions intentionally deferred (correctly left unresolved):**
C01 (vehicle status transitions), C03 (equipment counters), A08 (soft
delete), A09 (concurrency), B01 (live sheet schema validation), A01 (for
inspection/repair/PM/alert/command IDs — not yet needed), and every
domain area outside Phase 2's scope (D–M in the register).

**Unapproved decisions found:**
**C02 — Equipment Status Codes.** The register explicitly says "Do not
automatically reuse all vehicle statuses" for equipment (`TBD-BLOCKING`),
and the freeze checkpoints doc separately says "Do not invent equipment
status codes." Phase 2 nonetheless gave `Equipment.operational_status`
the exact same `OperationalStatus` enum used by `Vehicle`, baked into the
domain model, the API response schema, the seed data, the frontend label
maps, and the declared Google Sheets column — without flagging this as a
decision requiring approval anywhere in the Phase 2 report. This must be
resolved (either explicit approval to keep the reuse, or a distinct
equipment status vocabulary) before Phase 3 builds inspection/repair/alert
logic that reads or writes equipment status.

**Frozen Phase 1 contracts confirmed intact:**
`/api/v1` versioning; the common error envelope
(`{error:{code,message,details,request_id}}`); `Page`/`PageParams`
pagination shape; the opaque-prefixed stable-ID convention; ISO-8601 UTC
timestamps; the `Repository` ABC's `mode`/`check_ready` shape (extended,
not altered); `RequestContext`/`DEV_AUTH_MODE` behavior including the
production-safety guard in `main.py`; `StorageProvider`/local file
storage (untouched, not exercised by Phase 2); the mobile-first
foundation (`Card`, `ResponsiveTable`, `FormField`, the dialog
bottom-sheet pattern, mobile nav) — all reused unchanged by every new
Phase 2 page.

**Next phase readiness: NOT READY**

Specifically: Phase 3 should not begin until the C02 equipment-status
open decision is either explicitly approved as-is or corrected, because
Phase 3 (inspection/checklist/finding workflows) is likely to read or
branch on equipment status, and doing so on top of an unapproved
vocabulary compounds the cost of fixing it later. Everything else in
Phase 2 is technically sound, genuinely tested, and does not need rework;
this is a narrow, well-scoped gate, not a broad rebuild.

STOP HERE. Phase 3 was not started as part of this verification.
