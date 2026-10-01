# Web/API Phase 7 — Batch 7K2 — Equipment Text Preservation and Safe Status Writes — Batch Result

BATCH: Phase 7 Batch 7K2 (implementation of the approved 7K1 corrected contract)

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7k2-equipment-text-preservation` (local), based on
`66fe2fea2d38739cc6a0fa762b2ae86a8429cc45` (equal to
`web/phase7-dashboard-search-reporting` at preflight).

Design input: `Phase7_Batch7K1_Equipment_Text_Preservation_Contract_Review_Evidence_Corrected.txt`
(SHA-256 `54567e1520ba4d3357424d65838dc2b830d12ff869630bda2ad14387bc47a03b`,
205826 bytes, 2633 lines).

## 1. Approved choices

| Decision | Choice | Implemented as |
| --- | --- | --- |
| DEC-K1(b) | Validated lookup for EquipmentService and the equipment branches of the shared lookups | `asset_lookup.lookup_equipment`, `InspectionService._require_asset`, `AttachmentService.authorize_source` |
| DEC-K2(b) | Whole list fails only for blank/unrecognized category or status and unmappable rows; blank/duplicate ids listed | `EquipmentService.list_equipment`, `equipment_rules.equipment_row_issue` |
| DEC-K3(a) | Known-hazard id guard at the eight mutating sites; prefixes `=` `+` `-` `@` `'` | `asset_lookup.require_asset_for_new_work`, `equipment_rules.known_text_hazard` |
| DEC-K4(a) | Coded envelopes, rejected vs unknown, no retry/compensation/re-read | `equipment_errors` |
| DEC-K5(a) | History text forcing incl. reason and actor | `change_equipment_status_validated` |
| DEC-K6(a) | Frontend outcome classes, refresh, history error | `EquipmentDetailPage.tsx` |
| DEC-K7(a) | History data issues -> coded 500 with per-row counts | `EquipmentService.list_status_history` |
| DEC-K8(a) | Dates read as text; existing parsing kept | text-only headers |
| DEC-K9(b) | Mixed naive/aware history times -> coded error, no reinterpretation | `MIXED_TIMEZONE_TIMESTAMP` |
| DEC-K10(a) | Read-only callers: validated lookup, no guard | `require_asset_exists` |

## 2. Guard-scope qualification (authorized correction of the 7K1 wording)

The 7K1 contract said "the app itself cannot create downstream rows for a
text-unsafe id". That is overbroad. Accurate: **the new guard blocks the
eight explicitly enumerated mutating sites before their first write** — PM
work order, repair, part install, part transfer TARGET, material request,
position lifetime, inspection submit, and inspection-equipment attachment
upload. It does not protect every application write: the transfer SOURCE
(removal snapshot, segment close), part removal and other paths outside this
boundary are unguarded, and downstream writers/readers of `asset_id` are
unchanged. Reference records that read-only views may omit are therefore not
limited to rows created outside the app — historical rows and rows written by
unguarded paths are included. The approved input evidence is not edited.

## 3. User-visible behavior

- **Equipment list, detail, status history and lookups** keep stored text
  exactly: an id, code, name or serial such as "0012", "0099", "1234" or
  "๐๑๒" is shown and matched as written ("0012" is not "12"). Blank ids are
  never looked up; an id stored twice is refused (409
  `EQUIPMENT_ID_AMBIGUOUS`) everywhere except the list, which still shows both
  rows.
- **Data problems** in the equipment sheet: a row with a blank or unknown
  category/status fails the list (500 `EQUIPMENT_MASTER_DATA_INVALID`, counts
  per row, no ids) — previously a generic error; other rows stay usable by
  detail, status change and lookups. Structural problems and read failures
  have their own codes (`*_SCHEMA_INVALID`, `*_READ_FAILED`).
- **Status change** writes only the status cell and then appends history;
  other cells (including formulas and columns the app does not use) are not
  rewritten. If the update or the history append fails, the message says
  whether Google Sheets rejected it or the outcome is unknown; nothing is
  retried. "Acknowledged" means the request was accepted, not that the stored
  value was re-read.
- **New work** (the eight sites above) for an equipment id with a known text
  hazard (e.g. "0012", "1e3", "TRUE", "=A1", "-x") is refused with 422
  `EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK` before anything is written. Viewing,
  status changes and history for that equipment still work. Ids such as
  "2026-01-01" or "5%" are **not detected** — that does not make them safe.
- **Status history**: an unknown/blank status code, or a mix of times with
  and without a time zone, returns a coded error (counts only); times are not
  reinterpreted. Blank and duplicate history ids are shown as before.
- **Frontend**: pre-write and rejected errors stay in the open dialog with
  the chosen values; unknown or partial outcomes show a persistent page
  warning (scrolled into view) and one refresh; if that refresh fails, the
  page keeps the shown data with a stale-data notice and a manual "โหลดใหม่"
  button — this includes a refresh where only the history read failed (the
  history error is then shown next to the kept history). A failed history
  load is shown as an error, not as empty history. Older reads never
  overwrite newer data (Section 5.1).

## 4. Changed files

New: `backend/app/domain/equipment_rules.py`,
`backend/app/domain/equipment_errors.py`,
`backend/tests/test_equipment_text_preservation_batch7k2.py`,
`backend/tests/test_equipment_text_preservation_sheets_batch7k2.py`,
`frontend/e2e/equipment-status-change.spec.ts`, this report.

Modified: `backend/app/repositories/base.py`,
`backend/app/repositories/google_sheets/repository.py`,
`backend/app/repositories/mock/repository.py`,
`backend/app/domain/equipment_service.py`, `asset_lookup.py`,
`inspection_service.py`, `attachment_service.py`, `pm_service.py`,
`repair_service.py`, `part_instance_service.py`,
`material_request_service.py`, `position_lifetime_service.py`,
`backend/app/api/v1/equipment.py` (error documentation only),
`frontend/src/lib/labels.ts`, `frontend/src/pages/EquipmentDetailPage.tsx`,
`frontend/src/components/ChangeEquipmentStatusDialog.tsx`,
`frontend/src/pages/EquipmentDetailPage.test.tsx` (new tests appended),
`backend/tests/test_flexible_search_sheets_batch7j2.py` (only the two
authorized expectation changes T-X1 and T-X2), `CHANGELOG.md`.

Unchanged: legacy repository equipment methods, generic Sheets client,
vehicle paths, downstream writers/readers, authorization, dependencies,
configuration.

Clarification: with Google Sheets unconfigured, the equipment paths keep the
legacy controlled `RepositoryError` (generic 500) so the existing test
`test_equipment_domain_methods_report_not_configured_until_credentials_exist`
passes unchanged; `*_READ_FAILED` applies to read failures of a configured
repository.

## 5. Verification

### 5.1 Review corrections (fresh, on the final candidate)

Two review findings in `EquipmentDetailPage.tsx` were corrected (only this
page, its unit tests, the e2e spec and this report changed):

- **History-only refresh failure**: a U/H refresh now succeeds only when both
  the equipment and the history reads succeed. Otherwise the previously
  displayed equipment and history are kept, the stale-data notice and manual
  reload appear, the mutation warning stays, and a history failure is shown
  next to the kept history (an initial-load history failure is still shown
  explicitly). A later successful refresh replaces the data and clears the
  notices.
- **Read ordering**: `load()` and `refresh()` share one request generation;
  only the newest read may apply data, history errors, staleness or the
  refreshing state. Starting a status submission, changing the equipment
  route and unmounting invalidate pending reads; a status result for a
  previous route is ignored. The status-change button stays available during
  a refresh; nothing is retried automatically.
- **Route-specific state** (final correction): the page body is keyed by the
  equipment id, so moving to another equipment starts with a fresh state —
  no inherited dialog, inline error, mutation warning, stale/refreshing
  notice or stuck "saving" button. A status change still pending for the
  previous equipment completes without changing the new page (no warning,
  no reload); the read-generation and route-epoch protections are unchanged.

The nine new regression tests were run first against the reviewed component:
8 failed (R1a, R1c, R1d, R2-1..R2-5) and R1b passed (the reviewed code already
handled a failed equipment read); after the fix all pass. The final
correction added three route-change tests (R3-1, R3-2 x2); all three failed
against the corrected component (the previous equipment's dialog or warning
was still shown) and pass after the change.

| Command | Result | Exit |
| --- | --- | --- |
| `npx vitest run src/pages/EquipmentDetailPage.test.tsx` | 31 passed | 0 |
| `./scripts/run_frontend_tests.sh` | 47 files, 374 tests passed (362 + 9 + 3) | 0 |
| `npm run build` | built | 0 |
| `npm run lint` | 33 warnings (same file/rule set as before) | 0 |
| `npx playwright test e2e/equipment-status-change.spec.ts` | 25 passed (5 tests x 5 projects) | 0 |
| `npx playwright test` vehicle-equipment, equipment-search-completeness, parts-lifetime, responsive-shell | 100 passed | 0 |

Candidate code hashes were identical before and after this verification.

### 5.2 Original 7K2 verification (historical for unchanged files)

Recorded on the reviewed candidate (backend files are unchanged by the
correction, so the backend result was not re-run):

| Command | Result | Exit |
| --- | --- | --- |
| `./scripts/run_backend_tests.sh -q -p no:cacheprovider` | 2135 passed, 211 warnings | 0 |
| `./scripts/run_frontend_tests.sh` (superseded by 5.1) | 47 files, 362 tests passed | 0 |
| `npx playwright test` equipment-search-completeness, vehicle-equipment, flexible-search, parts-lifetime, inspection, pm-repair, responsive-shell, vehicle-search-partial-states, vehicle-search-data-quality | 245 passed | 0 |

2135 = 2044 (7J2) + 91 new backend tests (47 mock/service/API + 44 Sheets).
Every backend warning source of the 7J2 run is still present; the only new
sources are the two new 7K2 test files (Starlette's existing
`HTTP_422_UNPROCESSABLE_ENTITY` deprecation, raised by pre-existing
application code on the 422 paths these tests exercise).

The five Playwright projects are Chromium viewport emulations, not five
browser engines. Development-time failures are preserved in the evidence
with their fixes.

Not performed: live Google Sheets, Windows, other browser engines, realistic
data volumes.

## 6. Residual limitations

- Guard scope is the eight sites only (Section 2); downstream `asset_id`
  writers/readers keep legacy behavior, so read-only views may omit records
  stored in altered form.
- Date/time/percent/currency/locale interpretations by Google Sheets are not
  detected by the predicate.
- Concurrent row/column moves between the validated read and the write can
  misdirect the targeted write; history ids can collide under concurrent
  changes; unknown outcomes need a person to check the sheet (A09).
- Already-lost leading zeros are not recovered; padded ids remain unusable
  through the picker (it trims); attachments still have no RETIRED rule;
  route authorization (M02) unchanged.

Phase 7 remains **PARTIAL**.
