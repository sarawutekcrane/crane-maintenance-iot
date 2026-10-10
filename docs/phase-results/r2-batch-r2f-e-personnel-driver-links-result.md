# R2 Batch R2f-e — Personnel ↔ Driver Identity Link — Result

Authority: R2f Final Contract Consolidation (Corrected C1) and the R2f-e implementation authorization.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `462dd80478695241d25491c345c8625b2213d6ce`
  (tree `fa2c8c2a25cf05a5fe9082445ba05ff8ebcb5892`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only:
- no live Google Sheet was read or written;
- `personnel_master.driver_id` was not added live;
- `personnel_driver_link_history` was not created;
- `driver_master` and `vehicle_driver` were not touched;
- no Driver was seeded or linked.

## 1. Scope

**Added:**
- the Personnel ↔ Driver IDENTITY link: LINK / UNLINK / RELINK, explicit RECONCILIATION, append-only history,
  stale guard, replay, uniqueness and strict TEST / REAL scope;
- the dedicated `can_link_personnel_driver` capability;
- a bounded `driver_id`-only Driver reference reader;
- Driver resolution in `GET /personnel/{id}/relationships`.

**Not added:**
- crane / vehicle responsibility (R2f-f);
- the DRIVER_DEPARTMENT_MANAGER role;
- any ACTIVE gate;
- any Driver lifecycle or status vocabulary;
- any Driver master or `vehicle_driver` change;
- link-edit UI;
- live schema changes.

## 2. Identities and authority

- Driver stays a DISTINCT identity (`driver_master.driver_id`). It is never replaced by Personnel.
- The current link is `personnel_master.driver_id`: 0..1 ↔ 0..1, exact id only.
- The link is never inferred from name, phone, licence, position, department, branch, id prefix or `vehicle_driver`.
- `vehicle_driver` is not Personnel ↔ Driver authority and is not read.

## 3. Schema (target, not live)

- `PERSONNEL_MASTER_TARGET_COLUMNS` is the verified 12-column header plus `driver_id`, placed after `user_id` with
  the other relationship cells. The verified `PERSONNEL_MASTER_COLUMNS` is unchanged.
- `personnel_driver_link_history` has a frozen header:
  - `link_event_id`, `personnel_id`, `event_kind`;
  - `previous_driver_id`, `new_driver_id`;
  - `recorded_at`, `recorded_by`, `request_id`, `request_fingerprint`, `reason_th`;
  - `is_test_data`, `test_batch_id`, `related_request_id`.
- The history tab is not in `_CORE_SCHEMAS` and is never auto-created. Existing `driver_id` values with no history
  are `NO_HISTORY`; there is no migration.
- **Missing schema fails honestly.** Every read that needs `driver_id` returns 500 `PERSONNEL_MASTER_SCHEMA_INVALID`
  until the column exists: the link locate, the history read, and the R2f-a relationship read (and through it the
  R2f-d caretaker gate). No defaulted UNSET, no derivation.

## 4. Engine reuse

`PersonnelLinkService` / `LinkSpec` (R2f-b/c) are reused unchanged in behaviour. R2f-e adds only
`PERSONNEL_DRIVER_SPEC` (`app/domain/personnel_driver_link.py`).

Rules:
- operation order, LINK / RELINK / UNLINK rules, and stale-before-no-op (409, zero writes);
- target exactly once in scope: `DRIVER_NOT_FOUND`, `DRIVER_ID_AMBIGUOUS`, `DRIVER_SCOPE_UNPROVEN`;
- uniqueness per scope: `DRIVER_ALREADY_LINKED`, whose details carry the driver id only;
- `reason_th` of 1–500 characters;
- W1 history, then W2 the ONE `driver_id` cell;
- no retry, no compensation;
- MISMATCH → explicit reconciliation;
- exact replay succeeds only when not in MISMATCH, and a reused request id is `REQUEST_ID_REUSED`.

**Locate read.** The bounded locate reads only `personnel_id`, `driver_id`, `is_test_data` and `test_batch_id`.
- A row with `personnel_id` and `driver_id` both blank is a phantom row.
- Any other row is content-bearing, and its test flag must classify exactly or the read fails closed.

**No status gate.** Neither the Personnel nor the Driver `active_status` is read for linking. The Phase 6 rule that
`driver_master.active_status` is opaque is preserved.

## 5. Scope

- REAL resolves against the untagged live `driver_master`.
- TEST resolves only against explicitly TEST-scoped synthetic drivers of the exact batch, which exist in fake / mock
  repositories only. A live TEST link fails closed with `DRIVER_SCOPE_UNPROVEN`, whatever the id text looks like.
- Uniqueness is per scope.

## 6. API

- `POST /api/v1/personnel/{personnel_id}/driver-links`:
  - body `{operation, expected_driver_id, new_driver_id?, reason_th}`;
  - requires `can_link_personnel_driver`.
- `POST /api/v1/personnel/{personnel_id}/driver-links/reconcile`:
  - body `{expected_driver_id, related_request_id, reason_th}`;
  - requires `can_link_personnel_driver`.
- `GET /api/v1/personnel/{personnel_id}/driver-links/history`:
  - requires `can_view`;
  - returns `{personnel_id, current_driver_id, latest_history_driver_id, relationship_consistency, events}`, with
    no `request_fingerprint`.
- `GET /api/v1/personnel/{personnel_id}/relationships` gains `driver: {resolution, driver_id}`, with the R2f-a states
  RESOLVED / UNSET / MISSING / AMBIGUOUS / SCOPE_UNPROVEN. No other Driver field is returned.

`can_link_personnel_driver` is held by ADMIN (`ALL_CAPABILITIES`) and MAINTENANCE_MANAGER only. A 403 makes zero
repository calls. There is no DELETE route. The Phase 6 Driver routes are unchanged.

## 7. Google Sheets

**Reads:**
- `personnel_master`: a truly bounded column read of `personnel_id`, `driver_id`, `is_test_data`, `test_batch_id`.
- `driver_master`: a truly bounded `driver_id`-only read (`DRIVER_MASTER_REFERENCE_READ_SHEET`). The Phase 6
  `DRIVER_MASTER_SHEET` and `VEHICLE_DRIVER_SHEET` are unchanged.

**Writes:**
- W2 is ONE cell, `driver_id`, addressed by header name, as forced exact text. UNLINK writes a truly empty cell.
- `driver_master` is never written.

## 8. Deployment gate

R2f-e must NOT be integrated before a separately authorized LIVE SCHEMA PREPARATION:
1. add a blank `driver_id` to `personnel_master` after `user_id`, without changing any existing value;
2. create an empty `personnel_driver_link_history` with the frozen header;
3. verify every existing Personnel row is otherwise byte-equivalent;
4. link no real Driver.

## 9. Deliberate test amendments

Each amendment is marked "R2 Batch R2f-e (deliberate evolution)" in the test source.

**Shared R2f-a guard** (also used by the R2c-1 / R2f-b / R2f-c guards):
- `PERSONNEL_LINKS` gains DRIVER;
- the only new driver repository method is the bounded `read_driver_master_reference`;
- the `driver_master` schemas are exactly the Phase 6 one and the bounded reference read;
- link writes never name `DRIVER_MASTER`.

**R2f-a mock tests:**
- the relationship body includes `driver`;
- the capability set gains `can_link_personnel_driver`, which is the only driver capability;
- the zero-write route test allows the bounded driver read;
- `test_r2fa_10` now proves the driver read uses no Phase 6 domain and returns only `{resolution, driver_id}`.

**R2f-a Sheets tests:**
- the fake `personnel_master` is the target header;
- `driver_master` is read, bounded to `driver_id` (3 assertions).

**Other suites:**
- R2f-b / R2f-c route guards expect exactly the three driver-link routes.
- The R2f-d Sheets fake `personnel_master` is the target header (one import).
- The 7O2b / 7O2c MAINTENANCE_MANAGER sets gain `can_link_personnel_driver`.

## 10. Known prototype limitation (unchanged)

Google Sheets has no cross-row compare-and-set or unique constraint. Uniqueness and stale checks run before W1/W2,
so truly concurrent writers could race. This is accepted for the prototype and is to be revisited with PostgreSQL.
