"""Phase 7 Batch 7O2b — request fingerprint and replay lookup (contract Final
Rev2 §3.2, ENGINEERING E4). Pure; no I/O.

Fingerprint: SHA-256 hex of canonical JSON (sorted keys, UTF-8, separators
"," and ":") of {"op", "vehicle_id", "event_id", "body"}, where `body` is the
request body exactly as accepted — every key the client sent (an omitted
optional key stays absent, an explicit null stays null) and every value
unchanged (no trim or other normalisation). The mutation request schemas
reject unknown keys, so two different accepted bodies can never collapse into
one fingerprint by a key being dropped.

Lookup scope: every row of the operation's history tab (all vehicles).
- no row with the id -> None (continue normally; proves only that nothing
  was appended under this id);
- rows with the id, all with this fingerprint -> REPLAYED (their record ids);
- otherwise (another payload, vehicle or operation) -> REUSED.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

OP_REGISTRATION = "registration"
OP_REGISTRATION_RECONCILE = "registration_reconcile"
# Phase 7 Batch 7O2c: the five branch operations (Addendum A.4 names).
OP_TRANSFER = "transfer"
OP_INSERTION = "insertion"
OP_CORRECTION = "correction"
OP_CANCELLATION = "cancellation"
OP_BRANCH_RECONCILE = "reconcile"
# R2 Batch R2d: the four EQUIPMENT branch operations. Distinct names keep an
# equipment fingerprint from ever equalling a vehicle fingerprint, even for
# the same asset-id text and body (the frozen payload key `vehicle_id` carries
# the equipment id for these operations; the vehicle values are unchanged).
OP_EQUIPMENT_ASSIGNMENT = "equipment_assignment"
OP_EQUIPMENT_INSERTION = "equipment_insertion"
OP_EQUIPMENT_CORRECTION = "equipment_correction"
OP_EQUIPMENT_CANCELLATION = "equipment_cancellation"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_fingerprint(op: str, vehicle_id: str, event_id: str | None, body: Mapping[str, object]) -> str:
    payload = {"op": op, "vehicle_id": vehicle_id, "event_id": event_id, "body": dict(body)}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReplayLookup:
    replayed: bool  # False -> REQUEST_ID_REUSED
    record_ids: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]


def find_replay(
    rows: Sequence[Mapping[str, object]],
    request_id: str,
    fingerprint: str,
    *,
    record_id_column: str,
) -> ReplayLookup | None:
    hits = [row for row in rows if str(row.get("request_id") or "") == request_id]
    if not hits:
        return None
    same = all(str(row.get("request_fingerprint") or "") == fingerprint for row in hits)
    return ReplayLookup(
        replayed=same,
        record_ids=tuple(str(row.get(record_id_column) or "") for row in hits),
        rows=tuple(hits),
    )
