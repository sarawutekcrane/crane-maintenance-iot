"""Phase 7 Batch 7O2c — helpers shared by the registry write services
(registration, 7O2b; responsible branch, 7O2c). Extracted from
`registration_write_service` without any behaviour change.

Contract Final Rev2 §3.3, §8.1; Outcome Classification Addendum A.1. Nothing
here writes; nothing here raises HTTPException.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from fastapi import status

from app.domain.registration import DATA_CONTEXT_TEST
from app.domain.registry_errors import data_context_not_configured, registry_tab_error
from app.domain.vehicle_service import vehicle_path_error
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositoryFeatureNotImplementedError

T = TypeVar("T")

# Mock mode only (§8.1, review clarification C7 of 7O2b): rows written by the
# mock repository in the TEST context carry this clearly synthetic batch id
# when no REGISTRY_TEST_BATCH_ID is configured.
MOCK_TEST_BATCH_ID = "MOCK-7O2B-SYNTHETIC"


def error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=http_status, details=details)


def require_write_context(context: str | None, batch_id: str) -> str:
    """§8.1 + C7: the data context must be configured, and in TEST a
    non-blank batch id must be available before any write (checked at
    handler entry, before any read). Reads are not affected."""
    if context is None:
        raise data_context_not_configured()
    if context == DATA_CONTEXT_TEST and not batch_id.strip():
        raise error(
            "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED",
            "REGISTRY_TEST_BATCH_ID is not set; registry changes in the TEST context are refused",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"setting": "REGISTRY_TEST_BATCH_ID"},
        )
    return context


async def vehicle_read(call: Awaitable[T]) -> T:
    """A vehicle_master read with the validated-path error mapping."""
    try:
        return await call
    except RepositoryFeatureNotImplementedError:
        raise
    except RepositoryError as exc:
        mapped = vehicle_path_error(exc)
        if mapped is None:
            raise
        raise mapped from exc


async def registry_read(call: Awaitable[T]) -> T:
    """A registry tab read with the per-tab error mapping."""
    try:
        return await call
    except RepositoryFeatureNotImplementedError:
        raise
    except RepositoryError as exc:
        mapped = registry_tab_error(exc)
        if mapped is None:
            raise
        raise mapped from exc
