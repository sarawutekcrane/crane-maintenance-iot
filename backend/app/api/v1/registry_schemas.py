"""Phase 7 Batch 7O2a — response models of the registry read API (contract
Final Rev2 §4.5, §7.2, §7.4). The §7.1 `registry` vehicle fields live in
vehicle_schemas (the detail response refers to them)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

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


# ---- Phase 7 Batch 7O2b: registration mutations (§4.4, §4.6) ----
#
# Both request models FORBID unknown keys, so two different accepted bodies can
# never become the same request fingerprint by a key being dropped. Values are
# kept exactly as sent (no trimming). Rule checks with their own codes
# (text length, mode, reason) are made by the service, not by these models.


class RegistrationChangeRequest(BaseModel):
    """PATCH /vehicles/{vehicle_id}/registration — all four keys are required
    (each may be null)."""

    model_config = ConfigDict(extra="forbid")

    registration_no: str | None
    registration_province_code: str | None
    expected_registration_no: str | None
    expected_registration_province_code: str | None


class RegistrationReconciliationRequest(BaseModel):
    """POST /vehicles/{vehicle_id}/registration-history/reconciliations.
    `related_request_id` is optional; whether it was omitted or sent as null
    is part of the request identity (fingerprint)."""

    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    expected_registration_no: str | None
    expected_registration_province_code: str | None
    expected_history_revision: str
    # 1-500 characters is a SEMANTIC rule (422 REASON_REQUIRED, Rev2 §4.6),
    # checked by the service after body validation; only the type is checked here.
    reason_th: str | None = None
    related_request_id: str | None = None


class RegistrationChangeRecordResponse(BaseModel):
    change_id: str
    recorded_at: str
    request_id: str


class RegistrationChangedResponse(BaseModel):
    """200 for an applied change. PATCH also returns `vehicle` (built from the
    validated read plus the applied pair; no re-read)."""

    request_id: str
    changed: Literal[True]
    change: RegistrationChangeRecordResponse
    master_write: Literal["WRITTEN", "NOT_NEEDED"]
    warnings: list[str]
    vehicle: VehicleWithRegistryResponse | None = None


class RegistrationNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]
    warnings: list[str]


class RegistrationReplayResponse(BaseModel):
    """200 for a proven replay: the record exists; whether the master now
    matches it is `master_state` (the client still settles by history)."""

    request_id: str
    replayed: Literal[True]
    record_ids: list[str]
    master_state: Literal["MATCHES", "DIFFERS"]
    consistency: Literal["CONSISTENT", "NO_HISTORY", "MISMATCH"]
