# R2 Batch R2d — Equipment Branch Writes — Result

Status: **candidate, uncommitted** on local branch `review/r2-batch-r2d-equipment-branch-writes`, created from
integration HEAD `16bbaa5624e39ae26356272aece48591e5c60f9c`.

| Item | Status |
|---|---|
| Equipment branch writes (backend, history-only) | **DONE (candidate)** — verified on MockRepository and the writable fake Sheets transport, synthetic data only |
| Live R2d write / UAT | **BLOCKED — LIVE SCHEMA** (`asset_branch_history` is still the legacy 9-column tab) |
| Equipment projection / reconciliation | NOT APPLICABLE (no equipment projection exists) |
| `source_equipment_register` use | DEFERRED (not read, not written) |
| Part transfer | OUT OF SCOPE (unrelated; no Part code changed) |
| R2e / R2f | NOT STARTED |

## 1. Owner-approved decisions implemented

1. **First equipment branch assignment.** An equipment with no branch history can be assigned its first branch
   with no known source. Public term: **branch assignment**. Stored with the frozen R1 vocabulary:
   `record_kind = ASSIGNMENT`, `entry_operation = TRANSFER`, `revision_no = 1`, `event_id = assignment_id`,
   `recorded_from_source = NONE`, `recorded_from_branch_id` blank, `baseline_source = NONE`,
   `baseline_branch_id` blank. This means **"no authoritative previous branch is known"**, not "the equipment
   had no branch before". No prior branch is inferred from `source_equipment_register`, location, personnel,
   `branch_master`, the equipment code/name or anything else. No `INITIAL_ASSIGNMENT` value was added.
2. **Dedicated capability `can_transfer_equipment_branch`** for the assignment route. It is independent of
   `can_transfer_vehicle_branch`: neither implies the other. Provisional dev holders: ADMIN (through
   `ALL_CAPABILITIES`) and MAINTENANCE_MANAGER (explicit). MAINTENANCE, SUPERVISOR, TECHNICIAN and DRIVER do not
   hold it.
3. **`can_correct_branch_history` covers vehicle AND equipment** branch-history corrections (backdated insertion,
   correction, cancellation). Its value is unchanged. It stays separate from assignment/transfer authority in both
   directions.

**Part transfer is unrelated and out of scope.** A future Part transfer (moving a physical part to another
vehicle/asset) may cross branches without being a branch transfer. Neither branch-transfer capability authorizes
it, no Part-transfer capability was invented, and no Part code changed.

## 2. Architecture: history-only, dedicated service

- **W1 only:** each operation appends at most one `asset_branch_history` row with `asset_type = EQUIPMENT`. There
  is no W2: `equipment_master` is never written (it has no `responsible_branch_id`), no projection tab, cache or
  hidden state exists, and no `PROJECTION_RECONCILIATION` row is ever written for equipment.
- **Dedicated `EquipmentBranchWriteService`** (`backend/app/domain/equipment_branch_write_service.py`). The frozen
  vehicle `BranchWriteService` and `branch_routes.py` are byte-identical. Reused unchanged: the 26-column
  `ASSET_BRANCH_HISTORY_COLUMNS`, `validate_branch_row`, `derive_timeline` (via the R2b `equipment_timeline`),
  BHR1, `source_before`, `in_force_instants`, `tied_event_ids`, `SourceUndetermined`, `resolve_effective`,
  `find_replay`, `request_fingerprint`, `require_write_context`, `registry_read`, `parse_reference_rows`,
  `equipment_history_rows`. A few small private helpers (effective time, reason, stale/ambiguous/same-instant
  errors, destination check) are duplicated so that the vehicle module stays unchanged.
- **R2b unchanged:** `equipment_branch_history.py` and `equipment_branch_routes.py` are byte-identical. Reads
  after a write keep `master = NOT_IN_SCHEMA` and `consistency = UNDETERMINED`; `CONSISTENT` and
  `PROJECTION_MISMATCH` are never produced for equipment. If every equipment event is cancelled and the first
  recorded baseline is `NONE`, the read returns current `{null, NONE}` (accepted R2b behaviour). For equipment that
  means **"no authoritative branch is currently in force from the recorded history"**, not that the equipment is
  proven to belong to no branch.

Order per operation: effective time / reason (422) → write context (503) → accepted 7K2 equipment locate
(`EQUIPMENT_NOT_FOUND`, `EQUIPMENT_ID_AMBIGUOUS`, `EQUIPMENT_MASTER_SCHEMA_INVALID`,
`EQUIPMENT_MASTER_DATA_INVALID`, `EQUIPMENT_MASTER_READ_FAILED`) → one `asset_branch_history` read (tab-wide
record-id check, this equipment's frozen validation) → replay → stale and state checks → destination check (new
destination only) → W1. The post-write timeline is derived in memory before W1 (no re-read). No equipment-status
gate was added: equipment status behaviour is unchanged.

## 3. Routes and contracts

| Route | Capability |
|---|---|
| `POST /api/v1/equipment/{equipment_id}/branch-assignments` (first assignment and later transfers) | `can_transfer_equipment_branch` |
| `POST /api/v1/equipment/{equipment_id}/branch-history/insertions` | `can_correct_branch_history` |
| `POST /api/v1/equipment/{equipment_id}/branch-history/events/{event_id}/corrections` | `can_correct_branch_history` |
| `POST /api/v1/equipment/{equipment_id}/branch-history/events/{event_id}/cancellations` | `can_correct_branch_history` |

No `branch-projection/reconciliations` route for equipment. Every route checks the capability (403), then the
client `X-Request-Id` (422 `REQUEST_ID_REQUIRED`), then the body (422 `VALIDATION_ERROR`), all with zero
repository calls.

Request bodies (`extra="forbid"`, dedicated models in `equipment_branch_write_schemas.py`):

- **Assignment:** `to_branch_id`, `effective`, `expected_current_branch_id` (nullable; must be `null` while no
  branch is known), `expected_history_revision`, optional `note_th`.
- **Insertion / correction:** `to_branch_id`, `effective`, `reason_th`, `expected_history_revision`.
- **Cancellation:** `reason_th`, `expected_history_revision`.
- No `expected_master_branch_id` anywhere. `recorded_by`, `recorded_at`, test flags and fingerprints are rejected
  if sent (unknown keys).

Reused R1 rules: BHR1 stale guard (all four), current-branch stale guard (assignment), ambiguous timeline refused,
tie-target rule (C-c1), source never guessed (C-c2), same-instant refused, latest-event rule
(`BRANCH_TRANSFER_NOT_LATEST`), `BRANCH_INSERTION_NOT_HISTORICAL`, future effective time refused, no-op when the
destination equals the current branch (assignment) or the source (insertion) or the head (correction), event
lookup (`BRANCH_EVENT_NOT_FOUND`, `BRANCH_EVENT_CANCELLED`), revision increment with `supersedes_record_id`,
append-only rows (earlier rows are never edited). Not used for equipment: master mismatch gate, master stale
guard, projection W2, projection consistency, `BRANCH_PROJECTION_MISMATCH`, `BRANCH_PROJECTION_WRITE_FAILED`,
`reconciled_old_master_branch_id`.

**Destination branch:** the frozen R1 check — one `branch_master` read, exact `branch_id`, `422 BRANCH_NOT_FOUND`,
`422 BRANCH_INACTIVE` only when the `is_active` column exists and is `FALSE`; without that column (the live shape)
every listed branch is active; data issues → `BRANCH_MASTER_DATA_INVALID`. No `branch_master` read for a no-op or
a time-only correction.

**Responses (dedicated, `extra="forbid"`):**

- changed: `request_id`, `changed: true`, `record_id`, `event_id`, `timeline_status_after`, `current_branch_id`,
  `current_source` (from the equipment timeline: `EVENT`, `NONE`, …). No `projection_write`, `consistency` or
  `master`.
- no-op: the existing `BranchNoOpResponse` (`request_id`, `changed: false`, `warnings`).
- replay: `request_id`, `replayed: true`, `record_ids`. No `consistency`.

**Write failures:** append rejected or unknown → `503 BRANCH_HISTORY_WRITE_FAILED` with details
`{history_write_outcome: rejected|unknown, request_id}`. No `projection_write` key, no retry, no compensation, no
re-read, no second append.

**Actor and audit:** `recorded_by` = `RequestContext.user_id` (server side), `recorded_at` = server UTC time,
`request_id` = the `X-Request-Id` header, `request_fingerprint` server-generated, `is_test_data` /
`test_batch_id` from the server write context (TEST → `TRUE` + batch; REAL → `FALSE` + blank). No configured
context, or TEST without a batch id → `503 REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any read. REAL keeps the
frozen cutover safety (a non-`FALSE` row for the equipment fails with `CUTOVER_INCOMPLETE`).

## 4. Fingerprint cross-asset safety

The frozen fingerprint payload `{op, vehicle_id, event_id, body}` is unchanged; for equipment the equipment id is
passed in the frozen `vehicle_id` slot. Four additive operation names were added to `request_replay.py`:
`equipment_assignment`, `equipment_insertion`, `equipment_correction`, `equipment_cancellation`. The vehicle values
(`transfer`, `insertion`, `correction`, `cancellation`, `reconcile`) are unchanged. Because replay lookup spans the
whole shared tab:

- same request id, same equipment, same operation and body → **REPLAYED**;
- same request id, another equipment → **REQUEST_ID_REUSED**;
- same request id, a vehicle and an equipment — even with identical asset-id text and body →
  **REQUEST_ID_REUSED**, never a false replay.

## 5. Narrow R1 test amendments

| Test | Amendment |
|---|---|
| `test_branch_write_batch7o2c.py::test_branch_capabilities_and_roles` | `MAINTENANCE_MANAGER` expected set + `can_transfer_equipment_branch` (`# R2d`); every previous capability kept; other roles still checked |
| `test_registration_write_batch7o2b.py::test_capability_and_dev_role_mapping` | same addition to the `MAINTENANCE_MANAGER` set; the exact branch-capability inventory now lists the two vehicle-era capabilities **plus** `can_transfer_equipment_branch` (still an exact set) |
| `test_branch_write_batch7o2c.py::test_exactly_five_branch_mutation_routes_and_strict_bodies` | four `# R2d` equipment route entries added to the exact path map |
| `test_registration_write_batch7o2b.py::test_only_the_two_registration_mutations_exist` | the same four entries |
| `test_registry_read_api_batch7o2a.py::test_no_registry_mutation_route_exists` | the same four entries |

No assertion was relaxed to "anything allowed"; mutation restrictions, R1 capability holders and the vehicle body
checks are unchanged.

## 6. Files

New: `backend/app/domain/equipment_branch_write_service.py`, `backend/app/api/v1/equipment_branch_write_routes.py`,
`backend/app/api/v1/equipment_branch_write_schemas.py`, `backend/tests/test_equipment_branch_write_batch_r2d.py`,
`backend/tests/test_equipment_branch_write_sheets_batch_r2d.py`, this document.

Edited: `backend/app/domain/authz.py` (new capability, scope comment, MAINTENANCE_MANAGER),
`backend/app/domain/request_replay.py` (four constants), `backend/app/api/v1/router.py` (include), and the three R1
tests in §5. No repository change was needed (`append_asset_branch_history` is asset-neutral). Unchanged:
`branch_write_service.py`, `branch_routes.py`, `branch_timeline.py`, `registry_write_support.py`,
`registry_schemas.py`, `equipment_branch_history.py`, `equipment_branch_routes.py`, `master_reference.py`,
`context.py`, `config.py`, personnel and department modules, all Part modules, the frontend.

## 7. Test ids (batch-local PROPOSED)

| Id | Covered by |
|---|---|
| R2D-01 | first assignment: ASSIGNMENT/TRANSFER, source NONE, baseline NONE (mock + fake) |
| R2D-02 | one W1 only; equipment and vehicle state untouched (mock + fake) |
| R2D-03 | later assignment: source EVENT, baseline only on the first record |
| R2D-04 | same destination no-op: no branch_master read, no write (mock + fake request counts) |
| R2D-05 / 06 | current-branch and BHR1 stale guards; other assets do not change this revision |
| R2D-07 / 08 | same instant; not-latest; insertion not historical; future refused |
| R2D-09 / 10 / 11 | insertion (incl. before the first event → source NONE), correction, cancellation |
| R2D-12 | ambiguous timeline, tie-target rule, tied correction resolves it |
| R2D-13 / 14 / 15 | branch not found, inactive, data invalid, live-shape branch_master without `is_active` |
| R2D-16..19 | capability holders, vehicle capability insufficient (both ways), correction capability covers equipment, independence |
| R2D-20 | `X-Request-Id` required before any read |
| R2D-21..23 | replay, other-equipment reuse, vehicle/equipment same id+body → reused; vehicle op values unchanged |
| R2D-24 / 25 | generated rows EQUIPMENT; baseline NONE, never IMPORTED_MASTER; never PROJECTION_RECONCILIATION; mock/fake row parity |
| R2D-26 / 27 | PERMANENT: the R2d endpoints/service never read or write `source_equipment_register` (spy call set, R2d module sources, fake Sheets request log even with the tab present); R2d writes history only (`registry_write_log` W1 only); no projection writer is called; the R2d modules import no Part module |
| R2D-28 / 29 | append rejected / unknown (applied or not): coded, one attempt (mock + fake) |
| R2D-30 | actor, request id, fingerprint and timestamps server-set; client overrides rejected |
| R2D-31 / 32 | TEST batch, missing batch/context (fake), REAL cutover safety and FALSE rows (fake) |
| R2D-33 / 34 | R2b read after writes; all-cancelled baseline NONE read unchanged |
| R2D-35..37 | vehicle write, vehicle read, personnel and department unchanged |
| R2D-38 | the equipment capability's holders; correction and vehicle capability values unchanged |
| R2D-39 | PERMANENT: the current R2b + R2d routes are present with their exact methods; the four R2d request bodies stay strict (exact required fields, `extra` forbidden, no `expected_master_branch_id`). NOT PERMANENT: there is no assertion that these are the only equipment branch routes forever |
| (fake) | legacy 9-column history refused with `BRANCH_HISTORY_SCHEMA_INVALID` before any write |

No test freezes future equipment projection work, future lifecycle work, future source-register use or future
capabilities (independent-review fix R1 removed the three assertions that did; see below).

**One-off candidate evidence (independent-review fix R1)** — verified at this candidate, deliberately NOT asserted
by long-lived tests:

- At R2d candidate review time, runtime `equipment_master`/domain has no approved `responsible_branch_id`
  projection. This absence is not permanently tested; a later separately-approved Equipment projection batch may
  change it.
- This candidate adds no source-equipment-register read or write to the Repository interface. A later approved
  migration/reconciliation batch may add one; that is not frozen out.
- **R2D-40 (removed as a test):** Part Transfer is OUT OF R2d scope and no Part code/capability was changed by
  this candidate. This is candidate-scope evidence, not a permanent prohibition. A later Parts/Lifetime/Transfer
  batch may introduce its own capability and workflow. R2d's own isolation stays tested in R2D-26/27 (no Part
  import, no Part repository call) and R2D-17/19 (capability independence).

## 8. Verification

| Suite | Result |
|---|---|
| A. New R2d tests | 55 passed (43 mock + 12 fake Sheets; R2D-40 removed by review fix R1) |
| B. R2b equipment branch-history | 59 passed |
| C. R1 vehicle branch writes | 396 passed (incl. the amended inventory/capability tests) |
| D. R1 registration writes | 368 passed (incl. the amended inventory/capability tests) |
| E. Replay / append semantics (7O2a read API, 7O2d costs) | 168 passed |
| F. Equipment 7K2 / status | 109 passed (`test_equipment_api`, `test_equipment_status`, 7K2 text preservation mock + Sheets) |
| G. R2c-1 personnel | 122 passed |
| H. R2c-2 department | 152 passed |
| I. R2a master reference | 63 passed |
| J. Complete backend | **3518 passed** (= 3463 baseline + 55 new; R2D-40 removed by review fix R1) |
| K. Ruff `--select E4,E7,E9,F` | 13 findings (baseline 13, unchanged); new modules clean apart from the existing FastAPI `B008` pattern and `UP017` (`timezone.utc`, as in the vehicle service) |
| L. Frontend unit | 645 passed (58 files) |
| M. Typecheck / build | passed (`tsc -b && vite build`) |
| N. Frontend lint | 33 warnings (baseline), 0 errors |
| O. Playwright inventory | 565 tests in 23 files (unchanged; no frontend file changed) |
| P. Full Playwright | **565 passed** (run alone, no concurrent load) |

## 9. Live Google Sheets

No live workbook was read or written by this batch, its tests or its verification. Development and tests use
MockRepository and the writable fake transport with the frozen **26-column** history header and synthetic rows.
A passing fake run does **not** mean live UAT is ready.

**Live R2d write / UAT remains BLOCKED — LIVE SCHEMA.** The live `asset_branch_history` still has the legacy
9-column header; until migration every equipment write fails closed with `BRANCH_HISTORY_SCHEMA_INVALID`
(`MISSING_HEADERS`) before any write (tested). A separately approved migration/cutover must reconcile and preserve
the existing rows, add the frozen columns, classify legacy rows under an approved rule and validate TEST/REAL
classification. R2d does not migrate anything.

`source_equipment_register` is not a write target, its `responsible_branch_id` is not authoritative runtime
state, and no R2d endpoint reads or writes it.

## 10. Open items (not decided here)

1. The `asset_branch_history` live migration/cutover (blocks live UAT).
2. Any future equipment branch projection (and its reconciliation) — separately designed.
3. Whether `source_equipment_register` is useful migration evidence — a future batch.
4. Part transfer permissions and workflow — a separate Parts/Lifetime/Transfer decision.
5. Equipment status rules for branch history (none approved; behaviour unchanged).
