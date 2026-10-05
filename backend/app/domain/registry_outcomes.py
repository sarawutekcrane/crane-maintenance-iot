"""Phase 7 Batch 7O2b — the registration operations' outcome table
(Outcome Classification Addendum A.1, A.4). Data only.

`ZERO_WRITE_ALLOWLIST[op]` lists the (HTTP status, error code) pairs that the
server raises ONLY before W1 (the first write call) of that operation, so a
correlated envelope carrying one of them proves that attempt wrote nothing.
The client classifier reads the same table from
`frontend/src/lib/registryOutcomeAllowlist.json`; the backend tests assert the
two are identical and trigger every pair with zero write calls (B-OC-01).
A code that is not listed here is UNKNOWN to the client until it is added to
both tables with a test. The branch operations are added by 7O2c.
"""
from __future__ import annotations

from app.domain.request_replay import OP_REGISTRATION, OP_REGISTRATION_RECONCILE

COMMON_PRE_W1: frozenset[tuple[int, str]] = frozenset(
    {
        (403, "HTTP_ERROR"),  # capability route dependency
        (422, "REQUEST_ID_REQUIRED"),  # request-id route dependency
        (422, "VALIDATION_ERROR"),  # framework body validation
        (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"),  # handler entry
        (404, "VEHICLE_NOT_FOUND"),  # R1 read and locate
        (409, "VEHICLE_ID_AMBIGUOUS"),
        (500, "VEHICLE_MASTER_DATA_INVALID"),
        (500, "VEHICLE_MASTER_SCHEMA_INVALID"),
        (503, "VEHICLE_MASTER_READ_FAILED"),
    }
)

REGISTRATION_READS: frozenset[tuple[int, str]] = frozenset(
    {
        (503, "REGISTRATION_HISTORY_READ_FAILED"),  # R2
        (500, "REGISTRATION_HISTORY_SCHEMA_INVALID"),
        (500, "REGISTRATION_HISTORY_DATA_INVALID"),
        (503, "PROVINCE_MASTER_READ_FAILED"),  # R3
        (500, "PROVINCE_MASTER_SCHEMA_INVALID"),
        (500, "PROVINCE_MASTER_DATA_INVALID"),
    }
)

ZERO_WRITE_ALLOWLIST: dict[str, frozenset[tuple[int, str]]] = {
    OP_REGISTRATION: COMMON_PRE_W1
    | REGISTRATION_READS
    | {
        (422, "REGISTRATION_TEXT_INVALID"),  # semantic validation
        (422, "REGISTRATION_TEXT_REQUIRED"),
        (409, "REGISTRATION_PROJECTION_MISMATCH"),  # state / stale
        (409, "VEHICLE_REGISTRY_STALE"),
        (422, "PROVINCE_NOT_FOUND"),  # R3
        (422, "PROVINCE_INACTIVE"),
        (409, "REGISTRATION_DUPLICATE"),  # uniqueness
    },
    OP_REGISTRATION_RECONCILE: COMMON_PRE_W1
    | REGISTRATION_READS
    | {
        (422, "RECONCILIATION_MODE_INVALID"),  # semantic validation
        (422, "REASON_REQUIRED"),
        (422, "RELATED_REQUEST_NOT_FOUND"),  # related check
        (409, "VEHICLE_REGISTRY_STALE"),  # stale / state
        (409, "REGISTRATION_HISTORY_STALE"),
        (409, "MASTER_PAIR_INVALID"),
        (422, "PROVINCE_NOT_FOUND"),  # R3
        (422, "PROVINCE_INACTIVE"),
        (409, "REGISTRATION_DUPLICATE"),  # uniqueness
    },
}

# Not zero-write (Addendum A.2 rows of their own).
REQUEST_ID_REUSED = (409, "REQUEST_ID_REUSED")  # -> CONFLICT
HISTORY_WRITE_FAILED = (503, "REGISTRATION_HISTORY_WRITE_FAILED")  # W1 failed
MASTER_WRITE_FAILED = (503, "VEHICLE_MASTER_WRITE_FAILED")  # W2 failed after W1
SPECIAL_OUTCOMES: frozenset[tuple[int, str]] = frozenset({REQUEST_ID_REUSED, HISTORY_WRITE_FAILED, MASTER_WRITE_FAILED})

# Never allowlisted (always UNKNOWN on the client).
NEVER_ALLOWLISTED_CODES: frozenset[str] = frozenset(
    {"INTERNAL_ERROR", "NOT_FOUND", "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE"}
)
