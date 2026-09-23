"""Phase 7 Batch 7B2 — fleet status summary: pure counting, service error
mapping, mock-repository parity, API contract, authorization (current
dev-auth behavior only — production authentication is NOT implemented and
not claimed) and zero-write checks. The Google Sheets validated read is
covered separately in test_fleet_status_summary_sheets_batch7b2.py.
All fixtures are synthetic (SYN-* ids), not company fleet data.
"""
from __future__ import annotations

import copy
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.common import OperationalStatus, PageParams
from app.domain.fleet_summary import (
    classify_raw_status,
    count_fleet_status,
    find_identity_issues,
    sample_vehicle_ids,
)
from app.domain.vehicle import Vehicle
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError, VehicleMasterSummaryRead
from app.repositories.mock import MockRepository

URL = "/api/v1/dashboard/fleet-status"
STATUSES = [s.value for s in OperationalStatus]
NOW = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)


def _vehicle(vid: str, status: str = "READY", model: str = "SYN-MODEL-001") -> Vehicle:
    return Vehicle(
        vehicle_id=vid,
        machine_no=f"SYN-{vid}",
        model_id=model,
        operational_status=OperationalStatus(status),
        created_at=NOW,
        updated_at=NOW,
    )


# ---------------------------------------------------------------------------
# C1/C2 — pure counting helpers
# ---------------------------------------------------------------------------


def test_c1_empty_input_gives_all_five_zero_keys() -> None:
    summary = count_fleet_status([])
    assert summary.vehicle_total == 0
    assert summary.status_counts == dict.fromkeys(STATUSES, 0)
    assert list(summary.status_counts) == STATUSES
    assert summary.population == "VEHICLE_MASTER_VALIDATED_RECORDS"


def test_c2_all_five_statuses_counted_exactly_and_total_is_the_sum() -> None:
    plan = {"WORKING": 2, "READY": 1, "MAINTENANCE": 1, "OUT_OF_SERVICE": 1, "LONG_TERM_PARKING": 1}
    vehicles = [_vehicle(f"SYN-{s}-{i}", s) for s, n in plan.items() for i in range(n)]
    summary = count_fleet_status(vehicles)
    assert summary.status_counts == plan
    assert summary.vehicle_total == 6 == sum(summary.status_counts.values())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("WORKING", None),
        ("LONG_TERM_PARKING", None),
        ("", "BLANK_STATUS"),
        ("   ", "BLANK_STATUS"),
        (None, "BLANK_STATUS"),
        ("Working", "UNRECOGNIZED_STATUS"),
        (" READY", "UNRECOGNIZED_STATUS"),
        ("READY ", "UNRECOGNIZED_STATUS"),
        ("UNKNOWN", "UNRECOGNIZED_STATUS"),
        (1, "UNRECOGNIZED_STATUS"),
    ],
)
def test_raw_status_is_exact_no_default_trim_case_or_alias(raw, expected) -> None:
    assert classify_raw_status(raw) == expected


def test_identity_issues_blank_and_duplicate_ids_counted_per_occurrence() -> None:
    vehicles = [_vehicle(""), _vehicle("  "), _vehicle("SYN-1"), _vehicle("SYN-1"), _vehicle("SYN-2"), _vehicle("syn-2")]
    issues, duplicated = find_identity_issues(vehicles)
    assert issues == {"BLANK_VEHICLE_ID": 2, "DUPLICATE_VEHICLE_ID": 2}
    assert duplicated == ["SYN-1"]  # exact comparison: "syn-2" is not "SYN-2"


def test_sample_ids_are_distinct_sorted_nonblank_and_capped_at_20() -> None:
    ids = [f"SYN-{i:02d}" for i in range(30, 0, -1)] * 2 + ["", "  "]
    assert sample_vehicle_ids(ids) == [f"SYN-{i:02d}" for i in range(1, 21)]


# ---------------------------------------------------------------------------
# Service error mapping (stub repositories)
# ---------------------------------------------------------------------------


class _StubRepository(MockRepository):
    """Mock repository whose summary read is replaced per test."""

    def __init__(self, outcome) -> None:
        super().__init__()
        self._outcome = outcome
        self.summary_reads = 0

    async def read_vehicle_master_for_summary(self) -> VehicleMasterSummaryRead:
        self.summary_reads += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


async def _service_error(outcome) -> ApiError:
    with pytest.raises(ApiError) as info:
        await VehicleService(_StubRepository(outcome)).get_fleet_status_summary()
    return info.value


@pytest.mark.asyncio
async def test_schema_error_maps_to_500_schema_invalid_with_details() -> None:
    err = await _service_error(RepositorySchemaError("vehicle_master", "MISSING_HEADERS", ("operational_status",)))
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_SCHEMA_INVALID", 500)
    assert err.details == {"tab": "vehicle_master", "problem": "MISSING_HEADERS", "headers": ["operational_status"]}


@pytest.mark.asyncio
async def test_other_repository_error_maps_to_503_read_failed_without_details() -> None:
    err = await _service_error(RepositoryError("Google Sheets reading values failed: APIError: secret-ish detail"))
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_READ_FAILED", 503)
    assert err.details is None
    assert "secret-ish" not in err.message


@pytest.mark.asyncio
async def test_record_and_identity_issues_merge_into_one_data_invalid() -> None:
    read = VehicleMasterSummaryRead(
        vehicles=[_vehicle("SYN-2001"), _vehicle("SYN-2001", "WORKING"), _vehicle("SYN-2002")],
        issue_counts={"BLANK_STATUS": 1},
        issue_vehicle_ids=["SYN-2003"],
    )
    err = await _service_error(read)
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_DATA_INVALID", 500)
    assert err.details == {
        "issue_counts": {"BLANK_STATUS": 1, "DUPLICATE_VEHICLE_ID": 2},
        "sample_vehicle_ids": ["SYN-2001", "SYN-2003"],
    }


@pytest.mark.asyncio
async def test_unexpected_bug_is_not_swallowed_as_a_data_quality_error() -> None:
    with pytest.raises(ZeroDivisionError):
        await VehicleService(_StubRepository(ZeroDivisionError("bug"))).get_fleet_status_summary()


# ---------------------------------------------------------------------------
# C3/C4 — mock repository parity with list_vehicles
# ---------------------------------------------------------------------------


async def _assert_mock_parity(repo: MockRepository) -> None:
    service = VehicleService(repo)
    summary = await service.get_fleet_status_summary()
    unfiltered = await service.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams(page=1, page_size=1))
    assert summary.vehicle_total == unfiltered.total_items
    for status in OperationalStatus:
        page = await service.list_vehicles(q=None, operational_status=status, model_id=None, params=PageParams(page=1, page_size=1))
        assert summary.status_counts[status.value] == page.total_items


@pytest.mark.asyncio
async def test_c3_seed_repository_counts_equal_list_totals() -> None:
    repo = MockRepository()
    summary = await VehicleService(repo).get_fleet_status_summary()
    assert summary.vehicle_total == 3
    await _assert_mock_parity(repo)


@pytest.mark.asyncio
async def test_c4_more_than_450_fixture_vehicles_no_page_truncation() -> None:
    repo = MockRepository()
    for i in range(450):
        vehicle = _vehicle(f"SYN-VEH-{i:04d}", STATUSES[i % 5], model="SYN-ORPHAN-MODEL")  # orphan model ids are counted
        repo._vehicles[vehicle.vehicle_id] = vehicle
    summary = await VehicleService(repo).get_fleet_status_summary()
    assert summary.vehicle_total == 453
    await _assert_mock_parity(repo)


# ---------------------------------------------------------------------------
# Read accounting and zero writes (mock)
# ---------------------------------------------------------------------------


class _SpyRepository(MockRepository):
    """Counts every repository coroutine call; any write method raises."""

    _WRITE_PREFIXES = ("create_", "update_", "change_", "add_", "append_", "record_", "close_", "delete_", "set_", "save_", "end_", "approve_", "assign_", "install_", "remove_", "convert_", "upsert_", "mark_")

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def __getattribute__(self, name: str):
        attr = super().__getattribute__(name)
        if name.startswith("_") or not callable(attr):
            return attr
        calls = super().__getattribute__("calls")
        if name.startswith(_SpyRepository._WRITE_PREFIXES):
            def refuse(*args, **kwargs):
                raise AssertionError(f"write method called: {name}")
            return refuse

        def record(*args, **kwargs):
            calls.append(name)
            return attr(*args, **kwargs)

        return record


@pytest.mark.asyncio
async def test_one_repository_read_no_n_plus_one_and_no_other_reads() -> None:
    repo = _SpyRepository()
    await VehicleService(repo).get_fleet_status_summary()
    assert repo.calls == ["read_vehicle_master_for_summary"]


@pytest.mark.asyncio
async def test_z2_mock_state_unchanged_after_summary() -> None:
    repo = MockRepository()
    before = copy.deepcopy(vars(repo))
    await VehicleService(repo).get_fleet_status_summary()
    assert vars(repo) == before


# ---------------------------------------------------------------------------
# API contract, auth and routes
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


async def _get(path: str, headers: dict[str, str] | None = None, repo=None):
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
            return await client.get(path, headers=headers or {})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a5_response_shape_is_exact_and_global(client) -> None:
    response = await client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["population", "vehicle_total", "status_counts"]
    assert body["population"] == "VEHICLE_MASTER_VALIDATED_RECORDS"
    assert list(body["status_counts"]) == STATUSES
    assert all(isinstance(v, int) and v >= 0 for v in body["status_counts"].values())
    assert body["vehicle_total"] == sum(body["status_counts"].values())
    # No supported query parameters: unknown/filter-looking ones are ignored.
    filtered = await client.get(f"{URL}?status=WORKING&model_id=X&q=zzz")
    assert filtered.status_code == 200
    assert filtered.json() == body


@pytest.mark.asyncio
async def test_a5_zero_status_keys_are_present(client) -> None:
    body = (await client.get(URL)).json()
    assert body["status_counts"]["READY"] == 0
    assert body["status_counts"]["OUT_OF_SERVICE"] == 0


@pytest.mark.asyncio
async def test_api_counts_equal_vehicle_list_totals(client) -> None:
    body = (await client.get(URL)).json()
    assert body["vehicle_total"] == (await client.get("/api/v1/vehicles?page_size=1")).json()["total_items"]
    for status in STATUSES:
        listed = (await client.get(f"/api/v1/vehicles?status={status}&page_size=1")).json()["total_items"]
        assert body["status_counts"][status] == listed


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER"])
async def test_a1_every_current_dev_role_with_can_view_is_allowed(client, role: str) -> None:
    response = await client.get(URL, headers={"X-Dev-Role": role})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a2_unknown_dev_role_is_denied_before_any_read() -> None:
    repo = _SpyRepository()
    response = await _get(URL, {"X-Dev-Role": "UNKNOWN", "X-Request-ID": "req-a2"}, repo=repo)
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "HTTP_ERROR"
    assert "can_view" in error["message"]
    assert error["request_id"] == "req-a2"
    assert "vehicle_total" not in response.text
    assert repo.calls == []


@pytest.mark.asyncio
async def test_a3_non_dev_context_fails_closed_with_zero_reads() -> None:
    repo = _SpyRepository()
    with _env(DEV_AUTH_MODE="false", APP_ENV="development"):
        response = await _get(URL, repo=repo)
    assert response.status_code == 403
    assert repo.calls == []


@pytest.mark.asyncio
async def test_a4_routes_do_not_conflict(client) -> None:
    assert (await client.get("/api/v1/vehicles/VEH-1046")).status_code == 200
    summary = await client.get("/api/v1/vehicles/summary")
    assert summary.status_code == 404
    assert summary.json()["error"]["code"] == "VEHICLE_NOT_FOUND"
    assert (await client.get(URL)).status_code == 200


@pytest.mark.asyncio
async def test_non_get_methods_are_not_offered(client) -> None:
    response = await client.post(URL, json={})
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_unexpected_bug_surfaces_as_generic_internal_error() -> None:
    response = await _get(URL, repo=_StubRepository(ZeroDivisionError("bug")))
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert "bug" not in response.text and "ZeroDivisionError" not in response.text


@pytest.mark.asyncio
async def test_error_envelopes_carry_no_counts() -> None:
    cases = [
        (RepositorySchemaError("vehicle_master", "NO_HEADER_ROW"), 500, "VEHICLE_MASTER_SCHEMA_INVALID"),
        (VehicleMasterSummaryRead(vehicles=[], issue_counts={"UNMAPPABLE_ROW": 1}), 500, "VEHICLE_MASTER_DATA_INVALID"),
        (RepositoryError("down"), 503, "VEHICLE_MASTER_READ_FAILED"),
    ]
    for outcome, status_code, code in cases:
        response = await _get(URL, repo=_StubRepository(outcome))
        assert response.status_code == status_code
        body = response.json()
        assert list(body) == ["error"]
        assert body["error"]["code"] == code
        assert body["error"]["request_id"]
        assert "vehicle_total" not in response.text and "status_counts" not in response.text


@pytest.mark.asyncio
async def test_z3_api_summary_leaves_vehicle_data_and_history_unchanged(client) -> None:
    before_list = (await client.get("/api/v1/vehicles?page_size=200")).json()
    before_history = (await client.get("/api/v1/vehicles/VEH-1046/status-history")).json()
    for _ in range(3):
        assert (await client.get(URL)).status_code == 200
    assert (await client.get("/api/v1/vehicles?page_size=200")).json() == before_list
    assert (await client.get("/api/v1/vehicles/VEH-1046/status-history")).json() == before_history


def test_openapi_documents_the_route_contract() -> None:
    from app.main import create_app

    spec = create_app().openapi()
    operation = spec["paths"]["/api/v1/dashboard/fleet-status"]["get"]
    assert operation.get("parameters", []) == []
    assert set(operation["responses"]) == {"200", "403", "500", "503"}
    assert list(spec["paths"]["/api/v1/dashboard/fleet-status"]) == ["get"]
    schema = spec["components"]["schemas"]["FleetStatusSummaryResponse"]
    assert schema["required"] == ["population", "vehicle_total", "status_counts"]
    assert schema["additionalProperties"] is False
    counts = spec["components"]["schemas"]["FleetStatusCountsResponse"]
    assert counts["required"] == STATUSES
