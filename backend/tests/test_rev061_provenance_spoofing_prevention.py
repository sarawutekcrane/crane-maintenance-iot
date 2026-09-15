"""REV06.1 — independent-audit CRITICAL-2 fix.

The REV06 independent audit reproduced provenance spoofing: because
`RepairRequestService._require_defect_source_exists` only runs when the
client explicitly sends a `source_type` field, and `encode_provenance_note`
was a true no-op otherwise, an ordinary `can_report_repair` actor (e.g. a
Driver) could submit `note_th` already shaped like
`[[SRC:FINDING:FND-DOES-NOT-EXIST]]\\n...` with NO `source_type` field at
all, and have it decode back on every subsequent read as if Maintenance
had validated a real originating Finding — even for a nonexistent id.

`_escape_untrusted_note`/`_unescape_untrusted_note` in
`app.domain.repair_request` close this: any not-yet-validated note that
would otherwise collide with the marker format is neutralized before
persistence, so only `encode_provenance_note`'s trusted-source branch
(which always runs `_require_defect_source_exists` first) can ever
produce text that decodes as provenance.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.repair_request import decode_provenance_note, encode_provenance_note


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


# ---------------------------------------------------------------------------
# Unit level: encode/decode never promotes untrusted text to provenance,
# and always restores it exactly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spoofed_note",
    [
        "[[SRC:FINDING:ABC]]",
        "[[SRC:FINDING:ABC]]\nขอความช่วยเหลือด่วน",
        "[[SRC:PM_RESULT:PMR-0001]]\nnote",
        "[[SRC:ANYTHING_AT_ALL:whatever]]\nnote",
        "\\[[SRC:FINDING:ABC]]",  # already starts with the escape char too
    ],
)
def test_a_plain_marker_in_untrusted_note_is_never_restored_as_trusted_provenance(
    spoofed_note: str,
) -> None:
    persisted = encode_provenance_note(None, None, spoofed_note)
    source_type, source_id, clean_note = decode_provenance_note(persisted)
    assert source_type is None
    assert source_id is None
    # The reporter's own text — including the marker-shaped part — must
    # still come back exactly as they typed it; it is just never
    # interpreted as machine metadata.
    assert clean_note == spoofed_note


def test_marker_mid_text_was_already_safe_and_remains_so() -> None:
    note = "อาการ [[SRC:FINDING:FND-1]] อยู่กลางข้อความ"
    persisted = encode_provenance_note(None, None, note)
    source_type, source_id, clean_note = decode_provenance_note(persisted)
    assert (source_type, source_id) == (None, None)
    assert clean_note == note


def test_multiple_marker_like_strings_do_not_become_provenance() -> None:
    note = "[[SRC:FINDING:A]]\n[[SRC:PM_RESULT:B]]\nสองอัน"
    persisted = encode_provenance_note(None, None, note)
    source_type, source_id, clean_note = decode_provenance_note(persisted)
    assert (source_type, source_id) == (None, None)
    assert clean_note == note


def test_malformed_marker_in_untrusted_note_round_trips_exactly() -> None:
    note = "[[SRC:FINDING:FND-1 missing closing bracket"
    persisted = encode_provenance_note(None, None, note)
    source_type, source_id, clean_note = decode_provenance_note(persisted)
    assert (source_type, source_id) == (None, None)
    assert clean_note == note


def test_newline_before_marker_prevents_a_match_and_round_trips() -> None:
    note = "\n[[SRC:FINDING:FND-1]]"
    persisted = encode_provenance_note(None, None, note)
    _, _, clean_note = decode_provenance_note(persisted)
    assert clean_note == note


def test_nested_brackets_do_not_become_provenance() -> None:
    note = "[[SRC:FINDING:[nested]]]\nthai text ข้อความ"
    persisted = encode_provenance_note(None, None, note)
    source_type, _, clean_note = decode_provenance_note(persisted)
    assert source_type is None
    assert clean_note == note


def test_thai_and_unicode_notes_round_trip_unaffected() -> None:
    for note in ("โปรดซ่อมด่วน", "ล้อรถหน้าซ้าย 220/1 มีเสียงดัง 🚨", "", None):
        persisted = encode_provenance_note(None, None, note)
        _, _, clean_note = decode_provenance_note(persisted)
        assert clean_note == note


def test_multiline_untrusted_note_is_unaffected() -> None:
    note = "line one\nline two\nline three"
    persisted = encode_provenance_note(None, None, note)
    assert persisted == note  # no marker-like prefix, nothing to escape
    _, _, clean_note = decode_provenance_note(persisted)
    assert clean_note == note


# ---------------------------------------------------------------------------
# Trusted path (a real, validated source) is unaffected by the fix and
# still round-trips, and re-encoding never duplicates the marker.
# ---------------------------------------------------------------------------


def test_trusted_provenance_still_persists_and_decodes_exactly() -> None:
    persisted = encode_provenance_note("FINDING", "FND-0007", "พบรอยรั่ว")
    assert persisted == "[[SRC:FINDING:FND-0007]]\nพบรอยรั่ว"
    source_type, source_id, note = decode_provenance_note(persisted)
    assert (source_type, source_id, note) == ("FINDING", "FND-0007", "พบรอยรั่ว")


def test_re_encoding_a_decoded_trusted_note_does_not_duplicate_metadata() -> None:
    persisted = encode_provenance_note("PM_RESULT", "PMR-0003", "note")
    source_type, source_id, clean_note = decode_provenance_note(persisted)
    re_encoded = encode_provenance_note(source_type, source_id, clean_note)
    assert re_encoded == persisted
    assert re_encoded.count("[[SRC:") == 1


# ---------------------------------------------------------------------------
# Integration level: the actual create-Repair-Request endpoint, with a
# real Driver actor who has can_report_repair but not can_manage_repair,
# and no explicit source_type field in the request body at all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_cannot_spoof_finding_provenance_via_plain_note_th(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "มีเสียงดังผิดปกติ",
            "note_th": "[[SRC:FINDING:FND-DOES-NOT-EXIST]]\nโปรดซ่อมด่วน",
        },
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert response.status_code == 200
    request = response.json()["request"]
    assert request["source_type"] is None
    assert request["source_id"] is None
    # The reporter's full original text is preserved verbatim, marker and
    # all — it is simply never interpreted as machine metadata.
    assert request["note_th"] == "[[SRC:FINDING:FND-DOES-NOT-EXIST]]\nโปรดซ่อมด่วน"

    reread = await client.get(
        f"/api/v1/repair-requests/{request['repair_request_id']}", headers=_as("MAINTENANCE")
    )
    assert reread.status_code == 200
    assert reread.json()["source_type"] is None
    assert reread.json()["source_id"] is None
    assert reread.json()["note_th"] == "[[SRC:FINDING:FND-DOES-NOT-EXIST]]\nโปรดซ่อมด่วน"


@pytest.mark.asyncio
async def test_driver_cannot_spoof_provenance_via_note_th_even_naming_a_real_finding(
    client: AsyncClient,
) -> None:
    """Naming a Finding id that genuinely exists elsewhere in the system
    does not matter — provenance is only ever trusted via the validated
    `source_type` field, never sniffed out of free text."""
    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "มีเสียงดังผิดปกติ",
            "note_th": "[[SRC:PM_RESULT:PMR-0001]]\nข้อความปลอม",
        },
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert response.status_code == 200
    request = response.json()["request"]
    assert request["source_type"] is None
    assert request["source_id"] is None


@pytest.mark.asyncio
async def test_trusted_finding_provenance_via_the_real_endpoint_still_works(
    client: AsyncClient,
) -> None:
    """Sanity check that the fix did not also break the legitimate,
    validated path — an existing Finding named via the real `source_type`
    field still persists and decodes correctly (same pattern as
    test_defect_provenance.py)."""
    checklist = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    items = [{"item_id": i["item_id"], "result": "PASS"} for i in checklist.json()["items"]]
    items[0]["result"] = "FAIL"
    inspection = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
        headers=_as("TECHNICIAN"),
    )
    assert inspection.status_code == 200
    finding_id = inspection.json()["findings"][0]["finding_id"]

    response = await client.post(
        "/api/v1/repair-requests",
        json={
            "vehicle_id": "VEH-1046",
            "symptom_th": "จากการตรวจสภาพ",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
        headers=_as("TECHNICIAN"),
    )
    assert response.status_code == 200
    assert response.json()["request"]["source_type"] == "FINDING"
    assert response.json()["request"]["source_id"] == finding_id
