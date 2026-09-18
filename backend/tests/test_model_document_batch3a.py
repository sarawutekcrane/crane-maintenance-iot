"""Web/API Phase 6 Batch 3A — Model Document Create + List + Get +
History Foundation.

Scope: create/list/get only — revision/replacement lifecycle
(`replaced_by_document_id` linking, `effective_to` auto-closing,
`active_status`/`file_status` auto-transitions) is explicitly deferred
to Batch 3B pending unresolved project decisions (see the Batch 3
pre-implementation audit). No test here exercises or assumes such
behavior.

Proves: document creation/read round-trips through the API/
MockRepository; every create is an append-only new row (document history
is preserved, never overwritten); `document_type`/`document_name_th`/
`file_status`/`active_status` are honest opaque passthrough values
(NO-GUESSING RULE — no invented vocabulary, never coerced); `version` is
an opaque passthrough string, never numerically coerced, including
leading-zero and punctuation forms; `storage_ref` is an opaque
passthrough, including numeric-looking values; `replaced_by_document_id`
is always null from every code path in this batch; the client can never
supply `model_document_id`/`model_id`/`replaced_by_document_id`; and the
Google Sheets repository maps the one verified live tab
(`model_document`) correctly by header name, using a FAKE in-memory
gspread-shaped client only (never the real Google API — see
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
# Create / list / get — API / MockRepository round trip (items 1-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_model_document_round_trips(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={
            "document_type": "LOAD_CHART",
            "document_name_th": "ตารางยกของ",
            "version": "1.0",
            "effective_from": "2026-01-01",
            "effective_to": "2027-01-01",
            "storage_ref": "attachments/load-chart.pdf",
            "file_status": "UPLOADED",
            "active_status": "ACTIVE",
            "note_th": "ทดสอบ",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_id"] == "MODEL-0001"
    assert body["document_type"] == "LOAD_CHART"
    assert body["version"] == "1.0"
    assert body["replaced_by_document_id"] is None

    reread = await client.get(f"/api/v1/model-documents/{body['model_document_id']}")
    assert reread.status_code == 200
    assert reread.json() == body


@pytest.mark.asyncio
async def test_created_model_document_id_uses_the_disclosed_prefix(client: AsyncClient) -> None:
    """ID prefix decision (disclosed, not silently assumed): `MDOC-` —
    follows the same `PREFIX-NNNN` convention as `DRV-`/`VDRV-`/`CERT-`."""
    response = await client.post("/api/v1/models/MODEL-0001/documents", json={})
    assert response.status_code == 200
    assert response.json()["model_document_id"].startswith("MDOC-")


@pytest.mark.asyncio
async def test_create_model_document_for_unknown_model_returns_404(client: AsyncClient) -> None:
    """Item 2."""
    response = await client.post("/api/v1/models/MODEL-9999/documents", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_unknown_model_document_returns_404(client: AsyncClient) -> None:
    """Item 4."""
    response = await client.get("/api/v1/model-documents/MDOC-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_DOCUMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_model_documents_for_unknown_model_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models/MODEL-9999/documents")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_model_documents_for_a_model_with_none_yet_is_an_empty_list(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/models/MODEL-0003/documents")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_multiple_documents_for_the_same_model_are_preserved(client: AsyncClient) -> None:
    """Items 5-6: append-only history — a second create for the same
    model is always a distinct new row, never an update/overwrite."""
    first = await client.post(
        "/api/v1/models/MODEL-0002/documents",
        json={"document_type": "SERVICE_MANUAL", "version": "1"},
    )
    second = await client.post(
        "/api/v1/models/MODEL-0002/documents",
        json={"document_type": "SERVICE_MANUAL", "version": "2"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["model_document_id"] != second.json()["model_document_id"]

    history = await client.get("/api/v1/models/MODEL-0002/documents")
    assert history.status_code == 200
    ids = {d["model_document_id"] for d in history.json()}
    assert {first.json()["model_document_id"], second.json()["model_document_id"]}.issubset(ids)
    # The first row is untouched by the second create.
    first_reread = await client.get(f"/api/v1/model-documents/{first.json()['model_document_id']}")
    assert first_reread.json()["version"] == "1"


# ---------------------------------------------------------------------------
# NO-GUESSING RULE — opaque passthrough fields (items 7-13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_type_is_an_honest_passthrough_never_a_fixed_vocabulary(
    client: AsyncClient,
) -> None:
    """Items 7-8: whatever string a caller supplies is stored/returned
    verbatim; the backend never coerces it against an invented
    LOAD_CHART/OPERATION_MANUAL/SERVICE_MANUAL (or any other) enum, and
    an arbitrary, obviously-synthetic value is never rejected for that
    reason."""
    for arbitrary_value in ["LOAD_CHART", "ZZZ_UNEXPECTED_TYPE", "คู่มือการใช้งาน"]:
        response = await client.post(
            "/api/v1/models/MODEL-0001/documents",
            json={"document_type": arbitrary_value},
        )
        assert response.status_code == 200
        assert response.json()["document_type"] == arbitrary_value


@pytest.mark.asyncio
async def test_version_preserves_leading_zeros_and_arbitrary_punctuation(
    client: AsyncClient,
) -> None:
    """Items 9-10: `version` is opaque text, never numerically coerced —
    "001"/"1.0"/"Rev.A"/"2026.01" all round-trip exactly."""
    for version_value in ["001", "01", "1.0", "Rev.A", "2026.01"]:
        response = await client.post(
            "/api/v1/models/MODEL-0001/documents", json={"version": version_value}
        )
        assert response.status_code == 200
        assert response.json()["version"] == version_value

        reread = await client.get(f"/api/v1/model-documents/{response.json()['model_document_id']}")
        assert reread.json()["version"] == version_value


@pytest.mark.asyncio
async def test_storage_ref_is_an_opaque_passthrough_including_numeric_looking_values(
    client: AsyncClient,
) -> None:
    """Item 11."""
    for value in ["attachments/load-chart.pdf", "000012345678", "https://example.invalid/x"]:
        response = await client.post(
            "/api/v1/models/MODEL-0001/documents", json={"storage_ref": value}
        )
        assert response.status_code == 200
        assert response.json()["storage_ref"] == value


@pytest.mark.asyncio
async def test_file_status_is_an_honest_passthrough_never_a_fixed_vocabulary(
    client: AsyncClient,
) -> None:
    """Item 12."""
    for value in ["UPLOADED", "MISSING", "ZZZ_UNEXPECTED"]:
        response = await client.post(
            "/api/v1/models/MODEL-0001/documents", json={"file_status": value}
        )
        assert response.status_code == 200
        assert response.json()["file_status"] == value


@pytest.mark.asyncio
async def test_active_status_is_an_honest_passthrough_never_a_fixed_vocabulary(
    client: AsyncClient,
) -> None:
    """Item 13 — same NO-GUESSING treatment as `driver_master.active_status`."""
    for value in ["1", "0", "ZZZ_UNEXPECTED", "ใช้งาน"]:
        response = await client.post(
            "/api/v1/models/MODEL-0001/documents", json={"active_status": value}
        )
        assert response.status_code == 200
        assert response.json()["active_status"] == value


# ---------------------------------------------------------------------------
# Effective dates (items 14-16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_from_and_effective_to_round_trip(client: AsyncClient) -> None:
    """Items 14-15."""
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={"effective_from": "2026-03-15", "effective_to": "2027-03-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effective_from"] == "2026-03-15"
    assert body["effective_to"] == "2027-03-15"


@pytest.mark.asyncio
async def test_effective_to_null_round_trips(client: AsyncClient) -> None:
    """Item 16."""
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={"effective_from": "2026-03-15", "effective_to": None},
    )
    assert response.status_code == 200
    assert response.json()["effective_to"] is None


# ---------------------------------------------------------------------------
# Omitted fields / backend-owned fields (items 17-22)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitted_nullable_fields_remain_null(client: AsyncClient) -> None:
    """Item 17."""
    response = await client.post("/api/v1/models/MODEL-0001/documents", json={})
    assert response.status_code == 200
    body = response.json()
    for field in (
        "document_type",
        "document_name_th",
        "version",
        "effective_from",
        "effective_to",
        "storage_ref",
        "file_status",
        "active_status",
        "note_th",
    ):
        assert body[field] is None


@pytest.mark.asyncio
async def test_replaced_by_document_id_is_always_null_from_every_create(
    client: AsyncClient,
) -> None:
    """Item 18."""
    response = await client.post("/api/v1/models/MODEL-0001/documents", json={})
    assert response.status_code == 200
    assert response.json()["replaced_by_document_id"] is None


@pytest.mark.asyncio
async def test_create_request_cannot_inject_model_document_id(client: AsyncClient) -> None:
    """Item 19."""
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={"model_document_id": "MDOC-9999"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_cannot_inject_model_id(client: AsyncClient) -> None:
    """Item 20."""
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={"model_id": "MODEL-9999"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_cannot_inject_replaced_by_document_id(client: AsyncClient) -> None:
    """Item 21."""
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={"replaced_by_document_id": "MDOC-0001"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_rejects_unknown_extra_field(client: AsyncClient) -> None:
    """Item 22."""
    response = await client.post(
        "/api/v1/models/MODEL-0001/documents",
        json={"some_unexpected_field": "x"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Google Sheets — verified live tab/header mapping (FAKE in-memory client)
# (items 23, 25)
# ---------------------------------------------------------------------------


def test_model_document_schema_uses_the_exact_verified_live_headers() -> None:
    """Item 23."""
    assert schemas.MODEL_DOCUMENT_SHEET.tab_name == "model_document"
    assert schemas.MODEL_DOCUMENT_SHEET.required_headers == (
        "model_document_id",
        "model_id",
        "document_type",
        "document_name_th",
        "version",
        "effective_from",
        "effective_to",
        "storage_ref",
        "file_status",
        "active_status",
        "replaced_by_document_id",
        "note_th",
    )


@pytest.mark.asyncio
async def test_google_sheets_model_document_create_then_read_round_trips_by_header_name() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.MODEL_DOCUMENT_SHEET))
    created = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="LOAD_CHART",
        document_name_th="ตารางยกของ",
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=date(2027, 1, 1),
        storage_ref="attachments/load-chart.pdf",
        file_status="UPLOADED",
        active_status="ACTIVE",
        note_th=None,
    )
    assert created.model_document_id.startswith("MDOC-")

    reread = await repo.get_model_document(created.model_document_id)
    assert reread is not None
    assert reread.version == "1.0"
    assert reread.document_name_th == "ตารางยกของ"
    assert reread.storage_ref == "attachments/load-chart.pdf"
    assert reread.replaced_by_document_id is None


@pytest.mark.asyncio
async def test_google_sheets_fake_client_does_not_numerically_coerce_the_written_version_cell() -> (
    None
):
    """Item 25 (part 1): proves the write path defends `version` against
    numeric coercion the same way Batch 1 proved it for `phone` — the
    raw value sent to the Sheets client carries the text-forcing marker,
    never a bare digit string Sheets' USER_ENTERED mode would
    auto-convert."""
    ws = _ws(schemas.MODEL_DOCUMENT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    await repo.create_model_document(
        model_id="MODEL-0001",
        document_type=None,
        document_name_th=None,
        version="001",
        effective_from=None,
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    version_column = schemas.MODEL_DOCUMENT_SHEET.required_headers.index("version")
    raw_written_value = ws.rows[0][version_column]
    assert raw_written_value != "001"
    assert str(raw_written_value) == "'001"


@pytest.mark.asyncio
async def test_google_sheets_storage_ref_numeric_looking_value_survives_round_trip() -> None:
    """Item 25 (part 2)."""
    repo = _repo_with_fake_sheets(_ws(schemas.MODEL_DOCUMENT_SHEET))
    created = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type=None,
        document_name_th=None,
        version=None,
        effective_from=None,
        effective_to=None,
        storage_ref="000012345678",
        file_status=None,
        active_status=None,
        note_th=None,
    )
    assert created.storage_ref == "000012345678"

    reread = await repo.get_model_document(created.model_document_id)
    assert reread is not None
    assert reread.storage_ref == "000012345678"


@pytest.mark.asyncio
async def test_google_sheets_model_document_history_is_append_only_per_model() -> None:
    ws = _ws(schemas.MODEL_DOCUMENT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    first = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="SERVICE_MANUAL",
        document_name_th=None,
        version="1",
        effective_from=None,
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    second = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="SERVICE_MANUAL",
        document_name_th=None,
        version="2",
        effective_from=None,
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    assert len(ws.rows) == 2
    history = await repo.list_model_documents_for_model("MODEL-0001")
    ids = {d.model_document_id for d in history}
    assert ids == {first.model_document_id, second.model_document_id}


@pytest.mark.asyncio
async def test_google_sheets_missing_credentials_fails_explicitly_never_silently() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    with pytest.raises(RepositoryError, match="not configured"):
        await repo.get_model_document("MDOC-0001")


# ---------------------------------------------------------------------------
# Mock / Google Sheets parity (item 24)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_and_google_sheets_parity() -> None:
    from app.repositories.mock import MockRepository

    results = {}
    for name, repo in (
        ("mock", MockRepository()),
        ("google_sheets", _repo_with_fake_sheets(_ws(schemas.MODEL_DOCUMENT_SHEET))),
    ):
        created = await repo.create_model_document(
            model_id="MODEL-0001",
            document_type="LOAD_CHART",
            document_name_th="ตารางยกของ",
            version="001",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            storage_ref="attachments/x.pdf",
            file_status="UPLOADED",
            active_status="ACTIVE",
            note_th=None,
        )
        reread = await repo.get_model_document(created.model_document_id)
        results[name] = {
            "document_type": reread.document_type,
            "version": reread.version,
            "effective_from": reread.effective_from,
            "effective_to": reread.effective_to,
            "storage_ref": reread.storage_ref,
            "replaced_by_document_id": reread.replaced_by_document_id,
        }

    assert results["mock"] == results["google_sheets"]
