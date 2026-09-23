# Web/API Phase 7 — Batch 7B2 — Validated Fleet Status Dashboard — Batch Result

BATCH: Phase 7 Batch 7B2 (fleet status dashboard, KPI K1–K6 only)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED CANDIDATE, AWAITING INDEPENDENT REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL** (this batch does not close Phase 7, CP7
for any other KPI, or any open decision)

Branch: `review/phase7-batch7b2-fleet-dashboard`, based on
`8173c1031c3ee951284ce23bc89f0c7df9a6c763` (Batch 7A integrated). Design
input: the final 7B1 contract review evidence
(`Phase7_Batch7B1_Summary_Contract_Review_Evidence_Final.txt`, SHA-256
`4cce998545f988e78a54ebf3214e44dee45c3194cbd3a99f5619af89078f603c`),
main Sections 1–8, as resolved by the approved 7B2 implementation prompt.

## 1. Approval recorded

The user approved this batch ("อนุมัติ เริ่ม 7B2") after reviewing the 7B1
candidate policies. For **this slice only**, that approval covers:

| Decision | Approved choice |
| --- | --- |
| CP7 (K1–K6 only) | K1 `vehicle_total` and K2–K6 recorded operational-status counts, as defined in Section 3 below |
| DQ-1 | Parity-or-fail: counts are returned only when the data supports exact agreement with `GET /vehicles`; otherwise a whole-response error with no counts |
| DQ-1a | Blank/whitespace-only and exact-duplicate vehicle ids are part of the gate |
| DQ-1b | Non-blank data under an unnamed column or beyond the header width fails closed |
| READ-1 | One values response carries header + rows; the header is validated on that response before any filtering, padding or mapping |
| ERR-1 | 403 `HTTP_ERROR`, 500 `VEHICLE_MASTER_SCHEMA_INVALID`, 500 `VEHICLE_MASTER_DATA_INVALID`, 503 `VEHICLE_MASTER_READ_FAILED`, 500 `INTERNAL_ERROR` |
| AUTH-1 | Existing `can_view` capability required before any data read |
| NAV-1 | New `/dashboard` page and one menu item; only a plain unfiltered link to `/vehicles`; `VehicleListPage` unchanged |

Explicitly accepted consequence: a single blank `operational_status` cell
blocks the whole dashboard, even though the legacy vehicle list still
shows that row as READY. Legacy data and defaults are not modified.

This approval does **not** close CP7 for future KPIs, Phase 7 as a whole,
or any Open Decision (A05, A08, C01, D26, E01–E05, F01, G01–G04, H02,
H03, M01, M02 and the rest remain as recorded in the register).

## 2. API added

`GET /api/v1/dashboard/fleet-status` — global; **no supported query
parameters** (unknown parameters are ignored, as on every other route,
and never filter the result).

Success (HTTP 200), exactly:

```json
{
  "population": "VEHICLE_MASTER_VALIDATED_RECORDS",
  "vehicle_total": 6,
  "status_counts": {
    "WORKING": 2,
    "READY": 1,
    "MAINTENANCE": 1,
    "OUT_OF_SERVICE": 1,
    "LONG_TERM_PARKING": 1
  }
}
```

All counts are non-negative integers, all five keys are always present
(zero included), and `vehicle_total` always equals their sum. There is no
unknown-status count, freshness timestamp, per-metric partial state, or
PM/alert/certificate/online field. No 200 response ever carries partial
results.

Errors (existing envelope with `request_id`; no counts in any error):

| HTTP | `error.code` | When | `details` |
| --- | --- | --- | --- |
| 403 | `HTTP_ERROR` | caller lacks `can_view` (checked before any read) | `null` |
| 500 | `VEHICLE_MASTER_SCHEMA_INVALID` | proven structural problem | `{"tab", "problem", "headers"}`; `problem` ∈ `TAB_MISSING`, `NO_HEADER_ROW`, `MISSING_HEADERS`, `DUPLICATE_HEADERS`, `DATA_OUTSIDE_HEADER` |
| 500 | `VEHICLE_MASTER_DATA_INVALID` | record/identity problems | `{"issue_counts": {code: n}, "sample_vehicle_ids": [≤20 distinct, sorted, non-blank]}`; codes `BLANK_STATUS`, `UNRECOGNIZED_STATUS`, `UNMAPPABLE_ROW`, `BLANK_VEHICLE_ID`, `DUPLICATE_VEHICLE_ID` |
| 503 | `VEHICLE_MASTER_READ_FAILED` | not configured, read/API failure, or a tab failure that cannot be proven structural | `null` |
| 500 | `INTERNAL_ERROR` | unexpected bug (existing generic handler) | `null` |

No raw cell values, row numbers, stack traces or secrets are returned. The
OpenAPI document declares the route with no parameters, the exact
response schema (`additionalProperties: false`, all fields required) and
the 403/500/503 responses above.

## 3. KPI and validation policy (as implemented)

- **K1 `vehicle_total`** — number of vehicle master records (คัน). No
  active/archive filter (A08 is undecided), equipment excluded, no model
  join/filter, orphan `model_id`s counted, OUT_OF_SERVICE and
  LONG_TERM_PARKING included. Label "รถในทะเบียนทั้งหมด".
- **K2–K6 `status_counts`** — records whose RECORDED `operational_status`
  is exactly each code. Not a statement about IoT connectivity, physical
  readiness, status-transition validity (C01) or "inactive vehicle".
- **Population** — rows with at least one non-blank canonical cell (the
  existing `GoogleSheetsClient._has_any_canonical_value` rule used by
  `read_rows`); rows whose only content is in named non-canonical columns
  are phantoms for both the list and the summary.
- **Structure (Sheets)**, checked on the raw values of the single response
  before any padding/zip/filtering: a header row exists; all seven
  `VEHICLE_SHEET` headers are present by exact name (no trimming or
  case-folding); no duplicate names; at most one unnamed header cell
  (positions beyond the header width count as unnamed, because gspread
  pads the header to the widest row); no non-blank data under an unnamed
  header cell. Named extra columns are allowed. A cold open that raises
  gspread `WorksheetNotFound` is `TAB_MISSING`; a failure of a warm, cached
  worksheet is `READ_FAILED`, never a proven missing tab.
- **Records**: raw status must be a string exactly equal to one of the five
  codes (blank or whitespace-only → `BLANK_STATUS`; anything else,
  including case/whitespace variants → `UNRECOGNIZED_STATUS`). The
  unchanged `_vehicle_from_row` maps the row; only `ValueError`/`TypeError`
  (pydantic `ValidationError` is a `ValueError`) become `UNMAPPABLE_ROW`.
  Blank/whitespace-only ids and exact duplicate ids are counted per
  occurrence (two rows sharing an id → `DUPLICATE_VEHICLE_ID: 2`). No id
  format policy, and no model/component validation.
- **Parity guarantee**: for the same stored state, a successful summary
  equals `GET /vehicles` `total_items` unfiltered and filtered by each
  status. Not guaranteed: that every counted vehicle's detail page opens
  (detail also reads models/components), URL safety of stored ids,
  integrity of other sheets, or agreement across two requests if data
  changes between them.

## 4. Implementation

Web → API → `VehicleService` → Repository; the browser never touches Sheets.

- `GoogleSheetsClient.read_header_and_records(schema)` (new): one
  `worksheet.get(value_render_option=None, pad_values=False)` request —
  the identical request installed gspread's `get_all_records` sends —
  then `_validate_raw_structure` on the raw rows, then gspread's own
  `fill_gaps` / `numericise_all(row, False, "", False, [])` / `to_records`
  (the arguments `read_rows` uses for a tab read without
  `text_only_headers`, as `list_vehicles` does). It neither uses nor
  refreshes `_header_cache`. Design choice: structural validation runs
  inside the client, before records are built, so the returned
  `HeaderAndRecords` never needs to carry discarded cells.
- `GoogleSheetsRepository.read_vehicle_master_for_summary()` (new): phantom
  filter → exact status check → unchanged `_vehicle_from_row`.
- `MockRepository.read_vehicle_master_for_summary()` (new): deep copies of
  the typed in-memory vehicles.
- `VehicleService.get_fleet_status_summary()` (new): error mapping,
  identity checks and counting via the pure helpers in
  `app/domain/fleet_summary.py`; invariant K1 = ΣK2–K6 is checked.
- `app/api/v1/dashboard.py` (new): `require_capability(context, CAN_VIEW, …)`
  is the handler's first statement.
- Unchanged: `read_rows`, `find_row*`, `validate_schema`, `_get_header_sync`
  and the header cache, `_has_any_canonical_value`, `_vehicle_from_row`,
  `list_vehicles`, `get_vehicle`, every other repository caller, all
  existing routes, `VehicleListPage` and its tests, 7A e2e, seed data.

Measured gspread HTTP requests per summary (fake transport under the real
gspread 6.2.1 client; counts only, **no latency measured**): cold process
2 metadata + 1 `vehicle_master` values read; warm process exactly 1
values read; 0 writes; no other tab touched. (Legacy `list_vehicles` for
comparison: cold 2 metadata + 2 values reads — header `row_values(1)` plus
`get_all_records` — warm 1.)

## 5. UI added

`/dashboard` → `FleetStatusPage`, menu item "ภาพรวมกองรถ" after
"หน้าหลัก" (`HomePage` unchanged). Mobile-first grid: 1 column below
641px, 2 from 641px, 3 from 1024px; the total card spans the row.

- Title "ภาพรวมกองรถ"; refresh button "โหลดข้อมูลใหม่" in every state
  (never disabled; each press starts a new request generation).
- Success: total card "รถในทะเบียนทั้งหมด" `<n> คัน` with the only link,
  "ดูรายการรถทั้งหมด (ไม่กรองสถานะ)" → `/vehicles`; five status cards using
  the existing Thai labels/tones (not links); helper text "ต้องการดูรถตาม
  สถานะ ให้เปิดรายการรถแล้วเลือกตัวกรอง “สถานะ”". Zero total adds the
  empty state "ยังไม่มีรายการรถในทะเบียน".
- Scope note (always shown): "หน้านี้แสดงเฉพาะจำนวนรถตามสถานะที่บันทึกไว้
  ในทะเบียนรถ ยังไม่แสดงกำหนด PM อายุชิ้นส่วน ใบรับรองหมดอายุ งานซ่อมที่เปิด
  สถานะออนไลน์/ออฟไลน์ หรือการแจ้งเตือน".
- Loading/error/403 show no numbers; previous numbers are hidden during
  reload. Data/schema errors use the title "ไม่แสดงตัวเลขสรุป"; read and
  other failures "โหลดภาพรวมกองรถไม่สำเร็จ"; messages come from
  `describeErrorCode` (three new Thai entries), with the request id and a
  retry button via the existing `ErrorState`. 403 uses
  `PermissionDeniedState`.
- One page-owned `GET /dashboard/fleet-status` per load/refresh; the latest
  request generation wins for success and error alike. StrictMode is kept;
  in development the mount effect may send the summary GET twice (only the
  latest result is applied); the shell's `GET /me` is separate.

## 6. Files

Added: `backend/app/domain/fleet_summary.py`,
`backend/app/api/v1/dashboard.py`, `backend/app/api/v1/dashboard_schemas.py`,
`backend/tests/test_fleet_status_summary_batch7b2.py`,
`backend/tests/test_fleet_status_summary_sheets_batch7b2.py`,
`frontend/src/pages/FleetStatusPage.tsx`,
`frontend/src/pages/FleetStatusPage.test.tsx`,
`frontend/e2e/fleet-status-dashboard.spec.ts`, this document.

Modified (additive): `backend/app/repositories/base.py`,
`backend/app/repositories/google_sheets/client.py`,
`backend/app/repositories/google_sheets/repository.py`,
`backend/app/repositories/mock/repository.py`,
`backend/app/domain/vehicle_service.py`, `backend/app/api/v1/router.py`,
`frontend/src/App.tsx`, `frontend/src/components/NavBar.tsx`,
`frontend/src/lib/types.ts`, `frontend/src/lib/labels.ts`,
`frontend/src/index.css`, `frontend/src/App.test.tsx` (new `/dashboard`
route case; the home-page case is unchanged),
`frontend/src/components/NavBar.test.tsx` (new menu-link case; existing
cases unchanged), `CHANGELOG.md`.

Not changed: `README.md` and `backend/README.md` (no setup or command
changed; neither lists individual routes), governance register, baseline
prompts, seed data, dependencies, lockfiles, configs, hooks.

## 7. Verification

Library versions (installed from the existing `requirements.txt` /
`package-lock.json`, no change): gspread 6.2.1, pydantic 2.13.5.

| Check | Result |
| --- | --- |
| Backend `./scripts/run_backend_tests.sh` (full pytest) | PASS — 1171 passed (HEAD baseline 1080 + 91 new: 38 unit/service/API/mock, 53 fake-Sheets); 130 warnings, the same count as the HEAD baseline, none from new code |
| Frontend `./scripts/run_frontend_tests.sh` (full vitest) | PASS — 37 files, 208 tests (16 new `FleetStatusPage` cases, 1 new `NavBar` case, 1 new `App` route case) |
| Frontend `npm run build` (tsc -b + vite build) | PASS |
| Frontend `npm run lint` (oxlint) | PASS — 0 errors; 34 warnings, the identical file/rule set to the HEAD baseline (no new warning) |
| Playwright `fleet-status-dashboard`, `vehicle-search-partial-states`, `vehicle-equipment`, `responsive-shell` × 5 viewport projects | PASS — 95/95 (25 new: 4 mocked + 1 unmocked smoke × 5), 0 flaky, 0 retries |
| Backend lint | none configured in the repository (not added) |

### 7.1 Notes

- Development-mode request counts on a first `/dashboard` load (measured
  in the unmocked smoke, every viewport): shell `GET /me` = 2 and
  `GET /dashboard/fleet-status` = 2 — both doubled by React StrictMode's
  development mount repetition; only the latest summary result is applied.
- One lint warning (`react(set-state-in-effect)`) appeared in the first
  draft of `FleetStatusPage.tsx`; it was fixed by following the 7A pattern
  (the load function only applies results; event handlers show loading).
- The unmocked smoke compares dashboard counts with the vehicle list's
  own totals (unfiltered and per status filter) and retries that whole
  comparison, because `vehicle-equipment.spec.ts` changes a seed
  vehicle's status on the shared mock backend in parallel.

### 7.2 What the evidence does and does not prove

Parity and structural behavior are proven with the REAL installed gspread
transformation path (`Worksheet.get`, `get_all_records`, `row_values`,
`fill_gaps`, `numericise_all`, `to_records`) over a fake HTTP session.
**No live Google Sheets read was performed** (not authorized for this
batch): live latency, live API error shapes for a deleted tab, and the
assumption that one values response is a consistent read of header and
rows remain unverified against production. Fake-client results do not
prove production readiness. Production authentication/RBAC does not exist
(M01/M02); the capability check pins current dev-auth behavior only.

## 8. Deferred / out of scope

Open repairs, PM work orders, findings, certificates, counters,
online/last-seen, GPS, stored alerts, inactive vehicles, PM due and
lifetime due remain Phase 7 scope behind their named gates (see the 7B1
evidence Section 2.3 and 3.6). URL-seeded status filtering from dashboard
cards is deferred (NAV-1). Phase 7 remains **PARTIAL**.
