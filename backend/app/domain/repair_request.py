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

REV06.1 (independent-audit CRITICAL-2 fix, see
docs/phase-results/core-demo-fixes-result.md "DELTA REV06.1"):
`encode_provenance_note`/`decode_provenance_note` below now escape any
not-yet-validated note that would otherwise collide with the marker
format, so a `note_th` only ever decodes as trusted provenance when this
module itself built it from a `source_type`/`source_id` pair that already
passed `RepairRequestService._require_defect_source_exists`.

LEGACY REV06 NOTE MARKER IS UNTRUSTED FOR AUTHORITY: any `repair_request`
row created between REV06's ship date and this fix, whose `note_th`
decodes as `FINDING`/`PM_RESULT` provenance, cannot be distinguished by
this module alone from a row where an ordinary reporter typed
marker-shaped text before this escaping existed — the fixed 16-column
schema has no separate column recording whether `_require_defect_source_exists`
actually ran for that row. Treat any such pre-fix row's decoded
`source_type`/`source_id` as informational only, not as proof Maintenance
validated it, unless corroborated by other trusted server state (e.g. the
named Finding/PM Work Result record still exists and its own timestamp is
consistent with the request).
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
#
# REV06.1 (CRITICAL-2 fix): the pattern being "unlikely to occur naturally"
# is not the same as "impossible for a client to type on purpose". Before
# this fix, `encode_provenance_note` was a no-op whenever no *validated*
# source was given, so an ordinary `can_report_repair` actor could submit
# `note_th` already shaped like `[[SRC:FINDING:<anything>]]` (bypassing
# `RepairRequestService._require_defect_source_exists` entirely, since that
# check only runs when the client also sends `source_type`) and have it
# decoded back as if Maintenance itself had confirmed a real originating
# Finding/PM Work Result. `_escape_untrusted_note`/`_unescape_untrusted_note`
# close this: any raw, not-yet-validated note that would otherwise match
# `_PROVENANCE_PATTERN` (or that already starts with the escape character
# itself) is neutralized before it is ever persisted, so the *only* way a
# persisted `note_th` can decode as provenance is for `encode_provenance_note`
# itself to have built it from a `source_type`/`source_id` pair that already
# passed `_require_defect_source_exists`. The escape is exactly reversible,
# so a legitimate reporter's own text — even in this adversarial edge case —
# still round-trips back to precisely what they typed.
_PROVENANCE_PATTERN = re.compile(r"^\[\[SRC:(?P<type>[A-Z_]+):(?P<id>[^\]\n]+)\]\]\n?")

_UNTRUSTED_NOTE_ESCAPE = "\\"


def _escape_untrusted_note(note: str) -> str:
    """Neutralize a *not-yet-validated* note so it can never later be
    mistaken for a server-built provenance marker, while remaining exactly
    reversible via `_unescape_untrusted_note`. Only the narrow case that
    would otherwise collide (the note already starts with the escape
    character itself, or already matches `_PROVENANCE_PATTERN`) is touched
    — every ordinary note is returned byte-for-byte unchanged."""
    if note.startswith(_UNTRUSTED_NOTE_ESCAPE) or _PROVENANCE_PATTERN.match(note):
        return _UNTRUSTED_NOTE_ESCAPE + note
    return note


def _unescape_untrusted_note(note: str) -> str:
    """Inverse of `_escape_untrusted_note`."""
    if note.startswith(_UNTRUSTED_NOTE_ESCAPE):
        return note[len(_UNTRUSTED_NOTE_ESCAPE) :]
    return note

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
    """Build the persisted `note_th` value. When no *validated* originating
    defect is named (the overwhelming majority of Repair Requests — a
    driver's own free-text report has neither), `note_th` is persisted as
    the reporter's own text with any leading sequence that would otherwise
    collide with the marker format neutralized (REV06.1 CRITICAL-2 fix) —
    it is never a true no-op, precisely so that only this function's
    trusted-source branch below can ever produce text `decode_provenance_note`
    will treat as provenance."""
    if source_type is not None and source_id is not None:
        marker = f"[[SRC:{source_type}:{source_id}]]"
        if note_th:
            return f"{marker}\n{note_th}"
        return marker
    if note_th is None:
        return None
    return _escape_untrusted_note(note_th)


def decode_provenance_note(raw_note: str | None) -> tuple[str | None, str | None, str | None]:
    """Inverse of `encode_provenance_note`: returns
    `(source_type, source_id, clean_note_th)`, where `clean_note_th` is
    exactly what the reporter actually typed (the marker stripped, or any
    REV06.1 escape undone) — `None` when nothing follows a genuine marker,
    matching how an absent note is represented everywhere else in this
    codebase. `(None, None, raw_note)` when `raw_note` does not match the
    marker pattern at all (including `None`/plain-text notes, which is the
    common case) — `raw_note` here is first passed through
    `_unescape_untrusted_note` so a note that needed escaping on the way in
    still comes back exactly as the reporter typed it."""
    if not raw_note:
        return None, None, raw_note
    match = _PROVENANCE_PATTERN.match(raw_note)
    if not match:
        return None, None, _unescape_untrusted_note(raw_note)
    remainder = raw_note[match.end() :]
    return match.group("type"), match.group("id"), (remainder or None)


# ---------------------------------------------------------------------------
# meter_snapshot_id linkage (live UAT defect fix): the live `repair_request`
# sheet's fixed 16-column schema also has no dedicated column for the
# automatic CORE-G01 machine-state snapshot captured at report time (see
# `RepairRequest.meter_snapshot_id` below). Mirrors the `[[SRC:...]]`
# provenance marker above exactly — same anchored-marker + reversible-escape
# discipline — but as a SEPARATE, independently-recognized marker rather
# than folding a third field into `_PROVENANCE_PATTERN`: unlike
# source_type/source_id (a `RepairRequestService`-level concept, optional,
# encoded only when a reporter names an originating defect),
# `meter_snapshot_id` is a repository-level persistence concern — every
# backend's `create_repair_request` already receives it as its own
# parameter (`MockRepository` just stores it as a real field; only
# `GoogleSheetsRepository` has no column for it). `GoogleSheetsRepository`
# is therefore the sole caller of both functions below: it applies its own
# marker OUTERMOST around whatever `note_th` it is given (already
# source-encoded by `RepairRequestService`, or raw/plain from a direct
# repository-level caller) when writing, and strips it back off before
# returning `note_th` to any caller, so the `[[SRC:...]]` mechanics above
# stay completely unaware this layer exists — `RepairRequestService`'s own
# `decode_provenance_note` call keeps working unmodified on whatever
# `note_th` the repository hands back.
_METER_SNAPSHOT_PATTERN = re.compile(r"^\[\[MSNAP:(?P<id>[^\]\n]+)\]\]\n?")

_METER_SNAPSHOT_ESCAPE = "\\"


def _escape_meter_snapshot_lookalike(note: str) -> str:
    """Same reasoning as `_escape_untrusted_note` above, applied to the
    `[[MSNAP:...]]` marker instead: neutralizes only the narrow case that
    would otherwise let a not-yet-wrapped note collide with this marker on
    a later read, remaining exactly reversible. Independent of
    `_escape_untrusted_note`'s own pass — the two compose safely even when
    both fire on the same note (each layer only ever adds/removes exactly
    one leading escape character matching its own rule)."""
    if note.startswith(_METER_SNAPSHOT_ESCAPE) or _METER_SNAPSHOT_PATTERN.match(note):
        return _METER_SNAPSHOT_ESCAPE + note
    return note


def _unescape_meter_snapshot_lookalike(note: str) -> str:
    """Inverse of `_escape_meter_snapshot_lookalike`."""
    if note.startswith(_METER_SNAPSHOT_ESCAPE):
        return note[len(_METER_SNAPSHOT_ESCAPE) :]
    return note


def encode_meter_snapshot_link(note_th: str | None, meter_snapshot_id: str | None) -> str | None:
    """Repository-level companion to `encode_provenance_note`: the ONLY
    call `GoogleSheetsRepository.create_repair_request` needs to make
    `meter_snapshot_id` survive the frozen 16-column schema. Wraps
    whatever `note_th` it is given with `[[MSNAP:<id>]]` when a real
    snapshot id is given (the only path a real `POST /repair-requests`
    ever takes — the automatic snapshot is always captured before this is
    called); when it is not (only reachable via a direct repository-level
    call), still neutralizes any note that would otherwise be mistaken
    for this marker on a later read, mirroring `encode_provenance_note`'s
    own REV06.1 discipline: never a true no-op. A real, freshly-captured
    id is always placed at position 0 of the persisted string regardless
    of what `note_th` contains, so nothing a caller supplies through
    `note_th` can ever be mistaken for the anchored marker itself."""
    if meter_snapshot_id is None:
        if note_th is None:
            return None
        return _escape_meter_snapshot_lookalike(note_th)
    escaped_note = _escape_meter_snapshot_lookalike(note_th) if note_th else None
    marker = f"[[MSNAP:{meter_snapshot_id}]]"
    if escaped_note:
        return f"{marker}\n{escaped_note}"
    return marker


def decode_meter_snapshot_link(raw_note: str | None) -> tuple[str | None, str | None]:
    """Inverse of `encode_meter_snapshot_link`: returns
    `(meter_snapshot_id, remaining_note_th)`. `remaining_note_th` is
    exactly what `GoogleSheetsRepository.create_repair_request` was
    originally given (still source-encoded if applicable, with this
    layer's own escape undone) — `RepairRequestService`'s own
    `decode_provenance_note` call further decodes that, completely
    unaware this layer ever existed."""
    if not raw_note:
        return None, raw_note
    match = _METER_SNAPSHOT_PATTERN.match(raw_note)
    if not match:
        return None, _unescape_meter_snapshot_lookalike(raw_note)
    remainder = raw_note[match.end() :]
    if remainder:
        remainder = _unescape_meter_snapshot_lookalike(remainder)
    return match.group("id"), (remainder or None)


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
    for this). `MockRepository` persists it as a real field.
    `GoogleSheetsRepository` persists it inside `note_th`'s protected
    internal metadata envelope instead (see `encode_meter_snapshot_link`/
    `decode_meter_snapshot_link` above) — its own `create_repair_request`/
    `get_repair_request`/etc. transparently round-trip it there, never
    exposing the marker past that repository."""
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
    "encode_meter_snapshot_link",
    "decode_meter_snapshot_link",
]
