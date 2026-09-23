"""Certificate expiry report service (Phase 7 Batch 7D2).

Resolves the request (query validation, the single Bangkok `as_of` date),
performs ONE repository read (`read_vehicle_certificates_for_report`) and
delegates every rule to the pure `app.domain.certificate_expiry_report`.

Read-only by construction: it never calls the legacy
`VehicleCertificateService` (whose reads reconcile and WRITE stale ACTIVE
rows), never reads vehicles, and never writes.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from fastapi import status

from app.domain.certificate_expiry_report import (
    MODE_MISSING_EXPIRY_DATE,
    MODE_RANGE,
    CertificateExpiryReport,
    ReportFilter,
    build_report,
)
from app.domain.common import bangkok_today
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryError, RepositorySchemaError

_DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

REASON_INVALID_DATE = "INVALID_DATE"
REASON_NOT_ALLOWED_FOR_MODE = "NOT_ALLOWED_FOR_MODE"
REASON_AFTER_EXPIRY_TO = "AFTER_EXPIRY_TO"


def _validation_error(field: str, reason: str, message: str, value: object, **extra: object) -> ApiError:
    """Same 422 envelope shape as the existing `RequestValidationError`
    handler (`details.errors[*].loc/msg/type/input`), plus the report's
    machine-readable `field` and `reason`."""
    error: dict[str, object] = {
        "type": "value_error",
        "loc": ["query", field],
        "msg": message,
        "input": value,
        "field": field,
        "reason": reason,
    }
    error.update(extra)
    return ApiError(
        code="VALIDATION_ERROR",
        message="Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details={"errors": [error]},
    )


def _parse_query_date(field: str, value: str | None) -> date | None:
    """Strict calendar date `YYYY-MM-DD` (the whole string). Other ISO
    forms the stdlib would accept (compact, week dates) are rejected."""
    if value is None:
        return None
    if _DATE_TEXT.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise _validation_error(field, REASON_INVALID_DATE, "Expected a calendar date YYYY-MM-DD", value)


class CertificateExpiryReportService:
    def __init__(self, repository: Repository, today: Callable[[], date] = bangkok_today) -> None:
        self._repository = repository
        self._today = today

    async def get_report(
        self,
        mode: str,
        expiry_from: str | None,
        expiry_to: str | None,
        effective_status: str | None,
        page: int,
        page_size: int,
    ) -> CertificateExpiryReport:
        """Validate, resolve `as_of` exactly once, read once, build.
        Callers must authorize BEFORE calling (a denied request must not
        read). Errors carry no report rows, totals or disclosures."""
        if mode == MODE_MISSING_EXPIRY_DATE:
            for field, value in (("expiry_from", expiry_from), ("expiry_to", expiry_to)):
                if value is not None:
                    raise _validation_error(
                        field,
                        REASON_NOT_ALLOWED_FOR_MODE,
                        f"{field} is not accepted when mode={MODE_MISSING_EXPIRY_DATE}",
                        value,
                    )
        parsed_from = _parse_query_date("expiry_from", expiry_from)
        parsed_to = _parse_query_date("expiry_to", expiry_to)

        as_of = self._today()  # the ONLY clock evaluation for this request

        if mode == MODE_RANGE:
            resolved_to = parsed_to if parsed_to is not None else as_of
            is_default = parsed_to is None
            if parsed_from is not None and parsed_from > resolved_to:
                raise _validation_error(
                    "expiry_from",
                    REASON_AFTER_EXPIRY_TO,
                    "expiry_from is after the resolved expiry_to",
                    expiry_from,
                    resolved_expiry_to=resolved_to.isoformat(),
                    expiry_to_is_default=is_default,
                )
            report_filter = ReportFilter(
                mode=MODE_RANGE,
                expiry_from=parsed_from,
                expiry_to_requested=parsed_to,
                expiry_to_resolved=resolved_to,
                expiry_to_is_default=is_default,
                effective_status=effective_status,
            )
        else:
            report_filter = ReportFilter(
                mode=MODE_MISSING_EXPIRY_DATE,
                expiry_from=None,
                expiry_to_requested=None,
                expiry_to_resolved=None,
                expiry_to_is_default=False,
                effective_status=effective_status,
            )

        try:
            read = await self._repository.read_vehicle_certificates_for_report()
        except RepositorySchemaError as exc:
            raise ApiError(
                code="VEHICLE_CERTIFICATE_SCHEMA_INVALID",
                message=str(exc),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
            ) from exc
        except RepositoryError as exc:
            raise ApiError(
                code="VEHICLE_CERTIFICATE_READ_FAILED",
                message="vehicle_certificate could not be read",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        return build_report(read.rows, as_of, report_filter, page, page_size)


__all__ = ["CertificateExpiryReportService"]
