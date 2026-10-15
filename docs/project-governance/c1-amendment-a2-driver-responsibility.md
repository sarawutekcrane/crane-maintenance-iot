# R2 — C1 Amendment A2 — Permanent Responsible Driver, E2 Operational Assignment, Legacy Vehicle Driver Retirement

Status: **OWNER-APPROVED GOVERNANCE AMENDMENT FOR R2-C0** — UNCOMMITTED / READY FOR OWNER REVIEW (batch R2-C0,
documentation only).

**IMPLEMENTATION NOT YET AUTHORIZED.** R2-C0 changes governance documentation only. The pre-existing R2f-f backend
remains implemented and unchanged. E2 is not yet implemented, R11 production transactions are not yet implemented,
Legacy Vehicle Driver cutover has not occurred, and R2 has not been accepted. Each later batch (R2-C1 to R2-C4,
A2-10) needs its own separate owner authorization.

**Authority.**
- the owner's approval in principle of "R2 Governance Amendment A2 — Final Wording Proposal for Owner Review"
  (2026-10-15), which is the authoritative content of this file;
- "R2-C0 Governance Amendment Implementation — Owner Authorization — R2-C0 only" (this session, 2026-10-15);
- the owner decisions P1–P8 and O1–O4 recorded in A2-11, together with the REV5 owner business rules.

**What A2 does.** Like A1, A2 SUPPLEMENTS the frozen Corrected C1 contract. It does not rewrite, replace or edit C1 or
A1. It supersedes ONLY the obligations named in A2-0, and annotates the matching A1 statements in place (A2-9).

**Source limitation.** The frozen Corrected C1 is not stored as a file in this repository
(`docs/phase-results/r2-governance-v2-only-alignment-result.md` §1). Its exact wording could not be verified here.
A2 therefore identifies the affected C1 clauses by section and subject matter only; it does not quote, reproduce or
reconstruct C1 text. The A1 statements annotated under A2-9 were read from the repository at integration commit
`545748385a61a83bd9d880977bc40e025a527d11`.

Terms: **R2f-f** = the permanent responsible-driver history (existing). **E2** = the operational assignment history
defined below (not yet implemented). Examples use November 2026 and are illustrative only; times such as 08:00–20:00
and 20:00–08:00 are not defaults.

## A2-0 — Effect and Precedence

1. A2 supersedes ONLY the Phase 6 `vehicle_driver` legacy assignment retention obligations in frozen C1 §14, §20,
   §24 Q4 and §25, and the matching retention wording in A1.
2. Unaffected governance text remains in force, including:
   - Driver Master;
   - Personnel–Driver Links and the other references;
   - the R2f-a–g UI backlog;
   - histories, authorization, TEST/REAL isolation and auditing;
   - the Technician V2-only governance (A1, A1-R1).
3. Original decision texts are preserved. Supersession is recorded with explicit SUPERSEDED annotations, never by
   silently rewriting history.

## A2-1 — Permanent Vehicle Responsibility (R2f-f)

1. One vehicle may have zero or one permanent responsible driver at the same instant. One driver may permanently
   oversee several vehicles. Permanent responsibility does not imply that this person drives a vehicle at any
   particular time.
2. R2f-f remains the separate authority for permanent responsibility. Its event history and derivation remain
   unchanged for this feature. No E2 assignment, shift, cancellation or handover automatically changes R2f-f.
3. A legitimate R2f-f permanent responsible-person change is allowed while an E2 assignment remains active. It must
   not cancel or rewrite E2. Any independent R2f-f eligibility and authorization validation still applies.
4. R2f-f permanent responsibility is not an E2 operational-driving interval and does not block an E2 driver from being
   permanently responsible for other vehicles.

## A2-2 — E2 Operational Assignments — Scope

1. E2 is ONE separate append-only, versioned, auditable authority for temporary substitute-driving assignments and
   explicit shift-driving assignments, including day-to-day vehicle care during their effective assigned interval.
   E2 is NOT the retired Phase 6 `vehicle_driver` authority.
2. E2 documents the ASSIGNED driver, not verified actual attendance, actual physical driving, incident cause or
   fault. No attendance, GPS, vehicle-booking or incident-adjudication workflow is created as part of R2.
3. Routine no-shift driving by a permanent responsible driver does not require daily E2 entries. Where shift
   operation is used, the permanent responsible driver MAY be explicitly assigned to a shift alongside another driver
   on a different, non-overlapping shift. E2 entries are never created automatically from permanent responsibility.
4. A vehicle without any permanent responsible driver may still have E2 assignments, with a non-blocking warning.
   Missing shifts or unknown identities are never filled automatically from R2f-f.
5. Management writes are gated by `can_assign_crane_driver`; reads by `can_view` and the existing applicable
   authorization rules. Vehicle and driver references, current eligibility, Personnel–Driver Links and scope are
   validated fail closed, subject to the historical-correction exception in A2-7.2.

## A2-3 — Date, Shift and Time Contract

1. **Modes:**
   - FULL_DAY / NO_SHIFT: inclusive start and end calendar dates, no shift;
   - DAY_SHIFT;
   - NIGHT_SHIFT.

   DAY_SHIFT and NIGHT_SHIFT take a date range plus explicit applied scheduled start and end clock times on the
   assignment. No Worksite Master is required in R2; neither worksite nor branch is presumed equivalent.
2. **Time zone and FULL_DAY:** all work scheduling uses Asia/Bangkok. FULL_DAY normally covers
   [start date 00:00, day after end date 00:00). The UI shows it as ending at "24:00" on its last calendar day. The
   end is stored or calculated as next day 00:00, NOT as a literal 24:00 timestamp.
3. **Night label and duration:** NIGHT_SHIFT is labelled by its starting calendar date, even where the shift ends the
   next morning. Each shift is strictly longer than 0 and at most 24 hours. Equal clock start and end is valid only
   with an explicit next-day designation of exactly 24 hours; there is no ambiguous zero-length shift.
4. **Intervals:** the actual configured or entered APPLIED scheduled intervals govern conflict checks; DAY/NIGHT names
   alone do not. All effective intervals are half-open: the start is included, the end is excluded. Assignment times
   are never presented as verified actual attendance.
5. **Changed shift timing:** assignment-level applied times are preserved after they are recorded. When shift timing
   changes midway through an assignment:
   - divide it into date-based segments for the old and new scheduled hours;
   - preserve linkage and revisions;
   - revalidate all segments, including their mutual conflicts.

   Any conflict rejects the entire attempted change; there is no partial application.
6. **Administrative label:** a DAY_SHIFT administrative handover label at 00:00 after a prior FULL_DAY is not the
   driver's proven operating time and is not a driver-axis operational interval. The applied shift starts at its
   scheduled start clock time.

## A2-4 — Exclusivity, Warnings and Handovers

1. **Exclusivity:** a vehicle must not have two effective assigned operators during physically overlapping effective
   time, and a driver must not be assigned to two vehicles for physically overlapping effective time. Permanent
   responsibility is not counted in either operational-driving conflict check.
2. **Adjacency warning:** exact adjacency of one driver's assignments is allowed but warns of fatigue, breaks and
   fitness to operate. Saving the record is NOT a safety clearance. No legal rest minimum is invented, and no
   readiness to operate is certified.
3. **Normal next-day handovers:**
   - FULL_DAY ending Nov 20 → FULL_DAY starting Nov 21: valid at Nov 21 00:00.
   - FULL_DAY ending Nov 20 → DAY_SHIFT starting Nov 21: valid. The administrative transition is at Nov 21 00:00;
     driving is only from the applied DAY_SHIFT start.
   - A FULL_DAY starting Nov 20 on the same vehicle, or a DAY_SHIFT on Nov 20 inside the preceding FULL_DAY range: rejected.
4. **H2 — last-day night handover:**
   - A FULL_DAY ending on calendar date D may hand over at the applied start of a NIGHT_SHIFT whose first labelled
     date is D, only where this yields a non-empty derived predecessor interval.
   - An earlier NIGHT_SHIFT starting inside the FULL_DAY period, rather than on D, is rejected.
   - The original FULL_DAY dates stay in history. The derived vehicle AND driver effective ends equal the handover
     instant.
5. **H3 — morning handover:**
   - A NIGHT_SHIFT whose last labelled day is D, and whose applied last shift ends after midnight on D+1, may hand over
     to a FULL_DAY starting D+1 at that night shift's scheduled end.
   - The new FULL_DAY's stored starting date remains D+1; its derived effective start is the night shift's end.
   - The resulting interval must be non-empty.
6. **NIGHT_SHIFT → DAY_SHIFT:** true physical overlap is rejected; exact adjacency is permitted. H2 and H3 are
   narrow boundary exceptions only, never a general last-write-wins rule. No mid-shift handover workflow is in scope.
7. **HANDOVER event:** each H2 or H3 transition has a separate auditable HANDOVER event referring to:
   - the predecessor and successor identities and revision numbers;
   - the scheduled effective instant;
   - `recorded_at`, the recorder and the request ID.

   Original records are immutable. The event does not verify a physical handover.
8. **Whole-unit substitution:** a permitted substitution of an already scheduled driver is an explicit audited
   operation for a whole NIGHT or DAY shift, or a whole calendar day within a FULL_DAY. It is never part of an arbitrary
   partial shift. Outside H2/H3, inserting only a NIGHT_SHIFT over an existing FULL_DAY period is not allowed.
   Unaffected units continue under the original assignment (O4).

## A2-5 — Correction, Cancellation and Audit

1. **Future cancellation:** a future assignment cancelled before its start is removed from active planning and
   releases its interval. Its original details, the cancellation, the free-text reason, the actor and the recorded time
   remain available in an audit/history view. Stored rows and history are never physically deleted. Vehicle booking is
   a possible future consumer, not an R2 feature.
2. **Cancel before a handover:** a planned handover cancelled BEFORE its effective instant keeps its audit, revokes
   the transition and restores the predecessor's original derived coverage if no other conflict is introduced.
3. **Cancel after a handover:** after a handover took effect, elapsed periods are NOT restored retrospectively to the
   predecessor. The elapsed uncertain period is shown as UNKNOWN or an equivalent fail-closed state; an authorized,
   reasoned correction may resolve it. The system does not infer verified actual driving.
4. **Audited changes:** these are all audited, with immutable prior versions and a derived current state:
   - early ending, future booking and extending;
   - changing scheduled hours and replacing a whole shift or day;
   - correcting and cancelling.

   Retroactive correction of elapsed intervals requires a reason, the actor, the recorded time and conflict checks on
   both the vehicle and driver axes. A same-day new create does not require a retrospective reason merely because it is
   entered after 00:00.
5. **History:** earlier historical details are not automatically rewritten. Entered dates and hours, amendment
   chains, successful corrections and HANDOVER revisions are retained. The current UI shows the derived current
   assignment; history shows the originals and the changes.
6. **Fail closed:** missing or ambiguous references, and residual simultaneous assignment conflicts, fail closed. There is
   no invented assigned operator and no silent tie-breaker. Authorized corrections and cancellations can resolve
   inconsistencies. No separate actual-driver verification workflow is created.

## A2-6 — Duplicates, Scope, Concurrency and Production Dependencies

1. **Duplicates and replay:** an identical effective assignment submitted again does not create a duplicate and
   identifies the existing record. The same request ID with the same content replays the original result. A changed
   payload with a reused request ID is rejected.
2. **Stale and partial updates:** a stale edit requires an expected-revision guard. If a split or transition is only
   partly valid, the entire attempted logical update is rejected without partially changing the active assignment.
3. **Concurrent conflicting requests:** the first accepted by the trusted server transaction or serialization order
   wins. The conflicting later request is rejected with an explicit vehicle, driver and interval reason. Client device
   timestamps do not establish order. The present R2 non-production implementations are not represented as providing
   a multi-process or production transaction guarantee.
4. **Owner O1 APPROVED: NO E2 REAL WRITE USAGE ON GOOGLE SHEETS BEFORE R11.**
   - Mock/TEST implementation and tests may proceed under approved scopes, preserving TEST/REAL isolation and
     fail-closed behaviour.
   - This is NOT a claim that R11 or production database transactions are implemented or deployed.
   - R11 must implement reliable atomic production acceptance. R2 does not require a special Sheets-only production
     locking project.
5. **Scope, readiness and Live Sheets:** E2 needs explicit data-scope proof, read authorization, error semantics, audit
   and readiness handling. Any new E2 readiness source must not silently become a core health prerequisite, and must
   not create or edit any Live Sheets tab. These changes require a separate owner-authorized implementation review.

## A2-7 — Driver Eligibility and Historical Corrections

1. **Eligibility:**
   - A NEW or forward-effective assignment to a driver who is currently INACTIVE is rejected.
   - An existing assignment whose driver later becomes INACTIVE is retained, with a warning and no presumption of
     permission to continue operating.
   - Future appointments for that driver are retained with an abnormal status pending authorized review; there is no
     automatic silent cancellation.
2. **Owner O3 APPROVED:** authorized corrections of ELAPSED historical E2 assignments MAY name a driver who is
   currently INACTIVE, with a mandatory reason and complete revision/audit history. Present active status does not
   invalidate a factual historical correction.
   - The exception does not authorize new, current or future assignments for an INACTIVE driver.
   - It does not waive reference, scope or conflict validation.
   - If historical eligibility or scope cannot be established, it is not fabricated; the request fails closed as
     appropriate.
3. **Permanent responsibility and E2:** a person may be permanently responsible for several vehicles while having an
   E2 assignment on one. Permanent responsibility does not itself imply any driving.

## A2-8 — Legacy Retirement (C1 Supersession)

1. **C1 §14:**
   - SUPERSEDED for future cutover: the Phase 6 `vehicle_driver` assignment model, its 3 assignment routes and their
     retention tests.
   - Retained: `driver_master` and the four Driver Master routes, the Driver Master code, Personnel–Driver Links and
     the unrelated C1 §14 protections.
2. **C1 §20:** the `vehicle_driver` legacy read as an operational authority or readiness source is SUPERSEDED on approved
   cutover. No new R2 responsibility or assignment is sourced or migrated from its rows.
3. **C1 §24 Q4:**
   - SUPERSEDED: the prior requirement that the Phase 6 legacy driver-assignment routes remain available.
   - Preserved: R2f-f's three responsibility routes.
   - **Owner O2 APPROVED:** "No DELETE" means no HTTP DELETE endpoints and no deletion of saved data, history or Live
     Sheets tabs. Deleting old, unneeded API route CODE at the coordinated cutover is permissible after dependency
     proof and an owner-authorized batch.
4. **C1 §25:**
   - The `vehicle_driver` legacy-labelled panel is SUPERSEDED. It is replaced by TWO distinct Vehicle panels: the
     permanent responsible driver (R2f-f) and the assigned operational driver and shift (E2).
   - §25's other requirements are preserved:
     - stable IDs;
     - distinct current and history views;
     - effective vs recorded times;
     - unknown and scope-unproven states;
     - responsive display, ErrorState and stale → reload;
     - backend authorization, TEST/REAL and pending-intent.
5. **Order and protection:**
   - The old frontend and backend are not removed before the replacement is implemented and tested.
   - Live Sheets are not altered and legacy rows are not migrated.
   - Shared driver, personnel, audit, history, auth, report and test assets needed elsewhere are not removed.
   - Cleanup planning is based on dependencies and tests, not on frontend-reference evidence alone.

## A2-9 — A1 Amendment Annotations

The following annotations are appended in place to `docs/project-governance/c1-amendment-a1-v2-only.md`. No A1 text is
deleted or rewritten. Locations were verified against the A1 file at integration commit
`545748385a61a83bd9d880977bc40e025a527d11`.

| A1 location (verified) | A1 statement | Annotation appended |
|---|---|---|
| A1-R1 R2 "Superseded statements" table, row on A1-§24 / C1 §24 Q4 (line 77) | "Phase 6 Driver routes, the R2c / R2e GET schemas and "No DELETE" are unchanged." | [Phase 6 vehicle_driver assignment route retention SUPERSEDED by A2-8; four Driver Master routes remain.] |
| A1-R1 R3 "Amended C1 clauses", C1 §24 Q4 item (lines 92–93) | "Everything else in Q4 is unchanged." | [Exception to prior 'everything else in Q4 unchanged': legacy vehicle_driver assignment routes only SUPERSEDED by A2-8.] |
| A1-§24 "Unchanged C1 §24 Q4 (backend)" (lines 324–326) | "Phase 6 Driver routes … stay available in the backend. … No DELETE (unchanged)." | [Phase 6 vehicle_driver assignment route retention SUPERSEDED; 'No DELETE' interpreted as A2-8.3.] |
| A1-§25 "Mandatory separate UI backlog" (lines 368–369) | "legacy `vehicle_driver` labelling." | [Legacy vehicle_driver list/labelling backlog SUPERSEDED by R2f-f + E2 panels under A2-8.4.] |

The other A1-§25 backlog items, including "vehicle responsible driver", remain mandatory and are not superseded.

## A2-10 — Acceptance and Sequencing

Each batch needs its own separate owner authorization. None has started except R2-C0.

- **R2-C0:** governance documentation amendment with owner-approved wording and explicit source evidence, independently
  reviewed (this file and the A1 annotations).
- **R2-C1:** E2 backend, domain, API and mock TEST behaviour, including:
  - audit, schedules and handover;
  - whole-day or whole-shift substitution;
  - eligibility, queries and tests.

  No change to R2f-f permanent behaviour. E2 REAL Sheets usage is not enabled before R11.
- **R2-C2:** the mandatory R2f-a–g panels, plus E2 panels and historical search. The R2f-a–g panels are:
  - Personnel Technician / Account / Driver links and history;
  - department-history reads;
  - equipment caretaker;
  - vehicle permanent responsibility.

  Exact privileges are honoured, and there are no unapproved department-move controls.
- **R2-C3:** coordinated cutover, after the replacement UI is ready:
  - remove the three Phase 6 legacy assignment API routes, the legacy UI and the isolated code;
  - remove the obsolete `vehicle_driver` `_CORE_SCHEMAS` prerequisite and its static readiness coverage;
  - keep the four Driver Master routes and protect shared tests;
  - DO NOT touch any live Sheet, tab or data.
- **R2-C4:** complete backend, frontend and e2e regression; the acceptance matrix B01–B30 from REV5; a dependency
  review and owner R2 acceptance.
  - B28 is an acceptance contract for production. Mock one-process tests are not presented as production atomic
    guarantees.
  - R11 remains the production-gating dependency.

D5, H3, B7 and R11 are not complete, and A2 does not claim otherwise. B7 readiness remains gated by its actual
prerequisites. R3 (inspection and follow-up) is the next phase. Only after R2 and R3 acceptance is the handoff for
R4–R12 prepared. ESP32 firmware phases were not audited in this round.

## A2-11 — Owner Decisions (dated register)

### Decisions confirmed on 2026-10-15 (O1–O4)

| ID | Decision | Applied in |
|---|---|---|
| **O1** | E2 REAL in Google Sheets is prohibited before R11; no special Sheets production workaround is required. | A2-6.4, A2-10 (R2-C1) |
| **O2** | Remove verified retired legacy code and routes; do not delete actual data, history or Live Sheets; no HTTP DELETE API. | A2-8.3, A2-8.5, A2-10 (R2-C3) |
| **O3** | A reasoned, audited correction of past effective periods is allowed where the corrected driver is currently INACTIVE. It does not cover a new, current or future assignment. | A2-7.2 |
| **O4** | An internal substitution in a FULL_DAY range is limited to WHOLE CALENDAR DAYS; a partial DAY/NIGHT inserted mid-range is rejected. The separately approved H2 boundary handover and H3 morning handover remain valid. | A2-4.4, A2-4.5, A2-4.8 |

### Decisions previously approved by the owner (P1–P8)

The owner approved P1–P8 earlier in the R2 review conversation (recorded in the A2 proposal of 2026-10-15, and given in
full in the owner's R2-C0 review verdict of 2026-10-15). They are not taken from the older REV5 draft. The "Applied in"
column shows where A2 states the operative rule.

| ID | Approved operational decision | Applied in |
|---|---|---|
| **P1** | Routine no-shift driving by the permanent responsible driver does not require an E2 assignment. Where multiple shifts exist, explicitly assign each known shift driver, including the permanent responsible driver if applicable. Do not auto-fill unknown shifts. | A2-2.3, A2-2.4 |
| **P2** | Administrative handover dates/times and applied scheduled shift intervals have distinct meanings. Neither is proof of actual physical driving. | A2-3.4, A2-3.6, A2-4.3 |
| **P3** | Use derived effective operational intervals after approved handovers, corrections and substitutions for vehicle-axis and driver-axis conflict checks. | A2-4.1, A2-4.4, A2-4.5, A2-4.8, A2-5.4 |
| **P4** | Preserve immutable, auditable HANDOVER events with predecessor and successor references, effective instant, actor, recorded time and revision history. | A2-4.7, A2-5.5 |
| **P5** | Invalid references, ambiguous state and residual assignment conflicts fail closed. Never fabricate an assigned driver. Authorized resolution requires appropriate reason and audit. | A2-2.5, A2-5.3, A2-5.6, A2-7.2 |
| **P6** | E2 writes require `can_assign_crane_driver`. Apply the existing Driver and Personnel–Driver Links eligibility, authorization and scope gates, with the separately approved O3 exception for elapsed historical corrections. Permanent responsibility is not an E2 eligibility requirement. | A2-2.4, A2-2.5, A2-7.1, A2-7.2, A2-7.3 |
| **P7** | Concurrent conflicting assignments must have only one accepted winner. Production atomicity belongs to R11. R2 does not claim cross-process or production transaction safety. | A2-6.3, A2-6.4, A2-10 (R2-C4) |
| **P8** | Supersede only the approved legacy `vehicle_driver` obligations in C1 and A1. Preserve Driver Master, Personnel–Driver Links, R2f-f, shared infrastructure and historical data. Removal occurs only in an authorized coordinated cutover. | A2-0, A2-8, A2-9, A2-10 (R2-C3) |

### REV5 owner business rules

A2 incorporates the REV5 owner business rules that the owner accepted in principle (2026-10-15), as expressed in
A2-1 to A2-8. REV5 itself is an owner-review draft and is not stored in this repository. Its acceptance matrix
B01–B30 is referred to in A2-10 and is to be carried into the R2-C4 acceptance plan.
