"""Phase 7 Batch 7G2 — vehicle search validation (A0), mock repository,
service and HTTP level.

GET /vehicles now uses the SAME single validated vehicle-master read and
whole-population gates as the 7B2 fleet status summary before any filter
or pagination. Approved decisions exercised here: DEC-1 (A0), DEC-2(a)
(blank status fails, never READY), DEC-7(b) (list DATA_INVALID details
carry issue_counts only; the gated dashboard keeps sample_vehicle_ids),
DEC-10 (the legacy `Repository.list_vehicles` stays in place, unused by
the service). The Google Sheets path (real gspread over a fake transport)
is covered in test_vehicle_search_data_quality_sheets_batch7g2.py.
All fixtures are synthetic.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.common import OperationalStatus, PageParams
from app.domain.vehicle import Vehicle
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.base import (
    RepositoryError,
    RepositorySchemaError,
    VehicleMasterSummaryRead,
)
from app.repositories.mock import MockRepository

TS = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
MODELS = ("MODEL-0001", "MODEL-0002", "MODEL-0003")


def _vehicle(vid: str, status: OperationalStatus = OperationalStatus.READY, machine: str | None = None, model: str = "MODEL-0001") -> Vehicle:
    return Vehicle(
        vehicle_id=vid,
        machine_no=machine if machine is not None else f"TC-{vid[-3:]}",
        model_id=model,
        serial_number=None,
        operational_status=status,
        created_at=TS,
        updated_at=TS,
    )


def _repo_with(extra: list[Vehicle], keep_seed: bool = True) -> MockRepository:
    repo = MockRepository()
    if not keep_seed:
        repo._vehicles.clear()
    for index, vehicle in enumerate(extra):
        # Keyed by position so blank or duplicated ids can be stored too.
        repo._vehicles[f"__k{index}"] = vehicle
    return repo


def _big_repo() -> MockRepository:
    statuses = list(OperationalStatus)
    extra = [
        _vehicle(f"VEH-{i:03d}", statuses[i % 5], machine=f"TC-{(i * 7) % 50:02d}", model=MODELS[i % 3])
        for i in range(57)
    ]
    return _repo_with(extra)


class CountingRepository(MockRepository):
    """Mock repository that counts the vehicle reads the service makes."""

    def __init__(self, read: VehicleMasterSummaryRead | None = None, error: Exception | None = None) -> None:
        super().__init__()
        self._forced_read = read
        self._forced_error = error
        self.summary_reads = 0
        self.legacy_list_calls = 0
        self.get_vehicle_calls = 0

    async def read_vehicle_master_for_summary(self) -> VehicleMasterSummaryRead:
        self.summary_reads += 1
        if self._forced_error is not None:
            raise self._forced_error
        if self._forced_read is not None:
            return self._forced_read
        return await super().read_vehicle_master_for_summary()

    async def list_vehicles(self, *args, **kwargs):  # type: ignore[override]
        self.legacy_list_calls += 1
        return await super().list_vehicles(*args, **kwargs)

    async def get_vehicle(self, vehicle_id: str):  # type: ignore[override]
        self.get_vehicle_calls += 1
        return await super().get_vehicle(vehicle_id)


async def _list(service: VehicleService, q=None, status=None, model_id=None, page=1, page_size=20):
    return await service.list_vehicles(
        q=q, operational_status=status, model_id=model_id, params=PageParams(page=page, page_size=page_size)
    )


async def _list_error(service: VehicleService, **kwargs) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _list(service, **kwargs)
    return info.value


async def _dashboard_error(service: VehicleService) -> ApiError:
    with pytest.raises(ApiError) as info:
        await service.get_fleet_status_summary()
    return info.value


# ---------------------------------------------------------------------------
# G01 — clean data: identical to the legacy mock list (golden comparison)
# ---------------------------------------------------------------------------

_QUERIES = [None, "", "   ", "veh-01", "  VEH-01  ", "tc-1", "TC-2", "1046", "zzz"]
_STATUS_FILTERS = [None, *OperationalStatus]
_MODEL_FILTERS = [None, "MODEL-0002", "MODEL-9999"]
_PAGING = [(1, 1), (2, 1), (1, 7), (3, 7), (9, 7), (1, 20), (2, 20), (1, 200), (40, 5)]


@pytest.mark.asyncio
async def test_g01_clean_mock_results_equal_the_legacy_list_for_every_combination() -> None:
    repo = _big_repo()
    service = VehicleService(repo)
    compared = 0
    for q, status, model_id, (page, size) in itertools.product(_QUERIES, _STATUS_FILTERS, _MODEL_FILTERS, _PAGING):
        params = PageParams(page=page, page_size=size)
        legacy_items, legacy_total = await repo.list_vehicles(q=q, operational_status=status, model_id=model_id, params=params)
        result = await service.list_vehicles(q=q, operational_status=status, model_id=model_id, params=params)
        assert [v.model_dump() for v in result.items] == [v.model_dump() for v in legacy_items]
        assert (result.total_items, result.page, result.page_size) == (legacy_total, page, size)
        compared += 1
    assert compared == len(_QUERIES) * len(_STATUS_FILTERS) * len(_MODEL_FILTERS) * len(_PAGING)


@pytest.mark.asyncio
async def test_g01_query_semantics_ordering_and_out_of_range_page() -> None:
    service = VehicleService(_big_repo())
    # q is trimmed and lower-cased, matching machine_no OR vehicle_id substrings.
    by_id = await _list(service, q="  veh-05  ", page_size=200)
    assert [v.vehicle_id for v in by_id.items] == [f"VEH-{i:03d}" for i in range(50, 57)]
    by_machine = await _list(service, q="tc-12", page_size=200)
    assert by_machine.total_items >= 1
    assert all("tc-12" in v.machine_no.lower() or "tc-12" in v.vehicle_id.lower() for v in by_machine.items)
    # Exact status and model filters, sorted by vehicle_id.
    working = await _list(service, status=OperationalStatus.WORKING, model_id="MODEL-0002", page_size=200)
    assert working.items and all(
        v.operational_status == OperationalStatus.WORKING and v.model_id == "MODEL-0002" for v in working.items
    )
    everything = await _list(service, page_size=200)
    ids = [v.vehicle_id for v in everything.items]
    assert ids == sorted(ids) and everything.total_items == 60
    # total_items is the filtered count, computed before slicing.
    page2 = await _list(service, page=2, page_size=25)
    assert (len(page2.items), page2.total_items) == (25, 60)
    assert [v.vehicle_id for v in page2.items] == ids[25:50]
    # A page beyond the end is empty with the true filtered total.
    beyond = await _list(service, status=OperationalStatus.READY, page=99, page_size=10)
    assert beyond.items == [] and beyond.total_items == 12 and beyond.page == 99


@pytest.mark.asyncio
async def test_g01_seed_repository_behaviour_is_unchanged() -> None:
    service = VehicleService(MockRepository())
    result = await _list(service)
    assert [v.vehicle_id for v in result.items] == ["VEH-1046", "VEH-1047", "VEH-1048"]
    assert result.total_items == 3


# ---------------------------------------------------------------------------
# G03 — exactly one validated read, no legacy/per-row reads, zero writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g03_one_validated_read_no_other_vehicle_reads_and_no_writes() -> None:
    repo = CountingRepository()
    before = ({k: v.model_dump() for k, v in repo._vehicles.items()}, dict(repo._status_history))
    service = VehicleService(repo)
    for kwargs in ({}, {"q": "veh"}, {"status": OperationalStatus.READY}, {"model_id": "MODEL-0001"}, {"page": 5}):
        repo.summary_reads = 0
        await _list(service, **kwargs)
        assert repo.summary_reads == 1
    assert repo.legacy_list_calls == 0 and repo.get_vehicle_calls == 0
    after = ({k: v.model_dump() for k, v in repo._vehicles.items()}, dict(repo._status_history))
    assert after == before


@pytest.mark.asyncio
async def test_g03_one_read_even_when_validation_fails() -> None:
    repo = CountingRepository(read=VehicleMasterSummaryRead(vehicles=[], issue_counts={"BLANK_STATUS": 1}, issue_vehicle_ids=["VEH-X"]))
    await _list_error(VehicleService(repo), q="anything")
    assert repo.summary_reads == 1 and repo.legacy_list_calls == 0


# ---------------------------------------------------------------------------
# Validation before filtering; DEC-7(b) list details vs dashboard details
# ---------------------------------------------------------------------------

_INVALID_READS = {
    "blank_status": VehicleMasterSummaryRead(vehicles=[_vehicle("VEH-001")], issue_counts={"BLANK_STATUS": 2}, issue_vehicle_ids=["VEH-B1", "VEH-B2"]),
    "unrecognized_status": VehicleMasterSummaryRead(vehicles=[_vehicle("VEH-001")], issue_counts={"UNRECOGNIZED_STATUS": 1}, issue_vehicle_ids=["VEH-U1"]),
    "unmappable_row": VehicleMasterSummaryRead(vehicles=[_vehicle("VEH-001")], issue_counts={"UNMAPPABLE_ROW": 1}, issue_vehicle_ids=["VEH-M1"]),
    "blank_id": VehicleMasterSummaryRead(vehicles=[_vehicle("VEH-001"), _vehicle("   ")]),
    "duplicate_id": VehicleMasterSummaryRead(vehicles=[_vehicle("VEH-001"), _vehicle("VEH-D1"), _vehicle("VEH-D1")]),
}
_EXPECTED_COUNTS = {
    "blank_status": {"BLANK_STATUS": 2},
    "unrecognized_status": {"UNRECOGNIZED_STATUS": 1},
    "unmappable_row": {"UNMAPPABLE_ROW": 1},
    "blank_id": {"BLANK_VEHICLE_ID": 1},
    "duplicate_id": {"DUPLICATE_VEHICLE_ID": 2},
}
_EXPECTED_SAMPLES = {
    "blank_status": ["VEH-B1", "VEH-B2"],
    "unrecognized_status": ["VEH-U1"],
    "unmappable_row": ["VEH-M1"],
    "blank_id": [],
    "duplicate_id": ["VEH-D1"],
}
_UNRELATED_FILTERS = [
    {},
    {"q": "VEH-001"},
    {"q": "no-such-vehicle"},
    {"status": OperationalStatus.LONG_TERM_PARKING},
    {"model_id": "MODEL-9999"},
    {"page": 50, "page_size": 1},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_INVALID_READS))
async def test_g07_g10_g12b_any_issue_fails_every_list_request_with_counts_only(case: str) -> None:
    service = VehicleService(CountingRepository(read=_INVALID_READS[case]))
    for kwargs in _UNRELATED_FILTERS:
        err = await _list_error(service, **kwargs)
        assert (err.code, err.status_code) == ("VEHICLE_MASTER_DATA_INVALID", 500)
        # DEC-7(b): exactly {"issue_counts": {...}} — no sample ids, no rows.
        assert err.details == {"issue_counts": _EXPECTED_COUNTS[case]}
        for vid in ("VEH-B1", "VEH-B2", "VEH-U1", "VEH-M1", "VEH-D1", "VEH-001"):
            assert vid not in err.message
        assert err.message == "vehicle_master contains records that cannot be listed exactly"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_INVALID_READS))
async def test_dashboard_keeps_its_original_details_with_sample_ids(case: str) -> None:
    err = await _dashboard_error(VehicleService(CountingRepository(read=_INVALID_READS[case])))
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_DATA_INVALID", 500)
    assert err.message == "vehicle_master contains records that cannot be summarized exactly"
    assert err.details == {
        "issue_counts": _EXPECTED_COUNTS[case],
        "sample_vehicle_ids": _EXPECTED_SAMPLES[case],
    }


@pytest.mark.asyncio
async def test_combined_issue_counts_are_sorted_and_identical_for_list_and_dashboard() -> None:
    read = VehicleMasterSummaryRead(
        vehicles=[_vehicle("VEH-D"), _vehicle("VEH-D"), _vehicle(""), _vehicle("VEH-OK")],
        issue_counts={"UNRECOGNIZED_STATUS": 3, "BLANK_STATUS": 1},
        issue_vehicle_ids=["VEH-U"],
    )
    service = VehicleService(CountingRepository(read=read))
    list_err = await _list_error(service)
    dash_err = await _dashboard_error(service)
    expected = {"BLANK_STATUS": 1, "BLANK_VEHICLE_ID": 1, "DUPLICATE_VEHICLE_ID": 2, "UNRECOGNIZED_STATUS": 3}
    assert list(list_err.details["issue_counts"]) == sorted(expected)
    assert list_err.details["issue_counts"] == dash_err.details["issue_counts"] == expected
    assert set(list_err.details) == {"issue_counts"}
    assert dash_err.details["sample_vehicle_ids"] == ["VEH-D", "VEH-U"]


@pytest.mark.asyncio
async def test_mock_blank_and_duplicate_ids_fail_list_and_dashboard_alike() -> None:
    repo = _repo_with([_vehicle("VEH-900"), _vehicle("VEH-900", OperationalStatus.WORKING), _vehicle("  ")])
    service = VehicleService(repo)
    list_err = await _list_error(service, q="VEH-1046")
    dash_err = await _dashboard_error(service)
    assert list_err.details == {"issue_counts": {"BLANK_VEHICLE_ID": 1, "DUPLICATE_VEHICLE_ID": 2}}
    assert dash_err.details == {
        "issue_counts": {"BLANK_VEHICLE_ID": 1, "DUPLICATE_VEHICLE_ID": 2},
        "sample_vehicle_ids": ["VEH-900"],
    }
    # DEC-10: the legacy repository list is untouched and still lists them.
    _, legacy_total = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
    assert legacy_total == 6


# ---------------------------------------------------------------------------
# Repository failures: the service propagates; the route maps (see HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_errors_propagate_from_the_service_unchanged() -> None:
    schema_error = RepositorySchemaError("vehicle_master", "MISSING_HEADERS", ("operational_status",))
    for error in (schema_error, RepositoryError("down")):
        service = VehicleService(CountingRepository(error=error))
        with pytest.raises(RepositoryError) as info:
            await _list(service)
        assert info.value is error


@pytest.mark.asyncio
async def test_g11_unexpected_exceptions_are_not_converted() -> None:
    service = VehicleService(CountingRepository(error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        await _list(service)
    with pytest.raises(RuntimeError):
        await service.get_fleet_status_summary()


# ---------------------------------------------------------------------------
# Dashboard/list agreement for the same stored dataset (mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g12_dashboard_total_and_status_counts_equal_unfiltered_and_status_only_lists() -> None:
    service = VehicleService(_big_repo())
    summary = await service.get_fleet_status_summary()
    assert summary.vehicle_total == (await _list(service, page_size=1)).total_items
    for status in OperationalStatus:
        page = await _list(service, status=status, page_size=1)
        assert summary.status_counts[status.value] == page.total_items


# ---------------------------------------------------------------------------
# HTTP: error contract, authorization unchanged, 422 unchanged
# ---------------------------------------------------------------------------


async def _http(repo, path: str, headers: dict[str, str] | None = None, params=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    try:
        # raise_app_exceptions=False: observe the app's generic 500 handler
        # response instead of the transport re-raising the exception.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers or {}, params=params)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _assert_no_page_data(text: str) -> None:
    for key in ("items", "total_items", "page_size", "vehicle_total", "status_counts", "Traceback"):
        assert key not in text


@pytest.mark.asyncio
async def test_g15_http_error_envelopes_for_the_list() -> None:
    schema_error = RepositorySchemaError("vehicle_master", "MISSING_HEADERS", ("operational_status",))
    cases = [
        (CountingRepository(error=schema_error), 500, "VEHICLE_MASTER_SCHEMA_INVALID",
         {"tab": "vehicle_master", "problem": "MISSING_HEADERS", "headers": ["operational_status"]}),
        (CountingRepository(error=RepositoryError("socket: 10.0.0.1 refused")), 503, "VEHICLE_MASTER_READ_FAILED", None),
        (CountingRepository(read=_INVALID_READS["blank_status"]), 500, "VEHICLE_MASTER_DATA_INVALID",
         {"issue_counts": {"BLANK_STATUS": 2}}),
        (CountingRepository(read=_INVALID_READS["duplicate_id"]), 500, "VEHICLE_MASTER_DATA_INVALID",
         {"issue_counts": {"DUPLICATE_VEHICLE_ID": 2}}),
    ]
    for repo, status_code, code, details in cases:
        response = await _http(repo, "/api/v1/vehicles", params={"q": "VEH-001", "page": 2})
        assert response.status_code == status_code, code
        body = response.json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == code
        assert body["error"]["details"] == details
        assert body["error"]["request_id"]
        _assert_no_page_data(response.text)
        for vid in ("VEH-B1", "VEH-B2", "VEH-D1", "10.0.0.1"):
            assert vid not in response.text
        assert repo.summary_reads == 1


@pytest.mark.asyncio
async def test_http_dashboard_error_still_carries_sample_ids() -> None:
    response = await _http(CountingRepository(read=_INVALID_READS["blank_status"]), "/api/v1/dashboard/fleet-status")
    assert response.status_code == 500
    assert response.json()["error"]["details"] == {
        "issue_counts": {"BLANK_STATUS": 2},
        "sample_vehicle_ids": ["VEH-B1", "VEH-B2"],
    }


@pytest.mark.asyncio
async def test_http_unexpected_exception_keeps_generic_handling() -> None:
    response = await _http(CountingRepository(error=RuntimeError("secret detail")), "/api/v1/vehicles")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in response.text


@pytest.mark.asyncio
async def test_http_query_validation_is_unchanged_and_reads_nothing() -> None:
    for params in ({"status": "ready"}, {"status": "BROKEN"}, {"page": 0}, {"page_size": 201}):
        repo = CountingRepository()
        response = await _http(repo, "/api/v1/vehicles", params=params)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert repo.summary_reads == 0


@pytest.mark.asyncio
async def test_g02_authorization_unchanged_list_ungated_dashboard_gated() -> None:
    headers = {"X-Dev-Role": "UNKNOWN"}
    listed = await _http(CountingRepository(), "/api/v1/vehicles", headers=headers)
    assert listed.status_code == 200 and listed.json()["total_items"] == 3
    denied_repo = CountingRepository()
    denied = await _http(denied_repo, "/api/v1/dashboard/fleet-status", headers=headers)
    assert denied.status_code == 403 and denied_repo.summary_reads == 0


@pytest.mark.asyncio
async def test_http_success_shape_and_dashboard_agreement_on_seed_data() -> None:
    listed = await _http(None, "/api/v1/vehicles", params={"page_size": 2})
    assert listed.status_code == 200
    body = listed.json()
    assert set(body) == {"items", "page", "page_size", "total_items"}
    assert (body["page"], body["page_size"], body["total_items"]) == (1, 2, 3)
    assert set(body["items"][0]) == {
        "vehicle_id", "machine_no", "model_id", "serial_number", "operational_status", "created_at", "updated_at",
    }
    dashboard = (await _http(None, "/api/v1/dashboard/fleet-status")).json()
    assert dashboard["vehicle_total"] == body["total_items"]
    for status in OperationalStatus:
        per_status = (await _http(None, "/api/v1/vehicles", params={"status": status.value})).json()
        assert per_status["total_items"] == dashboard["status_counts"][status.value]


@pytest.mark.asyncio
async def test_openapi_documents_the_list_errors() -> None:
    response = await _http(None, "/openapi.json")
    if response.status_code != 200:
        response = await _http(None, "/api/v1/openapi.json")
    assert response.status_code == 200
    operation = response.json()["paths"]["/api/v1/vehicles"]["get"]
    assert {"500", "503", "422"} <= set(operation["responses"])
    assert "issue_counts only" in operation["responses"]["500"]["description"]
