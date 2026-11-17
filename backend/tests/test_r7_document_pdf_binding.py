"""R7-A — certificate / model-document PDF binding (Owner-approved bounded
Mock/TEST scope, DEC-R7-MOCK-BOUNDED-APPROACH-20261111).

SYNTHETIC Mock data and synthetic PDF bytes only. A document file seeded through
the internal `AttachmentService` below is a TEST FIXTURE, never a production
authorization: no public route may create one (no Owner policy names the
uploaders), and these tests prove that. Mock results are not PostgreSQL or
production storage evidence (R11, M07, B04).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, get_settings
from app.context import RequestContext
from app.domain.attachment import DOCUMENT_ATTACHMENT_PURPOSES, AttachmentPurpose
from app.domain.attachment_service import AttachmentService
from app.domain.authz import CAN_VIEW
from app.domain.vehicle_certificate import CertificateStatus
from app.errors import ApiError
from app.repositories.mock.repository import MockRepository
from app.storage.local import LocalFileStorageProvider

API = "/api/v1"
PDF = b"%PDF-1.4\n% synthetic R7 TEST document\n1 0 obj <<>> endobj\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
VIEWER = RequestContext(request_id="r7", user_id="USR-TEST-R7", roles=("TECHNICIAN",), is_dev_auth=True,
                        capabilities=frozenset({CAN_VIEW}))


class SpyStorage(LocalFileStorageProvider):
    """Local storage that records every read (deny-before-storage-read proofs)."""

    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.reads: list[str] = []

    async def read(self, storage_ref: str) -> bytes:
        self.reads.append(storage_ref)
        return await super().read(storage_ref)


def _files(root: str) -> list[str]:
    return sorted(os.listdir(root))


async def _certificate(repo: MockRepository, vehicle_id: str = "VEH-1048", storage_ref: str | None = None,
                       status: CertificateStatus | None = CertificateStatus.ACTIVE, code: str = "R7-INSURANCE"):
    return await repo.create_vehicle_certificate(
        vehicle_id=vehicle_id, certificate_type_code=code, certificate_type_name_th="ประกันภัย (TEST)",
        document_no="000123", issue_date=date(2026, 1, 1), expiry_date=date(2099, 1, 1), alert_lead_days=30,
        certificate_status=status, storage_ref=storage_ref, note_th=None, created_by_user_id="USR-TEST-R7",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


async def _model_document(repo: MockRepository, model_id: str = "MODEL-0003", storage_ref: str | None = None):
    return await repo.create_model_document(
        model_id=model_id, document_type="LOAD_CHART", document_name_th="ตารางพิกัดยก (TEST)", version="Rev.A",
        effective_from=date(2026, 1, 1), effective_to=None, storage_ref=storage_ref, file_status=None,
        active_status=None, note_th=None)


def _service(repo, storage, **settings_update) -> AttachmentService:
    get_settings.cache_clear()
    settings = get_settings()
    if settings_update:
        settings = settings.model_copy(update=settings_update)
    return AttachmentService(repo, storage, settings)


async def _seed_pdf(repo, storage, purpose: AttachmentPurpose, source_type: str, source_id: str, data: bytes = PDF):
    """TEST FIXTURE: the internal boundary (not a public route, not an authorization)."""
    return await _service(repo, storage).upload_attachment(
        purpose=purpose, filename="synthetic.pdf", content_type="application/pdf", data=data,
        uploaded_by="USR-TEST-R7", source_type=source_type, source_id=source_id)


async def _http(method: str, path: str, repo, storage, *, role: str = "ADMIN", user: str | None = "USR-TEST-R7",
                raise_app_exceptions: bool = True, **kwargs):
    from app.dependencies import get_repository, get_storage_provider, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_storage_provider] = lambda: storage
    headers = {"X-Dev-Role": role, "X-Request-Id": str(uuid.uuid4())}
    if user is not None:
        headers["X-Dev-User-Id"] = user
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.request(method, path, headers=headers, **kwargs)
    reset_dependency_cache()
    get_settings.cache_clear()
    return response


def _code(response) -> tuple[int, str]:
    body = response.json()
    return response.status_code, body.get("error", {}).get("code", "")


@pytest.fixture
def storage(temp_upload_dir) -> SpyStorage:
    return SpyStorage(temp_upload_dir)


# ---------------------------------------------------------------------------
# Public upload stays closed (no Owner policy names an uploader)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose,source_type", [
    ("VEHICLE_CERTIFICATE_DOCUMENT", "VEHICLE_CERTIFICATE"),
    ("MODEL_DOCUMENT_FILE", "MODEL_DOCUMENT"),
])
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "MAINTENANCE_MANAGER", "TECHNICIAN", "NO_SUCH_ROLE"])
async def test_public_document_upload_is_refused_for_every_role_and_stores_nothing(
        storage, temp_upload_dir, purpose, source_type, role) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    doc = await _model_document(repo)
    source_id = cert.certificate_id if source_type == "VEHICLE_CERTIFICATE" else doc.model_document_id
    response = await _http("POST", f"{API}/attachments", repo, storage, role=role,
                           data={"purpose": purpose, "source_type": source_type, "source_id": source_id},
                           files={"file": ("cert.pdf", PDF, "application/pdf")})
    assert _code(response) == (403, "DOCUMENT_FILE_UPLOAD_POLICY_UNRESOLVED")
    assert _files(temp_upload_dir) == []
    assert await repo.list_attachments_for_source(source_type, source_id) == []


async def test_public_document_upload_is_refused_even_for_a_guessed_or_missing_record(storage, temp_upload_dir) -> None:
    repo = MockRepository()
    for data in ({"purpose": "VEHICLE_CERTIFICATE_DOCUMENT", "source_type": "VEHICLE_CERTIFICATE",
                  "source_id": "CERT-9999"},
                 {"purpose": "VEHICLE_CERTIFICATE_DOCUMENT"}):
        response = await _http("POST", f"{API}/attachments", repo, storage, data=data,
                               files={"file": ("cert.pdf", PDF, "application/pdf")})
        assert _code(response) == (403, "DOCUMENT_FILE_UPLOAD_POLICY_UNRESOLVED")
    assert _files(temp_upload_dir) == []


@pytest.mark.parametrize("purpose", ["INSPECTION_EVIDENCE", "REPAIR_EVIDENCE", "PM_EVIDENCE",
                                     "REPAIR_REQUEST_EVIDENCE", "CHECKLIST_REFERENCE_IMAGE"])
@pytest.mark.parametrize("source_type", ["VEHICLE_CERTIFICATE", "MODEL_DOCUMENT"])
async def test_a_photo_purpose_cannot_smuggle_a_document_source(storage, temp_upload_dir, purpose,
                                                                 source_type) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    doc = await _model_document(repo)
    source_id = cert.certificate_id if source_type == "VEHICLE_CERTIFICATE" else doc.model_document_id
    response = await _http("POST", f"{API}/attachments", repo, storage,
                           data={"purpose": purpose, "source_type": source_type, "source_id": source_id},
                           files={"file": ("x.png", PNG, "image/png")})
    assert _code(response) == (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")
    assert _files(temp_upload_dir) == []


# ---------------------------------------------------------------------------
# Read: authorized vs unauthorized, deny before any storage read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_a_can_view_actor_lists_and_downloads_the_bound_certificate_pdf(storage, role) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    attachment = await _seed_pdf(repo, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                 "VEHICLE_CERTIFICATE", cert.certificate_id)
    listed = await _http("GET", f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/{cert.certificate_id}", repo,
                         storage, role=role)
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()
    assert row["attachment_id"] == attachment.attachment_id
    assert row["purpose"] == "VEHICLE_CERTIFICATE_DOCUMENT"
    assert row["content_type"] == "application/pdf"
    assert row["url"] == f"/api/v1/attachments/{attachment.attachment_id}/file"
    assert "storage_ref" not in row  # the opaque storage reference is never disclosed
    file = await _http("GET", row["url"], repo, storage, role=role)
    assert file.status_code == 200
    assert file.content == PDF
    assert file.headers["content-type"].startswith("application/pdf")


async def test_a_can_view_actor_downloads_the_bound_model_document_pdf(storage) -> None:
    repo = MockRepository()
    doc = await _model_document(repo)
    attachment = await _seed_pdf(repo, storage, AttachmentPurpose.MODEL_DOCUMENT_FILE, "MODEL_DOCUMENT",
                                 doc.model_document_id)
    file = await _http("GET", f"{API}/attachments/{attachment.attachment_id}/file", repo, storage, role="TECHNICIAN")
    assert file.status_code == 200 and file.content == PDF


async def test_an_actor_without_can_view_is_refused_before_any_storage_or_record_read(storage) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    attachment = await _seed_pdf(repo, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                 "VEHICLE_CERTIFICATE", cert.certificate_id)
    file = await _http("GET", f"{API}/attachments/{attachment.attachment_id}/file", repo, storage,
                       role="NO_SUCH_ROLE")
    assert _code(file) == (403, "ATTACHMENT_SOURCE_NOT_AUTHORIZED")
    assert storage.reads == []
    listed = await _http("GET", f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/{cert.certificate_id}", repo,
                         storage, role="NO_SUCH_ROLE")
    assert _code(listed) == (403, "ATTACHMENT_SOURCE_NOT_AUTHORIZED")


async def test_id_enumeration_without_can_view_cannot_tell_a_real_record_from_a_guessed_one(storage) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    doc = await _model_document(repo)
    for source_type, source_id in (("VEHICLE_CERTIFICATE", cert.certificate_id),
                                   ("VEHICLE_CERTIFICATE", "CERT-9999"),
                                   ("MODEL_DOCUMENT", doc.model_document_id),
                                   ("MODEL_DOCUMENT", "MDOC-9999")):
        response = await _http("GET", f"{API}/attachments/by-source/{source_type}/{source_id}", repo, storage,
                               role="NO_SUCH_ROLE")
        assert _code(response) == (403, "ATTACHMENT_SOURCE_NOT_AUTHORIZED"), (source_type, source_id)


async def test_the_capability_is_checked_before_the_record_is_read() -> None:
    class NoReadRepo(MockRepository):
        async def get_vehicle_certificate(self, certificate_id):  # pragma: no cover - must not run
            raise AssertionError("record read before authorization")

        async def get_model_document(self, model_document_id):  # pragma: no cover - must not run
            raise AssertionError("record read before authorization")

    service = _service(NoReadRepo(), None)
    for context in (RequestContext(request_id="r", user_id="USR-X", capabilities=frozenset()),
                    RequestContext(request_id="r", user_id=None, capabilities=frozenset({CAN_VIEW})),
                    RequestContext(request_id="r", user_id="   ", capabilities=frozenset({CAN_VIEW}))):
        for source_type in ("VEHICLE_CERTIFICATE", "MODEL_DOCUMENT"):
            with pytest.raises(ApiError) as caught:
                await service.authorize_source(context, source_type, "ANY-ID", "read")
            assert caught.value.code == "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


async def test_a_nonexistent_document_is_not_found_for_an_authorized_reader(storage) -> None:
    repo = MockRepository()
    for path, expected in ((f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/CERT-9999",
                            "VEHICLE_CERTIFICATE_NOT_FOUND"),
                           (f"{API}/attachments/by-source/MODEL_DOCUMENT/MDOC-9999", "MODEL_DOCUMENT_NOT_FOUND"),
                           (f"{API}/attachments/ATT-9999/file", "ATTACHMENT_NOT_FOUND")):
        assert _code(await _http("GET", path, repo, storage)) == (404, expected)


async def test_a_document_whose_parent_vehicle_or_model_is_missing_fails_closed_before_storage(storage) -> None:
    repo = MockRepository()
    orphan_cert = await _certificate(repo, vehicle_id="VEH-DOES-NOT-EXIST")
    orphan_doc = await _model_document(repo, model_id="MODEL-DOES-NOT-EXIST")
    stored = await storage.save("x.pdf", "application/pdf", PDF)
    rows = [await repo.create_attachment(purpose=AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                         storage_ref=stored.storage_ref, filename="x.pdf",
                                         content_type="application/pdf", size_bytes=len(PDF), uploaded_by=None,
                                         source_type="VEHICLE_CERTIFICATE", source_id=orphan_cert.certificate_id),
            await repo.create_attachment(purpose=AttachmentPurpose.MODEL_DOCUMENT_FILE,
                                         storage_ref=stored.storage_ref, filename="x.pdf",
                                         content_type="application/pdf", size_bytes=len(PDF), uploaded_by=None,
                                         source_type="MODEL_DOCUMENT", source_id=orphan_doc.model_document_id)]
    for row in rows:
        response = await _http("GET", f"{API}/attachments/{row.attachment_id}/file", repo, storage)
        assert _code(response) == (403, "ATTACHMENT_SOURCE_RELATIONSHIP_INVALID")
    assert storage.reads == []
    # The internal fixture path refuses to create such a file in the first place.
    with pytest.raises(ApiError) as caught:
        await _seed_pdf(repo, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, "VEHICLE_CERTIFICATE",
                        orphan_cert.certificate_id)
    assert caught.value.code == "ATTACHMENT_SOURCE_RELATIONSHIP_INVALID"


async def test_a_malformed_purpose_source_row_is_never_served(storage) -> None:
    """Possession of an attachment id never grants access: a row whose purpose and
    source disagree (whatever created it) or that lost its source fails closed."""
    repo = MockRepository()
    cert = await _certificate(repo)
    doc = await _model_document(repo)
    stored = await storage.save("x.pdf", "application/pdf", PDF)

    async def row(purpose, source_type, source_id):
        return await repo.create_attachment(purpose=purpose, storage_ref=stored.storage_ref, filename="x.pdf",
                                            content_type="application/pdf", size_bytes=len(PDF), uploaded_by=None,
                                            source_type=source_type, source_id=source_id)

    cases = [
        (await row(AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, "MODEL_DOCUMENT", doc.model_document_id),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        (await row(AttachmentPurpose.MODEL_DOCUMENT_FILE, "VEHICLE_CERTIFICATE", cert.certificate_id),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        (await row(AttachmentPurpose.INSPECTION_EVIDENCE, "VEHICLE_CERTIFICATE", cert.certificate_id),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        (await row(AttachmentPurpose.CHECKLIST_REFERENCE_IMAGE, "MODEL_DOCUMENT", doc.model_document_id),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        (await row(AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, None, None), (403, "ATTACHMENT_SOURCE_REQUIRED")),
        (await row(AttachmentPurpose.MODEL_DOCUMENT_FILE, None, None), (403, "ATTACHMENT_SOURCE_REQUIRED")),
    ]
    for attachment, expected in cases:
        response = await _http("GET", f"{API}/attachments/{attachment.attachment_id}/file", repo, storage)
        assert _code(response) == expected, attachment.purpose
    assert storage.reads == []


# ---------------------------------------------------------------------------
# Internal document-file checks (TEST fixture boundary)
# ---------------------------------------------------------------------------


async def test_internal_fixture_accepts_only_a_real_signature_pdf_and_stores_nothing_otherwise(
        storage, temp_upload_dir) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    service = _service(repo, storage)
    source = {"source_type": "VEHICLE_CERTIFICATE", "source_id": cert.certificate_id}
    purpose = AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT
    max_size = get_settings().attachment_max_size_bytes
    refused = [
        ({"content_type": "application/pdf", "data": b""}, "VALIDATION_ERROR"),
        ({"content_type": "application/pdf", "data": b"GIF89a not a pdf"}, "ATTACHMENT_CONTENT_MISMATCH"),
        ({"content_type": "application/pdf", "data": b" %PDF-1.4 leading byte"}, "ATTACHMENT_CONTENT_MISMATCH"),
        ({"content_type": "image/png", "data": PDF}, "ATTACHMENT_TYPE_NOT_ALLOWED"),
        ({"content_type": "application/octet-stream", "data": PDF}, "ATTACHMENT_TYPE_NOT_ALLOWED"),
        ({"content_type": "application/pdf", "data": b"%PDF-" + b"0" * max_size}, "ATTACHMENT_TOO_LARGE"),
    ]
    for kwargs, expected in refused:
        with pytest.raises(ApiError) as caught:
            await service.upload_attachment(purpose=purpose, filename="../../evil.exe", uploaded_by=None,
                                            **kwargs, **source)
        assert caught.value.code == expected, kwargs["content_type"]
    for bad_source, expected in (({"source_type": "MODEL_DOCUMENT", "source_id": "MDOC-0001"},
                                  "ATTACHMENT_SOURCE_REQUIRED"),
                                 ({"source_type": None, "source_id": None}, "ATTACHMENT_SOURCE_REQUIRED"),
                                 ({"source_type": "VEHICLE_CERTIFICATE", "source_id": "  "},
                                  "ATTACHMENT_SOURCE_REQUIRED"),
                                 ({"source_type": "VEHICLE_CERTIFICATE", "source_id": "CERT-9999"},
                                  "VEHICLE_CERTIFICATE_NOT_FOUND")):
        with pytest.raises(ApiError) as caught:
            await service.upload_attachment(purpose=purpose, filename="a.pdf", content_type="application/pdf",
                                            data=PDF, uploaded_by=None, **bad_source)
        assert caught.value.code == expected, bad_source
    assert _files(temp_upload_dir) == []

    ok = await service.upload_attachment(purpose=purpose, filename="../../ใบรับรอง 01.PDF",
                                         content_type="APPLICATION/PDF", data=PDF, uploaded_by="USR-TEST-R7",
                                         **source)
    assert ok.filename.endswith(".pdf") and "/" not in ok.filename and ".." not in ok.filename
    assert ok.content_type == "application/pdf" and ok.size_bytes == len(PDF)
    assert (ok.source_type, ok.source_id) == ("VEHICLE_CERTIFICATE", cert.certificate_id)
    assert _files(temp_upload_dir) == [ok.storage_ref]


async def test_internal_fixture_fails_closed_outside_the_synthetic_mock_repository(storage, temp_upload_dir) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    service = _service(repo, storage, data_repository=DataRepositoryMode.GOOGLE_SHEETS)
    with pytest.raises(ApiError) as caught:
        await service.upload_attachment(purpose=AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, filename="a.pdf",
                                        content_type="application/pdf", data=PDF, uploaded_by=None,
                                        source_type="VEHICLE_CERTIFICATE", source_id=cert.certificate_id)
    assert (caught.value.status_code, caught.value.code) == (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")
    assert _files(temp_upload_dir) == []


async def test_photo_purposes_still_refuse_pdf_and_still_accept_images(storage, temp_upload_dir) -> None:
    repo = MockRepository()
    source = {"source_type": "INSPECTION_VEHICLE", "source_id": "VEH-1046"}
    refused = await _http("POST", f"{API}/attachments", repo, storage,
                          data={"purpose": "INSPECTION_EVIDENCE", **source},
                          files={"file": ("evidence.pdf", PDF, "application/pdf")})
    assert _code(refused) == (422, "ATTACHMENT_TYPE_NOT_ALLOWED")
    assert _files(temp_upload_dir) == []
    accepted = await _http("POST", f"{API}/attachments", repo, storage,
                           data={"purpose": "INSPECTION_EVIDENCE", **source},
                           files={"file": ("evidence.png", PNG, "image/png")})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["purpose"] == "INSPECTION_EVIDENCE"
    assert len(_files(temp_upload_dir)) == 1
    assert get_settings().attachment_max_size_bytes == 10 * 1024 * 1024  # development default unchanged
    assert "application/pdf" not in get_settings().attachment_allowed_content_types_set


async def test_the_route_reads_at_most_one_byte_past_the_limit(storage, temp_upload_dir, monkeypatch) -> None:
    monkeypatch.setenv("ATTACHMENT_MAX_SIZE_BYTES", "10")
    response = await _http("POST", f"{API}/attachments", MockRepository(), storage,
                           data={"purpose": "INSPECTION_EVIDENCE", "source_type": "INSPECTION_VEHICLE",
                                 "source_id": "VEH-1046"},
                           files={"file": ("big.png", b"x" * 5000, "image/png")})
    assert _code(response) == (422, "ATTACHMENT_TOO_LARGE")
    assert response.json()["error"]["details"] == {"max_size_bytes": 10, "size_bytes": 11}
    assert _files(temp_upload_dir) == []


# ---------------------------------------------------------------------------
# Metadata failure (Correction R1): never delete on an ambiguous outcome
# ---------------------------------------------------------------------------


class FlakyAttachmentRepo(MockRepository):
    """`mode="before"`: raise BEFORE the row is written (pre-commit failure).
    `mode="after"`: write the row, THEN raise (commit-then-raise: the caller sees
    an error although the metadata is durably persisted)."""

    def __init__(self, failures: int, mode: str) -> None:
        super().__init__()
        self.failures = failures
        self.failure_mode = mode
        self.committed: list = []

    async def create_attachment(self, **kwargs):
        if self.failures > 0:
            self.failures -= 1
            if self.failure_mode == "after":
                self.committed.append(await super().create_attachment(**kwargs))
            raise RuntimeError(f"injected metadata failure ({self.failure_mode})")
        return await super().create_attachment(**kwargs)


class DeleteSpyStorage(SpyStorage):
    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.deletes: list[str] = []

    async def delete(self, storage_ref: str) -> None:
        self.deletes.append(storage_ref)
        await super().delete(storage_ref)


# Every purpose shares `_store_and_record`: the R7 document purposes AND the
# pre-existing photo/evidence purposes (Inspection / PM / Repair / Repair Request).
_UPLOAD_CASES = {
    "VEHICLE_CERTIFICATE_DOCUMENT": dict(purpose=AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, filename="a.pdf",
                                         content_type="application/pdf", data=PDF,
                                         source_type="VEHICLE_CERTIFICATE"),
    "MODEL_DOCUMENT_FILE": dict(purpose=AttachmentPurpose.MODEL_DOCUMENT_FILE, filename="a.pdf",
                                content_type="application/pdf", data=PDF, source_type="MODEL_DOCUMENT"),
    "INSPECTION_EVIDENCE": dict(purpose=AttachmentPurpose.INSPECTION_EVIDENCE, filename="a.png",
                                content_type="image/png", data=PNG, source_type="INSPECTION_VEHICLE",
                                source_id="VEH-1046"),
    "PM_EVIDENCE": dict(purpose=AttachmentPurpose.PM_EVIDENCE, filename="a.png", content_type="image/png", data=PNG,
                        source_type="PM_WORK_ORDER", source_id="PMWO-TEST-R7"),
    "REPAIR_EVIDENCE": dict(purpose=AttachmentPurpose.REPAIR_EVIDENCE, filename="a.png", content_type="image/png",
                            data=PNG, source_type="REPAIR", source_id="REP-TEST-R7"),
    "REPAIR_REQUEST_EVIDENCE": dict(purpose=AttachmentPurpose.REPAIR_REQUEST_EVIDENCE, filename="a.png",
                                    content_type="image/png", data=PNG, source_type="REPAIR_REQUEST",
                                    source_id="RR-TEST-R7"),
}


async def _upload_kwargs(repo, case: str) -> dict:
    kwargs = dict(_UPLOAD_CASES[case])
    if case == "VEHICLE_CERTIFICATE_DOCUMENT":
        kwargs["source_id"] = (await _certificate(repo)).certificate_id
    elif case == "MODEL_DOCUMENT_FILE":
        kwargs["source_id"] = (await _model_document(repo)).model_document_id
    return kwargs


@pytest.mark.parametrize("case", sorted(_UPLOAD_CASES))
async def test_commit_then_raise_keeps_the_persisted_rows_file_and_surfaces_the_error(
        temp_upload_dir, case) -> None:
    """The unsafe-deletion regression: the row IS persisted, the caller sees an
    error. The file the row points at must still exist and be readable."""
    storage = DeleteSpyStorage(temp_upload_dir)
    repo = FlakyAttachmentRepo(failures=1, mode="after")
    historical = await storage.save("historical.pdf", "application/pdf", PDF)
    kwargs = await _upload_kwargs(repo, case)
    with pytest.raises(RuntimeError, match=r"injected metadata failure \(after\)"):
        await _service(repo, storage).upload_attachment(uploaded_by=None, **kwargs)
    (row,) = repo.committed
    assert [a.attachment_id for a in await repo.list_attachments_for_source(
        kwargs["source_type"], kwargs["source_id"])] == [row.attachment_id]
    assert storage.deletes == []
    assert await storage.exists(row.storage_ref)
    assert await storage.read(row.storage_ref) == kwargs["data"]
    assert sorted(_files(temp_upload_dir)) == sorted([historical.storage_ref, row.storage_ref])


@pytest.mark.parametrize("case", ["VEHICLE_CERTIFICATE_DOCUMENT", "MODEL_DOCUMENT_FILE", "INSPECTION_EVIDENCE"])
async def test_commit_then_raise_file_stays_downloadable_through_the_authorized_route(
        temp_upload_dir, case) -> None:
    storage = DeleteSpyStorage(temp_upload_dir)
    repo = FlakyAttachmentRepo(failures=1, mode="after")
    kwargs = await _upload_kwargs(repo, case)
    with pytest.raises(RuntimeError):
        await _service(repo, storage).upload_attachment(uploaded_by=None, **kwargs)
    (row,) = repo.committed
    file = await _http("GET", f"{API}/attachments/{row.attachment_id}/file", repo, storage)
    assert file.status_code == 200, file.text
    assert file.content == kwargs["data"]
    assert storage.deletes == []


@pytest.mark.parametrize("case", sorted(_UPLOAD_CASES))
async def test_pre_commit_failure_deletes_nothing_and_a_retry_succeeds(temp_upload_dir, case) -> None:
    """No row was written. Nothing is deleted — the historical file certainly
    not; the new bytes are left as a documented unreferenced orphan (the outcome
    cannot be proven across the two stores) — and a retry records normally."""
    storage = DeleteSpyStorage(temp_upload_dir)
    repo = FlakyAttachmentRepo(failures=1, mode="before")
    historical = await storage.save("historical.pdf", "application/pdf", PDF)
    kwargs = await _upload_kwargs(repo, case)
    service = _service(repo, storage)
    with pytest.raises(RuntimeError, match=r"injected metadata failure \(before\)"):
        await service.upload_attachment(uploaded_by=None, **kwargs)
    assert storage.deletes == []
    assert await storage.read(historical.storage_ref) == PDF
    assert await repo.list_attachments_for_source(kwargs["source_type"], kwargs["source_id"]) == []
    files_after_failure = _files(temp_upload_dir)
    assert historical.storage_ref in files_after_failure and len(files_after_failure) == 2  # + 1 orphan

    retried = await service.upload_attachment(uploaded_by=None, **kwargs)
    assert [a.attachment_id for a in await repo.list_attachments_for_source(
        kwargs["source_type"], kwargs["source_id"])] == [retried.attachment_id]
    assert await storage.read(retried.storage_ref) == kwargs["data"]
    assert storage.deletes == []


async def test_an_http_metadata_failure_is_not_reported_as_success_and_deletes_nothing(temp_upload_dir) -> None:
    storage = DeleteSpyStorage(temp_upload_dir)
    for mode in ("before", "after"):
        repo = FlakyAttachmentRepo(failures=1, mode=mode)
        response = await _http("POST", f"{API}/attachments", repo, storage, raise_app_exceptions=False,
                               data={"purpose": "INSPECTION_EVIDENCE", "source_type": "INSPECTION_VEHICLE",
                                     "source_id": "VEH-1046"},
                               files={"file": ("a.png", PNG, "image/png")})
        assert _code(response) == (500, "INTERNAL_ERROR"), mode
        for row in repo.committed:
            assert await storage.read(row.storage_ref) == PNG
    assert storage.deletes == []


async def test_a_successful_photo_upload_is_unchanged(temp_upload_dir) -> None:
    storage = DeleteSpyStorage(temp_upload_dir)
    repo = MockRepository()
    response = await _http("POST", f"{API}/attachments", repo, storage,
                           data={"purpose": "INSPECTION_EVIDENCE", "source_type": "INSPECTION_VEHICLE",
                                 "source_id": "VEH-1046"},
                           files={"file": ("../evil name.PNG", PNG, "image/png")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["purpose"], body["content_type"], body["size_bytes"]) == ("INSPECTION_EVIDENCE", "image/png", len(PNG))
    assert body["filename"] == "evil_name.png"
    assert body["url"] == f"/api/v1/attachments/{body['attachment_id']}/file"
    file = await _http("GET", body["url"], repo, storage)
    assert file.status_code == 200 and file.content == PNG
    assert storage.deletes == []


async def test_a_listed_document_file_is_metadata_only_bytes_are_not_checked_by_the_list(temp_upload_dir) -> None:
    """Documents the real contract (Correction R1 item 7): list-by-source proves
    the row exists and the caller may read it — it performs no storage read or
    exists check. If the bytes are gone, the list still shows the row and only
    the download fails (no fabricated file)."""
    storage = SpyStorage(temp_upload_dir)
    repo = MockRepository()
    cert = await _certificate(repo)
    attachment = await _seed_pdf(repo, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                 "VEHICLE_CERTIFICATE", cert.certificate_id)
    os.remove(os.path.join(temp_upload_dir, attachment.storage_ref))  # bytes lost outside the application
    listed = await _http("GET", f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/{cert.certificate_id}", repo,
                         storage)
    assert [a["attachment_id"] for a in listed.json()] == [attachment.attachment_id]
    assert storage.reads == []
    file = await _http("GET", f"{API}/attachments/{attachment.attachment_id}/file", repo, storage,
                       raise_app_exceptions=False)
    # R7 policy R1 P-4b: missing bytes are an honest 404, never a generic 500 or a fabricated file.
    assert _code(file) == (404, "ATTACHMENT_FILE_MISSING")
    assert attachment.storage_ref not in file.text  # no storage path disclosed


# ---------------------------------------------------------------------------
# History: renew / revise keep each file with its own record; storage_ref opaque
# ---------------------------------------------------------------------------


async def test_renewal_creates_a_successor_that_owns_no_inherited_file(storage) -> None:
    repo = MockRepository()
    old = await _certificate(repo, storage_ref="https://legacy.example.invalid/000123.pdf")
    old_file = await _seed_pdf(repo, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, "VEHICLE_CERTIFICATE",
                               old.certificate_id)
    renewed = await _http("POST", f"{API}/certificates/{old.certificate_id}/renew", repo, storage,
                          json={"expiry_date": "2100-01-01"})
    assert renewed.status_code == 200, renewed.text
    new_id = renewed.json()["certificate_id"]
    assert renewed.json()["storage_ref"] is None  # omitted -> never inherited
    old_list = await _http("GET", f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/{old.certificate_id}", repo,
                           storage)
    new_list = await _http("GET", f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/{new_id}", repo, storage)
    assert [a["attachment_id"] for a in old_list.json()] == [old_file.attachment_id]
    assert new_list.json() == []
    old_now = await _http("GET", f"{API}/certificates/{old.certificate_id}", repo, storage)
    assert old_now.json()["certificate_status"] == "REPLACED"
    assert old_now.json()["storage_ref"] == "https://legacy.example.invalid/000123.pdf"
    # The old file stays readable through its own (now REPLACED) record.
    assert (await _http("GET", f"{API}/attachments/{old_file.attachment_id}/file", repo, storage)).content == PDF
    # A retry of the same renewal returns the same successor (existing guarantee), no new file.
    again = await _http("POST", f"{API}/certificates/{old.certificate_id}/renew", repo, storage,
                        json={"expiry_date": "2100-01-01"})
    assert again.json()["certificate_id"] == new_id
    assert len(await repo.list_attachments_for_source("VEHICLE_CERTIFICATE", new_id)) == 0


async def test_revision_creates_a_new_row_that_owns_its_own_file_independently(storage) -> None:
    repo = MockRepository()
    old = await _model_document(repo, storage_ref="0007")
    old_file = await _seed_pdf(repo, storage, AttachmentPurpose.MODEL_DOCUMENT_FILE, "MODEL_DOCUMENT",
                               old.model_document_id)
    revised = await _http("POST", f"{API}/model-documents/{old.model_document_id}/revise", repo, storage,
                          json={"version": "Rev.B", "effective_from": "2026-06-01", "storage_ref": None})
    assert revised.status_code == 200, revised.text
    new_id = revised.json()["model_document_id"]
    assert revised.json()["storage_ref"] is None
    new_pdf = PDF.replace(b"synthetic", b"revised  ")
    new_file = await _seed_pdf(repo, storage, AttachmentPurpose.MODEL_DOCUMENT_FILE, "MODEL_DOCUMENT", new_id,
                               data=new_pdf)
    assert (await _http("GET", f"{API}/attachments/{old_file.attachment_id}/file", repo, storage)).content == PDF
    assert (await _http("GET", f"{API}/attachments/{new_file.attachment_id}/file", repo, storage)).content == new_pdf
    old_now = await _http("GET", f"{API}/model-documents/{old.model_document_id}", repo, storage)
    assert old_now.json()["storage_ref"] == "0007" and old_now.json()["replaced_by_document_id"] == new_id


@pytest.mark.parametrize("legacy_ref", ["000123", "https://legacy.example.invalid/a.pdf", "../../etc/passwd",
                                        "ATT-0001", "แฟ้มเดิม/ใบรับรอง.pdf"])
async def test_a_historical_storage_ref_is_opaque_text_never_a_verified_server_file(storage, legacy_ref) -> None:
    repo = MockRepository()
    # A real attachment exists so a ref that *looks like* an attachment id is a meaningful probe.
    other = await _certificate(repo, code="R7-OTHER")
    await _seed_pdf(repo, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, "VEHICLE_CERTIFICATE",
                    other.certificate_id)
    cert = await _certificate(repo, storage_ref=legacy_ref)
    read = await _http("GET", f"{API}/certificates/{cert.certificate_id}", repo, storage)
    assert read.json()["storage_ref"] == legacy_ref  # preserved exactly, never normalized
    listed = await _http("GET", f"{API}/attachments/by-source/VEHICLE_CERTIFICATE/{cert.certificate_id}", repo,
                         storage)
    assert listed.status_code == 200 and listed.json() == []  # no file is inferred from the ref
    assert storage.reads == []
    assert (await repo.get_vehicle_certificate(cert.certificate_id)).storage_ref == legacy_ref


def test_document_purposes_are_exactly_the_two_bound_purposes() -> None:
    assert DOCUMENT_ATTACHMENT_PURPOSES == {AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                            AttachmentPurpose.MODEL_DOCUMENT_FILE}


# ---------------------------------------------------------------------------
# Access Management mode (D6)
# ---------------------------------------------------------------------------


async def test_d6_access_mode_keeps_document_writes_closed_and_reads_capability_gated(
        monkeypatch, storage, temp_upload_dir) -> None:
    from tests.test_access_management import API as AM_API, DRV1, MGR, employee, grant, http

    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
    store = MockRepository(access_management_seed=True)
    cert = await _certificate(store)
    doc = await _model_document(store)
    for method, path in (("POST", f"{AM_API}/vehicles/VEH-1046/certificates"),
                         ("POST", f"{AM_API}/certificates/{cert.certificate_id}/renew"),
                         ("POST", f"{AM_API}/models/MODEL-0001/documents"),
                         ("POST", f"{AM_API}/model-documents/{doc.model_document_id}/revise")):
        response = await http(method, path, store, MGR, json={})
        # R7 policy R1 P-1: left the D6 list for the TEST-only gate; no grant -> still refused.
        assert _code(response) == (403, "DOCUMENT_MASTER_NOT_AUTHORIZED"), path

    from app.dependencies import get_storage_provider

    async def am(method, path, user, **kwargs):
        from app.dependencies import get_repository, reset_dependency_cache
        from app.main import create_app

        get_settings.cache_clear()
        reset_dependency_cache()
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: store
        app.dependency_overrides[get_storage_provider] = lambda: storage
        headers = {"X-Dev-Role": "ADMIN", "X-Dev-User-Id": user, "X-Request-Id": str(uuid.uuid4())}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, **kwargs)

    upload = await am("POST", f"{API}/attachments", MGR,
                      data={"purpose": "VEHICLE_CERTIFICATE_DOCUMENT", "source_type": "VEHICLE_CERTIFICATE",
                            "source_id": cert.certificate_id},
                      files={"file": ("a.pdf", PDF, "application/pdf")})
    # R7 TEST: the root holder holds no document-manager grant -> refused, nothing stored.
    assert _code(upload) == (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")  # even the root holder
    assert _files(temp_upload_dir) == []

    attachment = await _seed_pdf(store, storage, AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                 "VEHICLE_CERTIFICATE", cert.certificate_id)
    refused = await am("GET", f"{API}/attachments/{attachment.attachment_id}/file", DRV1)
    assert _code(refused) == (403, "ATTACHMENT_SOURCE_NOT_AUTHORIZED")  # zero grants, X-Dev-Role ignored
    assert storage.reads == []
    granted = await grant(store, MGR, employee(DRV1), {"can_view": True})
    assert granted.status_code == 200, granted.text
    allowed = await am("GET", f"{API}/attachments/{attachment.attachment_id}/file", DRV1)
    assert allowed.status_code == 200 and allowed.content == PDF
    get_settings.cache_clear()



# ---------------------------------------------------------------------------
# R7 TEST-only PDF Management (Source Contract v1.0, 2026-11-14)
#
# The public upload is opened ONLY for a verified TEST employee holding the
# dedicated `can_manage_test_document_file` grant in Access Management mode.
# Catalog Correction R1 (Owner approval 2026-11-16): the grant is catalogued in
# category I as a root-only, non-delegable (SENSITIVE) capability, so the REAL
# audited grant / revoke API issues and honors it — see the `test_am_real_*`
# tests below (no dependency override, no fake /me). The `_manager` contexts
# are kept as focused unit tests of the gate's ordering and refusals.
# ---------------------------------------------------------------------------

from app.domain.authz import (  # noqa: E402
    ALL_CAPABILITIES,
    CAN_MANAGE_PM,
    CAN_MANAGE_TEST_DOCUMENT_FILE,
    ROLE_CAPABILITIES,
    TEST_ONLY_CAPABILITIES,
)
from app.domain.inspection_service import InspectionService  # noqa: E402

MGR_USER, MGR_PERSON = "USR-TEST-AM-MGR", "PER-TEST-AM-MGR"


def _manager(capabilities=frozenset({CAN_VIEW, CAN_MANAGE_TEST_DOCUMENT_FILE}), *, user_id=MGR_USER,
             personnel_id=MGR_PERSON, access=True) -> RequestContext:
    """SIMULATED Access-Management-resolved context (see the section note)."""
    return RequestContext(request_id="r7-test", user_id=user_id, roles=("TECHNICIAN",), is_dev_auth=True,
                          capabilities=frozenset(capabilities), personnel_id=personnel_id,
                          access=object() if access else None)


def _inspection_service(repo, storage, **settings_update) -> InspectionService:
    get_settings.cache_clear()
    update = {"access_management_mode": True, "data_repository": DataRepositoryMode.MOCK, **settings_update}
    return InspectionService(repo, storage, get_settings().model_copy(update=update))


async def _gate_upload(repo, storage, context, *, purpose=AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                       source_type="VEHICLE_CERTIFICATE", source_id=None, data=PDF, content_type="application/pdf",
                       filename="cert.pdf", **settings_update):
    return await _inspection_service(repo, storage, **settings_update).upload_attachment(
        purpose=purpose, filename=filename, content_type=content_type, data=data, uploaded_by=context.user_id,
        context=context, source_type=source_type, source_id=source_id)


def test_the_test_document_capability_has_no_default_holder() -> None:
    assert TEST_ONLY_CAPABILITIES == {"can_manage_test_document_file", "can_manage_test_document_master",
                                      "can_run_test_alert_evaluation", "can_act_on_test_alert"}
    for capability in TEST_ONLY_CAPABILITIES:
        assert capability not in ALL_CAPABILITIES  # ADMIN does not inherit it
        assert all(capability not in caps for caps in ROLE_CAPABILITIES.values())


async def test_a_simulated_test_manager_uploads_lists_and_reads_both_document_kinds(storage, temp_upload_dir) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    doc = await _model_document(repo)
    manager = _manager()
    service = _inspection_service(repo, storage)
    cases = ((AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, "VEHICLE_CERTIFICATE", cert.certificate_id,
              PDF + b"cert"),
             (AttachmentPurpose.MODEL_DOCUMENT_FILE, "MODEL_DOCUMENT", doc.model_document_id, PDF + b"model"))
    for purpose, source_type, source_id, data in cases:
        stored = await _gate_upload(repo, storage, manager, purpose=purpose, source_type=source_type,
                                    source_id=source_id, data=data, filename="../../ใบ cert<>.PDF")
        assert (stored.purpose, stored.source_type, stored.source_id) == (purpose, source_type, source_id)
        assert (stored.content_type, stored.size_bytes, stored.uploaded_by) == ("application/pdf", len(data), MGR_USER)
        assert stored.filename == "cert.pdf"  # path / unsafe characters stripped, .pdf enforced
        listed = await service.list_attachments_for_source(source_type, source_id, manager)
        assert [a.attachment_id for a in listed] == [stored.attachment_id]
        readable = await service.require_readable_attachment(stored.attachment_id, manager)
        assert await service.read_attachment_bytes(readable) == data  # exact bytes
    assert len(_files(temp_upload_dir)) == 2
    # The relation is stable: neither record lists the other's file.
    assert [a.purpose for a in await repo.list_attachments_for_source("VEHICLE_CERTIFICATE", cert.certificate_id)] \
        == [AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT]


@pytest.mark.parametrize("label,context,settings_update,expected", [
    ("can_view only", _manager({CAN_VIEW}), {}, (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")),
    ("can_manage_pm + can_view", _manager({CAN_VIEW, CAN_MANAGE_PM}), {}, (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")),
    ("every ordinary capability", _manager(ALL_CAPABILITIES), {}, (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")),
    ("revoked grant (no capability)", _manager(frozenset()), {}, (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")),
    ("unlinked / unknown / wrong-batch / inactive employee", _manager(personnel_id=None), {},
     (403, "ACCESS_ACTOR_NOT_VERIFIED")),
    ("context not resolved by Access Management", _manager(access=False), {}, (403, "ACCESS_ACTOR_NOT_VERIFIED")),
    ("blank actor", _manager(user_id="  "), {}, (403, "ACCESS_ACTOR_NOT_VERIFIED")),
    ("missing actor", _manager(user_id=None), {}, (403, "ACCESS_ACTOR_NOT_VERIFIED")),
    ("legacy development-role mode", _manager(), {"access_management_mode": False},
     (403, "DOCUMENT_FILE_UPLOAD_POLICY_UNRESOLVED")),
    ("non-Mock repository", _manager(), {"data_repository": DataRepositoryMode.GOOGLE_SHEETS},
     (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")),
    ("PostgreSQL repository", _manager(), {"data_repository": DataRepositoryMode.POSTGRESQL},
     (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")),
])
async def test_the_upload_gate_fails_closed_before_any_record_or_storage_access(
        temp_upload_dir, label, context, settings_update, expected) -> None:
    class NoReadRepo(MockRepository):
        async def get_vehicle_certificate(self, certificate_id):  # pragma: no cover - must not be reached
            raise AssertionError(f"record read before the gate refused: {label}")

    storage = SpyStorage(temp_upload_dir)
    with pytest.raises(ApiError) as refused:
        await _gate_upload(NoReadRepo(), storage, context, source_id="CERT-ANY", **settings_update)
    assert (refused.value.status_code, refused.value.code) == expected, label
    assert _files(temp_upload_dir) == [] and storage.reads == []


async def test_a_non_test_data_context_is_refused(monkeypatch, storage, temp_upload_dir) -> None:
    from app.config import Settings

    repo = MockRepository()
    cert = await _certificate(repo)
    monkeypatch.setattr(Settings, "registry_context_effective", property(lambda self: "REAL"))
    with pytest.raises(ApiError) as refused:
        await _gate_upload(repo, storage, _manager(), source_id=cert.certificate_id)
    assert (refused.value.status_code, refused.value.code) == (403, "DOCUMENT_FILE_UPLOAD_TEST_ONLY")
    assert _files(temp_upload_dir) == []


async def test_a_manager_without_can_view_cannot_upload_or_probe_records(storage, temp_upload_dir) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    for source_id in (cert.certificate_id, "CERT-GUESSED"):
        with pytest.raises(ApiError) as refused:
            await _gate_upload(repo, storage, _manager({CAN_MANAGE_TEST_DOCUMENT_FILE}), source_id=source_id)
        assert (refused.value.status_code, refused.value.code) == (403, "ATTACHMENT_SOURCE_NOT_AUTHORIZED")
    assert _files(temp_upload_dir) == []


async def test_the_manager_cannot_bind_a_file_to_a_wrong_guessed_or_broken_record(storage, temp_upload_dir) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    doc = await _model_document(repo)
    orphan_cert = await _certificate(repo, vehicle_id="VEH-DOES-NOT-EXIST")
    orphan_doc = await _model_document(repo, model_id="MODEL-DOES-NOT-EXIST")
    V, M = AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, AttachmentPurpose.MODEL_DOCUMENT_FILE
    cases = [
        ("purpose/source mismatch", dict(purpose=V, source_type="MODEL_DOCUMENT", source_id=doc.model_document_id),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        ("forged reverse mismatch", dict(purpose=M, source_type="VEHICLE_CERTIFICATE", source_id=cert.certificate_id),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        ("photo source type", dict(purpose=V, source_type="INSPECTION_VEHICLE", source_id="VEH-1046"),
         (422, "ATTACHMENT_SOURCE_NOT_ALLOWED_FOR_PURPOSE")),
        ("vehicle id in place of a certificate id", dict(source_id="VEH-1046"), (404, "VEHICLE_CERTIFICATE_NOT_FOUND")),
        ("model id in place of a model_document id", dict(purpose=M, source_type="MODEL_DOCUMENT",
                                                           source_id="MODEL-0001"), (404, "MODEL_DOCUMENT_NOT_FOUND")),
        ("certificate id under the model-document purpose", dict(purpose=M, source_type="MODEL_DOCUMENT",
                                                                  source_id=cert.certificate_id),
         (404, "MODEL_DOCUMENT_NOT_FOUND")),
        ("guessed certificate", dict(source_id="CERT-9999"), (404, "VEHICLE_CERTIFICATE_NOT_FOUND")),
        ("missing vehicle parent", dict(source_id=orphan_cert.certificate_id),
         (403, "ATTACHMENT_SOURCE_RELATIONSHIP_INVALID")),
        ("missing model parent", dict(purpose=M, source_type="MODEL_DOCUMENT", source_id=orphan_doc.model_document_id),
         (403, "ATTACHMENT_SOURCE_RELATIONSHIP_INVALID")),
        ("no source", dict(source_type=None, source_id=None), (403, "ATTACHMENT_SOURCE_REQUIRED")),
        ("half source", dict(source_id=None), (422, "VALIDATION_ERROR")),
        ("legacy raw storage_ref as id", dict(source_id="local://legacy/cert.pdf"), (404, "VEHICLE_CERTIFICATE_NOT_FOUND")),
        ("arbitrary URL as id", dict(source_id="https://example.invalid/cert.pdf"),
         (404, "VEHICLE_CERTIFICATE_NOT_FOUND")),
        ("MIME mismatch", dict(source_id=cert.certificate_id, content_type="image/png"),
         (422, "ATTACHMENT_TYPE_NOT_ALLOWED")),
        ("fake signature", dict(source_id=cert.certificate_id, data=b"MZ" + PDF), (422, "ATTACHMENT_CONTENT_MISMATCH")),
        ("PNG renamed .pdf", dict(source_id=cert.certificate_id, data=PNG, filename="x.pdf"),
         (422, "ATTACHMENT_CONTENT_MISMATCH")),
        ("empty", dict(source_id=cert.certificate_id, data=b""), (422, "VALIDATION_ERROR")),
        ("oversize", dict(source_id=cert.certificate_id, data=PDF + b"0" * 64), (422, "ATTACHMENT_TOO_LARGE")),
    ]
    for label, kwargs, expected in cases:
        settings_update = {"attachment_max_size_bytes": len(PDF) + 10} if label == "oversize" else {}
        with pytest.raises(ApiError) as refused:
            await _gate_upload(repo, storage, _manager(), **kwargs, **settings_update)
        assert (refused.value.status_code, refused.value.code) == expected, label
    assert _files(temp_upload_dir) == []
    for source_type, source_id in (("VEHICLE_CERTIFICATE", cert.certificate_id),
                                   ("MODEL_DOCUMENT", doc.model_document_id)):
        assert await repo.list_attachments_for_source(source_type, source_id) == []


async def test_a_gate_upload_survives_renewal_without_being_inherited(storage) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    stored = await _gate_upload(repo, storage, _manager(), source_id=cert.certificate_id)
    renewed = await _http("POST", f"{API}/certificates/{cert.certificate_id}/renew", repo, storage,
                          json={"expiry_date": "2100-01-01"})
    assert renewed.status_code == 200, renewed.text
    successor_id = renewed.json()["certificate_id"]
    assert successor_id != cert.certificate_id
    assert await repo.list_attachments_for_source("VEHICLE_CERTIFICATE", successor_id) == []
    file = await _http("GET", f"{API}/attachments/{stored.attachment_id}/file", repo, storage, role="TECHNICIAN")
    assert file.status_code == 200 and file.content == PDF  # the old file stays readable (can_view)


async def _am_http(method, path, store, storage, user, *, context_override=None, role="ADMIN", **kwargs):
    from app.dependencies import get_current_context, get_repository, get_storage_provider, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: store
    app.dependency_overrides[get_storage_provider] = lambda: storage
    if context_override is not None:
        app.dependency_overrides[get_current_context] = lambda: context_override
    headers = {"X-Dev-Role": role, "X-Dev-User-Id": user, "X-Request-Id": str(uuid.uuid4())}
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, **kwargs)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _am_env(monkeypatch) -> None:
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


class SpyAmRepo(MockRepository):
    """The Access Management seed, counting every document-record read."""

    def __init__(self) -> None:
        super().__init__(access_management_seed=True)
        self.document_reads: list[str] = []

    async def get_vehicle_certificate(self, certificate_id):
        self.document_reads.append(certificate_id)
        return await super().get_vehicle_certificate(certificate_id)

    async def get_model_document(self, model_document_id):
        self.document_reads.append(model_document_id)
        return await super().get_model_document(model_document_id)


def _pdf_upload(purpose: str, source_type: str, source_id: str, data: bytes = PDF) -> dict:
    return {"data": {"purpose": purpose, "source_type": source_type, "source_id": source_id},
            "files": {"file": ("synthetic.pdf", data, "application/pdf")}}


async def _am_world(monkeypatch):
    from tests.test_access_management import CLERK, DRV1, MGR, OPM, P, caps, delegate, employee, grant, revision

    _am_env(monkeypatch)
    store = SpyAmRepo()
    cert = await _certificate(store)
    doc = await _model_document(store)
    targets = (("VEHICLE_CERTIFICATE_DOCUMENT", "VEHICLE_CERTIFICATE", cert.certificate_id),
               ("MODEL_DOCUMENT_FILE", "MODEL_DOCUMENT", doc.model_document_id))
    return store, cert, doc, targets, dict(CLERK=CLERK, DRV1=DRV1, MGR=MGR, OPM=OPM, P=P, caps=caps,
                                             delegate=delegate, employee=employee, grant=grant, revision=revision)


async def test_am_real_grant_upload_list_download_then_revoke(monkeypatch, storage, temp_upload_dir) -> None:
    """Mandatory test 1 + 2: the root holder grants the exact capability through the
    audited API to one verified, active, account-linked synthetic TEST employee; /me
    reads it back; that employee uploads real multipart to the existing route for a
    certificate AND a model document, lists and downloads the exact bytes. A revoke
    through the same API removes the upload on the very next request."""
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    clerk, mgr = w["CLERK"], w["MGR"]
    granted = await w["grant"](store, mgr, w["employee"](clerk), {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})
    assert granted.status_code == 200, granted.text
    assert {CAN_VIEW, CAN_MANAGE_TEST_DOCUMENT_FILE} <= set(await w["caps"](store, clerk))
    grant_events = [e for e in await store.read_access_events()
                    if e["capability"] == CAN_MANAGE_TEST_DOCUMENT_FILE and e["kind"] == "GRANT"]
    assert [(e["personnel_id"], e["actor_personnel_id"]) for e in grant_events] == [(w["P"][clerk], w["P"][mgr])]

    uploaded = {}
    for purpose, source_type, source_id in targets:
        data = PDF + source_id.encode()
        response = await _am_http("POST", f"{API}/attachments", store, storage, clerk, role="TECHNICIAN",
                                  **_pdf_upload(purpose, source_type, source_id, data))
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["purpose"], body["source_type"], body["source_id"], body["uploaded_by"]) == (
            purpose, source_type, source_id, clerk)
        listed = await _am_http("GET", f"{API}/attachments/by-source/{source_type}/{source_id}", store, storage, clerk,
                                role="TECHNICIAN")
        assert [a["attachment_id"] for a in listed.json()] == [body["attachment_id"]]
        file = await _am_http("GET", body["url"], store, storage, clerk, role="TECHNICIAN")
        assert file.status_code == 200 and file.content == data
        uploaded[source_id] = body["url"]
    assert len(_files(temp_upload_dir)) == 2

    revoked = await w["grant"](store, mgr, w["employee"](clerk), {CAN_MANAGE_TEST_DOCUMENT_FILE: False})
    assert revoked.status_code == 200, revoked.text
    assert CAN_MANAGE_TEST_DOCUMENT_FILE not in await w["caps"](store, clerk)
    reads_before = list(store.document_reads)
    for purpose, source_type, source_id in targets:
        refused = await _am_http("POST", f"{API}/attachments", store, storage, clerk, role="TECHNICIAN",
                                 **_pdf_upload(purpose, source_type, source_id))
        assert _code(refused) == (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")
    assert store.document_reads == reads_before and len(_files(temp_upload_dir)) == 2
    for url in uploaded.values():  # the files already stored stay readable with can_view
        assert (await _am_http("GET", url, store, storage, clerk, role="TECHNICIAN")).status_code == 200


async def test_am_real_ungranted_actors_fail_before_any_record_or_storage_read(
        monkeypatch, storage, temp_upload_dir) -> None:
    """Another TEST employee (can_view only), the root holder without an individual
    grant, the ADMIN dev role (unlinked dev user, or a forged ADMIN header on a real
    employee) and an unknown account: all refused before any document-record read or
    storage access."""
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    drv1, mgr = w["DRV1"], w["MGR"]
    assert (await w["grant"](store, mgr, w["employee"](drv1), {CAN_VIEW: True})).status_code == 200
    assert (await w["grant"](store, mgr, w["employee"](mgr), {CAN_VIEW: True})).status_code == 200
    actors = ((drv1, "TECHNICIAN", "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED"),
              (drv1, "ADMIN", "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED"),  # forged dev header grants nothing
              (mgr, "ADMIN", "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED"),  # root position != the grant
              ("dev-user", "ADMIN", "ACCESS_ACTOR_NOT_VERIFIED"),  # unlinked development login
              ("USR-UNKNOWN-R7", "MAINTENANCE", "ACCESS_ACTOR_NOT_VERIFIED"))
    for user, role, expected in actors:
        for purpose, source_type, source_id in targets:
            refused = await _am_http("POST", f"{API}/attachments", store, storage, user, role=role,
                                     **_pdf_upload(purpose, source_type, source_id))
            assert _code(refused) == (403, expected), (user, role)
    assert store.document_reads == [] and storage.reads == [] and _files(temp_upload_dir) == []


async def test_am_real_root_may_self_grant_and_revoke_through_the_audited_api(
        monkeypatch, storage, temp_upload_dir) -> None:
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    mgr = w["MGR"]
    assert CAN_MANAGE_TEST_DOCUMENT_FILE not in await w["caps"](store, mgr)  # never automatic
    assert (await w["grant"](store, mgr, w["employee"](mgr),
                             {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})).status_code == 200
    purpose, source_type, source_id = targets[0]
    ok = await _am_http("POST", f"{API}/attachments", store, storage, mgr, role="TECHNICIAN",
                        **_pdf_upload(purpose, source_type, source_id))
    assert ok.status_code == 200, ok.text
    assert (await w["grant"](store, mgr, w["employee"](mgr), {CAN_MANAGE_TEST_DOCUMENT_FILE: False})).status_code == 200
    refused = await _am_http("POST", f"{API}/attachments", store, storage, mgr, role="TECHNICIAN",
                             **_pdf_upload(purpose, source_type, source_id))
    assert _code(refused) == (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")
    audit = [(e["kind"], e["personnel_id"], e["actor_personnel_id"]) for e in await store.read_access_events()
             if e["capability"] == CAN_MANAGE_TEST_DOCUMENT_FILE]
    assert audit == [("GRANT", w["P"][mgr], w["P"][mgr]), ("REVOKE", w["P"][mgr], w["P"][mgr])]
    assert len(_files(temp_upload_dir)) == 1


async def test_am_real_the_grant_is_root_only_and_never_delegable(monkeypatch, storage) -> None:
    """Mandatory test 3: a delegate cannot grant or delegate it; delegating it is refused;
    an unknown capability is 422; refusals leave existing grants intact; category I."""
    from tests.test_access_management import MNT, code

    store, cert, doc, targets, w = await _am_world(monkeypatch)
    mgr, opm, clerk = w["MGR"], w["OPM"], w["CLERK"]
    assert (await w["grant"](store, mgr, w["employee"](clerk), {CAN_VIEW: True})).status_code == 200
    assert (await w["delegate"](store, mgr, opm, MNT, [CAN_VIEW])).status_code == 200
    events_before = await store.read_access_events()

    by_delegate = await w["grant"](store, opm, w["employee"](clerk), {CAN_MANAGE_TEST_DOCUMENT_FILE: True})
    assert code(by_delegate)[0] == 403
    refused_delegation = await w["delegate"](store, mgr, opm, MNT, [CAN_VIEW, CAN_MANAGE_TEST_DOCUMENT_FILE])
    assert code(refused_delegation) == (422, "ACCESS_CAPABILITY_NOT_DELEGABLE")
    unknown = await w["grant"](store, mgr, w["employee"](clerk), {"can_manage_any_document_file": True})
    assert code(unknown) == (422, "ACCESS_CAPABILITY_NOT_GRANTABLE")
    assert await store.read_access_events() == events_before  # nothing written by any refusal
    assert CAN_VIEW in await w["caps"](store, clerk)  # the existing grant is intact
    assert CAN_MANAGE_TEST_DOCUMENT_FILE not in await w["caps"](store, clerk)

    from tests.test_access_management import http as am_http

    catalog = (await am_http("GET", f"{API}/access/catalog", store, mgr, request_id=None)).json()
    (category,) = [c["code"] for c in catalog["categories"]
                   if any(e["code"] == CAN_MANAGE_TEST_DOCUMENT_FILE and e["sensitive"] for e in c["capabilities"])]
    assert category == "I"
    assert "เฉพาะ TEST" in catalog["sensitive_note_th"]


async def test_am_real_granted_actor_still_cannot_use_the_d6_document_writes(monkeypatch, storage) -> None:
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    clerk, mgr = w["CLERK"], w["MGR"]
    assert (await w["grant"](store, mgr, w["employee"](clerk),
                             {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})).status_code == 200
    for user in (clerk, w["DRV1"]):  # granted and ungranted
        for method, path in (("POST", f"{API}/vehicles/VEH-1046/certificates"),
                             ("POST", f"{API}/certificates/{cert.certificate_id}/renew"),
                             ("POST", f"{API}/models/MODEL-0001/documents"),
                             ("POST", f"{API}/model-documents/{doc.model_document_id}/revise")):
            response = await _am_http(method, path, store, storage, user, role="TECHNICIAN", json={})
            # A PDF-file grant never implies the separate document-master grant (policy R1 §3).
            assert _code(response) == (403, "DOCUMENT_MASTER_NOT_AUTHORIZED"), (user, path)


async def test_am_http_route_with_a_simulated_manager_context(monkeypatch, storage, temp_upload_dir) -> None:
    """Gate ordering through the real route with the route context replaced by a
    SIMULATED grant holder (the real-grant proof is `test_am_real_*` above)."""
    _am_env(monkeypatch)
    store = MockRepository(access_management_seed=True)
    cert = await _certificate(store)
    doc = await _model_document(store)
    manager = _manager()
    for purpose, source_type, source_id in (("VEHICLE_CERTIFICATE_DOCUMENT", "VEHICLE_CERTIFICATE",
                                             cert.certificate_id),
                                            ("MODEL_DOCUMENT_FILE", "MODEL_DOCUMENT", doc.model_document_id)):
        viewer_only = await _am_http("POST", f"{API}/attachments", store, storage, MGR_USER,
                                     context_override=_manager({CAN_VIEW}),
                                     data={"purpose": purpose, "source_type": source_type, "source_id": source_id},
                                     files={"file": ("a.pdf", PDF, "application/pdf")})
        assert _code(viewer_only) == (403, "DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED")
        uploaded = await _am_http("POST", f"{API}/attachments", store, storage, MGR_USER, context_override=manager,
                                  data={"purpose": purpose, "source_type": source_type, "source_id": source_id},
                                  files={"file": ("a.pdf", PDF, "application/pdf")})
        assert uploaded.status_code == 200, uploaded.text
        body = uploaded.json()
        assert (body["source_type"], body["source_id"], body["purpose"]) == (source_type, source_id, purpose)
        assert body["url"] == f"/api/v1/attachments/{body['attachment_id']}/file"
        listed = await _am_http("GET", f"{API}/attachments/by-source/{source_type}/{source_id}", store, storage,
                                MGR_USER, context_override=manager)
        assert [a["attachment_id"] for a in listed.json()] == [body["attachment_id"]]
        file = await _am_http("GET", body["url"], store, storage, MGR_USER, context_override=manager)
        assert file.status_code == 200 and file.content == PDF
        assert file.headers["content-type"] == "application/pdf"
    for method, path in (("POST", f"{API}/vehicles/VEH-1046/certificates"),
                         ("POST", f"{API}/certificates/{cert.certificate_id}/renew"),
                         ("POST", f"{API}/models/MODEL-0001/documents"),
                         ("POST", f"{API}/model-documents/{doc.model_document_id}/revise")):
        response = await _am_http(method, path, store, storage, MGR_USER, context_override=manager, json={})
        # The gate resolves the actor through Access Management itself, so a replaced route
        # context (a simulation) cannot bypass it: still refused without the real grant.
        assert _code(response) == (403, "DOCUMENT_MASTER_NOT_AUTHORIZED"), path


# ---------------------------------------------------------------------------
# R7 Whole-Phase (Owner gate 2026-11-17): TEST-only document master writes (policy R1
# P-1) and TEST parent scope for PDFs (P-4b), with REAL audited grants (no simulation).
# TEST parents: VEH-1048 / MODEL-0003 (server reference); REAL: VEH-1046 / MODEL-0001.
# ---------------------------------------------------------------------------

from app.domain.authz import CAN_MANAGE_TEST_DOCUMENT_MASTER  # noqa: E402

_CERT_BODY = {"certificate_type_code": "R7-MASTER", "certificate_type_name_th": "ทดสอบ R7"}


async def _real_parents(store):
    real_cert = await _certificate(store, vehicle_id="VEH-1046", code="R7-REAL")
    real_doc = await _model_document(store, model_id="MODEL-0001")
    return real_cert, real_doc


def _master_routes(cert, doc, *, vehicle="VEH-1048", model="MODEL-0003"):
    return (("POST", f"{API}/vehicles/{vehicle}/certificates", _CERT_BODY),
            ("POST", f"{API}/certificates/{cert.certificate_id}/renew", {"expiry_date": "2100-01-01"}),
            ("POST", f"{API}/models/{model}/documents", {"document_type": "LOAD_CHART", "version": f"R7-{uuid.uuid4()}"}),
            ("POST", f"{API}/model-documents/{doc.model_document_id}/revise",
             {"version": f"R7-{uuid.uuid4()}", "effective_from": "2026-06-01"}))


async def _counts(store, cert, doc):
    return (len(await store.list_vehicle_certificates_for_vehicle("VEH-1048")),
            len(await store.list_vehicle_certificates_for_vehicle("VEH-1046")),
            len(await store.list_model_documents_for_model("MODEL-0003")),
            len(await store.list_model_documents_for_model("MODEL-0001")))


async def test_am_master_real_grant_creates_renews_revises_then_revoke_refuses(monkeypatch, storage) -> None:
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    clerk, mgr = w["CLERK"], w["MGR"]
    granted = await w["grant"](store, mgr, w["employee"](clerk), {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_MASTER: True})
    assert granted.status_code == 200, granted.text
    assert CAN_MANAGE_TEST_DOCUMENT_MASTER in await w["caps"](store, clerk)
    assert CAN_MANAGE_TEST_DOCUMENT_MASTER not in await w["caps"](store, mgr)  # never automatic
    for method, path, body in _master_routes(cert, doc):
        response = await _am_http(method, path, store, storage, clerk, role="TECHNICIAN", json=body)
        assert response.status_code == 200, (path, response.text)
    renewed_old = await store.get_vehicle_certificate(cert.certificate_id)
    assert renewed_old.certificate_status == CertificateStatus.REPLACED
    revoked = await w["grant"](store, mgr, w["employee"](clerk), {CAN_MANAGE_TEST_DOCUMENT_MASTER: False})
    assert revoked.status_code == 200
    before = await _counts(store, cert, doc)
    again = await _am_http("POST", f"{API}/vehicles/VEH-1048/certificates", store, storage, clerk, role="TECHNICIAN",
                           json={**_CERT_BODY, "certificate_type_code": "R7-AFTER-REVOKE"})
    assert _code(again) == (403, "DOCUMENT_MASTER_NOT_AUTHORIZED")
    assert await _counts(store, cert, doc) == before


async def test_am_master_gate_denies_in_order_before_any_write_on_every_route(monkeypatch, storage) -> None:
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    clerk, mgr, drv1 = w["CLERK"], w["MGR"], w["DRV1"]
    real_cert, real_doc = await _real_parents(store)
    assert (await w["grant"](store, mgr, w["employee"](drv1), {CAN_VIEW: True})).status_code == 200
    assert (await w["grant"](store, mgr, w["employee"](clerk),
                             {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_MASTER: True})).status_code == 200
    before = await _counts(store, cert, doc)
    for (method, path, body), (_, real_path, real_body) in zip(_master_routes(cert, doc),
                                                                _master_routes(real_cert, real_doc, vehicle="VEH-1046",
                                                                               model="MODEL-0001")):
        # 1. AM write policy: an unresolved / unlinked account (the dev ADMIN role grants nothing).
        unknown = await _am_http(method, path, store, storage, "USR-UNKNOWN-R7", role="ADMIN", json=body)
        assert _code(unknown) == (403, "ACCESS_ACTOR_NOT_VERIFIED"), path
        # 2d. verified employee without the grant (can_view only); malformed body still 403, not 422.
        for payload in (body, {"expiry_date": "not-a-date", "version": 12345, "certificate_type_code": None}):
            refused = await _am_http(method, path, store, storage, drv1, role="ADMIN", json=payload)
            assert _code(refused) == (403, "DOCUMENT_MASTER_NOT_AUTHORIZED"), path
        # 2e. granted, but the parent is REAL-scoped.
        real = await _am_http(method, real_path, store, storage, clerk, role="TECHNICIAN", json=real_body)
        assert _code(real) == (403, "DOCUMENT_PARENT_SCOPE_UNPROVEN"), real_path
    assert await _counts(store, cert, doc) == before  # nothing written by any refusal


async def test_am_master_and_pdf_refuse_unproven_or_unused_model_ancestry(monkeypatch, storage, temp_upload_dir) -> None:
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    clerk, mgr = w["CLERK"], w["MGR"]
    assert (await w["grant"](store, mgr, w["employee"](clerk), {
        CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_MASTER: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})).status_code == 200
    # A vehicle record that uses MODEL-0003 but is NOT in the scope reference (unknown ancestry).
    template = store._vehicles["VEH-1048"] if isinstance(store._vehicles, dict) else store._vehicles[0]
    stray = template.model_copy(update={"vehicle_id": "VEH-R7-STRAY", "model_id": "MODEL-0003"})
    if isinstance(store._vehicles, dict):
        store._vehicles["VEH-R7-STRAY"] = stray
    else:
        store._vehicles.append(stray)
    create = await _am_http("POST", f"{API}/models/MODEL-0003/documents", store, storage, clerk, role="TECHNICIAN",
                            json={"document_type": "LOAD_CHART", "version": "R7-STRAY"})
    assert _code(create) == (403, "DOCUMENT_PARENT_SCOPE_UNPROVEN")
    assert create.json()["error"]["details"]["reason"] == "MODEL_NOT_TEST_EXCLUSIVE"
    upload = await _am_http("POST", f"{API}/attachments", store, storage, clerk, role="TECHNICIAN",
                            **_pdf_upload("MODEL_DOCUMENT_FILE", "MODEL_DOCUMENT", doc.model_document_id))
    assert _code(upload) == (403, "DOCUMENT_PARENT_SCOPE_UNPROVEN")
    assert _files(temp_upload_dir) == []


async def test_am_pdf_with_a_real_grant_is_refused_on_real_parents_before_storage(monkeypatch, storage,
                                                                                   temp_upload_dir) -> None:
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    clerk, mgr = w["CLERK"], w["MGR"]
    real_cert, real_doc = await _real_parents(store)
    assert (await w["grant"](store, mgr, w["employee"](clerk),
                             {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})).status_code == 200
    for purpose, source_type, source_id in (("VEHICLE_CERTIFICATE_DOCUMENT", "VEHICLE_CERTIFICATE",
                                             real_cert.certificate_id),
                                            ("MODEL_DOCUMENT_FILE", "MODEL_DOCUMENT", real_doc.model_document_id)):
        refused = await _am_http("POST", f"{API}/attachments", store, storage, clerk, role="TECHNICIAN",
                                 **_pdf_upload(purpose, source_type, source_id))
        assert _code(refused) == (403, "DOCUMENT_PARENT_SCOPE_UNPROVEN"), source_id
        assert await store.list_attachments_for_source(source_type, source_id) == []
    assert _files(temp_upload_dir) == [] and storage.reads == []
    for purpose, source_type, source_id in targets:  # the TEST parents still work
        ok = await _am_http("POST", f"{API}/attachments", store, storage, clerk, role="TECHNICIAN",
                            **_pdf_upload(purpose, source_type, source_id))
        assert ok.status_code == 200, ok.text


async def test_am_master_gate_refuses_non_test_context_and_non_mock_repository(monkeypatch, storage) -> None:
    from app.config import DataRepositoryMode as Mode, Settings, get_settings as real_settings
    from app.dependencies import get_repository, get_settings_dependency, get_storage_provider, reset_dependency_cache
    from app.main import create_app

    store, cert, doc, targets, w = await _am_world(monkeypatch)
    assert (await w["grant"](store, w["MGR"], w["employee"](w["CLERK"]),
                             {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_MASTER: True})).status_code == 200

    async def call(settings_override=None, real_context=False):
        if real_context:
            monkeypatch.setattr(Settings, "registry_context_effective", property(lambda self: "REAL"))
        real_settings.cache_clear()
        reset_dependency_cache()
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: store
        app.dependency_overrides[get_storage_provider] = lambda: storage
        if settings_override is not None:
            app.dependency_overrides[get_settings_dependency] = lambda: settings_override
        headers = {"X-Dev-Role": "TECHNICIAN", "X-Dev-User-Id": w["CLERK"], "X-Request-Id": str(uuid.uuid4())}
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.post(f"{API}/vehicles/VEH-1048/certificates", headers=headers, json=_CERT_BODY)

    from app.config import RegistryDataContext

    # AM cannot be configured with a non-Mock repository (settings validator); these overrides
    # only prove the defence in depth. Without the TEST batch the AM write policy refuses first;
    # with it, the gate's own repository check answers 501. Neither writes anything.
    bare_sheets = real_settings().model_copy(update={"data_repository": Mode.GOOGLE_SHEETS})
    assert _code(await call(settings_override=bare_sheets)) == (403, "ACCESS_ACTOR_NOT_VERIFIED")
    sheets = real_settings().model_copy(update={"data_repository": Mode.GOOGLE_SHEETS,
                                                "registry_data_context": RegistryDataContext.TEST,
                                                "registry_test_batch_id": "MOCK-7O2B-SYNTHETIC"})
    assert _code(await call(settings_override=sheets)) == (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")
    # A REAL server context: the seeded TEST employees no longer resolve, so the AM write policy
    # refuses at step 1 (the gate's own TEST-context check is defence in depth behind it).
    assert _code(await call(real_context=True)) == (403, "ACCESS_ACTOR_NOT_VERIFIED")
    assert await store.list_vehicle_certificates_for_vehicle("VEH-1048") == [cert]


async def test_an_invalid_storage_ref_is_an_honest_500_without_a_path(storage) -> None:
    repo = MockRepository()
    cert = await _certificate(repo)
    row = await repo.create_attachment(purpose=AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT,
                                       storage_ref="../../outside.pdf", filename="x.pdf",
                                       content_type="application/pdf", size_bytes=1, uploaded_by="USR-TEST-R7",
                                       source_type="VEHICLE_CERTIFICATE", source_id=cert.certificate_id)
    file = await _http("GET", f"{API}/attachments/{row.attachment_id}/file", repo, storage, raise_app_exceptions=False)
    assert _code(file) == (500, "ATTACHMENT_STORAGE_REF_INVALID")
    assert "outside.pdf" not in file.text


async def test_am_real_grant_content_mismatch_is_refused_before_storage(monkeypatch, storage, temp_upload_dir) -> None:
    """U-18 with a REAL audited grant (not a simulated context): wrong MIME, PNG bytes as a
    PDF, a fake signature, an empty file and an oversize file are refused with nothing stored."""
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    assert (await w["grant"](store, w["MGR"], w["employee"](w["CLERK"]),
                             {CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})).status_code == 200
    monkeypatch.setenv("ATTACHMENT_MAX_SIZE_BYTES", str(len(PDF) + 10))
    cases = ((("p.pdf", PDF, "image/png"), "ATTACHMENT_TYPE_NOT_ALLOWED"),
             (("p.pdf", PNG, "application/pdf"), "ATTACHMENT_CONTENT_MISMATCH"),
             (("p.pdf", b"MZ" + PDF, "application/pdf"), "ATTACHMENT_CONTENT_MISMATCH"),
             (("p.pdf", b"", "application/pdf"), "VALIDATION_ERROR"),
             (("p.pdf", PDF + b"0" * 64, "application/pdf"), "ATTACHMENT_TOO_LARGE"))
    for file, expected in cases:
        response = await _am_http("POST", f"{API}/attachments", store, storage, w["CLERK"], role="TECHNICIAN",
                                  data={"purpose": "VEHICLE_CERTIFICATE_DOCUMENT", "source_type": "VEHICLE_CERTIFICATE",
                                        "source_id": cert.certificate_id}, files={"file": file})
        assert _code(response) == (422, expected), (file[2], expected, response.text)
    assert _files(temp_upload_dir) == []
    assert await store.list_attachments_for_source("VEHICLE_CERTIFICATE", cert.certificate_id) == []


async def test_am_reads_without_can_view_are_refused_and_dev_auth_off_refuses_all_four_master_writes(
        monkeypatch, storage) -> None:
    """U-02: an AM employee without can_view reads nothing (real and guessed ids alike).
    U-04: with dev auth OFF there is no trusted actor — every master write (create, renew,
    create, revise) is refused and nothing is written."""
    store, cert, doc, targets, w = await _am_world(monkeypatch)
    for path in (f"{API}/vehicles/VEH-1048/certificates", f"{API}/certificates/{cert.certificate_id}",
                 f"{API}/certificates/CERT-GUESSED", f"{API}/models/MODEL-0003/documents",
                 f"{API}/model-documents/{doc.model_document_id}", f"{API}/drivers", f"{API}/drivers/DRV-0001",
                 f"{API}/vehicles/VEH-1048/part-lifetime"):
        refused = await _am_http("GET", path, store, storage, w["DRV1"], role="ADMIN")
        assert refused.status_code == 403, path
        assert cert.certificate_id not in refused.text or "GUESSED" in path
    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "false")
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    legacy = MockRepository()
    lcert = await _certificate(legacy)
    ldoc = await _model_document(legacy)
    before = (len(await legacy.list_vehicle_certificates_for_vehicle("VEH-1048")),
              len(await legacy.list_model_documents_for_model("MODEL-0003")))
    for method, path, body in _master_routes(lcert, ldoc):
        response = await _http(method, path, legacy, storage, raise_app_exceptions=False, json=body)
        assert _code(response) == (403, "ACCESS_ACTOR_NOT_VERIFIED"), path
    assert (len(await legacy.list_vehicle_certificates_for_vehicle("VEH-1048")),
            len(await legacy.list_model_documents_for_model("MODEL-0003"))) == before


async def test_am_a_master_granted_employee_still_gets_403_on_every_other_unresolved_d6_write(
        monkeypatch, storage) -> None:
    """U-13: the document-master grant opens exactly the four document routes and nothing else."""
    from app.dependencies import AM_UNRESOLVED_WRITE_ROUTES
    from tests.test_access_management_security import _concrete

    store, cert, doc, targets, w = await _am_world(monkeypatch)
    assert (await w["grant"](store, w["MGR"], w["employee"](w["CLERK"]), {
        CAN_VIEW: True, CAN_MANAGE_TEST_DOCUMENT_MASTER: True, CAN_MANAGE_TEST_DOCUMENT_FILE: True})).status_code == 200
    for method, path in sorted(AM_UNRESOLVED_WRITE_ROUTES):
        response = await _am_http(method, _concrete(path), store, storage, w["CLERK"], role="TECHNICIAN", json={})
        assert _code(response) == (403, "ACCESS_CAPABILITY_MAPPING_UNRESOLVED"), (method, path)
