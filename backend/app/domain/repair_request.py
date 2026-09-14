"""Repair Request — a reported problem waiting for Maintenance review.

Core Demo Fixes Delta REV05 sections 2/3: overrides the earlier behavior
that let a Driver/technician/Inspection/PM flow create a Repair Work
Order (`RPR-xxxx`) directly. A Repair Request is NOT a Repair Work Order:
- Repair Request = reported problem waiting for Maintenance review
  (`request_status="PENDING"`).
- Repair Work Order = the accepted/open occurrence (`Repair`,
  `RPR-xxxx`), created only once an authorized Maintenance actor converts
  a pending request (or opens one directly with no request at all).

Backs the live `repair_request` sheet exactly as REV05 gives it — do not
add or rename columns here. `request_status` stays a plain,
unconstrained string (mirrors `MaterialRequest.request_status`'s own
precedent) rather than a fabricated final state machine: REV05 explicitly
says to leave rejection/cancellation/duplicate states TBD rather than
invent them, so only `PENDING` and `CONVERTED` are given real meaning by
`RepairRequestService` below.

`reporter_type`/`report_channel` stay plain, unconstrained strings for
the same reason — no rigid vocabulary is approved for either.
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel

REPAIR_REQUEST_STATUS_PENDING = "PENDING"
REPAIR_REQUEST_STATUS_CONVERTED = "CONVERTED"

# ---------------------------------------------------------------------------
# Core Demo Fixes Delta REV06 section 15 (P1 — defect provenance
# traceability): the live `repair_request` sheet's fixed 16-column schema
# (see `RepairRequest` below) has no dedicated column for "which Finding or
# PM Work Result this request originated from". REV06 does NOT add one —
# the schema stays exactly the given 16 columns. Instead, the ONLY
# currently-approved originating-defect source types (`FINDING`, from a
# non-Maintenance Inspection Finding, and `PM_RESULT`, from a PM defect —
# section 4's approved routing) are encoded as a strict, anchored,
# machine-readable prefix inside `note_th` itself:
#
#     [[SRC:<TYPE>:<ID>]]\n<original user note, if any>
#
# This is the ONE place in the codebase that builds or parses that prefix
# ("parsed centrally") — every other module reads/writes `note_th` as a
# plain string and never needs to know this convention exists.
# `RepairRequestService` is the sole caller of both functions below: it
# encodes on `create()` (when the reporter names an originating Finding/PM
# defect) and decodes on every read (`get`/`list_pending`/the initial read
# inside `convert`), so nothing downstream — including the API response
# schema — ever sees the raw marker.
#
# Why this cannot collide with a normal user note: the pattern is anchored
# at position 0 and requires the literal, ASCII bracket sequence
# "[[SRC:" immediately followed by an uppercase/underscore type token, a
# colon, an id with no "]"/newline, then "]]" — no real symptom
# description (Thai or English free text) written by a driver/technician
# starts this way. A note that happens not to match the pattern is simply
# returned unchanged, with no source decoded (fail-safe: worst case is
# "no provenance found", never a corrupted note).
_PROVENANCE_PATTERN = re.compile(r"^\[\[SRC:(?P<type>[A-Z_]+):(?P<id>[^\]\n]+)\]\]\n?")

# Only these two originating-defect source types are approved by section 4's
# routing ("Non-Maintenance Inspection defect: Finding -> Repair Request";
# "PM defect: PM Task/PM Result -> Repair Request"). `REPAIR_REQUEST`/
# `MANUAL`/`ALERT`/`INSPECTION_RESULT` are deliberately not accepted here —
# a Repair Request's own identity already IS the request, and the other
# values are not part of the approved non-Maintenance reporting routes.
REPAIR_REQUEST_DEFECT_SOURCE_TYPES = frozenset({"FINDING", "PM_RESULT"})


def encode_provenance_note(
    source_type: str | None, source_id: str | None, note_th: str | None
) -> str | None:
    """Build the persisted `note_th` value. No-op (returns `note_th`
    unchanged) when no originating defect is named — the overwhelming
    majority of Repair Requests (a driver's own free-text report has
    neither)."""
    if source_type is None or source_id is None:
        return note_th
    marker = f"[[SRC:{source_type}:{source_id}]]"
    if note_th:
        return f"{marker}\n{note_th}"
    return marker


def decode_provenance_note(raw_note: str | None) -> tuple[str | None, str | None, str | None]:
    """Inverse of `encode_provenance_note`: returns
    `(source_type, source_id, clean_note_th)`, where `clean_note_th` is
    exactly what the reporter actually typed (the marker stripped) —
    `None` when nothing follows the marker, matching how an absent note
    is represented everywhere else in this codebase. `(None, None,
    raw_note)` when `raw_note` does not match the marker pattern at all
    (including `None`/plain-text notes, which is the common case)."""
    if not raw_note:
        return None, None, raw_note
    match = _PROVENANCE_PATTERN.match(raw_note)
    if not match:
        return None, None, raw_note
    remainder = raw_note[match.end() :]
    return match.group("type"), match.group("id"), (remainder or None)


class RepairRequest(BaseModel):
    """One row of the live `repair_request` sheet — field names match its
    columns exactly."""

    repair_request_id: str
    vehicle_id: str
    reported_at: datetime
    reported_by_user_id: str | None = None
    reporter_type: str | None = None
    reporter_driver_id: str | None = None
    reporter_name_snapshot_th: str | None = None
    report_channel: str | None = None
    symptom_th: str | None = None
    priority: str | None = None
    request_status: str = REPAIR_REQUEST_STATUS_PENDING
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    repair_id: str | None = None
    converted_at: datetime | None = None
    note_th: str | None = None
    meter_snapshot_id: str | None = None
    """CORE-G01 automatic machine-state snapshot captured at report time
    (REV05 section 4) — domain-only convenience field, NOT one of the
    `repair_request` sheet's given 16 columns (it has no reserved column
    for this). `MockRepository` persists it so the demo's Maintenance
    review queue can show it; `GoogleSheetsRepository` honestly returns
    `None` here until a column is approved (documented, reversible gap —
    see docs/phase-results/core-demo-fixes-result.md REV05 section)."""
    source_type: str | None = None
    source_id: str | None = None
    """REV06 section 15: the originating Finding/PM Work Result this
    request was reported from, when any — domain-only convenience fields
    decoded from `note_th` by `RepairRequestService` (see
    `decode_provenance_note` above), NOT sheet columns. By the time any
    caller outside `RepairRequestService` sees a `RepairRequest`, `note_th`
    above is already the clean, decoded user note and these two fields
    carry the provenance instead — the raw `[[SRC:...]]` marker is never
    exposed past that one service."""


__all__ = [
    "RepairRequest",
    "REPAIR_REQUEST_STATUS_PENDING",
    "REPAIR_REQUEST_STATUS_CONVERTED",
    "REPAIR_REQUEST_DEFECT_SOURCE_TYPES",
    "encode_provenance_note",
    "decode_provenance_note",
]
