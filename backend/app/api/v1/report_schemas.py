"""Response schemas for Phase 7 reporting views (Batch 7D2: certificate
expiry report; Batch 7E2: recorded inspection findings report). Every
model forbids extra fields so nothing beyond the approved contract (no
storage_ref, alert_lead_days, is_critical, raw invalid cell contents or
unrelated data) can leak into a response."""
from __future__ import annotations

from datetime import date, datetime
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


# ---------------------------------------------------------------------------
# Batch 7E2: recorded inspection findings report
# ---------------------------------------------------------------------------


class InspectionFindingReportAssetType(str, Enum):
    VEHICLE = "VEHICLE"
    EQUIPMENT = "EQUIPMENT"


class InspectionFindingReportFilterResponse(BaseModel):
    """Echo of the applied filter. Dates are inclusive Asia/Bangkok
    calendar dates of `created_at`; null means unbounded."""

    model_config = ConfigDict(extra="forbid")

    asset_type: InspectionFindingReportAssetType | None
    created_from: date | None
    created_to: date | None


class InspectionFindingReportItemResponse(BaseModel):
    """One readable RECORDED finding (history, not verified outstanding
    work). Identifier/title texts are the original stored text, untrimmed
    (may be "" or whitespace; flagged). `created_at` is the recorded
    submission time normalized to UTC. `is_critical` is never returned."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    inspection_id: str
    result_id: str
    asset_type: InspectionFindingReportAssetType
    asset_id: str
    item_title: str
    recorded_status: Literal["OPEN", "ENDED"]
    created_at: datetime
    flags: list[
        Literal["DUPLICATE_FINDING_ID", "BLANK_FINDING_ID", "BLANK_INSPECTION_ID", "BLANK_RESULT_ID"]
    ]


class InspectionFindingReportPopulationResponse(BaseModel):
    """Whole-read disclosure, independent of filters and pagination:
    read_record_count = readable_count + issue_row_count (non-phantom
    rows). Report disclosures, not management KPIs."""

    model_config = ConfigDict(extra="forbid")

    read_record_count: int = Field(ge=0)
    readable_count: int = Field(ge=0)
    issue_row_count: int = Field(ge=0)


InspectionFindingDefectCode = Literal[
    "UNSUPPORTED_TEXT_VALUE",
    "BLANK_ASSET_TYPE",
    "UNRECOGNIZED_ASSET_TYPE",
    "BLANK_ASSET_ID",
    "BLANK_STATUS",
    "UNRECOGNIZED_STATUS",
    "MISSING_CREATED_AT",
    "INVALID_CREATED_AT",
    "CREATED_AT_WITHOUT_TIMEZONE",
    "UNREPRESENTABLE_CREATED_AT",
    "UNMAPPABLE_ROW",
]


class InspectionFindingReportDataIssuesResponse(BaseModel):
    """`issue_defect_counts` counts DIAGNOSED defect occurrences among
    issue rows (canonical key order; codes may overlap on one row; never
    a record count)."""

    model_config = ConfigDict(extra="forbid")

    issue_defect_counts: dict[InspectionFindingDefectCode, int]
    issue_defect_counts_are_occurrences: Literal[True]
    issue_rows_without_usable_id: int = Field(ge=0)
    sample_finding_ids: list[str] = Field(max_length=20)


class InspectionFindingReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: Literal["Asia/Bangkok"]
    filter: InspectionFindingReportFilterResponse
    items: list[InspectionFindingReportItemResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total_items: int = Field(ge=0)
    complete: bool
    population: InspectionFindingReportPopulationResponse
    data_issues: InspectionFindingReportDataIssuesResponse


# ---------------------------------------------------------------------------
# R8 (R8-09, Owner source approval 2026-11-18): fleet part-lifetime-due report
# ---------------------------------------------------------------------------

PartLifetimeItemStatus = Literal["DUE", "NOT_DUE", "UNKNOWN", "NO_APPLICABLE_RULE"]


class PartLifetimeDueRuleResponse(BaseModel):
    """One evaluated rule, copied from the R6 status service (no new formula)."""

    lifetime_rule_id: str | None
    due_action: str | None
    trigger_type: str | None
    status: str
    next_due_value: float | None = None
    next_due_date: str | None = None
    reasons: list[str]


class PartLifetimeDueItemResponse(BaseModel):
    vehicle_id: str
    machine_no: str | None
    target_type: Literal["PART_INSTANCE", "POSITION_LIFETIME"]
    target_id: str
    part_id: str | None
    position_code: str | None
    status: PartLifetimeItemStatus
    rules: list[PartLifetimeDueRuleResponse]


class PartLifetimeDueReportResponse(BaseModel):
    """Vehicle-hosted part lifetime results of one page of vehicles (paging is over
    vehicles, so each page makes a bounded number of reads). Item status: DUE when
    any rule is DUE; UNKNOWN when any rule is UNKNOWN (never shown as not due);
    NOT_DUE only when every rule is NOT_DUE; NO_APPLICABLE_RULE when no rule applies.
    `vehicles_out_of_scope` counts vehicles of this page outside the server data
    scope (disclosed, never silently hidden)."""

    status_filter: PartLifetimeItemStatus | None
    branch_id: str | None
    page: int
    page_size: int
    total_vehicles: int
    vehicles_evaluated: int
    vehicles_out_of_scope: int
    items: list[PartLifetimeDueItemResponse]
