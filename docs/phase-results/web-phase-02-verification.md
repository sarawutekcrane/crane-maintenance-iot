# WEB/API PHASE 2 — POST-PHASE VERIFICATION REPORT

CORRECTION ADDENDUM (applied after the original verification below): the
original audit found one blocking issue — decision C02 (Equipment Status
Codes) had been resolved by the implementation without approval, reusing
Vehicle's `OperationalStatus` enum wholesale for equipment. The user has
since explicitly approved a separate equipment status vocabulary (`READY`,
`IN_USE`, `MAINTENANCE`, `OUT_OF_SERVICE`), and the fix described in this
addendum has been implemented, tested, and re-verified. The original
report body below is left intact as the historical record of what was
found; Sections B, G, H, I, and K are updated in place to reflect the
correction, each clearly marked. No Phase 3 work was performed. No other
part of Phase 2 was redesigned or refactored.

**What changed to resolve C02:**
- Backend: `app/domain/equipment.py` gained `EquipmentOperationalStatus`
  (`READY`, `IN_USE`, `MAINTENANCE`, `OUT_OF_SERVICE`); `Equipment.operational_status`
  and `EquipmentResponse.operational_status` now use it instead of
  `OperationalStatus`. `app/domain/common.py`'s `OperationalStatus`
  docstring now states it is Vehicle-only. `Vehicle`'s enum and values are
  byte-for-byte unchanged (`WORKING`, `READY`, `MAINTENANCE`,
  `OUT_OF_SERVICE`, `LONG_TERM_PARKING`).
- Mock seed data: `EQP-0001` was seeded with the no-longer-valid
  `WORKING`; changed to `IN_USE`. `EQP-0002` (`READY`) and `EQP-0003`
  (`MAINTENANCE`) already used values that exist in the new vocabulary, so
  only their type changed, not their value.
- Frontend: `frontend/src/lib/types.ts` gained `EquipmentOperationalStatus`;
  `Equipment.operational_status` now uses it. `frontend/src/lib/labels.ts`
  gained `equipmentStatusLabel`/`equipmentStatusTone`, separate from
  `operationalStatusLabel`/`operationalStatusTone` (Vehicle-only).
  `EquipmentDetailPage.tsx`/`EquipmentListPage.tsx` now render equipment
  status via the equipment-specific maps.
- New backend tests: `backend/tests/test_equipment_status.py` (10 tests —
  see updated Section H).
- Updated existing frontend test fixtures
  (`EquipmentDetailPage.test.tsx`/`EquipmentListPage.test.tsx`) that had
  used the now-invalid `WORKING` value for equipment, to `IN_USE`.
- Also closed the smartphone-landscape/tablet-landscape responsive gap
  noted in Section G: added `smartphone-landscape` (568×320) and
  `tablet-landscape` (1024×768) Playwright projects to
  `frontend/playwright.config.ts`, and generalized the one project-name-
  conditional assertion in `frontend/e2e/responsive-shell.spec.ts` (the
  nav-toggle test) to branch on actual viewport width against the existing
  641px breakpoint instead of a hard-coded project name list, so it
  correctly covers the two new projects without weakening the assertions
  for the three original ones.
- Governance: `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
  decision C02 changed from `TBD-BLOCKING` to approved/frozen for the
  status-code vocabulary only; transition rules remain explicitly
  undefined/unapproved (not part of this decision).

Scope: audit only. No Phase 3 work performed. No code changed as part of
the *original* verification below (the correction described above was
applied afterward, at the user's explicit direction, and is itself scoped
strictly to fixing the one blocking finding plus the disclosed responsive
gap).

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
| 4 | Workshop equipment master | YES | `domain/equipment.py`, `equipment.py` router, `equipment_service.py` | `test_equipment_api.py` (5 tests, re-run PASSED); `test_equipment_status.py` (10 tests, added by correction, PASSED) | No | ORIGINAL finding: `operational_status` reused `Vehicle`'s `OperationalStatus` enum verbatim (open-decision issue, see Section B). RESOLVED: now uses the approved, separate `EquipmentOperationalStatus` vocabulary |
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

### FINDING — Decision ID **C02 (Equipment Status Codes)** — UNAPPROVED PERMANENT DECISION — **RESOLVED (see Correction Addendum)**

**Update:** the user has explicitly approved a separate equipment status
vocabulary (`READY`, `IN_USE`, `MAINTENANCE`, `OUT_OF_SERVICE`), and the
implementation has been corrected accordingly:
`app.domain.equipment.EquipmentOperationalStatus` (backend) and
`EquipmentOperationalStatus` (frontend `lib/types.ts`) now carry
equipment's own vocabulary, separate from `Vehicle`'s `OperationalStatus`.
`OPEN_DECISIONS_REGISTER_EN.txt` C02 is updated from `TBD-BLOCKING` to
approved/frozen for the status-code vocabulary only (transition rules
remain unapproved/undefined, unaffected by this decision). Re-verified
live and by new automated tests — see the updated Section H and the new
`backend/tests/test_equipment_status.py`. The finding below is preserved
verbatim as the original audit record.

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

**Conclusion for Section B (original):** one unapproved permanent decision
was found (C02). Per the verification instructions, this means the phase
is **not ready** to be waved through without this being surfaced and
resolved — see Final Verdict.

**Conclusion for Section B (after correction):** C02 is now resolved and
approved (status-code vocabulary only); no other unapproved permanent
decision was found in Phase 2. See the updated Final Verdict (Section K).

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
| Smartphone landscape | **CLOSED (see Correction Addendum)** | Original finding: no Playwright project existed for a landscape viewport. Fixed: added a `smartphone-landscape` project (568×320 — the `min-width: 481px` "smartphone landscape" breakpoint band per `RESPONSIVE_UI.md`, a width no other project previously exercised). Re-run result: 10/10 tests passed (see updated Section H) |
| Tablet (portrait) | YES | 10/10 tests passed |
| Tablet landscape | **CLOSED (see Correction Addendum)** | Original finding: not separately covered. Fixed: added a `tablet-landscape` project (1024×768 — the `min-width: 1024px` breakpoint band, also previously unexercised). Re-run result: 10/10 tests passed |
| Desktop (1280×800) | YES | 10/10 tests passed |

Fixing this required one small, targeted test-logic change beyond adding
the two new Playwright projects: the "mobile menu toggle expands and
collapses navigation" test in `responsive-shell.spec.ts` had branched on
`testInfo.project.name === 'smartphone-portrait'` specifically, which
would have mis-asserted a hidden toggle for `smartphone-landscape`
(568px is still below the 641px breakpoint where the toggle collapses, so
the toggle is correctly visible there too, same as smartphone-portrait).
The test now branches on `page.viewportSize().width < 641` — the actual
CSS breakpoint already frozen in `RESPONSIVE_UI.md` — instead of a
hard-coded project name, so the same one test correctly covers all five
projects. This is a generalization of existing test logic to a
already-frozen breakpoint value, not a new rule or a redesign; the
assertions themselves (toggle visible + expands/collapses vs. toggle
hidden + menu always visible) are unchanged.

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

**Conclusion for Section G (original):** solid coverage for portrait phone,
portrait tablet, and desktop. **Smartphone-landscape (and tablet-landscape)
have no automated or documented manual verification on this branch** —
flag as a manual test item (see Section J) and a gap against the FROZEN
guardrail wording, not a proven defect.

**Conclusion for Section G (after correction):** all five viewport bands
named in the baseline's FROZEN guardrail #4 (smartphone portrait,
smartphone landscape, tablet portrait, tablet landscape, desktop) now have
automated Playwright coverage, 50/50 passing. A real physical-device
landscape test remains a good idea (see Section J item 7) but is no longer
required to close a coverage gap — it would only be extra confidence on
top of already-passing automated coverage.

======================================================================
## H. AUTOMATED VERIFICATION
======================================================================

**Original verification run** (before the C02/landscape correction) is
preserved below, followed by the **correction re-run**.

### Backend (original)

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

### Frontend (original)

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

### Manual live-server verification (original)

Started `uvicorn app.main:app` on a scratch port (`DATA_REPOSITORY=mock`)
and issued direct `curl` calls (see Sections D/E/I for the specific
requests/responses); server was stopped afterward. This independently
confirmed the error envelope shape, 404 codes, `vehicle_id` stability
across a live `PATCH`, and equipment/vehicle separation, rather than
relying solely on the test suite's own assertions.

### Repository/data (original)

- `MockRepository` tests: covered above (`test_mock_repository.py`,
  `test_mock_repository_vehicle.py`) — **4 tests passed** total across
  both files.
- Google Sheets mapping/schema tests: `test_google_sheets_repository.py`
  — **3 tests passed**, but these only test the "not configured" path;
  no test exercises real header/schema validation against a live sheet,
  because that capability is not implemented yet (see Sections B, E).

No test was skipped, disabled, or hidden in this verification. No claimed
result in the Phase 2 report was found to be false.

---

### CORRECTION RE-RUN (after fixing C02 and the landscape gap)

All commands below were executed directly in this session, after the
code changes described in the Correction Addendum, against the same
checked-out branch. Exact commands, exact results — nothing summarized
from memory of the original run.

**Backend:**
```
cd backend && DATA_REPOSITORY=mock python -m pytest -v
```
Result: **47 passed, 0 failed** in 1.32s (the original 37 + 10 new in
`tests/test_equipment_status.py`: 4 parametrized "accepts each approved
status" cases, 2 parametrized "rejects vehicle-only status" cases, 1
distinct-vocabulary check, 1 "seeded equipment only uses approved
statuses" API check, 1 "vehicle status vocabulary unchanged" API check
(round-trips `LONG_TERM_PARKING` and `WORKING` through
`PATCH /vehicles/{id}/status`), 1 schema-level rejection check via
`EquipmentResponse.model_validate`). All 37 original tests still pass
unmodified.

**Frontend unit/component:**
```
cd frontend && npx vitest run
```
Result: **11 test files, 18 tests, 18 passed, 0 failed** (same count as
before — two existing equipment test fixtures were updated in place to
use a valid equipment status, `EquipmentDetailPage.test.tsx` gained one
new assertion that the equipment-specific Thai label renders; no test was
added or removed net).

**Frontend typecheck:**
```
npx tsc -b
```
Result: **exit 0, no type errors.**

**Frontend lint:**
```
npx oxlint
```
Result: **3 warnings** — identical pre-existing `react/set-state-in-effect`
warnings on `SystemStatusPage.tsx`, `EquipmentDetailPage.tsx`,
`VehicleDetailPage.tsx`. **0 errors.** No new warning introduced.

**Frontend production build:**
```
npm run build
```
Result: **PASSED.** `dist/index.html` 0.43 kB, `dist/assets/*.css` 7.75 kB
(2.10 kB gzip), `dist/assets/*.js` 285.15 kB (88.06 kB gzip — a ~0.06 kB
gzip increase from the new label maps/type).

**Frontend Playwright e2e:**
```
bash scripts/run_e2e_tests.sh
```
Result: **50 passed, 0 failed** (33.2s), across 5 viewport projects —
`smartphone-portrait`, the new `smartphone-landscape`, `tablet-portrait`,
the new `tablet-landscape`, `desktop` — each running the same 4 shell
tests + 6 vehicle/equipment tests as before (10 × 5 = 50). The 30 tests
that previously existed across 3 projects all still pass; the 20 new
results come from running the same, unmodified vehicle-equipment.spec.ts
tests against the 2 new projects, plus the 4 shell tests × 2 new
projects.

**Manual live-server re-verification:**
Started `uvicorn app.main:app` on a scratch port (`DATA_REPOSITORY=mock`)
again after the fix and confirmed live:
```
GET /api/v1/equipment?page_size=200
→ EQP-0001 operational_status: "IN_USE"
→ EQP-0002 operational_status: "READY"
→ EQP-0003 operational_status: "MAINTENANCE"
GET /api/v1/vehicles/VEH-1046
→ operational_status: "WORKING"   (unchanged — vehicle vocabulary untouched)
```
Server stopped afterward.

No test was skipped, disabled, or hidden in this correction. No claimed
result above was left unexecuted.

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
20. **No equipment status code was invented unless explicitly approved.** ORIGINAL FINDING: the existing vehicle status vocabulary was reused wholesale for equipment, which the register explicitly prohibited doing "automatically" — an open item, not a clean pass. **AFTER CORRECTION: YES** — equipment now uses `EquipmentOperationalStatus` (`READY`, `IN_USE`, `MAINTENANCE`, `OUT_OF_SERVICE`), explicitly approved by the user and recorded in `OPEN_DECISIONS_REGISTER_EN.txt` as C02's resolution; no additional/invented status beyond those four was introduced (verified by `test_equipment_and_vehicle_status_enums_are_distinct_vocabularies` and the `EquipmentOperationalStatus` enum itself having exactly 4 members).
21. **No strict vehicle status transition rules were invented unless explicitly approved.** YES — confirmed no transition matrix exists anywhere (backend accepts any status, frontend offers all statuses unconditionally).
22. **(Added after correction) No equipment status transition rules were invented.** YES — there is still no equipment status write endpoint at all in Phase 2 (only `GET`), so no transition logic of any kind exists to invent. The C02 resolution recorded in the register explicitly states it covers status codes only and that transition rules remain undefined/unapproved.

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
   - If it fails: screenshot in the failing orientation and note whether it's portrait or landscape specifically. (Landscape now has automated Playwright coverage too — see Section G's Correction Addendum update — so this manual pass is a real-device confidence check, not the only verification of landscape behavior.)

8. **Desktop test**
   - Prerequisite: standard desktop browser window (≥1280px wide).
   - Action: repeat items 1–4 at desktop width.
   - Expected: layout switches from stacked cards to a real table on the list pages; everything else behaves the same as mobile.
   - If it fails: screenshot + note the exact window width.

======================================================================
## K. FINAL VERDICT
======================================================================

### K.1 Original verdict (before correction) — historical record

PASS WITH KNOWN LIMITATIONS, Next phase readiness: NOT READY, blocked
specifically on the C02 unapproved decision. (Full original reasoning
preserved unchanged below in K.1 for the audit trail; superseded by K.2.)

**Blocking defects (original):** None — all suites passed. **Unapproved
decisions found (original):** C02 — Equipment Status Codes, as detailed
in Section B above. **Next phase readiness (original): NOT READY.**

### K.2 Verdict after the C02 / responsive-coverage correction — CURRENT

# PASS

**Blocking defects:**
None. The one blocking issue from the original verification — decision
C02 (Equipment Status Codes) resolved without approval — has been fixed:
the user explicitly approved a separate equipment status vocabulary
(`READY`, `IN_USE`, `MAINTENANCE`, `OUT_OF_SERVICE`), the implementation
now uses `EquipmentOperationalStatus` instead of reusing Vehicle's
`OperationalStatus`, and this is recorded as an approved/frozen decision
in `OPEN_DECISIONS_REGISTER_EN.txt`. Every automated test suite was
re-executed after the fix and passed (backend 47/47 — including 10 new
tests proving the vocabulary — frontend unit 18/18, e2e 50/50 — including
20 new results from the two new landscape viewport projects — typecheck
clean, build clean, lint 0 errors). Vehicle status behavior was
independently confirmed unchanged, live and by test. No frozen Phase 1
contract was touched by this correction.

**Known limitations (disclosed, unchanged from the original verification,
none of them blocking):**
- `GoogleSheetsRepository` has no real Google Sheets I/O yet; only the
  interface and declared tab/header schema exist (`validate_schema`
  still raises `NotImplementedError` unconditionally). This exactly
  matches the phase prompt's own sequencing instruction (scope item 14)
  and cannot be exercised in this sandboxed environment (no credentials,
  no network path to Google's API).
- No pager UI on the vehicle/equipment list pages despite the API
  supporting pagination (masked by the small seeded dataset).
- No RBAC/authorization beyond the fixed dev-auth context on the new
  write endpoints (`PATCH machine_no`, `PATCH status`) — consistent with
  the baseline's stated hardening-phase timeline, but a standing risk
  that should not be forgotten once real users exist.
- Equipment has no status-history/append-only tracking (only vehicles do)
  — acceptable since no acceptance test requires it this phase, and no
  equipment status-write endpoint exists yet for such history to record.
- Equipment status **transition rules** remain undefined/unapproved (by
  design — this correction resolved C02's status-*code* vocabulary only,
  per the user's explicit instruction not to define transition rules
  here). Any future equipment status-change endpoint must get its own
  transition-rule approval before shipping, the same way C01 (vehicle
  transitions) is still open.

**Open decisions intentionally deferred (correctly left unresolved):**
C01 (vehicle status transitions), the new equipment-status-transition gap
noted above (same category as C01, not separately numbered in the
register), C03 (equipment counters), A08 (soft delete), A09
(concurrency), B01 (live sheet schema validation), A01 (for
inspection/repair/PM/alert/command IDs — not yet needed), and every
domain area outside Phase 2's scope (D–M in the register).

**Unapproved decisions found:**
None remaining. C02 (Equipment Status Codes) — the only one found in the
original verification — is now resolved and approved (status-code
vocabulary only; see Section B and the Correction Addendum). No other
unapproved permanent decision was found during either pass of this
verification.

**Frozen Phase 1 contracts confirmed intact:**
`/api/v1` versioning; the common error envelope
(`{error:{code,message,details,request_id}}`); `Page`/`PageParams`
pagination shape; the opaque-prefixed stable-ID convention; ISO-8601 UTC
timestamps; the `Repository` ABC's `mode`/`check_ready` shape (extended,
not altered); `RequestContext`/`DEV_AUTH_MODE` behavior including the
production-safety guard in `main.py`; `StorageProvider`/local file
storage (untouched, not exercised by Phase 2); the mobile-first
foundation (`Card`, `ResponsiveTable`, `FormField`, the dialog
bottom-sheet pattern, mobile nav, and the 641px/1024px breakpoints now
exercised by two additional viewport projects) — all reused unchanged by
this correction, which only added `EquipmentOperationalStatus` and two
Playwright projects and did not touch any frozen Phase 1 file's shape or
behavior.

**Next phase readiness: READY**

Phase 2 has no remaining blocking defects, no remaining unapproved
permanent decisions, and full automated coverage across every viewport
band the baseline requires. Phase 3 may proceed when the user directs it
— not started as part of this task.

STOP HERE. Phase 3 was not started as part of this verification or its
correction.
