# Web/API Phase 4 — PM / Repair — Post-Phase Verification Report

STATUS: AUDIT ONLY. No Phase 5 work was started, no Phase 1–3 architecture
was redesigned, no open governance decision (E01–E05, F01–F03, or any
other) was resolved or silently marked approved, no test was hidden, and
no frozen contract was changed as part of this verification.

**Process note:** the task instructions referenced
`docs/phase-results/web-phase-04-result.md` and described "Phase 4 has
been implemented." At the start of this audit, the local checkout of
`web/phase-04-pm-repair` (`fc7a234`) contained **no** Phase 4 code and no
such result file — only the approved Component Role Naming correction.
`git fetch`/`git pull origin web/phase-04-pm-repair` retrieved a newer
commit, `748be5c` ("Implement Web/API Phase 4: PM and Repair workflows"),
which is the actual Phase 4 implementation. This report verifies
**`748be5c`**, not the stale local state this session started from.

Documents read in full before verifying, as required:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt`
- `docs/phase-results/web-phase-01-verification.md`, `web-phase-02-verification.md`,
  `web-phase-03-verification.md`
- `docs/phase-results/component-role-naming-correction.md`,
  `component-role-naming-verification.md`
- `docs/phase-results/web-phase-04-result.md`

Plus direct reading of the actual `748be5c` diff/source (not the result
report's prose): `app/domain/pm.py`, `pm_service.py`, `repair.py`,
`repair_service.py`, `meter.py`, `meter_service.py`, `asset_lookup.py`,
`attachment_service.py`, the PM/Repair/meter API routers, the
`MockRepository` PM/Repair methods, `seed_data.py`'s PM section, the
Google Sheets declared schemas, the frontend PM/Repair pages and
components, `App.tsx`'s route diff, `VehicleDetailPage.tsx`/
`EquipmentDetailPage.tsx`'s diffs, and all 46 new backend test bodies (by
name, cross-checked against the claims they support) — plus an
independent, from-scratch re-execution of every automated suite in this
session (Section U).

---

## A. Requirement Traceability

| Requirement (Phase 4 SCOPE) | Implemented | Evidence file/module | Automated test evidence | Manual test needed | Notes |
|---|---|---|---|---|---|
| PLAN1/PLAN2/PLAN3/PLAN4 support structure | YES (structure); PARTIAL (content) | `app/domain/pm.py` (`PmPlan.plan_code: str`, arbitrary) | `test_plan2_plan3_plan4_are_not_fabricated` | No | Structure supports any plan code; only `PLAN1` has a master record. See Section D. |
| Do not invent missing plan data | YES | `seed_data.py` PM section docstring; only `PLAN1` seeded, generic placeholder task text | `test_plan2_plan3_plan4_are_not_fabricated` | No | |
| PM triggers: ENGINE_HOUR/PTO_HOUR/ODOMETER/CALENDAR | YES (metadata only) | `PmTriggerType` enum | none reads this value for calculation (correct — E02/E03/E04 unresolved) | No | Descriptive metadata only, not consumed by any due logic |
| Backend due calculation service | NOT_APPLICABLE (correctly not built) | `PmPlanStatus.due_status` is always `"UNKNOWN"` with explanatory note | N/A | No | Building a real one would require E02/E03/E04 approval first — correctly deferred, not skipped by oversight |
| PM work order | YES | `PmWorkOrder`, `PmService.open_work_order`/`get_work_order`/`list_work_orders` | `test_open_pm_work_order_references_active_plan_and_revision`, 15 tests in `test_pm_work_order_api.py` | No | |
| Meter snapshot | YES | `MeterSnapshot`/`MeterService` | 11 tests in `test_meter_snapshot.py` | No | |
| Task revision | YES | `PmTaskRevision`/`PmTaskRevisionDetail` | `test_old_pm_task_revision_remains_readable_after_a_newer_one_becomes_active`, `test_new_pm_task_revision_does_not_mutate_old_work_order_history` | No | |
| Task result | YES | `PmWorkResult`, `PmService.submit_task_result` | `test_completed_task_result_is_not_silently_overwritten` | No | |
| Technician/user | YES | `opened_by`/`performed_by`/`closed_by` from `RequestContext.user_id` | covered indirectly by every work-order test | No | Real identity is `DEV_AUTH_MODE`'s fixed dev user — same pre-existing, disclosed limitation as every prior phase |
| Actual parts placeholder/integration | YES | `PmUsedPart` distinct from `PmTaskPart` | `test_actual_parts_used_are_separate_from_pm_task_standard_parts` | No | |
| Note/attachment | YES | `PmWorkOrder.note`, `PmWorkResult.evidence_attachment_ids` via `AttachmentService` | covered by PM work-order tests + `AttachmentPurpose.PM_EVIDENCE` | Yes — camera upload on a real phone | |
| Close workflow | YES | `PmService.close_work_order` | `test_close_work_order_preserves_task_result_history`, `test_closed_work_order_rejects_new_task_results` | No | |
| Repair: separate from PM | YES | Separate `Repair`/`RepairDetail` model, no shared table/ID prefix | `test_repair_is_separate_from_pm_work_order_namespace` | No | |
| Repair sources: MANUAL/INSPECTION_RESULT/FINDING/PM_RESULT/ALERT | YES | `RepairSourceType` | `test_manual_repair_creation_works`, `..._inspection_result_source_linkage_supported`, `..._finding_source_links..._without_mutating`, `..._pm_result_source_linkage_supported`, `..._alert_source_is_interface_ready...` | No | See Section K for per-source validity caveats |
| Category/symptom | YES | `Repair.category`/`symptom` (free text) | covered by repair-creation tests | No | No approved category vocabulary — free text is correct, not a gap |
| Meter snapshot on repair | YES | `Repair.meter_snapshot_id` | covered by repair-creation tests | No | |
| Driver/operator context | NOT_APPLICABLE | No driver/operator domain exists in Phases 1–4 | N/A | No | Correctly out of reach — nothing to attach yet |
| GPS when available | NOT_APPLICABLE | No GPS domain exists yet | N/A | No | Correctly out of reach |
| Attachments | YES | Shared `AttachmentService`, `AttachmentPurpose.REPAIR_EVIDENCE` | `test_repair_attachment_uses_storage_reference` | Yes — camera upload | |
| Append-only repair actions | YES | `RepairAction`, `RepairService.add_action` | `test_repair_action_history_is_append_only_and_previous_actions_remain_readable` | No | |
| Close workflow | YES | `RepairService.close_repair` | `test_close_repair_requires_no_unapproved_fields` | No | |
| Alert linkage | YES (interface only) | `RepairSourceType.ALERT` accepted structurally, no existence check | `test_alert_source_is_interface_ready_without_an_alert_domain` | No | Correct — no Alert domain exists yet; explicitly disclosed, not presented as a complete integration |
| PM formula not implemented independently in frontend | YES | `PmStatusPage.tsx` renders `due_status`/`due_status_note` verbatim, no client-side calculation | Frontend source read; `PmStatusPage.test.tsx` | No | |
| Same backend due service usable later by Dashboard/Vehicle Detail | YES (architecturally) | `PmService.list_applicable_plan_status` is the single source; no duplicate implementation elsewhere | Source read — only one call site defines this logic | No | No Dashboard exists yet (Phase 7) — nothing to duplicate it there yet |
| Google Sheet formulas not authoritative | YES (trivially) | No Google Sheets I/O is live; declared schemas only | N/A | No | |

**Traceability verdict:** every mandatory Phase 4 SCOPE item is present,
correctly scoped, and evidenced by a real, independently re-executed
automated test. The only structural PARTIAL (PLAN2/3/4 content) is
exactly what E05 requires — a plan *code* structure without invented
content — not an implementation gap.

---

## B. Open-Decision / Guessing Audit

| Decision | Current implementation behavior | Permanent rule or placeholder? | Explicitly approved? | Risk | Required action |
|---|---|---|---|---|---|
| **E01** PM Status Lifecycle | `PmWorkOrderStatus` has exactly `OPEN`/`CLOSED`. No `IN_PROGRESS`/`CANCELLED`/assignment state. No transition matrix anywhere in `PmService` beyond a single idempotency guard (cannot close twice, cannot add a result to a closed order). | Explicit, documented placeholder (`pm.py` module docstring: "provisional/configurable placeholder, not a resolution of E01"). Structurally reversible — adding a third state is an additive enum member plus new service checks, no schema break. | NO | Low today (single-user mock environment, no assignment/workflow feature depends on a richer lifecycle yet). | None for Phase 4. Must be resolved before any multi-user PM assignment/scheduling feature is built. |
| **E02** PM Warning Windows | No warning-window/tolerance/grace value exists anywhere in the codebase (grep-verified: no threshold constant in `pm.py`/`pm_service.py`/`config.py`). `due_status` is the literal string `"UNKNOWN"`. | N/A — nothing was decided, nothing invented. | NO source data supplied, correctly not invented. | None. | None for Phase 4. |
| **E03** PM Completion Baseline | `PmPlanStatus` exposes only `last_completed_work_order_id`/`last_completed_at`/`last_completed_meter_snapshot_id` — a **read of history** (the last closed work order for that plan+asset), not a computed "next baseline." No code anywhere treats this as the baseline for a future due calculation. | Correctly unresolved; the fact-only summary is explicitly documented as "a read of history, not a computed baseline" in `pm.py`. | NO | Low — nothing downstream currently consumes this as a baseline. | None for Phase 4. Must be resolved before any due/remaining calculation is built. |
| **E04** Missing Counter Behavior | `MeterReading.value: float \| None`. Verified end-to-end: domain model, `MeterService` (never defaults), `MockRepository.create_meter_snapshot` (stores `None` as-is), API response schema (`MeterReadingResponse.value: float \| None`), frontend type (`value: number \| null`), and the frontend rendering (`RepairDetailPage.tsx:206`: `reading.value == null ? 'ไม่ทราบค่า' : reading.value` — literal "unknown value", never `0`). | Correctly resolved as "never coerce" — this is the register's own stated direction ("Do not treat unknown as zero"), not an invented rule. | Consistent with the register's explicit rule, not a new decision | None found. | None. |
| **E05** PLAN2/PLAN3/PLAN4 Data | `SEED_PM_PLANS` contains exactly one entry (`PMP-0001`/`PLAN1`). Independently confirmed by reading `seed_data.py` directly (not the result report's claim) — no `PmPlan`, `PmTaskRevision`, or `PmTask` record exists for any other plan code. `GET /pm/plans/status` only returns plans matching seeded data; a guessed `PMP-0002/3/4` ID returns a controlled 404 (verified via `test_pm_plan_not_found_404`). | Correctly unresolved — a plan-code *concept* exists (the enum-free `plan_code: str` field accepts any string), but no content was fabricated for any unapproved plan. | NO (nothing to approve — nothing was invented) | None found. | None for Phase 4. |
| **F01** Repair Status Lifecycle | `RepairStatus` has exactly `OPEN`/`CLOSED`, identical reasoning/pattern to E01's `PmWorkOrderStatus`. | Explicit, documented placeholder (`repair.py` module docstring). Reversible. | NO | Low today. | Must be resolved before assignment/multi-technician repair workflow. |
| **F02** Finding-to-Repair Conversion | `RepairService.create_repair` accepts `source_type=FINDING`+`source_id`, validates the Finding *exists* (`find_inspection_finding`), but enforces no 1:1/many:1 rule, no deduplication, no approval step. A FAIL inspection never auto-creates a repair (`test_fail_result_does_not_automatically_create_a_repair`, independently re-run and passing). The source Finding is read-only — never mutated (`test_finding_source_links_to_repair_without_mutating_the_finding`). | Correctly unresolved — a *linking capability* was built, not a *business rule* about how many repairs a Finding may spawn. | NO | Low — a Finding could theoretically be linked from multiple repairs with no warning to the user; this is a UX gap once real usage begins, not a data-integrity risk. | Must be resolved before enforcing any 1:1/duplicate-prevention rule; until then, the current "link is possible, nothing enforced" behavior is correct. |
| **F03** Repair Closure Requirements | `RepairService.close_repair` requires only that the repair exists and is not already closed. No mandatory close note/technician/photo/part/approval/signature (verified directly in the method body — no such check exists). `test_close_repair_requires_no_unapproved_fields` independently re-run, passing — confirms a repair with zero actions/parts closes successfully. | Correctly unresolved. | NO | None found — no invented requirement to later walk back. | None for Phase 4. |

**No unapproved permanent business rule was found for E01–E05 or
F01–F03.** Every provisional/placeholder behavior is explicitly documented
in the relevant module's docstring (not just the phase report's prose),
independently confirmed by reading the actual code, and proven by a
still-passing, independently re-executed test. `OPEN_DECISIONS_REGISTER_EN.txt`
was not modified by Phase 4 (confirmed: `git diff fab84e3 748be5c --
docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` is empty).

---

## C. Special Audit — PM/Repair Status Placeholders

Checked directly against the code, not the result report's claim:

- **Not presented as approved company workflow states:** confirmed — both
  `PmWorkOrderStatus` and `RepairStatus` docstrings explicitly say
  "PROVISIONAL/CONFIGURABLE placeholder only... E01/F01 is not approved."
  No governance document or seed data calls `OPEN`/`CLOSED` an approved
  lifecycle.
- **No transition matrix was invented:** confirmed — grepped both service
  files for any state-transition table/dict; none exists. The only checks
  are idempotency guards (`PM_WORK_ORDER_ALREADY_CLOSED`,
  `REPAIR_ALREADY_CLOSED`, `PM_WORK_ORDER_CLOSED` for late results) — these
  are "is it already done" checks, not a transition matrix between three or
  more states.
- **No business logic assumes OPEN → CLOSED as the final production
  lifecycle:** confirmed — nothing in `PmService`/`RepairService` computes
  anything (a report, a KPI, a due calculation) that depends on there being
  only two states; the due-status calculation that would need a richer
  lifecycle simply does not exist yet (E02/E03/E04).
- **Future status expansion remains backward-compatible:** confirmed
  structurally — both are plain `str` Enums with no other code branching on
  "is it one of exactly these two values" other than direct equality checks
  against `OPEN`/`CLOSED` specifically; adding a third member is additive.
- **Frontend does not present them as a permanently frozen workflow:**
  confirmed by reading `PmWorkOrderDetailPage.tsx`/`RepairDetailPage.tsx` —
  both render a single `StatusBadge` from the current value via a label
  map (`pmWorkOrderStatusLabel`/`repairStatusLabel`); neither page renders
  a progress stepper, a workflow diagram, or any UI text implying these are
  the only two states that will ever exist.
- **E01 and F01 remain unresolved:** confirmed in Section B.

**No blocking finding.** `OPEN`/`CLOSED` is correctly implemented as a
minimal, disclosed, reversible placeholder — not a de facto frozen
workflow.

---

## D. PM Source Data / PLAN1 Placeholder Audit

- **PLAN1 content is clearly development/example/placeholder data:**
  confirmed — the plan's own Thai name is
  `"แผนบำรุงรักษาเชิงป้องกัน PLAN1 (ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)"`
  ("...temporary example data for development/testing system") and every
  task description is `"งานบำรุงรักษาตัวอย่างที่ N (PLAN1)"` ("example
  maintenance task N") — this discloses its nature in the rendered Thai UI
  itself, matching the same strong-disclosure pattern Phase 3's checklist
  placeholder used (and this audit independently confirmed for Phase 3).
- **No invented PM wording/interval/method/standard/part requirement
  presented as real data:** confirmed — every seeded `PmTask` has
  `trigger_type=None`, `interval_value=None`, `interval_unit=None`,
  `standard_parts=[]`. No numeric interval, standard, or part requirement
  of any kind exists in seed data.
- **PLAN2/PLAN3/PLAN4 were NOT fabricated:** confirmed by direct
  `seed_data.py` read (Section A) — `SEED_PM_PLANS` has exactly one entry.
- **Search for hardcoded PLAN2/PLAN3/PLAN4 tasks or intervals:**

  ```
  $ grep -rn "PLAN2\|PLAN3\|PLAN4" backend/app frontend/src
  (no matches)
  ```

  Confirmed: zero occurrences anywhere in application code. The only place
  the strings "PLAN2/PLAN3/PLAN4" appear at all in the repository is in
  governance/prompt documents (as concept names) and in this phase's own
  `test_plan2_plan3_plan4_are_not_fabricated`, which asserts their absence.

**No FAIL condition found** — per the audit's own rule ("If found without
authoritative source: FAIL"), since nothing was found.

---

## E. PM Revision / History Integrity

| Check | Result | Evidence |
|---|---|---|
| Stable PM plan identity | YES | `pm_plan_id` (`PMP-0001`), never regenerated; no update path exists for `PmPlan` at any layer |
| Stable task/revision identity | YES | `revision_id` (`PMREV-NNNN`), `pm_task_id` (`PMT-NNNN`) — seed-fixed, no mutation path |
| Old work orders retain the exact task revision used | YES | `PmWorkOrder.revision_id` set once at `open_work_order`; `submit_task_result` resolves tasks against `detail.work_order.revision_id`, never the plan's currently-active revision | `test_new_pm_task_revision_does_not_mutate_old_work_order_history` — independently re-read: it opens a work order, submits a result, inserts a second `PmTaskRevision` directly into the mock store, and confirms the already-open work order's history is unaffected |
| Later task revision does not change historical PM results | YES | Same evidence — `PmWorkResult.task_description` snapshots text at execution time, so even re-reading the old work order after a new revision exists shows the original text |
| Completed task results are not silently overwritten | YES | `PmService.submit_task_result` explicitly rejects a second result for the same task (`PM_TASK_RESULT_ALREADY_EXISTS`, 422) rather than replacing it | `test_completed_task_result_is_not_silently_overwritten` |
| Task order/history is reconstructable | YES | `PmTask.sequence`/`PmWorkResult.sequence`; `_pm_work_order_detail` sorts results by sequence |
| No Google Sheets row-number identity | YES | All IDs are prefixed opaque strings (`PMP-`, `PMREV-`, `PMT-`, `PMTP-`, `PMWO-`, `PMWR-`, `PMUP-`, `MSNAP-`, `RPR-`, `RPRA-`, `RPRP-`); declared Google Sheets schemas map by header name only (verified: `grep -n "row_number\|row number"` on `schemas.py` → no matches) |
| No update endpoint mutates historical completed PM results in place | YES | `backend/app/api/v1/pm.py` defines exactly `POST .../results` (create) — no `PATCH`/`PUT`/`DELETE` on any work-result path at any layer |

**No defect found.**

---

## F. PM Work Order / Result Model

| Check | Result | Evidence |
|---|---|---|
| `pm_work_order` → multiple `pm_work_result` | YES | `PmWorkOrderDetail.results: list[PmWorkResult]`; `create_pm_work_result` appends to a list keyed by work-order ID, never replaces |
| Work-order header separate from task results | YES | `PmWorkOrder` (header: asset/plan/revision/status/audit) vs. `PmWorkResult` (per-task record) are distinct Pydantic models with no field overlap beyond `pm_work_order_id` |
| Task results belong to the correct task revision | YES | `submit_task_result` looks up the task inside `detail.work_order.revision_id`'s own revision detail; a task ID from a different revision is rejected (`VALIDATION_ERROR`, 422) | `test_task_result_for_task_outside_the_revision_is_rejected` |
| Asset reference is stable | YES | `PmWorkOrder.asset_type`/`asset_id` reused from Phase 2's stable `vehicle_id`/`equipment_id`, never regenerated |
| Actor/time history retained where implemented | YES | `opened_by`/`opened_at`, `performed_by`/`performed_at` (per result), `closed_by`/`closed_at` all populated from `RequestContext`/`utc_now()` |
| No duplicate-authoritative state between frontend/backend | YES | `PmStatusPage.tsx`/`PmWorkOrderDetailPage.tsx` render `due_status`/status/results exactly as returned; no local recomputation found in either file |
| Frontend does not calculate PM status independently | YES | Confirmed by direct source read (Section A); the one client-side "calculation" is `state.tasks.sort(...)` by `sequence` for display order — not a business rule |

**No defect found.**

---

## G. PM Meter Snapshot Audit

| Check | Result | Evidence |
|---|---|---|
| `CARRIER_ENGINE` `ENGINE_HOUR` distinct from `CRANE_ENGINE` `ENGINE_HOUR` | YES | Reading validated against a specific `component_id`, not just `counter_type`; two readings with different `component_id`s but the same `counter_type` are independently stored | `test_carrier_engine_hour_remains_distinct_from_crane_engine_hour` |
| `PTO_HOUR` stays tied to correct component | YES | Same component-scoped validation | `test_pto_hour_associates_with_pto_component` |
| Vehicle odometer remains vehicle-level | YES | `MeterService` rejects any non-`ODOMETER` reading with `component_id=None`, and conversely accepts `ODOMETER` specifically as the one component-free counter | `test_odometer_is_vehicle_level_not_per_component`, `test_non_odometer_reading_without_a_component_is_rejected` |
| Single-engine vehicle does not receive fabricated `CRANE_ENGINE` | YES | `MeterService` validates `component_id` against the vehicle's **actual** `list_vehicle_components` result; a `CRANE_ENGINE`-role component that does not exist on a single-engine vehicle is rejected (`METER_COMPONENT_NOT_FOUND`, 422) | `test_single_engine_vehicle_rejects_a_fabricated_crane_engine_reading` — independently re-run, passing |
| `component_id` references are stable | YES | Reused verbatim from Phase 2's stable `component_id` (`CMP-NNNN`), never regenerated by Phase 4 |
| Missing/unknown values remain unknown/null | YES | See Section E04 above |
| Missing/unknown is NEVER silently converted to 0 | YES | `test_unknown_counter_value_stays_unknown_never_becomes_zero` — independently re-run, passing; also confirmed by direct code read of `MeterService`/`MockRepository.create_meter_snapshot`/API schemas — no `or 0`/default-to-zero pattern anywhere |
| E04 remains unresolved if business handling is not approved | Correctly treated as resolved-by-the-register's-own-rule, not invented | See Section B |
| A component from a different vehicle is rejected | YES (additional check beyond the audit's list, found during review) | `test_reading_a_real_component_from_a_different_vehicle_is_rejected` — a real `component_id` that exists but belongs to a *different* vehicle is still rejected, not just a nonexistent one |
| Equipment does not receive a fabricated counter/component model | YES | `MeterService` rejects any component-scoped reading when `asset_type != VEHICLE`; equipment snapshots may only carry `component_id=None` readings, and even those require nothing (an equipment snapshot with zero readings is valid) | `test_equipment_snapshot_may_carry_no_component_scoped_readings` |
| **E03 not silently decided as "completion snapshot = next PM baseline"** | YES — confirmed | `PmPlanStatus.last_completed_meter_snapshot_id` is documented and implemented purely as a **fact** (what was the last snapshot recorded), never consumed anywhere as an input to a due/remaining formula (no such formula exists in this phase at all) |

**No defect found.**

---

## H. PM Due / Warning Logic Audit

Searched the full repository for due/remaining/overdue logic:

```
$ grep -rn "due_status\|overdue\|remaining_hours\|remaining_distance\|warning_window\|grace_period" backend/app frontend/src
```

Only hits: `PmPlanStatus.due_status`/`due_status_note` (always `"UNKNOWN"` +
explanatory string) and their pass-through rendering in
`pm_schemas.py`/`PmStatusPage.tsx`. No calculation function of any kind
exists.

| Check | Result | Evidence |
|---|---|---|
| Backend/domain service is authoritative | YES (trivially — the only thing to be authoritative about is the literal string `"UNKNOWN"`) | `PmService.list_applicable_plan_status` is the sole producer of `due_status` |
| Frontend does not duplicate business calculations | YES | `PmStatusPage.tsx` line 113 hardcodes the Thai display text "ไม่สามารถคำนวณได้ในขณะนี้" ("cannot be calculated at this time") rather than computing anything from `last_completed_at`/dates |
| No warning-window values invented | YES | Confirmed — no threshold constant exists anywhere in `pm.py`, `pm_service.py`, `config.py`, or seed data |
| No tolerance/grace threshold invented | YES | Same search, same result |
| No fallback baseline invented | YES | `last_completed_*` fields are read-only facts, never defaulted or used as a computed baseline (Section G) |
| E02/E03/E04 remain unresolved unless supported by approved source | YES | Section B |
| Placeholder calculation interfaces are clearly isolated and reversible | YES | `PmPlanStatus.due_status: str = "UNKNOWN"` is a single field with a fixed literal value and an explanatory note field alongside it — trivially replaceable by a real calculation later without any schema-breaking change (the field already exists; only its value would start varying) |

**No defect found.**

---

## I. Standard Parts vs Actual Parts

| Check | Result | Evidence |
|---|---|---|
| `pm_task_part` (standard) vs `pm_used_part` (actual) vs `repair_part` remain separate concepts | YES | Three distinct Pydantic models (`PmTaskPart`, `PmUsedPart`, `RepairPart`), three distinct ID prefixes (`PMTP-`, `PMUP-`, `RPRP-`), three distinct repository storage structures | Direct model/repository read |
| Actual usage does not overwrite standard PM definition | YES | `test_actual_parts_used_are_separate_from_pm_task_standard_parts` — independently re-read: submits a result with `used_parts`, then re-fetches the task revision and asserts `standard_parts == []` (unchanged) |
| Repair parts do not appear as PM standard parts | YES | `test_repair_parts_are_separate_from_pm_parts` — independently re-run, passing; `RepairPart` has no relationship to `PmTask`/`PmTaskPart` at all (no shared foreign key, no shared table) |
| Phase 5 lifetime/instance tracking has NOT been implemented | YES | See Section T |
| No part-instance/lifetime reset logic introduced | YES | `PmTaskPart`/`PmUsedPart`/`RepairPart` all use `part_description: str` free text with **no** `part_id` field referencing any part master — confirmed by reading all three model definitions directly |

**No defect found.**

---

## J. Repair Domain Separation

| Check | Result | Evidence |
|---|---|---|
| Repair does not reuse PM work-order identity/model | YES | `test_repair_is_separate_from_pm_work_order_namespace` — independently re-run, passing; separate Pydantic models, separate repository dicts (`self._repairs` vs. `self._pm_work_orders`), separate ID prefixes |
| `repair_id` stable | YES | `RPR-NNNN`, generated once at creation, never regenerated |
| Repair action history append-oriented | YES | `add_repair_action` only ever appends to `self._repair_actions.setdefault(repair_id, []).append(...)`; no update/delete path at any layer | `test_repair_action_history_is_append_only_and_previous_actions_remain_readable` |
| Previous actions remain readable | YES | Same test — two actions added, both remain visible with distinct IDs after the second is added |
| No silent action overwrite | YES | Same evidence |
| Attachments use StorageProvider references | YES | `RepairAction.attachment_ids: list[str]` references `Attachment.attachment_id`; binary content only ever touches `StorageProvider` via the shared `AttachmentService` |
| Binary files are not stored directly in Google Sheets/database | YES | `Attachment.storage_ref` is a string; declared `repair_actions`/`repair_parts` Google Sheets schemas store metadata columns only (no binary column exists) |

**No defect found.**

---

## K. Repair Source Linkage

| `source_type` | Valid at this phase? | Validation behavior | Evidence |
|---|---|---|---|
| `MANUAL` | YES, fully | No `source_id` required or validated | `test_manual_repair_creation_works` |
| `INSPECTION_RESULT` | YES | `source_id` required; validated against `find_inspection_result` — rejected if not found | `test_inspection_result_source_linkage_supported`, `test_invalid_source_reference_is_rejected` |
| `FINDING` | YES | `source_id` required; validated against `find_inspection_finding`; **the Finding is read-only, never mutated** | `test_finding_source_links_to_repair_without_mutating_the_finding` — independently re-read: creates a repair linked to a finding, then re-fetches the original inspection detail and asserts it is byte-for-byte unchanged |
| `PM_RESULT` | YES | `source_id` required; validated against `find_pm_work_result` | `test_pm_result_source_linkage_supported` |
| `ALERT` | **Interface-ready only, not fully valid** — correctly disclosed | `source_id` required by shape, but **not validated against any real record** since no Alert domain exists yet in this repository | `test_alert_source_is_interface_ready_without_an_alert_domain` — the test itself and the module docstring both explicitly disclose this is not a complete integration |

- **FINDING linkage must not mutate the source Finding:** confirmed (see
  table above).
- **Repair must NOT auto-create for every inspection FAIL:** confirmed —
  `test_fail_result_does_not_automatically_create_a_repair`, independently
  re-run, passing; `InspectionService.submit_inspection`
  (Phase 3, untouched by this diff per `git diff fab84e3 748be5c` showing
  only the attachment-delegation refactor) contains no call into
  `RepairService` anywhere.
- **PM_RESULT linkage points to a real PM result when used:** confirmed
  (table above).
- **ALERT may remain interface-ready if Alert domain is not yet
  implemented:** confirmed, and — importantly — **not falsely presented as
  a complete integration**: the module docstring explicitly states "no
  Alert domain exists yet... nothing here validates it against a real
  alert record," and the dedicated test's own name says
  "interface-ready... without an alert domain." This is exactly the
  disclosure the audit brief asks to check for.
- **Invalid/nonexistent source references are rejected where validation is
  possible:** confirmed — `test_invalid_source_reference_is_rejected`
  covers `FINDING`/`INSPECTION_RESULT`/`PM_RESULT` with a nonexistent ID,
  all correctly rejected with `REPAIR_SOURCE_NOT_FOUND` (422).

**No defect found**, and no placeholder was misrepresented as complete.

---

## L. Finding → Repair Audit

F02 remains unresolved (Section B). Specifically verified Phase 4 did
**not** permanently decide:

- **One Finding = one Repair:** NOT decided — nothing prevents linking a
  second repair to the same finding; no uniqueness constraint exists on
  `(source_type, source_id)` in `MockRepository._repairs` or anywhere else.
- **Many Findings = one Repair:** NOT decided — a repair carries exactly
  one `source_id`, so this shape isn't even representable yet, but nothing
  claims this is the final design either.
- **Duplicate Repair behavior:** NOT decided — no dedup check exists.
- **Approval-before-Repair behavior:** NOT decided — `create_repair` has no
  approval/review step of any kind.

The implementation supports a simple linkage **API** only
(`source_type`+`source_id`, existence-validated, non-mutating) — confirmed
as capability-only, not a frozen business rule, by the complete absence of
any uniqueness/approval/conversion code path in `RepairService`.

**No defect found.**

---

## M. Repair Closure Audit

F03 remains unresolved (Section B). Verified `RepairService.close_repair`
(full method body read directly) requires **none** of:

- required close note — `close_note: str | None`, no non-null/non-empty
  check
- required technician — `closed_by` comes from `RequestContext.user_id`
  automatically (dev-auth's fixed user), never validated as "must be set
  to a real distinct technician"
- required photo — no check against `repair.actions`/attachments at close
  time
- required part — no check against `RepairPart` records at close time
- required approval — no second-actor/approval-state check anywhere
- required signature — no such concept exists in the codebase at all

`test_close_repair_requires_no_unapproved_fields` independently confirms a
repair with zero actions and zero parts closes successfully. No closure
requirement was traced to an approved source because none exists — this is
correctly the "as minimal as possible" default, not a hidden invented
rule.

**No defect found.**

---

## N. Phase 3 Integrity

| Check | Result | Evidence |
|---|---|---|
| Submitted inspection not mutated | YES | `git diff fab84e3 748be5c -- backend/app/domain/inspection_service.py` shows only attachment-method bodies replaced with delegation to `AttachmentService`; `submit_inspection`/inspection read paths are untouched |
| Checklist revision history not mutated | YES | `checklist.py` does not appear in the Phase 4 diff at all |
| Finding history not mutated | YES | `InspectionFinding` is only ever read by `RepairService` (`find_inspection_finding`), confirmed by grep — no write call anywhere |
| Evidence attachments not mutated | YES | `AttachmentService` extraction is a pure refactor: same `StorageProvider` calls, same validation, same filename sanitization, confirmed identical to the pre-extraction logic by direct diff read |
| Reference images not mutated | YES | `AttachmentPurpose.CHECKLIST_REFERENCE_IMAGE` untouched; two new members (`PM_EVIDENCE`, `REPAIR_EVIDENCE`) added additively |
| Repair linkage references Phase 3 records without rewriting them | YES | Confirmed in Section K/L |
| All 95 pre-existing Phase 1–3 backend tests still pass, unmodified | YES | Part of the 141/141 total re-run in Section U — independently confirmed by running the full suite, not by trusting the report's count |

**No defect found.** The one Phase 3 file with a body change
(`inspection_service.py`) is confirmed to be a behavior-preserving
refactor, not a functional change, both by direct diff read and by every
pre-existing Phase 3 test still passing unmodified.

---

## O. Asset / Component Integrity

| Check | Result | Evidence |
|---|---|---|
| VEHICLE and EQUIPMENT remain distinct | YES | `require_asset_exists` branches explicitly on `AssetType`, preserving distinct `VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND` codes (mirrors Phase 3's `InspectionService._require_asset` exactly, confirmed by direct comparison) |
| Shared asset reference does not merge identities | YES | No code path merges a vehicle and equipment record under one type; `AssetType`/`asset_id` pairs stay type-discriminated everywhere in PM/Repair |
| `EquipmentOperationalStatus` remains separate from Vehicle `OperationalStatus` | YES | Neither is read or written anywhere in Phase 4 code (grep-confirmed: zero references to either enum in `pm.py`/`pm_service.py`/`repair.py`/`repair_service.py`/`meter*.py`) |
| `CARRIER_ENGINE`/`CRANE_ENGINE`/`PTO` vocabulary remains authoritative | YES | `MeterService` reads `VehicleComponent.component_role` via Phase 2's existing `list_vehicle_components`, without redefining or duplicating the enum |
| `ENGINE_MAIN`/`ENGINE_SECONDARY` were not reintroduced | YES | `grep -rn "ENGINE_MAIN\|ENGINE_SECONDARY" backend/app frontend/src` → no matches in application code (only in historical verification reports and the naming-correction's own deprecation notes, unchanged from before Phase 4) |
| Permanent QR routes unchanged | YES | `git diff fab84e3 748be5c -- frontend/src/App.tsx` (Section above) shows `/vehicle/:vehicleId` and `/equipment/:equipmentId` route elements byte-for-byte unchanged; only new nested routes were added |

**No defect found.**

---

## P. Transaction ID Audit

| Identifier | Scheme | Stable? | Row-number-based? |
|---|---|---|---|
| `pm_plan_id` | `PMP-NNNN` (seed-fixed) | YES | NO |
| `pm_task_id` | `PMT-NNNN` (seed-fixed) | YES | NO |
| `pm_task_revision_id` | `PMREV-NNNN` (seed-fixed) | YES | NO |
| `pm_work_order_id` | `PMWO-NNNN`, in-process sequence | YES within a process | NO |
| `pm_work_result_id` | `PMWR-NNNN`, same pattern | YES | NO |
| `pm_used_part_id` | `PMUP-NNNN`, same pattern | YES | NO |
| `meter_snapshot_id` | `MSNAP-NNNN`, same pattern | YES | NO |
| `repair_id` | `RPR-NNNN`, same pattern | YES | NO |
| `repair_action_id` | `RPRA-NNNN`, same pattern | YES | NO |
| `repair_part_id` | `RPRP-NNNN`, same pattern | YES | NO |
| attachment IDs | `ATT-NNNN` (Phase 3, reused unchanged) | YES | NO |

Verified directly in `MockRepository` (Section on mock repo above): every
ID is generated from an in-memory monotonic counter plus a fixed prefix,
never from a dict/list position exposed to the caller, and the declared
Google Sheets schemas (`schemas.py`) map every PM/Repair tab by header name
only — no `row_number`/`row number` string exists anywhere in that file.

- **Frontend does not invent authoritative IDs:** confirmed — every ID used
  by `PmStatusPage`/`PmWorkOrderDetailPage`/`RepairDetailPage`/etc.
  originates from an API response; no `crypto.randomUUID()` or similar
  client-side ID generation exists in any new frontend file.
- **A01 status:** remains `TBD-BLOCKING`, exactly as every prior phase left
  it. Phase 4 continues the same isolated, mock-only, sequential
  `PREFIX-NNNN` convention already established by Phase 2/3 — this is a
  **local convention**, not a global freeze of A01. The pattern is
  consistent across all 10 new ID types, and swapping the *generation
  mechanism* (counter → UUID/DB sequence) later requires no caller-visible
  change, since every caller treats these as opaque strings.
- **A01 is not silently marked globally resolved:** confirmed —
  `OPEN_DECISIONS_REGISTER_EN.txt`'s A01 entry is untouched by this phase
  (register diff is empty, per Section B).

**No defect found.**

---

## Q. Google Sheets / Repository Audit

| Check | Result | Evidence |
|---|---|---|
| All Phase 4 access remains behind Repository | YES | `PmService`/`RepairService`/`MeterService` depend only on the `Repository` ABC (constructor injection), never a concrete implementation |
| Browser never accesses Google Sheets directly | YES | No Google API code exists anywhere in `frontend/` |
| Google Sheets schema uses stable headers | YES | `pm_plans`, `pm_task_revisions`, `pm_tasks`, `pm_task_parts`, `pm_work_orders`, `pm_work_results`, `pm_used_parts`, `meter_snapshots`, `meter_readings`, `repairs`, `repair_actions`, `repair_parts` all declared with named header columns |
| No row-number identity | YES | Confirmed (Section P) |
| No fake claim of live integration if credentials are unavailable | YES | `GoogleSheetsRepository`'s new Phase 4 methods follow the identical "declared schema + controlled `RepositoryError`/`NotImplementedError`" pattern as every prior phase; `validate_schema()` still unconditionally raises `NotImplementedError` (unchanged, confirmed not present in the diff) |
| MockRepository remains usable | YES | All 46 new backend tests run against `MockRepository` with zero external dependency; `DATA_REPOSITORY=mock python -m pytest` — 141/141 passed (Section U) |
| PostgreSQL migration remains feasible | YES | No new code depends on Python dict/list in-memory semantics beyond `MockRepository`'s own implementation; all callers depend on the `Repository` ABC |
| Multi-row operations are not assumed atomic if using Sheets | YES | No live Sheets write path exists to make this assumption in the first place; A09 (concurrency/optimistic locking) remains untouched and unresolved, same as every prior phase |

**No defect found.**

---

## R. Security / Attachment Review

| Check | Result | Evidence |
|---|---|---|
| StorageProvider abstraction reused, not weakened | YES | `AttachmentService` (new, shared) wraps the exact same `StorageProvider.save`/`read` calls Phase 3 used; `PM_EVIDENCE`/`REPAIR_EVIDENCE` are additive `AttachmentPurpose` members, no new upload/download route was created |
| Safe filename/path handling | YES | `safe_filename()` (moved verbatim from `inspection_service.py`, confirmed by direct code comparison) strips path components and unsafe characters identically to Phase 3's corrected behavior |
| Configurable upload validation | YES | Same `Settings.attachment_allowed_content_types`/`attachment_max_size_bytes` as Phase 3's correction, reused (not reimplemented) via `AttachmentService` |
| No binary data in database/Sheets | YES | Same `storage_ref`-only pattern; declared `pm_work_results`/`repair_actions` schemas have no binary column |
| M07 remains unresolved | YES | `.env.example`/code comments still explicitly label these as "LOCAL-DEVELOPMENT DEFAULTS ONLY"; `OPEN_DECISIONS_REGISTER_EN.txt` M07 entry untouched |
| No production upload policy silently frozen | YES | Same disclosure language carried forward verbatim from Phase 3's correction |
| No secrets committed | YES | `git diff fab84e3 748be5c --stat` shows no `.env`/credential-shaped file added; repo-wide secret-pattern search (same method as every prior phase's security review) found nothing new |

**No defect found.** Phase 4 reuses, rather than reimplements or weakens,
Phase 3's corrected attachment security boundary.

---

## S. Mobile / Responsive Review

Independently re-executed in this session (Section U) across all 5
required viewport projects — 110/110 Playwright tests passed, including
25 new results from `frontend/e2e/pm-repair.spec.ts` (5 tests × 5
viewports).

| Area | Result | Evidence |
|---|---|---|
| PM summary readable | YES | `PmStatusPage` uses the frozen `Card` primitive; e2e asserts it renders at all 5 viewports |
| Work-order/task cards usable | YES | `PmTaskCard` mirrors `ChecklistItemCard`'s card-per-item pattern (large buttons, no dense table) |
| Meter snapshots readable | YES | `MeterSnapshotFields` renders one full-width input per reading with an explicit "leave blank if unknown" hint |
| Actual parts entry usable without a wide table | YES | `PartRowsEditor` — confirmed by direct source read (Section above) to render one stacked card per part, never a multi-column table |
| PM history readable | YES | `PmWorkOrderHistoryPage` reuses `ResponsiveTable` (Phase 1's stacked-card-below-641px pattern) |
| Repair create/report usable on phone | YES | `RepairCreatePage` uses `FormField`/`sticky-actions`; e2e "Repair: report a MANUAL repair..." passes at all 5 viewports |
| Source visible | YES | `RepairCreatePage`/`RepairDetailPage` both render `repairSourceTypeLabel` + locked source hint |
| Action history readable | YES | Plain `<ul>`/`<li>` list, no dense table |
| Part entry mobile-friendly | YES | Same stacked-field pattern as PM (`RepairDetailPage`'s inline part form) |
| Attachments mobile-friendly | YES | `capture="environment"` file input, same pattern as Phase 3 |
| No unintended horizontal scroll | YES | `responsive-shell.spec.ts`'s scroll-width assertion, re-run and passing at all 5 viewports, on pages that now include PM/Repair navigation links |
| No hover-only required action | YES | All new interactive elements are `<button>`/`<a>`/form controls |
| Touch targets usable | YES | `.button` class (44px `--tap-target`, Phase 1 frozen CSS) reused unmodified by every new PM/Repair button |
| Thai text wraps correctly | YES | Global `overflow-wrap: break-word` (Phase 1, untouched) applies to all new pages; new CSS in `index.css` only adds layout rules (`.part-rows-editor*`, `.status-card__row`), no `white-space: nowrap` introduced (confirmed by reading the diff) |

**No defect found.**

---

## T. Phase 5 Contamination Audit

Repository-wide search:

```
$ grep -rniE "position_lifetime|instance_tracked|part_instance|tracking_mode|usage_segment|overhaul" backend/app frontend/src
```

Result: **no matches** in any Phase 4 (or earlier) application code. The
only place these terms exist at all is in governance/prompt documents
(`OPEN_DECISIONS_REGISTER_EN.txt`, baseline doc) as Phase 5 concept names,
and in `pm.py`/`repair.py`'s own docstrings explicitly *disclaiming* them
("No `part_id` linking to a part master exists yet — that is Phase 5
scope").

- **POSITION_LIFETIME / INSTANCE_TRACKED lifecycle:** NOT implemented —
  confirmed.
- **part_instance transfer:** NOT implemented — `PmUsedPart`/`RepairPart`
  have no `part_instance_id` field at all.
- **usage segment tracking:** NOT implemented.
- **overhaul lifecycle reset:** NOT implemented.
- **lifetime due calculations:** NOT implemented (there is no due
  calculation of any kind yet, PM or lifetime).
- **component lifetime accumulation:** NOT implemented.
- **physical-instance transfer history:** NOT implemented.

The only forward-compatible interface choice is `part_description: str`
free text with no `part_id` — this is the **minimal shape that avoids
blocking Phase 5**, not an implementation of Phase 5 itself, exactly as
the result report claims and as independently confirmed by reading all
three part model definitions.

**No Phase 5 logic found. No blocking finding.**

---

## U. Automated Verification

All commands below were executed directly, from scratch, in this
session — a fresh `python -m venv`, a fresh `npm install`, and the full
Playwright suite — not copied from the phase report's claimed numbers.

**Backend — pytest**
```
$ cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
$ DATA_REPOSITORY=mock python -m pytest -q
141 passed, 20 warnings in 4.12s
```
**Matches the phase report's claimed 141/141 exactly.** (20 warnings are
the pre-existing `HTTP_422_UNPROCESSABLE_ENTITY` Starlette deprecation
notice, same category present since Phase 1 — not a new issue.)

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npm install && npx vitest run
Test Files  21 passed (21)
     Tests  44 passed (44)
```
**Matches the claimed 44/44 exactly.**

**Frontend — typecheck**
```
$ npx tsc -b
(exit code 0 — PASSED)
```

**Frontend — lint**
```
$ npx oxlint
11 warnings, 0 errors — all react(set-state-in-effect), the same
pre-existing category present since Phase 1, now also on the 6 new
PM/Repair pages. No new warning category introduced.
```

**Frontend — production build**
```
$ npm run build
dist/index.html                   0.43 kB │ gzip:  0.30 kB
dist/assets/index-*.css          10.02 kB │ gzip:  2.47 kB
dist/assets/index-*.js          334.80 kB │ gzip: 96.90 kB
✓ built in 516ms
```
**Matches the claimed sizes exactly.**

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
110 passed (57.4s)
```
Ran across `smartphone-portrait`, `smartphone-landscape`,
`tablet-portrait`, `tablet-landscape`, `desktop`. **Matches the claimed
110/110 exactly** (85 pre-existing Phase 1–3 tests + 25 new: 5
`pm-repair.spec.ts` tests × 5 viewport projects).

**Summary**

| Suite | Result | Matches phase report's claim? |
|---|---|---|
| Backend pytest | 141/141 passed | YES |
| Frontend Vitest | 44/44 passed (21 files) | YES |
| Frontend typecheck (`tsc -b`) | PASSED | YES |
| Frontend lint (`oxlint`) | PASSED (11 pre-existing-category warnings, 0 errors) | YES |
| Frontend production build | PASSED | YES |
| Playwright e2e (5 viewports) | 110/110 passed | YES |

No test was skipped, disabled, or hidden in this verification. No claimed
result in the phase report was found to be false — every number matches
an independent, from-scratch re-run in this session.

---

## V. Manual Acceptance Plan

Run with `./scripts/run_dev.sh` (or `run_backend.sh` + `run_frontend.sh`),
`DATA_REPOSITORY=mock`, at `http://127.0.0.1:5173`.

1. **Open Vehicle PM**
   - Prerequisite: dev servers running.
   - Action: open `/vehicle/VEH-1046`, tap "PM".
   - Expected: PLAN1 card shows its Thai example-data name, "รุ่นรายการงานปัจจุบัน: รุ่นที่ 1", "ยังไม่มีประวัติ", and "ไม่สามารถคำนวณได้ในขณะนี้" for due status, plus the E02/E03/E04 note.
   - Failure evidence: screenshot + Network tab for `GET /api/v1/pm/plans/status?...`.

2. **Open Equipment PM (empty state)**
   - Action: open `/equipment/EQP-0001`, tap "PM".
   - Expected: "ยังไม่มีแผนบำรุงรักษาที่ใช้งานสำหรับสินทรัพย์นี้" (no fabricated equipment plan).
   - Failure evidence: screenshot; confirm no plan card renders.

3. **Create/open PM work order**
   - Action: from step 1, tap "เริ่มทำ PM".
   - Expected: navigates to `/pm/work-orders/PMWO-...` with 3 placeholder task cards, none completed.
   - Failure evidence: screenshot + `POST /api/v1/pm/work-orders` request/response.

4. **Multiple PM task results**
   - Action: submit all 3 tasks in sequence.
   - Expected: each becomes read-only after submission; attempting to resubmit the same task is not offered in the UI, and a direct API retry returns `PM_TASK_RESULT_ALREADY_EXISTS`.
   - Failure evidence: screenshot after each submission + the 422 response if retried via devtools/curl.

5. **Meter snapshot**
   - Action: on a task, fill in a component-scoped reading (e.g. CARRIER_ENGINE ENGINE_HOUR) and the ODOMETER field, submit.
   - Expected: "บันทึกค่ามาตรวัดแล้ว" appears on the completed task card.
   - Failure evidence: screenshot + `POST /api/v1/meter-snapshots` response.

6. **Unknown meter value**
   - Action: leave a meter field blank when submitting a task.
   - Expected: no value is sent for that reading (or `null`); the field is never silently treated as `0`. Verify via `GET /api/v1/meter-snapshots/{id}` that the reading's `value` is `null`, not `0`.
   - Failure evidence: raw JSON response showing `value`.

7. **Standard vs actual parts**
   - Action: add an actual part on a PM task via "+ เพิ่มอะไหล่ที่ใช้"; afterwards, fetch `GET /api/v1/pm/plans/PMP-0001/active-revision` and confirm the task's `standard_parts` is still `[]`.
   - Expected: the actual part appears only in the work result, never in the task's standard-parts list.
   - Failure evidence: both JSON responses side by side.

8. **PM history**
   - Action: after closing the work order, open `/vehicle/VEH-1046/pm/history`.
   - Expected: the closed work order appears with status "ปิดงานแล้ว".
   - Failure evidence: screenshot + `GET /api/v1/pm/work-orders?...` response.

9. **Create MANUAL repair**
   - Action: from Vehicle Detail, tap "แจ้งซ่อม", fill "อาการ/ปัญหาที่พบ", submit.
   - Expected: navigates to repair detail, status "กำลังดำเนินการ" (OPEN), source "แจ้งซ่อมด้วยตนเอง" (MANUAL).
   - Failure evidence: screenshot + `POST /api/v1/repairs` response.

10. **Create Repair from Finding linkage**
    - Prerequisite: an inspection submitted with at least one FAIL.
    - Action: open the inspection detail page, tap "แจ้งซ่อม" next to the finding.
    - Expected: repair-create page shows source locked to "ข้อบกพร่องจากการตรวจเช็ค" with the finding ID; after submitting, the repair detail page shows the same source.
    - Failure evidence: screenshot before/after + both API responses.

11. **Confirm Finding not mutated**
    - Action: after step 10, re-open the original inspection detail page.
    - Expected: the finding's title/text/status is byte-for-byte unchanged from before the repair was created; no "linked repair" field was retroactively added to the finding record itself (the link exists only on the Repair side).
    - Failure evidence: diff the `GET /api/v1/inspections/{id}` response before and after.

12. **Append Repair action**
    - Action: on the open repair, add two actions in sequence.
    - Expected: both remain visible afterward, in order, neither overwritten.
    - Failure evidence: screenshot after each addition.

13. **Add Repair part**
    - Action: add a part with quantity/unit.
    - Expected: appears in "อะไหล่ที่ใช้จริง" list immediately.
    - Failure evidence: screenshot + `POST /api/v1/repairs/{id}/parts` response.

14. **Attachment/photo**
    - Action: attach a photo to a repair action (camera on a real phone).
    - Expected: uploads successfully, appears attached to that action.
    - Failure evidence: screenshot + `POST /api/v1/attachments` response.

15. **Repair history**
    - Action: open `/vehicle/VEH-1046/repairs`.
    - Expected: the created repair(s) appear, newest first.
    - Failure evidence: screenshot + `GET /api/v1/repairs?...` response.

16. **Unknown/invalid source reference**
    - Action: `curl -X POST /api/v1/repairs` with `source_type=FINDING`, `source_id=FND-9999` (nonexistent).
    - Expected: `422 REPAIR_SOURCE_NOT_FOUND`, no repair created.
    - Failure evidence: raw response body.

17. **Inspection still works (regression)**
    - Action: run a full inspection submission on `VEH-1046`.
    - Expected: works identically to Phase 3's own verified behavior; no PM/Repair UI intrudes on this flow.
    - Failure evidence: screenshot + compare against Phase 3's own manual test result.

18. **Vehicle/equipment details still work (regression)**
    - Action: open `/vehicle/VEH-1046` and `/equipment/EQP-0001`.
    - Expected: all Phase 2/3 sections (identity, model, components, status history, inspection links) render exactly as before, with the new PM/แจ้งซ่อม/ประวัติการซ่อม buttons added alongside, not replacing anything.
    - Failure evidence: screenshot.

19. **QR routes unchanged (regression)**
    - Action: confirm `/vehicle/{vehicle_id}` and `/equipment/{equipment_id}` still resolve directly with no PM/repair ID anywhere in the path.
    - Failure evidence: screenshot of the URL bar.

20. **Smartphone and desktop tests**
    - Action: repeat steps 1–15 at a phone width (~375px, both orientations) and at ≥1280px desktop width.
    - Expected: no horizontal scrolling, parts render as stacked cards (not tables) on mobile, all primary buttons ≥44px tall; desktop shows the same information with more breathing room.
    - Failure evidence: screenshot in the failing viewport/orientation.

---

## W. Final Verdict

# PASS WITH KNOWN LIMITATIONS

**Blocking defects:** None. Every mandatory Phase 4 SCOPE item is
implemented and independently re-verified; all automated suites were
independently re-executed from scratch in this session and matched the
phase report's claims exactly (backend 141/141, frontend unit 44/44,
typecheck/lint/build clean, Playwright 110/110 across all 5 required
viewport bands). No frozen Phase 1–3 contract was changed (the one touched
file, `inspection_service.py`, is a confirmed behavior-preserving
refactor). No approved component-role contract was changed. No Phase 5
logic was found.

**Known limitations (disclosed, non-blocking, all correctly the product of
an unresolved governance decision rather than an implementation defect):**
- PM due/remaining/overdue is not calculated at all — `due_status` is
  always `"UNKNOWN"` (E02/E03/E04 unresolved, correctly so).
- Only `PLAN1` has any task content, and it is placeholder/example data
  only (E05) — not usable as a real maintenance procedure.
- No PM-authoring UI exists (creating/editing plans, task revisions, or
  standard parts) — Phase 4 only consumes seed data, matching the Phase 3
  precedent for checklists.
- `PmWorkOrderStatus`/`RepairStatus` have only `OPEN`/`CLOSED` (E01/F01
  unresolved) — no `IN_PROGRESS`, assignment, or cancellation state.
- No correction/void workflow exists for a submitted `PmWorkResult` or a
  posted `RepairAction` (same D04-style precedent Phase 3 established —
  not approved, not built).
- Repair `category`/`symptom` are free text; no approved category
  vocabulary exists.
- Equipment has no counter/component model (C03 deferred) — PM/Repair
  meter capture is vehicle-only, correctly so.
- `RepairSourceType.ALERT` is interface-ready only; no Alert domain exists
  to validate against yet — correctly disclosed, not presented as complete.
- Same A01 (transaction ID) caveat as every prior phase: IDs are opaque
  and stable, but the *generation mechanism* is an in-memory sequential
  counter, not yet a cross-storage strategy.
- All limitations already disclosed in Phase 1–3's own verifications
  remain accurate and unaffected by Phase 4: `GoogleSheetsRepository`'s
  methods are interface/schema-only, no RBAC beyond `DEV_AUTH_MODE`, M07
  (upload limits/MIME/malware scanning) remains an explicitly-labeled
  local-development default only.

**Unapproved decisions found:** None. Every E01–E05/F01–F03 item was left
correctly unresolved, each with an explicit, code-level disclosure (module
docstrings naming the exact blocking decision) and a passing test proving
the placeholder behavior rather than a hidden permanent rule.

**E01 status:** Unresolved, correctly so — provisional `OPEN`/`CLOSED` placeholder, no transition matrix.
**E02 status:** Unresolved, correctly so — no warning-window value exists anywhere.
**E03 status:** Unresolved, correctly so — `last_completed_*` is a fact, never a computed baseline.
**E04 status:** Resolved per the register's own explicit rule ("never treat unknown as zero") — not a new decision; proven never to coerce `null` to `0`.
**E05 status:** Unresolved, correctly so — only PLAN1 has a master record; PLAN2/3/4 do not exist at all.

**F01 status:** Unresolved, correctly so — provisional `OPEN`/`CLOSED` placeholder, identical reasoning to E01.
**F02 status:** Unresolved, correctly so — linkage capability exists; no 1:1/dedup/approval rule was invented.
**F03 status:** Unresolved, correctly so — no mandatory closure field of any kind exists.

**PLAN2/3/4 fabricated:** NO
**Unknown counter converted to zero:** NO
**Finding auto-creates Repair:** NO
**Repair mutates Finding:** NO
**PM and Repair part concepts remain separate:** YES
**Phase 5 lifetime logic accidentally implemented:** NO
**ENGINE_MAIN/ENGINE_SECONDARY reintroduced:** NO
**Frozen Phase 1–3 contracts changed:** NO
**Component-role contract changed:** NO
**Phase 5 accidentally started:** NO

**Next phase readiness:** READY

Phase 4's core contracts (PM work-order/result model, meter snapshot
contract, source linkage, revision references, backend due-status
interface) are stable, every governance decision Phase 4 touches is
correctly left open rather than guessed, and every automated test claim
was independently reproduced. Phase 5 (Part/Lifetime) may proceed when the
user directs it.

---

This is an audit only. Phase 5 was not started. No frozen Phase 1–3
contract was changed. No open business decision (E01–E05, F01–F03, or any
other) was resolved. No test was hidden. No unrelated feature was added.

STOP HERE. Do not begin Phase 5.
