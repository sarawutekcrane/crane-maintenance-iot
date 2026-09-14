# Web/API Phase 5 — Parts / Lifetime / Transfer — Post-Phase Verification Report

STATUS: AUDIT ONLY. No Phase 6 work was started, no Phase 1–4 architecture
was redesigned, no open governance decision (G01–G06, A01–A03, or any
other) was resolved or silently marked approved, no test was hidden, and
no frozen contract was changed as part of this verification.

**Process note:** as with the Phase 4 verification, this task's local
checkout of `web/phase-05-parts-lifetime` initially had no Phase 5 code —
only Phase 4 plus its own verification report. `git fetch`/`git pull
origin web/phase-05-parts-lifetime` retrieved a newer commit, `2fdabf5`
("Implement Web/API Phase 5: Parts, Lifetime, and Transfer"), which is the
actual Phase 5 implementation. This report verifies **`2fdabf5`**, not the
stale local state this session started from.

Documents read in full before verifying, as required:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/05_PHASE5_PARTS_LIFETIME_TRANSFER_EN.txt`
- `docs/phase-results/web-phase-01-verification.md`, `web-phase-02-verification.md`,
  `web-phase-03-verification.md`
- `docs/phase-results/component-role-naming-correction.md`,
  `component-role-naming-verification.md`
- `docs/phase-results/web-phase-04-result.md`, `web-phase-04-verification.md`
- `docs/phase-results/web-phase-05-result.md`

Plus direct reading of the actual `2fdabf5` diff/source (not only the
result report's prose): `app/domain/part.py`, `part_instance.py`,
`position_lifetime.py`, `lifetime_rule.py`, `part_lookup.py`,
`part_service.py`, `part_instance_service.py`,
`position_lifetime_service.py`, `lifetime_rule_service.py`, the
`pm.py`/`pm_service.py`/`repair.py`/`repair_service.py` diffs, the
`Repository` ABC diff (`base.py`), the `MockRepository`/seed-data diff,
the declared Google Sheets schemas/repository stub diff, the new API
routers/schemas, the frontend Phase 5 pages/components and their tests,
the `frontend/e2e/parts-lifetime.spec.ts` suite, and a repo-wide grep for
governance-sensitive terms — plus an independent, from-scratch
re-execution of every automated suite in this session (Section Y).

---

## A. Requirement Traceability

| Requirement (Phase 5 SCOPE) | Implemented | Evidence file/module | Automated test evidence | Manual test needed | Notes |
|---|---|---|---|---|---|
| Part Master, tracking modes NONE/CONSUMABLE/POSITION_LIFETIME/INSTANCE_TRACKED | YES | `app/domain/part.py` (`TrackingMode`, `PartMaster`) | `test_seeded_parts_cover_every_tracking_mode` | No | |
| `tracking_start_policy` | NOT_APPLICABLE (correctly not built) | No such field/endpoint exists | N/A | No | No due/warning calculation exists at all (G01/G02 unresolved), so a policy describing *when* tracking starts relative to a threshold has nothing to attach to yet; enrollment itself is on-demand per baseline §12, which is implemented (see Part Instance/Position Lifetime rows below). Not flagged as a gap — the phase's own SCOPE item 2 is bare "tracking_start_policy" with no acceptance test naming it, and Section 23 of the result report does not claim it exists. |
| Part Set / Kit revision, REQUIRED/OPTIONAL/ALTERNATIVE | YES | `app/domain/part.py` (`PartSet`, `PartSetRevision`, `PartSetItem`, `PartSetItemRequirement`) | `test_part_set_revision_supports_required_optional_alternative`, `test_later_part_set_revision_does_not_rewrite_earlier_one`, `test_part_set_revision_requires_valid_part_ids` | No | |
| Standard parts vs actual parts | YES | `PmTaskPart` (standard, untouched) vs `PmUsedPart`/`RepairPart` (actual, additively extended) | `test_linking_actual_pm_part_does_not_alter_standard_task_part_definition`, `test_standard_pm_part_actual_pm_part_and_repair_part_remain_distinct_concepts` | No | |
| PM/Repair actual actions CONSUMED/INSTALLED/REMOVED/SERVICED | YES (metadata only) | `PartActionType` on `PmUsedPart`/`RepairPart` | covered by `test_pm_repair_part_linkage.py` | No | Purely descriptive — recording `action=INSTALLED` does not itself create an `InstallationSegment`; a real install still goes through `PartInstanceService.install` (see module docstring, `part.py:78-91`) |
| Lifetime rules ENGINE_HOUR/PTO_HOUR/ODOMETER/CYCLE/CALENDAR, FIRST_DUE | YES (structure only) | `app/domain/lifetime_rule.py` (`LifetimeTriggerType`, `LifetimeRule.first_due_value`) | `test_engine_hour_trigger_requires_explicit_component_role`, `test_no_real_lifetime_interval_is_seeded_for_any_part` | No | No due/remaining calculation reads these fields anywhere (correct — G01/G02 unresolved) |
| Model rule + future vehicle override | YES (structure only) | `LifetimeRuleScope.MODEL`/`VEHICLE`, `model_id`/`vehicle_id` | `test_model_rule_created_with_explicit_component_role`, `test_vehicle_override_rule_created`, `test_vehicle_override_rule_requires_vehicle_id` | No | No override-precedence resolution implemented — correctly none needed since no calculation exists |
| Do not invent real model/part lifetime rules | YES | Zero `LifetimeRule` records in seed data; every numeric field defaults to `None` | `test_no_real_lifetime_interval_is_seeded_for_any_part` | No | See Section K |
| On-demand `part_instance` | YES | `PartInstanceService.create_instance`, `POST /part-instances` | `test_create_instance_on_demand_with_stable_identity`, `test_instance_can_only_be_created_for_instance_tracked_part` | No | No instance pre-seeded (Section D) |
| Historical prior-usage status KNOWN/PARTIAL/UNKNOWN | YES | `app/domain/part_instance.py` (`PriorUsageQuality`, `PriorUsage`) | `test_prior_usage.py` (5 tests, all re-run) | No | See Section J |
| Installation/usage segments | YES | `InstallationSegment` (append-oriented) | `test_transfer_between_vehicles_preserves_previous_segment_and_does_not_reset_usage`, `test_remove_into_in_repair_closes_active_segment_and_stops_host_accumulation` | No | See Section O |
| Component-aware counters | YES (reused, not reimplemented) | `LifetimeRule.component_role` reuses Phase 2's `ComponentRole`; baseline/removal snapshots reuse Phase 4's unchanged `MeterService` | `test_engine_hour_trigger_requires_explicit_component_role` | No | No new counter-validation logic was written — the existing `MeterService.require_snapshot_exists` is the sole authority |
| Transfer between vehicles without usage reset | YES | `PartInstanceService.transfer` (close+open within the same lifecycle) | `test_transfer_between_vehicles_preserves_previous_segment_and_does_not_reset_usage` | Yes — real phone/tablet workflow | See Section F |
| IN_REPAIR does not add operating hours | YES (structurally, by the absence of an active segment) | `remove(..., next_status=IN_REPAIR)` closes the active segment; no code path infers host usage without one | `test_remove_into_in_repair_closes_active_segment_and_stops_host_accumulation` | No | See Section G |
| Normal repair does not reset lifetime | YES | `remove`→`install` (repair pause) never calls `start_new_part_lifecycle` | `test_normal_repair_does_not_reset_lifetime` | No | See Section H |
| Approved overhaul may create new tracking cycle | YES | `start_new_lifecycle` requires explicit `approved_reason`; never auto-triggered | `test_approved_overhaul_starts_new_cycle_and_preserves_old_history`, `test_start_new_lifecycle_requires_explicit_approved_reason` | No | See Section I |
| Preserve old cycles | YES | Old `PartLifecycle`/its segments remain in `PartInstanceDetail` forever | Same test as above (re-reads the instance after overhaul and confirms both cycles/segments) | No | |
| Different specifications can use different part IDs | YES | `PART-0002`/`PART-0003`, same display name, different `specification` | `test_same_display_name_different_specification_gets_different_part_id` | No | |
| No preload of every physical part required | YES | Only 5 example `PartMaster` records seeded; zero `PartInstance`/`PositionLifetimeRecord`/`LifetimeRule`/`PartSetRevision` seeded | Seed-data read + `test_no_real_lifetime_interval_is_seeded_for_any_part` | No | |
| Thai UI for parts/lifetime/transfer | YES | `PartListPage`, `PartDetailPage`, `PartInstanceCreatePage`, `PartInstanceDetailPage`, `AssetPartsPage` | Vitest (8 new) + Playwright (`parts-lifetime.spec.ts`, 5 tests × 5 viewports) | Yes — native-Thai-speaker read-through | |

**Traceability verdict:** every mandatory Phase 5 SCOPE item is present,
correctly scoped, and evidenced by a real, independently re-executed
automated test. The one NOT_APPLICABLE (`tracking_start_policy`) is a bare
phase-prompt phrase with no dedicated acceptance test and no result-report
claim of a distinct implementation — its underlying need (on-demand
enrollment) is satisfied by the Part Instance / Position Lifetime
mechanics themselves.

---

## B. Open-Decision / Guessing Audit

| Decision | Current implementation behavior | Permanent rule or replaceable placeholder/interface? | Explicitly approved? | Risk | Required action |
|---|---|---|---|---|---|
| **G01** Real Lifetime Rules | `LifetimeRule.first_due_value`/`interval_value` exist as optional fields; zero `LifetimeRule` records are seeded; every test that sets a non-`None` value is disclosed test-only data. No due/remaining calculation reads these fields anywhere (grep-confirmed: no function computes "remaining"/"due" from a `LifetimeRule`). | Replaceable structural placeholder, explicitly documented as such in `lifetime_rule.py`'s module docstring. | NO | Low today — nothing consumes these fields for a real decision. | None for Phase 5. Must be resolved (with an authoritative source: model+part+spec+position) before any due/remaining/warning feature is built. |
| **G02** Lifetime Warning Windows | `LifetimeRule.warning_window_value` exists as an optional field, always `None` outside test-only data; nothing computes a warning state from it anywhere in backend or frontend (grep-confirmed: no `warning`/`grace_period`/percentage threshold constant exists in application code). | Replaceable structural placeholder. | NO | None found. | None for Phase 5. |
| **G03** Position Code Master | `PositionLifetimeRecord.position_code: str` is free text; no enum, no seeded vocabulary, no validation against a master list. Frontend label is generic ("ตำแหน่ง (position code)"); e2e test uses an obviously synthetic value (`BOOM-CYL-E2E-<viewport>`). | Replaceable — a real master list could later replace the free-text field or add validation without changing the record shape. | NO | Low — no company-wide position taxonomy was invented; a very small risk is that free-text position codes could drift/typo across records with no correction mechanism (see G06), but this is an accepted, disclosed consequence of not inventing a master list, not a fabricated rule. | None for Phase 5. Must be resolved before "scalable lifetime deployment" per the register's own stated trigger. |
| **G04** Overhaul Reset Rules | `PartLifecycle`/`start_new_lifecycle` provide only the cycle-boundary *architecture*. The endpoint requires a non-empty, freeform `approved_reason` string and refuses to run while the instance is `INSTALLED`; it does **not** evaluate any criterion (hours, cost, repair count, OEM threshold) to decide whether an overhaul is warranted — that judgment is entirely the caller's. | Structural placeholder — the mechanism (a second lifecycle) is permanent architecture, but the trigger criteria for using it are not decided by this phase. | NO | Low — nothing in the implementation could be mistaken for an approved OEM overhaul threshold, since no numeric/temporal criterion exists anywhere in the code path. | None for Phase 5. A real overhaul-qualification rule (if ever wanted) is a separate future decision. |
| **G05** Part Instance Status Transitions | `PartInstanceStatus` declares exactly the six register-named states. `PartInstanceService` enforces only: no duplicate ACTIVE installation, no install of a `SCRAPPED` instance, remove/transfer require currently `INSTALLED`, and `remove`'s `next_status` is restricted to `{REMOVED, IN_REPAIR, STOCK, SCRAPPED}` (never back to `INSTALLED`/`READY_FOR_INSTALL` directly). No company-approved transition matrix or permission model exists. | The register's own status is "PARTIALLY FROZEN" (vocabulary only) — Phase 5 does not change that status; the minimal technical guards above are disclosed in the result report (Section 37, "Risks/Concerns") as *this implementation's own judgment call*, not a sourced rule. | NO (register status unchanged) | Low-to-moderate — the `next_status` allow-list is a reasonable, narrow, non-destructive default, but it is an implementation choice that should be revisited once a real transition policy exists (correctly flagged by the result report itself, independently confirmed true by this audit's direct code read — Section P). | Revisit the `_REMOVAL_NEXT_STATUSES` allow-list the moment G05's transition matrix is approved; not blocking today. |
| **G06** Usage Adjustment Approval | No endpoint anywhere corrects/adjusts `prior_usage`, an accumulated total, or a baseline after creation (grep-confirmed: no `PATCH`/`PUT` route touches `PriorUsage`, `PartInstance`, or `PositionLifetimeRecord`; `InstallationSegment`s are create/close only). | N/A — no capability was built, so there is no "who may correct" question this phase needed to answer. | NO (nothing to approve) | None found — no half-built correction mechanism exists to create ambiguity later. | None for Phase 5. Must be resolved before any correction/adjustment feature is built. |
| **A01** Transaction ID Generation | Continues the exact isolated, mock-only, sequential `PREFIX-NNNN` convention every prior phase established, for 9 new ID types (`PART-`, `PSET-`, `PSREV-`, `PSITEM-`, `PINST-`, `PLC-`, `SEG-`, `POSLT-`, `LTR-`). | Reversible continuation of an already-disclosed local pattern, not a new freeze. | N/A (still `TBD-BLOCKING` per the register) | Low — same standing caveat as every prior phase: swapping the generation *mechanism* later (counter → UUID/DB sequence) requires no caller-visible change, since every caller treats these as opaque strings. | None for Phase 5. |
| **A02** Authoritative Data Source by Field | Untouched. Baseline/removal meter snapshots are validated via the existing, unmodified `MeterService.require_snapshot_exists` — no new authoritative-field-ownership question was introduced. | N/A | N/A | None. | None for Phase 5. |
| **A03** Counter Correction / Reconciliation Policy | Untouched. No counter-correction/reconciliation endpoint of any kind exists in this phase's diff. | N/A | N/A | None. | None for Phase 5. |

**No unapproved permanent business rule was found for G01–G06 or
A01–A03.** Every provisional/placeholder behavior is explicitly documented
in the relevant module's own docstring (not just the phase report's
prose), independently confirmed by reading the actual code in this
session, and proven by a still-passing, independently re-executed test.
`OPEN_DECISIONS_REGISTER_EN.txt` was **not** modified by Phase 5
(confirmed: `git diff 3d6bc43 2fdabf5 --
docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` is empty).

The one item worth carrying forward as a named, non-blocking risk is
**G05's `_REMOVAL_NEXT_STATUSES` allow-list** — a reasonable, disclosed,
minimal engineering default, not a hidden company policy, but it is this
implementation's own judgment call and should be the first thing revisited
once a real transition matrix is approved.

---

## C. Tracking Mode Integrity

| Check | Result | Evidence |
|---|---|---|
| `NONE` does not accidentally gain lifetime tracking | YES | `PART-0001` (`tracking_mode=NONE`) has no instance/position-lifetime concept attached anywhere; `PartInstanceService.create_instance`/`PositionLifetimeService.create` both reject any part whose mode doesn't match exactly (`PART_NOT_INSTANCE_TRACKED`/`PART_NOT_POSITION_LIFETIME`), so a `NONE` part can be enrolled as neither |
| `CONSUMABLE` can be recorded as actual usage | YES | `PmUsedPart`/`RepairPart.part_id` may reference a `CONSUMABLE` part (`PART-0002`/`PART-0003`) via `test_pm_used_part_may_link_to_part_master` — no `tracking_mode` check gates the PM/Repair linkage endpoints themselves (correct — the mode-specific gates belong to the instance/position-lifetime endpoints, not to the free-form actual-part record) |
| `CONSUMABLE` does not require a serialized `PartInstance` | YES | `test_seeded_parts_cover_every_tracking_mode`/frontend `PartDetailPage.test.tsx` confirm no "+ ลงทะเบียนชิ้นงานใหม่" (register instance) action renders for a `CONSUMABLE` part; `PartInstanceService.create_instance` would reject `PART-0002`/`PART-0003` with `PART_NOT_INSTANCE_TRACKED` if attempted directly |
| `POSITION_LIFETIME` can work without `PartInstance` | YES | `PositionLifetimeRecord` has no `part_instance_id` field at all (`position_lifetime.py:28-47`); `test_position_lifetime_requires_no_part_instance` asserts the API response type carries no such field |
| `POSITION_LIFETIME` lifetime belongs to asset+position+rule/baseline | YES | `PositionLifetimeRecord.asset_type`+`asset_id`+`position_code`+optional `lifetime_rule_id`+optional `baseline_meter_snapshot_id` — exactly this shape | Direct model read |
| `POSITION_LIFETIME` does not silently become `INSTANCE_TRACKED` | YES | `PositionLifetimeService.create` explicitly rejects a `part_id` whose `tracking_mode != POSITION_LIFETIME` (`PART_NOT_POSITION_LIFETIME`, 422) — an `INSTANCE_TRACKED` part (`PART-0005`) cannot be enrolled here | `test_instance_tracked_part_rejected_for_position_lifetime` |
| `INSTANCE_TRACKED` has stable physical instance identity | YES | `part_instance_id` (`PINST-NNNN`), generated once, never regenerated | `test_create_instance_on_demand_with_stable_identity` |
| `INSTANCE_TRACKED` history follows the real component | YES | `InstallationSegment` history is keyed by `part_instance_id`, reconstructable across every host asset and every lifecycle | `test_transfer_between_vehicles_preserves_previous_segment_and_does_not_reset_usage` |
| One mode never silently converts to another | YES | Both `create_instance` and `PositionLifetimeService.create` gate on the part's own `tracking_mode` field, which is set once at `PartMaster` creation and never mutated by any endpoint (no `PATCH /parts/{id}` exists at all) | Direct code read — no mutation path for `tracking_mode` exists anywhere |

**No defect found.** All four tracking modes remain distinct, non-collapsing concepts, enforced structurally rather than only documented.

---

## D. Part Master Audit

| Check | Result | Evidence |
|---|---|---|
| Stable `part_id` | YES | `PART-NNNN`, generated once at creation, no update/delete endpoint exists for `PartMaster` at any layer |
| Same display name, different specification → different `part_id` | YES | `PART-0002`/`PART-0003`, identical Thai `name`, `specification="ขนาด A"`/`"ขนาด B"` | `test_same_display_name_different_specification_gets_different_part_id` |
| Part number/spec/manufacturer not fabricated | YES | Every seeded record has `manufacturer=None`, `part_number=None`; only `specification` is set on the two records that need to prove the specification-distinguishes-identity rule | Direct seed-data read |
| `tracking_mode` belongs to the part definition | YES | Field on `PartMaster` itself, not derived elsewhere; set once at creation | `create_part_master` signature |
| No requirement to pre-register every physical component | YES | Only 5 example `PartMaster` rows exist; zero `PartInstance` rows are pre-seeded | Seed-data read (Section 24 of result report, independently confirmed) |
| Incremental/on-demand enrollment preserved | YES | `POST /parts` and `POST /part-instances` are both plain create-on-demand endpoints with no prerequisite catalog | Direct route/service read |

**No defect found.** `PartMaster` is a specification/catalog concept only, never an installed-instance record.

---

## E. Part Set / Kit Revision Audit

| Check | Result | Evidence |
|---|---|---|
| Part set / kit revision is immutable | YES | No update/delete endpoint exists for `PartSetRevision`/`PartSetItem` at any layer; a new revision is a wholly new `create_part_set_revision` call | Direct route/repository read |
| Later revision does not rewrite historical usage | YES | `test_later_part_set_revision_does_not_rewrite_earlier_one` creates revision 1, then revision 2, re-reads revision 1 directly by ID, confirms its items are byte-for-byte unchanged | Independently re-run, passing |
| REQUIRED/OPTIONAL/ALTERNATIVE are structural semantics only | YES | `PartSetItemRequirement` enum with no business logic branching on its value anywhere (grep-confirmed: no code path treats REQUIRED differently from OPTIONAL except as stored/returned metadata) | `test_part_set_revision_supports_required_optional_alternative` |
| No real company kit content fabricated | YES | No `PartSet`/`PartSetRevision` is seeded at all — the feature is fully functional but entirely empty of any content until a caller creates one | Seed-data read confirms zero seeded `PartSet` records |
| No source-less compatibility rules invented | YES | Every `PartSetItem.part_id` is validated only for *existence* (`PART_NOT_FOUND` if missing) — no compatibility/fitment rule (model, vehicle, position) is enforced or implied anywhere | `test_part_set_revision_requires_valid_part_ids`, direct service read |

**No defect found.**

---

## F. Instance-Tracked Component Audit

| Check | Result | Evidence |
|---|---|---|
| Stable `part_instance_id` | YES | `PINST-NNNN`, generated once, no update/delete path for the identity itself |
| Physical component history follows the same instance | YES | All segments/lifecycles are keyed by `part_instance_id`, readable together via `PartInstanceDetail` |
| Installation history append-oriented | YES | `create_installation_segment` only ever inserts a new row; no update/delete path exists for a segment's core fields beyond the single `close_installation_segment` call that sets `removed_at`/status |
| Removal history append-oriented | YES | Same evidence — closing is the only mutation, and it is a one-time, terminal state change on that segment |
| Transfer history reconstructable | YES | `test_transfer_between_vehicles_preserves_previous_segment_and_does_not_reset_usage`: after transfer, both the closed VEH-1046 segment and the new ACTIVE VEH-1047 segment are present and readable in `PartInstanceDetail.segments` |
| Old installation segments remain readable | YES | Same test — the old segment's fields (`asset_id`, `status=CLOSED`) are asserted directly, not merely "not deleted" |
| Transfer to a new vehicle does not reset accumulated usage | YES | `current_lifecycle_id` is asserted unchanged across the transfer in the lifecycle test family; `prior_usage` is asserted unchanged; no counter/total field exists anywhere that could be reset (by design — no usage total is computed at all yet) |
| Duplicate active installation rejected | YES | `test_install_then_duplicate_active_installation_is_rejected` — installing an already-`INSTALLED` instance again returns `422 PART_INSTANCE_ALREADY_INSTALLED` |
| Impossible transfer rejected | YES | `test_transfer_requires_currently_installed` — transferring a never-installed instance returns `422 PART_INSTANCE_NOT_INSTALLED`; `install`/`transfer` both call `require_asset_exists`, so a nonexistent target asset is rejected (`test_install_rejects_invalid_asset`) |
| Removed instance not still treated as actively installed | YES | `remove` closes the active segment and updates `status`; `_active_segment()` (used by both `remove` and `transfer`) scans for `status=ACTIVE` and returns `None` once closed — confirmed directly in `part_instance_service.py:130-134` |

**No defect found.**

---

## G. IN_REPAIR Usage Audit

| Check | Result | Evidence |
|---|---|---|
| No host `ENGINE_HOUR` accumulation while uninstalled | YES (structurally — no accumulation of any counter exists anywhere in the codebase yet) | An instance in `IN_REPAIR` has zero ACTIVE segments (`test_remove_into_in_repair_closes_active_segment_and_stops_host_accumulation` asserts no segment has `status=ACTIVE`, and the frontend e2e test independently asserts "ติดตั้งอยู่ปัจจุบัน" (currently installed) is not shown for any row) |
| No `PTO_HOUR` accumulation while uninstalled | YES | Same evidence — no counter of any kind is computed from segment state anywhere in this phase (there is no due/usage-total calculation at all, correctly, per G01/G02) |
| No `ODOMETER` accumulation while uninstalled | YES | Same evidence |
| No inferred host usage during repair/shop time | YES | No code path reads `IN_REPAIR` status and infers a usage value; `MeterService` is entirely independent of `PartInstanceStatus` |
| Previous accumulated usage is preserved | YES | `prior_usage` on the `PartInstance` record itself is never mutated by `remove`/`install` (only `status`/segments change) — confirmed by direct code read of `remove`/`install`, neither of which touches `self._repository.update_part_instance_status`'s counterpart for `prior_usage` |

**No defect found.** The "no accumulation while uninstalled" guarantee is
structural (falls directly out of "no ACTIVE segment exists"), not a flag
that could be forgotten, exactly as the module docstring claims and as
this audit independently confirmed by reading `part_instance_service.py`
directly rather than trusting the docstring's own claim.

---

## H. Repair vs Lifetime Reset

| Check | Result | Evidence |
|---|---|---|
| Ordinary Repair does NOT reset accumulated lifetime | YES | `test_normal_repair_does_not_reset_lifetime` — remove into `IN_REPAIR` then reinstall leaves `current_lifecycle_id` unchanged and the lifecycle count at 1 |
| Repair action does not create a new lifecycle automatically | YES | `remove`/`install` never call `start_new_part_lifecycle` anywhere in their bodies (direct code read, `part_instance_service.py:136-228`) — only the dedicated `start_new_lifecycle` method does, and only when explicitly invoked by the caller |
| No hidden reset occurs when Repair status changes | YES | Repair (Phase 4) and Part Instance (Phase 5) are entirely separate domains with no code path linking a `Repair`'s status change to any `PartInstance`/`PartLifecycle` mutation — grep-confirmed: `repair_service.py` never imports or calls anything from `part_instance_service.py` |
| No PM/Repair completion silently resets component life | YES | Same evidence — `pm_service.py`'s `submit_task_result`/`close_work_order` never touch `PartInstance`/`PartLifecycle` state; the only Phase 5 linkage from PM/Repair is the optional, read-only `part_id`/`part_instance_id`/`action` metadata fields on the actual-part record itself |

**No defect found.**

---

## I. Overhaul / Lifecycle Boundary

G04 remains unresolved/source-data-required, confirmed in Section B.

| Check | Result | Evidence |
|---|---|---|
| A new lifecycle can be represented | YES | `PartLifecycle.cycle_number` increments; `start_new_lifecycle` creates a second row |
| Old lifecycle remains readable | YES | `test_approved_overhaul_starts_new_cycle_and_preserves_old_history` — re-reads the instance after overhaul (`GET /part-instances/{id}`) and asserts the response is byte-for-byte identical to the overhaul call's own response, with both lifecycles and the old segment intact |
| Overhaul reset requires explicit caller/approved action | YES | `start_new_lifecycle` raises `422 VALIDATION_ERROR` for an empty/whitespace `approved_reason` (`test_start_new_lifecycle_requires_explicit_approved_reason`) |
| No Repair is automatically treated as Overhaul | YES | No code path connects `RepairService` to `PartInstanceService.start_new_lifecycle` at all — the two are only ever joined by a caller manually invoking both, never by one triggering the other |
| No OEM/company overhaul criteria invented | YES | `start_new_lifecycle` evaluates no numeric/temporal/cost criterion — it only checks "is `approved_reason` non-empty" and "is the instance not currently INSTALLED" (`test_cannot_start_new_lifecycle_while_installed`) |
| No real reset thresholds fabricated | YES | No hour/km/count threshold of any kind gates this endpoint |
| A field/action named "overhaul" does not imply automatic approval | YES | The Thai UI action is "เริ่มรอบการใช้งานใหม่ (Overhaul)" and requires an inline form with a free-text reason field before the button is enabled — no default reason is pre-filled, and the backend independently re-validates non-emptiness regardless of what the frontend sends |

**No defect found.** Phase 5 implements only lifecycle *architecture* —
the decision of what counts as an overhaul remains entirely the caller's
judgment call, never inferred or defaulted by the system.

---

## J. Prior Usage / Mid-Life Enrollment

| Check | Result | Evidence |
|---|---|---|
| `KNOWN`, `PARTIAL`, `UNKNOWN` all explicitly supported | YES | `test_instance_prior_usage_known_supported`, `test_instance_prior_usage_partial_supported`, `test_instance_prior_usage_unknown_never_becomes_zero` — all three independently re-run, passing |
| `UNKNOWN` never becomes numeric `0` | YES | Verified end-to-end: domain model (`PriorUsage.value: float \| None`) → `MockRepository` (stores `None` as-is) → API response (`value: null` in JSON) → frontend type (`value: number \| null`) → frontend rendering (`PartInstanceDetailPage.tsx:205-207`/`AssetPartsPage.tsx:213-215`: `quality === 'UNKNOWN' \|\| value === null ? 'ไม่ทราบค่า' : value`, literal Thai "unknown value", never `0`) |
| `UNKNOWN` is not treated as a new component | YES | `UNKNOWN` is accepted identically to `KNOWN`/`PARTIAL` at instance-creation time — no special-casing anywhere treats an `UNKNOWN`-prior-usage instance as "starting fresh" with an implied `0` baseline |
| `PARTIAL` preserves incompleteness | YES | `test_instance_prior_usage_partial_supported` supplies both a known partial `value` (100.0) and an explicit `note` describing what remains unknown ("ทราบเฉพาะช่วงหลังปี 2568... ก่อนหน้านั้นไม่มีข้อมูล") — both fields round-trip unchanged |
| `KNOWN` stores explicit known value only | YES | `test_instance_prior_usage_known_supported` — value + note stored and returned exactly as supplied |
| No guessed previous usage | YES | No code path computes/defaults a `PriorUsage.value` from anything — it is always exactly what the caller supplied, or `None` for `UNKNOWN` |
| UI clearly distinguishes unknown from zero | YES | Confirmed in both `PartInstanceDetailPage.tsx` and `AssetPartsPage.tsx` (Section above); `labels.ts:167-172` carries an explicit comment: "Never render UNKNOWN's value as `0` — always show this label instead" |
| Lifetime calculations do not treat `UNKNOWN` as 0 | YES (vacuously and correctly) | No lifetime/due/remaining calculation exists anywhere in this phase (G01/G02 unresolved), so there is no calculation that could misuse an `UNKNOWN` value — verified by the same grep used in Section K/L finding no due/remaining function anywhere |

**No defect found.** This is the same rigor as Phase 4's E04 (missing-counter) handling, applied consistently to the new `PriorUsage` concept.

---

## K. Lifetime Rule Audit

| Check | Result | Evidence |
|---|---|---|
| Structure supports ENGINE_HOUR/PTO_HOUR/ODOMETER/CYCLE/CALENDAR | YES | `LifetimeTriggerType` enum, all 5 members present |
| FIRST_DUE semantics supported where applicable | YES | `LifetimeRule.first_due_value: float \| None` |
| G01 remains unresolved | YES | Confirmed in Section B |

**Search for real-looking intervals** (executed directly in this session):
```
$ grep -rniE "interval_value\s*=\s*[0-9]|first_due_value\s*=\s*[0-9]|warning_window_value\s*=\s*[0-9]" backend/app
(no matches)
$ grep -rn "LifetimeRule(" backend/app/repositories/mock/seed_data.py
(no matches — zero LifetimeRule records seeded)
```

Every place a non-`None` `interval_value`/`first_due_value` appears is
inside a **test file** (`test_lifetime_rule.py`), never in `seed_data.py`
or any other application code path that a running system would present as
real data. Test values used
(`interval_value=500.0` for an `ENGINE_HOUR`-trigger `test-only` rule in
`test_model_rule_created_with_explicit_component_role`) are round numbers
with no unit/model/spec/position linkage claimed anywhere in the test's
own assertions or docstring — they exist solely to prove the field
round-trips correctly, and are never asserted as a "500-hour service
interval" being real. **No real hour interval, kilometer interval,
calendar interval, cycle limit, replacement limit, or OEM limit was found
anywhere in seed data or application code.**

**Real lifetime intervals fabricated: NO.**

---

## L. Warning Window Audit

G02 remains unresolved, confirmed in Section B.

```
$ grep -rniE "warning_window|grace_period|overdue" backend/app/domain backend/app/api backend/app/repositories/mock/seed_data.py
app/domain/lifetime_rule.py: (field declaration + docstring only)
app/domain/lifetime_rule_service.py: (parameter passthrough only)
app/api/v1/lifetime_rule_schemas.py / lifetime_rules.py: (field passthrough only)
```

No numeric threshold ("100 hours remaining", "10% remaining", "30 days",
a percentage constant, or a grace-period constant) exists anywhere in
`backend/app` or `frontend/src`. `warning_window_value` is a plain
optional `float | None` field with no default other than `None`, never
populated by seed data, and never read by any calculation function
(confirmed by the same repo-wide grep used in Section K — no
`due`/`remaining`/`overdue` computation exists anywhere). The field
remains configurable/unpopulated exactly as the audit brief requires.

**Warning thresholds fabricated: NO.**

---

## M. Position Lifetime Audit

| Check | Result | Evidence |
|---|---|---|
| `POSITION_LIFETIME` does not require serialized `PartInstance` | YES | Confirmed in Section C |
| Position lifetime is scoped to asset + position | YES | `PositionLifetimeRecord.asset_type`+`asset_id`+`position_code` |
| Position history remains reconstructable | YES | `list_position_lifetime_for_asset` returns every record for that asset; `test_list_position_lifetime_for_asset` |
| Baseline is not guessed | YES | `baseline_meter_snapshot_id` is optional and only ever set to a value the caller explicitly supplies and that `MeterService` validates exists (`require_snapshot_exists`) — never inferred/defaulted |
| G03 position-code vocabulary remains unresolved | YES | Confirmed in Section B; `position_code: str` free text, no enum |
| Placeholder position_code values are clearly development/example only | YES | The Playwright e2e test explicitly generates a synthetic, obviously-test value (`BOOM-CYL-E2E-<viewport>`) rather than a realistic-looking company code; no seed data pre-populates any `PositionLifetimeRecord` at all |
| No company-wide position master was silently invented | YES | Zero `PositionLifetimeRecord`s exist in seed data; no enum/master list exists anywhere in the codebase for `position_code` |

**No defect found.**

---

## N. Counter / Component Integrity

| Check | Result | Evidence |
|---|---|---|
| `CARRIER_ENGINE` `ENGINE_HOUR` distinct from `CRANE_ENGINE` `ENGINE_HOUR` | YES (via reused, unmodified Phase 4 `MeterService`) | `LifetimeRule.component_role` requires an explicit `ComponentRole` value when the trigger is component-scoped; no new counter-storage logic was written in Phase 5 — `MeterService`'s existing component-scoped validation (independently verified correct in the Phase 4 verification) is reused as-is |
| `PTO_HOUR` remains distinct | YES | Same reused mechanism |
| `ODOMETER` remains vehicle-level | YES | Same reused mechanism; unchanged by Phase 5 |
| A vehicle does not receive fabricated `CRANE_ENGINE` | YES | Phase 5 introduces no new component/vehicle seed data; the existing Phase 2/4-verified guarantee (`test_single_engine_vehicle_rejects_a_fabricated_crane_engine_reading`) is untouched |
| Missing required counter stays UNKNOWN | YES | Phase 5 does not add any new counter-value field — the only "missing value" concept it introduces is `PriorUsage.value=None` for `UNKNOWN`, handled correctly (Section J) |
| Lifetime rule does not silently choose a counter source | YES | `LifetimeRuleService.create` raises `422 VALIDATION_ERROR` if `trigger_type` is `ENGINE_HOUR`/`PTO_HOUR` and `component_role` is omitted — `test_engine_hour_trigger_requires_explicit_component_role`, independently re-run, passing |
| A02/A03 remain unresolved where applicable | YES | Confirmed in Section B |
| `ENGINE_MAIN`/`ENGINE_SECONDARY` not reintroduced | YES | `grep -rniE "ENGINE_MAIN\|ENGINE_SECONDARY" backend/app` → the only hit is `vehicle_model.py`'s own deprecation-note docstring (unchanged since the naming correction); `grep` in `frontend/src` → zero matches |

**No defect found.**

---

## O. Install / Remove / Transfer History

| Check | Result | Evidence |
|---|---|---|
| Which part instance | YES | `InstallationSegment.part_instance_id` |
| Which asset | YES | `InstallationSegment.asset_type`+`asset_id` |
| Which position | YES | `InstallationSegment.position_code` (optional) |
| Install time | YES | `installed_at` |
| Remove time | YES | `removed_at` (`None` while ACTIVE) |
| Transfer destination | YES | Represented as the new segment's `asset_type`/`asset_id` (Section F) |
| Usage accumulated in each host segment | PARTIAL, by design | No usage-total/delta is computed anywhere (correctly — no due calculation exists); the segment stores `baseline_meter_snapshot_id`/`removal_meter_snapshot_id` as the anchor points from which a *later* phase could compute a delta. This is explicitly disclosed in the result report (Section 15) and independently confirmed true — not a hidden gap. |
| Periods outside a host | YES | Reconstructable from the absence of an ACTIVE segment covering a given time range across `PartInstanceDetail.segments` |
| Historical segments not overwritten | YES | Confirmed in Section F |
| Transfer is not merely changing `current vehicle_id` | YES | `transfer()` closes the old segment (sets `removed_at`/status) and creates an entirely new segment row on the target asset — verified directly in `part_instance_service.py:177-228`; there is no "current vehicle" field on `PartInstance` at all to merely reassign |

**No defect found**, with one disclosed, correctly-scoped limitation (no
computed usage delta yet — by design, pending G01/G02).

---

## P. Part Instance Status Audit

| Check | Result | Evidence |
|---|---|---|
| No strict production transition matrix silently invented | YES | Confirmed in Section B — only the minimal technical guards exist, no full matrix |
| No unapproved state transition enforced as company policy | YES | The `_REMOVAL_NEXT_STATUSES` allow-list is disclosed by the result report itself as "this implementation's own minimal choice, not a sourced rule" (Section 37) — independently confirmed true by reading the code, and correctly not presented anywhere as an approved policy |
| State representation is minimal/reversible | YES | `PartInstanceStatus` is a plain string enum; adding a new state or a real transition matrix later is additive, not breaking |
| UI does not present provisional workflow as approved lifecycle | YES | `PartInstanceDetailPage.tsx` renders status via a plain label map (`partInstanceStatusLabel`) with inline expandable action forms — no progress stepper or "these are all the states that will ever exist" messaging |

**No defect found.**

---

## Q. Usage Adjustment / Correction

G06 remains unresolved, confirmed in Section B. Verified directly:
`grep -rn "PATCH\|PUT" backend/app/api/v1/part_instances.py
backend/app/api/v1/position_lifetime.py backend/app/api/v1/parts.py` →
zero matches — every Phase 5 route is `POST`/`GET` only. No destructive
editing capability of any kind exists for accumulated usage, prior usage,
or a baseline. This absence is documented (result report Section 36,
"Known Limitations") rather than silently omitted.

**No defect found. G06 was not implicitly resolved** — its absence is
explicit, not accidental.

---

## R. Phase 4 Integration

| Check | Result | Evidence |
|---|---|---|
| `pm_task_part` (standard) not overwritten by actual usage | YES | `test_linking_actual_pm_part_does_not_alter_standard_task_part_definition` — links an actual part with `part_id`, re-reads the task revision, confirms `standard_parts` unchanged |
| Repair part does not become PM standard part | YES | `test_standard_pm_part_actual_pm_part_and_repair_part_remain_distinct_concepts` — three distinct ID prefixes (`PMTP-`/`PMUP-`/`RPRP-`), no shared storage, confirmed by direct model read (no shared base class or table) |
| Completed Phase 4 history not destructively rewritten | YES | All 141 pre-existing Phase 4 backend tests pass unmodified as part of the 188/188 total (Section Y) — proving no existing behavior broke |
| Phase 5 optional links to `part_id`/`part_instance_id` are additive | YES | Confirmed in Section R of the code read (pm.py/repair.py diffs show only new optional fields, default `None`) |
| Normal Repair does not reset life | YES | Confirmed in Section H |

**No defect found.**

---

## S. Historical Data Integrity

| Check | Result | Evidence |
|---|---|---|
| No old PM history rewritten | YES | Full pre-existing PM test suite passes unmodified (Section Y) |
| No old Repair history rewritten | YES | Full pre-existing Repair test suite passes unmodified (Section Y) |
| No old Inspection/Finding history rewritten | YES | Phase 3 files (`inspection_service.py`, `checklist.py`) do not appear in the `2fdabf5` diff at all; full Phase 3 test suite passes unmodified |
| Part installation history append-oriented | YES | Confirmed in Section F |
| Lifecycle history preserved | YES | Confirmed in Section I |
| Kit revision history preserved | YES | Confirmed in Section E |
| No Google Sheets row-number identity | YES | All new IDs are prefixed opaque strings; declared Google Sheets tab schemas (`schemas.py`) map by header name only — `grep -n "row_number\|row number" backend/app/repositories/google_sheets/schemas.py` → no matches |

**No defect found.**

---

## T. ID Strategy Audit

| Identifier | Scheme | Stable? | Row-number-based? |
|---|---|---|---|
| `part_id` | `PART-NNNN` | YES | NO |
| `part_set_id` | `PSET-NNNN` | YES | NO |
| `part_set_revision_id` (`revision_id`) | `PSREV-NNNN` | YES | NO |
| `part_set_item_id` | `PSITEM-NNNN` | YES | NO |
| `part_instance_id` | `PINST-NNNN` | YES | NO |
| `lifecycle_id` | `PLC-NNNN` | YES | NO |
| `usage_segment_id` (`segment_id`) | `SEG-NNNN` | YES | NO |
| `position_lifetime_id` | `POSLT-NNNN` | YES | NO |
| `lifetime_rule_id` | `LTR-NNNN` | YES | NO |

Verified directly in `MockRepository`: every ID is generated from an
in-memory monotonic counter plus a fixed prefix, never from a dict/list
position exposed to the caller. Frontend does not invent authoritative
IDs — confirmed by reading every new page (`PartListPage`,
`PartDetailPage`, `PartInstanceCreatePage`, `PartInstanceDetailPage`,
`AssetPartsPage`): every ID rendered/used originates from an API response;
no client-side ID generation exists.

**A01 is not silently marked globally resolved:**
`OPEN_DECISIONS_REGISTER_EN.txt`'s A01 entry is untouched by this phase
(register diff is empty, confirmed in Section B). The ID *format* is
consistent across all 9 new types and with every prior phase's convention
— no inconsistent scheme was introduced.

**No defect found.**

---

## U. Google Sheets / Repository Audit

| Check | Result | Evidence |
|---|---|---|
| Browser does not access Google Sheets directly | YES | No Google API code exists anywhere in `frontend/` |
| All Phase 5 access is behind Repository | YES | `PartService`/`PartInstanceService`/`PositionLifetimeService`/`LifetimeRuleService` depend only on the `Repository` ABC (constructor injection) |
| Schema declarations use stable headers | YES | 9 new declared tab schemas (`part_masters`, `part_sets`, `part_set_revisions`, `part_set_items`, `part_instances`, `part_lifecycles`, `installation_segments`, `position_lifetime_records`, `lifetime_rules`) in `schemas.py`, each header-named |
| No row-number identity | YES | Confirmed in Section S |
| No false claim of live Sheets integration | YES | Every new `GoogleSheetsRepository` method calls `self._require_configured(...)` and returns nothing further — same controlled-error pattern as every prior phase; independently confirmed by direct code read (Section above) |
| MockRepository remains usable | YES | All 47 new backend tests run against `MockRepository` with zero external dependency; independently re-run in this session (Section Y) |
| PostgreSQL migration remains feasible | YES | No new code depends on Python dict/list in-memory semantics beyond `MockRepository`'s own implementation |
| No assumption that multi-row Sheets writes are atomic | YES | No live Sheets write path exists to make this assumption in the first place; A09 remains untouched and unresolved |

**No defect found.**

---

## V. Mobile / Responsive Review

Independently re-executed in this session (Section Y) across all 5
required viewport projects — 135/135 Playwright tests passed, including
25 new results from `frontend/e2e/parts-lifetime.spec.ts` (5 tests × 5
viewports).

| Area | Result | Evidence |
|---|---|---|
| Part Master search/list/detail usable | YES | `PartListPage`/`PartDetailPage` reuse the frozen `ResponsiveTable`/`Card`/`FormField` primitives; e2e "Part Master: search the catalog..." passes at all 5 viewports and asserts no horizontal scroll |
| Instance detail readable | YES | `PartInstanceDetailPage` renders install/remove/transfer/overhaul as inline expandable forms, plain stacked `<li>` history lists — mirrors `RepairDetailPage`'s established pattern |
| Install usable on phone | YES | e2e asserts the "+ ลงทะเบียนชิ้นงานใหม่"/"ติดตั้ง" buttons meet the ≥44px touch-target minimum via direct `boundingBox()` measurement |
| Remove usable on phone | YES | Same pattern, dedicated IN_REPAIR e2e test |
| Transfer usable on phone | YES | Dedicated e2e test asserts both segment rows render after transfer with no layout break |
| History readable | YES | Plain `<li>` lists, consistent with Repair/PM history rendering |
| Position/status history readable | YES | `AssetPartsPage` e2e test asserts the created record's card, its "ไม่ทราบค่า" value, and "ไม่สามารถคำนวณได้ในขณะนี้" due-status note are all visible, with no horizontal scroll |
| PM/Repair actual-part linkage usable | YES | e2e "PM actual part entry can link to a Part Instance" passes; `PartRowsEditor`'s new field is a plain full-width text input |
| No unintended horizontal scroll | YES | Explicit `scrollWidth <= clientWidth + 1` assertions in the Part Master and Position Lifetime e2e tests, re-run and passing at all 5 viewports |
| No hover-only required action | YES | All new interactive elements are `<button>`/`<a>`/form controls |
| Touch targets usable | YES | 44px minimum explicitly asserted for the two most consequential action buttons (register instance, add position-lifetime record); every other button reuses the same frozen `.button` class |
| Thai text wraps | YES | Global `overflow-wrap: break-word` (Phase 1, untouched) applies; no `white-space: nowrap` introduced in any new CSS |
| UNKNOWN clearly not shown as 0 | YES | Confirmed in Section J, and directly asserted by the e2e Position Lifetime test (`card.getByText('ไม่ทราบค่า')`) |
| Transfer/install/remove controls usable on phone | YES | Same e2e evidence as above, executed at `smartphone-portrait`/`smartphone-landscape` project configurations, not merely desktop |

**No defect found.**

---

## W. Security / Data Validation

| Check | Result | Evidence |
|---|---|---|
| No committed secrets | YES | `git ls-files \| grep -iE "\.env$\|credential\|service-account\|\.pem$\|\.key$\|secret"` → no matches |
| Input validation for IDs/enums | YES | Every enum field (`TrackingMode`, `PartSetItemRequirement`, `PartInstanceStatus`, `LifetimeTriggerType`, `LifetimeRuleScope`, `PartActionType`) is Pydantic-typed — an invalid string is rejected with `422` before reaching any service method |
| Invalid asset controlled | YES | `install`/`transfer`/`PositionLifetimeService.create` all call `require_asset_exists`, rejecting a nonexistent `asset_id` with `404`/`422` (`test_install_rejects_invalid_asset`) |
| Invalid part controlled | YES | `require_part_exists` used throughout (`PART_NOT_FOUND`, 404) — `test_get_unknown_part_returns_404`, `test_lifetime_rule_rejects_unknown_part` |
| Invalid instance controlled | YES | `require_part_instance_exists` (`PART_INSTANCE_NOT_FOUND`, 404) — `test_get_unknown_instance_returns_404`, `test_pm_used_part_rejects_unknown_part_instance_id`, `test_repair_part_rejects_unknown_part_instance_id` |
| Duplicate installation guarded | YES | Confirmed in Section F |
| Impossible transfer guarded | YES | Confirmed in Section F |
| Unsafe destructive overwrite absent | YES | Confirmed in Section Q — no `PATCH`/`PUT` exists for any Phase 5 resource |

**No defect found.**

---

## X. Phase 6 Contamination Audit

Repository-wide search executed directly in this session:

```
$ grep -rniE "driver_license|certificate_expiry|gps_track|alert_engine|device_provisioning|iot_device|ota_" backend/app/domain backend/app/api frontend/src/pages
(no matches)
```

No production implementation of driver management, certificate lifecycle,
GPS tracking, alert engine, advanced event ingestion, unrelated
document-management workflow, or IoT device management exists anywhere in
this phase's diff. The result report's own Section 26 claims the same,
independently confirmed true here rather than merely trusted.

**Phase 6 accidentally started: NO.**

---

## Y. Automated Verification

All commands below were executed directly, from scratch, in this
session — a fresh `pip install -e ".[dev]"`, a fresh `npm install`, and
the full Playwright suite — not copied from the phase report's claimed
numbers.

**Backend — pytest**
```
$ cd backend && source .venv/bin/activate && pip install -e ".[dev]"
$ DATA_REPOSITORY=mock python -m pytest -q
188 passed, 31 warnings in 6.23s
```
**Matches the phase report's claimed 188/188 exactly** (141 pre-existing
Phase 1–4 + 47 new). Warnings are all the pre-existing
`HTTP_422_UNPROCESSABLE_ENTITY` Starlette deprecation notice, same category
present since Phase 1 — not a new issue.

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npm install && npx vitest run
Test Files  25 passed (25)
     Tests  52 passed (52)
```
**Matches the claimed 52/52 exactly.**

**Frontend — typecheck**
```
$ npx tsc -b
(exit code 0 — PASSED)
```

**Frontend — lint**
```
$ npx oxlint
14 warnings, 0 errors — all react(set-state-in-effect), the same
pre-existing category present since Phase 1, now also on the 5 new Phase 5
pages. No new warning category introduced.
```

**Frontend — production build**
```
$ npm run build
dist/index.html                   0.43 kB │ gzip:  0.31 kB
dist/assets/index-*.css          10.02 kB │ gzip:  2.47 kB
dist/assets/index-*.js          366.45 kB │ gzip: 102.21 kB
✓ built in 443ms
```
**Matches the claimed sizes exactly.**

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
135 passed (1.1m)
```
Ran across `smartphone-portrait`, `smartphone-landscape`,
`tablet-portrait`, `tablet-landscape`, `desktop`. **Matches the claimed
135/135 exactly** (110 pre-existing Phase 1–4 tests + 25 new:
`parts-lifetime.spec.ts`, 5 tests × 5 viewport projects).

**Summary**

| Suite | Result | Matches phase report's claim? |
|---|---|---|
| Backend pytest | 188/188 passed | YES |
| Frontend Vitest | 52/52 passed (25 files) | YES |
| Frontend typecheck (`tsc -b`) | PASSED | YES |
| Frontend lint (`oxlint`) | PASSED (14 pre-existing-category warnings, 0 errors) | YES |
| Frontend production build | PASSED | YES |
| Playwright e2e (5 viewports) | 135/135 passed | YES |

No test was skipped, disabled, or hidden in this verification. No claimed
result in the phase report was found to be false — every number matches
an independent, from-scratch re-run in this session.

---

## Z. Manual Acceptance Plan

Run with `./scripts/run_dev.sh` (or `run_backend.sh` + `run_frontend.sh`),
`DATA_REPOSITORY=mock`, at `http://127.0.0.1:5173`.

1. **Part Master list**
   - Prerequisite: dev servers running.
   - Action: open `/parts`, search "ไส้กรองน้ำมันเครื่อง".
   - Expected: two results (`OIL-FILTER-A`/`OIL-FILTER-B`), same Thai name, different "สเปค" (ขนาด A / ขนาด B).
   - Failure evidence: screenshot + Network tab for `GET /api/v1/parts?q=...`.

2. **Part Master detail**
   - Action: open `PART-0002` (CONSUMABLE).
   - Expected: no "+ ลงทะเบียนชิ้นงานใหม่" action rendered.
   - Failure evidence: screenshot + page source showing the action absent.

3. **Same-name/different-spec parts**
   - Action: confirm both `PART-0002` and `PART-0003` open to distinct detail pages with distinct URLs/`part_id`s despite the identical display name.
   - Failure evidence: both URLs side by side.

4. **CONSUMABLE part**
   - Action: on a PM/Repair actual-part form, enter `PART-0002` as the linked `part_id`.
   - Expected: accepted; no instance-tracking prompt appears.
   - Failure evidence: `POST` request/response.

5. **POSITION_LIFETIME enrollment**
   - Action: open `/vehicle/VEH-1046/parts`, tap "+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง", position "BOOM-CYL-1", part `PART-0004`, leave prior-usage UNKNOWN, save.
   - Expected: new card shows "ไม่ทราบค่า" (never "0") and "ไม่สามารถคำนวณได้ในขณะนี้".
   - Failure evidence: screenshot + `GET /api/v1/position-lifetime/{id}` JSON.

6. **INSTANCE_TRACKED enrollment**
   - Action: open `/parts/PART-0005`, tap "+ ลงทะเบียนชิ้นงานใหม่", leave prior-usage UNKNOWN, save.
   - Expected: navigates to the instance detail page, status "พร้อมติดตั้ง".
   - Failure evidence: screenshot.

7. **Install part instance**
   - Action: tap "ติดตั้ง", target `VEH-1046`, position "MAIN-PUMP", confirm.
   - Expected: status becomes "ติดตั้งใช้งานอยู่"; one ACTIVE segment for VEH-1046.
   - Failure evidence: screenshot + `POST .../install` response.

8. **Remove part instance**
   - Action: tap "ถอดออก", select "อยู่ระหว่างซ่อม" (IN_REPAIR), confirm.
   - Expected: status "อยู่ระหว่างซ่อม"; no row shows "ติดตั้งอยู่ปัจจุบัน".
   - Failure evidence: screenshot + `POST .../remove` response.

9. **Transfer same instance to another vehicle**
   - Prerequisite: instance currently installed on VEH-1046.
   - Action: tap "โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น", target `VEH-1047`, confirm.
   - Expected: VEH-1046 row becomes "สิ้นสุดการติดตั้งแล้ว"; VEH-1047 row becomes "ติดตั้งอยู่ปัจจุบัน"; both remain visible.
   - Failure evidence: screenshot + `POST .../transfer` response.

10. **Verify old installation history remains**
    - Action: after step 9, scroll the instance's installation history.
    - Expected: both the VEH-1046 and VEH-1047 rows are present, in order, neither overwritten.
    - Failure evidence: screenshot of the full history list.

11. **Put instance IN_REPAIR**
    - Same as step 8.

12. **Confirm host usage does not accumulate while uninstalled**
    - Action: while the instance is IN_REPAIR, attempt to view any "current usage" figure for it.
    - Expected: no active-segment usage figure is shown for any host (none is computed at all in this phase — by design).
    - Failure evidence: screenshot showing no fabricated usage value.

13. **Normal Repair does not reset life**
    - Action: remove into IN_REPAIR, then reinstall the same instance.
    - Expected: "รอบที่ 1" (`cycle_number=1`) remains the current lifecycle throughout; no new lifecycle card appears.
    - Failure evidence: screenshot of the lifecycle section before/after.

14. **Prior usage KNOWN**
    - Action: register a new instance with prior-usage KNOWN, value `480.5`, note "จากบันทึกเดิม".
    - Expected: detail page shows `480.5` and the note verbatim.
    - Failure evidence: screenshot.

15. **Prior usage PARTIAL**
    - Action: register with PARTIAL, value `100`, note describing the gap.
    - Expected: both the value and the note render, with no indication of full/known completeness.
    - Failure evidence: screenshot.

16. **Prior usage UNKNOWN**
    - Action: register with UNKNOWN.
    - Expected: no value field renders as an editable number defaulting to 0; value shows "ไม่ทราบค่า".
    - Failure evidence: screenshot.

17. **Confirm UNKNOWN never displays as 0**
    - Action: inspect the raw API response for step 16's instance.
    - Expected: `"value": null`, never `"value": 0`.
    - Failure evidence: raw JSON.

18. **Lifecycle/overhaul boundary**
    - Prerequisite: instance not currently installed.
    - Action: tap "เริ่มรอบการใช้งานใหม่ (Overhaul)", leave the reason blank, attempt to confirm.
    - Expected: blocked with a validation message; cannot submit an empty reason.
    - Action (continued): enter a reason, confirm.
    - Expected: "รอบที่ 2" appears; "รอบที่ 1" remains visible with an end timestamp and its own installation history intact.
    - Failure evidence: screenshot before/after + the 422 response for the empty-reason attempt.

19. **Position lifetime without instance**
    - Same as step 5 — confirm the created record never exposes or requires a `part_instance_id`.
    - Failure evidence: raw JSON response showing no such field.

20. **PM actual part linkage**
    - Action: start a PM work order on `VEH-1046`, add a used part with a registered instance's ID in "รหัสชิ้นงาน (Part Instance)", submit.
    - Expected: the completed task shows a clickable link to the instance's detail page; the task's `standard_parts` (fetched separately) is unchanged.
    - Failure evidence: both JSON responses side by side.

21. **Repair actual part linkage**
    - Action: same, on a repair's part-entry form.
    - Expected: same linkage behavior; `RepairPart`/`PmUsedPart`/`PmTaskPart` remain visibly distinct record types.
    - Failure evidence: screenshot + JSON.

22. **Smartphone workflow**
    - Action: repeat steps 6–10 at a phone width (~375px, both orientations).
    - Expected: no horizontal scrolling; forms render as stacked fields; all primary buttons ≥44px tall.
    - Failure evidence: screenshot in the failing viewport/orientation.

23. **Desktop workflow**
    - Action: repeat steps 6–10 at ≥1280px width.
    - Expected: same information, more breathing room, no layout regressions.
    - Failure evidence: screenshot.

---

## AA. Final Verdict

# PASS WITH KNOWN LIMITATIONS

**Blocking defects:** None. Every mandatory Phase 5 SCOPE item is
implemented and independently re-verified; all automated suites were
independently re-executed from scratch in this session and matched the
phase report's claims exactly (backend 188/188, frontend unit 52/52,
typecheck/lint/build clean, Playwright 135/135 across all 5 required
viewport bands). No frozen Phase 1–4 contract was changed (every touched
file's diff is additive-only, independently confirmed by reading the
actual diffs, not merely the phase report's file list). No approved
component-role contract was changed. No Phase 6 logic was found.

**Known limitations (disclosed, non-blocking, all correctly the product of
an unresolved governance decision or a deliberately minimal scope rather
than an implementation defect):**
- No due/remaining/warning calculation exists for any lifetime rule or
  position-lifetime record (G01/G02 unresolved) — every such UI surface
  shows "ไม่สามารถคำนวณได้ในขณะนี้" verbatim.
- No usage-correction/adjustment endpoint exists (G06 unresolved).
- No Part Master edit/deactivate UI — create-and-read only, matching the
  Phase 3/4 precedent of building only what the phase's workflow requires.
- No Part Set assignment-to-PM-task UI — `PartSet`/`PartSetRevision` are a
  standalone, fully functional model not yet wired into any PM task.
- No computed "accumulated usage" figure anywhere — only raw
  baseline/removal snapshot references and segment timestamps (by design;
  no formula is approved).
- `PartInstanceService.remove`'s `next_status` allow-list is this
  implementation's own minimal, disclosed judgment call, not a sourced G05
  transition policy — flagged for revisit once G05 is resolved, not
  blocking today.
- Same A01 caveat as every prior phase: IDs are opaque and stable, but
  generated by an in-memory sequential counter, not yet a cross-storage
  strategy.
- All limitations already disclosed in Phase 1–4's own verifications
  remain accurate and unaffected: no RBAC beyond `DEV_AUTH_MODE`, M07
  upload limits remain local-development defaults only, `GoogleSheetsRepository`
  is interface/schema-only.

**Unapproved decisions found:** None. Every G01–G06/A01–A03 item was left
correctly unresolved, each with an explicit, code-level disclosure (module
docstrings naming the exact blocking decision) and a passing test proving
the placeholder behavior rather than a hidden permanent rule.

**G01 status:** Unresolved, correctly so — zero `LifetimeRule` records seeded; no due/remaining calculation exists anywhere.
**G02 status:** Unresolved, correctly so — no warning-window value populated or read anywhere.
**G03 status:** Unresolved, correctly so — `position_code` remains free text with no master vocabulary.
**G04 status:** Unresolved, correctly so — `start_new_lifecycle` requires an explicit reason but evaluates no overhaul-qualification criterion.
**G05 status:** Partially frozen, unchanged by this phase — the six known states are used exactly as named; only minimal technical guards were added (disclosed as the implementation's own choice).
**G06 status:** Unresolved, correctly so — no correction/adjustment capability exists at all.

**A01 impact:** Continues the existing mock-only sequential `PREFIX-NNNN` convention for 9 new ID types; not newly frozen, not newly resolved.
**A02 impact:** Untouched — no new authoritative-field-ownership question introduced; `MeterService` reused unchanged.
**A03 impact:** Untouched — no counter-correction/reconciliation endpoint was built.

**Real lifetime intervals fabricated:** NO
**Warning thresholds fabricated:** NO
**Position-code master fabricated:** NO
**Overhaul rule fabricated:** NO
**UNKNOWN converted to zero:** NO
**Normal Repair resets lifetime:** NO
**IN_REPAIR accumulates host usage:** NO
**Instance history lost on transfer:** NO
**POSITION_LIFETIME incorrectly requires instance:** NO
**PM/Repair/standard part concepts collapsed:** NO
**ENGINE_MAIN/ENGINE_SECONDARY reintroduced:** NO
**Frozen Phase 1–4 contracts changed:** NO
**Component-role contract changed:** NO
**Phase 6 accidentally started:** NO

**Next phase readiness:** READY

Phase 5's core contracts (`tracking_mode`, `part_instance`, position
baseline, tracking cycle, usage segment, actual-part actions, trigger
interface, overhaul reset interface) are stable, every governance decision
Phase 5 touches is correctly left open rather than guessed, and every
automated test claim was independently reproduced in this session. Phase 6
may proceed when the user directs it.

---

This is an audit only. Phase 6 was not started. No frozen Phase 1–4
contract was changed. No open business decision (G01–G06, A01–A03, or any
other) was resolved. No test was hidden. No unrelated feature was added.

STOP HERE. Do not begin Phase 6.
