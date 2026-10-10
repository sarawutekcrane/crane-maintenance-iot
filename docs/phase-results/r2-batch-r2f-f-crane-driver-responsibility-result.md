# R2 Batch R2f-f — Crane Driver Responsibility — Result

Authority: R2f Final Contract Consolidation (Corrected C1) and the R2f-f implementation authorization.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `1ec470229fe15d65c8c8da7d5d8be77efdb2bc6b`
  (tree `426fdee0f49d0f4953c6630b916e82f0a31284e1`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only:
- no live Google Sheet was read or written;
- `crane_driver_responsibility_history` was not created;
- no live responsibility event ran;
- `vehicle_master`, `driver_master`, `personnel_master` and `vehicle_driver` were not written.

## 1. Scope

**Added:**
- Crane / Vehicle ↔ Driver RESPONSIBILITY periods:
  - the current responsible-driver read;
  - immutable period history;
  - TRANSFER, INSERTION (backdating), END, CORRECTION and CANCELLATION with revision chains;
- exclusivity, stale guards, request replay and strict TEST / REAL scope;
- persisted-history same-scope reference proof;
- the Driver eligibility gate for NEW assignments;
- the reverse Driver → Vehicle read;
- the `can_assign_crane_driver` capability and the provisional `DRIVER_DEPARTMENT_MANAGER` dev role.

**Not added:**
- R2f-g;
- any UI;
- any `vehicle_driver` change;
- any Driver lifecycle or status vocabulary;
- a licence-expiry gate;
- a reconciliation route.

## 2. Three distinct concepts (never combined)

1. **Driver master:** `driver_master`. Read-only here, through bounded readers.
2. **Personnel ↔ Driver identity link (R2f-e):** `personnel_master.driver_id`. READ only, for the eligibility gate.
   R2f-f never links, unlinks or reconciles.
3. **Crane Driver responsibility:** `crane_driver_responsibility_history`. This is the ONLY responsibility authority.

**Phase 6 `vehicle_driver`:**
- It is not an authority. It is never read, migrated, normalized, made exclusive or auto-ended.
- Its `is_primary` / `assignment_status` / `end_at` mean nothing here.
- There is no baseline import: a vehicle with no history has no responsible driver (NONE).

The asset identity is the exact `vehicle_id`. There is no crane, category, status, branch or registration gate.

## 3. History schema

`crane_driver_responsibility_history` has 21 columns. It is the direct Driver analogue of the R2f-d caretaker schema:

| Group | Columns |
|---|---|
| Identity | `record_id`, `vehicle_id`, `driver_id` |
| Event | `record_kind`, `entry_operation` |
| Revision chain | `event_id`, `revision_no`, `supersedes_record_id` |
| Effective time | `effective_at`, `effective_precision`, `effective_source` |
| Source | `recorded_from_driver_id`, `recorded_from_source` |
| Audit | `recorded_at`, `recorded_by` |
| Request | `request_id`, `request_fingerprint`, `reason_th`, `related_request_id` (reserved, always blank) |
| Scope | `is_test_data`, `test_batch_id` |

The tab is not live, never auto-created, and not in `_CORE_SCHEMAS`. A missing tab fails closed with
`CRANE_DRIVER_RESPONSIBILITY_HISTORY_SCHEMA_INVALID`, but only on R2f-f routes.

## 4. Model

`app/domain/crane_driver_timeline.py` is the accepted R2f-d timeline, structurally renamed:
- record kinds ASSIGNMENT / CORRECTION / CANCELLATION;
- operations TRANSFER / INSERTION / END / CORRECTION / CANCELLATION;
- immutable revision chains, with cancellation terminal;
- effective-time ordering;
- derived period ends;
- current status NONE / EVENT / ENDED / UNDETERMINED;
- same-instant ties → AMBIGUOUS_ORDER, never NONE.

Every structural defect makes the timeline INVALID: 500 `CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID`.

`app/domain/crane_driver_responsibility.py` is the R2f-d write discipline:
- one W1 append per change;
- no W2, no projection, no retry, no compensation;
- 503 `DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED` on a failed write;
- rules mirror R2f-d (latest-only TRANSFER / END, historical INSERTION, revision-guarded CORRECTION / CANCELLATION).

## 5. Eligibility for NEW assignments (read only)

**When it applies:** TRANSFER, INSERTION, and a CORRECTION that changes the driver. Never END, CANCELLATION, a
time- or precision-only correction, or a read.

**Driver check:** the driver resolves exactly once in scope, with `driver_master.active_status` EXACTLY `ACTIVE`.
There is no normalization and no licence gate.

**Personnel check** (in-scope Personnel holding that `driver_id`):

| Holders | Result |
|---|---|
| None | Allowed: a driver needs no Personnel link |
| Exactly one | Its `active_status` must be EXACTLY `ACTIVE`, else `PERSONNEL_NOT_ACTIVE` |
| More than one | `DRIVER_PERSONNEL_AMBIGUOUS` (409) |

**Later inactivation does not affect history.** Existing periods stay readable, and END, CANCELLATION and same-driver
corrections stay allowed.

## 6. Scope and reference proof

One classifier is used everywhere:
- exactly once in scope → proven;
- several in scope → AMBIGUOUS;
- only out of scope, or a TEST request against untagged live masters → SCOPE_UNPROVEN;
- otherwise MISSING.

**Readers:**
- Vehicle: `read_vehicle_reference()`, bounded to `vehicle_id`.
- Driver: `read_driver_responsibility_reference()`, bounded to `driver_id` and `active_status`.
- Live rows are REAL; only fake / mock repositories supply explicit TEST-scoped synthetic rows. A live TEST write
  fails closed whatever the id text.

**Persisted history** (the Fix R1 principle, applied from the start): every stored `vehicle_id` and every nonblank
`driver_id` / `recorded_from_driver_id` is proven before the timeline is trusted. This checks existence, uniqueness
and scope only.
- Issue codes: `VEHICLE_REFERENCE_*` and `DRIVER_REFERENCE_*`, with kinds `MISSING` / `AMBIGUOUS` / `SCOPE_UNPROVEN`.
- **Direct read:** the requested vehicle is proven by the locate, then one driver read covers the stored driver ids.
- **Reverse read:** one vehicle read and one driver read cover all distinct stored ids, before any id is returned.

## 7. API

| Route | Capability |
|---|---|
| `GET /api/v1/vehicles/{vehicle_id}/responsible-drivers` | `can_view` |
| `POST /api/v1/vehicles/{vehicle_id}/responsible-driver-events` | `can_assign_crane_driver` |
| `GET /api/v1/drivers/{driver_id}/vehicles` | `can_view` |

- The POST takes one strict, operation-discriminated body. Every server-set field is a 422.
- There is no DELETE and no reconciliation route.
- Responses carry stable ids only: no Driver name, phone, licence or expiry.

## 8. Authorization

`can_assign_crane_driver` is held by:
- ADMIN (through all capabilities);
- MAINTENANCE_MANAGER;
- DRIVER_DEPARTMENT_MANAGER.

The provisional DEV_AUTH role `DRIVER_DEPARTMENT_MANAGER` has EXACTLY `{can_view, can_link_personnel_driver,
can_assign_crane_driver}`. Production mapping is R11. A 403 makes zero repository calls.

## 9. Deliberate test amendments

Each amendment is marked "R2 Batch R2f-f (deliberate evolution)" in the test source.

**Shared R2f-a guard:**
- the driver reference methods are exactly the R2f-e `read_driver_master_reference` (still `driver_id` only) plus
  `read_driver_responsibility_reference` (`driver_id`, `active_status`);
- the `driver_master` schemas gain `DRIVER_RESPONSIBILITY_REFERENCE_READ_SHEET`, which is bounded-read only.

**Capability and repository-surface tests:**
- R2f-a capability test: the driver capabilities are `can_link_personnel_driver` and `can_assign_crane_driver`.
- R2f-d repository-surface test: the only "responsibility" methods are the three crane-driver ones, and
  `asset_responsibility_history` still has none.

**R2f-e capability tests:**
- `DRIVER_DEPARTMENT_MANAGER` now holds `can_link_personnel_driver`, and its exact set is asserted;
- `can_assign_crane_driver` is the only crane capability and is separate from the link capability.

**7O2b / 7O2c:** the MAINTENANCE_MANAGER sets gain `can_assign_crane_driver`.

## 10. Known prototype limitation (unchanged)

Google Sheets has no cross-row compare-and-set or unique constraint. Stale, exclusivity and replay checks run before
W1, so truly concurrent writers could race. This is accepted for the prototype and is to be revisited with PostgreSQL.
