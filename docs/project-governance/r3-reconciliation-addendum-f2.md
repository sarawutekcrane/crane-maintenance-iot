# R3 Reconciliation Addendum (R3-F2)

Status: **R3 MOCK IMPLEMENTATION — OWNER REVIEW PENDING. NOT R3 FINAL ACCEPTANCE. NOT
PRODUCTION-READY.** Prepared on 2026-10-20 on `feature/r3-daily-inspection-finding-followup`,
baseline HEAD `4ac4b4b02146dbf04f94f85a982821034245f1a5`, with the R3 implementation present as
uncommitted working-tree changes.

## 0. How this addendum relates to the R3-B0 documents
- The accepted R3-B0 documents are historical evidence of what was approved at R3-B0. They are
  **not modified** by this addendum; their text stays exactly as accepted:
  - `r3-implementation-contract.md` — SHA-256 `c021097c6323b1f8e24ab84583bfad8a1e20067b615a4b201735e68e48d8c96d`
  - `r3-supersession-and-decision-register.md` — SHA-256 `5495483b8bf030c3fb931ad424dfa509cffc1bb21128152089074ec3313a4fc2`
- Where this addendum and the B0 text disagree, **this addendum records the later Owner decision
  and governs**; the B0 clause stays readable as history. Supersession entries continue the
  register's numbering (X19 onward).
- `OPEN_DECISIONS_REGISTER_EN.txt` and every other historical document stay unchanged.
- Content classes are kept distinct, as in B0: **Owner decision** (a later explicit Owner
  instruction, cited by name), **implemented mechanism** (built under the R3 Master
  Implementation authorization or a later correction authorization; not a new business rule),
  **limitation** (L-n), **proposal** (not approved). Evidence is cited only where it was
  verified in this repository.
- "Mock-implemented" below means: implemented in the mock repository and verified by the cited
  tests. It never means production-complete. In Google Sheets mode every R3 storage operation,
  and the Repair Request cancellation, answers 501 `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE`.

## 1. Later Owner decisions recorded here
| ID | Owner decision (source) | Summary |
|---|---|---|
| OD-1 | R3 Master Implementation, B1–B10 (Owner authorization, 2026-10-18/19) | Implement and test B1–B10 on mock following the B0 documents; R3-B0 final acceptance approved. |
| OD-L8 | "R3 Final Correction Round — L8 + L11 + registryPending" | L8 approved: V2 assign / withdraw on an R3 Finding round needs both `can_manage_repair` and `can_manage_finding_repair`; non-R3 V2 unchanged. |
| OD-L11a | Same round | L11 deferred: no delegate role in R3; the Maintenance Department Manager performs Finding management. |
| OD-L9 | "Owner-approved L9 and L10 final corrections" | PRIMARY must remain assigned during repair (rules in §3). |
| OD-L10 | Same round | Manager-controlled duplicate cancellation of PENDING Repair Requests (rules in §4). |
| OD-D9 | "R3-F1 — Final L10 correction", Phase Strategy A | Complete R3 Mock first; Access Management and L11 afterwards as a separate shared-platform workstream; no temporary delegate role. |
| OD-D8 | Same instruction | D8-A: narrow `can_cancel_repair_request` held only by MAINTENANCE_MANAGER and ADMIN. D8-B: cancellation is Mock-only; Sheets answers 501. |

## 2. L8 — V2 assignment authority on R3 Finding rounds
**Previous text (B0):** contract §8 row "V2 assign / withdraw — `can_manage_repair` (existing,
unchanged; see L8)"; register §5 "the V2 assign/withdraw authorization is unchanged (L8)";
register §6.1 L8 "unresolved".
**Owner decision:** OD-L8.
**What changed and why:** for an R3 Finding round only, V2 assign and V2 withdraw require BOTH
`can_manage_repair` and `can_manage_finding_repair`, so a holder of `can_manage_repair` alone
(MAINTENANCE, SUPERVISOR) can no longer change the team of a Finding round, matching the
manager-only intent of R3-04 / O-3.
**Implementation (verified):**
- `backend/app/domain/technician_assignment.py` — `require_r3_round_authority`, called by
  `TechnicianAssignmentService.assign` and `.withdraw` after the server reads the job and before
  replay detection, scope checks and any assignment read or write.
- The round is identified only by the server-stored `Repair.finding_id` (TS-3); nothing the
  client sends affects it. Without a caller context the check refuses (fails closed).
- The two V2 write routes (`backend/app/api/v1/technician_assignment_routes.py`) are the only
  callers; they pass the caller context. They are the only writers of V2 assignment rows.
- Frontend: `TechnicianAssignmentV2Panel.tsx` (prop `r3FindingRound`) hides the controls from
  users without the Finding authority; the backend stays authoritative.

**Non-R3 V2 behaviour:** unchanged — authorization, PRIMARY / MEMBER semantics, assignment-set
semantics; no V1 endpoint or legacy fallback enabled.
**Evidence (backend, `tests/test_r3_inspection_finding_followup.py`):**
`test_r3_l8_assign_and_withdraw_on_an_r3_round_need_both_capabilities`,
`test_r3_l8_a_replayed_request_id_is_still_refused_without_the_finding_authority`,
`test_r3_l8_service_fails_closed_without_a_caller_context_on_an_r3_round_only`,
`test_r3_l8_non_r3_orders_keep_the_accepted_v2_authorization`,
`test_r3_l8_the_manager_assigning_never_makes_the_manager_the_completing_lead`;
frontend `TechnicianAssignmentV2Panel.r3.test.tsx`.
**Status:** Mock-implemented and tested. **Production:** not supported (no production login;
Sheets R3 storage 501).

Supersession entry: **X19** — contract §8 V2 row and register §5 bullet "V2 assign/withdraw
authorization is unchanged (L8)" → governed by OD-L8 for R3 Finding rounds; unchanged for every
other job.

## 3. L9 — the PRIMARY technician must remain assigned during repair
**Previous text (B0):** register §6.1 L9 (a worked round whose PRIMARY cannot complete — set
withdrawn → NONE, AMBIGUOUS, unavailable — stays OPEN indefinitely; "unresolved").
**Owner decision:** OD-L9. Rules:
1. A Work Order may be opened and await its first technician assignment.
2. No repair work may begin on an R3 Finding round without a VALID current V2 team, which always
   has exactly one PRIMARY.
3. Once assigned, an active R3 round never loses its PRIMARY through a withdrawal.
4. PRIMARY A → B is one atomic replacement of the full assignment set; B may be an existing
   MEMBER or a new technician; a failed replacement leaves A's set current and writes nothing.
5. Only the current authenticated V2 PRIMARY submits completion; old set ids and the former lead
   are refused.
6. Earlier sets, the actor and the time of every change stay in history.
7. No proxy completion, forced closure or cancellation after work began.

**What changed and why:** the B0 "stuck round" can no longer be reached through a withdrawal,
and work cannot be recorded before a lead exists. The existing V2 append-only set model is
reused: a replacement is an ordinary V2 assign with the exact `expected_current`; no editable
PRIMARY field or competing assignment model was introduced.
**Implementation (verified):**
- `technician_assignment.py` `withdraw`: on an OPEN R3 round →
  409 `TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED_ON_R3_ROUND`, nothing written (after the L8
  authority check, so an unauthorized caller still receives 403).
- `backend/app/domain/repair_service.py` `require_round_work_allowed` — the single gate before an
  action, a part (`add_action`, `add_part`) or a repair evidence upload
  (`inspection_service.py` attachment upload): round not frozen (T3 / TS-6) and, on an R3 round,
  a VALID V2 team; otherwise 409 `REPAIR_LEAD_NOT_ASSIGNED` (or
  `TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS`).
- Completion: the existing `require_current_primary` (TS-13) — 403
  `REPAIR_COMPLETION_LEAD_ONLY`, 409 `REPAIR_ASSIGNMENT_STALE`.
- Frontend: the withdraw control is hidden on R3 rounds with an explanation; `R3RepairRoundPanel`
  shows "assign a team first" when there is no lead.

**Evidence:** `test_r3_l9_no_repair_work_is_recorded_before_a_lead_is_assigned`,
`test_r3_l9_the_lead_is_replaced_atomically_and_only_the_new_lead_completes` (existing member and
new technician), `test_r3_l9_a_failed_replacement_keeps_the_original_lead_and_every_row` (stale,
unknown technician, duplicate assignee),
`test_r3_l9_a_worked_round_can_never_lose_its_lead_so_completion_stays_possible`,
`test_r3_l9_non_r3_orders_keep_withdrawal_and_recording_without_assignment`; E2E `@mutation`
"L9 + L10: the lead is replaced, never withdrawn …".
**Mock guarantee vs production:** the mock append of a replacement set is single-process and
atomic. This is **not** production atomicity: Google Sheets multi-row writes and cross-process
races remain R11 restrictions (L3); Sheets R3 storage answers 501.
**Remaining limits (recorded, not expanded):**
- Material requests are **not** treated as repair-start evidence: "repair work" for this gate is
  an action, a part or a REPAIR_EVIDENCE attachment — the same set the TS-7 cancellation gate
  uses. Treating material requests as work would need a separate Owner decision.
- Two V2 sets recorded at the same instant make the team AMBIGUOUS; work is then refused until
  the Manager assigns a replacement.
- Non-R3 Work Orders keep withdrawal and recording without a V2 team (accepted behaviour).

**Status:** L9 resolved for Mock Implementation. **Production:** not supported.
Supersession entry: **X20** — register §6.1 L9 → governed by OD-L9; contract §8 row "Record
action / part / evidence" gains, for R3 rounds, the VALID-team precondition.

## 4. L10 — Manager-controlled cancellation of duplicate Repair Requests
**Previous text (B0):** register §6.1 L10 (a Finding-provenance request whose Finding has ENDED
stays PENDING permanently; "any rejection state belongs to R5"); contract §9 E-2 "A pending
request whose Finding has ENDED stays unconverted (L10)".
**Owner decisions:** OD-L10 and OD-D8.
**Rules as implemented:**
- Duplicate assessment is the Manager's decision: no automatic matching, no text similarity,
  no automatic cancellation (also not when a Finding becomes ENDED).
- Eligible: a Repair Request that exists, is PENDING, was never converted and is not linked to any
  Work Order (an interrupted conversion counts as converted) — **whatever its source**: R3
  Finding, an ordinary / manual report, or a PM result.
- Authority: `can_cancel_repair_request`, held only by MAINTENANCE_MANAGER and ADMIN, checked on
  the route and again in the service.
- A non-empty reason is mandatory; an optional duplicate reference to an existing Work Order or
  another Repair Request (never itself) is validated.
- Audit: status `CANCELLED`, `cancelled_by_user_id`, server `cancelled_at`, `cancel_reason_th`,
  `duplicate_of_repair_id` / `duplicate_of_repair_request_id`; every original field is kept; no
  hard delete.
- A CANCELLED request is never converted (409 `REPAIR_REQUEST_CANCELLED`); it leaves the
  actionable PENDING queue and stays in the detail view and the reporter's history.
- Existing Work Order cancellation rules (W5, TS-7) and the referenced Work Order are unchanged.
- Sheets mode: cancellation answers 501 (D8-B); no live schema or metadata envelope was added.

**Implementation (verified):** `backend/app/domain/authz.py` (`CAN_CANCEL_REPAIR_REQUEST`),
`repair_request.py` (status and audit fields, domain-only), `repair_request_service.py`
(`cancel`, `convert` refusal), `api/v1/repair_requests.py` (`POST
/repair-requests/{id}/cancellation`), `repositories/base.py` (default 501),
`repositories/mock/repository.py` (`cancel_repair_request`; the cancelled-request re-check inside
Work Order creation and inside the converted-mark write); frontend `RepairRequestDetailPage.tsx`,
`MyWorkPage.tsx` label.
**Evidence:** `tests/test_r3_f1_repair_request_cancellation.py` (all 17 cases: capability holders,
manual report with audit, PM result, every other role refused, Manager and ADMIN allowed, missing
reason / invalid reference, reference to another request, converted request, cancellation racing
a conversion) and in `tests/test_r3_inspection_finding_followup.py`:
`test_r3_l10_the_manager_cancels_a_duplicate_pending_request_with_its_audit_kept`,
`test_r3_l10_only_the_finding_authority_cancels`,
`test_r3_l10_a_converted_or_conversion_linked_request_cannot_be_cancelled`,
`test_r3_l10_an_ended_finding_never_cancels_its_pending_request_automatically`,
`test_r3_l10_requests_without_r3_finding_provenance_keep_the_accepted_flow`,
`test_r3_l10_repair_request_whose_finding_ended_cannot_be_converted_and_stays_pending`;
frontend `RepairRequestDetailPage.r3.test.tsx`; E2E `@mutation` "L9 + L10 …".
**Known constraint (unchanged, recorded):** the accepted exact-source uniqueness rule (Decision
B) still counts a CANCELLED request: a second Repair Request from the same Finding or PM result
is refused with 422 `REPAIR_REQUEST_SOURCE_ALREADY_REPORTED`. Changing that would need an Owner
decision.
**Mock guarantee vs production:** re-check and write happen with no `await` in between
(single-process); a cancellation landing during a conversion makes the conversion refuse and no
orphan Work Order is created (tested). Not production atomicity (L3, R11).
**Status:** L10 resolved for Mock Implementation. **Production:** not supported (Sheets 501).
Supersession entries: **X21** — register §6.1 L10 and contract §9 E-2 last bullet → governed by
OD-L10 / OD-D8 (the request still cannot be converted; it can now be cancelled by the Manager).
**X22** — register §6.1 L10 "any rejection state belongs to R5" → for Repair Requests, CANCELLED
is decided by OD-L10 / OD-D8; every other rejection or lifecycle state stays with R5.

## 5. L11 — Finding delegation: DEFERRED (not implemented, not waived)
**Previous text (B0):** contract §8 "Finding delegate (representation UNRESOLVED, L11)", the
"intended ✓ (L11)" cells, register §6.1 L11, contract §18 T-17.
**Owner decisions:** OD-L11a and OD-D9.
**Status:** **DEFERRED — Owner approved for the initial Manager-only R3 scope.** L11 is not
implemented in R3 and is not waived or cancelled. It will be delivered with centralized Access
Management after R3 Mock. No temporary delegate role and no temporary permission store may be
introduced.
**Effect on the workflow today:** the Owner rule O-3 that an explicitly authorized delegate may
perform Finding actions is not yet available. When the Maintenance Department Manager is absent,
only ADMIN can open, cancel or close an R3 round, assign its team, convert a Finding-provenance
request or terminate a Finding. The "intended ✓ (L11)" cells of contract §8 and scenario T-17
are deferred with L11.
**Future Access Management requirements (Owner-approved design concept, future work only —
nothing below exists in the codebase):**
1. Reuse the existing Employee Master (`personnel_master`) wherever verified.
2. One permission-management screen.
3. Department selector.
4. Position filter.
5. Employee selector offering both "all employees in the department" and individual employees.
6. Permission checkboxes.
7. Review and confirmation before saving.
8. Audit of every permission change.
9. The Maintenance Manager as the primary business permission administrator across departments.
10. Delegable Operation Manager authority over drivers across the whole Operation department.
11. Delegation never removes the Maintenance Manager's authority.
12. Permission changes are scoped, revocable and enforced on the server.
13. No unauthorized self-escalation.

The Access Management architecture, persistence, authentication and UI are **not implemented**.
Supersession entry: **X23** — register §6.1 L11 "R3-B3 gate", contract §17 R3-B3 row (L11) and
contract §18 T-17 → re-gated to the future Access Management workstream (OD-D9).

## 6. Decision status D1–D9 (from the read-only Access Management audit)
| ID | Subject | Status |
|---|---|---|
| D1 | Whether `can_manage_finding_repair` alone may authorize R3-round actions (changes the B0 "in addition to" combination) | **Pending — proposal only.** The B0 combination stays binding. |
| D2 | Old role table vs new grants precedence | Pending — proposal only |
| D3 | Explicit individual deny semantics | Pending — proposal only |
| D4 | Department transfer and new-employee grant handling | Pending — proposal only |
| D5 | Who may record department movements (`can_move_personnel_department` has zero holders, R2f-g) | Pending — proposal only |
| D6 | Delegation chains | Pending — proposal only |
| D7 | Position vocabulary normalization | Pending — proposal only |
| D8 | L10 authority and Sheets policy | **Owner-approved (OD-D8): D8-A and D8-B** |
| D9 | Phase strategy | **Owner-approved (OD-D9): Option A** |

## 7. Implemented mechanisms and codes added after B0 (documentation of fact, not new rules)
- TS-1, TS-2, TS-3, TS-4, TS-5, TS-6, TS-7, TS-8, TS-9, TS-10, TS-11, TS-12, TS-13 and TS-14 were
  implemented on mock under OD-1. TS-2 is in effect: MAINTENANCE_MANAGER holds
  `can_manage_repair`, `can_close_repair` and `can_manage_finding_repair`; this supersedes the
  contract §8 sentence "MAINTENANCE_MANAGER holds neither" as a statement of current grants
  (**X24**, history kept).
- TS-11 precisely: the equipment→model reference is read effective-dated (the latest reference
  whose `effective_from` is on or before the Bangkok date). In the mock it is seed data only:
  no route or service writes references, so "append-only" is a storage design statement, not a
  tested write path. Real equipment-model data is source data (UNVERIFIED).
- New capability (OD-D8): `can_cancel_repair_request`.
- Error codes introduced by the L8 / L9 / L10 corrections:
  `TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED_ON_R3_ROUND`, `REPAIR_REQUEST_CANCELLED`,
  `REPAIR_REQUEST_NOT_PENDING`, `REPAIR_REQUEST_CANCEL_REASON_REQUIRED`,
  `REPAIR_REQUEST_DUPLICATE_REFERENCE_NOT_FOUND`; `REPAIR_LEAD_NOT_ASSIGNED` is reused for the
  L9 work gate.

## 8. Verified project limitations
- **Mock implementation vs production readiness:** all R3 evidence is mock evidence.
- **Authentication:** no production login is integrated. Outside development mode a request has
  no user and no roles and is refused (M01 / R11). Capabilities derive only from a provisional
  role table; the `role_permission` sheet is not read (M02 TBD-BLOCKING).
- **Google Sheets:** R3 storage and Repair Request cancellation answer 501; Access Management has
  no storage at all.
- **TEST–REAL isolation** is not proven for any new R3 function; no TEST or REAL data was read or
  written (L4, L6).
- **Atomicity:** mock guards are single-process; Sheets multi-row atomicity and cross-process
  races are R11 (L3).
- **Department membership and provisioning:** department membership comes only from
  `personnel_department_history`, whose write capability has zero holders, so no employee has a
  derived department today; `department_master` is not yet a live tab; the `position` column is
  unvalidated free text; account provisioning is R11.
- **Known test instability — UNVERIFIED:** during R3-F1 verification the Playwright test
  `e2e/pm-repair.spec.ts` "Repair: report a MANUAL repair, append an action and a part, then
  close it" failed once in the tablet-portrait project (the free-text part input was detached
  from the DOM and the fill timed out). It did not reproduce in 35 focused repeats (15 in
  tablet-portrait, 20 across all viewports) and the next full E2E run passed (697 passed, 0
  failed, 12 skipped). Classified as **UNVERIFIED intermittent test instability**: not a
  confirmed product defect and not a proven non-issue. No source change was made for it.

## 9. R3 Mock acceptance traceability
Evidence cited is the last verified run on the current working tree (R3-F1 verification,
2026-10-20; no source or test file changed since): backend pytest 4979 passed / 0 failed / 0
skipped; Vitest 999 passed / 0 failed; `tsc -b`, production build and oxlint clean (30
pre-existing warnings); Playwright run 1: 696 passed / 1 failed (§8) / 12 skipped, run 2: 697
passed / 0 failed / 12 skipped; R3 `@mutation` E2E 4 passed. The 12 skips are the three
desktop-only real-submission tests in the four other viewports (one inspection per asset per
Bangkok day).

| Requirement | Implementation (verified) | Test evidence (verified) | Status | Remaining limits | Production gap |
|---|---|---|---|---|---|
| Four results, remark rule, optional photo, legacy NA (R3-15, R3-16) | `domain/checklist.py`, `domain/r3_inspection.py` `validate_answers`; `ChecklistItemCard.tsx` | `test_r3_abnormal_results_need_a_remark_photo_optional`, `test_r3_legacy_na_unshown_and_missing_items_are_refused`, `test_r3_b1_legacy_na_inspection_stays_readable`; `ChecklistItemCard.test.tsx` | Mock-implemented | — | Sheets 501 |
| Model checklist, `item_key`, daily / 7-day due logic (R3-02, R3-03, O-4) | `r3_inspection.py` `choose_assignment`, `due_items`; mock seed | `test_r3_due_first_inspection_then_day2_day8_and_idle_without_backfill`, `test_r3_missing_checklist_and_asset_override_and_ambiguity`, `test_r3_new_revision_keeps_item_identity_by_item_key_not_title`, `test_r3_not_installed_counts_as_the_last_weekly_result` | Mock-implemented | Real checklist content and model mappings are source data (UNVERIFIED) | Live data, Sheets |
| One inspection per asset per Bangkok day; request-id idempotency (R3-20, R3-21) | `inspection_service.py` `submit_inspection`; mock `submit_r3_inspection` | `test_r3_one_per_bangkok_day_and_idempotent_replay`, `test_r3_request_id_is_required_and_recording_needs_the_capability` | Mock-implemented | Single-process guard (L3) | R11 atomicity |
| Finding OPEN / ENDED episodes, E1–E4, N1, R1 | `r3_inspection.py` `plan_findings`; `inspection_service.py` `terminate_finding` | `test_r3_days_1_to_3_one_finding_day4_pass_ends_day20_new_finding`, `test_r3_not_installed_after_abnormal_keeps_the_finding_open`, `test_r3_manual_termination_needs_authority_and_a_reason`, `test_r3_pass_while_a_round_is_open_never_cancels_or_ends` | Mock-implemented | — | Sheets 501 |
| F-001 → completion → F-002; completion and closure separate (Q2, TS-4) | `repair_service.py` `submit_completion`, `close_repair` | `test_r3_lead_completion_ends_f001_and_a_later_fail_opens_f002_while_rpr001_is_open`, `test_r3_close_needs_finding_authority_and_the_lead_completion`; E2E `@mutation` F-001 scenario | Mock-implemented | — | Sheets 501 |
| Lead-only completion, stale-set refusal (Q2, TS-13) | `technician_assignment.py` `require_current_primary` | `test_r3_completion_is_lead_only_idempotent_and_refuses_stale_sets`, `test_r3_completion_without_a_lead_is_refused` | Mock-implemented | — | Production login |
| Frozen round (T3, TS-6) | `repair_service.py` `require_round_work_allowed` | `test_r3_round_is_frozen_after_completion_and_closed_orders_refuse_work` | Mock-implemented | — | Sheets 501 |
| Cancellation before work only (O-2, Q4, TS-7) | `repair_service.py` `cancel_repair` | `test_r3_cancel_before_work_then_pass_ends_the_finding`, `test_r3_cancellation_is_refused_once_work_exists`; E2E `@mutation` cancel scenario | Mock-implemented | L2 (unrecorded physical work) | Sheets 501 |
| Finding authority and guarded entry points (O-3, T1, T2, TS-1..TS-3, TS-5) | `authz.py`; `repairs.py`; `repair_request_service.py` `convert` | `test_r3_one_active_round_per_finding_and_manager_only_opening`, `test_r3_repair_request_conversion_and_inspection_result_bypasses_are_guarded` | Mock-implemented | L1; L11 deferred | Production RBAC |
| L8 | §2 | §2 | Mock-implemented | — | Production login, Sheets |
| L9 | §3 | §3 | Mock-implemented | Material requests not gated; AMBIGUOUS sets | R11 atomicity, Sheets |
| L10 | §4 | §4 | Mock-implemented | Exact-source uniqueness counts CANCELLED | Sheets 501 |
| L11 | — | — | **DEFERRED** (OD-L11a, OD-D9) | Delegate unavailable | Access Management workstream |
| Follow-up queue, labels, reports, five viewports (R3-11, TS-14) | `FindingFollowupPage.tsx`, `FindingDetailPage.tsx`, `R3RepairRoundPanel.tsx`; 7E2 report reads ENDED | `test_r3_followup_lists_open_findings_by_group_only`, `test_r3_b1_readers_cancelled_orders_and_ended_findings`; `FindingDetailPage.test.tsx`, `R3RepairRoundPanel.test.tsx`; E2E `r3-inspection-finding.spec.ts`, `inspection.spec.ts`, `photo-attachment-responsive.spec.ts` | Mock-implemented | §8 test instability (UNVERIFIED) | — |
| Fail-closed Sheets mode | `repositories/base.py` defaults | `test_r3_google_sheets_mode_fails_closed_for_r3_storage` | Verified (fail-closed) | — | Sheets implementation absent |

**R3 Final Acceptance is not declared by this addendum.**

## 10. Supersession index (continues register §4)
| # | Source (unchanged) | Governing replacement |
|---|---|---|
| X19 | Contract §8 V2 row; register §5 "V2 assign/withdraw authorization is unchanged (L8)" | OD-L8, §2 (R3 rounds only) |
| X20 | Register §6.1 L9; contract §8 "Record action / part / evidence" row | OD-L9, §3 |
| X21 | Register §6.1 L10; contract §9 E-2 last bullet | OD-L10 / OD-D8, §4 |
| X22 | Register §6.1 L10 "any rejection state belongs to R5" | OD-L10 / OD-D8 for CANCELLED only; other states stay R5 |
| X23 | Register §6.1 L11 gate; contract §17 R3-B3 (L11); contract §18 T-17 | OD-L11a / OD-D9, §5 (Access Management workstream) |
| X24 | Contract §8 "MAINTENANCE_MANAGER holds neither" (statement of grants at B0) | TS-2 in effect, §7 |
| X25 | Both B0 headers "PROPOSED — NOT IMPLEMENTED — NOT ACCEPTED"; register §6 "None of these is resolved" | Current status is this addendum's header: Mock-implemented, Owner review pending, not accepted; L8–L10 resolved for Mock, L11 deferred |
