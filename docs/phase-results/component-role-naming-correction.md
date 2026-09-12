# Component Role Naming Correction

STATUS: Approved cross-phase contract correction, performed after approved
Web/API Phase 3 and **before** Phase 4. Phase 4 was **not** started. No
Phase 1–3 architecture was redesigned. No unrelated feature was added. No
open decision other than the naming vocabulary itself was resolved.

Documents read in full before making changes, as required:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/phase-results/web-phase-01-verification.md`
- `docs/phase-results/web-phase-02-verification.md`
- `docs/phase-results/web-phase-03-verification.md`

---

## 1. Approved Decision

The user explicitly approved the following Component Role vocabulary:

- `CARRIER_ENGINE` — engine used for the carrier / lower chassis /
  travelling side of the crane. Thai UI: "เครื่องยนต์ Carrier /
  เครื่องยนต์ช่วงล่าง".
- `CRANE_ENGINE` — engine used for the crane / superstructure side. Thai
  UI: "เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน".
- `PTO` — unchanged.

`CARRIER_ENGINE` and `CRANE_ENGINE` are physical/functional roles, not
first/second engine numbering. A vehicle is not required to have both — a
vehicle may have `CARRIER_ENGINE` only, `CARRIER_ENGINE` + `PTO`,
`CARRIER_ENGINE` + `CRANE_ENGINE`, or another valid combination. No fake
`CRANE_ENGINE` component was created for a machine that does not
physically have one. Counter types (`ENGINE_HOUR`, `PTO_HOUR`, `ODOMETER`)
are a separate concept from component role and are unchanged.

This decision is recorded as **C04** (APPROVED / FROZEN, vocabulary only)
in `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`.

## 2. Previous Vocabulary

`ENGINE_MAIN`, `ENGINE_SECONDARY` — now deprecated legacy names, no longer
valid authoritative `ComponentRole` values.

## 3. New Vocabulary

`CARRIER_ENGINE`, `CRANE_ENGINE`, `PTO` (and the pre-existing `VEHICLE`
component-role member, unaffected).

---

## 4. Impact Analysis (performed before editing)

Full-repository search for `ENGINE_MAIN`/`ENGINE_SECONDARY` found 12 files:

| File | Classification | Action taken |
|---|---|---|
| `backend/app/domain/vehicle_model.py` | Authoritative domain enum (`ComponentRole`) | Renamed members `ENGINE_MAIN→CARRIER_ENGINE`, `ENGINE_SECONDARY→CRANE_ENGINE`; docstring updated |
| `backend/app/domain/vehicle.py` | Authoritative code — only imports the `ComponentRole` type, no literal value | No change needed |
| `backend/app/api/v1/vehicle_schemas.py` | API contract — only imports the `ComponentRole` type, no literal value | No change needed (automatically inherits the new enum) |
| `backend/app/repositories/google_sheets/schemas.py` | Google Sheets schema — declares the `component_role` **header name** only, no literal enum values | No change needed |
| `backend/app/repositories/mock/repository.py` | MockRepository — reads `ComponentRole` via the domain model, no literal value | No change needed |
| `backend/app/repositories/mock/seed_data.py` | Mock/dev seed data + Thai component labels | Migrated (see Section 6) |
| `backend/tests/test_vehicle_models_api.py`, `test_vehicles_api.py` | Test assertions | Updated to new vocabulary; one new test added (`test_single_engine_model_does_not_fabricate_a_crane_engine`) |
| `frontend/src/lib/types.ts` | Frontend type union (`ComponentRole`) | Updated |
| `frontend/src/lib/labels.ts` | Frontend Thai label map | Updated to the approved Thai wording |
| `frontend/src/pages/VehicleDetailPage.test.tsx`, `VehicleListPage.test.tsx` | Frontend test fixtures | Updated |
| `frontend/e2e/vehicle-equipment.spec.ts` | Playwright e2e assertions against real seed data | Updated to the approved Thai wording |
| `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt` (§10 COUNTERS) | Governance doc, FROZEN section, illustrative example only | Example updated; the FROZEN counter *concept* (`vehicle_id → component_id → counter_type → value`) itself is untouched; correction note added |
| `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt` (§4, §16) | Baseline requirements doc, illustrative examples | Examples updated; correction note added |
| `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` | Governance register | New decision **C04** added (approved/frozen) |
| `docs/phase-results/web-phase-02-result.md`, `web-phase-02-verification.md` | **Historical phase records** | **Left untouched** — history must not be silently overwritten; this correction is recorded as a new, separate report instead |
| `CHANGELOG.md` | Historical changelog | Left untouched; a **new** entry appended documenting this correction |

**Proposed migration method:** direct rename with no legacy-input
compatibility shim (justification in Section 5).

**Ambiguous data found:** **None.** See Section 6.

---

## 5. Migration / Compatibility Behavior

Checked whether the project currently persists or exposes
`ENGINE_MAIN`/`ENGINE_SECONDARY` through each surface named in the task:

| Surface | Exposed? | Detail |
|---|---|---|
| API responses | Yes (read-only) | `GET /api/v1/models/{id}` and `GET /api/v1/vehicles/{id}` echoed the enum value in `component_roles`/`component_role`. No API endpoint has ever **accepted** a client-supplied `component_role` as input — models/components are read-only in Phase 1–3 (`Create/update/delete not implemented` per Phase 2 verification). |
| Google Sheets columns | No | `schemas.py` declares only the header name `component_role`; no live Google Sheets I/O exists yet (`validate_schema()` still raises `NotImplementedError` unconditionally, confirmed unchanged by this correction) and no enum literal is declared in the schema file. |
| Mock data | Yes | `MockRepository`'s in-memory seed data (`seed_data.py`) — migrated, see Section 6. This is development/test data only, regenerated fresh on every process start; it is not a persisted store. |
| Historical records | No | The only append-only history table in Phase 1–3 is `VehicleStatusHistoryEntry` (vehicle **operational status**, not component role). No historical/immutable record anywhere stores a `component_role` value, so no historical-reconstruction risk exists. |
| Frontend state | Yes (derived from the API) | `types.ts`/`labels.ts` — updated. |
| Tests | Yes | Backend and frontend tests — updated. |

**Conclusion:** because (a) no write endpoint ever accepted a
client-supplied `component_role`, and (b) no persisted/historical record
ever stored the old names, there is **no real backward-compatibility
requirement** to satisfy. A legacy-input parsing/normalization layer was
therefore **not implemented** — adding one here would create exactly the
"permanent dual vocabulary" the task instructs against, with no
corresponding need. This is proven, not assumed: see
`backend/tests/test_component_role_naming.py::test_no_legacy_normalization_path_exists_for_the_old_names`
and `::test_api_output_never_emits_legacy_component_role_names`.

New writes and authoritative API/domain output use only `CARRIER_ENGINE`,
`CRANE_ENGINE`, `PTO` (and `VEHICLE`). `ENGINE_MAIN`/`ENGINE_SECONDARY` are
rejected outright by the `ComponentRole` enum and by every Pydantic schema
that type-references it (`VehicleModelResponse.component_roles`,
`VehicleComponentResponse.component_role`) — confirmed by
`ValidationError`/`ValueError` tests.

## 6. Ambiguous Data Found

**None.** All `ENGINE_MAIN`/`ENGINE_SECONDARY` occurrences before this
correction were `MockRepository` in-memory seed/test data (Phase 1–3 have
no real imported company data — Google Sheets I/O is not yet live). The
mapping used a known, non-guessed rule rather than blind ordinal
position:

- `MODEL-0002` (XCT80, the one seeded dual-engine model) — its own Thai
  description already reads "รถเครนล้อยาง เครื่องยนต์คู่ (ขับเคลื่อน +
  ยกเครน)" ("dual-engine wheel crane: drive/carrier + crane-lift"),
  independently naming which engine is which role. This is direct
  evidence, not an inferred ordinal mapping:
  `ENGINE_MAIN → CARRIER_ENGINE` ("ขับเคลื่อน" = drive/carrier),
  `ENGINE_SECONDARY → CRANE_ENGINE` ("ยกเครน" = crane-lift).
- `MODEL-0001` (QY50) and `MODEL-0003` (GR-250) are single-engine models
  (Thai description "เครื่องยนต์เดียว" = single engine) that previously
  declared only `ENGINE_MAIN` + `PTO`. These became `CARRIER_ENGINE` +
  `PTO` — **no `CRANE_ENGINE` was fabricated** for these single-engine
  machines, per the explicit modeling rule against inventing a
  crane-engine component that doesn't physically exist.

No record required the "do not guess — report it" fallback.

---

## 7. Files Affected

**Backend (authoritative code):**
- `backend/app/domain/vehicle_model.py` — `ComponentRole` enum renamed.
- `backend/app/repositories/mock/seed_data.py` — seed data + Thai labels migrated.

**Backend (tests):**
- `backend/tests/test_vehicle_models_api.py` — updated + 1 new test.
- `backend/tests/test_vehicles_api.py` — updated.
- `backend/tests/test_component_role_naming.py` — **new**, 11 tests covering the Test Requirements below.

**Frontend:**
- `frontend/src/lib/types.ts` — `ComponentRole` type union.
- `frontend/src/lib/labels.ts` — Thai label map.
- `frontend/src/pages/VehicleDetailPage.test.tsx`, `VehicleListPage.test.tsx` — fixtures updated.
- `frontend/e2e/vehicle-equipment.spec.ts` — assertions updated.

**Governance:**
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` — new decision C04 (APPROVED/FROZEN).
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt` — §10 example updated + correction note.
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt` — §4, §16 examples updated + correction note.
- `CHANGELOG.md` — new entry appended (history preserved, not rewritten).
- `docs/phase-results/component-role-naming-correction.md` — this report.

**Explicitly left untouched (historical record, per guardrail §6 "Historical transactions must not be silently overwritten"):**
- `docs/phase-results/web-phase-02-result.md`
- `docs/phase-results/web-phase-02-verification.md`

---

## 8. API Impact

- `GET /api/v1/models`, `GET /api/v1/models/{id}`: `component_roles` now
  returns `CARRIER_ENGINE`/`CRANE_ENGINE` instead of
  `ENGINE_MAIN`/`ENGINE_SECONDARY`. No other field, shape, or status code
  changed.
- `GET /api/v1/vehicles/{id}`: `components[].component_role` same change.
- No endpoint accepts `component_role` as input (read-only in Phase 1–3),
  so there is no request-schema breaking change to reason about.
- `vehicle_id`, `model_id`, `component_id` values are **byte-for-byte
  unchanged** — proven by
  `test_stable_vehicle_and_component_ids_are_unchanged_by_the_rename`.
- Error envelope, `/api/v1` versioning, and all other Phase 1–3 frozen
  contracts are untouched.

## 9. Google Sheets Impact

None. The declared `vehicle_components` tab schema
(`backend/app/repositories/google_sheets/schemas.py`) only names the
header `component_role`; it carries no enum literal to migrate. Live
Google Sheets I/O is not implemented in any phase to date
(`validate_schema()` still raises `NotImplementedError` unconditionally,
unchanged by this correction).

## 10. Frontend Impact

- `ComponentRole` type and `componentRoleLabel` Thai label map updated.
- `VehicleDetailPage` (consumes `componentRoleLabel` indirectly via
  `labels.ts`) automatically renders the new Thai wording — no page
  component code needed to change.
- Test fixtures (unit + Playwright) updated to the new vocabulary.

## 11. Historical-Data Impact

None. No append-only/immutable history table stores `component_role`
(only vehicle **status** history exists, which is a different field).
Vehicle/model/component identity fields (`vehicle_id`, `model_id`,
`component_id`) are unchanged, so no historical reconstruction is
affected.

---

## 12. Exact Tests Executed / Results

All commands below were executed directly in this session against the
current working tree, after the code changes described above.

**Backend — pytest**
```
$ cd backend && source .venv/bin/activate && DATA_REPOSITORY=mock python -m pytest -q
95 passed, 8 warnings in 2.55s
```
(82 pre-existing Phase 1–3 tests + 13 new/updated: 1 new test in
`test_vehicle_models_api.py`, 11 new tests in the new
`test_component_role_naming.py`, plus the pre-existing assertions in
`test_vehicles_api.py`/`test_vehicle_models_api.py` updated in place to
the new vocabulary rather than added as new tests. The 8 warnings are the
pre-existing `HTTP_422_UNPROCESSABLE_ENTITY` Starlette deprecation notice,
unrelated to this change — same category present since Phase 1.)

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npx vitest run
Test Files  15 passed (15)
     Tests  32 passed (32)
```

**Frontend — typecheck**
```
$ npx tsc -b
(exit code 0 — PASSED)
```

**Frontend — lint**
```
$ npx oxlint
6 warnings, 0 errors — same pre-existing react(set-state-in-effect)
category present since Phase 1/2/3, no new warning introduced.
```

**Frontend — production build**
```
$ npm run build
dist/index.html                   0.43 kB │ gzip:  0.31 kB
dist/assets/index-*.css           9.46 kB │ gzip:  2.40 kB
dist/assets/index-*.js          300.33 kB │ gzip: 90.84 kB
✓ built in 529ms
```
PASSED.

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
85 passed (52.2s)
```
Ran across `smartphone-portrait` (375×667), `smartphone-landscape`
(568×320), `tablet-portrait` (768×1024), `tablet-landscape` (1024×768),
`desktop` (1280×800) — 17 tests × 5 projects. Includes the updated
`vehicle-equipment.spec.ts` assertion for the new Thai component-role
labels, and the full, unmodified `inspection.spec.ts` suite (proving
Phase 3 inspection behavior is unaffected).

No test was skipped, disabled, or hidden. No result above was claimed
without being executed in this session.

**New tests added** (`backend/tests/test_component_role_naming.py`),
mapped to the Test Requirements:

1. `test_carrier_engine_is_accepted` ✓
2. `test_crane_engine_is_accepted` ✓
3. `test_pto_remains_accepted` ✓
4. `test_engine_main_is_rejected_for_new_authoritative_writes` ✓
5. `test_engine_secondary_is_rejected_for_new_authoritative_writes` ✓
6. `test_no_legacy_normalization_path_exists_for_the_old_names` +
   `test_api_output_never_emits_legacy_component_role_names` ✓ (no legacy
   path was implemented, per Section 5's reasoning; both tests prove
   the old names are rejected everywhere and never emitted)
7. `test_vehicle_may_contain_carrier_engine_without_crane_engine` ✓ (VEH-1046)
8. `test_vehicle_may_contain_both_carrier_and_crane_engine` ✓ (VEH-1047)
9. `test_vehicle_may_contain_carrier_engine_and_pto` ✓ (VEH-1046)
10. `test_multi_engine_vehicle_components_are_distinguishable_by_id_and_role` ✓
11. `test_stable_vehicle_and_component_ids_are_unchanged_by_the_rename` ✓
12. Phase 3 inspection behavior unaffected — proven by the full,
    unmodified `test_inspections_api.py`/`test_inspection_item_level_rules.py`/
    `test_attachment_upload_validation.py` suites (part of the 95/95 pass)
    and the full `inspection.spec.ts` Playwright suite (part of the 85/85
    pass) continuing to pass unchanged.
13. Vehicle `OperationalStatus`/`EquipmentOperationalStatus` unaffected —
    proven by `test_equipment_status.py` and vehicle status-history tests
    continuing to pass unchanged (part of the 95/95 pass); no code in this
    correction touches either enum.
14. Permanent QR behavior unaffected — proven by
    `vehicle-equipment.spec.ts`'s QR-route tests ("scanning the QR route
    opens the Vehicle Detail page directly", "equipment detail is
    reachable at its own stable QR route") continuing to pass unchanged
    across all 5 viewports.

---

## 13. Known Limitations

- No legacy-input compatibility layer exists for `ENGINE_MAIN`/
  `ENGINE_SECONDARY` (by design — see Section 5). If a future integration
  is discovered that already persisted these old values outside this
  repository (e.g., a real spreadsheet populated before this correction),
  that data would need a one-time explicit migration script at that time;
  no such data exists today.
- This correction does not touch or resolve any other open decision
  (A01–A10, B01–B04, C01–C03, D01–D04, etc.) — all remain exactly as
  Phase 3's verification left them.
- Component-based counters (`ENGINE_HOUR`/`PTO_HOUR`/`ODOMETER`) remain
  entirely unimplemented (Phase 8/IoT scope) — this correction only
  changes the component-role vocabulary they will eventually key off of.

## 14. Confirmation Phase 4 Was Not Started

Confirmed: no Phase 4 file
(`docs/claude-prompts/web-api/04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt`) scope
item was implemented. No PM, repair, or work-order domain code exists
anywhere in the repository (grep-verified). Only the component-role
vocabulary and its direct dependents (seed data, tests, labels,
governance docs) were touched.

---

## Final Verdict

# PASS

**Blocking defects:** None. All backend, frontend, and e2e suites pass in
full after the correction.

**Blocking defects — Legacy compatibility retained:** NO
**Legacy names emitted by new API responses:** NO
**Ambiguous real data found:** NO
**Stable IDs changed:** NO
**Phase 1–3 regression status:** PASS — 95/95 backend, 32/32 frontend
unit, typecheck/lint/build clean, 85/85 Playwright e2e (5/5 required
viewports), all re-executed in this session.
**Ready to begin Phase 4:** READY (this correction does not itself
authorize starting Phase 4 — it only clears one naming-vocabulary item;
Phase 4 was not started as part of this task per explicit instruction).
