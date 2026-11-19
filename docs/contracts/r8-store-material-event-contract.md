# R8 Store Material Event Contract — `R8-STORE-MATERIAL-EVENT-v1`

Status: **TEST-only contract (Mock repository).** Owner Decision 1 (R8 PRE-UAT Rev 1): Store is
integrated **later** with a real stock system. This system keeps **no stock ledger, no on-hand
quantity and no valuation**. It records the repair's material events in an append-only journal and
exposes them so that a future stock consumer can apply them exactly once.

Not PostgreSQL evidence, not production evidence. The journal append is guarded by a one-process
`expected_count` check; a transactional guarantee is owed by R11.

## 1. Event types (lifecycle of one requisition line)

| Event | Who (TEST grant / membership) | Rule |
|---|---|---|
| `REQUESTED` | current Technician V2 member of the repair, or `can_manage_repair` | repair must be OPEN (`STORE_REQUEST_AFTER_CLOSE_NOT_ALLOWED`) |
| `APPROVED` | `can_test_store_approve` | once per line; qty ≤ requested |
| `DENIED` | `can_test_store_approve` | once per line; reason required |
| `ISSUED` | `can_test_store_issue` | line APPROVED; qty ≤ approved − issued; actual `part_id`; a tracked `part_instance_id` must exist, belong to that part, be issued one at a time and not already be out |
| `USE_CONFIRMED` | current V2 member | names an issued identity (§1a); `position_code`; qty ≤ identity issued − used − declared |
| `RETURN_DECLARED` | current V2 member | names an issued identity (§1a); qty ≤ identity issued − used − declared |
| `RETURN_ACCEPTED` | `can_test_store_receive_return` | names an issued identity (§1a); qty ≤ min(identity declared − accepted, issued − used − accepted) |

### 1a. Physical identity (second independent review, 2026-11-18)

One line may be issued as several actual parts (equivalents) and as tracked instances. Every `USE_CONFIRMED`,
`RETURN_DECLARED` and `RETURN_ACCEPTED` carries the identity it moves — `part_id`, `part_instance_id` (empty when
not tracked) and `part_code_snapshot` copied from the matching `ISSUED` — and every quantity guard is applied per
identity, so totals never go negative and parts are never mixed. Nothing is guessed: no `part_id` →
`STORE_PART_IDENTITY_REQUIRED`; a part not issued on the line → `STORE_PART_NOT_ISSUED`; an unknown instance →
`STORE_PART_INSTANCE_NOT_ISSUED`; a part issued as instances without naming one → `STORE_PART_INSTANCE_REQUIRED`
(the issued instances are listed). The reconciliation lists `issued_parts` per identity; a movement without an
identity can never be attributed and blocks the line (`PART_IDENTITY_UNRECONCILED`).

Issued is **not** installed; used is **not** issued; a declared return is **not** an accepted return.
No return is invented: when everything issued was used, no return event exists.

Corrections, loss and damage have no approved policy (OPEN-003). They are **not implemented** and are
reported as `EXCEPTION_POLICY_PENDING`. `supersedes_event_id` is reserved for that future policy and is
always empty in v1.

## 2. Fields (every event)

| Field | Meaning |
|---|---|
| `event_id` | immutable, unique; the consumer's idempotency key |
| `event_type` | one of the seven types above |
| `event_version` | `"1"` |
| `material_request_id`, `requisition_line_id` | the existing material request and its line |
| `source_type`, `source_work_order_id` | `REPAIR` and the repair id |
| `asset_type`, `asset_id` | the repaired asset |
| `part_id`, `part_instance_id`, `part_code_snapshot` | part identity (empty when the line has no part code) |
| `quantity` | positive decimal **text**, at most 3 decimals (never a float) |
| `unit` | the line's unit; an issue in another unit is refused (`STORE_UNIT_MISMATCH`) |
| `position_code` | where it was used (USE_CONFIRMED) |
| `reason` | denial / return reason |
| `actor_user_id`, `actor_personnel_id` | the verified actor |
| `occurred_at`, `recorded_at` | ISO-8601 UTC |
| `request_id` | the client `X-Request-Id` (replay identity) |
| `supersedes_event_id` | reserved (empty in v1) |
| `data_context`, `test_batch_id` | `TEST` and the mock batch (`MOCK-7O2B-SYNTHETIC`) |

The internal replay `fingerprint` (SHA-256 of the canonical request) is stored but **not exposed**.

## 3. Feed

`GET /api/v1/store-material-events?after_event_id=<id>&limit=<1..500>` (trusted `can_view` reader):

```json
{ "contract": "R8-STORE-MATERIAL-EVENT-v1", "events": [ ... ], "next_after_event_id": "…" | null }
```

Events are returned in journal order. An unknown `after_event_id` → 404 `STORE_EVENT_NOT_FOUND`.
REAL context → 409 `STORE_REAL_NOT_ENABLED`; Google Sheets repository → 501.

## 4. Mapping for the future stock consumer

| Event | Stock effect |
|---|---|
| `ISSUED` | **deduct** `quantity` of `part_id` from stock |
| `RETURN_ACCEPTED` | **add back** `quantity` of the event's own `part_id` (and `part_instance_id`) to stock |
| every other type | no stock effect (workflow / audit only) |

A deterministic reference consumer is in `backend/tests/test_preuat_store_workflow.py` (`apply_stock_effects`,
fed the same feed twice). Apply each `event_id` **exactly once** (persist the last applied `event_id` and the set of applied ids).
Replay of a write returns the original event(s) and never appends a second event, so a duplicate
submission can never produce a second `ISSUED`.

## 5. Reconciliation (derived, never stored)

Per line: `unreconciled = issued − used − return_accepted`; `pending_return = declared − accepted`.
A repair is `RECONCILED` when no line awaits a decision, no approved quantity awaits issue, and every line
has `unreconciled = 0` and `pending_return = 0`. Repair classification (TEST-CANDIDATE-R1) is blocked until
the closed repair is reconciled (`CLASSIFICATION_BLOCKED_STORE_UNRECONCILED`).
