# R3 Implementation Contract — Daily Inspection and Finding Follow-up (v1)

Status: **PROPOSED — NOT IMPLEMENTED — NOT ACCEPTED.** R3-B0 documentation draft for Owner
review, prepared on 2026-10-18 from the read-only audit of `web/phase7-dashboard-search-reporting`
@ `e1a68d9bf4abb91adb97b1e753b4fa3634f847e6`.

[DOC] This document authorizes no implementation. Each batch (R3-B1 onward, §17) needs its own
Owner authorization. Supersessions, decision sources and open limitations are recorded in
`r3-supersession-and-decision-register.md` (the new R3 register). Historical documents (Phase 3,
Core Demo Fixes, 7E2, R2, the existing `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
and the external Master Roadmap) are unchanged.

## 1. Precedence and classification of content

Content in this contract is classified as follows. No clause is Owner-approved merely because it
is untagged.

1. **OWNER-APPROVED BUSINESS RULES.** R3-01..R3-24 as amended, O-1..O-5.2, Q1..Q6 and T1..T5
   (all 2026-10-18). A clause is an Owner rule only where it states, or is cited to, one of these
   decisions (for example "Owner rule Q2" or "(T3)"). These govern where they conflict with
   anything else.
2. **PROPOSED TECHNICAL MECHANISMS (TS-1..TS-14).** Implementation mechanisms, code names,
   derived display labels and data-handling details proposed in support of the Owner rules. They
   are tagged **TS-n** where they appear and are listed in §16. None is Owner-approved; each
   needs batch-specific authorization before it is built.
3. **UNRESOLVED IMPLEMENTATION CONDITIONS (L1..L11).** Known limitations or exception cases
   awaiting design or Owner approval, tagged **L1..L11** where they appear (register §6). None is
   resolved or production-ready.
4. **DOCUMENTATION-ONLY PROCESS STATEMENTS ([DOC]).** Statements about this document's own
   status and authority, the batch plan (§17) and the acceptance scenario list (§18). They
   create no business rule and authorize no work. The Owner approved incorporating the
   documentation corrections C1..C5 and C-A..C-C into these R3-B0 documents; that approval
   covers documentation only (register §3).

Other untagged text is descriptive context: current-code evidence (marked VERIFIED where read)
or cross-references.

Sources: accepted historical documents (Phase 3, Core Demo Fixes, 7E2, R2). The Master Roadmap is
an external Owner document, not present in this repository (UNVERIFIED here, L7). Code is
evidence of existing behaviour, never authority. Real checklist content, model mappings, item
frequencies and real role grants are UNVERIFIED until supplied.

## 2. Data scope
- Mock, and isolated TEST only after (a) a separate Owner approval and (b) a recorded TEST–REAL
  isolation proof. REAL schemas and data are never read or written by R3 batches.
- Mock results are not production evidence. Google Sheets multi-row atomicity, races and
  production RBAC are R11 restrictions (L3).
- Sheets TEST V2 end-to-end is blocked today: no TEST-scoped live technician master exists
  (`technician_assignment.py:32–34`). R3 repair-round flows are tested on mock first (T5, L4).

## 3. Safety
Every inspection result is an observation. No R3 record, label or report verifies a repair,
accepts work or declares an asset safe. 'ใช้งานได้รอการแก้ไข' and 'ไม่มีอุปกรณ์ติดตั้ง' grant no
regulatory or safety permission. R3 adds no safety-permit workflow and never prevents a
real-world safety response.

## 4. Inspection results and Thai labels
| Stored code | Thai label | Remark | Photo | Finding effect |
|---|---|---|---|---|
| PASS | ปกติ | optional | optional | may end an episode (§7 E1) |
| FAIL | ผิดปกติ | required, non-empty | optional | creates or continues |
| USABLE_PENDING_REPAIR | ใช้งานได้รอการแก้ไข | required, non-empty | optional | creates or continues |
| NOT_INSTALLED | ไม่มีอุปกรณ์ติดตั้ง | optional | optional | none; history only; never ends an episode |
| NA (legacy, read-only) | ไม่เกี่ยวข้อง (ข้อมูลเดิม) — display text proposed (TS-10) | — | — | never offered for new entry; never reinterpreted |

The four result codes and Thai labels, the remark and photo rules, and legacy NA read
compatibility without reinterpretation are Owner rules (R3-15, R3-16, Q6). The display text for
legacy NA is a proposed mechanism (TS-10). The per-item `required_photo_on_fail` and
`required_remark_on_fail` flags are kept for reading history but no longer drive validation
(R3-15).

## 5. Checklist model resolution and item identity
- M1 Resolution for vehicles and equipment: ASSET override → exact MODEL checklist → explicit
  MISSING_CHECKLIST. No fallback to another model or asset type.
- M2 Equipment model (O-4): an additive equipment→model reference; the equipment registry and
  its history are unchanged; no real model data is invented. **TS-11 (proposed):** the reference
  is append-only and effective-dated.
- M3 Revisions are immutable. Each item has `item_key` (stable across revisions, never derived
  from the title) and `frequency` ∈ {DAILY, EVERY_7_DAYS} (R3-02, R3-03, R3-14).
- M4 **TS-12 (proposed):** the active checklist revision is chosen by Asia/Bangkok date (the
  current code uses the UTC date, `mock/repository.py:813`).

## 6. Due logic and submission
- D1 The form shows all DAILY items plus every EVERY_7_DAYS item that either has no prior
  submitted result for asset + item_key, or has today (Bangkok) ≥ last result date + 7 days.
  Every accepted result value counts.
- D2 First inspection: daily + all weekly items. No backfill, no missed or overdue queue.
  Every shown item must be answered; items not shown are refused.
- S1 Submitted inspections are immutable (no edit, void, supersede or retrospective date);
  inspector and time come from the server.
- S2 `request_id`: same id + same payload → the original result, with no new rows, Findings,
  events or snapshot. Same id + different payload → rejected (TS-9: 409 `REQUEST_ID_REUSED`).
- S3 One successful inspection per asset per Bangkok date, any inspector. A second, distinct
  submission is rejected (TS-9: 409 `INSPECTION_ALREADY_SUBMITTED_TODAY`).
- S4 The server requires `can_record_inspection`. The mock guard is single-process only (L3).

## 7. Finding episodes
Status ∈ {OPEN, ENDED}. `end_reason` ∈ {NORMAL_REINSPECTION, TECHNICIAN_COMPLETION_SUBMITTED,
MANUAL_TERMINATION}. Episode key = asset_type + asset_id + item_key. At most one OPEN Finding per
key. No symptom-text matching (R3-12, R3-14). The code names ENDED and
TECHNICIAN_COMPLETION_SUBMITTED are Owner wording; NORMAL_REINSPECTION and MANUAL_TERMINATION are
proposed code names (TS-9).

**Linked Work Orders of a Finding** = every R3 Finding round (§9 P1) whose provenance is that
Finding, whatever its status.

| # | Trigger | Precondition (exact) | Result |
|---|---|---|---|
| A1 | FAIL / USABLE_PENDING_REPAIR | no OPEN Finding for the key | NEW Finding id (never reused) |
| A2 | FAIL / USABLE_PENDING_REPAIR | OPEN Finding exists | observation appended |
| E1 | PASS | Finding OPEN AND either (a) it has NO linked Work Order, or (b) EVERY linked Work Order is CANCELLED (cancellation is only possible before work, §10 W5) | ENDED, NORMAL_REINSPECTION, 'ตรวจครั้งล่าสุดแล้วไม่พบความผิดปกติ', inspection link |
| E2 | PASS | Finding OPEN and ANY linked Work Order is OPEN or CLOSED | observation only; nothing ended, cancelled or closed |
| E3 | Lead technician completion (§10 W2) | Finding OPEN; the Work Order is its linked OPEN round | ENDED, TECHNICIAN_COMPLETION_SUBMITTED, 'สิ้นสุดรอบติดตาม — ช่างส่งงานซ่อมแล้ว' |
| E4 | Manual termination | Finding OPEN; manager/delegate (§8); reason required | ENDED, MANUAL_TERMINATION (actor, time, reason) |
| N1 | NOT_INSTALLED, or item removed by a revision | Finding OPEN | no change |
| R1 | FAIL / USABLE_PENDING_REPAIR after ENDED | — | NEW Finding (e.g. F-002), even if the earlier Work Order is still OPEN; optional non-judgemental `previous_finding_id` link |

- E1 and E2 together are the exact reading of Q3 and R3-24: automatic termination never applies
  while any linked Work Order is OPEN or CLOSED.
- A linked CLOSED Work Order without a completion event should not arise for R3 rounds if TS-4
  is adopted. If one is ever found (anomaly or pre-R3 data), E1 does not apply. The Finding stays
  OPEN and can end only through E4.
- The end labels 'ตรวจครั้งล่าสุดแล้วไม่พบความผิดปกติ' and 'สิ้นสุดรอบติดตาม — ช่างส่งงานซ่อมแล้ว' are
  Owner wording, and E3 is never shown as 'ได้รับการยืนยันว่าแก้ไขสำเร็จ' (Owner rule).
- **TS-14 (proposed derived display labels, not stored):** OPEN with no linked OPEN Work Order =
  'รอพิจารณาเปิดงานซ่อม'; OPEN with a linked OPEN Work Order = 'อยู่ระหว่างซ่อม'.

## 8. Authority — role / capability / action matrix
**Owner rule (O-3, Q1, T1):** Finding-related management actions are performed only by the
Maintenance Department Manager or an explicitly authorized delegate, reusing the existing
capability architecture with one narrow additional capability.

Current grants (VERIFIED by reading `authz.py:147–212`): MAINTENANCE and SUPERVISOR hold
`can_manage_repair` and `can_close_repair`; MAINTENANCE_MANAGER holds neither. Capabilities
derive from roles only (`capabilities_for_roles`, `authz.py:213–220`).

**TS-1 (proposed):** ONE narrow capability, provisionally named `can_manage_finding_repair`,
checked IN ADDITION to the existing capability on every action against an R3 Finding round
(§9 P1) or a Finding. No grant changes in B0.

| Action | Server check (proposed) | ADMIN | MAINT. MANAGER (proposed grants, TS-2) | Finding delegate (representation UNRESOLVED, L11) | MAINTENANCE / SUPERVISOR | TECHNICIAN / DRIVER |
|---|---|---|---|---|---|---|
| Record inspection | `can_record_inspection` | ✓ | — (unchanged) | — | ✓ | ✓ |
| Open Work Order, MANUAL (non-R3) | `can_manage_repair` | ✓ | ✓ | L11 | ✓ unchanged | — |
| Open R3 Finding round (any entry point, §9) | `can_manage_repair` + `can_manage_finding_repair` | ✓ | ✓ | intended ✓ (L11) | ✗ | ✗ |
| Report Repair Request (with or without Finding provenance) | `can_report_repair` (unchanged) | ✓ | — | — | ✓ | ✓ |
| Convert Repair Request without Finding provenance | `can_manage_repair` | ✓ | ✓ | L11 | ✓ unchanged | — |
| Convert Repair Request with Finding provenance | `can_manage_repair` + `can_manage_finding_repair` | ✓ | ✓ | intended ✓ (L11) | ✗ | ✗ |
| V2 assign / withdraw | `can_manage_repair` (existing, unchanged; see L8) | ✓ | ✓ | L11 | ✓ unchanged | — |
| Record action / part / evidence | existing V2 membership or `can_manage_repair`, plus round not frozen (§10 W3) | ✓ | ✓ | L11 | ✓ | members |
| Submit completion | actor = current V2 PRIMARY only (no capability substitutes) | lead only | lead only | lead only | lead only | lead only |
| Close non-R3 Work Order (MANUAL, Repair Request without Finding provenance, pre-R3) | `can_close_repair` (unchanged) | ✓ | ✓ | L11 | ✓ unchanged | — |
| Close R3 Finding round | `can_close_repair` + `can_manage_finding_repair` (+ TS-4 completion precondition) | ✓ | ✓ | intended ✓ (L11) | ✗ | ✗ |
| Cancel R3 Finding round | `can_manage_repair` + `can_manage_finding_repair` + §10 W5 gate | ✓ | ✓ | intended ✓ (L11) | ✗ | ✗ |
| Manually terminate Finding | `can_manage_finding_repair` | ✓ | ✓ | intended ✓ (L11) | ✗ | ✗ |

"intended ✓" records the Owner rule (O-3) that an explicitly authorized delegate may perform the
Finding action. "L11" means the delegate's authority for that action depends on how the delegate
is represented, which is unresolved. No delegate grant is proposed for approval yet.

- **TS-2 (proposed manager grants, approval at the R3-B3 gate):** MAINTENANCE_MANAGER gains
  `can_manage_repair`, `can_close_repair` and `can_manage_finding_repair`. This supports the
  Owner requirement (T1) that the Maintenance Department Manager can manage, assign and close
  existing Repair work. MAINTENANCE and SUPERVISOR are unchanged and never receive
  `can_manage_finding_repair`.
- **L11 (unresolved, least privilege):** the current Finding-round checks require
  `can_manage_repair` or `can_close_repair` in addition to `can_manage_finding_repair`. A
  delegate role holding those two existing capabilities would also gain authority over unrelated
  repair flows (MANUAL orders, conversions without Finding provenance, closing non-R3 orders,
  V2 assignment, recording on any order). A role holding only `can_manage_finding_repair` would
  fail those checks. No delegate role or grant is proposed until the R3-B3 gate resolves this,
  with permission-matrix tests and separate Owner approval (register §6.1).
- Delegation is role-based only (L1). No per-user RBAC framework is introduced.

## 9. Finding provenance and entry points
**Owner rule (T2):** every backend entry point that can produce a Work Order with Finding
provenance enforces the Finding authority and the exact-Finding duplicate check. Unrelated
Repair Request and independent MANUAL flows are not disabled.

- P1 An **R3 Finding round** is a Work Order created through a guarded R3 entry point below. It
  records the originating Finding id at creation time. **TS-3 (proposed):** a creation-time R3
  round marker; its mechanism is open (L5). Pre-existing Work Orders are never reclassified.
- P2 Entry points and guards. Every guard requires §8 Finding authority, the Finding OPEN, and
  NO linked Work Order with status OPEN (exact Finding id).
  - E-1 `POST /repairs` with `source_type=FINDING` (`repair_service.py:78–79`): guarded; creates
    an R3 Finding round.
  - E-2 Finding → Repair Request → conversion:
    - Creating the request is unchanged: the accepted reporter flow under `can_report_repair`,
      the Decision B exact-source duplicate check (`repair_request_service.py:148–177`) and
      server-built `[[SRC:FINDING:F]]` provenance.
    - Converting (`repair_request_service.py:217–292`, which yields
      `source_type=REPAIR_REQUEST`) is guarded with F decoded from the request's server-built
      provenance, and creates an R3 Finding round.
    - Requests without Finding provenance are unchanged.
    - A pending request whose Finding has ENDED stays unconverted (L10).
  - E-3 `POST /repairs` with `source_type=INSPECTION_RESULT` (`repair_service.py:80–81`; the
    accepted Phase 4 flow, `RepairCreatePage.tsx:22–28`, `tests/test_repair_api.py`):
    - **TS-5 (proposed safest rule):** refuse it with 422 `REPAIR_SOURCE_USE_FINDING`
      (returning the Finding id) when the result is an R3 abnormal result (FAIL or
      USABLE_PENDING_REPAIR) linked to a Finding. The manager opens the round from the Finding
      through E-1 instead.
    - All other INSPECTION_RESULT sources (pre-R3 results, PASS, NOT_INSTALLED, legacy NA) are
      unchanged.
    - Whether the unrelated INSPECTION_RESULT flow is kept or retired is open (L5, R3-B3 gate).
- P3 The check is per exact Finding id. RPR-001 (F-001) never blocks F-002.
- P4 Repair Requests without Finding provenance, and independent MANUAL Work Orders, are
  unchanged.
- P5 No inspection creates a Repair Request or Work Order automatically.

## 10. Repair round (one Work Order = one round)
- W1 Work Order status ∈ {OPEN, CLOSED, CANCELLED}. No acceptance PASS/FAIL, awaiting
  verification, failed repair or any other state.
- W2 Completion ('ส่งงานซ่อมเสร็จ'), Owner rule Q2:
  - submitted only by the current V2 PRIMARY, verified on the server from the authenticated user
    account and the current VALID assignment set;
  - refused for NONE, AMBIGUOUS, non-lead members and managers;
  - **TS-13 (proposed stale-assignment check):** the client sends the set id it saw; a mismatch
    with the current set is refused;
  - an append-only event with T_finish (server time), actor, request_id and note; idempotent on
    request_id; at most one per Work Order;
  - status stays OPEN.
- W3 Frozen round (Owner rule T3): after completion, CLOSED or CANCELLED, the backend refuses new
  repair actions and parts. **TS-6 (proposed):** the refusal also covers new repair evidence
  attachments through the upload route (`attachment_service.py:279–300`), consistent with the
  freeze rule. Existing rows are never altered.
- W4 Closure (Owner rule: manager-controlled, never automatic, never back-dated):
  - **R3 Finding round:** OPEN → CLOSED by a holder of `can_close_repair` +
    `can_manage_finding_repair` (§8). T_close (server time), actor and note are recorded
    separately from T_finish.
  - **TS-4 (proposed technical mechanism, not a separate Owner business rule):** an R3 Finding
    round may be CLOSED only after a valid completion event by its current V2 PRIMARY.
    Otherwise → 409 `REPAIR_COMPLETION_NOT_SUBMITTED`. Purpose: prevent an administratively
    closed round whose Finding remains OPEN. No exception or bypass is introduced (L9).
  - **Non-R3 Work Orders** (MANUAL, Repair Requests without Finding provenance, unrelated
    INSPECTION_RESULT, PM_RESULT, ALERT, and all pre-R3 or legacy-model orders): closure is
    unchanged (`can_close_repair`, `repair_service.py:292–314`).
- W5 CANCELLED (Owner rules O-2, Q4), R3 Finding round: OPEN → CANCELLED only.
  - Allowed only when: the manager/delegate holds the §8 authority; a reason is given; there is
    no completion event; and no recorded repair work exists.
  - **TS-7 (proposed evidence gate):** the server reads (all must succeed) find zero repair
    actions, zero parts and zero REPAIR_EVIDENCE attachments for the order. Any read failure →
    refused (503); any evidence of work → refused (409).
  - No transition between CLOSED and CANCELLED in either direction, and no reopening.
  - The gate cannot see unrecorded physical work (L2). Operational rule: a manager confirms with
    the technician before cancelling, and work is recorded as it happens.
- W6 A new repair round always gets a new Work Order. In the R3 Finding flow, a new round
  follows only a genuine new inspection → new Finding (Q5). Manager-only observations create no
  Finding and no Finding round.

## 11. Concurrency and idempotency
- request_id on inspection submission and on completion submission.
- **TS-8 (proposed):** mock single-process guards for one-per-day, one completion per Work
  Order, and the races between cancellation and new work, and between closure and completion.
- Sheets: partial multi-row writes and cross-process races remain R11 restrictions (L3).

## 12. Reporting and queues
- The active follow-up view shows OPEN Findings in the two display groups.
- ENDED Findings appear in history with their end reason.
- CANCELLED orders are excluded from V2 waiting, my-work and the open-repair report, and kept in
  history.
- Historical totals are kept separate from active counts.
- No priority, severity or due date.
- **TS-14 (proposed derived display label):** a completion-submitted, still-OPEN order may show
  'ส่งงานแล้ว รอปิดงาน' (display only).

## 13. Audit
Append-only events for observations, Finding ends, completion, closure and cancellation: actor,
server time, reason, references (inspection, result, Finding, Work Order, attachments, request_id).

## 14. Compatibility order (Owner rule T4)
Readers for CANCELLED, ENDED, USABLE_PENDING_REPAIR, NOT_INSTALLED and legacy NA ship and are
tested (no INTERNAL_ERROR, including the strict read at `google_sheets/repository.py:2839`)
BEFORE any batch writes a new value.

## 15. Deferred / non-goals
- 3-month repeat-repair analysis or KPI, technician ranking or blame, SLA or blocking rules
  (source facts and links are kept for later);
- pre-R3 Finding migration or a legacy-Finding view (Q6);
- a new RBAC framework, a repair acceptance workflow, a migration workflow, or any API behaviour
  not listed in a later approved batch;
- R4 PM, general R5 lifecycle, R11 atomicity / RBAC / REAL, B7;
- inspection correction UX, backfill, safety permits.

[DOC] This contract specifies planned work for later batches; it does not authorize that work.

## 16. Proposed technical mechanisms (summary)
| ID | Mechanism | Supports | Batch gate (§17) |
|---|---|---|---|
| TS-1 | One narrow capability `can_manage_finding_repair` (provisional name) | O-3, Q1, T1 | R3-B3 |
| TS-2 | MAINTENANCE_MANAGER grants (delegate representation is L11, not proposed) | O-3, Q1, T1 | R3-B3 |
| TS-3 | Creation-time R3 Finding round marker | T2, Q6 | R3-B3 (L5) |
| TS-4 | Completion event required before closing an R3 Finding round | Finding/Work Order consistency | R3-B9 (L9 reviewed at R3-B8 and R3-B9) |
| TS-5 | Refuse INSPECTION_RESULT sources for R3 abnormal results | T2 | R3-B3 (L5) |
| TS-6 | Frozen round also covers repair evidence uploads | T3 | R3-B2 |
| TS-7 | Recorded-work evidence gate for cancellation, failing closed | Q4 | R3-B9 (L2) |
| TS-8 | Mock single-process guards | R3-20, R3-21, Q2, Q4 | R3-B6, R3-B8, R3-B9 |
| TS-9 | Error codes and proposed code names introduced by this contract | all | the batch that introduces each |
| TS-10 | Display text 'ไม่เกี่ยวข้อง (ข้อมูลเดิม)' for legacy NA | R3-16, Q6 | R3-B1 |
| TS-11 | Equipment→model reference is append-only and effective-dated | O-4 | R3-B4 |
| TS-12 | Active checklist revision chosen by Asia/Bangkok date | R3-02, R3-21 | R3-B2 |
| TS-13 | Stale-assignment check (client-sent set id) on completion | Q2 | R3-B8 |
| TS-14 | Derived display labels 'รอพิจารณาเปิดงานซ่อม', 'อยู่ระหว่างซ่อม', 'ส่งงานแล้ว รอปิดงาน' | R3-11 | R3-B10 |

## 17. Proposed implementation batches [DOC]
Planning sequence only. Each batch needs its own Owner authorization; listing a batch here
authorizes nothing.

| Batch | Scope | Mechanisms / limitations reviewed |
|---|---|---|
| R3-B0 | Documentation freeze: this contract and the R3 register | — |
| R3-B1 | Reader compatibility only: CANCELLED, ENDED, USABLE_PENDING_REPAIR, NOT_INSTALLED, legacy NA display, 7E2 allowed statuses, strict Sheets enum read; no new value written | TS-10 |
| R3-B2 | Guards: `can_record_inspection` on submission; frozen-round refusal on CLOSED orders for actions, parts and evidence (T3); Bangkok revision date | TS-6, TS-12 |
| R3-B3 | Authorization and provenance: narrow capability, manager grants, delegate representation, guards on every Finding entry point | TS-1, TS-2, TS-3, TS-5; L1, L5, L8, L10, L11 |
| R3-B4 | Model checklists, equipment model reference, `item_key`, frequency, due logic | TS-11; L6 |
| R3-B5 | Result entry and the remark rule (writes) | TS-9 |
| R3-B6 | Submission `request_id` and one inspection per Bangkok day | TS-8, TS-9; L3 |
| R3-B7 | Finding episodes, automatic and manual end | TS-9 |
| R3-B8 | Lead-only completion event and frozen round (mock first) | TS-8, TS-13; L4, L9 |
| R3-B9 | Finding-sourced Work Order, per-Finding duplicate check, cancellation before work, closure precondition | TS-4, TS-7, TS-8; L2, L9 |
| R3-B10 | Follow-up view, reports, labels, 5 viewports; acceptance matrix | TS-14 |

## 18. Acceptance scenarios (design only — NOT RUN) [DOC]
| # | Case | Expected |
|---|---|---|
| T-01 | F-001 → R3 round RPR-001 (lead A) → day-2 FAIL | F-001 OPEN with 2 observations |
| T-02 | Lead A completes (T_finish) → day-3 FAIL while RPR-001 is OPEN → manager closes RPR-001 → RPR-002 from F-002 with lead B | F-001 ENDED (completion submitted); F-002 NEW; RPR-002 allowed; T_close ≥ T_finish, both kept |
| T-03 | Round cancelled before work → later PASS | CANCELLED (reason, actor, time); F ENDED via E1(b) |
| T-04 | Cancel after an action, part or evidence; after completion; after CLOSED; on a read failure | Refused (409 or 503); CLOSED ↔ CANCELLED refused |
| T-05 | Completion by a non-lead, a manager, with a stale set id, with a NONE or AMBIGUOUS set; then by the lead; then a retry | Refused for all but the lead; the lead succeeds once; the retry returns the original |
| T-06 | Close an R3 round with no completion event (TS-4) | 409 `REPAIR_COMPLETION_NOT_SUBMITTED`; Finding stays OPEN |
| T-07 | MAINTENANCE / SUPERVISOR closes, cancels or opens an R3 round, converts a Finding-provenance request, or terminates a Finding | 403 |
| T-08 | MAINTENANCE / SUPERVISOR closes a MANUAL or non-Finding request order without a completion event | Allowed (unchanged) |
| T-09 | `POST /repairs` INSPECTION_RESULT for an R3 abnormal result (TS-5) | 422 `REPAIR_SOURCE_USE_FINDING`; any other INSPECTION_RESULT source unchanged |
| T-10 | Linked CLOSED order with no completion event (seeded anomaly) → PASS | No automatic end; only E4 |
| T-11 | Action, part or evidence on CLOSED, CANCELLED or completion-submitted orders | Refused; existing rows unchanged |
| T-12 | CANCELLED and ENDED readers (repair read, V2 waiting, my-work, open-repair report, 7E2, Sheets strict read) | No INTERNAL_ERROR; live queues exclude them |
| T-13 | Inspection retry, reused id with a changed payload, a second inspector the same Bangkok day, the midnight boundary | Original; rejected; rejected; correct date |
| T-14 | Model, override, missing checklist, equipment without a model, first inspection, day 8, idle, `item_key` across revisions | As in §5–§6 |
| T-15 | Four results, remark rule, optional photo, legacy NA; NOT_INSTALLED or item removal on an OPEN Finding | As in §4; no automatic end |
| T-16 | TEST isolation; R2 and V2 regressions; 5 viewports | Proof recorded before any TEST write; suites green; no V1 fallback; no overflow |
| T-17 | Permission matrix for the chosen delegate representation (L11, R3-B3 gate): every row of §8, for the manager, the delegate, MAINTENANCE, SUPERVISOR, TECHNICIAN and DRIVER | Delegate authority matches exactly what the Owner approves at R3-B3; no unrelated repair authority unless explicitly approved |
