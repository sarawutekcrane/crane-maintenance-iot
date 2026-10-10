"""R2 Batch R2f-a — the one error mapping for the relationship read foundation.

A repository failure is an ERROR, never a business state: a proven structural
problem becomes `<PREFIX>_SCHEMA_INVALID` (500, with tab / problem / headers)
and any other read failure `<PREFIX>_READ_FAILED` (503). It is never turned
into an empty list, UNSET or MISSING. The shapes match the R2c-1 personnel
errors, so `PERSONNEL_MASTER_*` is reported identically on every path.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from fastapi import status

from app.errors import ApiError
from app.repositories.base import (
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositorySchemaError,
)

T = TypeVar("T")


def schema_invalid(prefix: str, exc: RepositorySchemaError) -> ApiError:
    return ApiError(
        code=f"{prefix}_SCHEMA_INVALID",
        message=str(exc),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
    )


def read_failed(prefix: str, tab: str) -> ApiError:
    return ApiError(
        code=f"{prefix}_READ_FAILED",
        message=f"{tab} could not be read",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        details={"tab": tab},
    )


async def reference_read(call: Awaitable[T], prefix: str, tab: str) -> T:
    try:
        return await call
    except RepositoryFeatureNotImplementedError:
        raise
    except RepositorySchemaError as exc:
        raise schema_invalid(prefix, exc) from exc
    except RepositoryError as exc:
        raise read_failed(prefix, tab) from exc


__all__ = ["read_failed", "reference_read", "schema_invalid"]
