"""Recorded inspection findings report service (Phase 7 Batch 7E2).

Validates the query (strict calendar dates, created_from <= created_to),
performs ONE repository read (`read_inspection_findings_for_report`) and
delegates every rule to the pure `app.domain.inspection_finding_report`.

Read-only by construction: no clock, no inspection/repair/vehicle reads,
no joins and no writes. Callers must authorize BEFORE calling.
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import status

from app.domain.inspection_finding_report import InspectionFindingReport, ReportFilter, build_report
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryError, RepositorySchemaError

_DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

REASON_INVALID_DATE = "INVALID_DATE"
REASON_AFTER_CREATED_TO = "AFTER_CREATED_TO"


def _validation_error(field: str, reason: str, message: str, value: object) -> ApiError:
    """Same 422 envelope shape as the existing `RequestValidationError`
    handler (`details.errors[*].loc/msg/type/input`), plus the report's
    machine-readable `field` and `reason` (as in the 7D2 report)."""
    return ApiError(
        code="VALIDATION_ERROR",
        message="Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details={
            "errors": [
                {
                    "type": "value_error",
                    "loc": ["query", field],
                    "msg": message,
                    "input": value,
                    "field": field,
                    "reason": reason,
                }
            ]
        },
    )


def _parse_query_date(field: str, value: str | None) -> date | None:
    """Strict calendar date `YYYY-MM-DD` (the whole string, 4-digit year,
    a real date; 0001-01-01..9999-12-31). Everything else, including
    compact, week, time-bearing or newline-terminated forms and year 0000,
    is a 422 with reason INVALID_DATE."""
    if value is None:
        return None
    if _DATE_TEXT.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise _validation_error(field, REASON_INVALID_DATE, "Expected a calendar date YYYY-MM-DD", value)


class InspectionFindingReportService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def get_report(
        self,
        asset_type: str | None,
        created_from: str | None,
        created_to: str | None,
        page: int,
        page_size: int,
    ) -> InspectionFindingReport:
        """Validate, read once, build. Errors carry no report rows, totals
        or disclosures."""
        parsed_from = _parse_query_date("created_from", created_from)
        parsed_to = _parse_query_date("created_to", created_to)
        if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
            raise _validation_error(
                "created_from", REASON_AFTER_CREATED_TO, "created_from is after created_to", created_from
            )

        try:
            read = await self._repository.read_inspection_findings_for_report()
        except RepositorySchemaError as exc:
            raise ApiError(
                code="INSPECTION_FINDING_SCHEMA_INVALID",
                message=str(exc),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
            ) from exc
        except RepositoryError as exc:
            raise ApiError(
                code="INSPECTION_FINDING_READ_FAILED",
                message="inspection_findings could not be read",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        report_filter = ReportFilter(asset_type=asset_type, created_from=parsed_from, created_to=parsed_to)
        return build_report(read.rows, report_filter, page, page_size)
