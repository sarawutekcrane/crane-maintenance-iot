# Component Role Naming Correction — Independent Verification

STATUS: AUDIT ONLY. This report performs no implementation, starts no
Phase 4 work, redesigns no approved Phase 1–3 architecture, changes no
stable ID, changes no counter-type semantics, and resolves no unrelated
governance decision.

**Process note:** this verification began before the correction had been
pushed to `web/component-role-naming`. An initial pass of this audit
found the branch tip at `fab84e3` (end of Phase 3) with no correction
present anywhere — no code change, no `component-role-naming-correction.md`,
no governance entry — and drafted a FAIL report on that basis. Before that
draft was pushed, `git push` was rejected as non-fast-forward; `git fetch`
+ `git pull --rebase` revealed a new commit, `df3db37` ("Correct Component
Role vocabulary: CARRIER_ENGINE/CRANE_ENGINE replace
ENGINE_MAIN/ENGINE_SECONDARY"), had landed on the remote branch in the
interim. This report is the actual, complete verification performed
**against `df3db37`** — every section below re-examines the real diff,
independently re-runs every test suite, and re-derives its own verdict.
The earlier "correction does not exist" draft is superseded in full and
not reproduced here.

Branch verified: `web/component-role-naming` @ `df3db37`
("Correct Component Role vocabulary: CARRIER_ENGINE/CRANE_ENGINE replace
ENGINE_MAIN/ENGINE_SECONDARY"), on top of `fab84e3` (the approved, frozen
Phase 3 tip). `git status` is clean; this audit made no code changes.

Documents read in full before verifying, as instructed:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/phase-results/web-phase-01-verification.md`
- `docs/phase-results/web-phase-02-verification.md`
- `docs/phase-results/web-phase-03-verification.md`
- `docs/phase-results/component-role-naming-correction.md`

Plus a direct read of the full `df3db37` diff (every file, not summarized
from the correction report's own claims), and independent re-execution of
every automated test suite in this session (Section L).

---

## A. Repository-Wide Legacy Name Audit

Repository-wide search for `ENGINE_MAIN` and `ENGINE_SECONDARY` (tracked
files only; build artifacts and `__pycache__` — both gitignored, both
stale local build output from before this session's `git pull` —
excluded as not part of the repository):

| Location | Occurrence | Classification |
|---|---|---|
| `backend/app/domain/vehicle_model.py:28` (docstring) | "`ENGINE_MAIN`/`ENGINE_SECONDARY` are deprecated legacy names..." | **acceptable migration note** — explicitly marks them non-authoritative |
| `backend/tests/test_component_role_naming.py` (8 occurrences) | Names used only as *rejection* test inputs (`pytest.raises(ValueError)`, "not in valid_values", "not in models_text"/"not in detail_text") | **acceptable** — this is a test proving the old names are rejected and never emitted, not active use of them as valid data |
| `CHANGELOG.md` | New entry documenting the correction, naming the old values it replaced | **acceptable changelog/history** |
| `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` (new C04 entry) | Names the deprecated values explicitly as deprecated | **acceptable governance record** |
| `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt` (correction note) | Same | **acceptable governance record** |
| `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt` (correction note) | Same | **acceptable governance record** |
| `docs/phase-results/component-role-naming-correction.md` | The correction report itself, describing what was replaced | **acceptable migration note** |
| `docs/phase-results/component-role-naming-verification.md` | This report | **acceptable migration note** |
| `docs/phase-results/web-phase-02-result.md`, `web-phase-02-verification.md` | Historical Phase 2 reports, predating the correction | **acceptable historical record/documentation** — confirmed byte-for-byte untouched by `df3db37` (`git diff fab84e3 df3db37 -- <these files>` is empty) |

**No forbidden authoritative code and no forbidden active test/data
occurrence was found.** Every remaining occurrence of the old names is
either a deprecation note, a rejection-test assertion, a
changelog/governance record, or an untouched historical report — exactly
the categories the task marks acceptable. The domain enum
(`ComponentRole`), the API schemas that type-reference it, the mock
repository/seed data, the frontend type union, the frontend label map,
and every non-rejection test now use only `CARRIER_ENGINE`/
`CRANE_ENGINE`/`PTO`/`VEHICLE` — independently confirmed by reading the
actual diff (Section B) and by the live-response assertions in
`test_api_output_never_emits_legacy_component_role_names` (passing, see
Section L).

No historical record was rewritten by this correction or by this audit.

---

## B. Authoritative Vocabulary Review

Verified by reading the actual code at `df3db37`, not by trusting the
correction report's table:

| Layer | Vocabulary after correction | Verified how |
|---|---|---|
| Backend domain enum (`vehicle_model.py:23-26`) | `CARRIER_ENGINE`, `CRANE_ENGINE`, `PTO`, `VEHICLE` | Direct read of the enum definition |
| API schemas/responses (`vehicle_schemas.py`) | Type-references `ComponentRole` only (`component_roles: list[ComponentRole]`, `component_role: ComponentRole`) — no literal values to update, automatically inherits the corrected enum | Direct read; confirmed no hardcoded string literal of either old or new role name anywhere in this file |
| Repository data (`MockRepository`) | Reads `ComponentRole` via the domain model; no literal value | Direct read of `repository.py` — zero references to role names as string literals |
| MockRepository seed data (`seed_data.py`) | `MODEL-0001`/`MODEL-0003`: `[CARRIER_ENGINE, PTO]`; `MODEL-0002`: `[CARRIER_ENGINE, CRANE_ENGINE, PTO]`; Thai labels updated to the approved wording | Direct diff read (Section B of the correction report matches exactly what the diff shows) |
| Google Sheets mapping/schema (`google_sheets/schemas.py`) | Declares only the header name `component_role`; carries no enum literal | Direct read — confirmed no literal role value anywhere in this file, before or after the correction |
| Frontend types (`types.ts:18`) | `'CARRIER_ENGINE' \| 'CRANE_ENGINE' \| 'PTO' \| 'VEHICLE'` | Direct diff read |
| Frontend labels (`labels.ts:44-49`) | `เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง`, `เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน` | Direct diff read |
| Vehicle detail/list rendering | Consumes `componentRoleLabel` from `labels.ts`; no page-level code needed to change (confirmed: no diff to `VehicleDetailPage.tsx`/`VehicleListPage.tsx` themselves) | `git show df3db37 --stat` — these page files are absent from the changed-file list, only their *test fixtures* changed |
| Tests | All non-rejection tests now assert the new vocabulary; `test_component_role_naming.py` explicitly proves rejection of the old one | Direct diff read + independent re-run (Section L) |
| Current governance/baseline docs | `OPEN_DECISIONS_REGISTER_EN.txt` C04, `PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt` §10, `00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt` §4/§16 all updated with the new vocabulary and an explicit correction note; the FROZEN counter-model *concept* text (`vehicle_id -> component_id -> counter_type -> value`) is untouched | Direct diff read |

- **Is `ENGINE_MAIN` rejected for new authoritative use?** YES —
  `ComponentRole("ENGINE_MAIN")` raises `ValueError` (verified by direct
  code read of the enum and by re-running
  `test_engine_main_is_rejected_for_new_authoritative_writes`, which also
  proves `VehicleComponentResponse.model_validate(...)` raises
  `ValidationError` for a payload carrying the old value).
- **Is `ENGINE_SECONDARY` rejected for new authoritative use?** YES, same
  evidence, symmetric test.
- **Does new API output ever emit legacy names?** NO — independently
  re-run `test_api_output_never_emits_legacy_component_role_names`,
  which calls the live `GET /api/v1/models` and
  `GET /api/v1/vehicles/{VEH-1046,1047,1048}` endpoints and asserts
  `"ENGINE_MAIN"`/`"ENGINE_SECONDARY"` are absent from every response
  body. Passed (Section L).

---

## C. Semantic Correctness Review

Verified directly against the live seed data and API, not merely the
correction report's narrative:

- `CARRIER_ENGINE`/`CRANE_ENGINE` are **not** encoded as first/second by
  position: `VehicleModel.component_roles` is an unordered
  `list[ComponentRole]`, and the `_components_for()` seed-generation
  function (`seed_data.py:105-117`) assigns `component_id` sequentially
  by iteration order of that list, not by any special-cased "engine 1 /
  engine 2" logic. Renaming the enum members did not introduce any
  ordinal encoding.
- **A vehicle may have only `CARRIER_ENGINE`:** confirmed live —
  `VEH-1046` and `VEH-1048` (single-engine models `MODEL-0001`/
  `MODEL-0003`) expose `{CARRIER_ENGINE, PTO}`, with `CRANE_ENGINE`
  **absent**. Independently re-ran
  `test_vehicle_may_contain_carrier_engine_without_crane_engine` (asserts
  `"CRANE_ENGINE" not in roles` for `VEH-1046`) — passed.
- **A vehicle may have `CARRIER_ENGINE` + `PTO`:** same evidence —
  `test_vehicle_may_contain_carrier_engine_and_pto` — passed.
- **A vehicle may have `CARRIER_ENGINE` + `CRANE_ENGINE`:** confirmed
  live for `VEH-1047` (dual-engine `MODEL-0002`) —
  `test_vehicle_may_contain_both_carrier_and_crane_engine` — passed.
- **`CRANE_ENGINE` is not fabricated for vehicles that do not physically
  have one:** confirmed — `MODEL-0001`/`MODEL-0003` (Thai description
  "เครื่องยนต์เดียว" = single-engine) declare only `[CARRIER_ENGINE, PTO]`;
  no `CRANE_ENGINE` member was added to either. Independently re-ran
  `test_single_engine_model_does_not_fabricate_a_crane_engine` (new test,
  asserts `MODEL-0001`'s `component_roles == {CARRIER_ENGINE, PTO}` exactly)
  — passed.
- **Two distinct, independently addressable engine components on a
  dual-engine vehicle:** `test_multi_engine_vehicle_components_are_distinguishable_by_id_and_role`
  confirms `VEH-1047` has exactly 2 engine-role components with 2 distinct
  `component_id` values and both roles present — a necessary precondition
  for any future component-keyed counter (`component_id -> counter_type
  -> value`) to work correctly without conflating the two engines —
  passed.

**No evidence of `CARRIER_ENGINE == first engine` / `CRANE_ENGINE ==
second engine` ordinal treatment anywhere in code, seed data, or tests.**
The roles remain physical/functional, matching the approved decision.

---

## D. Mock / Seed Data Migration Review

Every seed record that carried `ENGINE_MAIN`/`ENGINE_SECONDARY` before
the correction, and its migration, independently re-derived from the
actual diff and seed file (not copied from the correction report):

| Model | Previous roles | New roles | Evidence supporting the mapping | Guess required? |
|---|---|---|---|---|
| `MODEL-0001` (Zoomlion QY50) | `ENGINE_MAIN`, `PTO` | `CARRIER_ENGINE`, `PTO` | Model's own Thai description: "รถเครนล้อยาง เครื่องยนต์เดียว" (single-engine wheel crane) — only one engine exists, so the sole engine role is necessarily the carrier/drive engine (a wheel crane's only engine drives the chassis; there is nothing else it could be) | NO |
| `MODEL-0002` (XCMG XCT80) | `ENGINE_MAIN`, `ENGINE_SECONDARY`, `PTO` | `CARRIER_ENGINE`, `CRANE_ENGINE`, `PTO` | Model's own Thai description: "เครื่องยนต์คู่ (ขับเคลื่อน + ยกเครน)" — "dual engine (**ขับเคลื่อน** = drive/carrier + **ยกเครน** = crane-lift)". This is a direct, named statement of which engine does which job, not an inferred ordinal mapping. `ENGINE_MAIN` (declared first, matching "drive") → `CARRIER_ENGINE`; `ENGINE_SECONDARY` (declared second, matching "crane-lift") → `CRANE_ENGINE` | NO — the model's own source text names both roles explicitly |
| `MODEL-0003` (Tadano GR-250) | `ENGINE_MAIN`, `PTO` | `CARRIER_ENGINE`, `PTO` | Same reasoning as `MODEL-0001`: "รถเครนล้อยาง เครื่องยนต์เดียว" (single-engine) | NO |

No vehicle record directly carries a `component_role` field independent
of its model's `component_roles` — vehicle components are generated from
the model's declared roles at seed-build time
(`build_seed_components()`/`_components_for()`), so migrating the three
models above is equivalent to migrating all affected vehicle component
records (`VEH-1046`→`MODEL-0001`, `VEH-1047`→`MODEL-0002`,
`VEH-1048`→`MODEL-0003`).

**No ambiguous record exists.** Every migrated record's mapping is
directly supported by that record's own pre-existing Thai description
text, not inferred from position or guessed. Per the task's rule, this
does not block a PASS verdict.

---

## E. Real Data / Google Sheets Impact

Checked independently (not assumed from the correction report):

- **Current project data source assumption:** `DATA_REPOSITORY=mock` is
  the only mode exercised by any script/test in this repository; no
  `.env` file with real Google credentials exists (confirmed clean, same
  as every prior phase's security review).
- **Google Sheets implementation status:** `GoogleSheetsClient.validate_schema()`
  still unconditionally raises `NotImplementedError`
  (confirmed unchanged by `df3db37` — this file is not in the commit's
  changed-file list). No live write/read path to a real spreadsheet
  exists anywhere in the codebase.
- **Repository write/read behavior:** `MockRepository` is fully
  in-memory, rebuilt fresh on every process start; no on-disk data file
  of any kind exists in the repository (`find` for JSON/data files
  returned nothing, matching Phase 1–3's own findings).
- **Historical snapshots/events / component history:** no such feature
  exists in the codebase yet (IoT/counter phases have not started). The
  only append-only history table in the entire codebase,
  `VehicleStatusHistoryEntry`, tracks vehicle **operational status**
  (`WORKING`/`READY`/etc.), a completely different field from
  `component_role` — confirmed by reading `backend/app/domain/vehicle.py`
  directly. No historical record of any kind stores a `component_role`
  value, so there is no persisted-legacy-value question to answer for
  history specifically.

**Report: NO REAL LEGACY DATA EXISTS.**

This holds both because no real company data source is connected in this
environment (mock-only architecture) and because, even within the mock
architecture, no persisted/historical table ever stored a
`component_role` value that could now be stale.

**What must happen before a future live Google Sheets migration:** the
correction report's Section 13 (Known Limitations) already states this
explicitly: "If a future integration is discovered that already
persisted these old values outside this repository (e.g., a real
spreadsheet populated before this correction), that data would need a
one-time explicit migration script at that time; no such data exists
today." This is adequate disclosure — it names the exact future
precondition (an explicit migration step at the moment Google Sheets I/O
actually goes live) rather than leaving it unstated.

---

## F. Stable ID Integrity

Independently verified by reading the seed data and by re-running the
correction's own ID-stability test, not by trusting its claim:

- `vehicle_id` values (`VEH-1046`, `VEH-1047`, `VEH-1048`) — unchanged;
  no line in the diff touches the `Vehicle(...)` constructor calls'
  `vehicle_id` arguments.
- `model_id` values (`MODEL-0001/2/3`) — unchanged, same evidence.
- `component_id` values — generated by `_components_for()` as
  `f"CMP-{next_id + index:04d}"`, a pure function of iteration order and
  a `next_id` counter passed in from `build_seed_components()`; the
  *labels and roles* inside each `VehicleComponent` changed, but the ID
  generation logic itself is untouched by the diff (`_components_for`'s
  body has no diff hunk). Independently re-ran
  `test_stable_vehicle_and_component_ids_are_unchanged_by_the_rename`,
  which asserts `VEH-1047`'s components are exactly
  `{CMP-0003, CMP-0004, CMP-0005}` — passed.
- `equipment_id`, `checklist_id`, `inspection_id`, `finding_id`,
  `attachment_id` — none of these domains' code was touched by `df3db37`
  at all (absent from the changed-file list); their generation logic is
  byte-for-byte the Phase 3 tip.

**Stable IDs changed: NO.**

---

## G. Counter Model Review

- Repository-wide search confirms: `ENGINE_HOUR`, `PTO_HOUR`, `ODOMETER`,
  `counter_type` appear **only** in governance/prompt documents
  (`PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`,
  `00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`, and not-yet-started Phase
  4/5 prompt files). **No counter implementation exists anywhere in
  `backend/app` or `frontend/src`**, confirmed both before and after this
  correction — `df3db37` touches no counter-related file. This is stated
  plainly rather than fabricated: no counter test evidence is claimed
  anywhere in this report.
- The correction updated only the *illustrative example* text in the two
  frozen governance documents (`CARRIER_ENGINE -> ENGINE_HOUR`,
  `CRANE_ENGINE -> ENGINE_HOUR`, replacing the old example
  `ENGINE_MAIN -> ENGINE_HOUR`/`ENGINE_SECONDARY -> ENGINE_HOUR`). The
  FROZEN counter *concept* itself — `vehicle_id -> component_id ->
  counter_type -> value` — is untouched, verified by direct diff read
  (Section B above): only the two example lines changed, the surrounding
  frozen sentence is identical before and after.
- Counter *type* names (`ENGINE_HOUR`/`PTO_HOUR`/`ODOMETER`) are
  role-independent labels and were not renamed, touched, or reinterpreted
  by this correction.

**Counter semantics changed: NO.**

---

## H. Legacy Compatibility Audit

**Legacy compatibility retained: NO.**

Verified directly:
- `ComponentRole` has exactly the 4 members `CARRIER_ENGINE`,
  `CRANE_ENGINE`, `PTO`, `VEHICLE` — no parallel `ENGINE_MAIN`/
  `ENGINE_SECONDARY` member coexists alongside them.
- No normalization/translation function exists anywhere that maps an
  incoming `"ENGINE_MAIN"`/`"ENGINE_SECONDARY"` string to
  `CARRIER_ENGINE`/`CRANE_ENGINE` — confirmed by reading every file in
  the diff plus a repository-wide search for any function referencing
  both an old and a new role name together (none found outside the
  rejection-test file, which explicitly tests that no such path exists:
  `test_no_legacy_normalization_path_exists_for_the_old_names`,
  independently re-run and passing).
- **Why this is safe, not a gap:** no write endpoint in Phase 1–3 ever
  accepted a client-supplied `component_role` (models/vehicle components
  are read-only — confirmed independently by re-reading
  `backend/app/api/v1/vehicles.py`'s router, which defines no
  POST/PATCH/PUT accepting a `component_role` field), and no persisted/
  historical table stores this field (Section E). With no write path and
  no historical record, there is nothing for a compatibility shim to
  bridge — introducing one would only recreate a permanent dual
  vocabulary with no corresponding real need, which the task instructs
  against.

---

## I. Governance Review

Verified by reading the actual register diff, not the correction
report's paraphrase:

- `OPEN_DECISIONS_REGISTER_EN.txt` now has a new **C04** entry (Section
  C, VEHICLE/EQUIPMENT), correctly recording:
  - ✅ `CARRIER_ENGINE`
  - ✅ `CRANE_ENGINE`
  - ✅ `PTO` (unchanged)
  - ✅ old `MAIN`/`SECONDARY` names explicitly marked "deprecated legacy
    names... not valid authoritative roles for new data"
  - ✅ "physical/functional roles, not first/second engine numbering"
  - ✅ "A vehicle is not required to have both roles" with explicit valid
    combinations listed
  - ✅ "Counter types (ENGINE_HOUR, PTO_HOUR, ODOMETER) are a separate
    concept from component role and remain unchanged by this decision"
  - Status is `APPROVED / FROZEN (vocabulary only)` — correctly scoped,
    mirroring how C02 was scoped to "status-code vocabulary only" and
    explicitly states it does **not** resolve any other decision
    ("including A02, A03, C01, C03").
- **No unrelated Open Decision was accidentally resolved or changed:**
  confirmed by diffing the full register file — the only hunk added is
  the new C04 block; C01, C02, C03, and every A/B/D–M entry is
  byte-for-byte unchanged from the Phase 3-verified state.

**Governance record is complete and correctly scoped.**

---

## J. Prior-Phase Regression Review

Re-confirmed live in this session (Section L), and by reading the diff
directly rather than trusting the correction report's file list:

**Phase 1:** `/api/v1` convention, error envelope, repository/storage
abstraction, and responsive foundation — none of these files appear
anywhere in the `df3db37` diff. Independently confirmed intact by the
full re-run in Section L (all Phase 1-origin tests are part of the
95/32/85 passing totals).

**Phase 2:** `vehicle_schemas.py`/`equipment_schemas.py`, equipment
status separation (`EquipmentOperationalStatus`), and the permanent QR
routes (`/vehicle/{vehicle_id}`, `/equipment/{equipment_id}` in
`App.tsx`) — none of these files are in the diff. Stable vehicle IDs
confirmed unchanged (Section F).

**Phase 3:** `inspection_service.py`, `checklist.py`, attachment
validation, and the Phase 3 correction's item-level FAIL rules — none of
these files are in the `df3db37` diff. The full, unmodified
`test_inspections_api.py`/`test_inspection_item_level_rules.py`/
`test_attachment_upload_validation.py` suites and the full
`inspection.spec.ts` Playwright suite continue to pass unchanged, part
of the 95/85 totals re-run independently in Section L.

**No regression found in any prior phase**, confirmed by direct diff
inspection (this correction's changed-file list touches only
`vehicle_model.py`, seed data, 5 test files, 1 new test file, 3
governance/baseline docs, and `CHANGELOG.md` — no Phase 1/2/3 domain
service, route, or page file appears anywhere in it) and by an
independent full-suite re-run.

---

## K. Frontend / Thai Label Review

Verified live by reading `frontend/src/lib/labels.ts` at `df3db37`:

```
CARRIER_ENGINE: 'เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง'
CRANE_ENGINE: 'เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน'
PTO: 'ระบบส่งกำลัง (PTO)'
```

This matches the task's approved wording exactly (`เครื่องยนต์ Carrier /
เครื่องยนต์ช่วงล่าง` for carrier-side, `เครื่องยนต์ Crane /
เครื่องยนต์ชุดเครน` for crane-side).

- **Does the UI still present `เครื่องยนต์หลัก`/`เครื่องยนต์รอง` (or the
  codebase's prior `เครื่องยนต์สำรอง`) as authoritative terminology?**
  NO — repository-wide search confirms these strings are now absent from
  every source file except the two untouched historical Phase 2 reports
  (Section A), which is correct and expected.
- `frontend/e2e/vehicle-equipment.spec.ts` was updated to assert the new
  Thai labels render on `/vehicle/VEH-1047` (`เครื่องยนต์ Carrier /
  เครื่องยนต์ช่วงล่าง` and `เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน`
  both visible) — independently re-run and passing (Section L).
- `VehicleDetailPage.tsx`/`VehicleListPage.tsx` component code required
  no change (they render whatever `componentRoleLabel` returns) — only
  their test fixtures were updated to use the new vocabulary as sample
  API data, confirmed by direct diff read.
- Historical documentation (Phase 1–3 verification reports) correctly
  retains the old labels and was not touched.

**No defect found.**

---

## L. Automated Verification

All commands below were executed directly in this session against
`web/component-role-naming` @ `df3db37`, independently — not copied from
the correction report's own claimed numbers, though they are cross-
checked against them below.

**Backend — pytest**
```
$ bash scripts/run_backend_tests.sh -q
95 passed, 8 warnings in 1.63s
```
Matches the correction report's claimed 95/95 exactly. (8 warnings are
the pre-existing, disclosed `HTTP_422_UNPROCESSABLE_ENTITY` Starlette
deprecation notice from Phase 3, unrelated to this change.)

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npx vitest run
Test Files  15 passed (15)
     Tests  32 passed (32)
```
Matches the claimed 32/32.

**Frontend — typecheck**
```
$ npx tsc -b
(exit code 0 — PASSED)
```

**Frontend — lint**
```
$ npx oxlint
6 warnings, 0 errors — all pre-existing react(set-state-in-effect)
category, same files/lines as Phase 3's own verification. No new warning.
```

**Frontend — production build**
```
$ npm run build
dist/index.html                   0.43 kB │ gzip:  0.31 kB
dist/assets/index-*.css           9.46 kB │ gzip:  2.40 kB
dist/assets/index-*.js          300.33 kB │ gzip: 90.84 kB
✓ built in 340ms
```
Matches the claimed sizes exactly.

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
85 passed (37.5s)
```
Ran across `smartphone-portrait`, `smartphone-landscape`,
`tablet-portrait`, `tablet-landscape`, `desktop`. Matches the claimed
85/85 exactly.

**Summary**

| Suite | Result | Matches correction report's claim? |
|---|---|---|
| Backend pytest | 95/95 passed | YES |
| Frontend Vitest | 32/32 passed (15 files) | YES |
| Frontend typecheck (`tsc -b`) | PASSED | YES |
| Frontend lint (`oxlint`) | PASSED (6 pre-existing warnings, 0 errors) | YES |
| Frontend production build | PASSED | YES |
| Playwright e2e (5 viewports) | 85/85 passed | YES |

No test was skipped, disabled, or hidden. No claimed result in the
correction report was found to be false — every number matches an
independent re-run in this session.

---

## M. Manual Acceptance Plan

Run with `./scripts/run_dev.sh` (or `run_backend.sh` + `run_frontend.sh`
separately), `DATA_REPOSITORY=mock`, at `http://127.0.0.1:5173`.

1. **Vehicle with `CARRIER_ENGINE` only**
   - Prerequisite: dev servers running.
   - Action: open `/vehicle/VEH-1046` (or `VEH-1048`).
   - Expected: exactly one engine component labeled "เครื่องยนต์
     Carrier / เครื่องยนต์ช่วงล่าง", plus "ระบบส่งกำลัง (PTO)"; no
     Crane-labeled component present.
   - Failure evidence: screenshot of the component list + `GET
     /api/v1/vehicles/VEH-1046` response JSON.

2. **Vehicle with `CARRIER_ENGINE` + `PTO`**
   - Same vehicle as item 1 — both components present together.
   - Expected: both "เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง" and
     "ระบบส่งกำลัง (PTO)" visible.
   - Failure evidence: same as item 1.

3. **Vehicle with `CARRIER_ENGINE` + `CRANE_ENGINE`**
   - Prerequisite: open `/vehicle/VEH-1047`.
   - Expected: both "เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง" and
     "เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน" visible, plus PTO.
   - Failure evidence: screenshot + `GET /api/v1/vehicles/VEH-1047`
     response JSON.

4. **Vehicle detail Thai labels**
   - Action: open any vehicle detail page and read the component labels.
   - Expected: only `เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง` /
     `เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน` appear; no
     `เครื่องยนต์หลัก`/`เครื่องยนต์รอง`/`เครื่องยนต์สำรอง` anywhere.
   - Failure evidence: screenshot with the labels visible.

5. **API response contains no legacy names**
   - Action: `curl http://127.0.0.1:8000/api/v1/models/MODEL-0002` and
     `curl http://127.0.0.1:8000/api/v1/vehicles/VEH-1047`.
   - Expected: `component_role(s)` values are only `CARRIER_ENGINE`/
     `CRANE_ENGINE`/`PTO`.
   - Failure evidence: raw JSON response body.

6. **Stable `component_id` remains unchanged**
   - Prerequisite: know the pre-correction `component_id` values for
     `VEH-1047` (`CMP-0003`, `CMP-0004`, `CMP-0005`, per Phase 2/3's own
     verification and re-confirmed in Section F above).
   - Action: `curl GET /api/v1/vehicles/VEH-1047`.
   - Expected: the same three `component_id` values appear, now with the
     corrected `component_role`.
   - Failure evidence: diff the `component_id` set against the
     pre-correction value.

7. **Phase 3 inspection still opens from the same vehicle**
   - Action: open `/vehicle/VEH-1046/inspect`.
   - Expected: unaffected — checklist loads and submits exactly as
     before the correction (component-role naming has no bearing on the
     inspection flow).
   - Failure evidence: screenshot + Network tab if it fails.

8. **QR route unchanged**
   - Action: confirm `/vehicle/{vehicle_id}` and `/equipment/{equipment_id}`
     still resolve directly to their detail pages, unaffected.
   - Failure evidence: screenshot of an unexpected redirect or 404.

All 8 items were independently confirmed structurally in Sections C, F,
J, and K above (via direct code/diff inspection and the live test suite
re-run in Section L), though not run manually through a browser in this
session — flagged as a manual-verification recommendation, not a
blocking gap, since the same assertions are already exercised by the
independently re-run automated Playwright suite (`vehicle-equipment.spec.ts`,
`inspection.spec.ts`).

---

## N. Final Verdict

# PASS

**Blocking defects:** None. The approved Component Role Naming
correction (`ENGINE_MAIN → CARRIER_ENGINE`, `ENGINE_SECONDARY →
CRANE_ENGINE`, `PTO` unchanged) is fully and correctly implemented across
every authoritative layer: backend domain enum, API schemas (via type
inheritance), mock repository/seed data, frontend types, frontend Thai
labels, and the corresponding tests. Every claim in
`docs/phase-results/component-role-naming-correction.md` was
independently re-verified against the actual `df3db37` diff and a fresh
re-run of every automated suite, and every claim held.

**Known limitations:**
- No legacy-input compatibility layer exists for `ENGINE_MAIN`/
  `ENGINE_SECONDARY` — confirmed correct rather than a gap, since no
  write endpoint ever accepted a client-supplied `component_role` and no
  persisted/historical record ever stored the old names (Sections E, H).
  If a future integration is discovered to have already persisted these
  old values outside this repository, that would need a one-time,
  explicit migration script at that time — correctly disclosed in the
  correction report's own Known Limitations (Section 13) and not
  fabricated as already-solved.
- This correction does not touch or resolve any other open decision
  (A01–A10, B01–B04, C01, C03, D01–D04, etc.) — all remain exactly as
  Phase 3's verification left them, confirmed by the register diff
  (Section I).
- Component-based counters (`ENGINE_HOUR`/`PTO_HOUR`/`ODOMETER`) remain
  entirely unimplemented (Phase 8/IoT scope) — this correction only
  changes the component-role vocabulary they will eventually key off of;
  no counter test evidence is claimed anywhere in this report (Section G).
- The manual acceptance plan (Section M) was verified structurally and
  via the automated e2e suite, not walked through in a live browser in
  this session — a real manual pass is still a reasonable confidence
  check before treating this as end-user-verified.

**Authoritative legacy-name occurrences remaining:** NO (Section A/B).

**Historical-only legacy-name occurrences remaining:** YES (the two
untouched Phase 2 phase-result reports, correctly left as history).

**Legacy compatibility retained:** NO (Section H).

**Ambiguous migrated data found:** NO (Section D — every migrated
record's mapping is directly supported by that model's own pre-existing
Thai description text).

**Real legacy company data found:** NO REAL LEGACY DATA EXISTS
(Section E).

**Stable IDs changed:** NO (Section F).

**Counter semantics changed:** NO (Section G).

**Unrelated governance decisions changed:** NO (Section I — only the new
C04 entry was added; C01/C02/C03/A–M entries are byte-for-byte
unchanged).

**Phase 1 regression:** PASS (Section J/L).

**Phase 2 regression:** PASS (Section J/L).

**Phase 3 regression:** PASS (Section J/L).

**Phase 4 accidentally started:** NO — the `df3db37` diff touches only
`vehicle_model.py`, seed data, test files, governance/baseline docs, and
`CHANGELOG.md`; no PM/repair/work-order domain code exists anywhere in
the repository (confirmed by the same repo-wide search Phase 3's own
verification used).

**Ready to merge correction into main:** READY.

---

This is an audit only. Phase 4 was not started. No frozen Phase 1–3
contract was changed. No stable ID was changed. No counter-type
semantics were changed. No unrelated governance decision was changed.
This report performed no implementation of its own — the correction
being verified was already complete on the branch before this report's
final pass was written.

STOP HERE. Do not begin Phase 4.
