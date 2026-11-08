"""R4 TASK-010 — final review corrections: Repair read isolation and Store source integrity.

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (Owner: Technician V2 only). The external
Repair reads — `GET /repairs`, the open-repair report (`GET /repairs/open-queue`) and
`GET /repairs/{id}` — return only Technician V2 work orders of the server's own TEST/REAL
scope (TEST context + TEST batch, or REAL), taken from server configuration only:

* the repository filters before ordering, counting and paging (one shared predicate,
  `in_v2_read_scope`, in Mock and Google Sheets);
* untrusted records (unknown model, blank / duplicated V2 id, unprovable V2 scope cells)
  fail the whole list closed (500, counts only) — never an empty or partial page;
* an unconfigured context is 503 before any record read;
* a detail of another scope, a Legacy job and a missing id are the same 404.

A Store request's asset must be its source work order's own asset (zero writes otherwise).
Every row is synthetic (Mock / fake Sheets transport). Mock pass is not PostgreSQL proof.
"""
from __future__ import annotations

import copy

import pytest

from app.domain import authz
from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.material_request_service import (
    MaterialRequestService,
    RequisitionLineInput,
)
from app.domain.meter_service import MeterService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.repair import RepairStatus
from app.domain.repair_service import RepairService
from app.domain.requisition import RequisitionSourceType
from app.domain.technician_assignment import AssignmentCutover
from app.errors import ApiError
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    T1,
    U1,
    assign,
    body,
    ctx,
    cut,
    http,
    new_pm,
    new_repair,
    repo_with,
)

BATCH_A = MOCK_TEST_BATCH_ID          # the server batch of every Mock / `http` request
BATCH_B = "SYN-OTHER-TEST-BATCH"
SCOPE_A = ("TECHNICIAN_V2", "TRUE", BATCH_A)
SCOPE_B = ("TECHNICIAN_V2", "TRUE", BATCH_B)
SCOPE_REAL = ("TECHNICIAN_V2", "FALSE", "")
LEGACY = ("", "", "")
_IGNORED_STATE = {"calls", "fail", "_depth"}
# An authenticated reader holding the approved read permission (R3 authorization correction).
READER = ctx("USR-SYN-READER", authz.CAN_VIEW)


def state(repo) -> dict:
    snapshot = {}
    for name, value in vars(repo).items():
        if name in _IGNORED_STATE or not isinstance(value, (dict, list)):
            continue
        try:
            snapshot[name] = copy.deepcopy(value)
        except TypeError:
            continue
    return snapshot


def service(repo, *, context: str | None = "TEST", batch: str = BATCH_A) -> RepairService:
    cutover = AssignmentCutover() if context is None else cut(context=context, batch=batch)
    return RepairService(repo, MeterService(repo), assignment_cutover=cutover)


async def repair_in(repo, scope: tuple[str, str, str], **update) -> str:
    repair_id = await new_repair(repo)
    model, flag, batch = scope
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(
        update={"assignment_model": model, "is_test_data": flag, "test_batch_id": batch, **update})
    return repair_id


async def three_scopes(repo) -> dict[str, str]:
    return {"A": await repair_in(repo, SCOPE_A), "B": await repair_in(repo, SCOPE_B),
            "REAL": await repair_in(repo, SCOPE_REAL), "LEGACY": await repair_in(repo, LEGACY)}


async def listed(svc: RepairService, **filters) -> tuple[list[str], int]:
    page = await svc.list_repairs_for_reader(READER, filters.get("asset_type"), filters.get("asset_id"),
                                             filters.get("status"), PageParams(page=1, page_size=200))
    return [i.repair_id for i in page.items], page.total_items


async def reported(svc: RepairService) -> tuple[list[str], int]:
    page = await svc.list_open_repairs_for_report(None, PageParams(page=1, page_size=200))
    return [i.repair_id for i in page.items], page.total_items


async def refusal(coro) -> tuple[int, str, object]:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.status_code, exc.value.code, exc.value.details


# ---------------------------------------------------------------------------
# Scope matrix: TEST batch A / TEST batch B / REAL / Legacy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_server_scope_lists_reports_and_reads_only_its_own_v2_repairs() -> None:
    repo = repo_with()
    ids = await three_scopes(repo)
    cases = {"A": service(repo), "B": service(repo, batch=BATCH_B), "REAL": service(repo, context="REAL", batch="")}
    for own, svc in cases.items():
        assert await listed(svc) == ([ids[own]], 1), own
        assert await reported(svc) == ([ids[own]], 1), own
        assert (await svc.get_repair_for_reader(ids[own], READER)).repair.repair_id == ids[own]
        for other in ("A", "B", "REAL", "LEGACY"):
            if other != own:  # another scope or Legacy: the same 404 as a missing id, no content
                assert await refusal(svc.get_repair_for_reader(ids[other], READER)) == (404, "REPAIR_NOT_FOUND", None)
        assert await refusal(svc.get_repair_for_reader("RPR-DOES-NOT-EXIST", READER)) == (404, "REPAIR_NOT_FOUND", None)


@pytest.mark.asyncio
async def test_http_list_report_and_detail_never_disclose_another_scope_or_legacy_rows() -> None:
    repo = repo_with()
    ids = await three_scopes(repo)
    stranger = repo._repairs[ids["B"]]
    repo._repairs[ids["B"]] = stranger.model_copy(update={"symptom": "SECRET-OTHER-SCOPE", "primary_technician": "x-b"})
    repo._repairs[ids["LEGACY"]] = repo._repairs[ids["LEGACY"]].model_copy(
        update={"symptom": "SECRET-LEGACY", "primary_technician": "legacy-user-a"})
    before = state(repo)
    for path in (f"{API}/repairs", f"{API}/repairs?status=OPEN", f"{API}/repairs/open-queue"):
        response = await http("GET", path, repo, request_id=None)
        assert response.status_code == 200, response.text
        assert [i["repair_id"] for i in response.json()["items"]] == [ids["A"]]
        assert response.json()["total_items"] == 1
        assert "SECRET" not in response.text and "legacy-user-a" not in response.text
    for other in ("B", "REAL", "LEGACY"):
        response = await http("GET", f"{API}/repairs/{ids[other]}", repo, request_id=None)
        missing = await http("GET", f"{API}/repairs/RPR-DOES-NOT-EXIST", repo, request_id=None)
        assert response.status_code == missing.status_code == 404
        assert response.json()["error"]["code"] == missing.json()["error"]["code"] == "REPAIR_NOT_FOUND"
        assert "SECRET" not in response.text and ids[other] in response.text  # only the requested id echoes
    assert state(repo) == before  # every GET above wrote nothing


# ---------------------------------------------------------------------------
# Untrusted records and an unconfigured context fail closed (never an empty page)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("damage, expected", [
    ({"assignment_model": "technician_v2"}, (500, "ASSIGNMENT_MODEL_DATA_INVALID", {"issues": {"ASSIGNMENT_MODEL_UNKNOWN": 1}})),
    ({"is_test_data": "yes"}, (500, "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", {"issues": {"JOB_SCOPE_FLAG_INVALID": 1}})),
    ({"is_test_data": "FALSE", "test_batch_id": "B"}, (500, "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID",
                                                      {"issues": {"JOB_SCOPE_FLAG_INVALID": 1}})),
])
async def test_one_untrusted_record_fails_the_whole_list_and_report_closed(damage, expected) -> None:
    repo = repo_with()
    good = await repair_in(repo, SCOPE_A)
    await repair_in(repo, SCOPE_A, **damage)
    svc = service(repo)
    assert await refusal(svc.list_repairs_for_reader(READER, None, None, None, PageParams())) == expected
    assert await refusal(svc.list_open_repairs_for_report(None, PageParams())) == expected
    response = await http("GET", f"{API}/repairs", repo, request_id=None)
    assert response.status_code == 500 and "items" not in response.json() and "total_items" not in response.text
    assert good not in response.text  # no partial records


@pytest.mark.asyncio
async def test_untrusted_detail_fails_closed_and_unknown_model_is_never_returned() -> None:
    repo = repo_with()
    bad_flag = await repair_in(repo, ("TECHNICIAN_V2", "maybe", BATCH_A), symptom="SECRET")
    bad_model = await repair_in(repo, ("V2", "TRUE", BATCH_A), symptom="SECRET")
    svc = service(repo)
    status, code, _ = await refusal(svc.get_repair_for_reader(bad_flag, READER))
    assert (status, code) == (500, "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID")
    status, code, _ = await refusal(svc.get_repair_for_reader(bad_model, READER))
    assert (status, code) == (500, "ASSIGNMENT_MODEL_DATA_INVALID")
    for repair_id in (bad_flag, bad_model):
        response = await http("GET", f"{API}/repairs/{repair_id}", repo, request_id=None)
        assert response.status_code == 500 and "SECRET" not in response.text


@pytest.mark.asyncio
async def test_an_unconfigured_context_is_503_before_any_record_read() -> None:
    repo = repo_with()
    repair_id = await repair_in(repo, SCOPE_A)
    svc = service(repo, context=None)
    repo.calls.clear()
    for coro in (svc.list_repairs_for_reader(READER, None, None, None, PageParams()),
                 svc.list_open_repairs_for_report(None, PageParams()),
                 svc.get_repair_for_reader(repair_id, READER)):
        status, _code, _ = await refusal(coro)
        assert status == 503
    assert not [name for name in repo.calls if name.startswith(("get_repair", "list_", "read_work_order"))]


# ---------------------------------------------------------------------------
# Filtering happens before ordering, counting and paging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_more_than_one_page_keeps_exact_totals_disjoint_pages_order_and_filters() -> None:
    repo = repo_with()
    own = [await repair_in(repo, SCOPE_A) for _ in range(23)]
    for scope in (SCOPE_B, SCOPE_REAL, LEGACY):
        for _ in range(9):
            await repair_in(repo, scope)
    closed = own[:5]
    for repair_id in closed:
        repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(update={"status": RepairStatus.CLOSED})
    svc = service(repo)
    seen, totals, page = [], set(), 1
    while True:
        result = await svc.list_repairs_for_reader(READER, None, None, None, PageParams(page=page, page_size=10))
        totals.add(result.total_items)
        if not result.items:
            break
        seen.extend(result.items)
        page += 1
    assert totals == {23} and page == 4  # 10 + 10 + 3, then an empty beyond-the-end page with the same total
    assert sorted(i.repair_id for i in seen) == sorted(own) and len({i.repair_id for i in seen}) == 23
    keys = [(i.opened_at, i.repair_id) for i in seen]
    assert keys == sorted(keys, reverse=True)
    open_page = await svc.list_repairs_for_reader(READER, None, None, RepairStatus.OPEN, PageParams(page=2, page_size=10))
    assert open_page.total_items == 18 and len(open_page.items) == 8
    report = await svc.list_open_repairs_for_report(None, PageParams(page=1, page_size=200))
    assert report.total_items == 18 and {i.repair_id for i in report.items} == set(own) - set(closed)
    by_asset = await svc.list_repairs_for_reader(READER, AssetType.VEHICLE, "VEH-1046", None, PageParams(page=1, page_size=5))
    assert by_asset.total_items == 23 and len(by_asset.items) == 5


@pytest.mark.asyncio
async def test_scoped_list_over_the_sheets_transport_matches_mock_rules() -> None:
    from tests.test_open_repair_report_sheets_batch7c2 import _backend, _repo, _row

    rows = [_row("SYN-RPR-A1"), _row("SYN-RPR-A2", status="CLOSED"),
            _row("SYN-RPR-B1", v2_cells=list(SCOPE_B)), _row("SYN-RPR-R1", v2_cells=list(SCOPE_REAL)),
            _row("SYN-RPR-L1", v2_cells=list(LEGACY))]
    repo = _repo(_backend(rows))
    svc = RepairService(repo, MeterService(repo), assignment_cutover=cut())
    page = await svc.list_repairs_for_reader(READER, None, None, None, PageParams())
    assert sorted(i.repair_id for i in page.items) == ["SYN-RPR-A1", "SYN-RPR-A2"] and page.total_items == 2
    report = await svc.list_open_repairs_for_report(None, PageParams())
    assert [i.repair_id for i in report.items] == ["SYN-RPR-A1"] and report.total_items == 1
    real = RepairService(repo, MeterService(repo), assignment_cutover=cut(context="REAL", batch=""))
    assert [i.repair_id for i in (await real.list_repairs_for_reader(READER, None, None, None, PageParams())).items] == [
        "SYN-RPR-R1"]
    # The unscoped repository read (internal callers) is unchanged.
    assert (await repo.list_repairs(None, None, None, PageParams()))[1] == 5


@pytest.mark.asyncio
async def test_valid_v2_repairs_stay_usable_and_operations_are_unchanged() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)  # a normal in-scope V2 job
    await assign(repo, repair_id, body(T1))
    detail = await http("GET", f"{API}/repairs/{repair_id}", repo, role="TECHNICIAN", user=U1, request_id=None)
    assert detail.status_code == 200 and detail.json()["repair"]["repair_id"] == repair_id
    action = await http("POST", f"{API}/repairs/{repair_id}/actions", repo, role="TECHNICIAN", user=U1,
                        json={"action_text": "ตรวจสอบ"})
    assert action.status_code == 200, action.text
    closed = await http("POST", f"{API}/repairs/{repair_id}/close", repo, json={})
    assert closed.status_code == 200 and closed.json()["repair"]["status"] == "CLOSED"
    listed_after = await http("GET", f"{API}/repairs", repo, request_id=None)
    assert [i["repair_id"] for i in listed_after.json()["items"]] == [repair_id]


# ---------------------------------------------------------------------------
# Store source asset integrity
# ---------------------------------------------------------------------------


async def store(repo, source: RequisitionSourceType, job_id: str, asset_type: AssetType, asset_id: str):
    return await MaterialRequestService(repo, cut()).create(
        source_type=source, source_work_order_id=job_id, asset_type=asset_type, asset_id=asset_id,
        lines=[RequisitionLineInput(part_description="อะไหล่ทดสอบ (synthetic)", quantity=1, unit="ชิ้น")],
        created_by="dev-user")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [RequisitionSourceType.PM, RequisitionSourceType.REPAIR])
@pytest.mark.parametrize("asset", [(AssetType.VEHICLE, "VEH-1047"), (AssetType.EQUIPMENT, "EQP-0001")])
async def test_a_store_request_for_another_asset_than_its_source_is_refused_with_zero_writes(source, asset) -> None:
    repo = repo_with()
    job_id = await (new_pm(repo) if source == RequisitionSourceType.PM else new_repair(repo))  # on VEH-1046
    before = state(repo)
    status, code, details = await refusal(store(repo, source, job_id, *asset))
    assert (status, code) == (409, "MATERIAL_REQUEST_SOURCE_ASSET_MISMATCH")
    assert details == {"source_work_order_id": job_id} and "VEH-1046" not in str(details)
    assert state(repo) == before  # no header, line, stock or audit record
    response = await http("POST", f"{API}/material-requests", repo, json={
        "source_type": source.value, "source_work_order_id": job_id, "asset_type": asset[0].value,
        "asset_id": asset[1], "lines": [{"part_description": "ไส้กรอง", "quantity": 1}]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "MATERIAL_REQUEST_SOURCE_ASSET_MISMATCH"
    assert state(repo) == before


@pytest.mark.asyncio
async def test_store_requests_for_the_sources_own_asset_still_work() -> None:
    repo = repo_with()
    pm_id, repair_id = await new_pm(repo), await new_repair(repo)
    for source, job_id in ((RequisitionSourceType.PM, pm_id), (RequisitionSourceType.REPAIR, repair_id)):
        created = await store(repo, source, job_id, AssetType.VEHICLE, "VEH-1046")
        assert created.request.source_work_order_id == job_id and created.request.vehicle_id == "VEH-1046"
        assert len(created.lines) == 1
