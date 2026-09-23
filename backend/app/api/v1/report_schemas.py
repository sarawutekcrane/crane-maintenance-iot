"""Response schemas for Phase 7 reporting views (Batch 7D2: certificate
expiry report). Every model forbids extra fields so nothing beyond the
approved contract (no storage_ref, alert_lead_days, raw invalid cell
contents or unrelated certificate data) can leak into a response."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CertificateReportMode(str, Enum):
    RANGE = "RANGE"
    MISSING_EXPIRY_DATE = "MISSING_EXPIRY_DATE"


class CertificateEffectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class CertificateExpiryReportFilterResponse(BaseModel):
    """Echo of the applied filter. `expiry_to_resolved` is today's Bangkok
    date when `expiry_to` was omitted (`expiry_to_is_default=true`). For
    MISSING_EXPIRY_DATE every date field is null and
    `expiry_to_is_default` is false."""

    model_config = ConfigDict(extra="forbid")

    mode: CertificateReportMode
    expiry_from: date | None
    expiry_to_requested: date | None
    expiry_to_resolved: date | None
    expiry_to_is_default: bool
    effective_status: CertificateEffectiveStatus | None


class CertificateExpiryReportItemResponse(BaseModel):
    """One readable in-scope certificate RECORD (not a vehicle). Flags are
    observations from the data read, not legal validity, compliance or a
    proven replacement relationship."""

    model_config = ConfigDict(extra="forbid")

    certificate_id: str
    vehicle_id: str
    certificate_type_code: str | None
    certificate_type_name_th: str | None
    document_no: str | None
    expiry_date: date | None
    stored_status: Literal["ACTIVE", "EXPIRED"]
    effective_status: CertificateEffectiveStatus
    expiry_position: Literal["BEFORE_TODAY", "TODAY", "AFTER_TODAY", "NO_EXPIRY_DATE"]
    flags: list[
        Literal[
            "SAME_TYPE_ACTIVE_EXISTS",
            "MULTIPLE_ACTIVE_SAME_TYPE",
            "STORED_ACTIVE_PAST_EXPIRY",
            "STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY",
            "LINK_PRESENT_ON_NON_REPLACED",
            "DUPLICATE_CERTIFICATE_ID",
            "BLANK_CERTIFICATE_ID",
            "BLANK_VEHICLE_ID",
        ]
    ]


class CertificateExpiryReportPopulationResponse(BaseModel):
    """Whole-read disclosure, independent of filters and pagination.
    read_record_count = in_scope_count + excluded_replaced_count +
    excluded_status_blank_count + issue_row_count. These are report
    disclosures, not management KPIs."""

    model_config = ConfigDict(extra="forbid")

    read_record_count: int = Field(ge=0)
    in_scope_count: int = Field(ge=0)
    in_scope_with_expiry_date_count: int = Field(ge=0)
    in_scope_without_expiry_date_count: int = Field(ge=0)
    excluded_replaced_count: int = Field(ge=0)
    excluded_status_blank_count: int = Field(ge=0)
    issue_row_count: int = Field(ge=0)
    excluded_rows_with_other_defects: int = Field(ge=0)
    replaced_link_observations: int = Field(ge=0)


class CertificateExpiryReportDataIssuesResponse(BaseModel):
    """`issue_defect_counts` counts defect OCCURRENCES among issue rows;
    codes may overlap on one row and must never be summed as a record
    count."""

    model_config = ConfigDict(extra="forbid")

    issue_defect_counts: dict[
        Literal["UNRECOGNIZED_STATUS", "INVALID_EXPIRY_DATE", "UNMAPPABLE_ROW"], int
    ]
    issue_defect_counts_are_occurrences: Literal[True]
    issue_rows_without_usable_id: int = Field(ge=0)
    sample_certificate_ids: list[str] = Field(max_length=20)


class CertificateExpiryReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_date: date
    timezone: Literal["Asia/Bangkok"]
    filter: CertificateExpiryReportFilterResponse
    items: list[CertificateExpiryReportItemResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total_items: int = Field(ge=0)
    complete: bool
    population: CertificateExpiryReportPopulationResponse
    data_issues: CertificateExpiryReportDataIssuesResponse
