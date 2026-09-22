# Web/API Phase 6 — Post-Implementation / Closure Verification Report

STATUS: **AUDIT / CLOSURE-DOCUMENTATION TASK.** This report verifies an
**already-implemented and merged** Phase 6 from the outside, on the
reviewed HEAD below. It resolves no open governance decision, changes no
application code/test/config/contract, and does not itself constitute
reviewer acceptance. **This is Revision 3.** Revision 2 corrected a
commit-range error and several other factual issues a reviewer found in
Revision 1 (Section 14). A second round of reviewer findings against
Revision 2 — a false claim that certificate renewal lacks dedicated
`storage_ref` test coverage, an incorrect reading of D26/A11's governance
scope for certificate-expiry and inactive-vehicle alert generation,
several broken cross-document section references, and imprecise
certificate-guard/model-document-orphan phrasing — are corrected in this
Revision 3 (Section 15).

**Reviewed source HEAD:** `0efa1243552ba958b497d253dec2bc8f7e0c376f`
**Reviewed branch:** `review/phase6-closure-docs`
**Whole-Phase-6 commit range:**
`3e54e6035c10dcb59454848d56c0866be504227c..0efa1243552ba958b497d253dec2bc8f7e0c376f`
(32 commits — corrected in Revision 2; Revision 1 used
`770cbc7..0efa124`, which git-exclusively omits `770cbc7` itself, the
Batch 1 commit — see Section 14, item 1).
**Method:** direct reading of current working-tree source, direct reading
of the actual Phase 6 backend/frontend test files (not just their names),
`git diff --name-status`/`git log` against the corrected range, a diff of
that range against `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`,
and (in the original session) a fresh, independent, from-scratch
re-execution of the required automated suites (Section 10) — **not
re-executed for this Revision 3 correction pass, nor for Revision 2**,
per each correction task's own explicit instruction; the original logs
are reused with honest provenance (Section 10).

---

## 1. Requirement Traceability (Phase 6 SCOPE, all batches 1–6F)

| Slice | Implemented | Evidence (file:function) | Automated test evidence | Notes |
|---|---|---|---|---|
| 1. Driver/Operator master + contact + license fields | YES | `app/domain/driver.py` (`Driver`); PATCH partial-update in `driver_service.py::update_driver`, full-replace in `Repository.update_driver` (two distinct layers — Section 3) | `test_driver_phase6_batch1.py` (32 tests) | Master fields updated in place — NOT versioned |
| 1. Assignment start/end history | YES | `driver_service.py` (`assign_driver`, `end_assignment`) | `test_assign_driver_creates_a_new_history_row`, `test_new_primary_assignment_does_not_modify_or_end_an_existing_assignment`, `test_ending_an_already_ended_assignment_is_an_idempotent_no_op` | See Acceptance Row 1 |
| 2A. Certificate foundation | YES | `app/domain/vehicle_certificate.py`, `vehicle_certificate_service.py` | `test_vehicle_certificate_batch2a.py` (28 tests) | |
| 2B. Certificate renewal/history (ACTIVE/REPLACED/EXPIRED) | YES | `renew_certificate` (two-write + corruption guard) | `test_vehicle_certificate_batch2b.py` (37 tests) | See Acceptance Row 2 |
| 3A. Model document foundation | YES | `app/domain/model_document.py`, `model_document_service.py` | `test_model_document_batch3a.py` (27 tests) | New over the whole range (Section 5) |
| 3B. Model document revision/history | YES | `revise_document` (two-write, no corruption guard) | `test_model_document_batch3b.py` (33 tests) | See Acceptance Row 3 |
| 4A. Events/offline metadata (`event_time`/`device_event_id`/`sequence`/`device_id`/`created_offline`/`time_quality`) | YES | `app/domain/vehicle_event.py`, `vehicle_event_service.py` | `test_vehicle_event_batch4a.py` (41 tests) | Exact field is `sequence`, not `sequence_number` |
| 4B. Latest-location projection | YES | `_project_latest_location` (in `vehicle_event_service.py`) | `test_latest_location_projection_batch4b.py` (24 tests) | |
| 4C. Daily summary | YES | `daily_summary_service.py` | `test_daily_summary_batch4c.py` (49 tests) | A04 still `TBD-DEFERRED` |
| 5A. Alert read | YES | `GET /vehicles/{id}/alerts`, `GET /alerts/{id}` | `test_alert_phase6_batch5a.py` (22 tests) | Read-only, confirmed no mutation verb |
| 5B. D25 internal alert lifecycle | YES (internal only) | `alert_service.py` (5 methods; `alert_id` is caller-supplied, not generated) | `test_alert_phase6_batch5b.py` (66 tests) | No HTTP route wired — see Acceptance Row 7 |
| 5C. AlertSetting read | YES (internal only, no route) | `app/domain/alert_setting.py`, `alert_setting_service.py` | `test_alert_setting_phase6_batch5c.py` (21 tests) | No `alert_setting*.py` file exists under `app/api/v1/` |
| 5D. D26 effective GLOBAL settings + DEVICE_OFFLINE suppression | YES | `get_effective_global_setting`, `should_suppress_device_offline` | `test_alert_setting_phase6_batch5d.py` (36 tests) | See Acceptance Row 8 |
| 6A. Work history UI | YES | `frontend/src/pages/VehicleWorkHistoryPage.tsx` | `VehicleWorkHistoryPage.test.tsx` (19 tests) | |
| 6B. Daily summary UI | YES | `VehicleDailySummaryPage.tsx` | `VehicleDailySummaryPage.test.tsx` (13 tests) | |
| 6C. Alerts read UI | YES | `VehicleAlertsPage.tsx` | `VehicleAlertsPage.test.tsx` (17 tests) | |
| 6D. Latest-location API/GPS card | YES | `latest_locations.py`, `VehicleLatestLocationCard.tsx` | `test_latest_location_read_api_batch6d.py` (12 tests) + `VehicleLatestLocationCard.test.tsx` (13 tests) | |
| 6E. Event-time GPS in work history | YES | `VehicleWorkHistoryPage.tsx` (`renderEventGps`) | Covered within `VehicleWorkHistoryPage.test.tsx` | 4-way render: valid/incomplete/invalid/none |
| 6F. Model-document revision UI | YES | `ModelDocumentsPage.tsx` (new over the whole range; further modified by commit `0efa124`) | `ModelDocumentsPage.test.tsx` (26 tests) + `model-document-revision.spec.ts` (4 tests × 5 viewports) | Original session re-run (Section 10); not re-run for this correction |

**Traceability verdict:** every named Phase 6 SCOPE slice (1 through 6F)
is present in the current source tree and backed by at least one
independently-inspected automated test. Backend Phase 6 test total:
**428 test functions** across 13 files (exact count, computed by
`grep -cE "^(async )?def test_"` per file in this task — see the companion result report's Section 15
for the per-file breakdown; Revision 1's "≈366" figure is withdrawn as an
unsupported approximation).

---

## 2. Open-Decision / Guessing Audit

| Decision | Register status (verified by direct read at this HEAD) | Phase 6 behavior | Explicitly approved by Phase 6? | Notes |
|---|---|---|---|---|
| **A01** Transaction ID Generation | `TBD-BLOCKING` | Opaque `PREFIX-NNNN` mock-sequential convention for backend-generated IDs; `Alert.alert_id` is the one exception — caller-supplied, never generated (Section 1) | NO (unchanged) | |
| **A04** Daily Summary Day Boundary | `TBD-DEFERRED` | Asia/Bangkok implemented as working convention | NO — register text unchanged | Implemented ≠ frozen |
| **A05** Device Online/Offline Threshold | `TBD-BLOCKING` | No heartbeat/grace/recovery code found in `backend/app/domain`/`backend/app/api` | NO | Blocks `DEVICE_OFFLINE` generation (companion result report Section 15 row 5) |
| **A06** Alert Severity Model | `APPROVED / FROZEN (vocabulary only)` — D24 | `AlertSeverity` = INFO/WARNING/CRITICAL | YES (vocabulary only) | `alert_type`→severity mapping undefined — applies as a blocker uniformly to every category (companion result report Section 15) |
| **A07** Alert Dedup/Auto-Resolve | `APPROVED / FROZEN (open-alert lifecycle contract only)` — D25 | 5 internal `AlertService` methods matching the register text exactly | YES (internal contract only) | No HTTP mutation endpoint — blocked by M02 |
| **A09** Concurrency/Optimistic Locking | `TBD-BLOCKING` | `ensure_condition_alert` and certificate renewal's corruption guard both fail honestly under a detected race rather than guessing | NO (unchanged) | Sheets multi-row writes are not transactional anywhere in this codebase |
| **A11** Alert Effective-Setting/Suppression | `APPROVED / FROZEN` — D26 | `get_effective_global_setting` + `should_suppress_device_offline` implement exactly the register's 7 numbered points | YES (the effective-setting/suppression contract only) | D26's own text (register lines 152–160) explicitly lists what it does **NOT** define: `alert_type`→severity mapping, PM due/overdue formulas, **certificate expiry calculation**, lifetime due calculation, repair alert generation rules, **inactive vehicle calculation**, OTA alert generation, safety-command generation/execution, notification/escalation, public Alert/AlertSetting mutation RBAC/API, MODEL/VEHICLE scope precedence, `auto_reenable_on_online` semantics, A05's heartbeat/grace/recovery policy, A01 `alert_id` generation, and A09 concurrency — each of these is a **named, tracked, unresolved item under D26/A11 itself**, not an ungoverned gap (companion result report Section 15) |
| **B04** Google Drive/File Storage | `TBD-DEFERRED` | `storage_ref` is opaque text only | NO | See Acceptance Row 9 |
| **E01–E04** PM Status Lifecycle/Warning Windows/Completion Baseline/Missing Counter | All `TBD-BLOCKING`/`SOURCE-DATA-REQUIRED` | No PM alert generation exists | NO | Companion result report Section 15 row 1 |
| **F01** Repair Status Lifecycle | `TBD-BLOCKING` — `RepairStatus`'s own docstring: "PROVISIONAL/CONFIGURABLE placeholder only ... F01 is not approved" | No repair alert generation exists | NO | Companion result report Section 15 row 4 |
| **G01/G02** Real Lifetime Rules / Warning Windows | `UNRESOLVED` (Phase 5) | No lifetime alert generation exists | NO | Companion result report Section 15 row 2 |
| **H02** GPS History | `DEFERRED` | No continuous tracking | NO (unchanged) | |
| **H03** Location Privacy/Access | `TBD-BLOCKING` | No location-specific RBAC exists | NO (unchanged) | |
| **M02** Exact Permission Matrix | `TBD-BLOCKING` | No alert-write permission in `role_permission`; this is *why* D25 has no HTTP route | NO (unchanged) | |
| **M07** File Upload Limits/MIME/Malware Scanning | `TBD-BLOCKING` | Unaffected by any current Phase 6 code path, but also blocks any *future* certificate/model-document upload wiring, not just the pre-existing Phase 3 mechanism (corrected, Section 14 item 5) | NO (unchanged) | |

`OPEN_DECISIONS_REGISTER_EN.txt` diff across the corrected range
(`git diff 3e54e60 0efa124 -- docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`)
shows **only** A06/A07/A11 were added/changed. No other register entry
was silently touched. This documentation task itself made **zero**
changes to the register, in either revision.

---

## 3. Nine Required Acceptance Rows

### Row 1 — Driver history preserved

- **Classification:** CONFIRMED (assignment history) / PRECISION NOTE
  (master fields are NOT versioned)
- **Source evidence:** `backend/app/domain/driver_service.py::update_driver`
  (PATCH partial-update layer) calling `Repository.update_driver`
  (full-replace persistence layer) — **two distinct layers**; `driver_service.py`
  resolves the omit-vs-explicit-null distinction before the repository
  ever sees a value (Section "Correction" below); `assign_driver`/
  `end_assignment` — append-only
- **Exact test file/name:** `backend/tests/test_driver_phase6_batch1.py::test_assign_driver_creates_a_new_history_row`,
  `::test_new_primary_assignment_does_not_modify_or_end_an_existing_assignment`,
  `::test_ending_an_already_ended_assignment_is_an_idempotent_no_op`,
  `::test_seeded_assignment_history_shows_one_ended_and_one_active_period`
- **Execution status:** re-verified present and passing in the original
  session's fresh full-suite pytest run (1080/1080 passed).
- **Limits:** `Driver` master is updated **in place** — no historical
  record of a prior name/phone/license value. Only
  `VehicleDriverAssignment` is append-only/history-preserving.
- **Correction (Revision 2):** Revision 1 stated
  "`DriverService.update_driver`, a full-replace contract distinguishing
  an omitted field from an explicit null." This conflated two layers.
  `DriverService.update_driver` is the **PATCH partial-update** logic
  (resolves omitted-vs-explicit-null using `fields_set`); the underlying
  `Repository.update_driver` (Mock/GoogleSheets implementations) is the
  **full-replace** persistence call, which has no concept of "omitted" at
  all — it always receives final, already-resolved values. The PATCH
  semantics apply only to the *optional* fields (`phone`, `license_no`,
  `license_expiry_date`, `active_status`, `note_th`); `driver_name_th` is
  always required and not subject to this distinction. The service's own
  docstring explicitly disclaims this as "not an established project-wide
  rule."

### Row 2 — Certificate history preserved

- **Classification:** CONFIRMED, narrow scope
- **Source evidence:** `vehicle_certificate_service.py::renew_certificate`
  (lines ~167–327; two-write, plus a corruption guard at lines ~269–293)
- **Exact test file/name:** `backend/tests/test_vehicle_certificate_batch2b.py::test_renew_active_certificate_succeeds_creates_distinct_new_active_row`,
  `::test_renew_marks_old_certificate_replaced_and_linked_history_preserved`,
  `::test_renew_already_replaced_certificate_returns_existing_successor_not_a_third_row`,
  `::test_renew_corrupt_replaced_linkage_fails_loudly`,
  `::test_renewal_rejected_when_more_than_one_active_in_group_adds_no_row`,
  `::test_google_sheets_renewal_preserves_old_row_and_appends_new_row`
- **Execution status:** re-verified present and passing (original
  full-suite run).
- **Limits, corrected (Revision 2):** Renewal is a **non-atomic two-write
  operation** with **two distinct safeguards**, not one:
  1. *Completed-renewal retry* (source already `REPLACED`): idempotent —
     returns the existing successor, or `422
     VEHICLE_CERTIFICATE_ACTIVE_STATE_CONFLICT` if the linkage is
     inconsistent.
  2. *Corruption guard* (source still `ACTIVE`, but its type-group already
     has more than one `ACTIVE` row — the signature of an earlier
     partial-failure orphan): **rejects the renewal with `422
     VEHICLE_CERTIFICATE_ACTIVE_STATE_CONFLICT` and creates NO new row**,
     directly proven by `test_renewal_rejected_when_more_than_one_active_in_group_adds_no_row`
     (pre-seeds a two-ACTIVE-row corrupt state, asserts the 422, asserts
     the certificate count is unchanged after the call).

  **Revision 1 incorrectly stated that a retry "creates another row" for
  certificate renewal and that this caveat "applies identically" to
  model-document revision.** That is wrong for certificates specifically:
  the corruption guard means a retry against an already-partially-failed
  renewal is rejected, not compounded. The underlying orphan row from the
  *original* partial failure is still not automatically fixed — manual
  reconciliation is still required — but no *additional* orphan is ever
  created by a subsequent call. This is a materially different, and
  materially safer, retry-failure behavior than model-document revision's
  (Row 3). Expiry reconciliation (`ACTIVE`→`EXPIRED`) remains lazy/
  read-triggered, not a scheduler.
  **This non-atomicity risk is present now**, in the current
  Google-Sheets-backed prototype — it is not a risk that only begins
  after a future PostgreSQL migration; that migration is the *prospective
  fix*, not the origin, of this risk.

### Row 3 — Document revisions preserved

- **Classification:** CONFIRMED, narrow scope — **retry-failure behavior
  is materially weaker than certificate renewal's (Row 2); this is a
  correction from Revision 1, which treated the two as identical**
- **Source evidence:** `model_document_service.py::revise_document`
  (lines ~80–257; two-write, **no corruption guard** — the only pre-write
  check is whether the source already has a `replaced_by_document_id`
  link)
- **Exact test file/name:** `backend/tests/test_model_document_batch3b.py::test_revise_creates_distinct_new_row_and_links_source`,
  `::test_revise_inherits_model_id_and_document_type`,
  `::test_missing_successor_link_target_is_422_conflict`,
  `::test_successor_wrong_model_id_is_422_conflict`,
  `::test_successor_wrong_document_type_is_422_conflict`,
  `::test_google_sheets_finalize_revision_preserves_unrelated_fields`,
  `::test_mock_and_google_sheets_revision_parity`
- **Execution status:** re-verified present and passing (original
  full-suite run); the Batch 6F UI's own revision-creation flow re-verified
  by the focused Playwright spec (20/20 passed, original session).
- **Limits:** If WRITE 1 (new row) succeeds and WRITE 2 (link the source)
  fails, the source's link remains unset. **A subsequent retry does NOT
  detect this orphan state** (unlike certificate renewal) and runs the
  normal path again, **creating ANOTHER new candidate row** — the
  service's own docstring narrates this exact sequence in detail
  ("creates ANOTHER new candidate row ... The original orphan is not
  deleted, relinked, or otherwise touched"). **To be precise:** if WRITE 2
  succeeds on this retry, that second candidate row becomes the properly-
  linked successor — it is not itself an orphan. What is left behind is
  the **original** unlinked row from the earlier failed attempt,
  permanently, alongside the now-successful revision. **No dedicated
  automated test exercises this original-row-left-behind scenario** — it
  is a disclosed absence of a guard (provable by the guard's absence in
  the code), not a positively-regression-tested guarantee the way
  certificate renewal's corruption guard is. `version` text is opaque,
  supplied whitespace preserved verbatim.

### Row 4 — Delayed offline event shows actual event time

- **Classification:** CONFIRMED (structurally) — PRECISION NOTE on test
  directness (unchanged from Revision 1's finding, restated for
  completeness)
- **Source evidence:** `vehicle_event_service.py::order_for_history`
  (sorts the trusted bucket by `event_time` descending, never
  `received_at`); `app/api/v1/vehicle_event_schemas.py` exposes
  `event_time`/`received_at` as two independent fields, and `received_at`
  cannot be client-supplied
- **Exact test file/name:** `backend/tests/test_vehicle_event_batch4a.py::test_history_read_order_sorts_trusted_time_events_and_isolates_untrusted_bucket`,
  `::test_client_supplied_received_at_forbidden`
- **Execution status:** re-verified present and passing (original
  full-suite run).
- **Limits:** No single test combines `created_offline=True` with a large
  `received_at`-minus-`event_time` gap to narrate a "reconnects after a
  day offline" scenario end-to-end — satisfied structurally by the
  ordering + field-independence tests, not by one dedicated integration
  test with that exact narrative.

### Row 5 — Duplicate event ingestion is idempotent

- **Classification:** CONFIRMED
- **Source evidence:** `vehicle_event_service.py::ingest_device_event` —
  looks up `(device_id, device_event_id)` first; on a match, re-runs
  idempotent side effects on the existing row and returns it unchanged
- **Exact test file/name:** `backend/tests/test_vehicle_event_batch4a.py::test_replay_same_device_and_device_event_id_returns_same_event_no_new_row`,
  `::test_replay_with_different_payload_still_returns_original_stored_event`
- **Execution status:** re-verified present and passing (original
  full-suite run).
- **Limits:** Identity is exactly `(device_id, device_event_id)`; cross-
  device `sequence` values are never compared
  (`test_order_for_history_never_compares_sequence_across_devices`).

### Row 6 — Invalid GPS is not shown as valid

- **Classification:** CONFIRMED — **both directions now evidenced;
  Revision 1's claimed test-coverage gap for the zero-coordinate case is
  withdrawn as false**
- **Source evidence:** backend combination rules
  (`vehicle_event_service.py` ~lines 247–260: `gps_valid=True` requires
  non-null coordinates, `gps_valid=None` requires null coordinates,
  `gps_valid=False` permits either as raw evidence never implying
  validity); every coordinate-presence check project-wide uses
  `is not None`/`!== null`, never truthy/falsy
- **Exact test file/name — invalid-GPS-rejection direction (backend
  request validation):** `backend/tests/test_vehicle_event_batch4a.py::test_gps_valid_true_with_coordinates_accepted`,
  `::test_gps_valid_true_missing_latitude_rejected`,
  `::test_gps_valid_false_with_coordinates_accepted_as_raw_evidence`,
  `::test_gps_valid_null_with_coordinates_rejected`,
  `::test_gps_fields_round_trip`
- **Exact test file/name — genuine-zero-is-valid direction (frontend
  UI rendering, corrected in Revision 2):**
  `frontend/src/components/VehicleLatestLocationCard.test.tsx::'displays
  both coordinates, including a genuine 0 value (not treated as
  missing)'` (stubs `latitude: 0, longitude: 0` in the latest-location
  API response, asserts both render as literal "0" text, not blank) and
  `frontend/src/pages/VehicleWorkHistoryPage.test.tsx::'displays numeric
  zero coordinates as valid when gps_valid is true, never as missing'`
  (stubs `gps_valid: true, latitude: 0, longitude: 0` on a work-history
  event, asserts the rendered text "ละติจูด 0 / ลองจิจูด 0"). Both were
  read directly in this correction task and confirmed to exist and to
  assert exactly what their names claim, at this HEAD.
- **Execution status:** all of the above were included in the original
  session's fresh full-suite/vitest runs (1080 backend / 177 frontend
  unit, both passing); not individually re-isolated, but covered by the
  full-suite pass.
- **Correction (Revision 2):** Revision 1 stated "no dedicated test
  asserts latitude/longitude exactly 0.0 is accepted/rendered as valid"
  — **this was false.** The two frontend tests above directly assert
  exactly that, for both the latest-location card and the work-history
  page. The backend's own GPS-combination-validation tests (previous
  paragraph) are correctly a *separate* concern (request-shape
  validation, not zero-value UI rendering) and were not mistakenly
  substituted for this UI evidence in this revision.
- **Limits:** None remaining beyond the ordinary scope of unit/component
  tests (they assert rendered text against a stubbed `fetch` response,
  not a full backend-to-frontend integration).

### Row 7 — Alert mute differs from resolve

- **Classification:** CONFIRMED
- **Source evidence:** `alert_service.py::mute_alert` (non-terminal,
  reversible via `reconcile_mute_expiry`) vs `resolve_condition_alert`
  (terminal, no reopen path)
- **Exact test file/name:** `backend/tests/test_alert_phase6_batch5b.py::test_c1_active_to_muted_succeeds`,
  `::test_c5_mute_rejects_from_resolved`,
  `::test_d3_reconcile_transitions_to_active_when_never_acknowledged`,
  `::test_d4_reconcile_transitions_to_acknowledged_when_previously_acknowledged`,
  `::test_e1_resolve_from_active_succeeds`,
  `::test_e4_resolve_idempotent_preserves_original_resolved_at`,
  `::test_e5_resolve_is_terminal_no_reopen_method_exists`,
  `::test_a5_creates_new_row_when_only_resolved_row_exists_for_identity`
- **Execution status:** re-verified present and passing (original
  full-suite run).
- **Limits:** D25's internal service contract only — no public HTTP
  endpoint exists to mute or resolve an alert; both transitions are
  exercised only by direct `AlertService` method calls in tests. Public
  alert mutation remains blocked by M02.

### Row 8 — Offline alert suppression follows rule (**narrow, policy-only scope — required explicit statement**)

- **Classification:** CONFIRMED, **narrowly scoped to policy evaluation
  only — does NOT mean DEVICE_OFFLINE alerts are ever generated or
  suppressed in a running system**
- **Source evidence:** `alert_setting_service.py::should_suppress_device_offline`
  — pure function implementing the exact D26 §3 table
- **Exact test file/name:** `backend/tests/test_alert_setting_phase6_batch5d.py::test_25_device_offline_suppression_table_matches_d26_exactly`
- **Execution status:** re-verified present and passing (original
  full-suite run).
- **Explicit narrow-scope statement:** performs zero writes (D26 §7) and
  is not called by any `DEVICE_OFFLINE`-detection/generation code path,
  because no such code path exists anywhere this task's searches covered
  (Section 15 of the companion result report, row 5). A05 remains
  `TBD-BLOCKING`. "Suppression follows the rule" is true only in the
  sense "the rule, if ever invoked by a future generator, is implemented
  correctly" — not evidence of any working end-to-end suppression
  behavior today.

### Row 9 — External file storage reference works (**narrow, storage_ref-only scope — required explicit statement, with corrected/completed test citations**)

- **Classification:** CONFIRMED as opaque metadata storage only — does
  NOT mean a working upload/download mechanism exists
- **Source evidence:** `vehicle_certificate.py`/`model_document.py`
  (`storage_ref: str | None`, explicit "no file-upload mechanism"
  docstrings)
- **Exact test file/name — corrected/completed in Revision 2 (Revision 1
  claimed no dedicated test existed beyond generic round-trip coverage;
  the following dedicated tests were found and read directly at this
  HEAD):**
  - `backend/tests/test_vehicle_certificate_batch2a.py::test_storage_ref_is_an_opaque_passthrough_including_numeric_looking_values`
    — posts `storage_ref` values `"attachments/cert-001.pdf"`, `"0012345"`,
    `"https://example.invalid/x"` and asserts each round-trips byte-exact,
    including the numeric-looking one (never coerced to a number).
  - `backend/tests/test_model_document_batch3a.py::test_storage_ref_is_an_opaque_passthrough_including_numeric_looking_values`
    (same pattern for model documents) and
    `::test_google_sheets_storage_ref_numeric_looking_value_survives_round_trip`
    (same, against the fake-Sheets-client path).
  - `backend/tests/test_model_document_batch3b.py::test_storage_ref_omitted_null_never_inherited_but_preserves_exact_text_when_supplied`
    — creates a source document with `storage_ref="attachments/old.pdf"`,
    revises it **without** supplying `storage_ref`, and asserts the new
    row's `storage_ref` is `None` (**not inherited**); a second source/
    revision pair supplies `storage_ref="attachments/new.pdf"` on the
    revise call and asserts it is preserved exactly.
  - `backend/tests/test_vehicle_certificate_batch2b.py::test_renew_omitted_fields_stay_null_never_auto_copied`
    (lines ~254–276) — **corrected in Revision 3: Revision 2 claimed
    certificate renewal has "no equivalent dedicated test" for
    `storage_ref` non-inheritance; this was false, and is withdrawn.**
    This test creates a source certificate with `document_no`,
    `issue_date`, `expiry_date`, `storage_ref="attachments/old.pdf"`, and
    `note_th` all set to non-null values, calls
    `POST /certificates/{id}/renew` with an **empty** request body
    (`json={}`), and asserts on the renewed row: `body["document_no"] is
    None`, `body["issue_date"] is None`, `body["expiry_date"] is None`,
    **`body["storage_ref"] is None`**, and `body["note_th"] is None`. Its
    own docstring states its purpose directly: *"document_no/issue_date/
    expiry_date/storage_ref/note_th must NEVER be copied from the source
    certificate when omitted — they stay null."* The test exercises five
    fields together rather than `storage_ref` alone (its name does not
    mention `storage_ref` specifically), but its body does assert
    `storage_ref`'s non-inheritance explicitly, and this assertion is
    just as much genuine coverage as a same-purpose test with a narrower
    name would be. This test is recorded `PASSED` in the original
    session's preserved verbose pytest log (line 1001:
    `tests/test_vehicle_certificate_batch2b.py::test_renew_omitted_fields_stay_null_never_auto_copied
    PASSED`). **What this test does NOT exercise:** the numeric-looking-
    value-survives-round-trip case for certificates specifically (that
    exact scenario is proven only for model documents, by
    `test_google_sheets_storage_ref_numeric_looking_value_survives_round_trip`
    above) — this narrower, genuinely-absent case is distinguished from
    the omitted-field-non-inheritance case, which certificates and model
    documents both have dedicated coverage for.
- **Execution status:** all of the above were included in the original
  session's fresh full-suite pytest run (1080/1080 passed).
- **Explicit narrow-scope statement:** `storage_ref` is purely opaque
  metadata — free text, no format validation, no upload endpoint, no
  download endpoint, no binary handling, no provider integration (B04
  `TBD-DEFERRED`, M07 `TBD-BLOCKING` — and M07 is not scoped to Phase 3
  alone; it would also govern any future certificate/model-document
  upload path, Section 2). It "works" only in the sense the string
  round-trips unchanged, and — for model-document revision specifically —
  is never silently inherited across a revision unless explicitly
  re-supplied. **This must not be confused with the separate, pre-existing
  Phase 3 inspection-attachment mechanism**
  (`POST /api/v1/attachments`, `GET /api/v1/attachments/{id}/file`),
  which **is** a real, working, independently-tested upload/download
  path, confirmed present and unmodified by Phase 6, but which Phase 6's
  certificates/model-documents are **not** wired to.

---

## 4. Exit Gate Reassessment

**Exit gate text:** *"Operational supporting data is stable for
Dashboard."*

- Driver, certificate, model-document, event, daily-summary, and
  latest-location data are all backend-authoritative, read via stable
  `/api/v1` routes, and independently proven append-only/history-
  preserving or lazily-reconciled exactly where they claim to be
  (Rows 1–6), **with the corrected understanding that certificate
  renewal and model-document revision have materially different
  non-atomicity risk profiles (Rows 2/3)**.
- Alert data (Rows 7–8) is stable as a read-only surface whose contents
  genuinely start empty in this task's own mock test environment
  (Section 2/companion result report Section 8), but whose underlying
  data model, lifecycle contract, and effective-setting policy are all
  real and tested. No generator populates it for any category
  (companion result report Section 15's 9-row table).
- `storage_ref` (Row 9) is stable opaque text, not a file-storage
  guarantee.

**Conclusion: the exit gate is met for what Phase 6 actually built** —
the operational supporting *data model and read APIs* are stable — with
the explicit caveat that "stable" does not mean "complete," and that two
of the nine acceptance rows (2 and 3) are stable in **different, now-
precisely-distinguished ways**.

## 5. Gap Classification

**A. MUST FIX BEFORE PHASE 6 ACCEPTANCE:** none found. Every
implementation behavior described above matches what its own tests prove
(after this revision's corrections); no undisclosed defect, no silently-
resolved governance decision, no fabricated business rule was found.
**Correction (Revision 3):** Revision 2 singled out certificate-expiry
generation and the inactive-vehicle threshold as having "the thinnest
governance cover," on the premise that no named decision blocked them
beyond a generic A06 gap, or that no governance ID existed for them at
all. That premise was wrong (Section 2/companion result report Section
15): D26/A11's own register text explicitly lists **both** "certificate
expiry calculation" and "inactive vehicle calculation" among the things
it does **not** define — both are already-tracked, named, unresolved
items under D26, exactly like every other row. Neither is weaker or
"closer to unblocked" than PM/lifetime/repair; the distinction Revision 2
drew between them is withdrawn.

**B. DEFERRED / BLOCKED (exact governance ID / status / reason):**
- A01 `TBD-BLOCKING` (also blocks certificate-expiry `alert_id`
  generation specifically, per D26's own "does NOT define" list), A04
  `TBD-DEFERRED`, A05 `TBD-BLOCKING` (blocks `DEVICE_OFFLINE` generation),
  A06 `APPROVED/FROZEN (vocabulary only)` (blocks correct severity
  assignment for any generated alert), A09 `TBD-BLOCKING`, B04
  `TBD-DEFERRED`, E01–E04 `TBD-BLOCKING`/`SOURCE-DATA-REQUIRED` (blocks PM
  alert generation), F01 `TBD-BLOCKING` (blocks repair alert generation),
  G01/G02 `UNRESOLVED` (blocks lifetime alert generation), H02
  `DEFERRED`, H03 `TBD-BLOCKING`, M02 `TBD-BLOCKING` (blocks public alert
  mutation), M07 `TBD-BLOCKING` (blocks any future upload wiring for
  `storage_ref`, not only Phase 3's existing mechanism).
- **D26/A11** (`APPROVED/FROZEN` for the effective-setting/suppression
  contract only): its own "does NOT define" list additionally and
  explicitly blocks **certificate expiry calculation** and **inactive
  vehicle calculation** (both moved here from an earlier, incorrect
  "informal gap"/no-ID characterization — Section 2), and **MODEL/VEHICLE
  `AlertSetting` scope precedence** (moved here from Category C below,
  per the reviewer's correction: D26 states this "remains UNRESOLVED — no
  MODEL or VEHICLE scoped setting may be given permanent precedence
  semantics until a later explicit decision is approved," which is a
  decision dependency on D26/A11 itself, not an assigned future-phase
  boundary).

**C. LATER-PHASE ITEMS (exact phase boundary):**
- Sensor/config error generation (`SENSOR_ERROR`/`CONFIG_SYNC_ERROR`) —
  Phase 8 boundary (`00_README_EXECUTION_ORDER_EN.txt`: "IoT device
  management, telemetry, online configuration").
- OTA failure generation — Phase 9 boundary (also named in D26's "does
  NOT define" list).
- Safety-command/feedback generation — Phase 9 boundary, additionally
  `SAFETY-BLOCKING` (L01–L08) even once Phase 9 starts (also named in
  D26's "does NOT define" list).
- Dashboard/search/reporting itself is Phase 7 scope (not started by this
  task — companion result report Section 20, read-only boundary
  assessment).

**A2 recorded:** implemented at `0efa1243552ba958b497d253dec2bc8f7e0c376f`.

**A1 recorded:** addressed by this documentation candidate (Revision 3),
on branch `review/phase6-closure-docs` — **pending reviewer acceptance
and merge; not yet accepted or merged.**

**NO UNBLOCKED PHASE 6 IMPLEMENTATION GAP FOUND.** Every category in the
companion result report's Section 15 table is either blocked by a named,
cited governance decision (Category B above) or explicitly out of the
Phase 6/current phase-plan boundary (Category C above); none is presented
as weaker, closer to unblocked, or otherwise singled out for different
treatment.

## 6. Closure Recommendation

**ACCEPTABLE WITH DOCUMENTED DEFERRED/BLOCKED ITEMS**

**Rationale, stated precisely (corrected, Revision 3 — Revision 2's
"every Phase 6 SCOPE slice is implemented and tested" was too broad and
is withdrawn):** Phase 6's SCOPE names two kinds of capability, and this
verdict rests on both being individually, correctly classified rather
than treated as one undifferentiated whole:
- **Implemented and verified capabilities** — driver/assignment records,
  certificate/model-document lifecycle and revision mechanics, event
  ingestion/idempotency/ordering, GPS latest-location and per-event
  projection, daily summary reconciliation, the public Alert read API, internal AlertSetting read service,
  and D25's internal lifecycle contract, and D26's effective-setting/
  suppression *policy evaluation* — all of these are present in the
  current source tree and independently backed by a passing automated
  test (Section 1's traceability table; Section 10's fresh original-
  session execution).
- **Explicitly blocked/deferred capabilities** — automatic Alert
  *generation* for every named category (PM, lifetime, certificate
  expiry, repair, device offline, inactive vehicle, sensor/config, OTA,
  safety), public Alert mutation, and MODEL/VEHICLE `AlertSetting`
  precedence — none of these exist in the current source tree, and each
  is individually classified in Section 5/companion result report
  Section 15 against a specific, named, cited governance decision (D26's
  own "does NOT define" list, E01–E04, F01, G01/G02, A05, A06, M02) or an
  explicit later-phase boundary (Phase 7/8/9).
- **No unblocked gap was found**, supported by this evidence: every
  absent capability traces to a named blocker or boundary (Section 5);
  none was found missing without one.

This revision corrects Revision 1's commit-range error, its false
GPS-zero test-gap claim, its conflated certificate/model-document
retry-risk claim, its "stub" mischaracterization of
`GoogleSheetsRepository`, and its missing per-category alert-generation
table; Revision 2 then introduced its own errors (an inaccurate "A06
only"/"no governance ID" reading of the certificate-expiry and
inactive-vehicle rows, several broken cross-references, an overstated
"implemented and tested" summary, and a storage_ref test-coverage claim
that was itself false for certificates), corrected here in Revision 3
(Section 15). None of these three revisions' corrections has changed the
underlying closure verdict — **ACCEPTABLE WITH DOCUMENTED
DEFERRED/BLOCKED ITEMS** has held throughout — only the evidence and
reasoning supporting *why* it holds.

**Phase Result Report STATUS: PASS.** This status applies to the implemented,
verified Phase 6 capabilities described above. It does not mean every capability
named in the original scope is implemented: automatic alert generation and the
other Category B/C items remain explicitly blocked/deferred or assigned to later
phases. **This verification report's closure verdict is ACCEPTABLE WITH DOCUMENTED
DEFERRED/BLOCKED ITEMS.** No unblocked Phase 6 implementation gap was found within
the reviewed scope. Neither status asserts production readiness or authorizes
Phase 7. Formal reviewer/user sign-off and merge of this documentation candidate
remain pending (Section 12).

---

## 7. Manual / Native-Thai UI Review

**Not performed in this task**, either revision.

## 8. Cross-Browser / Full Regression Coverage

**Not performed in this task, by explicit task scope**, either revision.
Only `model-document-revision.spec.ts` was run (20/20 passed, 5
Chromium-emulated viewport projects, original session).

---

## 9. Closure Matrix — Rows/Sections Cross-Index

| Required item | Location in this report |
|---|---|
| Reviewed HEAD/branch/range/method | Header, above |
| 9 acceptance rows | Section 3 |
| Exit-gate reassessment | Section 4 |
| A/B/C gap classification | Section 5 |
| A1/A2 status | Section 5 (end) |
| Closure recommendation | Section 6 |
| Manual UI review disclosure | Section 7 |
| Cross-browser/regression disclosure | Section 8 |
| Google Sheets I/O evidence levels (a/b/c) | Companion result report Section 6 |
| Per-category alert-generation table | Companion result report Section 15 |
| Correction checklist (Revision 2) | Section 14 |
| Correction checklist (Revision 3) | Section 15 |

---

## 10. Automated Verification (original session; not re-run for Revision 2 or Revision 3)

Full commands, environment, stdout/stderr, and exit codes are captured in
the delivered evidence file, outside this repository, with their
**original** timestamps and provenance preserved byte-for-byte — not
regenerated for either correction pass, per each correction task's
explicit instruction not to rerun suites for a documentation-only fix.
Summary:

| Suite | Result |
|---|---|
| Backend pytest (full, mock mode) | 1080/1080 passed |
| Frontend Vitest (full, non-watch) | 177/177 passed (36 files) |
| Frontend typecheck (`tsc -b`) | exit 0 |
| Frontend production build | exit 0 |
| Frontend lint (`oxlint`) | exit 0, 0 errors, 34 pre-existing-category warnings |
| Focused Playwright `model-document-revision.spec.ts` (5 viewports) | 20/20 passed |

No test was skipped, disabled, or hidden. No number above is reused from
any prior audit's report — every figure originates from the original
closure session's own execution (not this correction session, which
performed no test execution).

## 11. Provenance / Non-Contamination Confirmation

- `git diff 3e54e60 0efa124 -- docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
  shows only the A06/A07/A11 additions.
- This documentation task's own `git status --short` was empty at the
  start of both the original session and this correction session; its
  own changed-file list (companion result report Section 4a) contains
  only the two phase-result documents and the CHANGELOG entry.
- Phase 7 was not started.

## 12. Sign-Off Status

Formal user sign-off on this documentation candidate (Revision 3) is
**pending**. **READY** (companion result report Section 21) is a
technical-closure statement only and is **not** permission to begin
Phase 7.

---

## 13. Live vs. Fake-Client Google Sheets Evidence (new in Revision 2)

See the companion result report's Section 6 for the full three-level
distinction (implemented adapter I/O / fake-client automated tests / live
credentialed validation). Summary for this verification report's own
record: **level (a)** (real adapter code calling actual `gspread` via
`GoogleSheetsClient`) exists for every Phase 6 domain, confirmed by direct
reading of `create_model_document`, `get_alert`, `list_alerts_for_vehicle`,
and equivalent driver/certificate/summary methods. **Level (b)** (fake-
client engine tests) is what the original session's fresh pytest run
actually exercised — `test_google_sheets_real_io.py` and
`test_google_sheets_repository_completion.py`, both confirmed by their own
module docstrings to run against an in-memory `FakeWorksheet`/
`FakeSpreadsheet`, never real network I/O. **Level (c)** (live credentialed
Sheets validation) was **not performed** by this task or, as far as this
task's searches found, by any prior Phase 6 work — no test in this
codebase is gated on real `GOOGLE_APPLICATION_CREDENTIALS`/
`GOOGLE_SHEET_ID` values.

## 14. Correction Checklist (Revision 2)

Itemized against the reviewer's numbered findings, each with exact
source/test citations (full detail is in the sections referenced):

1. **Commit range** — corrected to `3e54e60..0efa124` (32 commits,
   includes Batch 1) throughout both reports and the CHANGELOG; file
   inventory recomputed via `git diff --name-status` on the corrected
   range (companion result report Section 4b). `ModelDocumentsPage.tsx`/
   test are new-over-the-whole-range, then further modified by Batch 6F;
   `location_snapshot.py` is modified, not new; previously-omitted
   modified files (`backend/pyproject.toml`, `google_sheets/client.py`,
   four pre-existing test files, `NavBar.tsx`) now listed; blanket
   "additive"/"unchanged" claims about old tests removed in favor of the
   actual diff stats.
2. **GPS-zero test gap** — false claim withdrawn; both dedicated frontend
   tests cited and read directly (Row 6 above).
3. **Certificate vs. model-document failure behavior** — corrected;
   certificate renewal's corruption guard (fails closed, no third row)
   distinguished from model-document revision's undetected-orphan risk
   (Rows 2/3 above); "risk only after PostgreSQL migration" framing
   removed — the risk is present now.
4. **Google Sheets implementation accuracy** — "controlled-error stub"
   claim replaced with the three-level (a)/(b)/(c) evidence distinction
   (companion result report Section 6, this report Section 13).
5. **Alert-generation assessment** — the missing per-category table is
   now present (companion result report Section 15); "always empty"
   claims narrowed to the mock seed data specifically; M07 corrected to
   cover future certificate/model-document uploads, not only Phase 3.
6. **storage_ref evidence** — exact test names cited and read directly;
   model-document revision's non-inheritance-when-omitted behavior
   distinguished from certificate renewal's own equivalent, which was
   **incorrectly** described here in Revision 2 as untested. **This
   sub-claim was itself wrong and is corrected in Revision 3** — see
   Section 15, item 1, and the current Row 9 above, which now cites
   `test_renew_omitted_fields_stay_null_never_auto_copied` directly.
7. **Source/contract precision** — driver PATCH (service layer) vs.
   full-replace (repository layer) distinguished (Row 1 above);
   `LocationService`'s file path (`location_snapshot.py`) confirmed cited
   at first use; Batch 6F's 4-file (not 3-file) diff stats corrected,
   including `labels.ts`; `Alert.alert_id`'s caller-supplied nature
   (not backend-generated) now stated explicitly; sweeping "exists
   nowhere" claims rescoped to what this task's actual searches covered.
8. **Cross-references/counts/warnings** — every `Section N` reference in
   both reports recomputed against each document's actual final heading
   numbering (as of Revision 2, this document had 14 sections, not 12;
   the companion result report's Screen/UX Notes is correctly Section 13,
   referenced accordingly); exact backend test-function count (428)
   computed and substituted for the prior "≈366" approximation; lint
   result restated as "exit 0, 0 errors, 34 warnings" rather than a bare
   "clean"/"PASSED" framing that invited misreading. **Two of Revision
   2's own cross-references were themselves broken and are fixed in
   Revision 3 — see Section 15, item 3.**

---

## 15. Correction Checklist (Revision 3)

A second round of reviewer findings against Revision 2, each verified
directly against source/tests/the register before editing:

1. **False certificate `storage_ref` test-coverage gap — withdrawn.**
   `backend/tests/test_vehicle_certificate_batch2b.py::test_renew_omitted_fields_stay_null_never_auto_copied`
   (lines ~254–276) was read directly at this HEAD: it creates a source
   certificate with `storage_ref="attachments/old.pdf"` (plus four other
   non-null fields), renews it with an empty request body, and asserts
   `body["storage_ref"] is None` on the renewed row — genuine, passing
   (original session log, line 1001) coverage of certificate `storage_ref`
   non-inheritance, exercised alongside four other omitted fields rather
   than in a `storage_ref`-named test. Revision 2's claim that certificate
   renewal has "no equivalent dedicated test" for this is withdrawn.
   Fixed in: Row 9 (Section 3) and Section 14, item 6.

2. **D26/A11's actual "does NOT define" scope used, replacing an invented
   informal-gap reading.** `docs/project-governance/
   OPEN_DECISIONS_REGISTER_EN.txt` lines 152–160 were read directly:
   D26 explicitly lists "certificate expiry calculation" and "inactive
   vehicle calculation" — among others — as things it does NOT define,
   meaning both are already-tracked, named, unresolved items under
   D26/A11, not an "A06-only" blocker (certificate) or an "informal,
   no-assigned-ID" gap warranting a new governance ID (inactive vehicle).
   Fixed in: companion result report Section 15 (the whole nine-row table
   rebuilt with an "implementation currently allowed?" column and D26
   citations added to every applicable row); this report's Section 2
   (A11 table row) and Section 5 (Category A's "thinnest governance
   cover" framing removed; MODEL/VEHICLE `AlertSetting` precedence moved
   from Category C to Category B, since D26 states it "remains
   UNRESOLVED ... until a later explicit decision is approved" — a
   decision dependency, not an assigned phase boundary); Section 6
   (Category-A/B distinction restated without singling out any row as
   weaker than the others).

3. **Broken cross-document/cross-section references fixed.** Two
   concrete breaks were found and corrected:
   - Companion result report Section 4 cited "Section 15 of the
     verification report" for a per-file test-count breakdown that was
     never actually written anywhere. Fixed by inlining the 13-file
     breakdown directly in the result report's own Section 4, removing
     the dangling reference.
   - Companion result report Section 15 (Known Limitations) cited
     "Section 16 of the verification report" for the pre-existing Phase 3
     attachment mechanism; this verification report has no Section 16 —
     that content actually lives in this report's Section 3, Acceptance
     Row 9. Fixed by correcting the reference to "Section 3, Acceptance
     Row 9."
   - `CHANGELOG.md`'s Phase 6 entry attributed the "per-category
     alert-generation table" to `web-phase-06-verification.md`; the table
     is in `web-phase-06-result.md`'s Section 15. Fixed by moving that
     attribution to the correct document.
   No other broken reference was found by re-checking every `Section N`
   mention in both documents against each document's actual final
   heading list at the time of this fix.

4. **Certificate-guard/model-document-orphan phrasing made conditional
   and precise.** Two imprecisions were corrected:
   - The certificate corruption guard's claim ("does NOT silently create
     a third row after a partial failure") is now explicitly scoped to
     its actual triggering condition — a **subsequent** renewal attempt
     against a certificate type-group already left in the specific
     two-`ACTIVE`-rows state by an earlier partial failure — rather than
     read as a claim that no partial failure of any kind can ever have an
     unexpected consequence. It is restated explicitly as not an
     atomicity or automatic-orphan-recovery guarantee.
   - Model-document revision's retry-then-success scenario is now
     described precisely: the retry's own second candidate row, if its
     WRITE 2 succeeds, becomes the properly-linked successor and is
     **not** itself an orphan. What remains is the **original** unlinked
     row from the earlier failed attempt — one leftover orphan, not two.
     Fixed in: companion result report Section 8 (Batch 2A/2B and 3A/3B
     implementation-summary paragraphs) and this report's Row 3
     (Section 3).

No test/build/lint/e2e suite was re-run to produce this checklist —
every fact above was established by reading source/test/governance files
and by git plumbing commands only (Section 10 above still reflects the
original session's own, unchanged, byte-for-byte-reused execution
evidence).

---

END OF VERIFICATION REPORT.
