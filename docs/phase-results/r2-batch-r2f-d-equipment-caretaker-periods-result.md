# R2 Batch R2f-d — Equipment ↔ Technician Caretaker Periods — Result

Authority: R2f Final Contract Consolidation (Corrected C1) and the R2f-d implementation authorization. Baseline:
`web/phase7-dashboard-search-reporting` @ `4d6240048e6990847dddc0acd02d7b4455d0ba1c`
(tree `a2ec326410a370032703faeb4f8ecc7b96b5aecb`); `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only: no live Google Sheet was read or written, `equipment_caretaker_history` was not created, and no
live caretaker assignment was run. Not committed (independent review first).

## 1. Scope

Added: the current-caretaker read, an immutable caretaker period history, TRANSFER, INSERTION (backdated
assignment), END, CORRECTION and CANCELLATION, revision chains, exclusivity, stale guards, request replay, strict
TEST / REAL scope, the Personnel + Technician ACTIVE gate for NEW assignments, the reverse Technician → Equipment
read, and a read surface suitable for checklist display. Also the dedicated `can_assign_equipment_caretaker`
capability.

Not added: Driver responsibility (R2f-e); caretaker write controls in the UI; any inspection gate, checklist matrix,
auto-selection or caretaker-based inspection authorization (`inspector_user_id` is unchanged); a caretaker column in
equipment_master; any use of `asset_responsibility_history`; changes to either personnel link history; live schema
changes.

## 2. Authority and history

- The only authority is `equipment_caretaker_history`. It is append-only, with no projection, no W2 and no
  reconciliation. It does not exist live, is never auto-created and fails closed when missing
  (`EQUIPMENT_CARETAKER_HISTORY_SCHEMA_INVALID`). It is not in `_CORE_SCHEMAS`.
- Frozen header: `record_id, equipment_id, technician_id, record_kind, entry_operation, event_id, revision_no,
  supersedes_record_id, effective_at, effective_precision, effective_source, recorded_from_technician_id,
  recorded_from_source, recorded_at, recorded_by, request_id, request_fingerprint, reason_th, related_request_id,
  is_test_data, test_batch_id`. The `related_request_id` column is reserved and always blank.
- There is no baseline or import. An equipment with no history has no caretaker (`current_status` NONE).
- `asset_responsibility_history` is not read, written, migrated or normalized. Its TEST roles are not vocabulary.

## 3. Timeline model (`app/domain/caretaker_timeline.py`, pure)

The R1 branch-timeline model is adapted to caretakers.

**Record kinds:**
- ASSIGNMENT, with entry operation TRANSFER, INSERTION or END. An END has a blank `technician_id` and a non-blank
  `recorded_from_technician_id`.
- CORRECTION (revision ≥ 2). It preserves the event's nature: an END stays an END, an assignment stays an
  assignment.
- CANCELLATION, which is terminal.

**Derivation:**
- In-force events are ordered by effective time, never by recorded order.
- Each period's end (`derived_end_at`) is the next in-force event's instant. Periods never overlap, so there is one
  caretaker at a time.

**INVALID** fails with 500 `EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID`, giving issue codes and counts only. It is
raised for:
- row-matrix defects;
- `RECORD_ID_DUPLICATE`, including tab-wide duplicates;
- `REVISION_FORK_OR_GAP`;
- `DANGLING_REFERENCE`;
- `CANCELLATION_NOT_LAST`;
- `CORRECTION_CHANGES_EVENT_NATURE`;
- `TEST_FLAG_INVALID`.

**AMBIGUOUS_ORDER** applies when in-force events share an effective instant:
- `current_status` becomes UNDETERMINED, never "none";
- new events are refused with `CARETAKER_TIMELINE_AMBIGUOUS`;
- only a tied event may be corrected or cancelled;
- the reverse read fails closed with a 409.

## 4. Write rules (`app/domain/equipment_caretaker.py`)

**Order of checks:**
1. Capability (403).
2. `X-Request-Id` (422).
3. Strict, operation-discriminated body (422).
4. Reason / effective-time / technician shape (422).
5. Data context (503).
6. Equipment locate.
7. One history read (tab-wide record-id check; this equipment's in-scope rows).
8. Replay (tab-wide by `request_id`).
9. Stale checks, in order: `expected_current_technician_id` for every operation, then for CORRECTION and
   CANCELLATION the event exists / is not cancelled / `expected_revision_no` is exact.
10. Ambiguity and order rules.
11. No-op.
12. The NEW-assignment gate.
13. W1 (one append).

**Per operation:**

| Operation | Instant | Reason | No-op when |
|---|---|---|---|
| TRANSFER | latest; NOW allowed | optional | the same caretaker as now |
| INSERTION | strictly before a later in-force event; no NOW | required | the same caretaker as just before |
| END | latest; NOW allowed | optional | there is no current caretaker |
| CORRECTION | any instant not already taken | required | identical technician, time and precision |
| CANCELLATION | none | required | — |

- A same instant is refused with `CARETAKER_EVENT_SAME_INSTANT`. Other refusals: `CARETAKER_EVENT_NOT_LATEST` and
  `CARETAKER_INSERTION_NOT_HISTORICAL`.
- A correction of an assignment needs `technician_id`; a correction of an END takes none
  (`CARETAKER_CORRECTION_CHANGES_EVENT_NATURE`). An END cannot be moved before every caretaker
  (`CARETAKER_END_WITHOUT_CARETAKER`).
- After W1 the only outcomes are success and 503 `CARETAKER_HISTORY_WRITE_FAILED
  {history_write_outcome, request_id}`. Nothing is retried, compensated or re-read.

**Deliberate choices to review:**
- **The gate runs after the no-op check.** This follows the R1/R2d destination-check precedent.
- **The equipment reference is a new bounded scoped reader.** `read_equipment_reference()` reads `equipment_id`
  only. On Sheets every row is REAL and `test_scope_supported=False`; the mock supplies explicit TEST-scoped
  synthetic rows. It does not reuse `EquipmentService.get_equipment`: that applies the 7K2 status / category
  gates, which would refuse the TEST fixtures and couple caretaker periods to the equipment status vocabulary.
  - Errors: `EQUIPMENT_NOT_FOUND` 404, `EQUIPMENT_ID_AMBIGUOUS` 409, `EQUIPMENT_SCOPE_UNPROVEN` 422.

## 5. ACTIVE gate (NEW assignments only)

**When it applies:** TRANSFER, INSERTION, and a CORRECTION that changes the technician. It never applies to END,
CANCELLATION or a time-only correction.

**What it checks:**
- **Technician:** exactly one in-scope technician_master row with `active_status` exactly `ACTIVE`. Errors:
  `TECHNICIAN_NOT_FOUND` / `TECHNICIAN_SCOPE_UNPROVEN` 422, `TECHNICIAN_ID_AMBIGUOUS` 409, `TECHNICIAN_NOT_ACTIVE`
  422.
- **Personnel:** exactly one in-scope personnel_master record holding that `technician_id`. Errors: none →
  `TECHNICIAN_PERSONNEL_UNRESOLVED` 422; more than one → `TECHNICIAN_PERSONNEL_AMBIGUOUS` 409.
- **Personnel status:** that record's `active_status` must be exactly `ACTIVE`, else `PERSONNEL_NOT_ACTIVE` 422.

**Scope** is the server's data context. It is never inferred from an id prefix, name, code, position, department
or branch.

## 6. API

- `GET /api/v1/equipment/{equipment_id}/caretakers` (`can_view`): returns `timeline_status`, `current_status`,
  `current_technician_id`, `current_since` and the events. For display it adds `current_technician_resolution` and
  `current_technician` (name and status only, for a checklist header).
- `POST /api/v1/equipment/{equipment_id}/caretaker-events` (`can_assign_equipment_caretaker`): one
  operation-discriminated body.
- `GET /api/v1/technicians/{technician_id}/equipment` (`can_view`): the equipment currently in this technician's
  care, in scope.

`can_assign_equipment_caretaker` is held by ADMIN (via `ALL_CAPABILITIES`) and MAINTENANCE_MANAGER only.
`can_manage_personnel`, `can_link_personnel_technician` and `can_link_personnel_account` are not reused. There is no
DELETE route and no driver route.

## 7. Google Sheets

**Reads:**
- equipment_master: a truly bounded `equipment_id`-only read; never written; no column added.
- technician_master: bounded to the four R2f-a columns.
- personnel_master: the R2f-a bounded relationship read.

**Writes:** one `append` to `equipment_caretaker_history`, ordered by its own header, with ids as forced exact
text.

## 8. Deliberate test amendments

Three existing assertions were amended narrowly. No test was skipped, excluded or removed.

- The exact MAINTENANCE_MANAGER capability sets gain `can_assign_equipment_caretaker`:
  - `test_registration_write_batch7o2b.py::test_capability_and_dev_role_mapping`;
  - `test_branch_write_batch7o2c.py::test_branch_capabilities_and_roles`.
- `test_relationship_read_batch_r2f_a.py::test_r2fa_09_reference_surface_is_read_only_and_routes_are_get_only` now
  also expects exactly one new route: the read-only `GET /api/v1/technicians/{technician_id}/equipment`. All other
  R2f-a guards are unchanged: repository technician / account / link names, `PERSONNEL_LINKS`, technician tabs, and
  no driver link.

## 9. Independent Review Fix R1 — persisted-history reference integrity

Persisted history is now same-scope proven before it is used (OD-13 / Corrected C1):
- REAL history must reference REAL equipment and REAL technicians.
- TEST history must reference TEST-scoped equipment and technicians of exactly the configured batch.

Scope is the reference row's proven scope, never the id text.

**What is checked.** Existence, uniqueness and scope only, never lifecycle status.
- An inactive historical technician is valid history.
- An inactive or missing linked Personnel record never affects a read.
- END, CANCELLATION and time-only CORRECTION stay allowed.
- Every distinct stored id is checked exactly once in scope:
  - each Technician id: every nonblank `technician_id` and `recorded_from_technician_id` of every in-scope row,
    following the frozen row model:
    - END: `technician_id` is blank; `recorded_from_technician_id` is the prior caretaker and is validated;
    - CANCELLATION: no Technician target or reference cells, so it contributes none;
  - each Equipment id.

**Defects.** A defect is a history data defect: 500 `EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID`, with issue counts
per distinct id and no ids or personal data.
- Issue codes:
  - `EQUIPMENT_REFERENCE_MISSING` / `_AMBIGUOUS` / `_SCOPE_UNPROVEN`;
  - `TECHNICIAN_REFERENCE_MISSING` / `_AMBIGUOUS` / `_SCOPE_UNPROVEN`.
- `SCOPE_UNPROVEN` means exact rows exist only out of scope, or a TEST request runs where TEST rows cannot be proven.
- A defect is never reported as NONE, UNRESOLVED, NOT_FOUND or an empty list.

**Direct read and writes.**
- The requested equipment is proven by the locate. Its rows carry exactly that id, so it is not re-read.
- The stored technician ids are proven by ONE bounded technician_master read.
- The new-assignment gate reuses that read.
- Writes therefore also fail closed before W1 on defective history. The proof for new events is unchanged.

**Reverse read.**
- The requested technician is proven in scope. An id existing only out of scope gives 422
  `TECHNICIAN_SCOPE_UNPROVEN`, never a TEST technician.
- All distinct stored equipment ids are proven by ONE bounded equipment_id read, and all stored technician ids by the
  same technician read, before any id is returned.

## 10. Known prototype limitation (unchanged)

Google Sheets has no cross-row compare-and-set. The stale, exclusivity and replay checks run before W1, so truly
concurrent writers could race. This is accepted for the prototype and is to be revisited with PostgreSQL.
