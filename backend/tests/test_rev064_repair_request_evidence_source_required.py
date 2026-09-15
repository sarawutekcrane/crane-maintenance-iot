"""REV06.4 delta — final independent (REV06.3 micro-audit) finding fix.

The REV06.3 micro acceptance audit found that `REPAIR_REQUEST_EVIDENCE`
was the one transactional evidence purpose never added to
`_PURPOSES_REQUIRING_SOURCE` — its REV06.1 fix only validated a source
when one was *present*, but never required one. A source-less
`REPAIR_REQUEST_EVIDENCE` attachment was therefore accepted on upload and
then downloadable by ANY authenticated actor, with no authorization check
at all — not even the `can_view` capability that gates
`CHECKLIST_REFERENCE_IMAGE`. No frontend flow ever used this purpose
without a source (or at all), so this contradicted the established
REV05 section 4 contract ("Repair Request attachments... source_type =
REPAIR_REQUEST, source_id = repair_request_id") without any legitimate
reason to allow the exception.

`REPAIR_REQUEST_EVIDENCE` is now in `_PURPOSES_REQUIRING_SOURCE`,
matching `REPAIR_EVIDENCE`/`PM_EVIDENCE`/`INSPECTION_EVIDENCE` exactly.
The existing reporter/`can_manage_repair` authorization logic for a
*given* `REPAIR_REQUEST` source is unchanged — see
`test_attachment_source_authorization.py` for that regression coverage.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


def _evidence_files() -> dict:
    return {"file": ("evidence.jpg", b"fake-jpeg-bytes", "image/jpeg")}


async def _submit_repair_request(
    client: AsyncClient, reporter_user_id: str = "user-driver-1"
) -> str:
    response = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "มีเสียงดังผิดปกติ"},
        headers=_as("DRIVER", reporter_user_id),
    )
    assert response.status_code == 200
    return response.json()["request"]["repair_request_id"]


async def _upload(
    client: AsyncClient, source_type: str | None, source_id: str | None, headers: dict
):
    data: dict[str, str] = {"purpose": "REPAIR_REQUEST_EVIDENCE"}
    if source_type is not None:
        data["source_type"] = source_type
    if source_id is not None:
        data["source_id"] = source_id
    return await client.post(
        "/api/v1/attachments", data=data, files=_evidence_files(), headers=headers
    )


# ---------------------------------------------------------------------------
# 1 — the exact audited exploit: source-less REPAIR_REQUEST_EVIDENCE.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_less_upload_is_rejected_and_persists_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage.local import LocalFileStorageProvider

    async def _boom(self, filename: str, content_type: str, data: bytes):  # pragma: no cover
        raise AssertionError(
            "storage.save() was reached for a rejected source-less REPAIR_REQUEST_EVIDENCE upload"
        )

    monkeypatch.setattr(LocalFileStorageProvider, "save", _boom)

    response = await _upload(client, None, None, _as("DRIVER", "uploader"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_REQUIRED"

    # No row persisted: attachment_id was never issued at all, so there is
    # nothing to enumerate. ATT-0001 (the first id this fresh app instance
    # would ever issue) must not exist.
    lookup = await client.get(
        "/api/v1/attachments/ATT-0001/file", headers=_as("DRIVER", "uploader")
    )
    assert lookup.status_code == 404


# ---------------------------------------------------------------------------
# 2/3 — one-sided source fields rejected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_type_only_is_rejected(client: AsyncClient) -> None:
    response = await _upload(client, "REPAIR_REQUEST", None, _as("DRIVER"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_source_id_only_is_rejected(client: AsyncClient) -> None:
    """`source_type=None` paired with a real `source_id` is caught by the
    REV06.3 purpose/source_type compatibility check first (`None` is not
    in REPAIR_REQUEST_EVIDENCE's allowed set), before the older "both
    fields together" completeness check would otherwise fire — still a
    422 fail-closed rejection either way."""
    response = await _upload(client, None, "RRQ-0001", _as("DRIVER"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


# ---------------------------------------------------------------------------
# 4 — wrong source_type rejected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_source_type_is_rejected(client: AsyncClient) -> None:
    request_id = await _submit_repair_request(client)
    response = await _upload(client, "REPAIR", request_id, _as("DRIVER", "user-driver-1"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE"


# ---------------------------------------------------------------------------
# 5 — nonexistent Repair Request fails closed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonexistent_repair_request_is_rejected(client: AsyncClient) -> None:
    response = await _upload(client, "REPAIR_REQUEST", "RRQ-9999", _as("MAINTENANCE"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPAIR_REQUEST_NOT_FOUND"


# ---------------------------------------------------------------------------
# 6/7/8 — valid Repair Request source: reporter allowed, unrelated denied,
# can_manage_repair allowed. Authorization policy itself is unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_source_reporter_allowed(client: AsyncClient) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    response = await _upload(
        client, "REPAIR_REQUEST", request_id, _as("DRIVER", "user-driver-1")
    )
    assert response.status_code == 200
    assert response.json()["source_type"] == "REPAIR_REQUEST"
    assert response.json()["source_id"] == request_id

    download = await client.get(
        f"/api/v1/attachments/{response.json()['attachment_id']}/file",
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert download.status_code == 200
    assert download.content == b"fake-jpeg-bytes"


@pytest.mark.asyncio
async def test_valid_source_unrelated_actor_denied(client: AsyncClient) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    response = await _upload(
        client, "REPAIR_REQUEST", request_id, _as("DRIVER", "user-driver-2")
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_valid_source_can_manage_repair_allowed(client: AsyncClient) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")
    response = await _upload(client, "REPAIR_REQUEST", request_id, _as("MAINTENANCE"))
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 9/10 — a legacy source-less row (written directly through the
# repository, bypassing the now-fixed service-layer upload gate, to
# reproduce the exact shape a pre-REV06.4 row would have) must fail closed
# on download, with storage never touched.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_source_less_row_download_denied_storage_untouched(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.dependencies import get_repository
    from app.domain.attachment import AttachmentPurpose

    repository = get_repository()
    legacy = await repository.create_attachment(
        purpose=AttachmentPurpose.REPAIR_REQUEST_EVIDENCE,
        storage_ref="legacy-storage-ref-never-read",
        filename="legacy.jpg",
        content_type="image/jpeg",
        size_bytes=12,
        uploaded_by="dev-user",
        source_type=None,
        source_id=None,
    )

    from app.storage.local import LocalFileStorageProvider

    async def _boom(self, storage_ref: str):  # pragma: no cover - must never run
        raise AssertionError(
            "storage.read() was reached for a legacy source-less REPAIR_REQUEST_EVIDENCE row"
        )

    monkeypatch.setattr(LocalFileStorageProvider, "read", _boom)

    response = await client.get(
        f"/api/v1/attachments/{legacy.attachment_id}/file", headers=_as("MAINTENANCE")
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ATTACHMENT_SOURCE_REQUIRED"


# ---------------------------------------------------------------------------
# 11 — no row persistence after a rejected source-less upload, proven via
# the by-source listing for a real, unrelated Repair Request staying
# empty (belt-and-suspenders alongside test 1's direct attachment-id
# non-existence check).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_upload_does_not_contaminate_any_by_source_listing(
    client: AsyncClient,
) -> None:
    request_id = await _submit_repair_request(client, reporter_user_id="user-driver-1")

    rejected = await _upload(client, None, None, _as("DRIVER", "user-driver-1"))
    assert rejected.status_code == 403

    listing = await client.get(
        f"/api/v1/attachments/by-source/REPAIR_REQUEST/{request_id}",
        headers=_as("DRIVER", "user-driver-1"),
    )
    assert listing.status_code == 200
    assert listing.json() == []
