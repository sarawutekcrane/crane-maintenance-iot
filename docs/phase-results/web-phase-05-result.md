# Web/API Phase 5 — Parts, Lifetime, Transfer — Phase Result Report

PHASE: Web/API Phase 5 — Parts, Part Sets, Lifetime, Incremental Tracking, and Component Transfer
STATUS: PASS

Documents read in full before implementation, as required:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/05_PHASE5_PARTS_LIFETIME_TRANSFER_EN.txt`
- `docs/phase-results/web-phase-01-verification.md`, `web-phase-02-verification.md`,
  `web-phase-03-verification.md`, `web-phase-04-result.md`, `web-phase-04-verification.md`
- `docs/phase-results/component-role-naming-correction.md`,
  `component-role-naming-verification.md`

Plus direct inspection of the full existing backend/frontend codebase
(domain models, services, repositories, API routes, frontend types/
labels/pages/components) before writing any Phase 5 code, to match
established conventions exactly rather than inventing new ones.

---

## 1. OBJECTIVE

Implement scalable parts/lifetime tracking that never requires
pre-registering every physical part on every vehicle (baseline §11/§12),
without resolving any open governance decision (G01–G06) and without
fabricating any real lifetime interval, warning threshold, position-code
vocabulary, overhaul-reset rule, or usage-correction policy.

## 2. PREREQUISITE CHECK

Phases 1–4 accepted (Phase 4 verification: PASS WITH KNOWN LIMITATIONS,
Section W — "Phase 5 (Part/Lifetime) may proceed when the user directs
it"). The approved component-role vocabulary (`CARRIER_ENGINE`,
`CRANE_ENGINE`, `PTO`) is used exactly as-is (a `LifetimeRule` referencing
a component-scoped counter must name one of these roles explicitly —
`ENGINE_MAIN`/`ENGINE_SECONDARY` were not reintroduced anywhere).

## 3. FROZEN CONTRACTS USED

- `/api/v1` prefix and route-registration pattern (`api/v1/router.py`).
- Common error envelope (`app.errors.ApiError`/`build_error_envelope`).
- `Repository`/`StorageProvider` abstractions — extended additively only
  (every Phase 1–4 abstract method signature is unchanged in shape;
  `add_repair_part` gained three new **optional, defaulted** keyword
  parameters, which no existing caller needed to change).
- `AssetType`/`AssetRef` (Phase 2) reused, not redefined, for every new
  Phase 5 asset reference (install/transfer/position-lifetime).
- `MeterService` (Phase 4) reused unchanged for every Phase 5 baseline/
  removal snapshot reference — no new copy of the component/asset
  validation logic was written.
- `PageParams`/`Page[T]` pagination envelope.
- `MockRepository`/`GoogleSheetsRepository` dual-implementation pattern,
  including the declared-schema + controlled `RepositoryError`/
  `NotImplementedError` precedent.
- Stable opaque `PREFIX-NNNN` ID convention.
- Thai UI / English backend-code convention; mobile-first responsive
  primitives (`Card`, `FormField`, `ResponsiveTable`, `StatusBadge`,
  `.sticky-actions`/`--tap-target`) — reused, none redesigned.
- `PmUsedPart`/`RepairPart` (Phase 4) extended **additively** with
  optional `part_id`/`part_instance_id`/`action` fields, per this phase's
  own explicit mandate ("Phase 5 may enrich actual part records with
  part_id / part_instance_id where appropriate... do not rewrite
  completed PM/Repair historical data"). `PmTaskPart` (standard PM part
  definition) was **not** touched.

No frozen Phase 1–4 interface was changed in a breaking way. Every
extension is additive: new optional fields with `None` defaults, new
abstract methods, new routers.

## 4. FILES ADDED

Backend domain:
- `app/domain/part.py` — `TrackingMode`, `PartMaster`, `PartActionType`,
  `PartSetItemRequirement`, `PartSet`, `PartSetItem`, `PartSetRevision`,
  `PartSetRevisionDetail`.
- `app/domain/part_instance.py` — `PriorUsageQuality`, `PriorUsage`,
  `PartInstanceStatus`, `PartInstance`, `LifecycleStartReason`,
  `PartLifecycle`, `InstallationSegmentStatus`, `InstallationSegment`,
  `PartInstanceDetail`.
- `app/domain/position_lifetime.py` — `PositionLifetimeRecord`.
- `app/domain/lifetime_rule.py` — `LifetimeTriggerType`,
  `LifetimeRuleScope`, `LifetimeRule`.
- `app/domain/part_lookup.py` — `require_part_exists`/
  `require_part_instance_exists` (mirrors `asset_lookup.py`).
- `app/domain/part_service.py`, `app/domain/part_instance_service.py`,
  `app/domain/position_lifetime_service.py`,
  `app/domain/lifetime_rule_service.py`.

Backend API:
- `app/api/v1/part_schemas.py`, `app/api/v1/parts.py`
- `app/api/v1/part_instance_schemas.py`, `app/api/v1/part_instances.py`
- `app/api/v1/position_lifetime_schemas.py`, `app/api/v1/position_lifetime.py`
- `app/api/v1/lifetime_rule_schemas.py`, `app/api/v1/lifetime_rules.py`

Backend tests (47 new, see Section 18):
- `tests/test_part_master.py`, `tests/test_part_instance.py`,
  `tests/test_part_lifecycle.py`, `tests/test_prior_usage.py`,
  `tests/test_position_lifetime.py`, `tests/test_lifetime_rule.py`,
  `tests/test_pm_repair_part_linkage.py`

Frontend:
- `src/pages/PartListPage.tsx` (+ `.test.tsx`)
- `src/pages/PartDetailPage.tsx` (+ `.test.tsx`)
- `src/pages/PartInstanceCreatePage.tsx`
- `src/pages/PartInstanceDetailPage.tsx` (+ `.test.tsx`)
- `src/pages/AssetPartsPage.tsx` (+ `.test.tsx`)
- `frontend/e2e/parts-lifetime.spec.ts`

Docs:
- `docs/phase-results/web-phase-05-result.md` (this report)

## 5. FILES MODIFIED

- `app/repositories/base.py` — additive: ~30 new abstract methods for
  Part Master/Set, Part Instance/lifecycle/installation segment, Position
  Lifetime, Lifetime Rule; `add_repair_part` gained three new optional
  keyword parameters. Every Phase 1–4 abstract method's existing
  parameters are unchanged.
- `app/repositories/mock/repository.py`, `app/repositories/mock/seed_data.py`
  — additive: new in-memory storage + methods; 5 clearly-labeled
  example/development `PartMaster` seed records (one per tracking mode,
  plus a second `CONSUMABLE` record with a different specification to
  prove distinct `part_id`s). No `PartInstance`, `PartSetRevision`,
  `PositionLifetimeRecord`, or `LifetimeRule` is seeded (incremental/
  on-demand enrollment — baseline §12).
- `app/repositories/google_sheets/repository.py`,
  `app/repositories/google_sheets/schemas.py` — additive: declared tab
  schemas + controlled-error method stubs, same pattern as every prior
  phase.
- `app/domain/pm.py` — additive: `PmUsedPart` gained optional
  `part_id`/`part_instance_id`/`action` fields.
- `app/domain/repair.py` — additive: `RepairPart` gained the same three
  optional fields.
- `app/domain/pm_service.py` — `UsedPartInput` gained the same three
  optional fields; `submit_task_result` now validates a supplied
  `part_id`/`part_instance_id` actually exists (404 otherwise) before
  persisting.
- `app/domain/repair_service.py` — `add_part` gained the same three
  optional parameters with the same existence validation.
- `app/api/v1/pm_schemas.py`, `app/api/v1/pm.py` — additive: request/
  response fields threaded through.
- `app/api/v1/repair_schemas.py`, `app/api/v1/repairs.py` — additive: same.
- `app/dependencies.py`, `app/api/v1/router.py` — additive wiring for the
  four new services/routers.
- `frontend/src/lib/types.ts`, `frontend/src/lib/labels.ts` — additive
  types/Thai labels for Phase 5, plus the additive `part_id`/
  `part_instance_id`/`action` fields on `PmUsedPart`/`RepairPart`.
- `frontend/src/App.tsx` — additive routes only; every frozen Phase 1–4
  route element is untouched.
- `frontend/src/components/NavBar.tsx` — additive "อะไหล่" nav link.
- `frontend/src/components/PartRowsEditor.tsx` — additive optional
  "รหัสชิ้นงาน (Part Instance)" input per row.
- `frontend/src/components/PmTaskCard.tsx` — additive: renders a linked
  `part_instance_id`/`action` on a completed task's used-parts list.
- `frontend/src/pages/VehicleDetailPage.tsx`,
  `frontend/src/pages/EquipmentDetailPage.tsx` — additive "อะไหล่/
  อายุการใช้งาน" action link; the "coming in a later phase" placeholder
  sentence was edited to remove the now-implemented parts/lifetime
  mention (same kind of edit Phase 3/4's own reports made).
- `frontend/src/pages/RepairDetailPage.tsx` — additive optional
  part-instance-link input on the actual-part form, and rendering of a
  linked `part_instance_id`/`action` on the actual-parts list.
- `CHANGELOG.md` — new entry appended; history preserved.

## 6. API ROUTES ADDED

Part Master / Part Set:
- `POST /api/v1/parts`
- `GET /api/v1/parts?q=&tracking_mode=&page=&page_size=`
- `GET /api/v1/parts/{part_id}`
- `POST /api/v1/part-sets`
- `POST /api/v1/part-sets/{part_set_id}/revisions`
- `GET /api/v1/part-sets/{part_set_id}/active-revision`
- `GET /api/v1/part-sets/{part_set_id}/revisions/{revision_id}`

Part Instance:
- `POST /api/v1/part-instances`
- `GET /api/v1/part-instances/{part_instance_id}`
- `POST /api/v1/part-instances/{part_instance_id}/install`
- `POST /api/v1/part-instances/{part_instance_id}/remove`
- `POST /api/v1/part-instances/{part_instance_id}/transfer`
- `POST /api/v1/part-instances/{part_instance_id}/start-new-lifecycle`

Position Lifetime:
- `POST /api/v1/position-lifetime`
- `GET /api/v1/position-lifetime/{position_lifetime_id}`
- `GET /api/v1/position-lifetime?asset_type=&asset_id=`

Lifetime Rule:
- `POST /api/v1/lifetime-rules`
- `GET /api/v1/lifetime-rules/{lifetime_rule_id}`
- `GET /api/v1/lifetime-rules?part_id=`

(PM/Repair actual-part routes are unchanged in path — `POST /pm/work-orders/{id}/results`
and `POST /repairs/{id}/parts` now additionally accept `part_id`/
`part_instance_id`/`action` in their existing request bodies.)

## 7. DATABASE / SHEET TABLES USED

Declared Google Sheets tab schemas (header-mapped, no live I/O — same
controlled `RepositoryError`/`NotImplementedError` pattern as every prior
phase): `part_masters`, `part_sets`, `part_set_revisions`,
`part_set_items`, `part_instances`, `part_lifecycles`,
`installation_segments`, `position_lifetime_records`, `lifetime_rules`.
The existing `repair_parts` schema gained the three new headers.

## 8. UI PAGES ADDED

- Part Master: catalog list/search (`/parts`), detail (`/parts/:partId`).
- Part Instance: on-demand registration (`/parts/:partId/instances/new`),
  detail with install/remove/transfer/lifecycle-history actions
  (`/part-instances/:instanceId`).
- Position lifetime: asset-scoped page (`/vehicle|equipment/:id/parts`)
  showing/creating `PositionLifetimeRecord`s for that asset.

---

## 9. PARTMASTER ARCHITECTURE

`PartMaster` (`part_id`, `part_code`, `name`, `specification`,
`manufacturer`, `part_number`, `tracking_mode`, `category`, `is_active`,
`metadata`) is a specification/catalog concept, never the installed
physical instance. Created on demand via `POST /parts` — there is no
requirement to pre-load a company catalog. Two seeded records
(`PART-0002`/`PART-0003`) share the exact same display name
("ไส้กรองน้ำมันเครื่อง") but different `specification` ("ขนาด A"/"ขนาด
B") and therefore different `part_id`s — proven directly by
`test_same_display_name_different_specification_gets_different_part_id`.

## 10. TRACKING-MODE ARCHITECTURE

`TrackingMode` (`NONE`/`CONSUMABLE`/`POSITION_LIFETIME`/`INSTANCE_TRACKED`)
is a field on `PartMaster`, not a derived value. Each mode's meaning is
enforced structurally, never just documented:
- `PartInstanceService.create_instance` rejects any part whose
  `tracking_mode != INSTANCE_TRACKED` (`PART_NOT_INSTANCE_TRACKED`, 422).
- `PositionLifetimeService.create` rejects a `part_id` whose
  `tracking_mode != POSITION_LIFETIME` (`PART_NOT_POSITION_LIFETIME`,
  422) — so an `INSTANCE_TRACKED` part can never be enrolled as a
  position-lifetime record and vice versa.
- `NONE`/`CONSUMABLE` parts have no instance/position concept at all;
  `CONSUMABLE` usage is recorded only via the existing PM/Repair
  actual-part linkage (Section 15), never via a permanent instance.

Proven by `test_instance_can_only_be_created_for_instance_tracked_part`
and `test_instance_tracked_part_rejected_for_position_lifetime`.

## 11. PART SET / REVISION DESIGN

`PartSet` (stable identity) → `PartSetRevision` (immutable, one specific
revision) → `PartSetItem` (`REQUIRED`/`OPTIONAL`/`ALTERNATIVE`,
`part_id`+quantity/unit/note). Mirrors `app.domain.checklist`/
`app.domain.pm`'s revision pattern exactly: a new revision is an entirely
new item list, never an edit of a previous revision's items — proven by
`test_later_part_set_revision_does_not_rewrite_earlier_one` (creates
revision 1, then revision 2, re-reads revision 1 directly by ID and
confirms its items are unchanged). Every item's `part_id` is validated to
exist before the revision is created (`PART_NOT_FOUND`, 404 otherwise).

## 12. POSITION_LIFETIME DESIGN

`PositionLifetimeRecord` (`asset_type`+`asset_id`+`position_code`+
optional `part_id`+optional `lifetime_rule_id`+optional baseline
snapshot+`prior_usage`) requires no serialized `PartInstance` at all —
proven by `test_position_lifetime_requires_no_part_instance` (the
response type carries no `part_instance_id` field whatsoever) and
`test_position_lifetime_part_id_is_optional` (a record may name no part
at all). `position_code` is plain free text; no company position-code
vocabulary was invented anywhere (G03 remains unresolved — see Section
23). `prior_usage` follows the identical KNOWN/PARTIAL/UNKNOWN discipline
as `PartInstance`.

## 13. INSTANCE_TRACKED DESIGN

`PartInstance` (`part_instance_id`, `part_id`, `serial_number`, `status`,
`prior_usage`, `current_lifecycle_id`) is created on demand
(`POST /part-instances`), never pre-registered. Creating one also creates
its first `PartLifecycle` (`start_reason=ENROLLMENT`, `cycle_number=1`).
`PartInstanceStatus` declares exactly the six states G05 names
(`INSTALLED`/`REMOVED`/`IN_REPAIR`/`READY_FOR_INSTALL`/`STOCK`/
`SCRAPPED`) and nothing more — no transition matrix is enforced beyond
the minimal technical guards in Section 14.

## 14. INSTALL / REMOVE / TRANSFER DESIGN

`InstallationSegment` (append-oriented; `ACTIVE`/`CLOSED`) is the single
mechanism for install, remove, and transfer:

- **Install** (`POST .../install`) requires the instance is not currently
  `INSTALLED` (`PART_INSTANCE_ALREADY_INSTALLED`, 422 — duplicate-active-
  installation guard) and not `SCRAPPED`; validates the target asset
  exists and the baseline snapshot (if given) exists; creates a new
  `ACTIVE` segment and sets `status=INSTALLED`.
- **Remove** (`POST .../remove`) requires the instance is currently
  `INSTALLED` and has an `ACTIVE` segment; `next_status` is restricted to
  `REMOVED`/`IN_REPAIR`/`STOCK`/`SCRAPPED` (never back to `INSTALLED`/
  `READY_FOR_INSTALL` directly — a validation error otherwise); closes
  the active segment (`removed_at`, `removal_meter_snapshot_id`,
  `removal_reason`) and updates `status`.
- **Transfer** (`POST .../transfer`) requires the instance is currently
  `INSTALLED`; closes the current segment and opens a new one on the
  target asset **within the same lifecycle**, in one call; `status`
  remains `INSTALLED` throughout (a transfer is not a removal). Proven
  end-to-end by `test_transfer_between_vehicles_preserves_previous_segment_and_does_not_reset_usage`:
  after transferring `VEH-1046` → `VEH-1047`, both segments remain
  readable (old `CLOSED`, new `ACTIVE`), both point at the same
  `lifecycle_id`, and `prior_usage` is byte-for-byte unchanged.

No segment is ever edited or deleted once created — only `close_installation_segment`
sets `removed_at`/status on an existing row.

## 15. USAGE-SEGMENT DESIGN

A segment's `baseline_meter_snapshot_id`/`removal_meter_snapshot_id`
(both validated against `MeterService` when supplied) are the anchor
points from which a later phase could compute accumulated usage as a
counter delta — this phase does **not** compute or expose any such
delta/total (no due/remaining calculation exists anywhere in the
codebase; G01/G02 unresolved). The full segment history (every
installation across every lifecycle, including periods with no active
segment) is reconstructable from `PartInstanceDetail.segments`, satisfying
baseline §13's "reconstruct... periods outside a host asset" requirement
structurally, without inventing a usage-total formula.

## 16. PRIOR-USAGE QUALITY HANDLING

`PriorUsage{quality: KNOWN|PARTIAL|UNKNOWN, value, note}` is used
identically on `PartInstance` and `PositionLifetimeRecord`. `UNKNOWN` is
stored and returned as `value=None` — verified end-to-end (domain model →
`MockRepository` → API response schema → frontend type
`value: number | null` → frontend rendering, which always shows the Thai
label "ไม่ทราบค่า" instead of `0`) by
`test_instance_prior_usage_unknown_never_becomes_zero`,
`test_position_lifetime_prior_usage_unknown_never_becomes_zero`, and the
frontend's `PartInstanceDetailPage.test.tsx`/`AssetPartsPage.test.tsx`
("never displays an UNKNOWN prior-usage value as 0"). `PARTIAL` preserves
both the known `value` and an explicit `note` describing what remains
unknown (never silently treated as complete).

## 17. LIFECYCLE / OVERHAUL ARCHITECTURE

`PartLifecycle` (`lifecycle_id`, `cycle_number`, `start_reason`
`ENROLLMENT`/`OVERHAUL`, `started_at`/`ended_at`) is the cycle boundary.
`start_new_lifecycle` (`POST .../start-new-lifecycle`) is the **only**
code path that ever creates a second lifecycle, and it:
- requires a non-empty caller-supplied `approved_reason` (422 otherwise —
  `test_start_new_lifecycle_requires_explicit_approved_reason`), and
- requires the instance is **not** currently `INSTALLED`
  (`PART_INSTANCE_INSTALLED`, 422 — so a lifecycle boundary never splits
  an open segment).

Removing an instance into `IN_REPAIR` and reinstalling it (a normal
repair pause) never touches `current_lifecycle_id` or creates a second
`PartLifecycle` — proven directly by
`test_normal_repair_does_not_reset_lifetime`. An approved overhaul
(`test_approved_overhaul_starts_new_cycle_and_preserves_old_history`)
ends the old lifecycle (`ended_at` set) and starts a new one
(`cycle_number + 1`); the old lifecycle and its own installation
segment(s) remain in `PartInstanceDetail.lifecycles`/`segments`,
unmodified and fully readable, forever. No rule anywhere decides which
repair "counts" as an overhaul — that decision is entirely the caller's
(G04 remains unresolved, see Section 23).

## 18. LIFETIME-RULE ABSTRACTION

`LifetimeRule` (`part_id`, `scope` `MODEL`/`VEHICLE`, `model_id`/
`vehicle_id`, `trigger_type` `ENGINE_HOUR`/`PTO_HOUR`/`ODOMETER`/`CYCLE`/
`CALENDAR`, `component_role`, `first_due_value`, `interval_value`,
`warning_window_value`) is purely structural. `LifetimeRuleService`
enforces:
- `scope=MODEL` requires a real `model_id`; `scope=VEHICLE` requires a
  real `vehicle_id` (404 otherwise) — this is the "model rule now, vehicle
  override later" shape from the baseline, without any override-
  precedence resolution (nothing consumes these rules for a calculation
  yet).
- `ENGINE_HOUR`/`PTO_HOUR` triggers **require** an explicit
  `component_role` (`VALIDATION_ERROR`, 422 otherwise) — a rule may never
  silently guess which counter drives it (guardrails §10), proven by
  `test_engine_hour_trigger_requires_explicit_component_role`.

`first_due_value`/`interval_value`/`warning_window_value` default to
`None` and are **never** populated by seed data — proven by
`test_no_real_lifetime_interval_is_seeded_for_any_part` (an empty list for
every seeded part). Every test that supplies a non-`None` value is
explicitly test-only development data, never presented as a real OEM/
company threshold.

## 19. PM INTEGRATION

`PmUsedPart` gained additive, optional `part_id`/`part_instance_id`/
`action` fields. `PmService.submit_task_result` validates a supplied
`part_id` (`PART_NOT_FOUND`, 404) / `part_instance_id`
(`PART_INSTANCE_NOT_FOUND`, 404) actually exists before persisting, via
the shared `app.domain.part_lookup` helpers (mirrors
`asset_lookup.require_asset_exists`'s exact pattern). Linking an actual
part never writes back into `PmTaskPart` (the standard definition) —
proven directly by
`test_linking_actual_pm_part_does_not_alter_standard_task_part_definition`,
which re-reads the task revision after linking and confirms
`standard_parts` is unchanged. `PmTaskPart` itself was not touched at
all.

## 20. REPAIR INTEGRATION

`RepairPart` gained the identical three additive fields;
`RepairService.add_part` gained the identical validation. Proven by
`test_repair_part_may_link_to_part_master_and_instance` and
`test_repair_part_rejects_unknown_part_instance_id`.
`test_standard_pm_part_actual_pm_part_and_repair_part_remain_distinct_concepts`
proves `PmTaskPart`/`PmUsedPart`/`RepairPart` remain three separate record
types (distinct ID prefixes `PMTP-`/`PMUP-`/`RPRP-`, no shared storage)
even after both gained the same linkage capability.

## 21. REPOSITORY CHANGES

See Section 5. `Repository` (base.py) gained ~30 new abstract methods,
every one additive (no existing method's parameter list was narrowed or
removed). `MockRepository` implements all of them with the same
in-memory-dict-plus-sequential-ID-counter pattern established since
Phase 2. `GoogleSheetsRepository` declares the same schemas and the same
controlled `RepositoryError`/`NotImplementedError` stub pattern — no live
Google Sheets I/O is claimed anywhere.

## 22. API ROUTES

See Section 6. All new routes follow the exact `APIRouter(tags=[...])` +
`Depends(get_..._service)` + Pydantic request/response schema pattern
established in every prior phase; every service is composed in
`app/dependencies.py` behind the abstract `Repository`/`MeterService`
interfaces only.

---

## 23. OPEN DECISIONS ENCOUNTERED

| Decision | Status after Phase 5 | What Phase 5 actually built |
|---|---|---|
| **G01** Real Lifetime Rules | **UNRESOLVED** — not marked approved | `LifetimeRule.first_due_value`/`interval_value` structurally exist but are `None` in every seeded/non-test record; no due/remaining calculation reads them anywhere. `test_no_real_lifetime_interval_is_seeded_for_any_part` proves zero rules exist for seeded parts. |
| **G02** Lifetime Warning Windows | **UNRESOLVED** — not marked approved | `LifetimeRule.warning_window_value` exists as an optional field, always `None` unless a test explicitly (and disclosedly) sets one; nothing computes a warning state from it. |
| **G03** Position Code Master | **UNRESOLVED** — not marked approved | `position_code` is free text on `PositionLifetimeRecord`; no enum, no seeded vocabulary, no validation against a master list. Frontend copy explicitly labels any example position code as development/example data, not company master data. |
| **G04** Overhaul Reset Rules | **UNRESOLVED** — not marked approved | `PartLifecycle`/`start_new_lifecycle` provide the cycle-boundary *architecture*; the decision of which repair "counts" as an overhaul is entirely the caller's via a required, freeform `approved_reason` — no criteria are enforced or inferred. |
| **G05** Part Instance Status Transitions | **PARTIALLY FROZEN, not further resolved** | `PartInstanceStatus` declares exactly the six known states named in the register. `PartInstanceService` enforces only the minimal technical guards (no duplicate active installation, can't install SCRAPPED, remove/transfer requires currently INSTALLED, removal `next_status` restricted to a safe subset) — no company-approved transition matrix or permission model was invented. |
| **G06** Usage Adjustment Approval | **UNRESOLVED, left unimplemented** | No endpoint exists anywhere to correct/adjust `prior_usage`, accumulated usage, or a baseline after creation. `prior_usage` is set once at instance/position-lifetime creation time and never mutated by any other endpoint — there is no "who may correct" question to answer because no correction capability was built. |

Additionally: **A01** (transaction ID strategy) remains `TBD-BLOCKING`;
Phase 5 continues the same isolated, mock-only, sequential `PREFIX-NNNN`
convention every prior phase established (`PART-`, `PSET-`, `PSREV-`,
`PSITEM-`, `PINST-`, `PLC-`, `SEG-`, `POSLT-`, `LTR-`) — a reversible
continuation, not a new freeze. **A02** (authoritative data source by
field) and **A03** (counter correction/reconciliation policy) are
untouched by this phase — no counter-correction endpoint of any kind was
built, and `MeterService` (the sole authority for meter snapshots) was
reused unchanged rather than duplicated.

No entry above was resolved, approved, or silently treated as decided.
`OPEN_DECISIONS_REGISTER_EN.txt` was **not** modified by this phase.

## 24. CONFIRMATION: NO REAL LIFETIME INTERVALS WERE FABRICATED

Confirmed by direct seed-data inspection and by
`test_no_real_lifetime_interval_is_seeded_for_any_part`: zero
`LifetimeRule` records exist in `MockRepository`'s seed data. Every
`PartMaster` seed record (`PART-0001`–`PART-0005`) has its Thai `name`
explicitly suffixed "(ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)" — clearly
disclosed as development/example data, mirroring the Phase 3/4 checklist/
PM-plan placeholder disclosure pattern exactly.

## 25. CONFIRMATION: NORMAL REPAIR DOES NOT RESET LIFETIME

Confirmed by `test_normal_repair_does_not_reset_lifetime`: removing an
`INSTANCE_TRACKED` component into `IN_REPAIR` and reinstalling it leaves
`current_lifecycle_id` and the lifecycle count unchanged; both
installation segments (before and after the repair pause) remain
readable. Only the explicit, separately-gated `start-new-lifecycle`
endpoint can ever create a second lifecycle.

## 26. CONFIRMATION: PHASE 6 WAS NOT IMPLEMENTED

Confirmed by repo-wide review: no driver/certificate management, GPS,
alert engine, document-management-beyond-attachment, event-ingestion, or
IoT/device code exists anywhere in this phase's diff. `grep -rniE
"driver|certificate|gps|alert_engine|device_id|telemetry"
backend/app/domain backend/app/api frontend/src/pages` (excluding this
phase's own files) shows no Phase 5 file referencing any Phase 6 concept.

## 27. FROZEN PHASE 1–4 CONTRACTS AFFECTED: **NO**

Every Phase 1–4 route, schema, and repository abstract method's existing
signature is unchanged in shape and behavior. `PmUsedPart`/`RepairPart`
gained additive optional fields only (verified: every existing Phase 4
backend test — 141/141 — passes unmodified after this phase's changes,
proving no existing caller/test broke).

## 28. APPROVED COMPONENT-ROLE CONTRACT AFFECTED: **NO**

`CARRIER_ENGINE`/`CRANE_ENGINE`/`PTO` are used exactly as approved,
read-only, via the existing `ComponentRole` enum (imported into
`LifetimeRule.component_role`, never redefined). No new component role
was added; `ENGINE_MAIN`/`ENGINE_SECONDARY` were not reintroduced anywhere
(repo-wide grep confirms zero occurrences outside historical verification
reports, unchanged from before this phase).

---

## 29. IMPLEMENTATION SUMMARY

Four new domain areas (Part Master/Set, Part Instance/lifecycle/segment,
Position Lifetime, Lifetime Rule) were added following the exact
service/repository/API layering every prior phase established. Part
Master and Part Set mirror the Phase 3/4 revision-controlled-master
pattern; Part Instance introduces an append-oriented installation-segment
history plus an explicitly-gated lifecycle boundary; Position Lifetime is
a serialization-free sibling concept for the same "track lifetime by
asset context" need; Lifetime Rule is a pure structural placeholder
awaiting G01/G02 source data. PM and Repair actual-part records gained
optional linkage to this new domain without altering their own Phase 4
shape or history.

## 30. LOCAL STARTUP COMMANDS

Unchanged from Phase 1–4:
```
./scripts/run_backend.sh     # or: cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
./scripts/run_frontend.sh    # or: cd frontend && npm run dev
./scripts/run_dev.sh         # both together
./scripts/run_backend_tests.sh
./scripts/run_e2e_tests.sh
```

## 31. BUILD / TYPECHECK / LINT RESULT

- Backend: no lint/typecheck tool is configured for this project (pytest
  only, per `backend/pyproject.toml` — unchanged from Phase 1–4).
- Frontend typecheck (`npx tsc -b`): **PASSED** (exit code 0).
- Frontend lint (`npx oxlint`): **PASSED** — 0 errors, 14 warnings, all
  the same pre-existing `react(set-state-in-effect)` category present
  since Phase 1, now also on the new Phase 5 pages; no new warning
  category introduced.
- Frontend production build (`npm run build`): **PASSED**.
  ```
  dist/index.html                   0.43 kB │ gzip:  0.31 kB
  dist/assets/index-*.css          10.02 kB │ gzip:  2.47 kB
  dist/assets/index-*.js          366.45 kB │ gzip: 102.21 kB
  ✓ built in ~380-400ms
  ```

## 32. TESTS ACTUALLY PERFORMED

All commands below were executed directly in this session.

**Backend — pytest**
```
$ cd backend && source .venv/bin/activate && DATA_REPOSITORY=mock python -m pytest -q
188 passed, 31 warnings in ~6s
```
(141 pre-existing Phase 1–4 tests, unmodified and passing, + 47 new:
`test_part_master.py` [7], `test_part_instance.py` [11],
`test_part_lifecycle.py` [4], `test_prior_usage.py` [5],
`test_position_lifetime.py` [6], `test_lifetime_rule.py` [6],
`test_pm_repair_part_linkage.py` [8]. All warnings are the pre-existing
`HTTP_422_UNPROCESSABLE_ENTITY` Starlette deprecation notice, same
category present since Phase 1.)

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npx vitest run
Test Files  25 passed (25)
     Tests  52 passed (52)
```
(44 pre-existing + 8 new: `PartListPage.test.tsx` [2],
`PartDetailPage.test.tsx` [1], `PartInstanceDetailPage.test.tsx` [3],
`AssetPartsPage.test.tsx` [2].)

**Frontend — typecheck / lint / build**: see Section 31.

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
135 passed (~65s)
```
(110 pre-existing Phase 1–4 tests, unmodified and passing, + 25 new: 5
tests in the new `frontend/e2e/parts-lifetime.spec.ts` × 5 viewport
projects [smartphone-portrait, smartphone-landscape, tablet-portrait,
tablet-landscape, desktop].)

No test was skipped, disabled, or hidden. No result above was claimed
without being executed in this session.

## 33. TEST RESULTS (SUMMARY TABLE)

| Suite | Result |
|---|---|
| Backend pytest | 188/188 passed (141 pre-existing + 47 new) |
| Frontend Vitest | 52/52 passed (25 files; 44 pre-existing + 8 new) |
| Frontend typecheck (`tsc -b`) | PASSED |
| Frontend lint (`oxlint`) | PASSED (0 errors, 14 pre-existing-category warnings) |
| Frontend production build | PASSED |
| Playwright e2e (5 viewports) | 135/135 passed (110 pre-existing + 25 new) |

## 34. SCREEN / UX NOTES

- Part Master list/detail use the existing `ResponsiveTable`/`Card`/
  `StatusBadge` primitives — no new desktop-only table pattern was
  introduced.
- Part Instance detail renders install/remove/transfer/overhaul as
  inline expandable forms (same pattern `RepairDetailPage` established
  for its action/part/close forms) rather than a modal — consistent with
  the mobile-first guidance to avoid crowded dialogs, and requires an
  explicit "เปิดฟอร์ม → กรอกข้อมูล → กดยืนยัน" sequence for every
  state-changing action (install/remove/transfer/overhaul), so none of
  them can be triggered by a single accidental tap.
- Lifecycle/installation history render as plain stacked `<li>` lists
  (never a dense table), matching `RepairDetailPage`'s action-history
  pattern.
- `PartRowsEditor`'s new "รหัสชิ้นงาน (Part Instance)" field is a plain
  full-width text input, consistent with the existing description/
  quantity/unit fields in the same component.
- Every new Thai string was written directly in the new page/component
  source, following the existing `lib/labels.ts` map-lookup convention
  for every enum-backed value (`trackingModeLabel`,
  `partInstanceStatusLabel`, `priorUsageQualityLabel`, etc.).

## 35. MANUAL TEST PLAN

Run with `./scripts/run_dev.sh`, `DATA_REPOSITORY=mock`, at
`http://127.0.0.1:5173`.

1. **Part Master catalog** — open `/parts`, search "ไส้กรองน้ำมันเครื่อง".
   Expected: two results (`OIL-FILTER-A`/`OIL-FILTER-B`), same name,
   different "สเปค" (ขนาด A / ขนาด B).
2. **CONSUMABLE detail** — open either result. Expected: no "+
   ลงทะเบียนชิ้นงานใหม่" action (CONSUMABLE has no instance concept).
3. **Register an INSTANCE_TRACKED instance** — open `/parts/PART-0005`,
   tap "+ ลงทะเบียนชิ้นงานใหม่", leave prior-usage as "ไม่ทราบค่า", save.
   Expected: navigates to the new instance's detail page, status
   "พร้อมติดตั้ง".
4. **Install** — tap "ติดตั้ง", enter `VEH-1046`, position "MAIN-PUMP",
   confirm. Expected: status becomes "ติดตั้งใช้งานอยู่"; installation
   history shows one ACTIVE row for VEH-1046.
5. **Duplicate install rejected** — attempt to install the same instance
   again via a direct API call. Expected: `422
   PART_INSTANCE_ALREADY_INSTALLED`.
6. **Transfer** — tap "โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น", target `VEH-1047`,
   confirm. Expected: the VEH-1046 row becomes "สิ้นสุดการติดตั้งแล้ว",
   a new VEH-1047 row is "ติดตั้งอยู่ปัจจุบัน"; both remain visible.
7. **Remove into IN_REPAIR** — tap "ถอดออก", select "อยู่ระหว่างซ่อม",
   confirm. Expected: status "อยู่ระหว่างซ่อม"; no row shows "ติดตั้งอยู่
   ปัจจุบัน" (no active segment — no host-usage accumulation).
8. **Overhaul** — with the instance not installed, tap "เริ่มรอบการใช้
   งานใหม่ (Overhaul)", enter a reason, confirm. Expected: a second
   "รอบที่ 2" lifecycle appears; "รอบที่ 1" remains visible with an "end"
   timestamp and its own installation history intact.
9. **Position lifetime** — open `/vehicle/VEH-1046`, tap "อะไหล่/
   อายุการใช้งาน", tap "+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง", enter a
   position code and `PART-0004`, save. Expected: a new card shows the
   position, "ไม่ทราบค่า" for the value (never "0"), and "ไม่สามารถคำนวณ
   ได้ในขณะนี้" for due status.
10. **PM actual part linked to an instance** — start a PM work order on
    `VEH-1046`, add a used part with the registered instance's ID in
    "รหัสชิ้นงาน (Part Instance)", submit. Expected: the completed task
    shows a clickable link to the instance's detail page.
11. **Repair actual part linked to an instance** — same, on a repair's
    part-entry form.
12. **Mobile viewport** — repeat steps 3–9 at a phone width (375px).
    Expected: no horizontal scrolling, all primary buttons ≥44px tall,
    forms render as stacked fields (never a wide table).

## 36. KNOWN LIMITATIONS

- No due/remaining/warning calculation exists for any lifetime rule or
  position-lifetime record — by design (G01/G02 unresolved). Every such
  UI surface shows "ไม่สามารถคำนวณได้ในขณะนี้" verbatim.
- No usage-correction/adjustment endpoint exists (G06 unresolved) — if a
  `prior_usage` value is entered incorrectly, there is currently no way to
  correct it other than direct data manipulation outside the API.
- No Part Master edit/deactivate UI exists — parts are create-and-read
  only in this phase (mirrors Phase 3/4's checklist/PM-plan precedent of
  building only what the phase's workflow requires).
- No Part Set assignment-to-PM-task UI exists — `PartSet`/
  `PartSetRevision` are a standalone, fully functional API/data model but
  are not yet wired into any PM task's standard-parts list (no
  requirement in this phase's scope named that wiring).
- `LifetimeRule` has no list-all-rules-for-a-model UI; only a
  list-by-part API/backend capability exists.
- Position lifetime and instance-tracked history do not yet expose a
  computed "accumulated usage" number anywhere — only the raw baseline/
  removal snapshot references and segment timestamps (by design; no
  formula is approved).
- Same A01 caveat as every prior phase: IDs are opaque and stable, but
  generated by an in-memory sequential counter, not yet a cross-storage
  strategy.

## 37. RISKS / CONCERNS

- `PartInstanceService.remove`'s `next_status` allow-list
  (`REMOVED`/`IN_REPAIR`/`STOCK`/`SCRAPPED`) is a judgment call about
  which outcomes are "technically safe" without a real transition
  matrix (G05) — it should be revisited the moment an approved
  transition policy exists, since today's allow-list is this
  implementation's own minimal choice, not a sourced rule.
- If a future phase introduces real `LifetimeRule` thresholds, the
  existing `PositionLifetimeRecord`/`PartInstance` records created during
  this phase (and any real data created before G01/G02 are resolved)
  will have no computed status until a due/remaining service is added —
  this is expected, not a defect, but worth flagging for that future
  phase's own prerequisite check.

## 38. G01 STATUS

**UNRESOLVED**, not marked approved by this phase. See Sections 18, 23.

## 39. G02 STATUS

**UNRESOLVED**, not marked approved by this phase. See Sections 18, 23.

## 40. G03 STATUS

**UNRESOLVED**, not marked approved by this phase. See Sections 12, 23.

## 41. G04 STATUS

**UNRESOLVED**, not marked approved by this phase. See Sections 17, 23, 25.

## 42. G05 STATUS

**PARTIALLY FROZEN** (per the register, unchanged by this phase) — the
known six states are used exactly as named; no transition matrix/
permission model was added. See Sections 13, 14, 23.

## 43. G06 STATUS

**UNRESOLVED**, left entirely unimplemented (no correction capability
exists). See Section 23.

## 44. A01/A02/A03 IMPACT

- **A01**: continues the existing mock-only sequential `PREFIX-NNNN`
  convention for 9 new ID types; not newly frozen, not newly resolved.
- **A02**: untouched. No new authoritative-field-ownership question was
  introduced (baseline/removal meter snapshots reuse the existing,
  unchanged `MeterService`).
- **A03**: untouched. No counter-correction/reconciliation endpoint was
  built anywhere in this phase.

## 45. CONFIRMATION NO REAL LIFETIME INTERVALS WERE FABRICATED

See Section 24. Confirmed: **YES**, none were fabricated.

## 46. CONFIRMATION NORMAL REPAIR DOES NOT RESET LIFETIME

See Section 25. Confirmed: **YES**, normal repair never resets lifetime.

## 47. CONFIRMATION PHASE 6 WAS NOT IMPLEMENTED

See Section 26. Confirmed: **YES**, Phase 6 was not implemented.

## 48. FROZEN PHASE 1–4 CONTRACTS AFFECTED

**NO.** See Section 27.

## 49. COMPONENT-ROLE CONTRACT AFFECTED

**NO.** See Section 28.

## 50. FINAL PHASE 5 IMPLEMENTATION STATUS

**PASS.** Every mandatory Phase 5 SCOPE item (Part Master, tracking
modes, Part Set/revision, standard-vs-actual parts, PM/Repair actual
actions, lifetime-rule structure, model-rule/vehicle-override shape,
on-demand `PartInstance`, prior-usage quality states, installation/usage
segments, component-aware counter references, cross-vehicle transfer,
IN_REPAIR pause behavior, no-lifetime-reset-on-normal-repair,
overhaul-creates-new-cycle-only-with-explicit-approval, distinct
`part_id`s for distinct specifications) is implemented, tested, and
independently re-verifiable. No unresolved governance decision (G01–G06,
A01–A03, or any other) was resolved or silently marked approved. No real
lifetime interval, warning threshold, position-code vocabulary, or
overhaul-qualification rule was fabricated.

## NEXT PHASE READINESS

READY.

---

STOP HERE. Do not begin Phase 6.
