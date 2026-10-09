"""Phase 7 Batch 7O2b — registration writes over HTTP with the MOCK repository
(contract Final Rev2 §3, §4.3-§4.7, §8.1; Outcome Classification Addendum A.1,
A.4, B-OC-01..04; independent-review clarifications C1-C8).

Acceptance rows: W-01..W-08, W-14, W-15 (server side), B-OC-01..B-OC-04,
the C1-C8 clarifications, and the client/server allowlist cross-check.
Fake-transport (Google Sheets) rows W-09, W-10, W-12 and mock/fake parity are
in test_registration_write_sheets_batch7o2b.py. Failures are injected through
`MockRepository.registry_write_faults` and method overrides on one instance.
Synthetic data only (the mock seed's registry fixtures).
"""
from __future__ import annotations

import ast
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.registration import registration_history_revision, validate_registration_rows
from app.domain.registration_write_service import MOCK_TEST_BATCH_ID, RegistrationWriteService
from app.domain.registry_outcomes import (
    NEVER_ALLOWLISTED_CODES,
    SPECIAL_OUTCOMES,
    ZERO_WRITE_ALLOWLIST,
)
from app.domain.request_replay import request_fingerprint
from app.errors import ApiError
from app.repositories.base import (
    RegistrationMasterRead,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
)
from app.repositories.mock import MockRepository
from tests.test_registry_read_api_batch7o2a import SpyRepository

API = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
ROLES_WITHOUT = ("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER")
_AUTO = object()


def _rid() -> str:
    return str(uuid.uuid4())


async def _http(
    method: str,
    path: str,
    *,
    repo=None,
    json_body=_AUTO,
    content: bytes | None = None,
    request_id=_AUTO,
    role: str | None = "ADMIN",
    settings: Settings | None = None,
    no_auth: bool = False,
    monkeypatch=None,
):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    if no_auth:
        monkeypatch.setenv("DEV_AUTH_MODE", "false")
    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    headers: dict[str, str] = {}
    if role is not None:
        headers["X-Dev-Role"] = role
    if request_id is _AUTO:
        request_id = _rid()
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    kwargs: dict = {"headers": headers}
    if content is not None:
        kwargs["content"] = content
        headers["Content-Type"] = "application/json"
    elif json_body is not _AUTO:
        kwargs["json"] = json_body
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.request(method, path, **kwargs)
            response.sent_request_id = request_id  # type: ignore[attr-defined]
            return response
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _patch_path(vid: str = "VEH-1046") -> str:
    return f"{API}/vehicles/{vid}/registration"


def _recon_path(vid: str = "VEH-1046") -> str:
    return f"{API}/vehicles/{vid}/registration-history/reconciliations"


def _body(no, pv, exp_no, exp_pv) -> dict:
    return {
        "registration_no": no,
        "registration_province_code": pv,
        "expected_registration_no": exp_no,
        "expected_registration_province_code": exp_pv,
    }


def _set_master(repo: MockRepository, vid: str, no: str, pv: str) -> None:
    repo._vehicle_registry.setdefault(vid, {}).update(registration_no=no, registration_province_code=pv)


def _rows(repo: MockRepository, vid: str) -> list[dict[str, str]]:
    return [r for r in repo._registration_history if r["vehicle_id"] == vid]


def _revision(repo: MockRepository, vid: str) -> str:
    return registration_history_revision(_rows(repo, vid))


def _recon_body(repo: MockRepository, vid: str, mode: str, exp_no, exp_pv, **extra) -> dict:
    body = {
        "mode": mode,
        "expected_registration_no": exp_no,
        "expected_registration_province_code": exp_pv,
        "expected_history_revision": _revision(repo, vid),
        "reason_th": "ปรับข้อมูลให้ตรงกัน (ทดสอบ)",
    }
    body.update(extra)
    return body


def _mismatch_repo() -> MockRepository:
    """VEH-1046: history says 0012/TH-21; the master was hand-edited to 0099/TH-20."""
    repo = MockRepository()
    _set_master(repo, "VEH-1046", "0099", "TH-20")
    return repo


def _err(response) -> dict:
    return response.json()["error"]


async def _history(repo, vid: str = "VEH-1046") -> dict:
    response = await _http("GET", f"{API}/vehicles/{vid}/registration-history", repo=repo, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


def _master(repo: MockRepository, vid: str) -> tuple[str, str]:
    cells = repo._vehicle_registry[vid]
    return cells["registration_no"], cells["registration_province_code"]


def _sheets_settings(context: str | None, batch: str = "") -> Settings:
    values: dict = {
        "data_repository": DataRepositoryMode.GOOGLE_SHEETS,
        "google_sheet_id": "fake",
        "google_application_credentials": "fake.json",
        "registry_test_batch_id": batch,
    }
    if context is not None:
        values["registry_data_context"] = context
    return Settings(**values)


# ---------------------------------------------------------------------------
# Permissions (§3.1) — W-01
# ---------------------------------------------------------------------------


def test_capability_and_dev_role_mapping() -> None:
    from app.domain.authz import ALL_CAPABILITIES, CAN_EDIT_VEHICLE_REGISTRATION, ROLE_CAPABILITIES

    assert CAN_EDIT_VEHICLE_REGISTRATION == "can_edit_vehicle_registration"
    assert CAN_EDIT_VEHICLE_REGISTRATION in ALL_CAPABILITIES
    assert ROLE_CAPABILITIES["ADMIN"] == ALL_CAPABILITIES
    # 7O2c completes the R1 mapping with the two branch capabilities (see
    # test_branch_write_batch7o2c.py); the registration capability is unchanged.
    assert ROLE_CAPABILITIES["MAINTENANCE_MANAGER"] == frozenset(
        {"can_view", CAN_EDIT_VEHICLE_REGISTRATION, "can_transfer_vehicle_branch", "can_correct_branch_history",
         "can_transfer_equipment_branch",  # R2d (owner-approved, provisional)
         "can_manage_personnel", "can_manage_department"}  # R2e (owner-approved, provisional)
    )
    for role in ROLES_WITHOUT:
        assert CAN_EDIT_VEHICLE_REGISTRATION not in ROLE_CAPABILITIES[role], role
    assert {c for c in ALL_CAPABILITIES if "branch" in c} == {
        "can_transfer_vehicle_branch", "can_correct_branch_history",
        "can_transfer_equipment_branch",  # R2d (owner-approved)
    }


@pytest.mark.asyncio
async def test_me_lists_the_new_capability_for_holders_only() -> None:
    for role, expected in (("ADMIN", True), ("MAINTENANCE_MANAGER", True), *((r, False) for r in ROLES_WITHOUT)):
        caps = (await _http("GET", f"{API}/me", role=role, request_id=None)).json()["capabilities"]
        assert ("can_edit_vehicle_registration" in caps) is expected, role


BAD_BODIES = [
    ("valid", None),
    ("schema-invalid", b'{"registration_no": 5}'),
    ("extra-key", json.dumps({**_body("1", None, "0012", "TH-21"), "x": 1}).encode()),
    ("malformed-json", b"{not json"),
    ("empty", b""),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [*ROLES_WITHOUT, "NO_AUTH"])
@pytest.mark.parametrize("label,content", BAD_BODIES, ids=[b[0] for b in BAD_BODIES])
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
@pytest.mark.parametrize("with_id", [True, False])
async def test_w01_refused_with_403_and_zero_repository_calls(role, label, content, endpoint, with_id, monkeypatch) -> None:
    repo = SpyRepository()
    if endpoint == "patch":
        method, path, valid = "PATCH", _patch_path(), _body("0013", "TH-21", "0012", "TH-21")
    else:
        method, path, valid = "POST", _recon_path(), _recon_body(MockRepository(), "VEH-1046", "APPLY_RECORDED", "0012", "TH-21")
    response = await _http(
        method, path, repo=repo, role=None if role == "NO_AUTH" else role, no_auth=role == "NO_AUTH",
        monkeypatch=monkeypatch, json_body=valid if content is None else _AUTO, content=content,
        request_id=_AUTO if with_id else None,
    )
    assert response.status_code == 403, response.text
    assert _err(response)["code"] == "HTTP_ERROR"
    assert repo.calls == []


# ---------------------------------------------------------------------------
# Request id (§3.2) — W-02, dependency order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [None, "", "abc", "1234", uuid.uuid4().hex, "{" + str(uuid.uuid4()) + "}", str(uuid.uuid4()) + " "])
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
async def test_w02_missing_or_malformed_request_id_is_422_with_zero_calls(request_id, endpoint) -> None:
    repo = SpyRepository()
    method, path = ("PATCH", _patch_path()) if endpoint == "patch" else ("POST", _recon_path())
    for content in (None, b"{not json", b'{"x": 1}'):
        response = await _http(
            method, path, repo=repo, role="MAINTENANCE_MANAGER", request_id=request_id,
            json_body=_body("0013", "TH-21", "0012", "TH-21") if content is None else _AUTO, content=content,
        )
        assert response.status_code == 422, (request_id, content)
        assert _err(response)["code"] == "REQUEST_ID_REQUIRED"
    assert repo.calls == []


@pytest.mark.asyncio
async def test_w02_middleware_generated_id_does_not_satisfy_the_header_rule() -> None:
    response = await _http("PATCH", _patch_path(), repo=SpyRepository(), request_id=None,
                           json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert response.status_code == 422
    assert _err(response)["code"] == "REQUEST_ID_REQUIRED"
    assert _err(response)["request_id"]  # the middleware's own id is still echoed in the envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
async def test_order_capability_then_request_id_then_body(endpoint) -> None:
    repo = SpyRepository()
    method, path = ("PATCH", _patch_path()) if endpoint == "patch" else ("POST", _recon_path())
    no_cap = await _http(method, path, repo=repo, role="TECHNICIAN", request_id=None, content=b"{bad")
    no_id = await _http(method, path, repo=repo, role="MAINTENANCE_MANAGER", request_id="bad", content=b"{bad")
    bad_body = await _http(method, path, repo=repo, role="MAINTENANCE_MANAGER", content=b"{bad")
    assert [r.status_code for r in (no_cap, no_id, bad_body)] == [403, 422, 422]
    assert [_err(r)["code"] for r in (no_cap, no_id, bad_body)] == ["HTTP_ERROR", "REQUEST_ID_REQUIRED", "VALIDATION_ERROR"]
    assert repo.calls == []


@pytest.mark.asyncio
async def test_maintenance_manager_and_admin_may_change() -> None:
    for role, vid in (("MAINTENANCE_MANAGER", "VEH-1046"), ("ADMIN", "VEH-1046")):
        repo = MockRepository()
        response = await _http("PATCH", _patch_path(vid), repo=repo, role=role, json_body=_body("0013", "TH-21", "0012", "TH-21"))
        assert response.status_code == 200, response.text
        assert _rows(repo, vid)[-1]["recorded_by"] == "dev-user"


# ---------------------------------------------------------------------------
# Semantic validation (§4.4 step 1) — zero reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "number,province,code",
    [
        ("", "TH-21", "REGISTRATION_TEXT_INVALID"),
        ("x" * 51, None, "REGISTRATION_TEXT_INVALID"),
        ("--", None, "REGISTRATION_TEXT_INVALID"),
        ("  ", None, "REGISTRATION_TEXT_INVALID"),
        ("​﻿", None, "REGISTRATION_TEXT_INVALID"),
        (" .-– ", "TH-21", "REGISTRATION_TEXT_INVALID"),
        (None, "TH-21", "REGISTRATION_TEXT_REQUIRED"),
    ],
)
async def test_semantic_validation_refuses_before_any_read(number, province, code) -> None:
    repo = SpyRepository()
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body(number, province, "0012", "TH-21"))
    assert response.status_code == 422
    assert _err(response)["code"] == code
    assert repo.calls == []


@pytest.mark.asyncio
async def test_fifty_characters_are_allowed_and_stored_exactly() -> None:
    repo = MockRepository()
    text = " ก" + "x" * 47 + " "  # 50 characters, edge spaces kept
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body(text, "TH-21", "0012", "TH-21"))
    assert response.status_code == 200, response.text
    assert _master(repo, "VEH-1046") == (text, "TH-21")
    assert _rows(repo, "VEH-1046")[-1]["new_registration_no"] == text
    assert response.json()["vehicle"]["registry"]["registration_no"] == {"state": "RECORDED", "value": text}


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
async def test_mutation_bodies_reject_unknown_keys_with_zero_calls(endpoint) -> None:
    repo = SpyRepository()
    if endpoint == "patch":
        response = await _http("PATCH", _patch_path(), repo=repo, json_body={**_body("1", None, "0012", "TH-21"), "note": "x"})
    else:
        body = _recon_body(MockRepository(), "VEH-1046", "APPLY_RECORDED", "0012", "TH-21", extra="x")
        response = await _http("POST", _recon_path(), repo=repo, json_body=body)
    assert response.status_code == 422
    assert _err(response)["code"] == "VALIDATION_ERROR"
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["registration_no", "registration_province_code", "expected_registration_no", "expected_registration_province_code"])
async def test_patch_requires_all_four_keys(missing) -> None:
    body = _body("0013", "TH-21", "0012", "TH-21")
    del body[missing]
    repo = SpyRepository()
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=body)
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    assert repo.calls == []


# ---------------------------------------------------------------------------
# PATCH success, history-first writes, response without re-read (C8) — B-OC-04
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_writes_history_then_master_and_returns_the_contract_body() -> None:
    repo = MockRepository()
    before = list(repo._registration_history)
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("กข 77", "TH-20", "0012", "TH-21"))
    assert response.status_code == 200, response.text
    body = response.json()
    rid = response.sent_request_id
    assert response.headers["X-Request-Id"] == rid
    assert set(body) == {"request_id", "changed", "change", "master_write", "warnings", "vehicle"}
    assert body["request_id"] == rid and body["changed"] is True and body["master_write"] == "WRITTEN"
    assert body["warnings"] == []
    assert set(body["change"]) == {"change_id", "recorded_at", "request_id"}
    assert body["change"]["request_id"] == rid
    assert body["change"]["change_id"].startswith("VRH-") and len(body["change"]["change_id"]) == 36
    assert repo.registry_write_log == ["W1", "W2"]
    row = repo._registration_history[-1]
    assert repo._registration_history[:-1] == before  # earlier rows untouched
    assert row["change_kind"] == "CHANGE"
    assert (row["old_registration_no"], row["old_registration_province_code"]) == ("0012", "TH-21")
    assert (row["new_registration_no"], row["new_registration_province_code"]) == ("กข 77", "TH-20")
    assert row["recorded_by"] == "dev-user" and row["request_id"] == rid
    assert row["recorded_at"] == body["change"]["recorded_at"] and "." in row["recorded_at"] and row["recorded_at"].endswith("+00:00")
    assert row["request_fingerprint"] == request_fingerprint(
        "registration", "VEH-1046", None, _body("กข 77", "TH-20", "0012", "TH-21"))
    assert (row["is_test_data"], row["test_batch_id"]) == ("TRUE", MOCK_TEST_BATCH_ID)
    assert (row["related_request_id"], row["accepted_exceptions"], row["note_th"]) == ("", "", "")
    assert validate_registration_rows(_rows(repo, "VEH-1046"), "TEST") == {}
    assert _master(repo, "VEH-1046") == ("กข 77", "TH-20")
    # C8: the vehicle in the response is R1 plus the applied pair (no re-read)
    vehicle = body["vehicle"]
    assert vehicle["vehicle_id"] == "VEH-1046"
    assert vehicle["registry"]["registration_no"] == {"state": "RECORDED", "value": "กข 77"}
    assert vehicle["registry"]["registration_province"] == {"state": "RECORDED", "value": "TH-20"}
    assert vehicle["registry"]["responsible_branch"] == {"state": "RECORDED", "value": "BR-LAEM-CHABANG"}
    history = await _history(repo)
    assert history["consistency"] == "CONSISTENT"
    assert history["items"][-1]["request_id"] == rid


@pytest.mark.asyncio
async def test_c8_success_response_is_built_without_a_post_write_read() -> None:
    class CountingRepo(MockRepository):
        reads_after_w2 = 0

        async def read_vehicle_registration_master(self, vehicle_id):
            if "W2" in self.registry_write_log:
                CountingRepo.reads_after_w2 += 1
            return await super().read_vehicle_registration_master(vehicle_id)

        async def get_vehicle_validated(self, vehicle_id):
            if "W2" in self.registry_write_log:
                CountingRepo.reads_after_w2 += 1
            return await super().get_vehicle_validated(vehicle_id)

    repo = CountingRepo()
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert response.status_code == 200
    assert CountingRepo.reads_after_w2 == 0


@pytest.mark.asyncio
async def test_clearing_and_partial_pairs() -> None:
    repo = MockRepository()
    cleared = await _http("PATCH", _patch_path(), repo=repo, json_body=_body(None, None, "0012", "TH-21"))
    assert cleared.status_code == 200, cleared.text
    assert _master(repo, "VEH-1046") == ("", "")
    assert cleared.json()["vehicle"]["registry"]["registration_no"] == {"state": "NOT_RECORDED", "value": None}
    text_only = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("ทะเบียนรอจังหวัด", None, None, None))
    assert text_only.status_code == 200, text_only.text
    assert _master(repo, "VEH-1046") == ("ทะเบียนรอจังหวัด", "")
    assert (await _history(repo))["consistency"] == "CONSISTENT"


# ---------------------------------------------------------------------------
# W-03 registration rules, RK1 duplicates; W-04 no-op on an existing duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w03_duplicate_pair_on_another_vehicle_is_refused_with_zero_writes() -> None:
    repo = MockRepository()
    response = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body("0012", "TH-21", None, None))
    assert response.status_code == 409
    error = _err(response)
    assert error["code"] == "REGISTRATION_DUPLICATE"
    assert error["details"] == {"conflict_count": 1, "conflict_vehicle_ids": ["VEH-1046"]}
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["กข 1234", "กข-1234", "กข ๑๒๓๔", " กข.1234 ", "กข–1234", "กข​1234", "กข1234"])
async def test_w03_rk1_variants_collide_in_the_same_province(variant) -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "กข-1234", "TH-20")  # VEH-1047 has no history: master is the baseline
    response = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body(variant, "TH-20", None, None))
    assert (response.status_code, _err(response)["code"]) == (409, "REGISTRATION_DUPLICATE")


@pytest.mark.asyncio
async def test_w03_same_text_other_province_and_0012_vs_12_are_allowed() -> None:
    repo = MockRepository()
    other_province = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body("0012", "TH-20", None, None))
    assert other_province.status_code == 200, other_province.text
    repo = MockRepository()
    numeric = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body("12", "TH-21", None, None))
    assert numeric.status_code == 200, numeric.text  # "0012" != "12": no numeric conversion
    assert _master(repo, "VEH-1048") == ("12", "TH-21")


@pytest.mark.asyncio
async def test_w03_pairs_without_province_are_never_compared() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "0012", "")
    response = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body("0012", None, None, None))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_w03_a_cleared_historical_plate_can_be_reused() -> None:
    repo = MockRepository()  # VEH-1048 once held ทดสอบ 99 / TH-10 and was cleared
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("ทดสอบ 99", "TH-10", "0012", "TH-21"))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_w03_existing_duplicates_elsewhere_do_not_block_an_unrelated_pair() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "0012", "TH-21")  # already duplicates VEH-1046
    response = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body("ใหม่ 1", "TH-21", None, None))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_w03_self_exclusion_is_by_row_and_blank_id_rows_block() -> None:
    from app.domain.vehicle import Vehicle

    repo = MockRepository()
    template = repo._vehicles["VEH-1047"]
    repo._vehicles["  "] = template.model_copy(update={"vehicle_id": "  "})  # a non-phantom row with a blank id
    repo._vehicle_registry["  "] = {"registration_no": "บล 5", "registration_province_code": "TH-21", "responsible_branch_id": ""}
    assert isinstance(repo._vehicles["  "], Vehicle)
    response = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, json_body=_body("บล 5", "TH-21", None, None))
    assert response.status_code == 409
    assert _err(response)["details"] == {"conflict_count": 1, "conflict_vehicle_ids": []}  # non-blank ids only
    # the target's own row never conflicts with itself
    own = await _http("PATCH", _patch_path(), repo=MockRepository(), json_body=_body("0012 ", "TH-21", "0012", "TH-21"))
    assert own.status_code == 200, own.text


@pytest.mark.asyncio
async def test_w03_inactive_province_newly_assigned_vs_kept() -> None:
    repo = MockRepository()
    refused = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0012", "TH-76", "0012", "TH-21"))
    assert (refused.status_code, _err(refused)["code"]) == (422, "PROVINCE_INACTIVE")
    assert repo.registry_write_log == []
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "เดิม 1", "TH-76")  # no history: the inactive code is the baseline
    kept = await _http("PATCH", _patch_path("VEH-1047"), repo=repo, json_body=_body("เดิม 2", "TH-76", "เดิม 1", "TH-76"))
    assert kept.status_code == 200, kept.text


@pytest.mark.asyncio
async def test_unknown_province_is_refused_even_when_kept() -> None:
    repo = MockRepository()  # VEH-1047 holds the unknown code TH-99
    response = await _http("PATCH", _patch_path("VEH-1047"), repo=repo, json_body=_body("กข-1235", "TH-99", "กข-1234", "TH-99"))
    assert (response.status_code, _err(response)["code"]) == (422, "PROVINCE_NOT_FOUND")
    assert _err(response)["details"] == {"province_code": "TH-99"}
    blank = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0012", "", "0012", "TH-21"))
    assert (blank.status_code, _err(blank)["code"]) == (422, "PROVINCE_NOT_FOUND")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_w04_noop_on_an_existing_duplicate_warns_and_writes_nothing() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "0012", "TH-21")
    response = await _http("PATCH", _patch_path("VEH-1047"), repo=repo, json_body=_body("0012", "TH-21", "0012", "TH-21"))
    assert response.status_code == 200
    body = response.json()
    assert body == {"request_id": response.sent_request_id, "changed": False, "warnings": ["EXISTING_DUPLICATE_PAIR"]}
    assert repo.registry_write_log == []
    plain = await _http("PATCH", _patch_path(), repo=MockRepository(), json_body=_body("0012", "TH-21", "0012", "TH-21"))
    assert plain.json()["warnings"] == [] and plain.json()["changed"] is False


@pytest.mark.asyncio
async def test_noop_reads_no_province_master() -> None:
    repo = SpyRepository()
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0012", "TH-21", "0012", "TH-21"))
    assert response.json()["changed"] is False
    assert "read_province_master_validated" not in repo.calls
    assert repo.calls == ["read_vehicle_registration_master", "get_vehicle_validated", "read_vehicle_registration_history_validated"]


# ---------------------------------------------------------------------------
# W-05 stale / mismatch; C1 precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w05_stale_expected_pair() -> None:
    repo = MockRepository()
    stale = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0011", "TH-21"))
    assert (stale.status_code, _err(stale)["code"]) == (409, "VEHICLE_REGISTRY_STALE")
    assert _err(stale)["details"] == {"current_matches_request": False}
    already = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0012", "TH-21", "0011", None))
    assert _err(already)["details"] == {"current_matches_request": True}
    null_vs_value = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", None))
    assert _err(null_vs_value)["code"] == "VEHICLE_REGISTRY_STALE"  # null compared exactly
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_w05_projection_mismatch() -> None:
    repo = _mismatch_repo()
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0100", "TH-20", "0099", "TH-20"))
    assert (response.status_code, _err(response)["code"]) == (409, "REGISTRATION_PROJECTION_MISMATCH")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_c1_projection_mismatch_precedes_stale() -> None:
    repo = _mismatch_repo()
    # expected values are ALSO stale (they name the recorded pair, not the master)
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0100", "TH-20", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (409, "REGISTRATION_PROJECTION_MISMATCH")


@pytest.mark.asyncio
async def test_first_change_from_imported_value_has_no_history_and_is_not_a_mismatch() -> None:
    repo = MockRepository()  # VEH-1047: NO_HISTORY
    response = await _http("PATCH", _patch_path("VEH-1047"), repo=repo, json_body=_body("กข-1234", "TH-20", "กข-1234", "TH-99"))
    assert response.status_code == 200, response.text
    row = _rows(repo, "VEH-1047")[0]
    assert (row["old_registration_no"], row["old_registration_province_code"]) == ("กข-1234", "TH-99")  # baseline kept


# ---------------------------------------------------------------------------
# Reference, history and context failures (zero writes; never "not found")
# ---------------------------------------------------------------------------


def _raise(exc):
    async def method(*args, **kwargs):
        raise exc

    return method


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc,status,code",
    [
        (RepositoryTabReadError("province_master", "down"), 503, "PROVINCE_MASTER_READ_FAILED"),
        (RepositorySchemaError("province_master", "TAB_MISSING"), 500, "PROVINCE_MASTER_SCHEMA_INVALID"),
    ],
)
async def test_province_outage_is_never_reported_as_not_found(exc, status, code) -> None:
    repo = MockRepository()
    repo.read_province_master_validated = _raise(exc)  # type: ignore[method-assign]
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (status, code)
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_invalid_province_master_is_data_invalid() -> None:
    repo = MockRepository()
    repo._province_master.append({"province_code": "TH-21", "province_name_th": "ซ้ำ", "is_active": "TRUE"})
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (500, "PROVINCE_MASTER_DATA_INVALID")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc,status,code",
    [
        (RepositoryTabReadError("vehicle_registration_history", "down"), 503, "REGISTRATION_HISTORY_READ_FAILED"),
        (RepositorySchemaError("vehicle_registration_history", "MISSING_HEADERS", ("note_th",)), 500, "REGISTRATION_HISTORY_SCHEMA_INVALID"),
        (RepositoryTabReadError("vehicle_master", "down"), 503, "VEHICLE_MASTER_READ_FAILED"),
        (RepositorySchemaError("vehicle_master", "MISSING_HEADERS", ("vehicle_id",)), 500, "VEHICLE_MASTER_SCHEMA_INVALID"),
    ],
)
async def test_read_failures_are_coded_with_zero_writes(exc, status, code) -> None:
    repo = MockRepository()
    target = "read_vehicle_registration_history_validated" if exc.tab == "vehicle_registration_history" else "read_vehicle_registration_master"
    setattr(repo, target, _raise(exc))
    for method, path, body in (
        ("PATCH", _patch_path(), _body("0013", "TH-21", "0012", "TH-21")),
        ("POST", _recon_path(), _recon_body(MockRepository(), "VEH-1046", "APPLY_RECORDED", "0012", "TH-21")),
    ):
        response = await _http(method, path, repo=repo, json_body=body)
        assert (response.status_code, _err(response)["code"]) == (status, code)
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_missing_registration_columns_stop_writes_before_any_write() -> None:
    repo = MockRepository()
    original = repo.read_vehicle_registration_master

    async def without_province(vehicle_id):
        read = await original(vehicle_id)
        return RegistrationMasterRead(
            vehicle=read.vehicle, registry=read.registry, registry_columns=frozenset({"registration_no"}),
            target_row_key=read.target_row_key, rows=read.rows, write_target=read.write_target,
        )

    repo.read_vehicle_registration_master = without_province  # type: ignore[method-assign]
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", None, "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")
    assert _err(response)["details"] == {"tab": "vehicle_master", "problem": "MISSING_HEADERS", "headers": ["registration_province_code"]}
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_vehicle_not_found_ambiguous_and_invalid_record() -> None:
    repo = MockRepository()
    missing = await _http("PATCH", _patch_path("VEH-NONE"), repo=repo, json_body=_body("1", None, None, None))
    assert (missing.status_code, _err(missing)["code"]) == (404, "VEHICLE_NOT_FOUND")
    repo.read_vehicle_registration_master = _raise(RepositoryIdentityAmbiguousError("vehicle_master", 2))  # type: ignore[method-assign]
    ambiguous = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("1", None, None, None))
    assert (ambiguous.status_code, _err(ambiguous)["code"]) == (409, "VEHICLE_ID_AMBIGUOUS")
    repo.read_vehicle_registration_master = _raise(RepositoryRecordInvalidError("vehicle_master", "BLANK_STATUS"))  # type: ignore[method-assign]
    invalid = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("1", None, None, None))
    assert (invalid.status_code, _err(invalid)["code"]) == (500, "VEHICLE_MASTER_DATA_INVALID")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_unset_data_context_is_503_before_any_read() -> None:
    repo = SpyRepository()
    response = await _http("PATCH", _patch_path(), repo=repo, settings=_sheets_settings(None, "BATCH-1"),
                           json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_c7_blank_test_batch_id_refuses_mutations_but_not_reads() -> None:
    repo = SpyRepository()
    settings = _sheets_settings("TEST", "")
    patch = await _http("PATCH", _patch_path(), repo=repo, settings=settings, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (patch.status_code, _err(patch)["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert _err(patch)["details"] == {"setting": "REGISTRY_TEST_BATCH_ID"}
    recon = await _http("POST", _recon_path(), repo=repo, settings=settings,
                        json_body=_recon_body(MockRepository(), "VEH-1046", "APPLY_RECORDED", "0012", "TH-21"))
    assert (recon.status_code, _err(recon)["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.calls == []
    # the 7O2a read endpoints keep working with a blank batch id
    for path in ("/vehicles/VEH-1046/registration-history", "/vehicles/VEH-1046/branch-history", "/provinces", "/branches"):
        read = await _http("GET", f"{API}{path}", repo=MockRepository(), settings=settings, request_id=None)
        assert read.status_code == 200, (path, read.text)


@pytest.mark.asyncio
async def test_c7_configured_batch_id_is_written_and_mock_uses_the_labelled_synthetic_id() -> None:
    repo = MockRepository()
    response = await _http("PATCH", _patch_path(), repo=repo, settings=_sheets_settings("TEST", "UAT-BATCH-7"),
                           json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert response.status_code == 200, response.text
    assert (_rows(repo, "VEH-1046")[-1]["is_test_data"], _rows(repo, "VEH-1046")[-1]["test_batch_id"]) == ("TRUE", "UAT-BATCH-7")
    repo = MockRepository()
    await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert _rows(repo, "VEH-1046")[-1]["test_batch_id"] == MOCK_TEST_BATCH_ID == "MOCK-7O2B-SYNTHETIC"
    with pytest.raises(ValueError):
        Settings(data_repository=DataRepositoryMode.MOCK, registry_data_context="REAL")


@pytest.mark.asyncio
async def test_real_context_writes_false_flags_and_refuses_test_rows() -> None:
    from app.domain.registration import REGISTRATION_HISTORY_COLUMNS

    repo = MockRepository()
    # REAL: the seed's TRUE rows of VEH-1046 are CUTOVER_INCOMPLETE -> refused before any write
    service = RegistrationWriteService(repo, "REAL", "")
    with pytest.raises(ApiError) as info:
        await service.change_registration("VEH-1046", _body("0013", "TH-21", "0012", "TH-21"), request_id=_rid(), user_id="u1")
    assert info.value.code == "REGISTRATION_HISTORY_DATA_INVALID"
    assert "CUTOVER_INCOMPLETE" in info.value.details["issues"]
    assert repo.registry_write_log == []
    # REAL with no rows for the vehicle: rows are written FALSE without a batch id
    repo._registration_history = [r for r in repo._registration_history if r["vehicle_id"] != "VEH-1047"]
    outcome = await service.change_registration("VEH-1047", _body("ก 1", "TH-20", "กข-1234", "TH-99"), request_id=_rid(), user_id="u1")
    assert outcome.changed
    row = _rows(repo, "VEH-1047")[-1]
    assert set(row) == set(REGISTRATION_HISTORY_COLUMNS)
    assert (row["is_test_data"], row["test_batch_id"], row["recorded_by"]) == ("FALSE", "", "u1")


# ---------------------------------------------------------------------------
# W-15 history row matrix blocks mutations; tab-wide duplicate ids
# ---------------------------------------------------------------------------

ROW_DEFECTS = {
    "CHANGE_KIND_INVALID": {"change_kind": "EDIT"},
    "CHANGE_ID_INVALID": {"change_id": "VRH-xyz"},
    "RECORDED_AT_INVALID": {"recorded_at": "2026-09-05T03:00:00"},
    "FIELD_REQUIRED:recorded_by": {"recorded_by": ""},
    "FIELD_REQUIRED:request_id": {"request_id": ""},
    "FINGERPRINT_INVALID": {"request_fingerprint": "abc"},
    "TEST_FLAG_INVALID": {"is_test_data": "yes"},
    "NEW_PAIR_INVALID": {"new_registration_no": "", "new_registration_province_code": "TH-21"},
    "REASON_REQUIRED": {"change_kind": "RECONCILIATION_ACCEPT_MASTER", "note_th": " "},
    "RELATED_REQUEST_DANGLING": {"related_request_id": "mock-seed-7o2a-0101"},
    "ACCEPTED_EXCEPTIONS_INVALID": {"accepted_exceptions": "EXISTING_DUPLICATE_PAIR"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("issue", sorted(ROW_DEFECTS))
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
async def test_w15_every_row_issue_blocks_both_mutations(issue, endpoint) -> None:
    repo = _mismatch_repo()
    repo._registration_history[0].update(ROW_DEFECTS[issue])  # VEH-1046's only row
    if endpoint == "patch":
        response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0099", "TH-20"))
    else:
        response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"))
    assert (response.status_code, _err(response)["code"]) == (500, "REGISTRATION_HISTORY_DATA_INVALID")
    assert issue in _err(response)["details"]["issues"]
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_w15_duplicate_request_and_change_ids() -> None:
    repo = MockRepository()
    extra = dict(repo._registration_history[0], change_id="VRH-" + "d" * 32, recorded_at="2026-09-06T03:00:00+00:00")
    repo._registration_history.append(extra)  # same request id twice for VEH-1046
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert "REQUEST_ID_DUPLICATE" in _err(response)["details"]["issues"]
    repo = MockRepository()
    other = dict(repo._registration_history[1])  # VEH-1048's row id reused on VEH-1047 (another vehicle)
    other.update(vehicle_id="VEH-1047", request_id="other-request")
    repo._registration_history.append(other)
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (500, "REGISTRATION_HISTORY_DATA_INVALID")
    assert _err(response)["details"]["issues"] == {"CHANGE_ID_DUPLICATE": 1}  # anywhere in the tab
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# W-07 write-failure matrix (history-first boundary table §4.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,outcome,row_recorded",
    [("rejected", "rejected", False), ("unknown_applied", "unknown", True), ("unknown_not_applied", "unknown", False)],
)
async def test_w07_w1_failures(fault, outcome, row_recorded) -> None:
    repo = MockRepository()
    repo.registry_write_faults["W1"] = fault
    before = len(repo._registration_history)
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (503, "REGISTRATION_HISTORY_WRITE_FAILED")
    assert _err(response)["details"] == {
        "history_write_outcome": outcome, "master_write": "NOT_ATTEMPTED", "request_id": response.sent_request_id,
    }
    assert _err(response)["request_id"] == response.sent_request_id
    assert repo.registry_write_log == ["W1"]  # W2 never attempted
    assert _master(repo, "VEH-1046") == ("0012", "TH-21")
    assert len(repo._registration_history) == before + (1 if row_recorded else 0)
    consistency = (await _history(repo))["consistency"]
    assert consistency == ("MISMATCH" if row_recorded else "CONSISTENT")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,outcome,master_applied",
    [("rejected", "rejected", False), ("unknown_applied", "unknown", True), ("unknown_not_applied", "unknown", False)],
)
async def test_w07_w2_failures(fault, outcome, master_applied) -> None:
    repo = MockRepository()
    repo.registry_write_faults["W2"] = fault
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (503, "VEHICLE_MASTER_WRITE_FAILED")
    details = _err(response)["details"]
    assert details["history_recorded"] is True and details["master_write_outcome"] == outcome
    assert details["request_id"] == response.sent_request_id
    assert details["change_id"] == _rows(repo, "VEH-1046")[-1]["change_id"]
    assert repo.registry_write_log == ["W1", "W2"]
    assert _master(repo, "VEH-1046") == (("0013", "TH-21") if master_applied else ("0012", "TH-21"))
    history = await _history(repo)
    assert history["consistency"] == ("CONSISTENT" if master_applied else "MISMATCH")
    assert history["items"][-1]["request_id"] == response.sent_request_id


# ---------------------------------------------------------------------------
# W-06 replay; C4 request identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w06_replay_after_success_matches() -> None:
    repo = MockRepository()
    rid = _rid()
    body = _body("0013", "TH-21", "0012", "TH-21")
    first = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    again = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    assert again.status_code == 200
    assert again.json() == {
        "request_id": rid, "replayed": True, "record_ids": [first.json()["change"]["change_id"]],
        "master_state": "MATCHES", "consistency": "CONSISTENT",
    }
    assert again.headers["X-Request-Id"] == rid
    assert repo.registry_write_log == ["W1", "W2"]  # the replay wrote nothing


@pytest.mark.asyncio
@pytest.mark.parametrize("w2_fault", ["rejected", "unknown_not_applied"])
async def test_w06_replay_after_a_partial_write_reports_differs(w2_fault) -> None:
    repo = MockRepository()
    repo.registry_write_faults["W2"] = w2_fault
    rid, body = _rid(), _body("0013", "TH-21", "0012", "TH-21")
    await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    repo.registry_write_faults.clear()
    again = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    assert again.status_code == 200
    assert (again.json()["replayed"], again.json()["master_state"], again.json()["consistency"]) == (True, "DIFFERS", "MISMATCH")
    assert repo.registry_write_log == ["W1", "W2"]


@pytest.mark.asyncio
async def test_w06_replay_after_w1_unknown_applied_and_replay_precedes_stale() -> None:
    repo = MockRepository()
    repo.registry_write_faults["W1"] = "unknown_applied"
    rid, body = _rid(), _body("0013", "TH-21", "0012", "TH-21")
    await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    repo.registry_write_faults.clear()
    _set_master(repo, "VEH-1046", "0050", "TH-20")  # the expected values are now stale too
    again = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["master_state"] == "DIFFERS"


@pytest.mark.asyncio
async def test_w06_reuse_after_a_rejected_attempt_is_processed_as_new() -> None:
    repo = MockRepository()
    repo.registry_write_faults["W1"] = "rejected"
    rid, body = _rid(), _body("0013", "TH-21", "0012", "TH-21")
    first = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    assert _err(first)["details"]["history_write_outcome"] == "rejected"
    repo.registry_write_faults.clear()
    resend = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    assert resend.status_code == 200 and resend.json()["changed"] is True


@pytest.mark.asyncio
async def test_c4_same_id_identical_body_replays_changed_value_is_reused_extra_key_is_invalid() -> None:
    repo = MockRepository()
    rid, body = _rid(), _body("0013", "TH-21", "0012", "TH-21")
    await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=body)
    same = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body=dict(reversed(list(body.items()))))
    assert same.json()["replayed"] is True  # key order is not identity
    changed = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body={**body, "registration_no": "0014"})
    assert (changed.status_code, _err(changed)["code"]) == (409, "REQUEST_ID_REUSED")
    trimmed = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body={**body, "registration_no": "0013 "})
    assert _err(trimmed)["code"] == "REQUEST_ID_REUSED"  # text is never normalised before fingerprinting
    extra = await _http("PATCH", _patch_path(), repo=repo, request_id=rid, json_body={**body, "comment": "x"})
    assert (extra.status_code, _err(extra)["code"]) == (422, "VALIDATION_ERROR")
    other_vehicle = await _http("PATCH", _patch_path("VEH-1048"), repo=repo, request_id=rid, json_body=_body("0013", "TH-21", None, None))
    assert _err(other_vehicle)["code"] == "REQUEST_ID_REUSED"
    other_op = await _http("POST", _recon_path(), repo=repo, request_id=rid,
                           json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0013", "TH-21"))
    assert _err(other_op)["code"] == "REQUEST_ID_REUSED"
    assert repo.registry_write_log == ["W1", "W2"]


def test_c4_fingerprint_is_canonical_json_of_the_accepted_body() -> None:
    body = {"registration_no": "กข 1", "registration_province_code": None,
            "expected_registration_no": None, "expected_registration_province_code": None}
    canonical = (
        '{"body":{"expected_registration_no":null,"expected_registration_province_code":null,'
        '"registration_no":"กข 1","registration_province_code":null},"event_id":null,"op":"registration","vehicle_id":"VEH-1"}'
    )
    assert request_fingerprint("registration", "VEH-1", None, body) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with_null = {"mode": "ACCEPT_MASTER", "related_request_id": None}
    without = {"mode": "ACCEPT_MASTER"}
    assert request_fingerprint("registration_reconcile", "V", None, with_null) != request_fingerprint("registration_reconcile", "V", None, without)


@pytest.mark.asyncio
async def test_c4_reconciliation_omitted_vs_null_related_request_id_are_different_requests() -> None:
    repo = _mismatch_repo()
    rid = _rid()
    omitted = _recon_body(repo, "VEH-1046", "ACCEPT_MASTER", "0099", "TH-20")
    assert "related_request_id" not in omitted
    first = await _http("POST", _recon_path(), repo=repo, request_id=rid, json_body=omitted)
    assert first.status_code == 200, first.text
    assert _rows(repo, "VEH-1046")[-1]["request_fingerprint"] == request_fingerprint("registration_reconcile", "VEH-1046", None, omitted)
    explicit_null = {**omitted, "related_request_id": None}
    again = await _http("POST", _recon_path(), repo=repo, request_id=rid, json_body=explicit_null)
    assert (again.status_code, _err(again)["code"]) == (409, "REQUEST_ID_REUSED")  # presence is part of identity
    same = await _http("POST", _recon_path(), repo=repo, request_id=rid, json_body=omitted)
    assert same.json()["replayed"] is True


# ---------------------------------------------------------------------------
# W-08 / W-14 / W-15 reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w08_apply_recorded_writes_audit_row_and_master() -> None:
    repo = _mismatch_repo()
    before = [dict(r) for r in repo._registration_history]
    body = _recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20", related_request_id="mock-seed-7o2a-0101")
    response = await _http("POST", _recon_path(), repo=repo, json_body=body)
    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out) == {"request_id", "changed", "change", "master_write", "warnings"}
    assert (out["changed"], out["master_write"], out["warnings"]) == (True, "WRITTEN", [])
    assert repo.registry_write_log == ["W1", "W2"]
    assert repo._registration_history[:-1] == before  # never edits or re-appends earlier rows
    row = repo._registration_history[-1]
    assert row["change_kind"] == "RECONCILIATION_APPLY_RECORDED"
    assert (row["old_registration_no"], row["old_registration_province_code"]) == ("0099", "TH-20")
    assert (row["new_registration_no"], row["new_registration_province_code"]) == ("0012", "TH-21")
    assert row["related_request_id"] == "mock-seed-7o2a-0101" and row["note_th"] == body["reason_th"]
    assert _master(repo, "VEH-1046") == ("0012", "TH-21")
    assert (await _history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_c2_accept_master_writes_history_only_and_returns_not_needed() -> None:
    repo = _mismatch_repo()
    response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "ACCEPT_MASTER", "0099", "TH-20"))
    assert response.status_code == 200, response.text
    assert response.json()["master_write"] == "NOT_NEEDED"
    assert response.json()["warnings"] == []
    assert repo.registry_write_log == ["W1"]
    row = repo._registration_history[-1]
    assert row["change_kind"] == "RECONCILIATION_ACCEPT_MASTER"
    assert (row["old_registration_no"], row["new_registration_no"]) == ("0012", "0099")
    assert row["accepted_exceptions"] == ""
    assert _master(repo, "VEH-1046") == ("0099", "TH-20")
    assert (await _history(repo))["consistency"] == "CONSISTENT"
    later = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0100", "TH-20", "0099", "TH-20"))
    assert later.status_code == 200  # later genuine edits work


@pytest.mark.asyncio
async def test_w08_apply_blocked_by_duplicate_accept_records_it() -> None:
    repo = _mismatch_repo()
    _set_master(repo, "VEH-1047", "0012", "TH-21")  # the recorded pair is now held by another vehicle
    apply = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"))
    assert (apply.status_code, _err(apply)["code"]) == (409, "REGISTRATION_DUPLICATE")
    assert _err(apply)["details"] == {"conflict_count": 1, "conflict_vehicle_ids": ["VEH-1047"]}
    assert repo.registry_write_log == []
    _set_master(repo, "VEH-1048", "0099", "TH-20")  # the MASTER pair is also duplicated
    accept = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "ACCEPT_MASTER", "0099", "TH-20"))
    assert accept.status_code == 200, accept.text
    assert accept.json()["warnings"] == ["EXISTING_DUPLICATE_PAIR"]
    assert repo._registration_history[-1]["accepted_exceptions"] == "EXISTING_DUPLICATE_PAIR"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,expected", [("TH-99", "REFERENCE_UNKNOWN_ACCEPTED"), ("TH-76", "REFERENCE_INACTIVE_ACCEPTED")])
async def test_w15_accept_master_records_reference_exceptions(code, expected) -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1046", "0099", code)
    response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "ACCEPT_MASTER", "0099", code))
    assert response.status_code == 200, response.text
    assert response.json()["warnings"] == [expected]
    assert repo._registration_history[-1]["accepted_exceptions"] == expected
    assert validate_registration_rows(_rows(repo, "VEH-1046"), "TEST") == {}


@pytest.mark.asyncio
async def test_accept_master_province_outage_is_503_never_guessed() -> None:
    repo = _mismatch_repo()
    repo.read_province_master_validated = _raise(RepositoryTabReadError("province_master", "down"))  # type: ignore[method-assign]
    response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "ACCEPT_MASTER", "0099", "TH-20"))
    assert (response.status_code, _err(response)["code"]) == (503, "PROVINCE_MASTER_READ_FAILED")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("master", [("", "TH-20"), ("x" * 51, "TH-20"), ("--", "")])
async def test_w15_accept_of_a_malformed_master_pair_is_409(master) -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1046", *master)
    exp = (master[0] or None, master[1] or None)
    response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "ACCEPT_MASTER", *exp))
    assert (response.status_code, _err(response)["code"]) == (409, "MASTER_PAIR_INVALID")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_w15_apply_of_a_since_inactive_or_unknown_province_is_422() -> None:
    repo = _mismatch_repo()
    next(p for p in repo._province_master if p["province_code"] == "TH-21")["is_active"] = "FALSE"
    inactive = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"))
    assert (inactive.status_code, _err(inactive)["code"]) == (422, "PROVINCE_INACTIVE")
    repo._province_master = [p for p in repo._province_master if p["province_code"] != "TH-21"]
    unknown = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"))
    assert (unknown.status_code, _err(unknown)["code"]) == (422, "PROVINCE_NOT_FOUND")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_w14_related_request_id_must_name_this_vehicles_request() -> None:
    repo = _mismatch_repo()
    for related in ("no-such-request", "mock-seed-7o2a-0102"):  # nonexistent; VEH-1048's request
        response = await _http("POST", _recon_path(), repo=repo,
                               json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20", related_request_id=related))
        assert (response.status_code, _err(response)["code"]) == (422, "RELATED_REQUEST_NOT_FOUND"), related
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,consistency,master",
    [("rejected", "MISMATCH", ("0099", "TH-20")), ("unknown_applied", "CONSISTENT", ("0012", "TH-21")),
     ("unknown_not_applied", "MISMATCH", ("0099", "TH-20"))],
)
async def test_w14_apply_w2_failures_leave_history_as_the_evidence(fault, consistency, master) -> None:
    repo = _mismatch_repo()
    repo.registry_write_faults["W2"] = fault
    response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"))
    assert (response.status_code, _err(response)["code"]) == (503, "VEHICLE_MASTER_WRITE_FAILED")
    assert _err(response)["details"]["history_recorded"] is True
    assert _master(repo, "VEH-1046") == master
    assert (await _history(repo))["consistency"] == consistency


@pytest.mark.asyncio
async def test_reconciliation_stale_checks_and_noops() -> None:
    repo = _mismatch_repo()
    stale_pair = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0012", "TH-21"))
    assert (stale_pair.status_code, _err(stale_pair)["code"]) == (409, "VEHICLE_REGISTRY_STALE")
    stale_rev = await _http("POST", _recon_path(), repo=repo,
                            json_body={**_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"), "expected_history_revision": "RHR1-0"})
    assert (stale_rev.status_code, _err(stale_rev)["code"]) == (409, "REGISTRATION_HISTORY_STALE")
    consistent = MockRepository()
    noop = await _http("POST", _recon_path(), repo=consistent, json_body=_recon_body(consistent, "VEH-1046", "APPLY_RECORDED", "0012", "TH-21"))
    assert noop.json() == {"request_id": noop.sent_request_id, "changed": False, "warnings": []}
    no_history = await _http("POST", _recon_path("VEH-1047"), repo=consistent,
                             json_body=_recon_body(consistent, "VEH-1047", "ACCEPT_MASTER", "กข-1234", "TH-99"))
    assert no_history.json()["changed"] is False
    assert repo.registry_write_log == [] and consistent.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [({"mode": "FIX"}, "RECONCILIATION_MODE_INVALID"), ({"mode": None}, "RECONCILIATION_MODE_INVALID"),
     ({"reason_th": "  "}, "REASON_REQUIRED"), ({"reason_th": None}, "REASON_REQUIRED")],
)
async def test_reconciliation_semantic_refusals_have_zero_reads(change, code) -> None:
    repo = SpyRepository()
    body = {**_recon_body(MockRepository(), "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"), **change}
    response = await _http("POST", _recon_path(), repo=repo, json_body=body)
    assert (response.status_code, _err(response)["code"]) == (422, code)
    assert repo.calls == []


# R1 fix 1: the 1-500 character reason rule is semantic (REASON_REQUIRED), not
# framework validation, for direct API callers too.
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["APPLY_RECORDED", "ACCEPT_MASTER"])
@pytest.mark.parametrize(
    "reason", ["", "   ", "\t\n", None, "ก" * 501, " " + "x" * 500], ids=["empty", "spaces", "tab-newline", "null", "501", "501-edge-space"]
)
async def test_r1_reason_rule_is_semantic_reason_required_with_zero_calls(mode, reason) -> None:
    repo = SpyRepository()
    body = {**_recon_body(MockRepository(), "VEH-1046", mode, "0099", "TH-20"), "reason_th": reason}
    response = await _http("POST", _recon_path(), repo=repo, json_body=body)
    assert (response.status_code, _err(response)["code"]) == (422, "REASON_REQUIRED")
    assert repo.calls == []
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r1_reason_of_wrong_type_is_still_framework_validation() -> None:
    repo = SpyRepository()
    body = {**_recon_body(MockRepository(), "VEH-1046", "ACCEPT_MASTER", "0099", "TH-20"), "reason_th": 5}
    response = await _http("POST", _recon_path(), repo=repo, json_body=body)
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["ก" * 500, " " + "ข" * 498 + " ", "x"], ids=["500", "500-edge-spaces", "1"])
async def test_r1_reason_of_1_to_500_characters_is_accepted_and_stored_exactly(reason) -> None:
    repo = _mismatch_repo()
    body = {**_recon_body(repo, "VEH-1046", "ACCEPT_MASTER", "0099", "TH-20"), "reason_th": reason}
    response = await _http("POST", _recon_path(), repo=repo, json_body=body)
    assert response.status_code == 200, response.text
    assert _rows(repo, "VEH-1046")[-1]["note_th"] == reason  # not trimmed
    assert validate_registration_rows(_rows(repo, "VEH-1046"), "TEST") == {}


@pytest.mark.asyncio
async def test_w14_a_malformed_recorded_pair_can_never_be_applied() -> None:
    repo = _mismatch_repo()
    repo._registration_history[0].update(new_registration_no="", new_registration_province_code="TH-21")
    response = await _http("POST", _recon_path(), repo=repo, json_body=_recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20"))
    assert (response.status_code, _err(response)["code"]) == (500, "REGISTRATION_HISTORY_DATA_INVALID")
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# B-OC-01 every allowlisted pair: exact status/code, zero writes, correlated id
# ---------------------------------------------------------------------------


def _patch_case(**kw):
    return {"method": "PATCH", "vid": "VEH-1046", "body": _body("0013", "TH-21", "0012", "TH-21"), **kw}


def _recon_case(**kw):
    def build(repo):
        return _recon_body(repo, "VEH-1046", "APPLY_RECORDED", "0099", "TH-20")

    return {"method": "POST", "vid": "VEH-1046", "body": build, "mismatch": True, **kw}


def _common_cases(make):
    def schema_missing(repo):
        original = repo.read_vehicle_registration_master

        async def read(vehicle_id):
            r = await original(vehicle_id)
            return RegistrationMasterRead(r.vehicle, r.registry, frozenset(), r.target_row_key, r.rows, r.write_target)

        repo.read_vehicle_registration_master = read

    def setter(name, exc):
        return lambda repo: setattr(repo, name, _raise(exc))

    def bad_history(repo):
        repo._registration_history[0]["recorded_by"] = ""

    def dup_province(repo):
        repo._province_master.append(dict(repo._province_master[0]))

    return {
        (403, "HTTP_ERROR"): make(role="DRIVER"),
        (422, "REQUEST_ID_REQUIRED"): make(request_id="not-a-uuid"),
        (422, "VALIDATION_ERROR"): make(extra_key=True),
        (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"): make(settings=_sheets_settings(None, "B")),
        (404, "VEHICLE_NOT_FOUND"): make(vid="VEH-NONE"),
        (409, "VEHICLE_ID_AMBIGUOUS"): make(mutate=setter("read_vehicle_registration_master", RepositoryIdentityAmbiguousError("vehicle_master", 2))),
        (500, "VEHICLE_MASTER_DATA_INVALID"): make(mutate=setter("read_vehicle_registration_master", RepositoryRecordInvalidError("vehicle_master", "BLANK_STATUS"))),
        (500, "VEHICLE_MASTER_SCHEMA_INVALID"): make(mutate=schema_missing),
        (503, "VEHICLE_MASTER_READ_FAILED"): make(mutate=setter("read_vehicle_registration_master", RepositoryTabReadError("vehicle_master", "x"))),
        (503, "REGISTRATION_HISTORY_READ_FAILED"): make(mutate=setter("read_vehicle_registration_history_validated", RepositoryTabReadError("vehicle_registration_history", "x"))),
        (500, "REGISTRATION_HISTORY_SCHEMA_INVALID"): make(mutate=setter("read_vehicle_registration_history_validated", RepositorySchemaError("vehicle_registration_history", "TAB_MISSING"))),
        (500, "REGISTRATION_HISTORY_DATA_INVALID"): make(mutate=bad_history),
        (503, "PROVINCE_MASTER_READ_FAILED"): make(mutate=setter("read_province_master_validated", RepositoryTabReadError("province_master", "x"))),
        (500, "PROVINCE_MASTER_SCHEMA_INVALID"): make(mutate=setter("read_province_master_validated", RepositorySchemaError("province_master", "TAB_MISSING"))),
        (500, "PROVINCE_MASTER_DATA_INVALID"): make(mutate=dup_province),
    }


def _province(repo, code, **cells):
    next(p for p in repo._province_master if p["province_code"] == code).update(cells)


B_OC_CASES = {
    "registration": {
        **_common_cases(_patch_case),
        (422, "REGISTRATION_TEXT_INVALID"): _patch_case(body=_body("", None, "0012", "TH-21")),
        (422, "REGISTRATION_TEXT_REQUIRED"): _patch_case(body=_body(None, "TH-21", "0012", "TH-21")),
        (409, "REGISTRATION_PROJECTION_MISMATCH"): _patch_case(mutate=lambda r: _set_master(r, "VEH-1046", "0099", "TH-20"), body=_body("1", None, "0099", "TH-20")),
        (409, "VEHICLE_REGISTRY_STALE"): _patch_case(body=_body("0013", "TH-21", "9", "TH-21")),
        (422, "PROVINCE_NOT_FOUND"): _patch_case(body=_body("0013", "TH-98", "0012", "TH-21")),
        (422, "PROVINCE_INACTIVE"): _patch_case(body=_body("0013", "TH-76", "0012", "TH-21")),
        (409, "REGISTRATION_DUPLICATE"): _patch_case(mutate=lambda r: _set_master(r, "VEH-1047", "0013", "TH-21")),
    },
    "registration_reconcile": {
        **_common_cases(_recon_case),
        (422, "RECONCILIATION_MODE_INVALID"): _recon_case(patch={"mode": "X"}),
        (422, "REASON_REQUIRED"): _recon_case(patch={"reason_th": ""}),
        (422, "RELATED_REQUEST_NOT_FOUND"): _recon_case(patch={"related_request_id": "nope"}),
        (409, "VEHICLE_REGISTRY_STALE"): _recon_case(patch={"expected_registration_no": "0012"}),
        (409, "REGISTRATION_HISTORY_STALE"): _recon_case(patch={"expected_history_revision": "RHR1-x"}),
        (409, "MASTER_PAIR_INVALID"): _recon_case(mutate=lambda r: _set_master(r, "VEH-1046", "", "TH-20"),
                                                  patch={"mode": "ACCEPT_MASTER", "expected_registration_no": None}),
        (422, "PROVINCE_NOT_FOUND"): _recon_case(mutate=lambda r: setattr(r, "_province_master", [p for p in r._province_master if p["province_code"] != "TH-21"])),
        (422, "PROVINCE_INACTIVE"): _recon_case(mutate=lambda r: _province(r, "TH-21", is_active="FALSE")),
        (409, "REGISTRATION_DUPLICATE"): _recon_case(mutate=lambda r: _set_master(r, "VEH-1047", "0012", "TH-21")),
    },
}


def test_b_oc_cases_cover_exactly_the_allowlist() -> None:
    for op, cases in B_OC_CASES.items():
        assert set(cases) == set(ZERO_WRITE_ALLOWLIST[op]), op


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "op,pair", [(op, pair) for op, cases in B_OC_CASES.items() for pair in sorted(cases)], ids=lambda v: v if isinstance(v, str) else f"{v[0]}-{v[1]}"
)
async def test_b_oc_01_each_allowlisted_pair_writes_nothing(op, pair) -> None:
    case = B_OC_CASES[op][pair]
    repo = _mismatch_repo() if case.get("mismatch") else MockRepository()
    body = case["body"](repo) if callable(case["body"]) else dict(case["body"])
    body.update(case.get("patch", {}))
    if case.get("extra_key"):
        body["unexpected"] = 1
    if "mutate" in case:
        case["mutate"](repo)
    path = _patch_path(case["vid"]) if case["method"] == "PATCH" else _recon_path(case["vid"])
    response = await _http(
        case["method"], path, repo=repo, json_body=body, role=case.get("role", "MAINTENANCE_MANAGER"),
        request_id=case.get("request_id", _AUTO), settings=case.get("settings"),
    )
    assert (response.status_code, _err(response)["code"]) == pair, response.text
    assert _err(response)["request_id"] == response.sent_request_id
    assert repo.registry_write_log == []


def _codes_raised_in(path: Path) -> set[str]:
    """Every error code literal given to `_error(...)` / `ApiError(code=...)` in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if name == "_error" and node.args and isinstance(node.args[0], ast.Constant):
            codes.add(node.args[0].value)
        if name == "ApiError":
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Constant):
                    codes.add(kw.value.value)
    return codes


def test_b_oc_static_every_coded_refusal_is_classified() -> None:
    app_dir = REPO_ROOT / "backend" / "app"
    raised = _codes_raised_in(app_dir / "domain" / "registration_write_service.py") | _codes_raised_in(
        app_dir / "api" / "v1" / "request_id_dependency.py"
    )
    classified = {c for pairs in ZERO_WRITE_ALLOWLIST.values() for _, c in pairs} | {c for _, c in SPECIAL_OUTCOMES}
    assert raised, "the static scan found no codes"
    assert raised <= classified, raised - classified
    assert not (NEVER_ALLOWLISTED_CODES & classified)


def test_b_oc_03_no_http_exception_after_the_dependency_stage() -> None:
    app_dir = REPO_ROOT / "backend" / "app"
    for path in (app_dir / "domain" / "registration_write_service.py", app_dir / "api" / "v1" / "registration_routes.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        } | {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert "HTTPException" not in names, path
        assert "require_capability" not in names, path  # the in-handler 403 helper is not used after dependencies
    # the only HTTPException of the mutations is the capability dependency
    deps = (app_dir / "api" / "v1" / "request_id_dependency.py").read_text(encoding="utf-8")
    assert deps.count("raise HTTPException") == 1


def test_allowlist_client_and_server_tables_are_identical() -> None:
    client = json.loads((REPO_ROOT / "frontend" / "src" / "lib" / "registryOutcomeAllowlist.json").read_text(encoding="utf-8"))
    ops = {k for k in client if not k.startswith("_")}
    assert ops == set(ZERO_WRITE_ALLOWLIST)
    for op in ops:
        pairs = [tuple(p) for p in client[op]]
        assert len(pairs) == len(set(pairs)), op
        assert set(pairs) == set(ZERO_WRITE_ALLOWLIST[op]), (op, set(pairs) ^ set(ZERO_WRITE_ALLOWLIST[op]))
    flat = {c for pairs in ZERO_WRITE_ALLOWLIST.values() for _, c in pairs}
    assert not ({"INTERNAL_ERROR", "NOT_FOUND", "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE", "REQUEST_ID_REUSED",
                 "REGISTRATION_HISTORY_WRITE_FAILED", "VEHICLE_MASTER_WRITE_FAILED"} & flat)
    # HTTP_ERROR is allowlisted only with 403
    assert {s for pairs in ZERO_WRITE_ALLOWLIST.values() for s, c in pairs if c == "HTTP_ERROR"} == {403}


# ---------------------------------------------------------------------------
# B-OC-02 unexpected failures after a write are INTERNAL_ERROR (never coded)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_oc_02_crash_after_w1() -> None:
    repo = MockRepository()
    repo.registry_write_faults["W1"] = "crash_after_apply"
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (500, "INTERNAL_ERROR")
    assert _rows(repo, "VEH-1046")[-1]["request_id"] == response.sent_request_id  # recorded
    assert _master(repo, "VEH-1046") == ("0012", "TH-21")  # W2 never ran
    assert (await _history(repo))["consistency"] == "MISMATCH"


@pytest.mark.asyncio
async def test_b_oc_02_crash_after_w2() -> None:
    repo = MockRepository()
    repo.registry_write_faults["W2"] = "crash_after_apply"
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (500, "INTERNAL_ERROR")
    assert _master(repo, "VEH-1046") == ("0013", "TH-21")
    assert (await _history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_b_oc_02_failure_while_building_the_response(monkeypatch) -> None:
    import app.api.v1.registration_routes as routes

    def broken(outcome):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(routes, "_respond", broken)
    repo = MockRepository()
    response = await _http("PATCH", _patch_path(), repo=repo, json_body=_body("0013", "TH-21", "0012", "TH-21"))
    assert (response.status_code, _err(response)["code"]) == (500, "INTERNAL_ERROR")
    assert _err(response)["request_id"] == response.sent_request_id
    assert repo.registry_write_log == ["W1", "W2"]
    assert _master(repo, "VEH-1046") == ("0013", "TH-21")


# ---------------------------------------------------------------------------
# Route inventory: only the two 7O2b mutations exist (no 7O2c route)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_the_two_registration_mutations_exist() -> None:
    schema = (await _http("GET", "/openapi.json", request_id=None)).json()["paths"]
    registry_paths = {p: set(ops) for p, ops in schema.items() if any(k in p for k in ("branch", "province", "registration"))}
    assert registry_paths == {
        f"{API}/branches": {"get"},
        f"{API}/provinces": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/branch-history": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/registration-history": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/registration": {"patch"},
        f"{API}/vehicles/{{vehicle_id}}/registration-history/reconciliations": {"post"},
        f"{API}/vehicles/{{vehicle_id}}/branch-transfers": {"post"},  # 7O2c
        f"{API}/vehicles/{{vehicle_id}}/branch-history/insertions": {"post"},  # 7O2c
        f"{API}/vehicles/{{vehicle_id}}/branch-history/events/{{event_id}}/corrections": {"post"},  # 7O2c
        f"{API}/vehicles/{{vehicle_id}}/branch-history/events/{{event_id}}/cancellations": {"post"},  # 7O2c
        f"{API}/vehicles/{{vehicle_id}}/branch-projection/reconciliations": {"post"},  # 7O2c
        f"{API}/equipment/{{equipment_id}}/branch-history": {"get"},  # R2b (read only)
        f"{API}/equipment/{{equipment_id}}/branch-assignments": {"post"},  # R2d (history-only)
        f"{API}/equipment/{{equipment_id}}/branch-history/insertions": {"post"},  # R2d (history-only)
        f"{API}/equipment/{{equipment_id}}/branch-history/events/{{event_id}}/corrections": {"post"},  # R2d
        f"{API}/equipment/{{equipment_id}}/branch-history/events/{{event_id}}/cancellations": {"post"},  # R2d
    }
    patch_body = schema[f"{API}/vehicles/{{vehicle_id}}/registration"]["patch"]["requestBody"]["content"]["application/json"]["schema"]
    assert set(patch_body["required"]) == {"registration_no", "registration_province_code", "expected_registration_no", "expected_registration_province_code"}
    assert patch_body["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Raw-body parsing path (the routes parse the body themselves, after both
# dependencies). Cases A-F pinned together.
# ---------------------------------------------------------------------------

RAW_BODIES = {
    "malformed": b"{not json",
    "truncated": b'{"registration_no": "x"',
    "non-utf8": b"\xff\xfe\x00{",
    "empty": b"",
}


def _assert_json_safe_envelope(response, sent_bytes: bytes) -> None:
    """E: the envelope is plain JSON and never echoes the raw request bytes."""
    text = response.text
    json.loads(text)  # parseable
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    for item in (error["details"] or {}).get("errors", []):
        assert "input" not in item and "ctx" not in item and "url" not in item
    if len(sent_bytes.strip()) > 4:  # short bodies such as [] occur naturally in any JSON envelope
        assert sent_bytes.decode("utf-8", "replace") not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
@pytest.mark.parametrize("label", sorted(RAW_BODIES))
async def test_raw_body_a_unauthorized_malformed_is_403_zero_calls(endpoint, label) -> None:
    repo = SpyRepository()
    method, path = ("PATCH", _patch_path()) if endpoint == "patch" else ("POST", _recon_path())
    response = await _http(method, path, repo=repo, role="TECHNICIAN", content=RAW_BODIES[label])
    assert (response.status_code, _err(response)["code"]) == (403, "HTTP_ERROR")
    _assert_json_safe_envelope(response, RAW_BODIES[label])
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
@pytest.mark.parametrize("label", sorted(RAW_BODIES))
@pytest.mark.parametrize("request_id", [None, "not-a-uuid"])
async def test_raw_body_b_bad_request_id_and_malformed_is_request_id_required(endpoint, label, request_id) -> None:
    repo = SpyRepository()
    method, path = ("PATCH", _patch_path()) if endpoint == "patch" else ("POST", _recon_path())
    response = await _http(method, path, repo=repo, role="MAINTENANCE_MANAGER", request_id=request_id, content=RAW_BODIES[label])
    assert (response.status_code, _err(response)["code"]) == (422, "REQUEST_ID_REQUIRED")
    _assert_json_safe_envelope(response, RAW_BODIES[label])
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["patch", "reconcile"])
@pytest.mark.parametrize("label", sorted(RAW_BODIES))
async def test_raw_body_c_valid_id_malformed_json_is_validation_error(endpoint, label) -> None:
    repo = SpyRepository()
    method, path = ("PATCH", _patch_path()) if endpoint == "patch" else ("POST", _recon_path())
    response = await _http(method, path, repo=repo, role="MAINTENANCE_MANAGER", content=RAW_BODIES[label])
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    assert _err(response)["request_id"] == response.sent_request_id
    _assert_json_safe_envelope(response, RAW_BODIES[label])
    assert repo.calls == []


SCHEMA_INVALID = {
    "patch": [
        b"[]", b'"text"', b"null", b"42",
        b'{"registration_no": 5, "registration_province_code": null, "expected_registration_no": null, "expected_registration_province_code": null}',
        b'{"registration_no": "a"}',
        b'{"registration_no": "a", "registration_province_code": null, "expected_registration_no": null, "expected_registration_province_code": null, "extra": "SECRET-RAW-VALUE"}',
    ],
    "reconcile": [
        b"[]",
        b'{"mode": "APPLY_RECORDED", "expected_registration_no": null, "expected_registration_province_code": null, "reason_th": "r"}',
        b'{"mode": "APPLY_RECORDED", "expected_registration_no": null, "expected_registration_province_code": null, "expected_history_revision": 1, "reason_th": "r"}',
        b'{"mode": "APPLY_RECORDED", "expected_registration_no": null, "expected_registration_province_code": null, "expected_history_revision": "x", "reason_th": "r", "extra": "SECRET-RAW-VALUE"}',
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,content", [(e, c) for e, cs in SCHEMA_INVALID.items() for c in cs])
async def test_raw_body_d_f_schema_invalid_or_extra_keys_are_validation_error(endpoint, content) -> None:
    repo = SpyRepository()
    method, path = ("PATCH", _patch_path()) if endpoint == "patch" else ("POST", _recon_path())
    response = await _http(method, path, repo=repo, role="MAINTENANCE_MANAGER", content=content)
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    _assert_json_safe_envelope(response, content)
    assert "SECRET-RAW-VALUE" not in response.text  # E: no input values echoed
    if b'"extra"' in content:  # F: the unknown key is named and refused
        assert any(e["type"] == "extra_forbidden" for e in _err(response)["details"]["errors"])
    assert repo.calls == []
