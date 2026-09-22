# Web/API Phase 6 — Driver, Certificates, Documents, Work History, GPS, and Alerts — Phase Result Report

> **Provenance note (read first):** This report is produced by a
> **documentation-only closure task** (branch `review/phase6-closure-docs`,
> reviewed HEAD `0efa1243552ba958b497d253dec2bc8f7e0c376f`). It documents a
> Phase 6 implementation that was **already built and merged in earlier
> sessions** before this task began. This task did not write any Phase 6
> application code; it inspected the current working tree/tests/git history
> directly and reports what is actually present. **This is Revision 3.**
> Revision 2 corrected a commit-range error and several other factual
> issues found by reviewer verification of Revision 1. Revision 3 corrects
> a second round of reviewer findings against Revision 2 — a false claim
> that certificate renewal lacks dedicated `storage_ref` test coverage, an
> incorrect reading of D26/A11's governance scope for certificate-expiry
> and inactive-vehicle alert generation, and broken cross-document section
> references — see the companion verification report's Section 15 for the
> itemized correction checklist. Section 4 ("FILES ADDED"/"FILES
> MODIFIED") lists two
> separate things explicitly labelled apart: (a) the full Phase 6
> implementation inventory (informational, derived from git history) and
> (b) this task's own changed-file list (normative — the only files this
> task itself touches).

PHASE: Web/API Phase 6 — Driver/Operator, Certificates, Model Documents,
Work History (events + daily summary), GPS, and Alerts (read + internal
lifecycle + effective-setting policy)

STATUS: **PASS**

Documents read in full before writing this report, as required by the
closure task instructions:
- `docs/claude-prompts/web-api/00_README_EXECUTION_ORDER_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/06_PHASE6_DRIVER_CERT_DOCS_HISTORY_GPS_ALERTS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/phase-results/web-phase-05-result.md`,
  `docs/phase-results/web-phase-05-verification.md`
- `CHANGELOG.md`, `README.md`, `backend/README.md`
- `docs/claude-prompts/web-api/07_PHASE7_DASHBOARD_SEARCH_REPORTING_EN.txt`
  (read only to assess the Phase 7 boundary in Section 20 below — **not
  executed**, per the closure task's explicit instruction)

Plus direct inspection of the actual current source (`app/domain/*.py`,
`app/api/v1/*.py`, `app/repositories/*`, `frontend/src/pages/*.tsx`,
`frontend/src/components/*.tsx`), the full Phase 6 backend/frontend test
files (function-by-function, not just file names), `git diff --name-status`
across the corrected Phase 6 commit range (Section 4), and that range's
diff against `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` —
not only prior audit summaries, which are treated as supporting evidence,
not authority over current code.

---

## 1. OBJECTIVE

Close documentation gap **A1** (missing `web-phase-06-result.md` /
`web-phase-06-verification.md` / CHANGELOG entry for an already-merged
Phase 6 implementation) and reassess Phase 6 closure now that **A2**
(Batch 6F, model-document revision UI) has been implemented and merged at
`0efa1243552ba958b497d253dec2bc8f7e0c376f`. This report and its companion
verification report are the deliverable; **no application code, test,
dependency, lockfile, config, governance text, prompt baseline, seed data,
or API contract was changed by this task** (Revision 1 or this
Revision 2).

## 2. PREREQUISITE CHECK

Phases 1–5 accepted (Phase 5 verification: PASS, "NEXT PHASE READINESS:
READY"). Verified directly in this task:
- `git branch --show-current` = `review/phase6-closure-docs`
- `git rev-parse HEAD` = `0efa1243552ba958b497d253dec2bc8f7e0c376f` (exact
  required SHA)
- `git status --short` = empty at the start of both the original task and
  this correction task (confirmed independently both times)
- `git diff --check` = clean (exit 0, no whitespace-conflict markers,
  confirmed independently both times)

## 3. FROZEN CONTRACTS USED

Phase 6's own implementation (already merged; verified unchanged by this
documentation task) reused, without redefining:
- `/api/v1` prefix, route-registration pattern, common error envelope
  (`ApiError`/`build_error_envelope`).
- `Repository`/`StorageProvider` abstractions — extended additively for
  every new Phase 6 abstract method; no Phase 1–5 method signature was
  narrowed. **This does not mean no pre-existing file was touched** — see
  Section 4b for the full list of modified non-Phase-6-domain files
  (`backend/pyproject.toml`, `requirements.txt`,
  `google_sheets/client.py`, four pre-existing test files, `NavBar.tsx`,
  `VehicleDetailPage.tsx`/its test, `common.py`) discovered by the
  corrected range's `git diff --name-status`.
- `AssetRef`/`AssetType`, `ComponentRole` (`CARRIER_ENGINE`/`CRANE_ENGINE`/
  `PTO`, C04), `OperationalStatus` (Vehicle) — all reused unchanged.
- The opaque `PREFIX-NNNN` stable-ID convention (A01, still
  `TBD-BLOCKING`) for backend-generated IDs — **with one explicit
  exception**: `Alert.alert_id` is **caller-supplied**, never generated by
  `AlertService.ensure_condition_alert` (confirmed directly:
  `alert_service.py`'s own docstring states "a brand-new ACTIVE row is
  created using the caller-supplied `alert_id` (never generated here —
  see A01)"). Driver/certificate/model-document/event IDs are backend-
  generated (e.g. `create_model_document`'s `self._next_id(rows,
  "model_document_id", "MDOC")`).
- Thai UI / English backend-code convention; mobile-first responsive
  primitives (`Card`, `ResponsiveTable`, `FormField`, `.sticky-actions`).
- The pre-existing Phase 3 `Attachment`/`AttachmentPurpose` upload/download
  mechanism (`POST /api/v1/attachments`,
  `GET /api/v1/attachments/{id}/file`) — **reused as-is, not replaced**;
  Phase 6's `storage_ref` fields are a separate, new, purely opaque
  metadata concept (Section 14).

This documentation task itself uses no frozen contract beyond reading it —
it adds no code and calls no API.

## 4. FILES ADDED / FILES MODIFIED

**(a) This task's own changed files (normative — the only files this
review branch actually modifies, across both the original task and this
correction):**

Added:
- `docs/phase-results/web-phase-06-result.md` (this report)
- `docs/phase-results/web-phase-06-verification.md`

Modified:
- `CHANGELOG.md` (Phase 6 entry appended/corrected; all prior entries
  preserved verbatim)

No other file is touched by this task. `README.md`/`backend/README.md`
were read and evaluated but intentionally **not** changed — see Section 13
(Screen/UX Notes) for the explicit reasoning.

**(b) Whole Phase 6 implementation inventory (informational only —
derived from `git diff --name-status 3e54e6035c10dcb59454848d56c0866be504227c
0efa1243552ba958b497d253dec2bc8f7e0c376f`; NOT files this task added or
modified):**

**Commit range correction (Revision 2):** Revision 1 of this report used
the range `770cbc7..0efa124` (31 commits) and described it as "the whole
Phase 6 range." That range is **git-exclusive of its lower bound**, and
`770cbc77304926947717f16607f91d92341ccce6` **is** the Batch 1 commit
itself ("feat(phase6): add driver operator and assignment history") — so
`770cbc7..0efa124` silently **excludes Batch 1**. The correct range is
`3e54e6035c10dcb59454848d56c0866be504227c..0efa1243552ba958b497d253dec2bc8f7e0c376f`
(**32 commits**, `3e54e60` being the last pre-Phase-6 commit and thus the
correct exclusive base), verified directly:
```
$ git log -1 --format='%H %P' 770cbc7
770cbc77304926947717f16607f91d92341ccce6 3e54e6035c10dcb59454848d56c0866be504227c
$ git log --oneline 770cbc7..0efa124 | wc -l
31   # excludes 770cbc7 itself — WRONG range for "whole Phase 6"
$ git log --oneline 3e54e60..0efa124 | wc -l
32   # includes 770cbc7 (Batch 1) — CORRECT range
```
This report and its companion verification report now use
`3e54e60..0efa124` (32 commits) consistently.

Full `git diff --name-status 3e54e60 0efa124` output (this is the
complete, actual file inventory — not a curated subset):

*Backend API (new files, `A`):*
`app/api/v1/alert_schemas.py`, `alerts.py`, `daily_summaries.py`,
`daily_summary_schemas.py`, `driver_schemas.py`, `drivers.py`,
`latest_location_schemas.py`, `latest_locations.py`,
`model_document_schemas.py`, `model_documents.py`,
`vehicle_certificate_schemas.py`, `vehicle_certificates.py`,
`vehicle_event_schemas.py`, `vehicle_events.py`.

*Backend domain (new files, `A`):*
`app/domain/alert.py`, `alert_service.py`, `alert_setting.py`,
`alert_setting_service.py`, `daily_summary.py`, `daily_summary_service.py`,
`driver.py`, `driver_service.py`, `model_document.py`,
`model_document_service.py`, `vehicle_certificate.py`,
`vehicle_certificate_service.py`, `vehicle_event.py`,
`vehicle_event_service.py`.

*Backend domain (modified, `M`, pre-existing files — NOT new):*
- `app/domain/common.py` — `bangkok_today`/`to_bangkok_date`/
  `next_bangkok_midnight` added (Batch 4C timezone support).
- `app/domain/location_snapshot.py` — **this file existed before Batch 1**
  and was **modified**, not created new, to add Batch 6D's `LocationService`
  read-side alongside its pre-existing write-side content. Revision 1
  incorrectly implied this file's Phase 6 content was simply "new."

*Backend API/infra (modified, `M`):*
`app/api/v1/router.py`, `app/dependencies.py`, `app/repositories/base.py`,
`app/repositories/google_sheets/client.py`,
`app/repositories/google_sheets/repository.py`,
`app/repositories/google_sheets/schemas.py`,
`app/repositories/mock/repository.py`, `app/repositories/mock/seed_data.py`,
**`backend/pyproject.toml`**, **`backend/requirements.txt`** (both
modified for the `tzdata`/`gspread`/`google-auth` dependency additions —
Revision 1 omitted `pyproject.toml` from this list).

*Backend tests (new files, `A`, 13 files):*
`test_alert_phase6_batch5a.py`, `test_alert_phase6_batch5b.py`,
`test_alert_setting_phase6_batch5c.py`, `test_alert_setting_phase6_batch5d.py`,
`test_daily_summary_batch4c.py`, `test_driver_phase6_batch1.py`,
`test_latest_location_projection_batch4b.py`,
`test_latest_location_read_api_batch6d.py`, `test_model_document_batch3a.py`,
`test_model_document_batch3b.py`, `test_vehicle_certificate_batch2a.py`,
`test_vehicle_certificate_batch2b.py`, `test_vehicle_event_batch4a.py` —
**428 test functions** (exact count, computed directly in this task via
`grep -cE "^(async )?def test_"` per file, not an approximation).
Per-file breakdown: `test_alert_phase6_batch5a.py` 22,
`test_alert_phase6_batch5b.py` 66, `test_alert_setting_phase6_batch5c.py`
21, `test_alert_setting_phase6_batch5d.py` 36,
`test_daily_summary_batch4c.py` 49, `test_driver_phase6_batch1.py` 32,
`test_latest_location_projection_batch4b.py` 24,
`test_latest_location_read_api_batch6d.py` 12,
`test_model_document_batch3a.py` 27, `test_model_document_batch3b.py` 33,
`test_vehicle_certificate_batch2a.py` 28,
`test_vehicle_certificate_batch2b.py` 37,
`test_vehicle_event_batch4a.py` 41 (sum = 428).

*Backend tests (modified, `M`, pre-existing files — Revision 1 wrongly
implied "every old test file was unchanged"):*
- `test_google_sheets_real_io.py` (+242/-7 lines — includes a real
  behavior change to the fake `gspread`-shaped test double's `update()`
  method, made "column-range-aware" for Batch 5B's alert-lifecycle sheet
  updates, not merely additive new test cases; see Section 6 for detail).
- `test_google_sheets_repository_completion.py` (+41/-0).
- `test_mock_repository_vehicle.py` (+37/-0).
- `test_pm_work_order_api.py` (+48/-0).
These four files' *net* changes are additive (no existing assertion was
removed in the latter three; the first file's 7 deleted lines were a
fake-client method being replaced by a more capable one, not a test
assertion being weakened), but "additive" and "unchanged" are not the
same claim, and Revision 1 conflated them.

*Frontend (new files, `A`):*
`frontend/e2e/driver-phase6-batch1.spec.ts`,
`frontend/e2e/model-document-revision.spec.ts`,
`frontend/src/components/VehicleLatestLocationCard.tsx` (+ `.test.tsx`),
`frontend/src/pages/DriverDetailPage.tsx` (+ `.test.tsx`),
`DriverListPage.tsx` (+ `.test.tsx`), `ModelDocumentsPage.tsx`
(+ `.test.tsx`) — **`ModelDocumentsPage.tsx`/`.test.tsx` are NEW over the
whole `3e54e60..0efa124` range** (added by Batch 3A, `A` status in the
range diff), **then further modified by Batch 6F** (commit `0efa124`
itself) — both facts are true and distinct; Revision 1's phrasing risked
implying they were merely "modified" over the whole range. `
VehicleAlertsPage.tsx` (+ `.test.tsx`), `VehicleCertificatesPage.tsx`
(+ `.test.tsx`), `VehicleDailySummaryPage.tsx` (+ `.test.tsx`),
`VehicleDriverAssignmentsPage.tsx` (+ `.test.tsx`),
`VehicleWorkHistoryPage.tsx` (+ `.test.tsx`).

*Frontend (modified, `M`, pre-existing files):*
`frontend/src/App.tsx` (additive routes), **`frontend/src/components/
NavBar.tsx`** (adds one nav item, `{ to: '/drivers', label: 'คนขับทั้งหมด'
}`, with an inline comment explaining the distinct wording from
`VehicleDetailPage`'s own per-vehicle driver link — Revision 1 omitted
`NavBar.tsx` from the modified-file list entirely), `frontend/src/lib/
labels.ts`, `frontend/src/lib/types.ts`, `frontend/src/pages/
VehicleDetailPage.tsx` (+ its test file — embeds the new latest-location
card / action links).

*Governance (modified, `M`):*
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` (A06/A07/A11
additions only — see the verification report Section 2).

**Batch 6F's own commit (`0efa124`) file list** (a strict subset of the
above, shown separately per the reviewer's request — this commit touches
**four** files, not three):
```
frontend/e2e/model-document-revision.spec.ts   | 148 ++
frontend/src/lib/labels.ts                     |  11 +
frontend/src/pages/ModelDocumentsPage.test.tsx | 916 ++++...
frontend/src/pages/ModelDocumentsPage.tsx      | 573 ++++...
4 files changed, 1589 insertions(+), 59 deletions(-)
```
Revision 1 attributed this diff to "the page, its test file, and a new
e2e spec" — omitting `frontend/src/lib/labels.ts` (+11 lines, new Thai
label strings for the revision workflow) as a fourth touched file.

## 5. API ROUTES ADDED (whole Phase 6, informational)

Driver / assignment (Batch 1):
- `POST /api/v1/drivers`
- `GET /api/v1/drivers`
- `GET /api/v1/drivers/{driver_id}`
- `PATCH /api/v1/drivers/{driver_id}`
- `GET /api/v1/vehicles/{vehicle_id}/driver-assignments`
- `POST /api/v1/vehicles/{vehicle_id}/driver-assignments`
- `POST /api/v1/vehicle-driver-assignments/{assignment_id}/end`

Certificates (Batch 2A/2B):
- `POST /api/v1/vehicles/{vehicle_id}/certificates`
- `GET /api/v1/vehicles/{vehicle_id}/certificates`
- `GET /api/v1/certificates/{certificate_id}`
- `POST /api/v1/certificates/{certificate_id}/renew`

Model documents (Batch 3A/3B):
- `POST /api/v1/models/{model_id}/documents`
- `GET /api/v1/models/{model_id}/documents`
- `GET /api/v1/model-documents/{model_document_id}`
- `POST /api/v1/model-documents/{model_document_id}/revise`

Vehicle events / work history (Batch 4A):
- `POST /api/v1/vehicle-events`
- `GET /api/v1/vehicle-events/{event_id}`
- `GET /api/v1/vehicles/{vehicle_id}/events`

Daily summary (Batch 4C):
- `GET /api/v1/vehicles/{vehicle_id}/daily-summaries` (read-only; no
  write route exists or is intended)

Latest location (Batch 6D):
- `GET /api/v1/vehicles/{vehicle_id}/latest-location` (read-only)

Alerts (Batch 5A — **read-only**, confirmed by direct grep that no
POST/PATCH/PUT/DELETE verb exists in `alerts.py`):
- `GET /api/v1/vehicles/{vehicle_id}/alerts`
- `GET /api/v1/alerts/{alert_id}`

AlertSetting: **no HTTP route exists at all** — confirmed by
`grep -rln "AlertSetting|alert_setting" backend/app/api/v1/*.py` returning
zero matches. It is reachable only through the internal
`AlertSettingService` (Section 16).

## 6. DATABASE / SHEET TABLES USED

Declared Google Sheets tab schemas (header-mapped): `driver_master`,
`vehicle_driver`, `vehicle_certificate`, `model_document`, `vehicle_event`,
`latest_location`, `daily_summary`, `alert`, `alert_setting`.

**Correction (Revision 2) — this is real adapter I/O, not a controlled-
error stub.** Revision 1 stated that `GoogleSheetsRepository` "declares
the same schema + the project's established controlled-error stub
pattern" for Phase 6 methods. This was **wrong**, confirmed by direct
reading of the actual method bodies at this HEAD. Three distinct levels
of evidence must be kept separate:

1. **(a) Implemented adapter/client I/O — real, in application code.**
   `app/repositories/google_sheets/client.py`'s own module docstring
   states plainly: *"Google Sheets client/adapter — real read/write I/O"*,
   wrapping the actual third-party `gspread` library with
   service-account auth (`GOOGLE_APPLICATION_CREDENTIALS`) against a
   sheet named by `GOOGLE_SHEET_ID`, every call run via
   `asyncio.to_thread`. This is **not new to Phase 6** (it dates to "Core
   Demo Fixes Delta REV05," a pre-Phase-6 body of work) — but Phase 6's
   own repository methods call into it exactly like every domain added
   since REV05. Concretely, at this HEAD:
   `GoogleSheetsRepository.create_model_document` (repository.py:4161)
   calls `self._client.read_rows(...)` then `self._client.append_row(...)`;
   `get_alert`/`list_alerts_for_vehicle` (repository.py:4694,4706) call
   `self._client.find_row(...)`/`self._client.read_rows(...)`. Driver,
   certificate, daily-summary, revision, and alert-lifecycle methods
   follow the identical pattern. **None of these raise
   `NotImplementedError`/an unconditional `RepositoryError` stub** — they
   perform real row read/append/update calls through the adapter.
2. **(b) Automated fake-client/adapter tests — what was actually
   exercised in this task's fresh pytest run.** `test_google_sheets_real_io.py`
   and `test_google_sheets_repository_completion.py` (both re-run fresh
   in this task, Section 11) exercise this real adapter/engine logic
   against a **`FakeWorksheet`/`FakeSpreadsheet`** pair implementing just
   enough of `gspread`'s surface (`row_values`, `get_all_records`,
   `append_row`, `update`, `worksheets`, `worksheet`) for
   `GoogleSheetsClient`'s generic row engine to run — confirmed directly
   by that test file's own module docstring: *"exercised against a FAKE
   in-memory `gspread`-shaped client (never the real Google API/network
   ... Unit/repository tests must mock/fake the Google API/client and
   MUST NOT mutate the real live spreadsheet by default)."* This proves
   the header-mapping/append-vs-update/null-preservation *engine logic*
   correctly, with **zero network dependency** — a real and meaningful
   test, but not live-Sheets validation.
3. **(c) Live credentialed Google Sheets validation — NOT performed by
   this task, and no evidence found that it has ever been performed for
   Phase 6 methods.** No test file gated on real
   `GOOGLE_APPLICATION_CREDENTIALS`/`GOOGLE_SHEET_ID` values was found for
   any Phase 6 method (the only credential-related code found in the
   test suite deliberately *unsets* `GOOGLE_SHEET_ID` to test the
   "not configured" error path). This task did not set real credentials,
   did not connect to any live spreadsheet, and makes no claim of live
   Sheets validation for Phase 6 or any other phase.

**Correct summary sentence to replace Revision 1's "controlled-error
stub" claim:** Phase 6's `GoogleSheetsRepository` methods are real,
adapter-backed implementations (level a), proven correct against a fake
in-memory client (level b), with no live credentialed validation
performed or claimed (level c) — this is a materially different and more
complete implementation than the "stub" framing Revision 1 used, which
described an earlier phase's now-superseded pattern.

## 7. UI PAGES ADDED

- Driver list/detail (`/drivers`, `/drivers/:driverId`); per-vehicle
  assignment history (`/vehicle/:vehicleId/drivers`).
- Vehicle certificates (`/vehicle/:vehicleId/certificates`).
- Model documents, including the Batch 6F revision workflow
  (`/models/:modelId/documents`).
- Vehicle work history (`/vehicle/:vehicleId/work-history`), including
  Batch 6E's per-event GPS column.
- Vehicle daily summary (`/vehicle/:vehicleId/daily-summary`).
- Vehicle alerts, read-only (`/vehicle/:vehicleId/alerts`).
- Latest-location GPS card embedded in `VehicleDetailPage` (Batch 6D).

No UI page exists for `AlertSetting` (consistent with it having no public
API route — Section 5).

---

## 8. IMPLEMENTATION SUMMARY (by batch, as actually built)

**Batch 1 — Driver/Operator.** Update semantics span **two distinct
layers, which Revision 1 conflated:**
- **`DriverService.update_driver`** (`app/domain/driver_service.py:71`)
  is the **PATCH partial-update layer**: a field omitted from the request
  body (`fields_set` = `UpdateDriverRequest.model_fields_set`) keeps its
  current stored value; a field present in the request — including an
  explicit JSON `null` — is applied exactly as given (an explicit `null`
  clears it). `driver_name_th` itself is always required and is not
  subject to this omit/null distinction. The service's own docstring
  explicitly flags this null-clears behavior as "not an established
  project-wide rule... this endpoint's own continued behavior," not a
  general pattern to assume elsewhere.
- **`Repository.update_driver`** (the interface and both its `Mock`/
  `GoogleSheets` implementations) is a **full-replace contract** — it has
  no concept of "omitted vs explicit null" at all; it always receives
  final, already-resolved values from the service layer above it and
  simply writes them. Revision 1's phrasing ("a full-replace contract
  distinguishing an omitted field from an explicit null") incorrectly
  attributed the PATCH-resolution behavior to the repository layer,
  when that resolution happens one layer up, in the service.

**Driver master fields are not versioned** — only one current row per
driver exists; there is no historical record of a prior name/phone/
license value. `VehicleDriverAssignment` is the append-only history
mechanism: `assign_driver` always inserts a new row and never modifies an
existing one (no PRIMARY-exclusivity rule); `end_assignment` only ever
sets `end_at` on the exact target row and is idempotent.

**Batch 2A/2B — Certificates.** `VehicleCertificate` renewal
(`POST /certificates/{id}/renew`, `vehicle_certificate_service.py:167`)
is a **two-write operation**: WRITE 1 creates a brand-new row
(`create_vehicle_certificate`, new `certificate_id`, `status=ACTIVE`);
WRITE 2 (`mark_vehicle_certificate_replaced`) sets the **source** row's
status to `REPLACED` and links `replaced_by_certificate_id` — the source
row is never deleted or otherwise altered. **No true atomicity is
implemented** (Google Sheets has none) — but renewal has **two distinct,
separately-tested safeguards, which Revision 1 collapsed into one
inaccurate claim ("retry creates another row"):**
1. **Completed-renewal retry** (source already `REPLACED`): returns the
   existing successor if its linkage is internally consistent; raises
   `422 VEHICLE_CERTIFICATE_ACTIVE_STATE_CONFLICT` if the linkage is
   missing/inconsistent (`test_renew_corrupt_replaced_linkage_fails_loudly`).
2. **Corruption guard** (source still `ACTIVE`, code lines ~269–293): before
   performing WRITE 1, the source's own `certificate_type_code` group
   (after reconciling every sibling's expiry too) must contain **exactly
   one** `ACTIVE` row, and it must be the source itself. This catches the
   specific case where an **earlier** renewal attempt's WRITE 1 succeeded
   but WRITE 2 failed (leaving old+new both `ACTIVE`) — a subsequent call
   is **rejected with `422 VEHICLE_CERTIFICATE_ACTIVE_STATE_CONFLICT`
   before any new row is created**, proven directly by
   `test_renewal_rejected_when_more_than_one_active_in_group_adds_no_row`
   (pre-seeds two `ACTIVE` rows in one group, calls `renew_certificate`,
   asserts the 422 and asserts the certificate count is **unchanged**
   after the call). **Precisely stated:** when a certificate's own
   `certificate_type_code` group is already left in this specific
   two-`ACTIVE`-rows corrupt state by an earlier partial failure, a
   **subsequent** renewal attempt against either of those two rows is
   rejected before any further row is created — it fails closed instead
   of silently compounding the corruption with a third row. This is a
   guard against *retrying into* an already-corrupt state, not a general
   guarantee that no partial failure of any kind can ever leave the
   system in an unexpected state. The orphan `ACTIVE` row from the
   original partial failure is **still not automatically reconciled**
   (manual reconciliation is still required to resolve which of the two
   `ACTIVE` rows is canonical) — the guard prevents a *subsequent renewal
   attempt* from compounding the problem, it does not *fix* the
   underlying inconsistency, and it is not a claim of atomicity or
   automatic orphan recovery.

Expiry reconciliation (`ACTIVE`→`EXPIRED`) is **lazy/read-triggered**
(`_reconcile_expiry`, using `bangkok_today()`), not scheduled.

**Batch 3A/3B — Model Documents.** `ModelDocument` revision
(`POST /model-documents/{id}/revise`, `model_document_service.py:80`)
uses the same two-write shape (WRITE 1 creates a new row inheriting
`model_id`/`document_type`; WRITE 2 `finalize_model_document_revision`
closes the source row and links it), **but has NO equivalent corruption
guard** — confirmed by direct code reading: the only pre-write check is
"does the source already have a `replaced_by_document_id` link" (the
completed-revision-retry case). If WRITE 1 succeeds and WRITE 2 fails,
the source's link remains unset, so **a subsequent retry does NOT detect
the orphan and runs the normal path again — creating ANOTHER new
candidate row**, exactly as the service's own docstring states in detail:
*"The retry therefore runs the normal path again: it creates ANOTHER new
candidate row (WRITE 1) and, if WRITE 2 succeeds this time, links the
source to that second candidate — not to the original orphan. The
original orphan is not deleted, relinked, or otherwise touched."* No
dedicated automated test exercises this specific scenario end-to-end (it
is a disclosed absence-of-a-guard, not a positively-tested guarantee) —
unlike certificate renewal's corruption guard, which **is** positively
tested (previous paragraph). **To be precise about what "compounds":** the
retry's own second candidate row is **not** itself an orphan — if WRITE 2
succeeds on the retry, that second row becomes the properly-linked
successor, exactly as a normal revision would. What compounds is that the
**original** orphan row (from the earlier failed attempt) is left behind,
unlinked and untouched, permanently, in addition to the successful
revision now existing — i.e. the sheet ends up with one extra, unlinked,
never-cleaned-up row, not two unlinked rows. **Certificate renewal and
model-document revision are therefore both non-atomic two-write
operations, but their actual retry-failure behavior differs**: certificate
renewal fails closed on a detected partial-failure state, creating no
further row at all until the inconsistency is manually reconciled;
model-document revision does not detect the partial-failure state, so its
retry proceeds normally and succeeds, but leaves the earlier orphan behind
uncleaned. Version text (`version` field) is opaque and stored with
supplied whitespace preserved verbatim.

**This non-atomicity risk exists now, in the current mock/Google-Sheets
prototype architecture — it is not a risk that "becomes real only after"
a future PostgreSQL migration.** Revision 1 incorrectly implied the risk
was a forward-looking concern for that migration; in fact PostgreSQL
transactions are the *future fix* for a risk that is *already present*
today, and no transaction support has been built to address it yet.

**Batch 4A — Events / offline metadata.** `VehicleEvent`'s exact fields
(`app/domain/vehicle_event.py`) are `event_id` (backend-generated),
`device_event_id` (device-generated, required string), `sequence` (**not**
`sequence_number` — required non-negative int, per-device namespace),
`device_id`, `event_time` (device-supplied, required exactly when
`time_quality` is `TIME_SYNCED`/`TIME_ESTIMATED`), `received_at`
(backend-generated, UTC, at ingestion — cannot be client-supplied,
confirmed by `test_client_supplied_received_at_forbidden`),
`created_offline` (bool, stored exactly as supplied, never inferred),
`time_quality` (`TIME_SYNCED`/`TIME_ESTIMATED`/`TIME_NOT_SYNCED`), plus
`component_id`, `latitude`/`longitude`/`gps_valid`,
`fuel_level_value`/`fuel_level_unit`, `note_th`. Only
`ENGINE_START`/`ENGINE_STOP`/`PTO_ON`/`PTO_OFF` are acceptable via the
public `POST /vehicle-events` create endpoint; `DEVICE_ONLINE`/
`DEVICE_OFFLINE` cannot be created through this endpoint
(`test_device_offline_rejected_by_post`). Duplicate protection/
idempotency: identity is exactly `(device_id, device_event_id)`;
`ingest_device_event` looks this up *first*; on a match it re-runs the
idempotent location-projection/daily-summary side effects on the existing
row and returns it unchanged, never creating a second `event_id`/row
(`test_replay_same_device_and_device_event_id_returns_same_event_no_new_row`,
`test_replay_with_different_payload_still_returns_original_stored_event`).
History ordering (`order_for_history`) sorts the trusted bucket
(`time_quality` SYNCED/ESTIMATED, non-null `event_time`) by `event_time`
descending — **never by `received_at`** — proven by
`test_history_read_order_sorts_trusted_time_events_and_isolates_untrusted_bucket`,
which creates events with `event_time` values in a different order than
their creation order and confirms the API response follows `event_time`.
`received_at` and `event_time` are two independent response fields
(`event_time: datetime | None`, `received_at: datetime`,
`vehicle_event_schemas.py:72,78`), with `received_at` exclusively
backend-set — the mechanism that makes a delayed/offline-uploaded event
show its true `event_time` rather than its ingestion time is proven by
these two facts together; no single test literally narrates a "phone
reconnects after a day offline" scenario combining `created_offline=True`
with a large `received_at`-minus-`event_time` gap (see the verification
report's Row 4 for this precise evidence boundary).

**Batch 4B/6D — Latest-location projection + read API.** The write-side
projector (`VehicleEventService._project_latest_location`) advances the
single `latest_location` row for a vehicle **iff** `gps_valid is True`
and both coordinates are present and `time_quality` is
SYNCED/ESTIMATED and the event's `event_time` is strictly newer than the
currently-stored `gps_time` (an older/out-of-order event is silently
skipped). The read-side (`LocationService`, defined in
`app/domain/location_snapshot.py` — **this file pre-dates Batch 1 and was
modified, not created, to add this read-side class**, Section 4b;
`GET /vehicles/{id}/latest-location`, Batch 6D) is a plain read with no
write side effect. **GPS zero-coordinate handling is directly, positively
tested in the frontend — Revision 1 incorrectly claimed no dedicated test
exists for this.** Every coordinate-presence check across the codebase
(`vehicle_event_service.py`, `location_snapshot.py`,
`VehicleWorkHistoryPage.tsx`, `VehicleLatestLocationCard.tsx`) uses
`is not None`/`!== null` (never a truthy/falsy check), and this is
confirmed by two dedicated frontend tests at this HEAD:
`frontend/src/components/VehicleLatestLocationCard.test.tsx::'displays
both coordinates, including a genuine 0 value (not treated as missing)'`
(stubs `latitude: 0, longitude: 0`, asserts both render as the literal
text "0", not blank) and
`frontend/src/pages/VehicleWorkHistoryPage.test.tsx::'displays numeric
zero coordinates as valid when gps_valid is true, never as missing'`
(stubs `gps_valid: true, latitude: 0, longitude: 0`, asserts the rendered
text "ละติจูด 0 / ลองจิจูด 0"). These are UI-rendering assertions,
appropriately distinct from the backend's own GPS-combination validation
tests (`test_gps_valid_true_with_coordinates_accepted` etc., which test
request validation, not zero-value rendering) — both layers are now
correctly and separately evidenced.

**Batch 4C — Daily summary.** `DailySummary` records
`ENGINE_RUN_DURATION`/`PTO_RUN_DURATION` per vehicle/component/day, with
`DailySummaryDataStatus` of `COMPLETE` or `PARTIAL`. A missing/incomplete
value is represented as `null`/`PARTIAL`, never coerced to `0`.
Reconciliation runs a full rebuild on every trusted
ENGINE_START/STOP/PTO_ON/OFF ingest, skipped for `TIME_NOT_SYNCED` events.
Day-boundary splitting uses `app/domain/common.py`'s
`to_bangkok_date`/`next_bangkok_midnight` (`ZoneInfo("Asia/Bangkok")`) —
the **implemented convention**, but `OPEN_DECISIONS_REGISTER_EN.txt`
decision **A04 still reads `Status: TBD-DEFERRED`** — Asia/Bangkok is a
working placeholder, **not a formally approved/frozen production policy**.

**Batch 5A/5B — Alerts (read + D25 internal lifecycle).** The public API
surface is exactly two read-only `GET` routes. `AlertService`
additionally implements five **internal-only** lifecycle methods matching
D25/A07 exactly: `ensure_condition_alert` (open-identity dedup by
`(vehicle_id, alert_type, source_type, source_id)`; **takes a
caller-supplied `alert_id: str` — never generates one itself**, per its
own docstring, "never generated here — see A01"), `acknowledge_alert`,
`mute_alert`, `reconcile_mute_expiry`, `resolve_condition_alert`. None of
these five methods is wired to any HTTP route or FastAPI dependency
(confirmed by grep across `backend/app/api/` and
`backend/app/dependencies.py` — no match). Public alert mutation is
blocked by **M02**. `RESOLVED` is terminal
(`test_e5_resolve_is_terminal_no_reopen_method_exists`); recurrence after
resolution creates a brand-new alert row via `ensure_condition_alert`'s
zero-open-rows path.

**Note on "no generated alert rows" (corrected, Revision 2):** the
**`MockRepository`'s own seed data contains zero `Alert` rows** (confirmed
directly — `grep -c "Alert(" app/repositories/mock/seed_data.py` = 0), so
the mock environment this task's own test run exercises genuinely starts
empty. This is a narrower, more precise claim than Revision 1's blanket
"reads are currently-always-empty," which incorrectly implied the
*capability* to hold rows doesn't exist: `AlertService`/`Repository` both
have full create/read methods, `GoogleSheetsRepository.get_alert`/
`list_alerts_for_vehicle` read whatever rows actually exist in a live
sheet (which could be non-empty if any internal-only lifecycle call was
ever exercised against it), and D25's internal methods do accept and
persist caller-supplied alert records. **What is actually true, and
remains true after this correction: no code path in this codebase
*automatically* calls `ensure_condition_alert` for any alert category —
see the per-category table in Section 15.**

**Batch 5C/5D — AlertSetting (read + D26 effective GLOBAL policy).**
`AlertSetting` has no HTTP route at all. `get_effective_global_setting`
implements D26/A11's GLOBAL-scope-only fail-closed matching exactly (>1
usable row → `422 ALERT_SETTING_GLOBAL_CONFLICT`).
`should_suppress_device_offline(operational_status)` implements the exact
frozen table (`test_25_device_offline_suppression_table_matches_d26_exactly`).
This is a pure policy-evaluation function, zero writes (D26 §7), **not
itself an alert generator** — nothing in `backend/app/domain` or
`backend/app/api` outside its own tests calls it (scoped grep result, not
a claim about code that might exist elsewhere in a way this task's search
methodology would miss).

**Batch 6A–6E — Read-only UI.** Thai pages consuming the above read APIs
exactly as the backend orders/labels them, with no independent
recalculation. Batch 6E adds a 4-way per-event GPS render — valid/
incomplete-coordinates/explicitly-invalid/no-data.

**Batch 6F — Model-document revision UI (`0efa124`, HEAD).** Extends
`ModelDocumentsPage.tsx` with a revision-creation form, successor-
visibility rendering, a page-wide pending guard blocking a *different*
document's workflow while one revision POST is in flight (test: `blocks
opening a different document while a revision POST is pending...`), a
stale-response guard dropping a revise response after navigation away
(test: `drops a stale revise response instead of overwriting a different
model that was navigated to while it was pending`), and explicit
uncertain-outcome handling for a network rejection / 500-with-envelope /
502-or-503-without-envelope (all three tests under `describe('...server
error classification')`), versus a definite-rejection mapped
validation/conflict error (inputs preserved, no uncertain-outcome refresh
action). The commit touches **four** files, not three (Section 4b):
`ModelDocumentsPage.tsx`, `.test.tsx`, `frontend/e2e/
model-document-revision.spec.ts`, and `frontend/src/lib/labels.ts`.

## 9. LOCAL STARTUP COMMANDS

Unchanged from Phase 1–5:
```
./scripts/run_backend.sh     # http://127.0.0.1:8000
./scripts/run_frontend.sh    # http://127.0.0.1:5173
./scripts/run_dev.sh         # both together
./scripts/run_backend_tests.sh
./scripts/run_frontend_tests.sh
./scripts/run_e2e_tests.sh
```

## 10. BUILD / TYPECHECK / LINT RESULT

Executed fresh in the **original** closure-documentation session (these
commands were NOT re-run for this Revision 2 correction pass, per the
correction task's own instruction not to rerun suites for a documentation-
only fix; the original captured logs are reused byte-for-byte — see the
companion evidence file for full provenance):
- Backend: no separate lint/typecheck tool is configured (pytest only).
- Frontend typecheck (`tsc -b`, part of `npm run build`): exit code 0.
- Frontend production build (`npm run build`): exit code 0.
  `dist/assets/index-*.js  460.44 kB │ gzip: 117.76 kB`, built in ~554ms.
- Frontend lint (`npx oxlint` / `npm run lint`): **exit code 0, 0 errors,
  34 warnings.** (Revision 1 called this "PASSED" without stating the
  warning count in this summary section, which invited misreading as
  "no warnings"; corrected here to state the exact figures. All 34
  warnings are pre-existing categories — `react(set-state-in-effect)`,
  `react(preserve-manual-memoization)`, `react(only-export-components)`.
  **Whether these exact categories were "not newly introduced by Phase
  6" is asserted only in the narrow, provable sense that this
  documentation task introduced no source change and therefore no new
  warning** — this task did not perform a baseline lint diff against a
  pre-Phase-6 commit to independently verify that no Phase-6 commit ever
  introduced a new warning category; no such broader claim is made.)

## 11. TESTS ACTUALLY PERFORMED

All commands below were executed directly, from scratch, in the
**original** closure-documentation session (fresh `pip install -e
".[dev]"`, fresh `npm install`) on the reviewed HEAD
`0efa1243552ba958b497d253dec2bc8f7e0c376f`, and are **reused unchanged**
for this Revision 2 correction pass (no source/test file changed, so no
rerun was performed or is needed — see the companion evidence file for
exact original timestamps and provenance). Full stdout/stderr/exit codes/
timestamps are captured in the delivered evidence file (outside this
repository).

**Backend — pytest (full suite, mock mode):**
```
$ cd backend && source .venv/bin/activate
$ DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development python -m pytest -v
1080 passed, 130 warnings in 53.75s
```

**Frontend — unit/component (Vitest, non-watch):**
```
$ cd frontend && npm test
Test Files  36 passed (36)
     Tests  177 passed (177)
```

**Frontend — typecheck / production build / lint:** see Section 10.

**Focused Playwright e2e — `model-document-revision.spec.ts`, all 5
required viewport projects:**
```
$ cd frontend && npx playwright test e2e/model-document-revision.spec.ts
20 passed (29.0s)
```
(4 tests × 5 viewport projects: smartphone-portrait, smartphone-landscape,
tablet-portrait, tablet-landscape, desktop.)

**Not run in this task (by explicit task scope), either session:** the
full Playwright regression suite (all other `frontend/e2e/*.spec.ts`
files); a live-credentialed Google Sheets integration run (Section 6).

No test was skipped, disabled, hidden, or added. No result above was
claimed without being executed in the original session. Historical
figures cited in this task's own brief (e.g. a pre-6F audit's reported
"backend 1080 / frontend 155," or a corrected-6F "frontend 177 / focused
26 / e2e 20") are **not** reused as this task's own results — every
number in this section is the original session's own fresh execution,
reused honestly with its original provenance in this revision, not
re-executed and not re-labeled as new.

## 12. TEST RESULTS (SUMMARY TABLE)

| Suite | Result |
|---|---|
| Backend pytest (full) | 1080/1080 passed |
| Frontend Vitest (full) | 177/177 passed (36 files) |
| Frontend typecheck (`tsc -b`) | exit 0 |
| Frontend production build | exit 0 |
| Frontend lint (`oxlint`) | exit 0, 0 errors, 34 warnings (pre-existing categories) |
| Focused Playwright — `model-document-revision.spec.ts` (5 viewports) | 20/20 passed |

## 13. SCREEN / UX NOTES

- All Phase 6 pages reuse the frozen `ResponsiveTable`/`Card`/`FormField`
  mobile-first primitives; no new desktop-only layout pattern was
  introduced.
- **README.md / backend/README.md — no change made, by design.** Both
  files were read in full. `README.md`'s "Phase Results" section already
  only names Phase 1/2 explicitly and has not been kept current for Phase
  3, 4, or 5 either. Adding a Phase-6-only pointer would not close that
  pre-existing gap and would be inconsistent with how Phases 3–5 were
  (not) reflected there. `backend/README.md` describes the backend's
  structure/test command, unchanged by Phase 6 (new routes are
  discoverable at runtime via the existing `/docs` OpenAPI endpoint,
  which the README already points to). Both files are therefore left
  untouched. This decision is unchanged by, and out of scope for, this
  Revision 2 correction (the correction task explicitly stated "README
  changes remain unnecessary for this targeted correction; no new
  scope").

## 14. TBD VALUES REMAINING

- **A01** Transaction ID Generation — `TBD-BLOCKING`; Phase 6 continues
  the opaque `PREFIX-NNNN` mock-sequential convention for backend-
  generated IDs, **except `Alert.alert_id`, which is caller-supplied**
  (Section 3).
- **A04** Daily Summary Day Boundary — `TBD-DEFERRED`; Asia/Bangkok is
  implemented, not formally frozen.
- **A05** Device Online/Offline Threshold — `TBD-BLOCKING`; no heartbeat/
  grace/recovery code exists anywhere this task's searches covered
  (Section 15's per-category table).
- **A06** Alert Severity Model — `APPROVED/FROZEN (vocabulary only)`; the
  `alert_type`→severity *mapping* remains undefined — a real, if narrow,
  blocker on any category's alert generation (Section 15).
- **A09** Concurrency/Optimistic Locking — `TBD-BLOCKING`; Google Sheets
  multi-row writes remain non-transactional; `ensure_condition_alert`'s
  `ALERT_OPEN_IDENTITY_CONFLICT` and certificate renewal's corruption
  guard are the two places Phase 6 makes a resulting race condition an
  explicit, fail-honest outcome.
- **B04** Google Drive / File Storage — `TBD-DEFERRED`; `storage_ref`
  remains opaque text only.
- **M02** Exact Permission Matrix — `TBD-BLOCKING`; blocks any public
  Alert mutation endpoint.
- **M07** File Upload Limits/MIME/Malware Scanning — `TBD-BLOCKING`.
  **Correction (Revision 2):** Revision 1 stated M07 is "unaffected" by
  Phase 6 and affects only the pre-existing Phase 3 attachment mechanism.
  That is too narrow: M07 also blocks any **future** production file
  upload for certificates/model documents, should `storage_ref` ever be
  wired to a real upload path — it is not scoped to Phase 3 alone, even
  though no Phase 6 code currently exercises it (B04/M07 remain distinct
  from, and this task does not conflate them with, the working Phase 3
  attachment upload/download mechanism, which M07 also already governs).
- **H02** GPS History — `DEFERRED`.
- **H03** Location Privacy/Access — `TBD-BLOCKING`.

## 15. KNOWN LIMITATIONS

**Per-category alert-generation audit (required; restored in Revision 2,
corrected in Revision 3 — see below).** `docs/project-governance/
OPEN_DECISIONS_REGISTER_EN.txt` lines 152–160, decision **D26/A11**,
contain an explicit list of what D26 does **NOT** define:

> D26 does NOT define: alert_type -> severity mapping, PM due/overdue
> formulas, certificate expiry calculation, lifetime due calculation,
> repair alert generation rules, inactive vehicle calculation, OTA alert
> generation, safety-command alert generation/execution, notification/
> escalation behavior, public Alert mutation RBAC, AlertSetting mutation
> RBAC, AlertSetting mutation API, MODEL/VEHICLE scope precedence,
> auto_reenable_on_online's behavioral semantics, A05's heartbeat/grace/
> recovery policy, A01 alert_id generation, or A09 concurrency/optimistic
> locking. Those all remain separately unresolved.

**Correction (Revision 3):** Revision 2 treated certificate-expiry
generation as blocked by "A06 only" and the inactive-vehicle threshold as
an "informal gap" with no assigned governance ID, recommending one be
assigned. Both were wrong: D26 **explicitly names** "certificate expiry
calculation" and "inactive vehicle calculation" in its own "does NOT
define" list above — these are **already tracked, named, unresolved
items under D26/A11**, not gaps outside the register. Every row below is
now cross-checked against this exact list rather than against an earlier
report's framing.

| # | Category | Automatic generation exists? | Rule/formula/trigger frozen? | Implementation currently allowed? | Governance ID(s) / status / relevant text | Classification |
|---|---|---|---|---|---|---|
| 1 | PM due/overdue | NO — confirmed by grep: `ensure_condition_alert` is referenced only inside `alert_service.py` itself and its own tests; no PM service calls it | NO | **NO** | **E01** PM Status Lifecycle `TBD-BLOCKING`; **E02** PM Warning Windows `SOURCE-DATA-REQUIRED/TBD`; **E03** PM Completion Baseline `TBD-BLOCKING`; **E04** Missing Counter Behavior `TBD-BLOCKING`; **A06** severity mapping undefined; D26 also explicitly lists "PM due/overdue formulas" as not defined | **BLOCKED/DEFERRED** (E01–E04; D26) |
| 2 | Lifetime (`PART_LIFETIME_DUE`) | NO (same grep evidence) | NO | **NO** | **G01** Real Lifetime Rules `UNRESOLVED` (Phase 5); **G02** Lifetime Warning Windows `UNRESOLVED`; A06; D26 also explicitly lists "lifetime due calculation" as not defined | **BLOCKED/DEFERRED** (G01/G02; D26) |
| 3 | Certificate expiry (`CERTIFICATE_EXPIRY`) | NO — the underlying expiry *date calculation* (`_reconcile_expiry`, `ACTIVE`→`EXPIRED`) and the `alert_lead_days` field both already exist and work for the certificate's own status field, but nothing calls `ensure_condition_alert` from them — **the existing lazy `ACTIVE`→`EXPIRED` transition is not, and does not imply, approval of automatic Alert-row generation** | NO | **NO** | **D26 explicitly lists "certificate expiry calculation"** in its own "does NOT define" list (register lines 152–160) — this is a named, tracked, unresolved item, not merely a generic A06 gap; **A06** (severity mapping) and **A01** (`alert_id` generation strategy, also explicitly named in the same D26 list) are additional applicable blockers | **BLOCKED/DEFERRED** (D26; A06; A01) |
| 4 | Repair (`REPAIR_OPEN`) | NO (same grep evidence) | NO | **NO** | **F01** Repair Status Lifecycle `TBD-BLOCKING` — `RepairStatus`'s own source docstring states "PROVISIONAL/CONFIGURABLE placeholder only ... F01 is not approved"; A06; D26 also explicitly lists "repair alert generation rules" as not defined | **BLOCKED/DEFERRED** (F01; D26) |
| 5 | Device offline (`DEVICE_OFFLINE`) | NO | Suppression policy YES (D26/A11 §3), detection threshold NO | **NO** | **A05** Device Online/Offline Threshold `TBD-BLOCKING` — no heartbeat/grace/recovery code found in `backend/app/domain`/`backend/app/api`; D26 defines only the suppression policy for an alert that would exist *if* something generated it, and separately, explicitly lists "A05's heartbeat/grace/recovery policy" in its own "does NOT define" list | **BLOCKED/DEFERRED** (A05; D26) |
| 6 | Inactive vehicle (`INACTIVE_VEHICLE`) | NO | NO | **NO** | **D26 explicitly lists "inactive vehicle calculation"** in its own "does NOT define" list (register lines 152–160) — this is an already-tracked, named, unresolved item under D26/A11, distinct from A05's device-offline heartbeat concept; **not** an ungoverned/unassigned gap | **BLOCKED/DEFERRED** (D26) |
| 7 | Sensor/config (`SENSOR_ERROR`/`CONFIG_SYNC_ERROR`) | NO | N/A | **NO** | No IoT/device/telemetry/config-sync code exists anywhere (`grep` for device-telemetry/config classes returns zero matches); `00_README_EXECUTION_ORDER_EN.txt` assigns "IoT device management, telemetry, online configuration" to **Phase 8**, not started | **OUT OF PHASE 6** (Phase 8 boundary) |
| 8 | OTA (`OTA_FAILURE`) | NO | N/A | **NO** | No OTA code exists anywhere; `00_README_EXECUTION_ORDER_EN.txt` assigns OTA to **Phase 9**, not started; **K01–K03** remain `TBD-BLOCKING`/unresolved; D26 also explicitly lists "OTA alert generation" as not defined | **OUT OF PHASE 6** (Phase 9 boundary; D26) |
| 9 | Safety (`SAFETY_COMMAND`/`SAFETY_FEEDBACK_FAILURE`) | NO | N/A | **NO** | No safety-command code exists anywhere; Phase 9 boundary; **L01–L08** are `SAFETY-BLOCKING` even once Phase 9 starts; D26 also explicitly lists "safety-command alert generation/execution" as not defined | **OUT OF PHASE 6** (Phase 9 boundary, additionally safety-blocked; D26) |

**No item above is classified "MISSING-UNBLOCKED."** Rows 1, 2, 3, 4, and
6 each have a specific, named, unresolved governance decision blocking
them — for row 3 (certificate expiry) and row 6 (inactive vehicle) that
decision is D26/A11 itself, cited directly above, not an absence of
governance. Rows 7–9 are explicitly out of the Phase 6 boundary per the
project's own phase plan. No row is presented as "closest to unblocked"
or otherwise singled out as weaker than the others — every row's
blocker is named and, where D26 applies, quoted directly from the
register.

**Zero generated Alert rows in the mock environment's seed data does not
prove zero real-world due/overdue/offline conditions** — it only proves
no generator exists yet for any category (table above). A future
Dashboard must present "not generated / unavailable" distinctly from a
verified zero, which this phase does not attempt to design or implement.
This codebase's `alert_type` values are illustrative examples drawn from
the baseline document (`PM_DUE`, `PM_OVERDUE`, etc.) — `alert_type` itself
is stored as a plain opaque string on `Alert`/`AlertSetting`, with **no
fixed/enforced vocabulary of allowed values anywhere in the schema or
service layer**; this report's per-category table should not be read as
implying a closed enum exists.

Other known limitations:
- Certificate renewal / model-document revision are non-atomic two-write
  operations with materially different retry-failure behavior (Section 8)
  — certificate renewal fails closed on a detected partial failure;
  model-document revision does not detect it.
- `storage_ref` establishes no binary upload, no provider integration, and
  no working download URL (B04/M07 unresolved) — distinct from the
  separate pre-existing Phase 3 inspection-attachment mechanism, which
  continues to work unchanged (Section 3, Acceptance Row 9, of the
  verification report).
- No public HTTP endpoint exists to acknowledge/mute/resolve an Alert.
- No MODEL/VEHICLE-scoped `AlertSetting` precedence exists.

## 16. RISKS / CONCERNS

- The certificate-renewal / model-document-revision non-atomicity risk is
  present **today**, in the current architecture — not a risk deferred
  until a future PostgreSQL migration. Certificate renewal's corruption
  guard reduces (does not eliminate) its blast radius; model-document
  revision has no equivalent guard yet.
- `A05` remaining `TBD-BLOCKING` means `DEVICE_OFFLINE` alerts cannot be
  generated even once a generator is written, until a heartbeat/threshold
  policy is approved.
- Because no alert generator exists for any category, a naive future
  Dashboard implementation could mistakenly present an empty alert list
  as "everything is fine" rather than "not yet computed."

## 17. ANY CHANGE TO PREVIOUS FROZEN PHASES

**NONE beyond Phase 6's own already-accepted additive extensions to the
`Repository` interface.** This documentation task itself changes zero
source, test, config, or contract files, in either the original session
or this Revision 2 correction.

## 18. CONFIRMATION: THIS TASK MADE NO APPLICATION CHANGE

Confirmed by `git status --short` at the start of both the original task
and this correction task, and by this task's own file list (Section 4a)
containing only the two phase-result documents and one CHANGELOG entry.

## 19. A1 / A2 STATUS

- **A2** (Batch 6F, model-document revision UI): **implemented**, merged
  at `0efa1243552ba958b497d253dec2bc8f7e0c376f`.
- **A1** (this documentation gap): **addressed by this documentation
  candidate** (Revision 3, incorporating two rounds of reviewer
  corrections), on `review/phase6-closure-docs`, **pending reviewer
  acceptance and
  merge** — not yet accepted or merged as of this report.

## 20. PHASE 7 BOUNDARY ASSESSMENT (read-only — not executed)

`docs/claude-prompts/web-api/07_PHASE7_DASHBOARD_SEARCH_REPORTING_EN.txt`
was read in full to assess readiness, per this task's explicit
instruction to assess the boundary without executing it. Given Section 15
above, the single most important boundary fact for Phase 7 is: **there is
currently no alert-generation service of any kind to summarize**, and the
per-category table now makes explicit exactly which categories are
governance-blocked under a named decision (rows 1, 2, 3, 4, 5, 6 — rows 3
and 6 specifically via D26/A11's own "does NOT define" list) versus out
of the Phase 6/current phase-plan boundary entirely (rows 7–9). Phase 7
must not silently treat alert-list emptiness as "0 problems." No Phase 7 code,
route, page, or test was written or executed by this task.

## 21. NEXT PHASE READINESS

**READY**, in the same sense every prior accepted Phase Result Report uses
the word: the accepted Phase 6 implementation is structurally sound, was
fully tested by this task's own fresh execution in the original session
(1080 backend / 177 frontend unit / 20 focused e2e, all passing), and its
known gaps are explicitly disclosed governance items (Section 14/15/16),
not silent defects. **Formal user sign-off on this documentation
candidate is still pending** (Section 19).

---

STOP HERE. Do not begin Phase 7.
