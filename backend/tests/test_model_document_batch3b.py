"""Web/API Phase 6 Batch 3B — Model Document Revision Lifecycle.

Builds on Batch 3A (`tests/test_model_document_batch3a.py`, left untouched
and still green). Proves the 8 locked rules (see
`app.domain.model_document_service.ModelDocumentService.revise_document`
docstring, restated from the Batch 3B task's own locked-rule sections):

- revision always creates a new row, never overwrites/deletes the old one
- old -> linked via `replaced_by_document_id`, `effective_to` closed to
  the day before the new row's `effective_from`; new -> `effective_to`
  always null
- `model_id`/`document_type` are always inherited, never client-suppliable
- `version` is required, non-blank, exact text, and must differ from the
  source's version (never auto-incremented, never numerically compared)
- `effective_from` is required and must be strictly later than the
  source's `effective_from`; a pre-existing incompatible
  `source.effective_to` is rejected rather than silently overwritten
- `document_name_th`/`active_status` inherit-if-omitted;
  `storage_ref`/`file_status`/`note_th` are never inherited
- a completed-revision retry returns the existing successor rather than
  duplicating; a corrupted/missing link is rejected, never silently
  repaired
- `active_status`/`file_status` are never used to determine revision
  eligibility or "the effective" revision — the only chain link is
  `replaced_by_document_id`."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.model_document_service import ModelDocumentService
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


async def _create_document(
    client: AsyncClient,
    model_id: str,
    **overrides,
) -> dict:
    payload = {
        "document_type": "LOAD_CHART",
        "document_name_th": "ตารางยกของ เดิม",
        "version": "1.0",
        "effective_from": "2026-01-01",
        "storage_ref": "attachments/load-chart-v1.pdf",
        "file_status": "UPLOADED",
        "active_status": "ACTIVE",
        "note_th": "seed",
    }
    payload.update(overrides)
    response = await client.post(f"/api/v1/models/{model_id}/documents", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# REVISION (items 1-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_creates_distinct_new_row_and_links_source(client: AsyncClient) -> None:
    """Items 1-4."""
    source = await _create_document(client, "MODEL-0001", document_type="REVISE_BASIC")

    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 200, response.text
    new_doc = response.json()

    assert new_doc["model_document_id"] != source["model_document_id"]
    assert new_doc["model_document_id"].startswith("MDOC-")
    assert new_doc["replaced_by_document_id"] is None

    old_reread = await client.get(f"/api/v1/model-documents/{source['model_document_id']}")
    assert old_reread.status_code == 200
    assert old_reread.json()["replaced_by_document_id"] == new_doc["model_document_id"]


@pytest.mark.asyncio
async def test_revise_inherits_model_id_and_document_type(client: AsyncClient) -> None:
    """Items 5-6."""
    source = await _create_document(client, "MODEL-0002", document_type="INHERIT_TYPE_TEST")
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 200
    new_doc = response.json()
    assert new_doc["model_id"] == "MODEL-0002"
    assert new_doc["document_type"] == "INHERIT_TYPE_TEST"


@pytest.mark.asyncio
async def test_revise_request_cannot_supply_backend_owned_fields(client: AsyncClient) -> None:
    """Items 7-12: extra="forbid" rejects model_id/document_type/
    model_document_id/replaced_by_document_id/effective_to/unknown."""
    source = await _create_document(client, "MODEL-0001", document_type="FORBID_TEST")
    forbidden_bodies = [
        {"version": "2.0", "effective_from": "2026-06-01", "model_id": "MODEL-9999"},
        {"version": "2.0", "effective_from": "2026-06-01", "document_type": "OTHER"},
        {"version": "2.0", "effective_from": "2026-06-01", "model_document_id": "MDOC-9999"},
        {
            "version": "2.0",
            "effective_from": "2026-06-01",
            "replaced_by_document_id": "MDOC-0001",
        },
        {"version": "2.0", "effective_from": "2026-06-01", "effective_to": "2027-01-01"},
        {"version": "2.0", "effective_from": "2026-06-01", "some_unexpected_field": "x"},
    ]
    for body in forbidden_bodies:
        response = await client.post(
            f"/api/v1/model-documents/{source['model_document_id']}/revise", json=body
        )
        assert response.status_code == 422, body


# ---------------------------------------------------------------------------
# VERSION (items 13-20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_required_missing_null_empty_rejected(client: AsyncClient) -> None:
    """Items 13-15."""
    source = await _create_document(client, "MODEL-0001", document_type="VERSION_REQUIRED")
    for body in (
        {"effective_from": "2026-06-01"},  # omitted
        {"version": None, "effective_from": "2026-06-01"},  # explicit null
        {"version": "", "effective_from": "2026-06-01"},  # empty
    ):
        response = await client.post(
            f"/api/v1/model-documents/{source['model_document_id']}/revise", json=body
        )
        assert response.status_code == 422, body


@pytest.mark.asyncio
async def test_version_whitespace_only_rejected(client: AsyncClient) -> None:
    """Item 16."""
    source = await _create_document(client, "MODEL-0001", document_type="VERSION_WHITESPACE")
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "   ", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_DOCUMENT_VERSION_REQUIRED"


@pytest.mark.asyncio
async def test_version_exact_same_as_source_rejected(client: AsyncClient) -> None:
    """Item 17."""
    source = await _create_document(
        client, "MODEL-0001", document_type="VERSION_DUPLICATE", version="1.0"
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "1.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_DOCUMENT_VERSION_DUPLICATE"


@pytest.mark.asyncio
async def test_version_remains_exact_text_leading_zero_and_nonnumeric(
    client: AsyncClient,
) -> None:
    """Items 18-20."""
    for version_value in ["002", "001", "Rev.B", "2026.01"]:
        source = await _create_document(
            client, "MODEL-0001", document_type=f"VERSION_TEXT_{version_value}", version="000"
        )
        response = await client.post(
            f"/api/v1/model-documents/{source['model_document_id']}/revise",
            json={"version": version_value, "effective_from": "2026-06-01"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == version_value

        reread = await client.get(f"/api/v1/model-documents/{response.json()['model_document_id']}")
        assert reread.json()["version"] == version_value


# ---------------------------------------------------------------------------
# EFFECTIVE DATE LIFECYCLE (items 21-30)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_from_required_missing_and_null_rejected(client: AsyncClient) -> None:
    """Items 21-22."""
    source = await _create_document(client, "MODEL-0001", document_type="EFFECTIVE_FROM_REQUIRED")
    for body in (
        {"version": "2.0"},  # omitted
        {"version": "2.0", "effective_from": None},  # explicit null
    ):
        response = await client.post(
            f"/api/v1/model-documents/{source['model_document_id']}/revise", json=body
        )
        assert response.status_code == 422, body


@pytest.mark.asyncio
async def test_source_effective_from_null_rejects_revision(client: AsyncClient) -> None:
    """Item 23."""
    source = await _create_document(
        client, "MODEL-0001", document_type="SOURCE_EFFECTIVE_FROM_NULL", effective_from=None
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_DOCUMENT_EFFECTIVE_FROM_MISSING"


@pytest.mark.asyncio
async def test_new_effective_from_equal_or_earlier_than_source_rejected(
    client: AsyncClient,
) -> None:
    """Items 24-25."""
    for candidate in ("2026-01-01", "2025-12-31"):
        source = await _create_document(
            client,
            "MODEL-0001",
            document_type=f"EFFECTIVE_FROM_ORDER_{candidate}",
            effective_from="2026-01-01",
        )
        response = await client.post(
            f"/api/v1/model-documents/{source['model_document_id']}/revise",
            json={"version": "2.0", "effective_from": candidate},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MODEL_DOCUMENT_EFFECTIVE_FROM_NOT_LATER"


@pytest.mark.asyncio
async def test_valid_later_effective_from_succeeds_and_closes_old_effective_to(
    client: AsyncClient,
) -> None:
    """Items 26-28."""
    source = await _create_document(
        client, "MODEL-0001", document_type="EFFECTIVE_TO_CLOSE", effective_from="2026-01-01"
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 200
    new_doc = response.json()
    assert new_doc["effective_to"] is None

    old_reread = await client.get(f"/api/v1/model-documents/{source['model_document_id']}")
    assert old_reread.json()["effective_to"] == "2026-05-31"


@pytest.mark.asyncio
async def test_matching_preexisting_old_effective_to_is_accepted(client: AsyncClient) -> None:
    """Item 29."""
    source = await _create_document(
        client,
        "MODEL-0001",
        document_type="EFFECTIVE_TO_MATCH",
        effective_from="2026-01-01",
        effective_to="2026-05-31",
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_conflicting_preexisting_old_effective_to_rejected_without_adding_row(
    client: AsyncClient,
) -> None:
    """Item 30."""
    source = await _create_document(
        client,
        "MODEL-0001",
        document_type="EFFECTIVE_TO_CONFLICT",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    before_count = len((await client.get("/api/v1/models/MODEL-0001/documents")).json())

    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_DOCUMENT_EFFECTIVE_TO_CONFLICT"

    after_count = len((await client.get("/api/v1/models/MODEL-0001/documents")).json())
    assert after_count == before_count


# ---------------------------------------------------------------------------
# document_name_th (items 31-33)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_name_th_omitted_inherits_from_source(client: AsyncClient) -> None:
    """Item 31."""
    source = await _create_document(
        client, "MODEL-0001", document_type="NAME_INHERIT", document_name_th="ชื่อเดิม"
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 200
    assert response.json()["document_name_th"] == "ชื่อเดิม"


@pytest.mark.asyncio
async def test_document_name_th_supplied_overrides(client: AsyncClient) -> None:
    """Item 32."""
    source = await _create_document(
        client, "MODEL-0001", document_type="NAME_OVERRIDE", document_name_th="ชื่อเดิม"
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "document_name_th": "ชื่อใหม่"},
    )
    assert response.status_code == 200
    assert response.json()["document_name_th"] == "ชื่อใหม่"


@pytest.mark.asyncio
async def test_document_name_th_explicit_null_clears(client: AsyncClient) -> None:
    """Item 33."""
    source = await _create_document(
        client, "MODEL-0001", document_type="NAME_CLEAR", document_name_th="ชื่อเดิม"
    )
    response = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "document_name_th": None},
    )
    assert response.status_code == 200
    assert response.json()["document_name_th"] is None


# ---------------------------------------------------------------------------
# active_status (items 34-37)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_status_omitted_inherits_supplied_overrides_explicit_null_clears(
    client: AsyncClient,
) -> None:
    """Items 34-36."""
    # omitted -> inherit
    source1 = await _create_document(
        client, "MODEL-0001", document_type="ACTIVE_INHERIT", active_status="ACTIVE"
    )
    r1 = await client.post(
        f"/api/v1/model-documents/{source1['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert r1.status_code == 200
    assert r1.json()["active_status"] == "ACTIVE"

    # supplied -> override
    source2 = await _create_document(
        client, "MODEL-0001", document_type="ACTIVE_OVERRIDE", active_status="ACTIVE"
    )
    r2 = await client.post(
        f"/api/v1/model-documents/{source2['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "active_status": "PENDING"},
    )
    assert r2.status_code == 200
    assert r2.json()["active_status"] == "PENDING"

    # explicit null -> clears
    source3 = await _create_document(
        client, "MODEL-0001", document_type="ACTIVE_CLEAR", active_status="ACTIVE"
    )
    r3 = await client.post(
        f"/api/v1/model-documents/{source3['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "active_status": None},
    )
    assert r3.status_code == 200
    assert r3.json()["active_status"] is None


@pytest.mark.asyncio
async def test_old_active_status_never_changes(client: AsyncClient) -> None:
    """Item 37."""
    source = await _create_document(
        client, "MODEL-0001", document_type="ACTIVE_OLD_UNCHANGED", active_status="ACTIVE"
    )
    await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "active_status": "SOMETHING_ELSE"},
    )
    old_reread = await client.get(f"/api/v1/model-documents/{source['model_document_id']}")
    assert old_reread.json()["active_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# file_status (items 38-41)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_status_omitted_null_supplied_value_never_inherited(
    client: AsyncClient,
) -> None:
    """Items 38-40: unlike active_status, file_status is NEVER
    inherited — omitted or explicit null both result in null on the new
    row, even though the source has a non-null file_status."""
    source1 = await _create_document(
        client, "MODEL-0001", document_type="FILE_STATUS_OMIT", file_status="UPLOADED"
    )
    r1 = await client.post(
        f"/api/v1/model-documents/{source1['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert r1.status_code == 200
    assert r1.json()["file_status"] is None

    source2 = await _create_document(
        client, "MODEL-0001", document_type="FILE_STATUS_SUPPLIED", file_status="UPLOADED"
    )
    r2 = await client.post(
        f"/api/v1/model-documents/{source2['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "file_status": "PENDING"},
    )
    assert r2.status_code == 200
    assert r2.json()["file_status"] == "PENDING"

    source3 = await _create_document(
        client, "MODEL-0001", document_type="FILE_STATUS_NULL", file_status="UPLOADED"
    )
    r3 = await client.post(
        f"/api/v1/model-documents/{source3['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "file_status": None},
    )
    assert r3.status_code == 200
    assert r3.json()["file_status"] is None


@pytest.mark.asyncio
async def test_old_file_status_never_changes(client: AsyncClient) -> None:
    """Item 41."""
    source = await _create_document(
        client, "MODEL-0001", document_type="FILE_STATUS_OLD_UNCHANGED", file_status="UPLOADED"
    )
    await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "file_status": "PENDING"},
    )
    old_reread = await client.get(f"/api/v1/model-documents/{source['model_document_id']}")
    assert old_reread.json()["file_status"] == "UPLOADED"


# ---------------------------------------------------------------------------
# storage_ref / note_th (items 42-45)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_ref_omitted_null_never_inherited_but_preserves_exact_text_when_supplied(
    client: AsyncClient,
) -> None:
    """Items 42-43."""
    source1 = await _create_document(
        client,
        "MODEL-0001",
        document_type="STORAGE_REF_OMIT",
        storage_ref="attachments/old.pdf",
    )
    r1 = await client.post(
        f"/api/v1/model-documents/{source1['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert r1.status_code == 200
    assert r1.json()["storage_ref"] is None

    source2 = await _create_document(
        client,
        "MODEL-0001",
        document_type="STORAGE_REF_SUPPLIED",
        storage_ref="attachments/old.pdf",
    )
    r2 = await client.post(
        f"/api/v1/model-documents/{source2['model_document_id']}/revise",
        json={
            "version": "2.0",
            "effective_from": "2026-06-01",
            "storage_ref": "attachments/new.pdf",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["storage_ref"] == "attachments/new.pdf"


@pytest.mark.asyncio
async def test_note_th_omitted_null_and_supplied(client: AsyncClient) -> None:
    """Items 44-45."""
    source = await _create_document(
        client, "MODEL-0001", document_type="NOTE_TH_TEST", note_th="หมายเหตุเดิม"
    )
    r1 = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert r1.status_code == 200
    assert r1.json()["note_th"] is None

    source2 = await _create_document(
        client, "MODEL-0001", document_type="NOTE_TH_SUPPLIED", note_th="หมายเหตุเดิม"
    )
    r2 = await client.post(
        f"/api/v1/model-documents/{source2['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01", "note_th": "หมายเหตุใหม่"},
    )
    assert r2.status_code == 200
    assert r2.json()["note_th"] == "หมายเหตุใหม่"


# ---------------------------------------------------------------------------
# COMPLETED-REVISION RETRY / CORRUPTION GUARD (items 46-50)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_retry_returns_existing_successor_creates_no_third_row(
    client: AsyncClient,
) -> None:
    """Items 46-47."""
    source = await _create_document(client, "MODEL-0001", document_type="RETRY_TEST")
    first = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "2.0", "effective_from": "2026-06-01"},
    )
    assert first.status_code == 200

    before_count = len((await client.get("/api/v1/models/MODEL-0001/documents")).json())
    second = await client.post(
        f"/api/v1/model-documents/{source['model_document_id']}/revise",
        json={"version": "3.0", "effective_from": "2027-01-01"},
    )
    assert second.status_code == 200
    assert second.json()["model_document_id"] == first.json()["model_document_id"]

    after_count = len((await client.get("/api/v1/models/MODEL-0001/documents")).json())
    assert after_count == before_count


@pytest.mark.asyncio
async def test_missing_successor_link_target_is_422_conflict() -> None:
    """Item 48: constructed directly against the repository (unreachable
    via the guarded public API, since no delete exists) to simulate a
    corrupted link — the successor referenced by replaced_by_document_id
    doesn't actually exist."""
    repo = MockRepository()
    service = ModelDocumentService(repo)
    source = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="CORRUPT_MISSING",
        document_name_th=None,
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    await repo.finalize_model_document_revision(
        model_document_id=source.model_document_id,
        effective_to=date(2026, 5, 31),
        replaced_by_document_id="MDOC-9999",
    )

    with pytest.raises(Exception) as exc_info:
        await service.revise_document(
            model_document_id=source.model_document_id,
            version="2.0",
            effective_from=date(2026, 6, 1),
            document_name_th=None,
            storage_ref=None,
            file_status=None,
            active_status=None,
            note_th=None,
        )
    assert "MODEL_DOCUMENT_REVISION_STATE_CONFLICT" in str(
        getattr(exc_info.value, "code", exc_info.value)
    )


@pytest.mark.asyncio
async def test_successor_wrong_model_id_is_422_conflict() -> None:
    """Item 49."""
    repo = MockRepository()
    service = ModelDocumentService(repo)
    source = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="CORRUPT_WRONG_MODEL",
        document_name_th=None,
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    wrong_model_successor = await repo.create_model_document(
        model_id="MODEL-0002",  # wrong model_id
        document_type="CORRUPT_WRONG_MODEL",
        document_name_th=None,
        version="2.0",
        effective_from=date(2026, 6, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    await repo.finalize_model_document_revision(
        model_document_id=source.model_document_id,
        effective_to=date(2026, 5, 31),
        replaced_by_document_id=wrong_model_successor.model_document_id,
    )

    with pytest.raises(Exception) as exc_info:
        await service.revise_document(
            model_document_id=source.model_document_id,
            version="3.0",
            effective_from=date(2027, 1, 1),
            document_name_th=None,
            storage_ref=None,
            file_status=None,
            active_status=None,
            note_th=None,
        )
    assert "MODEL_DOCUMENT_REVISION_STATE_CONFLICT" in str(
        getattr(exc_info.value, "code", exc_info.value)
    )


@pytest.mark.asyncio
async def test_successor_wrong_document_type_is_422_conflict() -> None:
    """Item 50."""
    repo = MockRepository()
    service = ModelDocumentService(repo)
    source = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="CORRUPT_WRONG_TYPE",
        document_name_th=None,
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    wrong_type_successor = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="DIFFERENT_TYPE",  # wrong document_type
        document_name_th=None,
        version="2.0",
        effective_from=date(2026, 6, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    await repo.finalize_model_document_revision(
        model_document_id=source.model_document_id,
        effective_to=date(2026, 5, 31),
        replaced_by_document_id=wrong_type_successor.model_document_id,
    )

    with pytest.raises(Exception) as exc_info:
        await service.revise_document(
            model_document_id=source.model_document_id,
            version="3.0",
            effective_from=date(2027, 1, 1),
            document_name_th=None,
            storage_ref=None,
            file_status=None,
            active_status=None,
            note_th=None,
        )
    assert "MODEL_DOCUMENT_REVISION_STATE_CONFLICT" in str(
        getattr(exc_info.value, "code", exc_info.value)
    )


# ---------------------------------------------------------------------------
# NO document_type CHAIN GROUPING (items 51-52)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_independent_same_type_documents_are_not_treated_as_one_chain(
    client: AsyncClient,
) -> None:
    """Items 51-52: two independent documents that happen to share the
    same document_type are NOT grouped into one chain — the revision
    chain is linked only by replaced_by_document_id, never inferred from
    document_type. Revising one must not mutate the other."""
    doc_a = await _create_document(
        client, "MODEL-0001", document_type="SHARED_TYPE_NO_CHAIN", version="A-1.0"
    )
    doc_b = await _create_document(
        client, "MODEL-0001", document_type="SHARED_TYPE_NO_CHAIN", version="B-1.0"
    )

    response = await client.post(
        f"/api/v1/model-documents/{doc_a['model_document_id']}/revise",
        json={"version": "A-2.0", "effective_from": "2026-06-01"},
    )
    assert response.status_code == 200

    doc_b_reread = await client.get(f"/api/v1/model-documents/{doc_b['model_document_id']}")
    assert doc_b_reread.json()["replaced_by_document_id"] is None
    assert doc_b_reread.json()["version"] == "B-1.0"
    assert doc_b_reread.json()["effective_to"] is None


# ---------------------------------------------------------------------------
# GOOGLE SHEETS (items 53-57)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_sheets_finalize_revision_preserves_unrelated_fields() -> None:
    """Item 55."""
    ws = _ws(schemas.MODEL_DOCUMENT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    source = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="GS_PRESERVE",
        document_name_th="ชื่อเดิม",
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        storage_ref="attachments/old.pdf",
        file_status="UPLOADED",
        active_status="ACTIVE",
        note_th="หมายเหตุ",
    )
    await repo.finalize_model_document_revision(
        model_document_id=source.model_document_id,
        effective_to=date(2026, 5, 31),
        replaced_by_document_id="MDOC-9001",
    )
    reread = await repo.get_model_document(source.model_document_id)
    assert reread is not None
    assert reread.document_name_th == "ชื่อเดิม"
    assert reread.version == "1.0"
    assert reread.effective_from == date(2026, 1, 1)
    assert reread.storage_ref == "attachments/old.pdf"
    assert reread.file_status == "UPLOADED"
    assert reread.active_status == "ACTIVE"
    assert reread.note_th == "หมายเหตุ"


@pytest.mark.asyncio
async def test_google_sheets_replaced_by_document_id_round_trips_as_text() -> None:
    """Item 56: same numeric-coercion protection class as Batch 1's
    `phone`/Batch 2A's `document_no`/`version`."""
    ws = _ws(schemas.MODEL_DOCUMENT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    source = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="GS_LINK_TEXT",
        document_name_th=None,
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    updated = await repo.finalize_model_document_revision(
        model_document_id=source.model_document_id,
        effective_to=date(2026, 5, 31),
        replaced_by_document_id="MDOC-0042",
    )
    assert updated.replaced_by_document_id == "MDOC-0042"

    reread = await repo.get_model_document(source.model_document_id)
    assert reread is not None
    assert reread.replaced_by_document_id == "MDOC-0042"


@pytest.mark.asyncio
async def test_google_sheets_old_effective_to_round_trips_as_date() -> None:
    """Item 57: effective_to is a genuine Sheet date, never text-forced."""
    ws = _ws(schemas.MODEL_DOCUMENT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    source = await repo.create_model_document(
        model_id="MODEL-0001",
        document_type="GS_EFFECTIVE_TO_DATE",
        document_name_th=None,
        version="1.0",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        storage_ref=None,
        file_status=None,
        active_status=None,
        note_th=None,
    )
    await repo.finalize_model_document_revision(
        model_document_id=source.model_document_id,
        effective_to=date(2026, 5, 31),
        replaced_by_document_id="MDOC-0043",
    )
    effective_to_column = schemas.MODEL_DOCUMENT_SHEET.required_headers.index("effective_to")
    raw_value = ws.rows[0][effective_to_column]
    # Never text-forced — no leading-apostrophe marker.
    assert not str(raw_value).startswith("'")
    assert str(raw_value) == "2026-05-31"

    reread = await repo.get_model_document(source.model_document_id)
    assert reread is not None
    assert reread.effective_to == date(2026, 5, 31)


@pytest.mark.asyncio
async def test_mock_and_google_sheets_revision_parity() -> None:
    """Item 54 (Mock parity is items 46-57 running through MockRepository
    directly via `client`/`_create_document`, which uses MockRepository;
    this test additionally proves both backends produce the same shape of
    result for the same revision scenario, mirroring Batch 2B's own
    parity test)."""
    results = {}
    for name, repo in (
        ("mock", MockRepository()),
        ("google_sheets", _repo_with_fake_sheets(_ws(schemas.MODEL_DOCUMENT_SHEET))),
    ):
        service = ModelDocumentService(repo)
        source = await repo.create_model_document(
            model_id="MODEL-0001",
            document_type="PARITY_TEST",
            document_name_th="ชื่อ",
            version="1.0",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            storage_ref=None,
            file_status=None,
            active_status="ACTIVE",
            note_th=None,
        )
        new_doc = await service.revise_document(
            model_document_id=source.model_document_id,
            version="2.0",
            effective_from=date(2026, 6, 1),
            document_name_th=None,
            storage_ref=None,
            file_status=None,
            active_status=None,
            note_th=None,
            fields_set=frozenset(),
        )
        old_reread = await repo.get_model_document(source.model_document_id)
        results[name] = {
            "new_version": new_doc.version,
            "new_document_name_th": new_doc.document_name_th,
            "new_active_status": new_doc.active_status,
            "new_effective_to": new_doc.effective_to,
            "old_effective_to": old_reread.effective_to if old_reread else None,
            "old_linked_to_new": (
                old_reread.replaced_by_document_id == new_doc.model_document_id
                if old_reread
                else False
            ),
        }

    assert results["mock"] == results["google_sheets"]
    assert results["mock"]["new_document_name_th"] == "ชื่อ"  # inherited
    assert results["mock"]["new_active_status"] == "ACTIVE"  # inherited
    assert results["mock"]["old_effective_to"] == date(2026, 5, 31)
    assert results["mock"]["old_linked_to_new"] is True


# ---------------------------------------------------------------------------
# REGRESSION (items 58-62) — run via the full test suite, not encoded as
# individual test functions here; see the implementation report for the
# actual pytest invocation results.
# ---------------------------------------------------------------------------
