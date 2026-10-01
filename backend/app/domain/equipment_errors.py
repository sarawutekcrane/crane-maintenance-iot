"""Phase 7 Batch 7K2 — equipment error mapping and the new-work id guard
(approved 7K1 corrected contract, Sections 4.4-4.6 and 5.3).

Equipment-specific on purpose: `vehicle_service.vehicle_path_error` is not
widened. Write outcomes are reported only as far as the evidence
establishes: "rejected" for an HTTP 4xx error response, "unknown" for a 5xx
or transport failure, after which the request MAY have been applied. Nothing
is retried, compensated or re-read.
"""
from __future__ import annotations

from fastapi import status

from app.domain.equipment_rules import known_text_hazard
from app.errors import ApiError
from app.repositories.base import (
    RepositoryError,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
    RepositoryWriteError,
)

EQUIPMENT_TAB = "equipment_master"
EQUIPMENT_HISTORY_TAB = "equipment_status_history"
_TAB_CODE_PREFIX = {
    EQUIPMENT_TAB: "EQUIPMENT_MASTER",
    EQUIPMENT_HISTORY_TAB: "EQUIPMENT_STATUS_HISTORY",
}


def equipment_lookup_error(exc: RepositoryError) -> ApiError | None:
    """API error for an expected failure of a validated equipment read, or
    None (the caller then re-raises the exception unchanged)."""
    tab = getattr(exc, "tab", None)
    prefix = _TAB_CODE_PREFIX.get(tab) if isinstance(tab, str) else None
    if prefix is None:
        return None
    if isinstance(exc, RepositoryIdentityAmbiguousError):
        return ApiError(
            code="EQUIPMENT_ID_AMBIGUOUS",
            message="The equipment id matches more than one equipment record; nothing was changed",
            status_code=status.HTTP_409_CONFLICT,
            details={"match_count": exc.match_count},
        )
    if isinstance(exc, RepositoryRecordInvalidError):
        return data_invalid_error(tab, {exc.issue: 1})
    if isinstance(exc, RepositorySchemaError):
        return ApiError(
            code=f"{prefix}_SCHEMA_INVALID",
            message=str(exc),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
        )
    if isinstance(exc, RepositoryTabReadError):
        return ApiError(
            code=f"{prefix}_READ_FAILED",
            message=f"{exc.tab} could not be read",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return None


def equipment_write_error(exc: RepositoryError) -> ApiError | None:
    """`equipment_lookup_error` plus the two write-failure envelopes."""
    if isinstance(exc, RepositoryWriteError):
        if exc.tab == EQUIPMENT_HISTORY_TAB:
            # Only attempted after the equipment update was ACKNOWLEDGED (not
            # re-read). An unknown history outcome may mean the row exists.
            message = (
                "The equipment status update was acknowledged, but Google Sheets rejected the "
                "status-history write request; nothing was retried"
                if exc.outcome == "rejected"
                else "The equipment status update was acknowledged, but the status-history write "
                "outcome is unknown (the history row may or may not have been recorded); "
                "nothing was retried"
            )
            return ApiError(
                code="EQUIPMENT_STATUS_HISTORY_WRITE_FAILED",
                message=message,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"equipment_status_updated": True, "history_write_outcome": exc.outcome},
            )
        if exc.tab == EQUIPMENT_TAB:
            message = (
                "Google Sheets rejected the equipment update request; nothing was retried"
                if exc.outcome == "rejected"
                else "The equipment update outcome is unknown (the request may have been applied); "
                "nothing was retried"
            )
            return ApiError(
                code="EQUIPMENT_MASTER_WRITE_FAILED",
                message=message,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"equipment_write_outcome": exc.outcome},
            )
        return None
    return equipment_lookup_error(exc)


def data_invalid_error(tab: str, issue_counts: dict[str, int]) -> ApiError:
    """500 <TAB>_DATA_INVALID with per-row issue counts only (no ids)."""
    prefix = _TAB_CODE_PREFIX[tab]
    return ApiError(
        code=f"{prefix}_DATA_INVALID",
        message=f"{tab} contains records that cannot be used exactly; nothing was changed",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"issue_counts": {key: issue_counts[key] for key in sorted(issue_counts)}},
    )


def require_equipment_id_usable_for_new_work(equipment_id: str) -> None:
    """DEC-K3(a): refuse an equipment id with a KNOWN text hazard before a
    new-work request writes anything. Called only at the eight approved
    mutating sites, after the equipment lookup. Not detecting a hazard does
    not make an id safe (see `equipment_rules.known_text_hazard`)."""
    if known_text_hazard(equipment_id):
        raise ApiError(
            code="EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK",
            message=(
                "This equipment id cannot yet be used for new work records: the downstream "
                "records would not keep it exactly"
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"asset_type": "EQUIPMENT"},
        )
