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


async def _certificate(repo: MockRepository, vehicle_id: str = "VEH-1046", storage_ref: str | None = None,
                       status: CertificateStatus | None = CertificateStatus.ACTIVE, code: str = "R7-INSURANCE"):
    return await repo.create_vehicle_certificate(
        vehicle_id=vehicle_id, certificate_type_code=code, certificate_type_name_th="ประกันภัย (TEST)",
        document_no="000123", issue_date=date(2026, 1, 1), expiry_date=date(2099, 1, 1), alert_lead_days=30,
        certificate_status=status, storage_ref=storage_ref, note_th=None, created_by_user_id="USR-TEST-R7",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


async def _model_document(repo: MockRepository, model_id: str = "MODEL-0001", storage_ref: str | None = None):
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
    assert _code(file) == (500, "INTERNAL_ERROR")


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
        assert _code(response) == (403, "ACCESS_CAPABILITY_MAPPING_UNRESOLVED"), path

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
    assert _code(upload) == (403, "DOCUMENT_FILE_UPLOAD_POLICY_UNRESOLVED")  # even the root holder
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
