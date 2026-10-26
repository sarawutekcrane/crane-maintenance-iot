# R4 Cross-Phase Regression Contract — R3 / Access Management / Existing PM

**Status:** Owner-approved governance addendum and review gate. It is not a source-code patch and
not a production activation.
**Dates:** Owner contract dated 2026-10-22; this documentation prepared 2026-10-26.
**Project:** CRANE FLEET MAINTENANCE / IoT Web Application + Backend API.
**Repository:** `sarawutekcrane/crane-maintenance-iot`.
**Evidence baseline (read-only):** `feature/r4-pm-master-b1-mock` @
`3023c31728099eacc92bbb152e483759a551221c`.
**Supersession rule:** the Owner's later, explicit R4 decisions control R4 implementation. This
addendum preserves compatible, already accepted R3 and Access Management (AM) behavior. It does
not re-open R4, revive an earlier ban on starting R4, or turn R3 Mock acceptance into production
acceptance.

## 1. Owner decision and source hierarchy

The Owner authorizes incorporating prior-chat agreements that (a) do not contradict current R4
Owner Decisions and (b) reduce regression risk. This document adds **acceptance and regression
obligations** only. It does **not** authorize:
- new source-code changes or privilege expansion;
- PM Master Publish/Assign;
- deployment, TEST/REAL writes or merge;
- deletion of historic data;
- the start of B2 without its own scoped implementation instruction.

Evidence it relies on (all present at the baseline commit):

| Source | What it establishes |
|---|---|
| `docs/project-governance/r3-mock-acceptance-record.md` | R3 Mock accepted with limitations; L10/D8 cancellation of eligible PENDING, never-converted requests (`can_cancel_repair_request`); Mock-only scope; L11 deferred at the R3 checkpoint. |
| `docs/project-governance/access-management-l11-mock-acceptance-record.md` | Later centralized AM + L11 Mock acceptance; source-scoped Finding authority, distinct from PM and manual repair; no production activation. |
| `backend/app/domain/repair_request_service.py` | Cancellation, exact-source duplicate rejection, PM-result provenance and conversion paths. |
| `backend/app/api/v1/repair_requests.py` | Server-side capability checks at request boundaries. |
| `backend/tests/test_r3_f1_repair_request_cancellation.py`, `backend/tests/test_repair_request_duplicate_source_prevention.py` | Existing negative and positive proof for cancellation and exact-source deduplication. |
| `backend/app/domain/pm_service.py`, `backend/tests/test_repair_pm_work_authorization.py` | Existing PM Work Order runtime and its authorization. |
| `docs/phase-results/r4-b1-pm-master-foundation-mock-result.md`, `backend/tests/test_pm_master_b1_mock.py` | The separate, Mock-only R4-B1 Master boundary. |

## 2. Frozen cross-phase behaviors

### XPR-01 — A Repair Request is not a Repair Work Order
- Creating a Repair Request from an authorized report does **not** create a Repair Work Order.
  Conversion is a separate authorized action.
- An R4 PM result or finding may be a `PM_RESULT` defect-source reference only when a real source
  record exists and the approved workflow calls for user-directed reporting.
- No automatic Repair Request creation or cancellation as a side effect of PM Master publish, PM
  result save, close, due or outstanding transitions.
- The `FINDING`, `PM_RESULT` and `MANUAL` source distinctions stay intact. Source equality is never
  inferred from vehicle, symptoms, text or clock time.

### XPR-02 — R3-L10 cancellation compatibility
- Only an existing **PENDING, never-converted** Repair Request can be cancelled, whatever its
  source (Finding, manual report or an approved PM-result source).
- Cancellation is an **authorized human action** by a context holding `can_cancel_repair_request`,
  with a substantive reason. `cancelled_by`, `cancelled_at`, the reason, the source reference and
  all existing record data are retained.
- **No automatic cancellation.** `CONVERTED` and already `CANCELLED` requests cannot be cancelled
  again, and a cancelled request cannot be converted later. An existing Repair Work Order is never
  cancelled or changed as collateral damage.
- Older role-based Mock test fixtures are **not** proof that any real user holds an AM capability;
  enforcement stays server-authoritative.

Code anchors at the baseline: `repair_request_service.py` refuses cancellation of a non-PENDING
request (`REPAIR_REQUEST_NOT_PENDING`) and conversion of a cancelled one
(`REPAIR_REQUEST_CANCELLED`); cancellation requires `CAN_CANCEL_REPAIR_REQUEST`.

### XPR-03 — Exact-source deduplication survives cancellation
- A later Repair Request with the same (`source_type`, `source_id`) for a `FINDING` or `PM_RESULT`
  is refused **whatever the prior request's status**, including `CANCELLED` and `CONVERTED`. The
  existing API error is `REPAIR_REQUEST_SOURCE_ALREADY_REPORTED`.
- Only exact provenance IDs are deduplicated, never similar symptom text. Different source IDs stay
  independent. Manual and source-less reports keep their approved behavior.
- A rejected duplicate must not create an orphan meter/location snapshot, an extra Repair Request
  row, a Work Order or a duplicate audit effect.
- Changing the cancelled-source rule is a **new Owner decision**; it must not change silently
  inside R4.

Code note: `_require_source_not_already_reported` looks up every request with that exact source
and has no status filter, so a `CANCELLED` request also blocks a re-report. Its docstring still
says "PENDING or already CONVERTED"; that wording predates L10 and does not narrow the behavior.

### XPR-04 — Access Management and L11 authority isolation
- L11's `can_manage_finding_repair` is **scoped to Finding sources**. It grants no automatic
  authority over `PM_RESULT`, `MANUAL`, PM Work Orders or the PM Master.
- `can_manage_pm` covers approved PM Work Order actions. It is **not** authority to Publish, Assign
  or review-write the PM Master.
- **VAL-AM stays OPEN and fail-closed** for every R4 Master mutation until a separately authorized
  capability and verified actor rules exist. Root appointment and permission administration do not
  substitute for business-level PM Master authority.
- No new role, workaround, temporary admin bypass, implicit bulk grant, fallback legacy
  authorization or inferred delegation.

### XPR-05 — Legacy PM and historical data preservation
- The R4 Master foundation stays separate from the current PM runtime until a future authorized
  batch integrates it. Existing PM plan/task/revision/Work Order behavior, authorizations,
  inspection, repair, Technician V2, location and meter snapshots stay unchanged.
- A newly published PM Master revision applies only to Work Orders opened after its approved
  activation. Existing OPEN/CLOSED Work Orders keep their exact scope, revision reference, source
  lineage, historical results and Repair Request source links.
- The later Owner-approved E01 PM lifecycle, the Outstanding vs Due distinction, the three
  Performed options and Not Performed reasons, and the ban on finalizing a Work Order with zero
  actual Performed all stay in force. This addendum is not an alternative E01 design.
- `source_sheet` is provenance, not PM Plan identity; verified mapping is used instead. Later
  corrected standards, cancellation/blank-template decisions and spare-part quantities need a new
  source, review and revision, never fabrication.

### XPR-06 — Single/dual IoT readiness without premature activation
- **Confirmed dual-engine cranes:** one physical vehicle with distinct `CARRIER_ENGINE` and
  `CRANE_ENGINE` components and independent meter dimensions, and a separate IoT device per
  component once real installations exist.
- **Confirmed single-engine cranes:** one engine and one device; `PTO` is not another engine.
  An UNKNOWN vehicle mapping stays UNKNOWN and is never auto-assigned.
- Current `vehicle_pm_mapping`: 130 `NOT_SEPARATED_IN_PLAN`, 53 `CARRIER_AND_CRANE`, 52 `UNKNOWN`
  (from an earlier independent read-only review of the connected MAINTENANCE Sheet). These are
  **source classifications, not proof of installed devices**.
- Synthetic Mock data may test one- and two-device scenarios. TEST data needs separately
  authorized, isolated writes (`is_test_data` and `test_batch_id` where required). No REAL writes
  and no fabricated installation metadata.
- IoT device topology never overrides existing PM permission or Repair Request controls.

## 3. Mandatory regression checklist for every future R4 implementation batch

"Established evidence" names tests and records that already exist at the baseline commit; it was
read, **not re-run**, when this document was recorded. "Required at R4 integration" lists what a
future batch must add and run before acceptance.

| ID | Behavior to preserve | Established evidence (existing, not re-run here) | Required at R4 integration |
|---|---|---|---|
| R4-XR-01 | Cancelling a PENDING Finding, Manual or PM_RESULT request needs an authorized actor and a reason; audit and original data are kept | `test_r3_f1_repair_request_cancellation.py`: manual report cancelled with data and audit kept; PM_RESULT request follows the same rules; other roles refused with nothing changed; missing reason refused | Run the suite against any R4 PM-result source and confirm the existing R3 cases are unaffected |
| R4-XR-02 | `CONVERTED` and `CANCELLED` requests cannot be cancelled or converted illegally; Repair and history unchanged | Same suite: converted request cannot be cancelled, conversion idempotent; cancel/convert race leaves no orphan Work Order; cancelled request refused at conversion (`REPAIR_REQUEST_CANCELLED`) | Test every eligible and rejected transition once PM results are integrated |
| R4-XR-03 | A cancelled `PM_RESULT` still blocks a second request from the same exact source | `test_a_pm_result_request_follows_the_same_rules_and_keeps_its_source` (cancel, then retry → `REPAIR_REQUEST_SOURCE_ALREADY_REPORTED`); `test_second_rrq_from_same_pm_result_is_rejected`; `test_second_rrq_from_same_finding_is_rejected` | Cover cancel + retry + direct API attempts for any new R4 path; protection must be in the backend, not only the UI. Add an explicit FINDING cancel-then-retry case (today covered by the status-independent lookup in code, not by a dedicated test) |
| R4-XR-04 | Different `PM_RESULT` IDs with the same symptoms stay independent; MANUAL behavior unaffected | Partial only. `test_different_findings_both_allowed` proves that two different FINDING IDs (with different symptom text) are both accepted; it does not cover `PM_RESULT` IDs or identical symptoms. `test_manual_reports_with_identical_symptom_text_remain_allowed` supports MANUAL behavior only. No existing test proves that different `PM_RESULT` IDs with identical symptom text stay independent | Add an integration test proving that two different `PM_RESULT` source IDs with identical symptom text are both accepted (no text-based dedup); add further negative no-text-dedup cases if a new PM workflow changes source identity |
| R4-XR-05 | A refused duplicate creates no orphan snapshot, Work Order or extra request | Orphan-free rejection: `test_mock_repository_rejected_duplicate_creates_no_orphan_snapshot`; `test_google_sheets_repository_rejected_duplicate_creates_no_orphan_snapshot` (fake Sheets interface). Separately, `test_rrq_to_rpr_conversion_idempotency_unaffected` supports conversion idempotency (no second Repair Work Order) and refusal of a duplicate after conversion; it is not by itself proof of orphan-free rejection | Assert side-effect-free rejection on every new R4 integration path |
| R4-XR-06 | No automatic Repair Request from PM Master publish, due, outstanding or result transitions | R3 acceptance record: partly by code inspection; the R4-B1 Master is not imported by the runtime (`test_b1_17_strict_mock_isolation`) | Add an explicit absence-of-side-effect test for each future R4 action |
| R4-XR-07 | Finding-only L11 authority cannot change PM requests or the PM Master | `access-management-l11-mock-acceptance-record.md` (AM-3); AM security and identity suites; `test_r3_inspection_finding_followup.py`. These establish that `can_manage_finding_repair` is Finding-scoped; they are not yet a complete negative authorization matrix for `PM_RESULT` operations and PM Master writes | Explicit denied-capability matrix for PM Master and PM-result requests, including root and delegate edge cases |
| R4-XR-08 | `can_manage_pm` grants no PM Master publish/assign; every Master write fails closed (VAL-AM) | `test_pm_master_b1_mock.py`: `test_b1_13_*` (root holder with `can_manage_pm` denied), `test_forged_master_publish_*`, `test_b1_fix_03_*` (valid proof still denied) | Keep the denial until an independent Owner security decision and its tests |
| R4-XR-09 | Old PM OPEN/CLOSED Work Orders do not change when the Master is published or revised | `test_pm_master_b1_mock.py`: `test_b1_10_*` (OPEN and CLOSED Work Orders byte-identical across publishes) | Snapshot and compare before/after any integration |
| R4-XR-10 | PM Plan and meter source lineage and one- vs two-engine dimensions stay distinct | `pm_source_preview.py`, `meter.py`; `test_pm_master_b1_mock.py`: `test_r2_01_*`, `test_r2_02_*`, `test_r2_03_*` | Positive and negative single/dual/unknown cases, offline device, device swap, no fabricated readings |
| R4-XR-11 | No regression in inspection, Finding, Repair, Technician V2, PM assignment or permissions | Existing backend suites. Historical result only: 5,074 passed, 1 skipped, as reported by Claude for the R4-B1 correction verification of the reviewed R3 patch before commit `3023c31`. It was not re-run for this documentation, and it was not independently re-run on the pushed commit | Run affected tests and the full backend regression; add frontend/E2E once UI is touched |
| R4-XR-12 | No historical or source deletions and no destructive cleanup | Mandatory Cleanup Review policy (RETAIN / REPLACE / DEFER / UNVERIFIED / REMOVE) | Classify with evidence; any destructive action needs Owner approval first |

## 4. Scope and exit controls

**This action:** acceptance checklist and codebase cross-reference only. No source code, database,
Google Sheet, firmware, API, role, test or production system was modified. No tests were executed
when this document was recorded; every result cited above is historical evidence.

**Before an actual R4 code batch:**
- identify affected paths and, where possible, write the negative cases first;
- require a separate Owner-authorized scope;
- report any conflict with this contract as `BLOCKED/OWNER_DECISION_REQUIRED`;
- never change accepted R3/AM or legacy PM behavior just to satisfy new tests;
- no manual test-data insertion into TEST or REAL without separate approval.

**Exit evidence required for implementation:**
- (a) the test list and real run results;
- (b) the git diff and modified files;
- (c) authentication/authorization denial proof;
- (d) proof of no duplicate or orphan effects;
- (e) immutable old Work Orders;
- (f) the outstanding UNKNOWN gates;
- (g) the cleanup classification and no unauthorized modifications;
- (h) no production claim from Mock results.

## 5. Compatibility decision summary

- **"Do not begin R4 during R3"** was a chronological gate, not a permanent denial. Later
  Owner-specific R4-B1 authorization and accepted Mock checkpoints superseded it; R4-B1 is not
  re-opened or undone.
- **"L11 follows R3"** is superseded by the later completed AM + L11 Mock acceptance. L11 remains
  separate from PM Master authority.
- **"PM authorization details not yet decided"** remains an open Master-write decision, consistent
  with VAL-AM. It is not permission to invent access rights.
- Exact-source duplicate handling, manual PENDING cancellation and protection of PM/Repair history
  remain compatible, binding constraints for R4 integration.
