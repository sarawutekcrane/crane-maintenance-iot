# R3 Supersession and Decision Register (v1)

Status: **PROPOSED — NOT IMPLEMENTED — NOT ACCEPTED.** R3-B0 documentation draft for Owner
review, companion to `r3-implementation-contract.md`, prepared on 2026-10-18 at baseline
`e1a68d9bf4abb91adb97b1e753b4fa3634f847e6`.

This is the new R3 register. It is separate from, and does not modify, the existing
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`, which stays unchanged as history.

Historical documents are not modified. Where they conflict with R3, this register records which
clause governs, so that older agreements are not silently restored. This register authorizes no
implementation.

## 1. Classification
No content is Owner-approved merely because it is untagged.

| Category | Content | Section |
|---|---|---|
| Owner-approved business rules | R3-01..R3-24 as amended; O-1..O-5.2; Q1..Q6; T1..T5 | §2 |
| Proposed technical mechanisms | TS-1..TS-14 (contract §16); none is Owner-approved; each needs batch-specific authorization | §3, contract §16 |
| Unresolved implementation conditions | L1..L11 | §6 |
| Documentation-only process statements | Document status and authority, the batch plan (contract §17), the acceptance scenario list (contract §18), and the incorporation of documentation corrections C1..C5 and C-A..C-C (documentation only) | §3, contract §17–§18 |

## 2. Owner-approved decisions (2026-10-18), closed
| ID | Decision | Contract clause |
|---|---|---|
| O-1 | Mock + isolated TEST; REAL forbidden | §2 |
| O-2 | Narrow CANCELLED, limited further by Q4 | §10 W5 |
| O-3 | Manager / explicit delegate only for Finding-related management actions | §8 |
| O-4 | Model checklists for vehicles AND equipment; additive equipment model reference | §5 |
| O-5.1 | NOT_INSTALLED never ends a Finding | §7 N1 |
| O-5.2 | Item removed by revision never ends a Finding; manual termination with reason | §7 N1, E4 |
| Q1 | B — reuse the existing Repair authorization; manager/delegate restriction kept | §8 |
| Q2 | B — only the current V2 lead submits completion, server-verified | §10 W2 |
| Q3 | A — after cancellation before work, a later PASS ends the Finding | §7 E1(b) |
| Q4 | No cancellation once real work started, after completion, or once CLOSED | §10 W5 |
| Q5 | B — no Finding or Finding round from a manager-only observation; independent MANUAL flows unchanged | §10 W6, §9 P4 |
| Q6 | No pre-R3 Finding migration or view; no deletion or rewrite of existing data | §15, §9 P1 |
| T1 | A — reuse the capability architecture with one narrow additional capability; delegation limitation recorded | §8 |
| T2 | A — guard every Finding-provenance route to a Work Order, including Repair Request conversion | §9 |
| T3 | A — CLOSED, CANCELLED and completion-submitted orders refuse new actions and parts | §10 W3 |
| T4 | Readers before writers for every new status or result value | §14 |
| T5 | A — V2 integration tested on mock first; Sheets TEST needs isolation proof and a separate prerequisite | §2 |

## 3. Documentation corrections and how each is classified
C1..C5 and C-A..C-C are documentation corrections the Owner approved for incorporation into these
R3-B0 documents. They are not separate Owner-approved business rules.

| ID | Correction | Classification | Contract clause |
|---|---|---|---|
| C1 | Closing an R3 Finding round also requires the narrow Finding capability; non-R3 closure is unchanged | Application of O-3 / Q1 / T1; mechanisms TS-1, TS-2; delegate representation unresolved (L11) | §8, §10 W4 |
| C2 | An R3 Finding round may be CLOSED only after a valid lead completion event | **Proposed technical mechanism TS-4**; the no-completion case is unresolved (L9) | §10 W4 |
| C3 | Automatic end on PASS only when there is no linked Work Order or every linked one is CANCELLED | Exact reading of Q3 and R3-24 | §7 E1, E2 |
| C4 | Both Finding bypass routes documented and guarded | Application of T2; mechanisms TS-3, TS-5; compatibility choice unresolved (L5); stuck requests unresolved (L10) | §9 P2 |
| C5 | Verification of untracked documentation files | Documentation-only process (R3-B0 verification); not a contract rule | — |
| C-A | Classification corrected: untagged text is not Owner-approved by default; previously untagged mechanisms are now TS-10..TS-14 | Documentation-only process | §1, §4, §5, §7, §10 W2, §12, §16 |
| C-B | The Finding delegate is no longer described as a narrow role; its representation is an unresolved least-privilege problem | Unresolved implementation condition L11 | §8 |
| C-C | Batch references defined (R3-B0..R3-B10); L1..L11 notation; register naming; TS-4 / L9 gate aligned | Documentation-only process | §1, §16, §17 |

## 4. Superseded clauses (quoted; the source text is unchanged)
| # | Source | Superseded wording | Governing replacement |
|---|---|---|---|
| X1 | Owner R3-06 (first R3 prompt) | "Technician closing a Repair Work Order (CLOSED) does NOT automatically verify/close Finding. Maintenance manager or authorized delegate explicitly verifies correction … If correction is not accepted, continue follow-up." | The episode ends at the lead's completion (§7 E3). The manager controls closure (§10 W4). No verification step. |
| X2 | Owner R3-24 (first prompt) | "manager/delegate verification is required for a completed repair as in R3-06" | Removed; §7 E3, §10 W4. |
| X3 | Owner R3-11 (first prompt) | "until verified/appropriately terminated … awaiting-verification" | Active = OPEN; there is no awaiting-verification group (§12). |
| X4 | Read-only audit report v1 (2026-10-18), proposed contract §7 | "PENDING_REPAIR_DECISION → IN_REPAIR → AWAITING_VERIFICATION → VERIFIED_CORRECTED" and its transition table | OPEN / ENDED + end_reason (§7). |
| X5 | Read-only audit report v1, open decisions O-5.3 / O-5.4 | "Abnormal again while awaiting verification → same Finding"; "Normal after CLOSED but before verification → still needs verification" | After T_finish, any abnormal result creates a new Finding (§7 R1). |
| X6 | vNext-2 report, Q1 option | "add `can_manage_finding_followup` and `can_cancel_repair`" | One narrow capability (§8, TS-1). |
| X7 | vNext-2 report, Q2 option | "a current V2 assignment member" | Current V2 PRIMARY only (§10 W2). |
| X8 | vNext-2 report, Q3 option / scenario D2 | "a later PASS does not end it automatically" | §7 E1(b). |
| X9 | vNext-2 report, Q4 option / W5 | "allowed only before completion submission" | Allowed only before any recorded work (§10 W5). |
| X10 | vNext-2 report, Q5 option / W7 / scenario E | "new MANUAL Work Order with a provenance note" | Removed for the R3 flow (§10 W6). |
| X11 | vNext-2 report, Q6 option | "a separate 'ข้อมูลเดิมก่อน R3' list" | Removed (§15). |
| X12 | First R3-B0 draft, §7 E1 | "PASS … OPEN, no active repair" | Exact condition E1(a)/(b) (C3). |
| X13 | First R3-B0 draft, §8 | "Close Work Order — `can_close_repair`" for every order | R3 rounds additionally need the narrow capability (C1). |
| X14 | First R3-B0 draft, §10 W4 | "Allowed with or without a completion event" | R3 rounds: proposed mechanism TS-4; non-R3 unchanged (C2). |
| X15 | Phase 3 prompt `03_PHASE3_INSPECTION_CHECKLIST_HISTORY_EN.txt:142–145` | "PASS/FAIL/N/A … required-photo-on-fail rules" | §4. |
| X16 | `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` D01, D02, D04, F02 | TBD-BLOCKING | Resolved for R3 by §5, §6, §6 S1, §9. F01 stays open apart from the narrow CANCELLED (§10 W5). D03 stays SOURCE-DATA-REQUIRED. The file itself is unchanged. |
| X17 | Second R3-B0 draft, contract §1 | "Untagged rules are Owner-approved business rules." | Explicit classification; untagged text is not Owner-approved by default (C-A). |
| X18 | Second R3-B0 draft, contract §8 / TS-2 | "a provisional TEST "Finding delegate" role holds exactly `can_view`, `can_manage_repair`, `can_close_repair` and `can_manage_finding_repair`" | Withdrawn as a proposal; delegate representation is unresolved (L11, C-B). |

## 5. Preserved accepted features
- Immutable inspection snapshots and the revision display.
- Attachment authorization (REV06.2).
- Repair Request reporting under `can_report_repair` and the Decision B exact-source duplicate
  check.
- Technician Assignment V2 only, legacy routes returning 410, no V1 fallback; the V2
  assign/withdraw authorization is unchanged (L8).
- Meter snapshots, the 7E2 report (extended to read ENDED), the open-repair report, my-work.
- R2 acceptance and its R11 deferrals.
- Closure and recording rules for every non-R3 Work Order (MANUAL, Repair Requests without
  Finding provenance, unrelated INSPECTION_RESULT, PM_RESULT, ALERT, pre-R3 and legacy-model
  orders), except the T3 frozen-round refusal on CLOSED orders.

### Key distinctions
- **Finding ENDED vs Work Order CLOSED.** ENDED closes an observation episode. Its reason may be
  a normal re-inspection, the lead's completion submission, or manual termination; none of them
  certifies a successful repair. CLOSED is the manager's separate administrative act with its own
  time. A Finding can be ENDED while its round is still OPEN. If TS-4 is adopted, an R3 round is
  never CLOSED while its Finding is still OPEN. A CLOSED order is never re-labelled failed when
  the defect returns.
- **CANCELLED before work.** CANCELLED records an R3 round that was opened but never worked on.
  It needs a manager/delegate, a reason and a successful evidence check (TS-7), and it never
  happens automatically. The Finding stays OPEN; a later PASS ends it only if every linked order
  is CANCELLED (§7 E1(b)).

## 6. Unresolved implementation conditions
None of these is resolved or production-ready.

### 6.1 Tracked items for review gates
| ID | Actual problem | Potential operational impact | Intended batch / gate | Required evidence / test | Separate Owner approval |
|---|---|---|---|---|---|
| L5 | (a) `POST /repairs` accepts `source_type=INSPECTION_RESULT` (`repair_service.py:80–81`; accepted Phase 4 flow, `tests/test_repair_api.py`). An abnormal R3 result could reach a Work Order without its Finding. (b) There is no existing field marking a Work Order as an R3 Finding round. | A Finding-less round would bypass the manager-only check and the exact-Finding duplicate check, and its Finding would never end through E3. | R3-B3 gate: choose TS-5 (refuse for R3 abnormal results) and the TS-3 marker mechanism; decide whether the unrelated INSPECTION_RESULT flow stays. | Bypass tests (T-09); a regression of the accepted INSPECTION_RESULT tests for non-R3 results; marker read-back on mock. | **Yes**, for any change to the accepted INSPECTION_RESULT flow and for the marker's persistence. |
| L8 | V2 assign / withdraw (`technician_assignment_routes.py:58`) accepts any `can_manage_repair` holder, including MAINTENANCE and SUPERVISOR, on R3 rounds too. | Non-manager staff could change the technician of a Finding round, which goes against the manager/delegate intent of R3-04. | R3-B3 gate. | A 403/200 matrix for assign and withdraw on R3 and non-R3 jobs; the R2 V2 regression suites. | **Yes**: the change touches accepted R2 / V2 behaviour. Until decided, V2 stays unchanged. |
| L9 | An R3 round with recorded work whose current V2 PRIMARY cannot submit completion (set withdrawn → NONE, AMBIGUOUS set, technician unavailable). TS-4 blocks closure; Q4 blocks cancellation. | The round stays OPEN indefinitely; the Finding can end only through manual termination (E4); queues show a stuck order. | Reviewed at the R3-B8 gate (completion) and the R3-B9 gate (TS-4 closure). No automatic proxy completion, cancellation or closure bypass is introduced. | A mock scenario reproducing each NONE / AMBIGUOUS / unavailable case, showing that closure and cancellation are refused and E4 still works. | **Yes**, for any exception path (for example proxy completion or a recorded override). |
| L10 | A pending Repair Request with Finding provenance whose Finding has ENDED cannot be converted (guard E-2). The Repair Request flow has no rejection state (REV05 TBD). | The request stays PENDING in the queue permanently. | R3-B3 gate (conversion guard); any rejection state belongs to R5. | A conversion attempt after the Finding ended is refused; the pending queue shows the request unchanged. | **Yes**, for any new Repair Request state or queue behaviour. |
| L11 | Least privilege for the Finding delegate. The Finding-round checks require `can_manage_repair` or `can_close_repair` in addition to `can_manage_finding_repair`. A delegate role holding those existing capabilities would also gain authority over unrelated repair flows (MANUAL orders, conversions without Finding provenance, closing non-R3 orders, V2 assignment, recording on any order). A role holding only `can_manage_finding_repair` would fail those checks. | Either the delegate is broader than the Owner rule intends, or the delegate cannot perform the Finding actions. | R3-B3 gate. No delegate role or grant is proposed until then, and no new RBAC mechanism is introduced. | Permission-matrix tests for every action in contract §8, per role (T-17), for whichever representation is chosen. | **Yes**, before any capability, role or check change. |

### 6.2 Other established limitations
- L1 Delegation is role-based only. Per-person scope, expiry and grant audit cannot be expressed
  (production RBAC: R11). Gate: R3-B3.
- L2 The cancellation evidence gate cannot see physical work that was never recorded. Gate:
  R3-B9.
- L3 Google Sheets multi-row atomicity and cross-process races are R11 restrictions. Mock guards
  are not production evidence. Gate: R3-B6 (recorded as an accepted limitation), R11.
- L4 Sheets TEST V2 end-to-end is blocked until a TEST-scoped technician master exists. TEST–REAL
  isolation must be proven and recorded before any TEST write. Gate: R3-B8 (mock first); a
  separate Owner-approved TEST prerequisite.
- L6 Live TEST and REAL data presence is UNVERIFIED. Anything found is reported, never altered.
  Gate: R3-B4 and any later batch that touches TEST.
- L7 The Master Roadmap is external and UNVERIFIED in this repository. Gate: none (documentation
  provenance only).
