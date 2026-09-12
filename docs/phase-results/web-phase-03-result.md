PHASE: Web/API Phase 3 — Inspection, Checklist Revision, History, and Abnormal Findings
STATUS: PASS

Prerequisite phases 1-2 are accepted and their public contracts (API
versioning, error envelope, repository/storage abstraction, stable-ID
convention, Thai UI shell, mobile-first responsive foundation, Vehicle/
Equipment domain + QR routes) are treated as frozen. This report follows
the structure requested in the Phase 3 task brief; where it overlaps with
the phase-prompt's own required report fields (`03_PHASE3_INSPECTION_...`),
both are covered together under one heading.

======================================================================
1. SCOPE IMPLEMENTED
======================================================================

The full Phase 3 user flow: scan QR → Vehicle/Equipment Detail →
"ตรวจเช็ค" → checklist (auto-loaded, no manual revision choice) → PASS/
FAIL/N/A per item with remark + evidence photo → "ส่งผลการตรวจ" →
immutable inspection record → "ประวัติการตรวจเช็ค" history.

Implemented:
- Revision-controlled checklist master/revision/item, with effective-date
  selection of "the" active revision per asset type.
- Checklist item fields: identity, sequence, title, inspection point,
  reference image (metadata via the shared `Attachment` model), method,
  standard, instruction, frequency (free text, unset), required-photo-
  on-fail flag, `is_critical` flag (always `False` in seed data).
- PASS / FAIL / N/A result enum (English codes, Thai labels only in the
  frontend).
- Reference image (checklist/revision/item guidance) vs inspection
  evidence photo (submitted result) as two distinct concepts, never
  sharing one field or storage meaning.
- Immutable inspection submission: header + per-item results + findings,
  with each item result snapshotting the checklist item's display text at
  submission time so a later revision can never alter history.
- FAIL → creates an OPEN `InspectionFinding` ("normal abnormal finding
  for maintenance review"). No automatic Repair Order is created (Repair
  is Phase 4, explicitly out of scope).
- Critical-item architecture (`is_critical` on both the checklist item and
  the finding) exists, but no seed item is marked critical — no source
  data authorizes that classification (see Section 13/14).
- Shared engine for VEHICLE and EQUIPMENT — same domain models, service,
  API routes, and frontend pages, with the two asset types never merged
  (separate master tables/identities preserved from Phase 2).
- Inspection entry point + history added to both detail pages without
  touching the frozen `/vehicle/{vehicle_id}` / `/equipment/{equipment_id}`
  QR routes/behavior.
- Mobile-first inspection workflow: card-per-item layout, large PASS/
  FAIL/N/A buttons, remark + evidence controls appear immediately on
  FAIL (no extra navigation), sticky submit action, camera-capable file
  input, no horizontal scrolling, 44px+ touch targets — verified at all
  5 required viewport bands via Playwright (see Section 9/10).
- History/detail access: per-asset inspection list and a read-only,
  immutable inspection detail page showing the exact revision/text used.
- Repository abstraction preserved: browser never touches Google Sheets;
  `MockRepository` fully implements the new methods; `GoogleSheetsRepository`
  declares the schema and reports a controlled not-configured error, same
  pattern as Phase 2.
- Evidence/reference attachments go through the existing `StorageProvider`
  abstraction (`LocalFileStorageProvider`); only metadata + `storage_ref`
  are ever persisted in the repository.

Not implemented (explicitly out of scope for Phase 3, see Section 15):
Repair workflow, PM, automatic due/scheduling logic, checklist-authoring
UI (creating/editing checklist masters/revisions — Phase 3 ships with
seeded placeholder checklists only), correction/void/supersede of a
submitted inspection, RBAC beyond the existing dev-auth context.

======================================================================
2. FILES / MODULES ADDED OR CHANGED
======================================================================

Backend — added:
- `backend/app/domain/attachment.py` — `AttachmentPurpose`, `Attachment`.
- `backend/app/domain/checklist.py` — `InspectionResultValue`,
  `ChecklistMaster`, `ChecklistItem`, `ChecklistRevision`,
  `ChecklistRevisionDetail`.
- `backend/app/domain/inspection.py` — `FindingStatus`,
  `InspectionHeader`, `InspectionItemResult`, `InspectionFinding`,
  `InspectionDetail`, `InspectionSummary`, `NewInspectionItemInput`.
- `backend/app/domain/inspection_service.py` — `InspectionService`
  (checklist retrieval, attachment upload/read, submission validation,
  history).
- `backend/app/api/v1/inspection_schemas.py` — API request/response
  Pydantic models.
- `backend/app/api/v1/inspections.py` — checklist/attachment/inspection
  routes.
- Tests: `backend/tests/test_inspections_api.py`,
  `backend/tests/test_mock_repository_inspection.py`.

Backend — modified:
- `backend/app/repositories/base.py` — added checklist/attachment/
  inspection abstract methods (existing vehicle/equipment methods
  untouched).
- `backend/app/repositories/mock/repository.py`,
  `backend/app/repositories/mock/seed_data.py` — full in-memory
  implementation + placeholder seed checklists (see Section 5/14).
- `backend/app/repositories/google_sheets/repository.py`,
  `backend/app/repositories/google_sheets/schemas.py` — declared tab/
  header schemas + controlled not-configured/not-implemented methods,
  same pattern as Phase 2's vehicle/equipment methods.
- `backend/app/dependencies.py` — `get_inspection_service` provider.
- `backend/app/api/v1/router.py` — registers the inspections router.
- `backend/pyproject.toml`, `backend/requirements.txt` — added
  `python-multipart` (required by FastAPI for the multipart attachment
  upload endpoint).

Frontend — added:
- `frontend/src/components/ChecklistItemCard.tsx` (+ `.test.tsx`) —
  one inspection item card (title/point/method/standard/instruction,
  reference image, PASS/FAIL/N/A, remark, evidence upload).
- `frontend/src/pages/InspectionFormPage.tsx` (+ `.test.tsx`) — the
  checklist form, shared by `/vehicle/:vehicleId/inspect` and
  `/equipment/:equipmentId/inspect`.
- `frontend/src/pages/InspectionHistoryPage.tsx` (+ `.test.tsx`) —
  per-asset inspection history list.
- `frontend/src/pages/InspectionDetailPage.tsx` (+ `.test.tsx`) —
  immutable inspection record view.
- `frontend/e2e/inspection.spec.ts` — 5 new Playwright test cases (25
  runs across the 5 viewport projects).

Frontend — modified:
- `frontend/src/lib/types.ts` — inspection/checklist/attachment types.
- `frontend/src/lib/labels.ts` — Thai labels for PASS/FAIL/N/A, asset
  type, and new error codes.
- `frontend/src/lib/apiClient.ts` — added `apiPost` (JSON POST) and
  `apiUpload` (multipart form-data), alongside the existing `apiGet`/
  `apiPatch`; no change to their behavior or to `ApiError`/`ApiResult<T>`.
- `frontend/src/App.tsx` — added the 5 new routes (see Section 8).
- `frontend/src/pages/VehicleDetailPage.tsx`,
  `frontend/src/pages/EquipmentDetailPage.tsx` — added "ตรวจเช็ค" /
  "ประวัติการตรวจเช็ค" entry points; the rest of each page is unchanged.
- `frontend/src/index.css` — added `.checklist-item-card*`/
  `.result-button*` rules on top of the existing frozen mobile-first
  primitives (`Card`, `.form-field`, `.sticky-actions`, `--tap-target`);
  no existing rule was changed.
- `README.md`, `CHANGELOG.md` — document Phase 3.

======================================================================
3. API ROUTES ADDED
======================================================================

- `GET /api/v1/checklists/active?asset_type=VEHICLE|EQUIPMENT` — the
  checklist revision currently effective for that asset type, with items
  (404 `NO_ACTIVE_CHECKLIST` if none configured).
- `GET /api/v1/checklists/{checklist_id}/revisions/{revision_id}` — one
  specific historical revision (404 `CHECKLIST_REVISION_NOT_FOUND`).
- `POST /api/v1/attachments` (multipart: `purpose`, `file`) — uploads a
  reference-image or evidence-photo file via `StorageProvider` and
  records its metadata.
- `GET /api/v1/attachments/{attachment_id}/file` — streams the stored
  file back (404 `ATTACHMENT_NOT_FOUND`).
- `POST /api/v1/inspections` — submit a new immutable inspection (body:
  `asset_type`, `asset_id`, `items[]`; 404 `VEHICLE_NOT_FOUND`/
  `EQUIPMENT_NOT_FOUND`, 422 `VALIDATION_ERROR` with structured
  `details` for missing/unknown items or FAIL rule violations).
- `GET /api/v1/inspections?asset_type=&asset_id=&page=&page_size=` —
  paginated history, newest first.
- `GET /api/v1/inspections/{inspection_id}` — full immutable detail (404
  `INSPECTION_NOT_FOUND`).

All new routes live under the frozen `/api/v1` prefix and use the frozen
error envelope; no Phase 1/2 route changed shape.

======================================================================
4. DOMAIN / REPOSITORY ARCHITECTURE
======================================================================

Layering is unchanged from Phase 1/2: `API route → InspectionService →
Repository interface → MockRepository | GoogleSheetsRepository`. Routes
depend only on `InspectionService`; the service depends only on the
`Repository`/`StorageProvider` abstractions (never on a concrete
implementation), so a future PostgreSQL repository needs no route/service
change — only a new `Repository` implementation.

`InspectionService` owns every business rule Phase 3 is allowed to define
without an approved open decision:
- resolves "the" active checklist for an asset type (`get_active_checklist`),
- validates a submission covers every active-revision item exactly once,
- enforces the FAIL-remark rule and the item-level required-photo-on-fail
  rule,
- validates evidence attachment IDs are real, `INSPECTION_EVIDENCE`
  attachments,
- reuses Phase 2's `VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND` codes for
  asset validation instead of inventing new ones.

`Repository` gained 8 new abstract methods (checklist read x2, attachment
create/read x2, inspection create/read/list x3) — purely additive, no
existing method's signature or behavior changed (the same extension
pattern Phase 2 used, anticipated by Phase 1's docstring on `Repository`).

`MockRepository` stores checklists/revisions/items/attachments/
inspections in-memory, isolated per instance (proven by test — see
Section 10); `create_inspection` builds the immutable snapshot and any
FAIL findings in one call, matching the pattern `change_vehicle_status`
already used in Phase 2 (append, never mutate).

`GoogleSheetsRepository` declares the 7 new tab/header schemas
(`checklist_masters`, `checklist_revisions`, `checklist_items`,
`attachments`, `inspections`, `inspection_item_results`,
`inspection_findings`) mapped by header name, and raises the same
controlled `RepositoryError`("not configured")/`NotImplementedError`
sequence Phase 2 established — this sandboxed environment has no Google
credentials or network path to the Sheets API, so live I/O is
implemented and tested on the developer's machine once configured,
matching Phase 2's precedent exactly.

======================================================================
5. CHECKLIST REVISION / HISTORY DESIGN
======================================================================

- `ChecklistMaster` is the stable identity (`checklist_id`, `asset_type`,
  `code`, `name`). `ChecklistRevision` is immutable once created
  (`revision_id`, `checklist_id`, `revision_number`, `effective_date`).
  `ChecklistItem` rows belong to exactly one revision; a new revision is
  a new, separate set of items — never an edit of a previous revision's
  items.
- Active-revision selection: among revisions of the asset type's
  checklist with `effective_date <= today`, the one with the latest
  `(effective_date, revision_number)` wins. No manual revision choice is
  ever exposed to an ordinary user — `GET /checklists/active` always
  returns exactly the one to use.
- Historical inspections do **not** merely reference `revision_id` for
  traceability — each `InspectionItemResult` also snapshots the item's
  `title`/`inspection_point`/`method`/`standard`/`instruction`/
  `is_critical` at submission time. This means a later revision (or even
  a hypothetical future edit path) can never retroactively change what a
  historical inspection displays, which is a stronger guarantee than
  revision-reference alone.
- Old revisions remain directly readable via
  `GET /checklists/{id}/revisions/{id}` even after a newer revision
  becomes active — proven by
  `test_old_checklist_revision_remains_readable_after_a_newer_one_becomes_active`
  and by the API-level `test_checklist_revision_direct_read_matches_active`.
- `test_new_checklist_revision_does_not_mutate_a_previously_submitted_inspection`
  proves introducing a new revision (with the same item IDs) after an
  inspection was submitted leaves that inspection's stored item title
  and `revision_id` byte-for-byte unchanged.

There is no checklist-authoring endpoint in Phase 3 (creating/editing
checklist masters/revisions is out of scope — see Section 15); the two
active checklists (VEHICLE, EQUIPMENT) ship as `MockRepository` seed data
only, and the immutability tests above simulate what a future authoring
phase would do by writing a second revision directly into the mock
store, to prove the read-side guarantees hold before any write-side
tooling exists.

======================================================================
6. FINDING BEHAVIOR
======================================================================

Every `FAIL` result creates exactly one `InspectionFinding`
(`status = OPEN`), snapshotting the item's title and its `is_critical`
flag at that moment. This satisfies the Phase 3 scope's "normal abnormal
finding" requirement. Explicitly **not** implemented:
- No automatic Repair Order is created for any finding — Repair is
  Phase 4 and the task brief forbids inventing this.
- No alert/severity-based escalation path for "critical" items — no
  source data marks any item critical (D03), and the alert severity
  model itself is a separate unapproved decision (A06 in the register).
  `is_critical` is carried on the finding purely so a later, explicitly
  approved phase can branch on it without re-deriving it from a possibly
  since-changed checklist.
- `FindingStatus` has a single member (`OPEN`) on purpose — any
  acknowledged/converted-to-repair/closed lifecycle belongs to Phase 4's
  Finding-to-Repair conversion decision (F02, TBD-BLOCKING), which this
  phase does not resolve.

Tested by `test_submit_inspection_fail_creates_finding` (finding fields,
linkage to the correct result, `is_critical=False`) and
`test_submit_inspection_all_pass_for_vehicle`/
`test_submit_inspection_accepts_na` (no finding when there is no FAIL).

======================================================================
7. REFERENCE IMAGE VS EVIDENCE IMAGE HANDLING
======================================================================

Both are the same underlying `Attachment` model (metadata +
`storage_ref`, going through `StorageProvider` — no binary content in the
repository), but kept structurally and semantically separate via
`AttachmentPurpose`:
- `CHECKLIST_REFERENCE_IMAGE` — attached only to a `ChecklistItem`
  (`reference_image_attachment_id`), belongs to the checklist/revision
  and is shared by every inspection that uses that item.
- `INSPECTION_EVIDENCE` — attached only to an `InspectionItemResult`
  (`evidence_attachment_ids: list[str]`), belongs to one specific
  submitted result.

The submission service rejects an evidence attachment ID that resolves
to an attachment with any other purpose (or does not exist) — see
`test_submit_inspection_unknown_evidence_attachment_is_rejected` — so an
evidence photo can never be silently reused as a reference image or vice
versa. On the frontend, `ChecklistItemCard` renders the two in visually
distinct positions (`reference_image` above the PASS/FAIL/N/A controls
with a "ภาพอ้างอิง" caption; evidence photos inside the FAIL-only
details block with a "รูปถ่ายหลักฐาน" caption) — proven by
`ChecklistItemCard.test.tsx`'s
"renders the reference image separately from evidence photos" test.

No seed checklist item ships with a reference image (no real image
exists to attach without fabricating one — see Section 13); the field
and rendering path are fully implemented and tested with a synthetic
attachment, ready for real reference images once supplied.

======================================================================
8. VEHICLE / EQUIPMENT SUPPORT
======================================================================

One inspection engine (`InspectionService`, `InspectionFormPage`,
`InspectionHistoryPage`, `InspectionDetailPage`) serves both asset types
via the existing `AssetType`/`AssetRef` pattern from Phase 2 — no
vehicle/equipment-specific inspection code path exists. Master identities
remain fully separate (unchanged from Phase 2): `Vehicle`/`Equipment` are
different Pydantic models, different repository methods, different ID
prefixes (`VEH-`/`EQP-`), and inspection asset validation reuses the
exact Phase 2 `VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND` codes rather than
merging them into one "asset not found" code.

New frontend routes (added to `App.tsx`, the frozen QR routes are listed
first and unchanged):
```
/vehicle/:vehicleId                (frozen, Phase 2 — unchanged)
/vehicle/:vehicleId/inspect         (new)
/vehicle/:vehicleId/inspections     (new)
/equipment/:equipmentId             (frozen, Phase 2 — unchanged)
/equipment/:equipmentId/inspect     (new)
/equipment/:equipmentId/inspections (new)
/inspections/:inspectionId          (new, shared detail view)
```
`InspectionFormPage`/`InspectionHistoryPage` read `vehicleId` or
`equipmentId` from the route params to derive `AssetType` — proven
end-to-end by the Playwright test "the same inspection engine supports
workshop equipment" (equipment checklist loads, submits, and reaches the
same `/inspections/{id}` detail page as a vehicle inspection).

======================================================================
9. MOBILE / RESPONSIVE IMPLEMENTATION
======================================================================

Built entirely on the frozen Phase 1 mobile-first primitives (`Card`,
`FormField`'s CSS conventions, `.sticky-actions`, `--tap-target: 44px`,
`ResponsiveTable`, `StatusBadge`) — no existing responsive rule was
changed, only new `.checklist-item-card*`/`.result-button*` rules added.

- Each checklist item renders as one touch-friendly `Card` with title,
  point/method/standard/instruction (only when not blank), reference
  image, and PASS/FAIL/N/A as three large buttons (`min-height:
  calc(--tap-target + 0.25rem)`), stacked full-width on phones
  (`< 481px`) and side-by-side from smartphone-landscape width up.
- Selecting FAIL reveals the remark + evidence controls immediately in
  the same card — no navigation to another page/step.
- The evidence file input uses `capture="environment"` so a phone opens
  its camera directly; upload/remove state (uploading indicator, photo
  thumbnail, "ลบรูป" button) is visible inline.
- The "ส่งผลการตรวจ" submit action uses the frozen `.sticky-actions`
  pattern so it stays reachable while scrolling a long checklist.
- No page introduces a wide table or requires horizontal scrolling;
  history uses the existing `ResponsiveTable` (stacked cards on phones,
  table from tablet width up).
- All new UI text is Thai; Thai text wrapping relies on the existing
  global `overflow-wrap`/`word-break` rules (unchanged).

Verified, not just designed: the new Playwright suite
(`e2e/inspection.spec.ts`) runs across all 5 required viewport
projects — smartphone portrait (375×667), smartphone landscape
(568×320), tablet portrait (768×1024), tablet landscape (1024×768),
desktop (1280×800) — asserting: checklist loads and renders Thai item
titles, PASS/FAIL/N/A buttons meet the 44px touch-target minimum, FAIL
reveals remark/photo controls without navigation, a real file upload via
`setInputFiles` reaches the evidence-required validation and finding
creation, no unintended horizontal scrolling after submission, history
list is reachable and shows the Thai pass/fail summary, and the same
flow works for equipment. See Section 10 for exact results.

======================================================================
10. EXACT AUTOMATED TESTS EXECUTED AND RESULTS
======================================================================

All commands below were executed in this session.

Backend:
```
$ cd backend && source .venv/bin/activate && pip install -e ".[dev]"
$ DATA_REPOSITORY=mock python -m pytest -q
72 passed in 1.35s   (47 pre-existing Phase 1/2 tests + 25 new)
```
New backend test files:
- `tests/test_inspections_api.py` (21 tests) — active checklist
  auto-loads for VEHICLE/EQUIPMENT, direct revision read matches active,
  controlled 404 for missing revision, PASS/FAIL/N/A accepted, FAIL
  without remark rejected (422), FAIL without required photo rejected
  (422, with `item_id` in `details`), missing/unknown item IDs rejected
  (422, with `missing_item_ids`/`unknown_item_ids` in `details`), invalid
  result enum rejected (422), unknown evidence attachment rejected (422),
  unknown vehicle/equipment returns controlled 404
  (`VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND`), equipment inspection uses
  the same engine, FAIL creates a linked finding with evidence, get/list
  inspection immutable read, attachment upload/download round-trip,
  attachment 404.
- `tests/test_mock_repository_inspection.py` (4 tests) — checklist data
  isolated per repository instance, old revision remains readable after
  a newer one becomes active, new revision does not mutate a previously
  submitted inspection, active-revision selection ignores a
  not-yet-effective future revision.
5 warnings, all pre-existing `HTTP_422_UNPROCESSABLE_ENTITY` deprecation
notices from Starlette (same pattern already present in `app/errors.py`
since Phase 1 — not introduced by this phase).

Frontend unit/component (Vitest):
```
$ cd frontend && npx vitest run
Test Files  15 passed (15)
     Tests  29 passed (29)     (18 pre-existing + 11 new)
```
New: `ChecklistItemCard.test.tsx` (4 tests — PASS/FAIL/N/A render as
Thai-labeled radio controls, clicking a control calls back, FAIL reveals
remark/required-photo controls immediately, reference image and evidence
photo render as separate `<img>` elements), `InspectionFormPage.test.tsx`
(3 tests — active checklist auto-loads and renders Thai titles, submit
stays disabled until every item is answered then posts the correct
PASS-only payload, FAIL without a remark is blocked client-side before
any request is sent), `InspectionHistoryPage.test.tsx` (2 tests — Thai
pass/fail summary row + link, Thai empty state), `InspectionDetailPage.test.tsx`
(2 tests — full immutable record renders in Thai including the finding
section, controlled Thai 404 for an unknown inspection id).

Frontend typecheck:
```
$ npx tsc -b
(no output; exit code 0 — PASSED)
```

Frontend lint:
```
$ npx oxlint
6 warnings, 0 errors — all `react(set-state-in-effect)` on the
data-fetch-in-useEffect pattern already flagged since Phase 1 (now also
on the 4 new inspection pages, same category, no new lint category
introduced).
```

Frontend production build:
```
$ npm run build
dist/index.html                 0.43 kB │ gzip:  0.30 kB
dist/assets/index-*.css         9.46 kB │ gzip:  2.40 kB
dist/assets/index-*.js        299.35 kB │ gzip: 90.67 kB
✓ built in 435ms
```
PASSED (up from Phase 2's 285.15 kB/88.06 kB gzip JS, for the 4 new pages
+ 1 new component + inspection types/labels/apiClient additions).

Frontend Playwright e2e (real Chromium, backend+frontend auto-started):
```
$ bash scripts/run_e2e_tests.sh
75 passed (37.4s)   across smartphone-portrait, smartphone-landscape,
                    tablet-portrait, tablet-landscape, desktop
```
55 pre-existing Phase 1/2 tests (11 per viewport × 5) all still pass
unmodified; 20 new results from `e2e/inspection.spec.ts`'s 5 tests × 5
viewport projects:
- "ตรวจเช็ค loads the active checklist automatically and submits an
  all-PASS inspection" — 44px+ PASS button, no horizontal scroll after
  submit.
- "marking an item FAIL shows remark/photo controls immediately and
  creates a finding" — real file upload via `setInputFiles`, 44px+
  submit button, finding + remark visible on the resulting detail page.
- "inspection history is reachable from Vehicle Detail and lists a
  submitted inspection".
- "the same inspection engine supports workshop equipment".
- "missing checklist item selection is blocked and a Thai not-found
  record shows for an unknown inspection id".

No test was claimed without being executed in this session.

======================================================================
11. MANUAL TEST PLAN
======================================================================

Run with `./scripts/run_dev.sh` (or `run_backend.sh` + `run_frontend.sh`),
`DATA_REPOSITORY=mock`, at `http://127.0.0.1:5173`.

1. **Vehicle inspection, all PASS** — open `/vehicle/VEH-1046`, tap
   "ตรวจเช็ค". Expected: 5 items load automatically in Thai, no revision
   picker anywhere. Tap "ผ่าน" on all 5. Expected: "ส่งผลการตรวจ" becomes
   enabled only once every item has an answer. Tap it. Expected:
   navigates to `/inspections/INS-...` showing all 5 items as "ผ่าน" and
   no "ข้อบกพร่องที่พบ" section.
2. **FAIL with required photo** — open `/vehicle/VEH-1046/inspect`
   again, mark the 5th item "ไม่ผ่าน". Expected: a remark box and
   "รูปถ่ายหลักฐาน (จำเป็น)" file input appear in the same card
   immediately (no extra page). Try submitting without a photo — expect
   a Thai validation message and no navigation. Attach a photo, add a
   remark, submit. Expected: the detail page shows "ข้อบกพร่องที่พบ"
   listing that item, the remark, and the photo thumbnail.
3. **History** — from `/vehicle/VEH-1046`, tap "ประวัติการตรวจเช็ค".
   Expected: both submissions from steps 1-2 appear, newest first, with
   correct pass/fail counts; tapping a row opens its immutable detail.
4. **Equipment** — repeat step 1 at `/equipment/EQP-0001/inspect`
   (4 items). Expected: identical workflow, separate history at
   `/equipment/EQP-0001/inspections`.
5. **Reference vs evidence** — inspect any item's card: confirm the
   evidence photo you attached in step 2 never appears above the PASS/
   FAIL/N/A controls (that position is reserved for a reference image,
   which is blank for all seeded items since none was supplied).
6. **Mobile phone test** — on a real phone (or DevTools device
   emulation) in portrait and landscape: open the inspect flow, confirm
   the PASS/FAIL/N/A buttons are easy to tap with one hand, the camera
   opens when adding a photo, no horizontal scrolling occurs, and the
   "ส่งผลการตรวจ" button stays reachable while scrolling.
7. **Desktop** — repeat steps 1-4 at ≥1280px width; confirm PASS/FAIL/
   N/A lay out side-by-side and history renders as a real table.
8. **Old revision stays readable** — `curl` (or open in a browser)
   `GET /api/v1/checklists/CHK-0001/revisions/REV-0001` before and after
   submitting inspections; confirm the response never changes.

======================================================================
12. KNOWN LIMITATIONS
======================================================================

- **Checklist content is placeholder/example data only** (see Section
  13/14) — no real inspection standard exists in this repository, so
  seed item titles are generic numbered placeholders ("รายการตรวจสอบ
  ตัวอย่างที่ N") and `method`/`standard`/`instruction`/`frequency` are
  all blank. This must be replaced with real content once the user
  supplies it; the revision/immutability/finding architecture itself
  does not need to change to do so.
- No checklist-authoring UI/endpoint exists (create/edit checklist
  masters or revisions) — out of Phase 3's acceptance tests, which only
  require the inspection *workflow*, not checklist administration. The
  two active checklists ship as fixed `MockRepository` seed data.
- `GoogleSheetsRepository`'s Phase 3 methods declare their tab/header
  schema but raise a controlled `RepositoryError`/`NotImplementedError`
  until real `GOOGLE_SHEET_ID`/`GOOGLE_APPLICATION_CREDENTIALS` exist —
  identical, expected limitation to every domain Phase 2 already shipped
  this way; this sandboxed environment has no Google credentials or
  network path to verify live Sheets I/O.
- No pager UI on the inspection history list (matches Phase 2's list
  pages) — the API supports `page`/`page_size`, only the small seeded
  dataset masks the missing pager control.
- No RBAC beyond the existing `DEV_AUTH_MODE` fixed development user —
  unchanged, pre-existing limitation from Phase 1, not introduced here.
- Removing an evidence photo in the form before submitting does not
  delete the already-uploaded file from storage (it simply stops being
  referenced) — acceptable for Phase 3 since no storage-quota/cleanup
  requirement exists yet; flag if orphaned-file cleanup becomes a
  requirement in a later phase.
- The `react(set-state-in-effect)` lint warning (pre-existing since
  Phase 1) now also appears on the 4 new pages, for the same
  data-fetch-in-`useEffect` reason as every other detail page — not a
  new issue category.

======================================================================
13. OPEN DECISIONS ENCOUNTERED
======================================================================

Checked against `OPEN_DECISIONS_REGISTER_EN.txt`. Four directly govern
this phase (D01-D04); none were resolved, approved, or silently decided.
See Section 14 for exactly how each was handled.

- **D01 — Checklist Assignment Rules** (`TBD-BLOCKING before multiple
  checklist families`). No asset/model/type → checklist assignment
  matrix exists; instead there is exactly one active checklist family
  per `AssetType` (VEHICLE, EQUIPMENT). This does not trigger D01's
  stated blocking condition ("before multiple checklist families")
  because there is only one family per type, but it is *not* a general
  solution — a future requirement like "different checklist per vehicle
  model" still needs D01 answered before it can be built.
- **D02 — Daily vs Weekly Scheduling** (`TBD-BLOCKING before automatic
  due logic`). No automatic due/scheduling logic of any kind was built.
  `ChecklistItem.frequency` exists as a free-text field (architecture
  only) and is left unset by every seed item.
- **D03 — Critical Inspection Item Rules** (`SOURCE-DATA-REQUIRED`). No
  seed item is marked critical; `is_critical` defaults to `False`
  everywhere it appears (item, result, finding).
- **D04 — Inspection Correction Policy** (`TBD-BLOCKING before
  production`). No correction/void/supersede capability exists at any
  layer (domain, repository, API, or UI) — submitted inspections are
  create-and-read only.

Also touched, already-approved decisions reused without change:
- **C02 (Equipment status vocabulary)** — `EquipmentOperationalStatus`
  is used unchanged for equipment-status display on the detail page; no
  inspection code reads or writes equipment/vehicle operational status.
- **A10 (`/api/v1` partially frozen)** — new routes follow the existing
  prefix/error-envelope convention; no compatibility-policy question was
  reached.

Not touched by this phase (out of reach, same as Phase 1/2's own
reports): A01-A09 (transaction ID strategy for other domains, counter
reconciliation, alert model, soft-delete, concurrency, sheet schema
version, test-data separation, auth method), B02-B04, C01/C03, E-M
sections in full.

======================================================================
14. ANY GOVERNANCE DECISIONS INTENTIONALLY LEFT UNRESOLVED
======================================================================

D01, D02, D03, and D04 were all deliberately left unresolved, per the
task brief's explicit instruction not to make these decisions. Concretely:

- **D01**: implemented the narrowest placeholder that does not require an
  assignment policy — "one active checklist per asset type" — documented
  in `app/domain/checklist.py`'s module docstring and
  `Repository.get_active_checklist_revision`'s docstring as a Phase 3
  simplification, not a frozen business rule. If a future phase needs
  per-model or per-category checklists, D01 must be answered first.
- **D02**: no scheduling/due logic was written at all — "ตรวจเช็ค" remains
  a fully manual, on-demand action from the detail page. The `frequency`
  field is present in the schema (per the phase scope's explicit
  requirement to support it "where source data exists") but is never
  read by any code — it is pure metadata, unset in seed data, and
  changing/populating it later requires no architecture change.
- **D03**: `is_critical` is architected everywhere (item, snapshotted
  result, finding) but is `False` on every seed item and is never
  computed or inferred — it can only ever become `True` once real,
  approved source data supplies it (there is no code path that derives
  it from anything else).
- **D04**: rather than guessing a correction/void/supersede design, none
  was built — `POST /api/v1/inspections` and the two `GET` routes are
  the entire inspection write/read surface. This is the strictest
  possible reading of "submitted historical inspection data must not be
  edited in place" and leaves D04 fully open for the user to decide
  later without any existing behavior to migrate away from.

`OPEN_DECISIONS_REGISTER_EN.txt` was **not** modified — none of D01-D04
were approved by the user in this task, so none were marked resolved in
the register, consistent with the task brief's explicit instruction.

======================================================================
15. CONFIRMATION THAT PHASE 4 WAS NOT IMPLEMENTED
======================================================================

Confirmed. No Repair domain model, repair status lifecycle, repair
routes, or repair UI exist anywhere in this change. FAIL results stop at
creating an `InspectionFinding` with a single `OPEN` state and no
conversion path — `FindingStatus` intentionally has only one member so
there is nothing to "half-implement" of Phase 4's Finding-to-Repair
conversion (F02, itself `TBD-BLOCKING` and unapproved). PM
(`04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt`) was not read as an implementation
source for this phase — only as prior context already summarized in the
baseline.

======================================================================
16. FROZEN PHASE 1/2 CONTRACTS AFFECTED: NO
======================================================================

- `/api/v1` versioning, the common error envelope, `Page`/`PageParams`
  pagination shape, the opaque prefixed stable-ID convention, UTC
  ISO-8601 timestamps, `RequestContext`/`DEV_AUTH_MODE` — all reused
  unchanged.
- `Repository`/`StorageProvider` — extended only (new abstract methods),
  exactly as Phase 1's docstring on `Repository` anticipated; `mode`/
  `check_ready` and every Phase 2 method's signature/behavior are
  byte-for-byte unchanged (all 47 pre-existing backend tests re-run and
  pass unmodified as a subset of the 72 total).
- `VehicleService`/`EquipmentService`, `Vehicle`/`Equipment`/
  `VehicleModel` domain models, and their API routes/schemas — untouched;
  `InspectionService` calls the same repository asset-lookup methods and
  reuses the same not-found error codes rather than adding a parallel
  path.
- Frozen Phase 2 QR routes `/vehicle/{vehicle_id}` and
  `/equipment/{equipment_id}` — unchanged; the new
  `/vehicle/{id}/inspect`, `/vehicle/{id}/inspections`, and
  `/equipment/{id}/...` routes are separate nested paths. No checklist
  revision ID or inspection ID was encoded into the permanent QR route
  (verified: `App.tsx`'s `/vehicle/:vehicleId` route element and its
  path pattern are unchanged from Phase 2).
- Mobile-first responsive foundation (`Card`, `ResponsiveTable`,
  `FormField`, `.sticky-actions`, `--tap-target`, breakpoints) — reused
  as-is; only new, additive CSS classes were introduced for the
  checklist-item card and result buttons.
- All 55 pre-existing Playwright tests and all 18 pre-existing Vitest
  tests re-run and pass unmodified as a subset of the current totals (75
  and 29 respectively).

No STOP was required — no frozen contract needed to change to implement
this phase.

======================================================================
17. FINAL PHASE 3 IMPLEMENTATION STATUS: PASS
======================================================================

All mandatory Phase 3 scope items are implemented and covered by
automated tests that were actually executed in this session (backend
72/72, frontend unit 29/29, typecheck/build/lint clean, Playwright
75/75 across all 5 required viewport bands). D01-D04 remain correctly
unresolved with documented, reversible placeholders rather than invented
business rules or fabricated checklist content. No Phase 1/2 frozen
contract was changed. Phase 4 was not started.

======================================================================
ADDITIONAL PHASE-PROMPT REPORT FIELDS
======================================================================

FROZEN CONTRACTS USED: see Section 16.

DATABASE / SHEET TABLES USED:
- Mock mode (in-memory, seeded): `checklists` (2: `CHK-0001` VEHICLE,
  `CHK-0002` EQUIPMENT), `checklist_revisions` (2, one per checklist,
  `revision_number=1`), `checklist_items` (5 for `REV-0001`, 4 for
  `REV-0002`), `attachments`, `inspections`, `inspection_item_results`,
  `inspection_findings` (all created at runtime as inspections are
  submitted — no seed rows).
- Google Sheets mode: the 7 tab names/header schemas above are declared
  in `app/repositories/google_sheets/schemas.py` but not yet read/written
  against a real spreadsheet (see Section 12).

UI PAGES ADDED:
- `/vehicle/:vehicleId/inspect`, `/equipment/:equipmentId/inspect` —
  `InspectionFormPage`.
- `/vehicle/:vehicleId/inspections`, `/equipment/:equipmentId/inspections`
  — `InspectionHistoryPage`.
- `/inspections/:inspectionId` — `InspectionDetailPage`.

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
Try the flow once both are running: open
`http://127.0.0.1:5173/vehicle/VEH-1046`, tap "ตรวจเช็ค".
OpenAPI docs: http://127.0.0.1:8000/docs.

STOP HERE. DO NOT IMPLEMENT THE NEXT PHASE.
