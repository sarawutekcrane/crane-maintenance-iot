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


# ---------------------------------------------------------------------------
# R2 Batch R2f-c — Personnel ↔ User Account link (the linked user_id is the
# SUBJECT; the actor is server-set). No account field other than user_id
# appears anywhere.
# ---------------------------------------------------------------------------


class PersonnelAccountLinkRequest(BaseModel):
    """LINK / RELINK need `new_user_id`; UNLINK takes none (blank or absent)."""

    model_config = ConfigDict(extra="forbid")

    operation: LinkOperation
    expected_user_id: str
    new_user_id: str | None = None
    reason_th: str


class PersonnelAccountLinkReconcileRequest(BaseModel):
    """Recovery only (MISMATCH): restores the latest history target, never a client-chosen one."""

    model_config = ConfigDict(extra="forbid")

    expected_user_id: str
    related_request_id: str
    reason_th: str


class PersonnelAccountLinkChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    link_event_id: str
    previous_user_id: str | None
    new_user_id: str | None
    relationship_consistency_after: LinkConsistency


class PersonnelAccountLinkEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_event_id: str
    event_kind: LinkEventKind
    previous_user_id: str | None
    new_user_id: str | None
    recorded_at: str
    recorded_by: str
    reason_th: str
    request_id: str


class PersonnelAccountLinkHistoryResponse(BaseModel):
    """`user_ids_visible` is false for a caller without can_link_personnel_account:
    every user id field is then null because it is REDACTED, not because it is
    unset (Final Contract C1 §16)."""

    model_config = ConfigDict(extra="forbid")

    personnel_id: str
    user_ids_visible: bool
    current_user_id: str | None
    latest_history_user_id: str | None
    relationship_consistency: LinkConsistency
    events: list[PersonnelAccountLinkEventResponse]


# ---------------------------------------------------------------------------
# R2 Batch R2f-e — Personnel ↔ Driver identity link. The stable driver_id is
# visible to can_view callers; no other Driver field (name, phone, licence,
# expiry, status, note) appears anywhere, and request_fingerprint is never
# returned.
# ---------------------------------------------------------------------------


class PersonnelDriverLinkRequest(BaseModel):
    """LINK / RELINK need `new_driver_id`; UNLINK takes none (blank or absent)."""

    model_config = ConfigDict(extra="forbid")

    operation: LinkOperation
    expected_driver_id: str
    new_driver_id: str | None = None
    reason_th: str


class PersonnelDriverLinkReconcileRequest(BaseModel):
    """Recovery only (MISMATCH): restores the latest history target, never a client-chosen one."""

    model_config = ConfigDict(extra="forbid")

    expected_driver_id: str
    related_request_id: str
    reason_th: str


class PersonnelDriverLinkChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    link_event_id: str
    previous_driver_id: str | None
    new_driver_id: str | None
    relationship_consistency_after: LinkConsistency


class PersonnelDriverLinkEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_event_id: str
    event_kind: LinkEventKind
    previous_driver_id: str | None
    new_driver_id: str | None
    recorded_at: str
    recorded_by: str
    reason_th: str
    request_id: str


class PersonnelDriverLinkHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personnel_id: str
    current_driver_id: str | None
    latest_history_driver_id: str | None
    relationship_consistency: LinkConsistency
    events: list[PersonnelDriverLinkEventResponse]
