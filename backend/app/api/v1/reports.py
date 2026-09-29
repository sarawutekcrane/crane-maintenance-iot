"""Reporting routes (Phase 7).

Batch 7D2 — `GET /reports/certificate-expiry`: read-only certificate
expiry report, one row per certificate RECORD. Requires the existing
`can_view` capability BEFORE any repository read (approved DEC 5; this
does not freeze the wider M02 permission matrix and does not change the
existing certificate routes). Row-value defects give a disclosed partial
result (`complete=false`, DEC 4 option B); structural/read failures fail
the whole request with no rows, totals or disclosures.

Batch 7E2 — `GET /reports/inspection-findings`: read-only recorded
inspection findings report, one row per recorded finding RECORD (history,
not verified outstanding work). Requires `can_view` BEFORE any repository
read (approved DEC-B; does not freeze M02 and does not change the legacy
/findings or /inspections routes). Row-value defects give a disclosed
partial result (DEC-C); structural/read failures fail the whole request.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.report_schemas import (
    CertificateEffectiveStatus,
    CertificateExpiryReportDataIssuesResponse,
    CertificateExpiryReportFilterResponse,
    CertificateExpiryReportItemResponse,
    CertificateExpiryReportPopulationResponse,
    CertificateExpiryReportResponse,
    CertificateReportMode,
    InspectionFindingReportAssetType,
    InspectionFindingReportDataIssuesResponse,
    InspectionFindingReportFilterResponse,
    InspectionFindingReportItemResponse,
    InspectionFindingReportPopulationResponse,
    InspectionFindingReportResponse,
)
from app.context import RequestContext
from app.dependencies import (
    get_certificate_expiry_report_service,
    get_current_context,
    get_inspection_finding_report_service,
)
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.certificate_expiry_report import REPORT_TIMEZONE, CertificateExpiryReport
from app.domain.certificate_expiry_report_service import CertificateExpiryReportService
from app.domain.inspection_finding_report import (
    REPORT_TIMEZONE as FINDING_REPORT_TIMEZONE,
    InspectionFindingReport,
)
from app.domain.inspection_finding_report_service import InspectionFindingReportService

router = APIRouter(tags=["reports"])

_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"

_CERTIFICATE_EXPIRY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
    422: {
        "description": (
            "VALIDATION_ERROR — invalid query, a date parameter with mode=MISSING_EXPIRY_DATE "
            "(reason NOT_ALLOWED_FOR_MODE), or expiry_from after the resolved expiry_to "
            "(field expiry_from, reason AFTER_EXPIRY_TO, resolved_expiry_to, expiry_to_is_default)."
        )
    },
    500: {
        "description": (
            "VEHICLE_CERTIFICATE_SCHEMA_INVALID (details: tab, problem, headers) for a proven "
            "vehicle_certificate structural problem, or INTERNAL_ERROR. No rows, totals or "
            "disclosures are returned."
        )
    },
    503: {"description": "VEHICLE_CERTIFICATE_READ_FAILED — vehicle_certificate could not be read."},
}


def _response(report: CertificateExpiryReport) -> CertificateExpiryReportResponse:
    f = report.filter
    p = report.population
    d = report.data_issues
    return CertificateExpiryReportResponse(
        as_of_date=report.as_of_date,
        timezone=REPORT_TIMEZONE,
        filter=CertificateExpiryReportFilterResponse(
            mode=f.mode,
            expiry_from=f.expiry_from,
            expiry_to_requested=f.expiry_to_requested,
            expiry_to_resolved=f.expiry_to_resolved,
            expiry_to_is_default=f.expiry_to_is_default,
            effective_status=f.effective_status,
        ),
        items=[
            CertificateExpiryReportItemResponse(
                certificate_id=i.certificate_id,
                vehicle_id=i.vehicle_id,
                certificate_type_code=i.certificate_type_code,
                certificate_type_name_th=i.certificate_type_name_th,
                document_no=i.document_no,
                expiry_date=i.expiry_date,
                stored_status=i.stored_status,
                effective_status=i.effective_status,
                expiry_position=i.expiry_position,
                flags=i.flags,
            )
            for i in report.items
        ],
        page=report.page,
        page_size=report.page_size,
        total_items=report.total_items,
        complete=report.complete,
        population=CertificateExpiryReportPopulationResponse(
            read_record_count=p.read_record_count,
            in_scope_count=p.in_scope_count,
            in_scope_with_expiry_date_count=p.in_scope_with_expiry_date_count,
            in_scope_without_expiry_date_count=p.in_scope_without_expiry_date_count,
            excluded_replaced_count=p.excluded_replaced_count,
            excluded_status_blank_count=p.excluded_status_blank_count,
            issue_row_count=p.issue_row_count,
            excluded_rows_with_other_defects=p.excluded_rows_with_other_defects,
            replaced_link_observations=p.replaced_link_observations,
        ),
        data_issues=CertificateExpiryReportDataIssuesResponse(
            issue_defect_counts=d.issue_defect_counts,
            issue_defect_counts_are_occurrences=True,
            issue_rows_without_usable_id=d.issue_rows_without_usable_id,
            sample_certificate_ids=d.sample_certificate_ids,
        ),
    )


@router.get(
    "/reports/certificate-expiry",
    response_model=CertificateExpiryReportResponse,
    responses=_CERTIFICATE_EXPIRY_ERROR_RESPONSES,
    summary="Certificate expiry report (one row per certificate record)",
)
async def get_certificate_expiry_report(
    mode: CertificateReportMode = Query(default=CertificateReportMode.RANGE),
    expiry_from: str | None = Query(
        default=None, pattern=_DATE_PATTERN, description="Inclusive, YYYY-MM-DD, RANGE only."
    ),
    expiry_to: str | None = Query(
        default=None,
        pattern=_DATE_PATTERN,
        description="Inclusive, YYYY-MM-DD, RANGE only. Omitted = today's Bangkok date.",
    ),
    effective_status: CertificateEffectiveStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: CertificateExpiryReportService = Depends(get_certificate_expiry_report_service),
) -> CertificateExpiryReportResponse:
    # Authorization before any repository read: a denied request reads nothing.
    require_capability(context, CAN_VIEW, "รายงานใบรับรองตามวันหมดอายุ (certificate expiry report)")
    report = await service.get_report(
        mode=mode.value,
        expiry_from=expiry_from,
        expiry_to=expiry_to,
        effective_status=effective_status.value if effective_status is not None else None,
        page=page,
        page_size=page_size,
    )
    return _response(report)


_INSPECTION_FINDINGS_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
    422: {
        "description": (
            "VALIDATION_ERROR — invalid query (FastAPI), a created_from/created_to that is not a "
            "calendar date YYYY-MM-DD (reason INVALID_DATE), or created_from after created_to "
            "(field created_from, reason AFTER_CREATED_TO)."
        )
    },
    500: {
        "description": (
            "INSPECTION_FINDING_SCHEMA_INVALID (details: tab, problem, headers) for a proven "
            "inspection_findings structural problem, or INTERNAL_ERROR. No rows, totals or "
            "disclosures are returned."
        )
    },
    503: {"description": "INSPECTION_FINDING_READ_FAILED — inspection_findings could not be read."},
}


def _finding_report_response(report: InspectionFindingReport) -> InspectionFindingReportResponse:
    f = report.filter
    p = report.population
    d = report.data_issues
    return InspectionFindingReportResponse(
        timezone=FINDING_REPORT_TIMEZONE,
        filter=InspectionFindingReportFilterResponse(
            asset_type=f.asset_type,
            created_from=f.created_from,
            created_to=f.created_to,
        ),
        items=[
            InspectionFindingReportItemResponse(
                finding_id=i.finding_id,
                inspection_id=i.inspection_id,
                result_id=i.result_id,
                asset_type=i.asset_type,
                asset_id=i.asset_id,
                item_title=i.item_title,
                recorded_status=i.recorded_status,
                created_at=i.created_at,
                flags=i.flags,
            )
            for i in report.items
        ],
        page=report.page,
        page_size=report.page_size,
        total_items=report.total_items,
        complete=report.complete,
        population=InspectionFindingReportPopulationResponse(
            read_record_count=p.read_record_count,
            readable_count=p.readable_count,
            issue_row_count=p.issue_row_count,
        ),
        data_issues=InspectionFindingReportDataIssuesResponse(
            issue_defect_counts=d.issue_defect_counts,
            issue_defect_counts_are_occurrences=True,
            issue_rows_without_usable_id=d.issue_rows_without_usable_id,
            sample_finding_ids=d.sample_finding_ids,
        ),
    )


@router.get(
    "/reports/inspection-findings",
    response_model=InspectionFindingReportResponse,
    responses=_INSPECTION_FINDINGS_ERROR_RESPONSES,
    summary="Recorded inspection findings report (one row per recorded finding)",
)
async def get_inspection_findings_report(
    asset_type: InspectionFindingReportAssetType | None = Query(default=None),
    created_from: str | None = Query(
        default=None,
        description="Inclusive Asia/Bangkok calendar date of created_at, YYYY-MM-DD.",
    ),
    created_to: str | None = Query(
        default=None,
        description="Inclusive Asia/Bangkok calendar date of created_at, YYYY-MM-DD.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: InspectionFindingReportService = Depends(get_inspection_finding_report_service),
) -> InspectionFindingReportResponse:
    # Authorization before any repository read: a denied request reads nothing.
    require_capability(
        context, CAN_VIEW, "รายงานข้อบกพร่องจากการตรวจเช็ค (inspection findings report)"
    )
    report = await service.get_report(
        asset_type=asset_type.value if asset_type is not None else None,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return _finding_report_response(report)
