"""Web/API Phase 6 Batch 2A — Vehicle Certificate Create + List + Get +
History Foundation.

Scope: create/list/get only — renewal/replacement lifecycle
(`replaced_by_certificate_id` linking, ACTIVE exclusivity, EXPIRED
derivation) is explicitly deferred to Batch 2B pending unresolved project
decisions (see the Batch 2 pre-implementation audit). No test here
exercises or assumes such behavior.

Proves: certificate creation/read round-trips through the API/
MockRepository; every create is an append-only new row (certificate
history is preserved, never overwritten); `certificate_type_code`/
`certificate_type_name_th`/`document_no`/`storage_ref` are honest opaque
passthrough values (NO-GUESSING RULE — no invented vocabulary, never
coerced); `certificate_status` is validated against the one approved
3-value vocabulary (ACTIVE/REPLACED/EXPIRED) but stays optional/nullable
with no fabricated default; `alert_lead_days` is a plain nullable integer
with no fabricated default; `created_by_user_id`/`created_at` are always
backend-derived, never client-suppliable; `replaced_by_certificate_id` is
always null from every code path in this batch; and the Google Sheets
repository maps the one verified live tab (`vehicle_certificate`)
correctly by header name, using a FAKE in-memory gspread-shaped client
only (never the real Google API — see
`tests/test_google_sheets_real_io.py` module docstring for why)."""
from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


# ---------------------------------------------------------------------------
# Create / list / get — API / MockRepository round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_certificate_round_trips(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={
            "certificate_type_code": "INSURANCE",
            "certificate_type_name_th": "ประกันภัย",
            "document_no": "0012345678",
            "issue_date": "2026-01-01",
            "expiry_date": "2027-01-01",
            "alert_lead_days": 30,
            "certificate_status": "ACTIVE",
            "storage_ref": "attachments/cert-001.pdf",
            "note_th": "ทดสอบ",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_id"] == "VEH-1046"
    assert body["certificate_type_code"] == "INSURANCE"
    assert body["document_no"] == "0012345678"
    assert body["certificate_status"] == "ACTIVE"
    assert body["replaced_by_certificate_id"] is None

    reread = await client.get(f"/api/v1/certificates/{body['certificate_id']}")
    assert reread.status_code == 200
    assert reread.json() == body


@pytest.mark.asyncio
async def test_created_certificate_id_uses_the_disclosed_prefix(client: AsyncClient) -> None:
    """ID prefix decision (disclosed, not silently assumed): `CERT-` —
    follows the same `PREFIX-NNNN` convention as Batch 1's `DRV-`/`VDRV-`
    (see `MockRepository._vehicle_certificate_seq` /
    `GoogleSheetsRepository._next_id(rows, "certificate_id", "CERT")`)."""
    response = await client.post("/api/v1/vehicles/VEH-1046/certificates", json={})
    assert response.status_code == 200
    assert response.json()["certificate_id"].startswith("CERT-")


@pytest.mark.asyncio
async def test_backend_generated_fields_are_correct_on_a_normal_valid_create(
    client: AsyncClient,
) -> None:
    """Item 7: `certificate_id`/`created_by_user_id`/`created_at` are
    still correctly backend-derived exactly as before this correction —
    this test sends no backend-owned field at all (a normal valid
    request), so it is unaffected by the new `extra="forbid"` rejection
    behavior proven separately below."""
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"note_th": "provenance test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["certificate_id"].startswith("CERT-")
    assert body["vehicle_id"] == "VEH-1046"
    assert body["created_by_user_id"] == "dev-user"
    assert body["created_at"] is not None
    assert body["replaced_by_certificate_id"] is None


# ---------------------------------------------------------------------------
# API-CONTRACT CORRECTION: the client must never be able to supply a
# backend-owned field. `CreateVehicleCertificateRequest` now declares
# `extra="forbid"`, so any of these must be rejected with 422 rather than
# silently ignored (the previous, incorrect behavior — silent-ignore only
# happened to look safe because none of these fields existed on the
# model; that is not the same as actively rejecting them).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_request_with_certificate_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"certificate_id": "CERT-9999"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_with_vehicle_id_in_body_is_rejected(client: AsyncClient) -> None:
    """`vehicle_id` must come only from the URL path — a body-supplied
    value (even one matching the path) is rejected, never merged/ignored."""
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"vehicle_id": "VEH-1046"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_with_replaced_by_certificate_id_is_rejected(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"replaced_by_certificate_id": "CERT-0001"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_with_created_by_user_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"created_by_user_id": "SOMEONE_ELSE"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_with_created_at_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"created_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_unknown_certificate_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/certificates/CERT-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_CERTIFICATE_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_certificate_for_unknown_vehicle_returns_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/vehicles/VEH-9999/certificates", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_certificates_for_unknown_vehicle_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-9999/certificates")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_certificates_for_a_vehicle_with_none_yet_is_an_empty_list(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1048/certificates")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_two_creates_for_the_same_vehicle_produce_two_distinct_history_rows(
    client: AsyncClient,
) -> None:
    """Append-only history: a second create for the same vehicle is
    always a distinct new row, never an update/overwrite of the first."""
    first = await client.post(
        "/api/v1/vehicles/VEH-1047/certificates",
        json={"certificate_type_code": "TAX", "document_no": "AAA"},
    )
    second = await client.post(
        "/api/v1/vehicles/VEH-1047/certificates",
        json={"certificate_type_code": "TAX", "document_no": "BBB"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["certificate_id"] != second.json()["certificate_id"]

    history = await client.get("/api/v1/vehicles/VEH-1047/certificates")
    assert history.status_code == 200
    ids = {c["certificate_id"] for c in history.json()}
    assert {first.json()["certificate_id"], second.json()["certificate_id"]}.issubset(ids)
    # The first row is untouched by the second create.
    first_reread = await client.get(f"/api/v1/certificates/{first.json()['certificate_id']}")
    assert first_reread.json()["document_no"] == "AAA"


# ---------------------------------------------------------------------------
# certificate_status — the one approved vocabulary, still optional/nullable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_certificate_status_defaults_to_null_never_a_fabricated_value(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/v1/vehicles/VEH-1046/certificates", json={})
    assert response.status_code == 200
    assert response.json()["certificate_status"] is None


@pytest.mark.asyncio
async def test_certificate_status_accepts_each_approved_value(client: AsyncClient) -> None:
    for value in ["ACTIVE", "REPLACED", "EXPIRED"]:
        response = await client.post(
            "/api/v1/vehicles/VEH-1046/certificates", json={"certificate_status": value}
        )
        assert response.status_code == 200
        assert response.json()["certificate_status"] == value


@pytest.mark.asyncio
async def test_certificate_status_rejects_an_unapproved_value(client: AsyncClient) -> None:
    """Unlike `active_status`/`assignment_status` (Batch 1, plain opaque
    passthrough), `certificate_status` HAS an approved vocabulary, so an
    arbitrary caller-supplied value is rejected rather than persisted."""
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"certificate_status": "SOME_UNAPPROVED_VALUE"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# NO-GUESSING RULE — opaque passthrough fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_certificate_type_code_and_name_are_honest_passthrough_never_a_fixed_vocabulary(
    client: AsyncClient,
) -> None:
    for code, name in [
        ("INSURANCE", "ประกันภัย"),
        ("ZZZ_UNEXPECTED_TYPE", "ไม่ใช่ประเภทจริง"),
        ("weight-certificate-2026", "ใบรับรองน้ำหนัก"),
    ]:
        response = await client.post(
            "/api/v1/vehicles/VEH-1046/certificates",
            json={"certificate_type_code": code, "certificate_type_name_th": name},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["certificate_type_code"] == code
        assert body["certificate_type_name_th"] == name


@pytest.mark.asyncio
async def test_storage_ref_is_an_opaque_passthrough_including_numeric_looking_values(
    client: AsyncClient,
) -> None:
    for value in ["attachments/cert-001.pdf", "0012345", "https://example.invalid/x"]:
        response = await client.post(
            "/api/v1/vehicles/VEH-1046/certificates", json={"storage_ref": value}
        )
        assert response.status_code == 200
        assert response.json()["storage_ref"] == value


@pytest.mark.asyncio
async def test_document_no_with_a_leading_zero_survives_round_trip(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates", json={"document_no": "0012345678"}
    )
    assert response.status_code == 200
    assert response.json()["document_no"] == "0012345678"

    reread = await client.get(f"/api/v1/certificates/{response.json()['certificate_id']}")
    assert reread.json()["document_no"] == "0012345678"


# ---------------------------------------------------------------------------
# alert_lead_days — plain nullable integer, no default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_lead_days_defaults_to_null_never_a_fabricated_value(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/v1/vehicles/VEH-1046/certificates", json={})
    assert response.status_code == 200
    assert response.json()["alert_lead_days"] is None


@pytest.mark.asyncio
async def test_alert_lead_days_round_trips_an_arbitrary_value(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates", json={"alert_lead_days": 45}
    )
    assert response.status_code == 200
    assert response.json()["alert_lead_days"] == 45


# ---------------------------------------------------------------------------
# issue_date / expiry_date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_and_expiry_dates_round_trip(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"issue_date": "2026-03-15", "expiry_date": "2027-03-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["issue_date"] == "2026-03-15"
    assert body["expiry_date"] == "2027-03-15"


# ---------------------------------------------------------------------------
# replaced_by_certificate_id — always null from this batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replaced_by_certificate_id_is_always_null_from_every_create(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/certificates",
        json={"certificate_status": "REPLACED"},
    )
    assert response.status_code == 200
    assert response.json()["replaced_by_certificate_id"] is None


# ---------------------------------------------------------------------------
# Google Sheets — verified live tab/header mapping (FAKE in-memory client)
# ---------------------------------------------------------------------------


def test_vehicle_certificate_schema_uses_the_exact_verified_live_headers() -> None:
    assert schemas.VEHICLE_CERTIFICATE_SHEET.tab_name == "vehicle_certificate"
    assert schemas.VEHICLE_CERTIFICATE_SHEET.required_headers == (
        "certificate_id",
        "vehicle_id",
        "certificate_type_code",
        "certificate_type_name_th",
        "document_no",
        "issue_date",
        "expiry_date",
        "alert_lead_days",
        "certificate_status",
        "replaced_by_certificate_id",
        "storage_ref",
        "created_by_user_id",
        "created_at",
        "note_th",
    )


@pytest.mark.asyncio
async def test_google_sheets_certificate_create_then_read_round_trips_by_header_name() -> None:
    from datetime import datetime, timezone

    repo = _repo_with_fake_sheets(_ws(schemas.VEHICLE_CERTIFICATE_SHEET))
    created = await repo.create_vehicle_certificate(
        vehicle_id="VEH-1046",
        certificate_type_code="INSURANCE",
        certificate_type_name_th="ประกันภัย",
        document_no="0012345678",
        issue_date=date(2026, 1, 1),
        expiry_date=date(2027, 1, 1),
        alert_lead_days=30,
        certificate_status=None,
        storage_ref="attachments/cert-001.pdf",
        note_th=None,
        created_by_user_id="dev-user",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert created.certificate_id.startswith("CERT-")

    reread = await repo.get_vehicle_certificate(created.certificate_id)
    assert reread is not None
    assert reread.document_no == "0012345678"
    assert reread.certificate_type_name_th == "ประกันภัย"
    assert reread.alert_lead_days == 30
    assert reread.storage_ref == "attachments/cert-001.pdf"
    assert reread.replaced_by_certificate_id is None


@pytest.mark.asyncio
async def test_google_sheets_fake_client_does_not_numerically_coerce_the_written_document_no_cell() -> (
    None
):
    """Proves the write path defends `document_no` against numeric
    coercion the same way Batch 1 proved it for `phone`: the raw value
    sent to the Sheets client carries the text-forcing marker, never a
    bare digit string Sheets' USER_ENTERED mode would auto-convert."""
    from datetime import datetime, timezone

    ws = _ws(schemas.VEHICLE_CERTIFICATE_SHEET)
    repo = _repo_with_fake_sheets(ws)
    await repo.create_vehicle_certificate(
        vehicle_id="VEH-1046",
        certificate_type_code=None,
        certificate_type_name_th=None,
        document_no="0012345678",
        issue_date=None,
        expiry_date=None,
        alert_lead_days=None,
        certificate_status=None,
        storage_ref=None,
        note_th=None,
        created_by_user_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    document_no_column = schemas.VEHICLE_CERTIFICATE_SHEET.required_headers.index("document_no")
    raw_written_value = ws.rows[0][document_no_column]
    assert raw_written_value != "0012345678"
    assert str(raw_written_value) == "'0012345678"


@pytest.mark.asyncio
async def test_google_sheets_certificate_history_is_append_only_per_vehicle() -> None:
    from datetime import datetime, timezone

    ws = _ws(schemas.VEHICLE_CERTIFICATE_SHEET)
    repo = _repo_with_fake_sheets(ws)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = await repo.create_vehicle_certificate(
        vehicle_id="VEH-1046",
        certificate_type_code="TAX",
        certificate_type_name_th=None,
        document_no="AAA",
        issue_date=None,
        expiry_date=None,
        alert_lead_days=None,
        certificate_status=None,
        storage_ref=None,
        note_th=None,
        created_by_user_id=None,
        created_at=now,
    )
    second = await repo.create_vehicle_certificate(
        vehicle_id="VEH-1046",
        certificate_type_code="TAX",
        certificate_type_name_th=None,
        document_no="BBB",
        issue_date=None,
        expiry_date=None,
        alert_lead_days=None,
        certificate_status=None,
        storage_ref=None,
        note_th=None,
        created_by_user_id=None,
        created_at=now,
    )
    assert len(ws.rows) == 2
    history = await repo.list_vehicle_certificates_for_vehicle("VEH-1046")
    ids = {c.certificate_id for c in history}
    assert ids == {first.certificate_id, second.certificate_id}


@pytest.mark.asyncio
async def test_google_sheets_missing_credentials_fails_explicitly_never_silently() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    with pytest.raises(RepositoryError, match="not configured"):
        await repo.get_vehicle_certificate("CERT-0001")
