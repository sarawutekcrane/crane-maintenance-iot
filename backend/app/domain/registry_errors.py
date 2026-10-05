"""Phase 7 Batch 7O2a — error envelopes of the registry read endpoints
(contract Final Rev2 §4.5, §7.2, §7.4, §8.1). Codes are stable English
identifiers; the frontend maps them to Thai."""
from __future__ import annotations

from fastapi import status

from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError, RepositoryTabReadError

TAB_CODE_PREFIX = {
    "branch_master": "BRANCH_MASTER",
    "province_master": "PROVINCE_MASTER",
    "asset_branch_history": "BRANCH_HISTORY",
    "vehicle_registration_history": "REGISTRATION_HISTORY",
}


def registry_tab_error(exc: RepositoryError) -> ApiError | None:
    """A proven structural problem -> 500 <PREFIX>_SCHEMA_INVALID {tab,
    problem, headers}; any other failure of a known registry tab -> 503
    <PREFIX>_READ_FAILED {tab}. None for anything else (propagates)."""
    tab = getattr(exc, "tab", None)
    prefix = TAB_CODE_PREFIX.get(tab) if isinstance(tab, str) else None
    if prefix is None:
        return None
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
            message=f"{tab} could not be read",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"tab": tab},
        )
    return None


def data_invalid(tab: str, issues: dict[str, int]) -> ApiError:
    """500 <PREFIX>_DATA_INVALID {tab, issues} (issue code -> count; §7.4,
    §7.7): the rows exist but break the contract's row rules; nothing is
    returned in place of them. Codes and counts only, no row values."""
    return ApiError(
        code=f"{TAB_CODE_PREFIX[tab]}_DATA_INVALID",
        message=f"{tab} contains rows that cannot be read exactly",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": tab, "issues": dict(sorted(issues.items()))},
    )


def data_context_not_configured() -> ApiError:
    return ApiError(
        code="REGISTRY_DATA_CONTEXT_NOT_CONFIGURED",
        message="REGISTRY_DATA_CONTEXT is not set for this deployment",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def branch_filter_unavailable() -> ApiError:
    return ApiError(
        code="VEHICLE_BRANCH_FILTER_UNAVAILABLE",
        message="vehicle_master has no responsible_branch_id column, so the list cannot be filtered by branch",
        status_code=status.HTTP_409_CONFLICT,
        details={"column": "responsible_branch_id"},
    )
