# Web/API Phase 7 — Batch 7J2 — Flexible Vehicle and Equipment Search — Batch Result

BATCH: Phase 7 Batch 7J2 (implementation of the approved 7J1 Final contract)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7j2-flexible-search` (local), based on
`47dec0aa2c4313657f93d8e1c262b8f5ea9ca41e` (equal to
`web/phase7-dashboard-search-reporting` at preflight).

Design input: `Phase7_Batch7J1_Flexible_Search_Contract_Review_Evidence_Final.txt`
(SHA-256 `313025b3df5af8d6c71ac961761256f0a5b64c50e2809044cb346c891f384006`,
127198 bytes, 2050 lines). The owner approved every recommended choice
D-1..D-11 for this batch (superseding that file's historical "UNAPPROVED"
labels for D-1..D-10).

## 1. Approved choices

| Decision | Choice | Implemented as |
| --- | --- | --- |
| D-1 | All terms must match; each may match a different field of the same record | `search_match.record_matches` |
| D-2 | Only U+002D is a hyphen | `search_match.HYPHEN` |
| D-3 | Whitespace = Python `str.isspace()`; zero-width space stays literal | `tokenize` |
| D-4 | A q of only `-` terms: zero results, HTTP 200 | `tokenize` returns `()` |
| D-5 | No Unicode normalization, no Thai/ASCII digit equivalence | — |
| D-6(a) | Equipment: flexible matching on the UNCHANGED legacy read | `list_equipment_records` reuses `read_rows` + mapper |
| D-7 | Equipment matching/category/order/paging in `EquipmentService` | `EquipmentService.list_equipment` |
| D-8 RC | The whole query must match the vehicle plus ONE model row | `vehicle_service._vehicle_matches` |
| D-9 | Model index read per request with usable terms; no cache | `VehicleService._model_search_rows` |
| D-10 | Vehicle search label/placeholder mention model search | `VehicleListPage.tsx` |
| D-11 | Thai+ASCII-digit term: all parts in ONE name field (7J1 Final 4.10) | `thai_digit_pieces`, `token_matches` |

## 2. User-visible behavior

Search terms are separated by spaces; every term must be found
(case-insensitive, as part of a value, in any order).

- **Vehicles**: machine number, vehicle id, and the code/name of the
  vehicle's model (joined by exact `model_id`). Examples: "Tadano" and
  "รถเครน25" find a vehicle by its model name; "TC13" finds machine number
  "TC-13"; "tc-12 zoomlion" combines machine number and model.
- **Equipment**: name, equipment id (new) and equipment code. Examples:
  "กลึง1" finds "เครื่องกลึงเบอร์ 1" and also "เครื่องกลึงเบอร์ 10" (a part of a
  value, not an exact number); "กลึง 1" is two terms and may find more
  (e.g. an item whose id contains "1"); "LATHE01" finds "LATHE-01";
  "eqp 0002" finds EQP-0002.
- Identifier fields (machine number, vehicle id, model code, equipment
  id/code) also match with spaces and `-` ignored. Names are matched as
  written, except the D-11 Thai+digit rule.
- A search of only `-` finds nothing. Status, model and category filters
  still combine with the text. Totals count every match before paging;
  ordering (by id) is unchanged.
- No exact-number matching, numeric conversion ("0012" is not "12"),
  spelling correction, transliteration, synonyms or ranking. Results do
  not represent capacity or other numeric facts.

## 3. Reads, failures and cost

- The vehicle list keeps the 7G2 whole-population validation first; its
  errors and `issue_counts`-only details are unchanged.
- A vehicle search with usable terms then reads `model_master` once
  (model_id, model_code, model_name as text; no `maintenance_plan`, no full
  model mapping). Empty, whitespace-only and `-`-only searches do not.
- New failure dependency: when `model_master` is structurally broken or
  unreadable, a vehicle SEARCH (not the unfiltered list or dashboard) fails
  with the existing `MODEL_MASTER_SCHEMA_INVALID` (500, tab/problem/headers)
  or `MODEL_MASTER_READ_FAILED` (503, no details) — no vehicle, model or
  sample ids.
- Measured fake-transport request counts (`test_s05_*`, not live Sheets):

  | Query | Cold metadata | Cold values | Warm values |
  | --- | --- | --- | --- |
  | empty | 2 | 1 (vehicle_master) | 1 |
  | usable terms | 3 | 2 (+ model_master) | 2 |
  | `-` only | 2 | 1 | 1 |

  Counts are independent of row count; there are no per-vehicle reads.
  The asset picker's vehicle searches therefore cost two Sheets reads.

## 4. Limitations and follow-up (D-6(a), D-8)

- **Equipment data (retained, unchanged)**: the legacy equipment read
  numericises numeric-looking values; one equipment row with a code such
  as "0012" (or a numeric-looking id, name or serial) still fails the whole
  equipment list (generic 500), as before this batch. Equipment detail,
  status change and part install/transfer lookups are unchanged.
- **Status-change write hazard (pre-existing, not changed)**: changing an
  equipment status rewrites the whole sheet row from a numericised read, so
  leading zeros in columns the app does not map (e.g. `model_name` "0250")
  can be lost (7J1 probe P2, fake transport).
- **Follow-up**: a separate coherent equipment read/write contract (list,
  detail, lookups, targeted status writes) — not part of 7J2.
- **Duplicate model ids**: search evaluates each row separately (RC). The
  existing display already disagrees for duplicates (detail shows the first
  row, the list's model column the last, the dropdown both); unchanged.

## 5. Changed files

New: `backend/app/domain/search_match.py`,
`backend/tests/test_flexible_search_batch7j2.py`,
`backend/tests/test_flexible_search_sheets_batch7j2.py`,
`frontend/e2e/flexible-search.spec.ts`, this report.

Modified: `backend/app/domain/vehicle_service.py`,
`backend/app/domain/equipment_service.py`,
`backend/app/repositories/base.py`,
`backend/app/repositories/google_sheets/repository.py`,
`backend/app/repositories/mock/repository.py`,
`backend/app/api/v1/vehicles.py` and `equipment.py` (q descriptions and
error documentation only), `frontend/src/pages/VehicleListPage.tsx` (label
and placeholder only), `CHANGELOG.md`.

Existing tests changed narrowly: 7G2 Sheets fixtures for q success paths
(model_master tab), G13 measured counts, the 7G2 mock G01 comment and G03
model-read count; the vehicle search label text in
`VehicleListPage.test.tsx` and three e2e specs; and, after a failed
verification attempt, two `getByLabel('รุ่น')` selectors made exact in
`vehicle-search-partial-states.spec.ts` (the new label contains "รุ่น").

## 6. Verification

Fresh on the final candidate (code hashes identical before and after;
`pip freeze` identical before and after):

| Command | Result | Exit |
| --- | --- | --- |
| `./scripts/run_backend_tests.sh -q -p no:cacheprovider` | 2044 passed, 174 warnings | 0 |
| `./scripts/run_frontend_tests.sh` | 47 files, 345 tests passed | 0 |
| `npm run build` | built | 0 |
| `npm run lint` | 33 warnings (same set as the 7H2 run) | 0 |
| `npx playwright test e2e/flexible-search.spec.ts` | 15 passed (3 tests × 5 projects) | 0 |
| `npx playwright test` vehicle-search-partial-states, vehicle-search-data-quality, equipment-search-completeness, vehicle-equipment, fleet-status-dashboard, parts-lifetime, responsive-shell | 185 passed | 0 |

The five Playwright projects are Chromium viewport emulations, not five
browser engines. The new e2e spec runs against the real mock backend (no
route mocking). Backend warning sources are identical to the 7H2 run; none
come from the new tests. 2044 = 1997 + 47 new backend tests.

Preserved failure: final attempt 1 had the e2e regression exit 1 (5
failed: the `getByLabel('รุ่น')` strict-mode ambiguity above); the selectors
were made exact and the whole final verification rerun.

Not performed: live Google Sheets, Windows, other browser engines,
realistic data volumes. Earlier owner-reported Windows smoke checks predate
and do not validate flexible search.

Phase 7 remains **PARTIAL**.
