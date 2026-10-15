"""R2 Batch R2f-h4 B2 — scope-aware technician list / detail (C1 Amendment
A1-§15, owner decision O4) and the synthetic mock TEST fixtures. Mock / service
level; every row is SYNTHETIC.

- REAL: REAL rows only. TEST: TEST rows of exactly the server batch only.
  Unconfigured (or TEST without a batch): 503 before any repository read.
- Scope is server-derived; no query parameter selects it.
- Authorization (`can_view`, 403 before reads), paging, sorting, response shape
  and identity-integrity fail-closed are unchanged (integrity is evaluated over
  the returned scope).
- The mock seed carries two linked TEST Personnel / Technician / Account chains of
  the mock batch that pass the existing BOTH-ACTIVE gate and resolve V2 My Work.

Governance list: R2FH4B2-REAL, -TEST, -BATCH, -CTX, -AUTH, -INT, -PAGE, -PARAM,
-FIX (fixtures and gates), -COMPAT.
"""
from __future__ import annotations

import uuid

import pytest

from app.config import Settings
from app.domain.common import PageParams
from app.domain.personnel_relationship import same_scope
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.technician import TechnicianService, in_server_scope
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST
from app.repositories.mock.repository import MockRepository
from tests.test_relationship_read_batch_r2f_a import RelSpy, tech
from tests.test_technician_assignment_batch_r2f_h1 import assign, body, new_pm, new_repair

API = "/api/v1"
MOCK = dict(scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)
OTHER = dict(scope=REFERENCE_SCOPE_TEST, batch="SYN-OTHER-BATCH")
REAL_SETTINGS = Settings(data_repository="google_sheets", registry_data_context="REAL")
UNCONFIGURED = Settings(data_repository="google_sheets")
TEST_NO_BATCH = Settings(data_repository="google_sheets", registry_data_context="TEST")


def rows():
    return [tech("TEC-R-2"), tech("TEC-R-1"), tech("TEC-T-2", **MOCK), tech("TEC-T-1", **MOCK),
            tech("TEC-O-1", **OTHER)]


async def call(path: str, repo, *, settings: Settings | None = None, role: str = "MAINTENANCE",
               user: str | None = None):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    headers = {"X-Dev-Role": role}
    if user is not None:
        headers["X-Dev-User-Id"] = user
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [i["technician_id"] for i in response.json()["items"]]


def code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# ---------------------------------------------------------------------------
# REAL / TEST / other batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh4b2_real_01_real_lists_and_details_real_rows_only() -> None:
    repo = RelSpy(technicians=rows())
    assert ids(await call(f"{API}/technicians", repo, settings=REAL_SETTINGS)) == ["TEC-R-1", "TEC-R-2"]
    assert (await call(f"{API}/technicians/TEC-R-1", repo, settings=REAL_SETTINGS)).json()["technician_id"] == "TEC-R-1"
    for tid in ("TEC-T-1", "TEC-O-1"):
        assert code(await call(f"{API}/technicians/{tid}", repo, settings=REAL_SETTINGS)) == (404, "TECHNICIAN_NOT_FOUND")


@pytest.mark.asyncio
async def test_r2fh4b2_test_01_test_lists_and_details_server_batch_test_rows_only() -> None:
    repo = RelSpy(technicians=rows())
    assert ids(await call(f"{API}/technicians", repo)) == ["TEC-T-1", "TEC-T-2"]  # mock = TEST + mock batch
    detail = await call(f"{API}/technicians/TEC-T-1", repo)
    assert detail.status_code == 200 and detail.json()["technician_id"] == "TEC-T-1"
    for tid in ("TEC-R-1", "TEC-O-1"):  # REAL and other-batch rows never visible in TEST
        assert code(await call(f"{API}/technicians/{tid}", repo)) == (404, "TECHNICIAN_NOT_FOUND")


@pytest.mark.asyncio
async def test_r2fh4b2_batch_01_another_test_batch_is_never_visible() -> None:
    repo = RelSpy(technicians=[tech("TEC-O-1", **OTHER), tech("TEC-O-2", **OTHER)])
    response = await call(f"{API}/technicians", repo)
    assert ids(response) == [] and response.json()["total_items"] == 0
    service = TechnicianService(repo, "TEST", "SYN-OTHER-BATCH")
    assert [t.technician_id for t in (await service.list_technicians(PageParams(page=1, page_size=20))).items] \
        == ["TEC-O-1", "TEC-O-2"]  # the same rows ARE visible to their own batch


def test_r2fh4b2_batch_02_scope_rule_is_identical_to_the_relationship_rule() -> None:
    for row in (tech("A"), tech("A", **MOCK), tech("A", **OTHER), tech("A", scope=REFERENCE_SCOPE_TEST, batch="")):
        for context, batch in (("REAL", ""), ("REAL", MOCK_TEST_BATCH_ID), ("TEST", MOCK_TEST_BATCH_ID),
                               ("TEST", "SYN-OTHER-BATCH")):
            assert in_server_scope(row, context, batch) == same_scope(row, context, batch)
    assert REFERENCE_SCOPE_REAL != REFERENCE_SCOPE_TEST


# ---------------------------------------------------------------------------
# Context and authorization, both before any read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [UNCONFIGURED, TEST_NO_BATCH])
@pytest.mark.parametrize("path", ["technicians", "technicians/TEC-T-1"])
async def test_r2fh4b2_ctx_01_unconfigured_is_503_before_any_read(settings, path) -> None:
    repo = RelSpy(technicians=rows())
    repo.calls.clear()
    assert code(await call(f"{API}/{path}", repo, settings=settings)) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.calls == []
    for context, batch in ((None, ""), ("TEST", "")):
        with pytest.raises(ApiError) as exc:
            await TechnicianService(repo, context, batch).list_technicians(PageParams(page=1, page_size=20))
        assert exc.value.code == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["technicians", "technicians/TEC-T-1"])
async def test_r2fh4b2_auth_01_capability_is_checked_before_context_and_reads(path) -> None:
    repo = RelSpy(technicians=rows())
    repo.calls.clear()
    for settings in (None, UNCONFIGURED):
        assert (await call(f"{API}/{path}", repo, settings=settings, role="NO_SUCH_ROLE")).status_code == 403
    assert repo.calls == []
    for role in ("TECHNICIAN", "DRIVER", "MAINTENANCE", "MAINTENANCE_MANAGER", "ADMIN"):  # can_view unchanged
        assert (await call(f"{API}/{path}", repo, role=role)).status_code == 200, role


# ---------------------------------------------------------------------------
# Identity integrity, paging, sorting, no client scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh4b2_int_01_integrity_fails_closed_over_the_returned_scope() -> None:
    dup = RelSpy(technicians=[tech("TEC-T-1", **MOCK), tech("TEC-T-1", **MOCK), tech("TEC-R-1")])
    response = await call(f"{API}/technicians", dup)
    assert code(response) == (500, "TECHNICIAN_MASTER_DATA_INVALID")
    assert response.json()["error"]["details"]["issues"] == {"DUPLICATE_TECHNICIAN_ID": 2}
    assert "TEC-T-1" not in response.text  # counts only
    assert code(await call(f"{API}/technicians/TEC-T-1", dup)) == (409, "TECHNICIAN_ID_AMBIGUOUS")
    # Defects confined to another scope never block this scope (the list shows only its own scope).
    other = RelSpy(technicians=[tech("TEC-T-1", **MOCK), tech("TEC-R-1"), tech("TEC-R-1"), tech("", first="x")])
    assert ids(await call(f"{API}/technicians", other)) == ["TEC-T-1"]
    assert code(await call(f"{API}/technicians", other, settings=REAL_SETTINGS)) == (500, "TECHNICIAN_MASTER_DATA_INVALID")


@pytest.mark.asyncio
async def test_r2fh4b2_page_01_paging_and_sorting_are_unchanged() -> None:
    repo = RelSpy(technicians=[tech(f"TEC-T-{n}", **MOCK) for n in (5, 3, 1, 4, 2)] + [tech("TEC-R-0")])
    first = await call(f"{API}/technicians?page=1&page_size=2", repo)
    second = await call(f"{API}/technicians?page=2&page_size=2", repo)
    third = await call(f"{API}/technicians?page=3&page_size=2", repo)
    assert (ids(first), ids(second), ids(third)) == (["TEC-T-1", "TEC-T-2"], ["TEC-T-3", "TEC-T-4"], ["TEC-T-5"])
    assert {k: first.json()[k] for k in ("page", "page_size", "total_items")} == {
        "page": 1, "page_size": 2, "total_items": 5}
    (item, _) = first.json()["items"]
    assert set(item) == {"technician_id", "first_name", "last_name", "active_status"}
    for bad in ("page=0", "page_size=0", "page_size=201"):
        assert (await call(f"{API}/technicians?{bad}", repo)).status_code == 422


@pytest.mark.asyncio
async def test_r2fh4b2_param_01_no_client_selectable_scope() -> None:
    repo = RelSpy(technicians=rows())
    baseline = ids(await call(f"{API}/technicians", repo))
    for query in ("scope=REAL", "data_context=REAL", "context=REAL", "registry_data_context=REAL",
                  "test_batch_id=SYN-OTHER-BATCH", "is_test_data=FALSE", "scope=REAL&test_batch_id="):
        assert ids(await call(f"{API}/technicians?{query}", repo)) == baseline, query
        assert code(await call(f"{API}/technicians/TEC-R-1?{query}", repo)) == (404, "TECHNICIAN_NOT_FOUND"), query
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    for path in ("/api/v1/technicians", "/api/v1/technicians/{technician_id}"):
        names = {p["name"] for p in paths[path]["get"].get("parameters", [])}
        assert names <= {"page", "page_size", "technician_id"}, names


# ---------------------------------------------------------------------------
# Synthetic mock fixtures (O4): relationships, ACTIVE gates, V2 + My Work
# ---------------------------------------------------------------------------

LINKED = (("PER-TEST-911", "TEC-TEST-911", "USR-TEST-911"), ("PER-TEST-912", "TEC-TEST-912", "USR-TEST-912"))


@pytest.mark.asyncio
async def test_r2fh4b2_fix_01_seed_lists_only_the_mock_batch_technicians() -> None:
    repo = MockRepository()
    assert ids(await call(f"{API}/technicians", repo)) == ["TEC-TEST-901", "TEC-TEST-911", "TEC-TEST-912"]
    assert code(await call(f"{API}/technicians/TEC-TEST-001", repo)) == (404, "TECHNICIAN_NOT_FOUND")  # REAL fixture
    for pid, tid, uid in LINKED:
        person = next(p for p in repo._personnel_master if p["personnel_id"] == pid)
        assert (person["is_test_data"], person["test_batch_id"], person["active_status"]) == (
            "TRUE", MOCK_TEST_BATCH_ID, "ACTIVE")
        assert (person["technician_id"], person["user_id"]) == (tid, uid)


@pytest.mark.asyncio
async def test_r2fh4b2_fix_02_seed_chains_resolve_both_ways() -> None:
    repo = MockRepository()
    for pid, tid, uid in LINKED:
        rel = await call(f"{API}/personnel/{pid}/relationships", repo, role="ADMIN")
        assert rel.status_code == 200, rel.text
        assert rel.json()["technician"]["resolution"] == "RESOLVED"
        assert rel.json()["technician"]["technician"]["active_status"] == "ACTIVE"
        assert rel.json()["account"] == {"resolution": "RESOLVED", "user_id": uid}
        reverse = await call(f"{API}/technicians/{tid}/personnel", repo)
        assert reverse.json() == {"technician_id": tid, "resolution": "RESOLVED", "personnel_id": pid, "match_count": 1}


@pytest.mark.asyncio
async def test_r2fh4b2_fix_03_seed_chains_pass_the_both_active_gate_and_resolve_my_work() -> None:
    repo = MockRepository()
    repair_id, wo_id = await new_repair(repo), await new_pm(repo)  # mock TEST V2 jobs (h1 helpers, setting ON)
    for job_id, kind in ((repair_id, "REPAIR"), (wo_id, "PM")):
        from app.domain.technician_assignment import PM, REPAIR

        outcome = await assign(repo, job_id, body("TEC-TEST-911", "TEC-TEST-912"), kind=REPAIR if kind == "REPAIR"
                               else PM, request_id=str(uuid.uuid4()))
        assert outcome.changed and outcome.current.primary_technician_id == "TEC-TEST-911"
    for uid, role in (("USR-TEST-911", "PRIMARY"), ("USR-TEST-912", "COLLABORATOR")):
        response = await call(f"{API}/my-work", repo, role="TECHNICIAN", user=uid)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["resolution"] == "RESOLVED"
        assert {(i["work_type"], i["job_id"], i["assignment_role"]) for i in payload["items"]} == {
            ("REPAIR", repair_id, role), ("PM", wo_id, role)}


@pytest.mark.asyncio
async def test_r2fh4b2_fix_04_existing_seed_ids_and_behaviour_are_preserved() -> None:
    repo = MockRepository()
    assert [(t.values["technician_id"], t.scope) for t in repo._technician_master][:3] == [
        ("TEC-TEST-001", REFERENCE_SCOPE_REAL), ("TEC-TEST-002", REFERENCE_SCOPE_REAL),
        ("TEC-TEST-901", REFERENCE_SCOPE_TEST)]
    assert [p["personnel_id"] for p in repo._personnel_master][:4] == [
        "PER-TEST-001", "PER-TEST-002", "PER-TEST-003", "PER-TEST-901"]
    # TEC-TEST-901 stays unlinked (no seed Personnel holds it). R2-C2 Personnel Scope Option S
    # (deliberate evolution, S3): the R2c-1 personnel list follows the server scope — the mock
    # (TEST) context lists the mock batch's TEST personnel; the REAL-scope list is unchanged.
    assert (await call(f"{API}/technicians/TEC-TEST-901/personnel", repo)).json()["resolution"] == "UNSET"
    listed = await call(f"{API}/personnel", repo)
    assert listed.status_code == 200
    assert [p["personnel_id"] for p in listed.json()["items"]] == ["PER-TEST-911", "PER-TEST-912"]
    real = await call(f"{API}/personnel", repo, settings=REAL_SETTINGS)
    assert real.status_code == 200 and real.json()["total_items"] == 3


@pytest.mark.asyncio
async def test_r2fh4b2_compat_01_v2_reads_and_signals_are_unaffected() -> None:
    repo = MockRepository()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body("TEC-TEST-911"))
    read = await call(f"{API}/repairs/{repair_id}/technician-assignments", repo)
    assert read.status_code == 200 and read.json()["current"]["primary_technician_id"] == "TEC-TEST-911"
    assert (await call(f"{API}/repairs/{repair_id}", repo)).json()["repair"]["assignment_model"] == "TECHNICIAN_V2"
    assert (await call(f"{API}/me", repo)).json()["data_context"] == "TEST"
