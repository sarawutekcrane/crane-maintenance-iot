"""R2 Batch R2f-b — request / response models of the Personnel ↔ Technician
link routes. Every request is `extra="forbid"`: actor, timestamps, test flags,
request id, fingerprint and the history event kind are server-set (any of them
in a body is a 422). Ids are opaque exact text; a blank expected value means
"I expect no current link". The R2f-a relationship GET models are unchanged.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

LinkOperation = Literal["LINK", "UNLINK", "RELINK"]
LinkEventKind = Literal["LINK", "UNLINK", "RELINK", "RECONCILIATION"]
LinkConsistency = Literal["NO_HISTORY", "CONSISTENT", "MISMATCH"]


class PersonnelTechnicianLinkRequest(BaseModel):
    """LINK / RELINK need `new_technician_id`; UNLINK takes none (blank or absent)."""

    model_config = ConfigDict(extra="forbid")

    operation: LinkOperation
    expected_technician_id: str
    new_technician_id: str | None = None
    reason_th: str


class PersonnelTechnicianLinkReconcileRequest(BaseModel):
    """Recovery only (MISMATCH): restores the latest history target, never a client-chosen one."""

    model_config = ConfigDict(extra="forbid")

    expected_technician_id: str
    related_request_id: str
    reason_th: str


class PersonnelTechnicianLinkChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    link_event_id: str
    previous_technician_id: str | None
    new_technician_id: str | None
    relationship_consistency_after: LinkConsistency


class LinkNoOpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[False]


class LinkReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    replayed: Literal[True]
    record_ids: list[str]


class PersonnelTechnicianLinkEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_event_id: str
    event_kind: LinkEventKind
    previous_technician_id: str | None
    new_technician_id: str | None
    recorded_at: str
    recorded_by: str
    reason_th: str
    request_id: str


class PersonnelTechnicianLinkHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personnel_id: str
    current_technician_id: str | None
    latest_history_technician_id: str | None
    relationship_consistency: LinkConsistency
    events: list[PersonnelTechnicianLinkEventResponse]
