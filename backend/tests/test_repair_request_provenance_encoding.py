"""Unit tests for the pure `note_th` provenance marker functions (REV06
section 15) — the mechanism `RepairRequestService` uses to preserve
Finding/PM defect provenance without changing the live `repair_request`
sheet's fixed 16-column schema. See `app.domain.repair_request` module
docstring for the full design rationale.
"""
from __future__ import annotations

from app.domain.repair_request import decode_provenance_note, encode_provenance_note


def test_encode_is_a_no_op_without_a_named_source() -> None:
    assert encode_provenance_note(None, None, "อาการปกติ") == "อาการปกติ"
    assert encode_provenance_note(None, None, None) is None


def test_encode_then_decode_round_trips_exactly() -> None:
    encoded = encode_provenance_note("FINDING", "FND-0007", "พบรอยรั่ว")
    assert encoded == "[[SRC:FINDING:FND-0007]]\nพบรอยรั่ว"
    source_type, source_id, note = decode_provenance_note(encoded)
    assert (source_type, source_id, note) == ("FINDING", "FND-0007", "พบรอยรั่ว")


def test_encode_then_decode_with_no_user_note_leaves_note_none() -> None:
    encoded = encode_provenance_note("PM_RESULT", "PMR-0003", None)
    assert encoded == "[[SRC:PM_RESULT:PMR-0003]]"
    source_type, source_id, note = decode_provenance_note(encoded)
    assert (source_type, source_id, note) == ("PM_RESULT", "PMR-0003", None)


def test_decode_of_plain_text_never_matches() -> None:
    for text in (
        None,
        "",
        "เครื่องยนต์มีเสียงดัง",
        "อาการ [[SRC:FINDING:FND-1]] อยู่กลางข้อความ",  # not anchored at position 0
        "SRC:FINDING:FND-1",  # missing the [[ ]] delimiters entirely
    ):
        source_type, source_id, note = decode_provenance_note(text)
        assert source_type is None
        assert source_id is None
        assert note == text


def test_decode_rejects_a_malformed_marker_and_returns_the_raw_text_unchanged() -> None:
    # Missing closing bracket — must not partially match / corrupt the note.
    malformed = "[[SRC:FINDING:FND-1 เครื่องยนต์มีเสียงดัง"
    source_type, source_id, note = decode_provenance_note(malformed)
    assert source_type is None
    assert source_id is None
    assert note == malformed


def test_marker_id_cannot_contain_a_closing_bracket_or_newline() -> None:
    # The id component is deliberately restricted so the marker can never
    # be ambiguous about where it ends.
    source_type, source_id, note = decode_provenance_note("[[SRC:FINDING:FND]1]]\nrest")
    # "FND]1" is not a valid id (contains "]"), so this does not match as
    # a whole and is returned unchanged — never silently truncated.
    assert source_type is None
    assert note == "[[SRC:FINDING:FND]1]]\nrest"
