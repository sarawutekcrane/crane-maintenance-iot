"""Phase 7 Batch 7O2a — vehicle registration rules (pure; no I/O).

Contract: Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2 §4.3 (RK1), §4.5
and §7.7 (registration-history rows). Registration text is stored and
displayed exactly as entered; `registration_key` is used ONLY to compare
registrations for duplicates and is never written back or shown.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime

REGISTRATION_KEY_VERSION = "RK1"
MAX_REGISTRATION_LENGTH = 50

# RK1 (contract §4.3). Owner-approved examples: "กข 1234" == "กข-1234" ==
# "กข ๑๒๓๔" within one province; "0012" != "12" (no numeric conversion).
# The other removals are the documented engineering defaults (E3).
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_REMOVED = frozenset("-.‐‑–−​﻿")


def registration_key(text: str) -> str:
    """RK1 comparison key: NFC, Thai digits -> ASCII, drop every
    `str.isspace()` character, '-', U+2010, U+2011, U+2013, U+2212, '.',
    U+200B and U+FEFF, then casefold. Nothing else is folded (no numeric
    conversion, no other punctuation, no full-width folding)."""
    folded = unicodedata.normalize("NFC", text).translate(_THAI_DIGITS)
    return "".join(ch for ch in folded if not ch.isspace() and ch not in _REMOVED).casefold()


def pair_is_valid(registration_no: str | None, province_code: str | None) -> bool:
    """The normal pair rules (contract §4.4 step 1): text 1-50 characters
    with a non-empty RK1 key, or null; a province never without text."""
    if registration_no is None:
        return province_code is None
    return 0 < len(registration_no) <= MAX_REGISTRATION_LENGTH and registration_key(registration_no) != ""


# ---------------------------------------------------------------------------
# vehicle_registration_history rows (contract §4.5 columns, §7.7 matrix)
# ---------------------------------------------------------------------------

REGISTRATION_HISTORY_COLUMNS: tuple[str, ...] = (
    "change_id",
    "vehicle_id",
    "change_kind",
    "old_registration_no",
    "old_registration_province_code",
    "new_registration_no",
    "new_registration_province_code",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "related_request_id",
    "accepted_exceptions",
    "note_th",
    "is_test_data",
    "test_batch_id",
)

CHANGE_KIND_CHANGE = "CHANGE"
CHANGE_KINDS = (CHANGE_KIND_CHANGE, "RECONCILIATION_APPLY_RECORDED", "RECONCILIATION_ACCEPT_MASTER")
ACCEPTED_EXCEPTION_CODES = ("REFERENCE_UNKNOWN_ACCEPTED", "REFERENCE_INACTIVE_ACCEPTED", "EXISTING_DUPLICATE_PAIR")

CONSISTENCY_CONSISTENT = "CONSISTENT"
CONSISTENCY_NO_HISTORY = "NO_HISTORY"
CONSISTENCY_MISMATCH = "MISMATCH"
CONSISTENCY_UNDETERMINED = "UNDETERMINED"

DATA_CONTEXT_TEST = "TEST"
DATA_CONTEXT_REAL = "REAL"

_CHANGE_ID = re.compile(r"VRH-([0-9a-f]{32}|[0-9]+)")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def text(value: object) -> str:
    """A cell as text: None -> "", anything else str()."""
    return "" if value is None else str(value)


def optional_text(value: object) -> str | None:
    """A cell as an optional value: blank (after strip) -> None, else the exact text."""
    raw = text(value)
    return raw if raw.strip() else None


def parse_aware(value: object) -> datetime | None:
    """An ISO 8601 instant WITH an offset, or None (blank, naive or unparseable).
    Never reinterprets a naive value."""
    raw = text(value)
    if not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _count(issues: dict[str, int], code: str) -> None:
    issues[code] = issues.get(code, 0) + 1


def validate_registration_rows(rows: Sequence[Mapping[str, object]], context: str) -> dict[str, int]:
    """Issue counts for ONE vehicle's history rows (physical order). Empty =
    valid. Total: a malformed cell becomes an issue code, never an exception.
    In the REAL context any TRUE or blank test flag is CUTOVER_INCOMPLETE."""
    issues: dict[str, int] = {}
    seen_requests: list[str] = []
    ids: list[str] = []
    for row in rows:
        kind = text(row.get("change_kind"))
        flag = text(row.get("is_test_data"))
        if context == DATA_CONTEXT_REAL and flag != "FALSE":
            _count(issues, "CUTOVER_INCOMPLETE")
        if kind not in CHANGE_KINDS:
            _count(issues, "CHANGE_KIND_INVALID")
        change_id = text(row.get("change_id"))
        ids.append(change_id)
        if not _CHANGE_ID.fullmatch(change_id):
            _count(issues, "CHANGE_ID_INVALID")
        if parse_aware(row.get("recorded_at")) is None:
            _count(issues, "RECORDED_AT_INVALID")
        if not text(row.get("recorded_by")).strip():
            _count(issues, "FIELD_REQUIRED:recorded_by")
        request_id = text(row.get("request_id"))
        if not request_id.strip():
            _count(issues, "FIELD_REQUIRED:request_id")
        if not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
            _count(issues, "FINGERPRINT_INVALID")
        if flag not in ("TRUE", "FALSE", ""):
            _count(issues, "TEST_FLAG_INVALID")
        if not pair_is_valid(optional_text(row.get("new_registration_no")), optional_text(row.get("new_registration_province_code"))):
            _count(issues, "NEW_PAIR_INVALID")
        # The OLD pair records what the master held (possibly an imported,
        # malformed value); it is deliberately not re-validated.
        if kind in CHANGE_KINDS[1:] and not text(row.get("note_th")).strip():
            _count(issues, "REASON_REQUIRED")
        related = text(row.get("related_request_id"))
        if related and (kind == CHANGE_KIND_CHANGE or related not in seen_requests):
            _count(issues, "RELATED_REQUEST_DANGLING")
        accepted = [a for a in text(row.get("accepted_exceptions")).split(";") if a]
        if accepted and (kind != "RECONCILIATION_ACCEPT_MASTER" or any(a not in ACCEPTED_EXCEPTION_CODES for a in accepted)):
            _count(issues, "ACCEPTED_EXCEPTIONS_INVALID")
        if request_id and request_id in seen_requests:
            _count(issues, "REQUEST_ID_DUPLICATE")
        seen_requests.append(request_id)
    if len(ids) != len(set(ids)):
        _count(issues, "CHANGE_ID_DUPLICATE")
    return issues


_EPOCH = datetime.fromisoformat("1970-01-01T00:00:00+00:00")


def ordered_rows(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Recorded order: (recorded_at, physical row). Total: a row without a
    valid recorded_at sorts first instead of raising (validation reports it)."""
    def key(pair: tuple[int, Mapping[str, object]]) -> tuple[bool, datetime, int]:
        parsed = parse_aware(pair[1].get("recorded_at"))
        return (parsed is not None, parsed or _EPOCH, pair[0])

    return [row for _, row in sorted(enumerate(rows), key=key)]


def latest_new_pair(rows: Sequence[Mapping[str, object]]) -> tuple[str | None, str | None] | None:
    if not rows:
        return None
    last = ordered_rows(rows)[-1]
    return optional_text(last.get("new_registration_no")), optional_text(last.get("new_registration_province_code"))


def registration_consistency(
    rows: Sequence[Mapping[str, object]], master_pair: tuple[str | None, str | None] | None
) -> str:
    """NO_HISTORY (no rows), CONSISTENT (latest new pair == master pair),
    MISMATCH, or UNDETERMINED when a registration column is not in the
    master schema (`master_pair` None)."""
    if not rows:
        return CONSISTENCY_NO_HISTORY
    if master_pair is None:
        return CONSISTENCY_UNDETERMINED
    return CONSISTENCY_CONSISTENT if latest_new_pair(rows) == master_pair else CONSISTENCY_MISMATCH


def registration_history_revision(rows: Sequence[Mapping[str, object]]) -> str:
    """RHR1 token: SHA-256 over the vehicle's rows (contract columns only,
    canonical JSON, recorded order), first 20 hex characters."""
    canonical = [{c: text(row.get(c)) for c in REGISTRATION_HISTORY_COLUMNS} for row in ordered_rows(rows)]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return f"RHR1-{digest[:20]}"
