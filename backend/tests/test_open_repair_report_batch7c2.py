"""Phase 7 Batch 7C2 — open-repair report ("งานซ่อมค้าง",
GET /api/v1/repairs/open-queue): service error mapping, mock-repository
parity with the legacy OPEN list, pagination over a fixed 250-record
dataset, asset-type filtering, shared (opened_at, repair_id) ordering,
legacy-route compatibility, authorization (current dev-auth behavior only
— production authentication is NOT implemented and not claimed) and
zero-write checks. The Google Sheets structural read is covered in
test_open_repair_report_sheets_batch7c2.py.
All fixtures are synthetic (SYN-* ids), not company fleet data.
"""
from __future__ import annotations

import copy
import inspect
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.asset import AssetType
from app.domain.assignment import AssignmentRole, RepairAssignmentHistoryEntry
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import Repair, RepairAction, RepairSourceType, RepairStatus
from app.domain.repair_service import RepairService
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError
from app.repositories.mock import MockRepository

URL = "/api/v1/repairs/open-queue"
BASE = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)

# Repository method-name prefixes that would change stored state.
_WRITE_PREFIXES = (
    "create_", "add_", "assign_", "close_", "update_", "mark_", "append_",
    "record_", "end_", "set_", "delete_", "change_", "install_", "remove_",
    "upsert_", "save_", "acknowledge_", "mute_", "resolve_", "submit_", "convert_",
)


def _repair(
    rid: str,
    status: RepairStatus = RepairStatus.OPEN,
    asset_type: AssetType = AssetType.VEHICLE,
    asset_id: str = "SYN-VEH-1",
    opened_at: datetime = BASE,
    primary: str | None = None,
    symptom: str | None = "synthetic",
) -> Repair:
    return Repair(
        repair_id=rid,
        asset_type=asset_type,
        asset_id=asset_id,
        source_type=RepairSourceType.MANUAL,
        status=status,
        opened_at=opened_at,
        primary_technician=primary,
        symptom=symptom,
    )


class _SpyRepository(MockRepository):
    """Mock repository that records every public coroutine call."""

    def __init__(self, repairs: list[Repair] | None = None) -> None:
        super().__init__()
        self.calls: list[str] = []
        for r in repairs or []:
            self._repairs[r.repair_id] = r
            self._repair_actions[r.repair_id] = []

    def __getattribute__(self, name: str):
        attr = super().__getattribute__(name)
        if not name.startswith("_") and inspect.iscoroutinefunction(attr):
            calls = super().__getattribute__("calls")

            async def wrapper(*args, **kwargs):
                calls.append(name)
                return await attr(*args, **kwargs)

            return wrapper
        return attr

    def writes(self) -> list[str]:
        return [c for c in self.calls if c.startswith(_WRITE_PREFIXES)]


class _FailingRepository(_SpyRepository):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    async def list_open_repairs_for_report(self, asset_type, params):
        raise self._exc


def _service(repo) -> RepairService:
    return RepairService(repo, MeterService(repo))


def _dataset_250() -> list[Repair]:
    """250 unique OPEN ids; opened_at repeats in groups of 7 (ties), plus
    CLOSED records that must never appear."""
    repairs = [
        _repair(
            f"SYN-RPR-{i:04d}",
            asset_type=AssetType.EQUIPMENT if i % 4 == 0 else AssetType.VEHICLE,
            asset_id=f"SYN-EQP-{i % 3}" if i % 4 == 0 else f"SYN-VEH-{i % 5}",
            opened_at=BASE + timedelta(minutes=i // 7),
        )
        for i in range(250)
    ]
    repairs += [
        _repair(f"SYN-RPR-C{i:03d}", status=RepairStatus.CLOSED, opened_at=BASE + timedelta(days=1))
        for i in range(12)
    ]
    return repairs


async def _all_pages(service: RepairService, asset_type=None, page_size=50):
    pages = []
    page = 1
    while True:
        result = await service.list_open_repairs_for_report(asset_type, PageParams(page=page, page_size=page_size))
        if not result.items:
            return pages, result.total_items
        pages.append(result.items)
        page += 1


# ---------------------------------------------------------------------------
# Service: parity, population, pagination, ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", [None, AssetType.VEHICLE, AssetType.EQUIPMENT])
async def test_report_equals_legacy_open_list_exactly(asset_type) -> None:
    repo = _SpyRepository(_dataset_250())
    service = _service(repo)
    report = await service.list_open_repairs_for_report(asset_type, PageParams(page=1, page_size=200))
    legacy = await service.list_repairs(asset_type, None, RepairStatus.OPEN, PageParams(page=1, page_size=200))
    assert report.items == legacy.items
    assert report.total_items == legacy.total_items
    expected = 250 if asset_type is None else len([i for i in range(250) if (i % 4 == 0) == (asset_type == AssetType.EQUIPMENT)])
    assert report.total_items == expected
    assert all(item.status == RepairStatus.OPEN for item in report.items)
    if asset_type is not None:
        assert all(item.asset_type == asset_type for item in report.items)


@pytest.mark.asyncio
async def test_250_records_page_size_50_gives_five_disjoint_pages_covering_all() -> None:
    service = _service(_SpyRepository(_dataset_250()))
    pages, total = await _all_pages(service, page_size=50)
    assert total == 250
    assert [len(p) for p in pages] == [50, 50, 50, 50, 50]
    ids = [item.repair_id for p in pages for item in p]
    assert len(ids) == len(set(ids)) == 250
    assert set(ids) == {f"SYN-RPR-{i:04d}" for i in range(250)}
    # Descending (opened_at, repair_id) across page boundaries, ties included.
    keys = [(item.opened_at, item.repair_id) for p in pages for item in p]
    assert keys == sorted(keys, reverse=True)
    assert len({item.opened_at for p in pages for item in p}) < 250  # ties present


@pytest.mark.asyncio
async def test_250_records_page_size_200_and_beyond_end_keeps_total() -> None:
    service = _service(_SpyRepository(_dataset_250()))
    first = await service.list_open_repairs_for_report(None, PageParams(page=1, page_size=200))
    second = await service.list_open_repairs_for_report(None, PageParams(page=2, page_size=200))
    beyond = await service.list_open_repairs_for_report(None, PageParams(page=6, page_size=50))
    assert (len(first.items), len(second.items)) == (200, 50)
    assert {i.repair_id for i in first.items}.isdisjoint({i.repair_id for i in second.items})
    assert first.total_items == second.total_items == 250
    assert beyond.items == [] and beyond.total_items == 250 and beyond.page == 6


@pytest.mark.asyncio
async def test_equal_timestamps_are_ordered_by_repair_id_string_descending() -> None:
    repairs = [_repair(rid) for rid in ("SYN-RPR-2", "SYN-RPR-10", "SYN-RPR-1")]
    repairs.append(_repair("SYN-RPR-0", opened_at=BASE + timedelta(seconds=1)))
    service = _service(_SpyRepository(repairs))
    report = await service.list_open_repairs_for_report(None, PageParams())
    # String order, not numeric: "SYN-RPR-2" > "SYN-RPR-10" > "SYN-RPR-1".
    assert [i.repair_id for i in report.items] == ["SYN-RPR-0", "SYN-RPR-2", "SYN-RPR-10", "SYN-RPR-1"]
    legacy = await service.list_repairs(None, None, None, PageParams())
    assert [i.repair_id for i in legacy.items] == ["SYN-RPR-0", "SYN-RPR-2", "SYN-RPR-10", "SYN-RPR-1"]


@pytest.mark.asyncio
async def test_action_count_is_preserved_in_the_report() -> None:
    repo = _SpyRepository([_repair("SYN-RPR-1"), _repair("SYN-RPR-2")])
    repo._repair_actions["SYN-RPR-1"] = [
        RepairAction(repair_action_id=f"SYN-ACT-{n}", repair_id="SYN-RPR-1", action_text="x", created_at=BASE)
        for n in range(3)
    ]
    report = await _service(repo).list_open_repairs_for_report(None, PageParams())
    assert {i.repair_id: i.action_count for i in report.items} == {"SYN-RPR-1": 3, "SYN-RPR-2": 0}


@pytest.mark.asyncio
async def test_mixed_naive_and_aware_timestamps_keep_existing_failure() -> None:
    repairs = [_repair("SYN-RPR-1"), _repair("SYN-RPR-2", opened_at=datetime(2026, 1, 15, 9, 0))]
    service = _service(_SpyRepository(repairs))
    with pytest.raises(TypeError):
        await service.list_open_repairs_for_report(None, PageParams())
    with pytest.raises(TypeError):
        await service.list_repairs(None, None, RepairStatus.OPEN, PageParams())


@pytest.mark.asyncio
async def test_report_reads_once_and_never_writes_and_mock_state_is_unchanged() -> None:
    repo = _SpyRepository(_dataset_250())
    before = copy.deepcopy({k: v for k, v in vars(repo).items() if k != "calls"})
    service = _service(repo)
    for asset_type in (None, AssetType.VEHICLE, AssetType.EQUIPMENT):
        for page in (1, 2, 99):
            await service.list_open_repairs_for_report(asset_type, PageParams(page=page, page_size=50))
    assert set(repo.calls) == {"list_open_repairs_for_report", "list_repairs"}
    assert repo.writes() == []
    assert {k: v for k, v in vars(repo).items() if k != "calls"} == before


# ---------------------------------------------------------------------------
# Service error mapping
# ---------------------------------------------------------------------------


async def _service_error(exc: Exception) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _service(_FailingRepository(exc)).list_open_repairs_for_report(None, PageParams())
    return info.value


@pytest.mark.asyncio
async def test_schema_error_maps_to_500_before_the_generic_repository_error() -> None:
    err = await _service_error(RepositorySchemaError("repair_order", "MISSING_HEADERS", ("status",)))
    assert (err.code, err.status_code) == ("REPAIR_ORDER_SCHEMA_INVALID", 500)
    assert err.details == {"tab": "repair_order", "problem": "MISSING_HEADERS", "headers": ["status"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["TAB_MISSING", "NO_HEADER_ROW", "DUPLICATE_HEADERS", "DATA_OUTSIDE_HEADER"])
async def test_every_structural_problem_is_reported_verbatim(problem: str) -> None:
    err = await _service_error(RepositorySchemaError("repair_order", problem))
    assert err.details == {"tab": "repair_order", "problem": problem, "headers": []}


@pytest.mark.asyncio
async def test_other_repository_error_maps_to_503_without_details_or_leak() -> None:
    err = await _service_error(RepositoryError("Google Sheets reading rows from 'repair_action' failed: secret-ish"))
    assert (err.code, err.status_code) == ("REPAIR_ORDER_READ_FAILED", 503)
    assert err.details is None
    assert "secret-ish" not in err.message


@pytest.mark.asyncio
async def test_mapping_errors_are_not_converted_into_repository_errors() -> None:
    with pytest.raises(ValueError):
        await _service(_FailingRepository(ValueError("'Open' is not a valid RepairStatus"))).list_open_repairs_for_report(
            None, PageParams()
        )


# ---------------------------------------------------------------------------
# API contract, authorization and compatibility
# ---------------------------------------------------------------------------


@contextmanager
def _env(**values: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@asynccontextmanager
async def _client(repo=None) -> AsyncIterator[AsyncClient]:
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    try:
        # raise_app_exceptions=False: observe the app's own generic 500
        # handler response instead of httpx re-raising the exception.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _as(role: str, user: str | None = None) -> dict[str, str]:
    headers = {"X-Dev-Role": role}
    if user:
        headers["X-Dev-User-Id"] = user
    return headers


async def _collect(client: AsyncClient, path: str, headers=None) -> tuple[list[dict], int]:
    items: list[dict] = []
    page = 1
    sep = "&" if "?" in path else "?"
    while True:
        body = (await client.get(f"{path}{sep}page={page}&page_size=200", headers=headers or {})).json()
        if not body["items"]:
            return items, body["total_items"]
        items += body["items"]
        page += 1


@pytest.mark.asyncio
async def test_api_defaults_shape_and_parity_with_legacy_route() -> None:
    async with _client(_SpyRepository(_dataset_250())) as client:
        response = await client.get(URL)
        assert response.status_code == 200
        body = response.json()
        assert list(body) == ["items", "page", "page_size", "total_items"]
        assert (body["page"], body["page_size"], body["total_items"], len(body["items"])) == (1, 50, 250, 50)
        assert set(body["items"][0]) == {
            "repair_id", "asset_type", "asset_id", "source_type", "source_id", "status",
            "opened_at", "closed_at", "action_count", "primary_technician", "collaborators", "symptom",
        }
        for asset_type in ("", "&asset_type=VEHICLE", "&asset_type=EQUIPMENT"):
            report = await _collect(client, f"{URL}?x=1{asset_type}")
            legacy = await _collect(client, f"/api/v1/repairs?status=OPEN{asset_type}")
            assert report == legacy


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "asset_type=vehicle",
        "asset_type=TRUCK",
        "asset_type=",
        "page=0",
        "page=-1",
        "page=abc",
        "page_size=0",
        "page_size=201",
        "page_size=1.5",
    ],
)
async def test_invalid_query_is_422_before_any_read(query: str) -> None:
    repo = _SpyRepository(_dataset_250())
    async with _client(repo) as client:
        response = await client.get(f"{URL}?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR"])
async def test_roles_holding_can_manage_repair_are_allowed(role: str) -> None:
    async with _client(_SpyRepository(_dataset_250())) as client:
        response = await client.get(URL, headers=_as(role))
    assert response.status_code == 200
    assert response.json()["total_items"] == 250


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["DRIVER", "TECHNICIAN", "UNKNOWN"])
async def test_roles_without_can_manage_repair_are_denied_before_any_read(role: str) -> None:
    repo = _SpyRepository(_dataset_250())
    async with _client(repo) as client:
        response = await client.get(f"{URL}?asset_type=VEHICLE", headers={**_as(role), "X-Request-ID": "req-7c2"})
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "HTTP_ERROR"
    assert "can_manage_repair" in error["message"]
    assert error["request_id"] == "req-7c2"
    assert "total_items" not in response.text and "items" not in response.json()
    assert repo.calls == []


@pytest.mark.asyncio
async def test_anonymous_non_dev_context_is_denied_before_any_read() -> None:
    repo = _SpyRepository(_dataset_250())
    with _env(DEV_AUTH_MODE="false", APP_ENV="development"):
        async with _client(repo) as client:
            response = await client.get(URL)
    assert response.status_code == 403
    assert repo.calls == []


@pytest.mark.asyncio
async def test_known_authorization_gaps_are_characterized_not_approved() -> None:
    """KNOWN EXISTING GAPS (DEC-3), recorded here as characterization only —
    NOT desired authorization contracts; remediation is deferred to the
    authorization/M02 work. With dev auth disabled (anonymous context):
    GET /repairs?status=OPEN is ungated, and GET /repairs/my-work passes
    assigned_to=None, exposing the whole OPEN population through
    pagination — while the open-queue report is denied."""
    repo = _SpyRepository(_dataset_250())
    with _env(DEV_AUTH_MODE="false", APP_ENV="development"):
        async with _client(repo) as client:
            legacy = await client.get("/api/v1/repairs?status=OPEN&page_size=1")
            my_work_items, my_work_total = await _collect(client, "/api/v1/repairs/my-work")
            report = await client.get(URL)
    assert legacy.status_code == 200 and legacy.json()["total_items"] == 250
    assert my_work_total == 250 and len(my_work_items) == 250
    assert report.status_code == 403


@pytest.mark.asyncio
async def test_closed_work_orders_and_repair_requests_are_excluded() -> None:
    async with _client() as client:  # real mock backend (seed data)
        maint = _as("MAINTENANCE", "syn-maint-1")
        before = (await client.get(URL, headers=maint)).json()["total_items"]
        pending = await client.post(
            "/api/v1/repair-requests",
            json={"vehicle_id": "VEH-1046", "symptom_th": "เสียงดัง", "priority": "NORMAL"},
            headers=_as("DRIVER", "syn-driver-1"),
        )
        to_convert = await client.post(
            "/api/v1/repair-requests",
            json={"vehicle_id": "VEH-1046", "symptom_th": "น้ำมันรั่ว", "priority": "NORMAL"},
            headers=_as("DRIVER", "syn-driver-1"),
        )
        assert pending.status_code == to_convert.status_code == 200
        request_id = to_convert.json()["request"]["repair_request_id"]
        converted = await client.post(f"/api/v1/repair-requests/{request_id}/convert", json={}, headers=maint)
        assert converted.status_code == 200
        converted_id = converted.json()["repair"]["repair_id"]
        direct = await client.post(
            "/api/v1/repairs",
            json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "source_type": "MANUAL"},
            headers=maint,
        )
        closed = await client.post(
            "/api/v1/repairs",
            json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
            headers=maint,
        )
        closed_id = closed.json()["repair"]["repair_id"]
        assert (await client.post(f"/api/v1/repairs/{closed_id}/close", json={}, headers=maint)).status_code == 200

        items, total = await _collect(client, URL, headers=maint)
    ids = [i["repair_id"] for i in items]
    assert total == before + 2
    assert converted_id in ids and direct.json()["repair"]["repair_id"] in ids
    assert closed_id not in ids
    assert pending.json()["request"]["repair_request_id"] not in ids and request_id not in ids
    assert ids.count(converted_id) == 1  # a converted request contributes only its work order
    assert all(i["status"] == "OPEN" for i in items)


@pytest.mark.asyncio
async def test_legacy_list_my_work_and_waiting_assignment_are_unchanged() -> None:
    """Membership, totals and assignment-HISTORY filtering of the legacy
    callers are unchanged by the shared ordering/helper; only equal-time
    ordering gained the repair_id tie-breaker."""
    repairs = [
        _repair("SYN-RPR-A", primary="syn-tech-1"),
        _repair("SYN-RPR-B", primary="syn-tech-1"),     # denormalized column only (stale)
        _repair("SYN-RPR-C"),
        _repair("SYN-RPR-D", status=RepairStatus.CLOSED, primary="syn-tech-1"),
        _repair("SYN-RPR-E", asset_type=AssetType.EQUIPMENT, asset_id="SYN-EQP-1"),
    ]
    repo = _SpyRepository(repairs)
    for rid in ("SYN-RPR-A", "SYN-RPR-D"):
        repo._repair_assignment_history[rid] = [
            RepairAssignmentHistoryEntry(
                repair_assignment_id=f"SYN-ASG-{rid}",
                repair_id=rid,
                user_id="syn-tech-1",
                assignment_role=AssignmentRole.PRIMARY,
                assigned_at=BASE,
                active_status=True,
            )
        ]
    async with _client(repo) as client:
        tech = _as("TECHNICIAN", "syn-tech-1")
        maint = _as("MAINTENANCE", "syn-maint-1")
        my_work = (await client.get("/api/v1/repairs/my-work", headers=tech)).json()
        waiting = (await client.get("/api/v1/repairs/waiting-assignment", headers=maint)).json()
        legacy_open = (await client.get("/api/v1/repairs?status=OPEN", headers=maint)).json()
        legacy_all = (await client.get("/api/v1/repairs", headers=maint)).json()
        assigned = (await client.get("/api/v1/repairs?assigned_to=syn-tech-1", headers=maint)).json()
        report = (await client.get(URL, headers=maint)).json()
    assert [i["repair_id"] for i in my_work["items"]] == ["SYN-RPR-A"] and my_work["total_items"] == 1
    assert [i["repair_id"] for i in waiting["items"]] == ["SYN-RPR-E", "SYN-RPR-C", "SYN-RPR-B"]
    assert waiting["total_items"] == 3
    assert [i["repair_id"] for i in assigned["items"]] == ["SYN-RPR-D", "SYN-RPR-A"]
    assert legacy_open["total_items"] == 4 and legacy_all["total_items"] == 5
    assert [i["repair_id"] for i in legacy_all["items"]] == ["SYN-RPR-E", "SYN-RPR-D", "SYN-RPR-C", "SYN-RPR-B", "SYN-RPR-A"]
    assert report["items"] == legacy_open["items"]
    assert repo.writes() == []


@pytest.mark.asyncio
async def test_error_envelopes_carry_no_rows_or_totals() -> None:
    cases = [
        (RepositorySchemaError("repair_order", "MISSING_HEADERS", ("status",)), 500, "REPAIR_ORDER_SCHEMA_INVALID"),
        (RepositoryError("down"), 503, "REPAIR_ORDER_READ_FAILED"),
        (ValueError("'Open' is not a valid RepairStatus"), 500, "INTERNAL_ERROR"),
        (TypeError("can't compare offset-naive and offset-aware datetimes"), 500, "INTERNAL_ERROR"),
        (ZeroDivisionError("bug"), 500, "INTERNAL_ERROR"),
    ]
    for exc, status_code, code in cases:
        repo = _FailingRepository(exc)
        async with _client(repo) as client:
            response = await client.get(URL)
        assert response.status_code == status_code, code
        body = response.json()
        assert list(body) == ["error"]
        assert body["error"]["code"] == code
        assert body["error"]["request_id"]
        assert "total_items" not in response.text and '"items"' not in response.text
        assert "Traceback" not in response.text
        if code == "INTERNAL_ERROR":
            assert str(exc) not in response.text
        assert repo.writes() == []


@pytest.mark.asyncio
async def test_zero_writes_across_api_paths() -> None:
    repo = _SpyRepository(_dataset_250())
    before = copy.deepcopy({k: v for k, v in vars(repo).items() if k != "calls"})
    async with _client(repo) as client:
        for path, headers in [
            (URL, {}),                                     # success
            (f"{URL}?asset_type=EQUIPMENT", {}),           # filtered
            (f"{URL}?page=99", {}),                        # out of range
            (f"{URL}?page_size=500", {}),                  # validation
            (URL, _as("DRIVER")),                          # permission
        ]:
            await client.get(path, headers=headers)
    empty = _SpyRepository()
    async with _client(empty) as client:
        assert (await client.get(URL)).json()["total_items"] == 0  # empty
    assert repo.writes() == [] and empty.writes() == []
    assert {k: v for k, v in vars(repo).items() if k != "calls"} == before


def test_openapi_documents_the_report_contract() -> None:
    from app.main import create_app

    spec = create_app().openapi()
    operation = spec["paths"]["/api/v1/repairs/open-queue"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}
    assert set(params) == {"page", "page_size", "asset_type"}
    assert params["page"]["schema"]["default"] == 1 and params["page"]["schema"]["minimum"] == 1
    assert params["page_size"]["schema"]["default"] == 50
    assert (params["page_size"]["schema"]["minimum"], params["page_size"]["schema"]["maximum"]) == (1, 200)
    assert {"200", "403", "422", "500", "503"} <= set(operation["responses"])
    assert list(spec["paths"]["/api/v1/repairs/open-queue"]) == ["get"]
