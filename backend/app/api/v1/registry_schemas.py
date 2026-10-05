"""Phase 7 Batch 7O2a — response models of the registry read API (contract
Final Rev2 §4.5, §7.2, §7.4). The §7.1 `registry` vehicle fields live in
vehicle_schemas (the detail response refers to them)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.api.v1.vehicle_schemas import (  # noqa: F401  (re-exported)
    RegistryFieldResponse,
    VehicleRegistryResponse,
    VehicleWithRegistryResponse,
)

# ---- §7.2 reference lists ----


class BranchResponse(BaseModel):
    branch_id: str
    branch_name: str
    is_active: bool


class BranchListResponse(BaseModel):
    items: list[BranchResponse]


class ProvinceResponse(BaseModel):
    province_code: str
    province_name_th: str
    is_active: bool


class ProvinceListResponse(BaseModel):
    items: list[ProvinceResponse]


# ---- §7.4 branch history ----


class BranchCurrentResponse(BaseModel):
    branch_id: str | None
    source: Literal["EVENT", "BASELINE", "IMPORTED_MASTER", "NONE", "UNDETERMINED"]


class BranchBaselineResponse(BaseModel):
    branch_id: str | None
    source: Literal["IMPORTED_MASTER", "NONE"]


class BranchEventResponse(BaseModel):
    event_id: str
    in_force: bool
    head_record_id: str
    revision_no: int
    to_branch_id: str | None
    effective_at: str | None
    effective_precision: str | None
    derived_from_branch_id: str | None
    original_entry_from_branch_id: str | None
    original_entry_from_source: str | None
    head_entry_from_branch_id: str | None
    head_entry_from_source: str | None
    derived_end_at: str | None
    notes: list[str]


class BranchRecordResponse(BaseModel):
    record_id: str
    record_kind: str
    entry_operation: str
    event_id: str | None
    revision_no: int | None
    supersedes_record_id: str | None
    branch_id: str | None
    effective_at: str | None
    recorded_from_branch_id: str | None
    recorded_from_source: str | None
    recorded_at: str
    recorded_by: str
    request_id: str
    related_request_id: str | None
    reason_th: str | None
    reconciled_old_master_branch_id: str | None


class BranchHistoryResponse(BaseModel):
    asset_type: Literal["VEHICLE"]
    asset_id: str
    timeline_status: Literal["VALID", "AMBIGUOUS_ORDER"]
    current: BranchCurrentResponse
    master: RegistryFieldResponse
    consistency: Literal["CONSISTENT", "NO_HISTORY", "PROJECTION_MISMATCH", "UNDETERMINED"]
    history_revision: str
    baseline: BranchBaselineResponse | None
    events: list[BranchEventResponse]
    records: list[BranchRecordResponse]
    excluded_test_rows: int
    issues: dict[str, int]


# ---- §4.5 registration history ----


class RegistrationCurrentResponse(BaseModel):
    registration_no: RegistryFieldResponse
    registration_province: RegistryFieldResponse


class RegistrationHistoryItemResponse(BaseModel):
    change_id: str
    change_kind: str
    old_registration_no: str | None
    old_registration_province_code: str | None
    new_registration_no: str | None
    new_registration_province_code: str | None
    recorded_at: str
    recorded_by: str
    request_id: str
    related_request_id: str | None
    accepted_exceptions: list[str]
    note_th: str | None


class RegistrationHistoryResponse(BaseModel):
    vehicle_id: str
    current: RegistrationCurrentResponse
    # UNDETERMINED (engineering, §7.6): a registration column is not in the
    # master schema, so the latest row cannot be compared with the master.
    consistency: Literal["CONSISTENT", "NO_HISTORY", "MISMATCH", "UNDETERMINED"]
    history_revision: str
    items: list[RegistrationHistoryItemResponse]
    excluded_test_rows: int
    issues: dict[str, int]
