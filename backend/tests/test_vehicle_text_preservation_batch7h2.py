"""Phase 7 Batch 7H2 — vehicle text preservation: mock repository, service
error mapping and HTTP behavior.

Covers the new VehicleService-scoped repository paths (DEC-H15a) on the
mock repository, the per-stage error/outcome mapping of the Final 7H1
contract (5.3, DEC-H6/H7/H14), DEC-H8(b) whitespace-only machine numbers
(422 before any repository call), and that legacy callers keep using the
legacy methods. The Google Sheets behavior (real gspread over the fake
transport) is in test_vehicle_text_preservation_sheets_batch7h2.py.
All fixtures are synthetic.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.common import OperationalStatus, PageParams
from app.domain.vehicle import Vehicle
from app.domain.vehicle_service import VehicleService, vehicle_path_error
from app.errors import ApiError
from app.repositories.base import (
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
    RepositoryWriteError,
)
from app.repositories.mock import MockRepository

TS = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)

_TRACKED = (
    "get_vehicle", "get_vehicle_model", "list_vehicle_models", "list_vehicle_components",
    "list_vehicle_status_history", "update_vehicle_machine_no", "change_vehicle_status",
    "get_vehicle_validated", "get_vehicle_model_validated", "list_vehicle_models_validated",
    "list_vehicle_components_validated", "list_vehicle_status_history_validated",
    "update_vehicle_machine_no_validated", "change_vehicle_status_validated",
    "read_vehicle_master_for_summary", "list_vehicles",
)


class SpyRepository(MockRepository):
    """Mock repository recording the vehicle-related repository calls made
    BY ITS CALLER (outermost calls only — the mock's own internal
    delegation from a validated method to a legacy one is not recorded)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self._depth = 0

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if name in _TRACKED:
            spy = self

            async def wrapper(*args, **kwargs):
                if spy._depth == 0:
                    spy.calls.append(name)
                spy._depth += 1
                try:
                    return await attr(*args, **kwargs)
                finally:
                    spy._depth -= 1

            return wrapper
        return attr


class RaisingRepository(MockRepository):
    """Raises `error` from every validated VehicleService path."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def _raise(self, *args, **kwargs):
        raise self.error

    get_vehicle_validated = _raise
    get_vehicle_model_validated = _raise
    list_vehicle_models_validated = _raise
    list_vehicle_components_validated = _raise
    list_vehicle_status_history_validated = _raise
    update_vehicle_machine_no_validated = _raise
    change_vehicle_status_validated = _raise


def _vehicle(vid: str, machine: str = "TC-1") -> Vehicle:
    return Vehicle(vehicle_id=vid, machine_no=machine, model_id="MODEL-0001", serial_number=None,
                   operational_status=OperationalStatus.READY, created_at=TS, updated_at=TS)


def _with_extra(repo: MockRepository, *vehicles: Vehicle) -> MockRepository:
    for i, v in enumerate(vehicles):
        repo._vehicles[f"__k{i}"] = v
    return repo


async def _http(repo, method: str, path: str, **kwargs):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# DEC-H8(b) — whitespace-only machine_no: 422 before any repository call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [" ", "   ", "\t", "\n", " ", "　", " \t  "])
async def test_h8b_whitespace_only_machine_no_is_422_with_zero_repository_calls(value: str) -> None:
    repo = SpyRepository()
    before = repo._vehicles["VEH-1046"].machine_no
    response = await _http(repo, "PATCH", "/api/v1/vehicles/VEH-1046", json={"machine_no": value})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["type"] == "whitespace_only"
    assert repo.calls == []
    assert repo._vehicles["VEH-1046"].machine_no == before


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [" 0012 ", "0012", "'x", "=1+1", "TC 12", "\t12", "TRUE", "1.50"])
async def test_h8b_accepted_values_are_stored_and_returned_unchanged(value: str) -> None:
    repo = SpyRepository()
    response = await _http(repo, "PATCH", "/api/v1/vehicles/VEH-1046", json={"machine_no": value})
    assert response.status_code == 200
    assert response.json()["machine_no"] == value
    detail = await _http(repo, "GET", "/api/v1/vehicles/VEH-1046")
    assert detail.json()["vehicle"]["machine_no"] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"machine_no": ""}, {"machine_no": "x" * 101}, {"machine_no": 12}, {}])
async def test_h8b_existing_type_and_length_validation_is_kept(body: dict) -> None:
    repo = SpyRepository()
    response = await _http(repo, "PATCH", "/api/v1/vehicles/VEH-1046", json=body)
    assert response.status_code == 422
    assert repo.calls == []


# ---------------------------------------------------------------------------
# Mock semantics on the new paths (T15) and identity (DEC-H5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t15_vehicle_service_uses_only_the_validated_paths_and_never_rereads() -> None:
    repo = SpyRepository()
    service = VehicleService(repo)
    await service.get_vehicle_detail("VEH-1046")
    await service.list_components("VEH-1046")
    await service.list_status_history("VEH-1046")
    await service.list_models(None, PageParams())
    await service.get_model("MODEL-0001")
    repo.calls.clear()
    await service.update_machine_no("VEH-1046", "0012")
    assert repo.calls == ["update_vehicle_machine_no_validated"]
    repo.calls.clear()
    vehicle, entry = await service.change_status("VEH-1046", OperationalStatus.MAINTENANCE, "u", "n")
    assert repo.calls == ["change_vehicle_status_validated"]  # no post-write re-read (DEC-H17)
    assert (vehicle.machine_no, vehicle.operational_status, entry.vehicle_id) == ("0012", OperationalStatus.MAINTENANCE, "VEH-1046")


@pytest.mark.asyncio
async def test_t15_vehicle_service_never_calls_the_legacy_vehicle_methods() -> None:
    repo = SpyRepository()
    service = VehicleService(repo)
    await service.get_vehicle_detail("VEH-1046")
    await service.list_components("VEH-1046")
    await service.list_status_history("VEH-1046")
    await service.list_models(None, PageParams())
    await service.get_model("MODEL-0001")
    await service.update_machine_no("VEH-1046", "X")
    await service.change_status("VEH-1046", OperationalStatus.WORKING, None, None)
    legacy = {"get_vehicle", "get_vehicle_model", "list_vehicle_models", "list_vehicle_components",
              "list_vehicle_status_history", "update_vehicle_machine_no", "change_vehicle_status"}
    assert legacy.isdisjoint(repo.calls)


@pytest.mark.asyncio
async def test_t17_legacy_callers_keep_the_legacy_method() -> None:
    repo = SpyRepository()
    await require_asset_exists(repo, AssetType.VEHICLE, "VEH-1046")
    assert repo.calls == ["get_vehicle"]


@pytest.mark.asyncio
async def test_mock_duplicate_ids_are_409_everywhere_with_nothing_changed() -> None:
    repo = _with_extra(MockRepository(), _vehicle("VEH-D", "A"), _vehicle("VEH-D", "B"))
    service = VehicleService(repo)
    history_before = {k: list(v) for k, v in repo._status_history.items()}
    for call in (service.get_vehicle_detail("VEH-D"), service.list_components("VEH-D"),
                 service.list_status_history("VEH-D"), service.update_machine_no("VEH-D", "X"),
                 service.change_status("VEH-D", OperationalStatus.WORKING, "u", None)):
        with pytest.raises(ApiError) as info:
            await call
        assert (info.value.code, info.value.status_code, info.value.details) == ("VEHICLE_ID_AMBIGUOUS", 409, {"match_count": 2})
    assert sorted(v.machine_no for k, v in repo._vehicles.items() if k.startswith("__k")) == ["A", "B"]
    assert {k: list(v) for k, v in repo._status_history.items()} == history_before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/vehicles/%20", "/api/v1/vehicles/%20%20/components",
                                  "/api/v1/vehicles/%09/status-history"])
async def test_blank_path_ids_are_404(path: str) -> None:
    response = await _http(_with_extra(MockRepository(), _vehicle(" ")), "GET", path)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "VEHICLE_NOT_FOUND")


@pytest.mark.asyncio
async def test_exact_identity_no_normalization_in_mock() -> None:
    service = VehicleService(_with_extra(MockRepository(), _vehicle("0012")))
    assert (await service.get_vehicle_detail("0012")).vehicle.vehicle_id == "0012"
    for other in ("12", " 0012", "0012 ", "veh-1046"):
        with pytest.raises(ApiError) as info:
            await service.get_vehicle_detail(other)
        assert info.value.code == "VEHICLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Error / outcome mapping (5.3, DEC-H6/H7/H14) and propagation (T14)
# ---------------------------------------------------------------------------

_MAPPING_CASES = [
    (RepositoryIdentityAmbiguousError("vehicle_master", 3), "VEHICLE_ID_AMBIGUOUS", 409, {"match_count": 3}),
    (RepositoryRecordInvalidError("vehicle_master", "BLANK_STATUS"), "VEHICLE_MASTER_DATA_INVALID", 500, {"issue_counts": {"BLANK_STATUS": 1}}),
    (RepositoryWriteError("vehicle_master", "rejected", 400, "x"), "VEHICLE_MASTER_WRITE_FAILED", 503, {"vehicle_write_outcome": "rejected"}),
    (RepositoryWriteError("vehicle_master", "unknown", None, "x"), "VEHICLE_MASTER_WRITE_FAILED", 503, {"vehicle_write_outcome": "unknown"}),
    (RepositoryWriteError("vehicle_status_history", "unknown", 503, "x"), "VEHICLE_STATUS_HISTORY_WRITE_FAILED", 503,
     {"vehicle_status_updated": True, "history_write_outcome": "unknown"}),
    (RepositoryWriteError("vehicle_status_history", "rejected", 400, "x"), "VEHICLE_STATUS_HISTORY_WRITE_FAILED", 503,
     {"vehicle_status_updated": True, "history_write_outcome": "rejected"}),
    (RepositorySchemaError("vehicle_master", "MISSING_HEADERS", ("machine_no",)), "VEHICLE_MASTER_SCHEMA_INVALID", 500,
     {"tab": "vehicle_master", "problem": "MISSING_HEADERS", "headers": ["machine_no"]}),
    (RepositorySchemaError("model_master", "NO_HEADER_ROW"), "MODEL_MASTER_SCHEMA_INVALID", 500,
     {"tab": "model_master", "problem": "NO_HEADER_ROW", "headers": []}),
    (RepositorySchemaError("maintenance_plan", "TAB_MISSING"), "MODEL_MASTER_SCHEMA_INVALID", 500,
     {"tab": "maintenance_plan", "problem": "TAB_MISSING", "headers": []}),
    (RepositorySchemaError("vehicle_component", "DUPLICATE_HEADERS", ("label",)), "VEHICLE_COMPONENT_SCHEMA_INVALID", 500,
     {"tab": "vehicle_component", "problem": "DUPLICATE_HEADERS", "headers": ["label"]}),
    (RepositorySchemaError("vehicle_status_history", "MISSING_HEADERS", ("note",)), "VEHICLE_STATUS_HISTORY_SCHEMA_INVALID", 500,
     {"tab": "vehicle_status_history", "problem": "MISSING_HEADERS", "headers": ["note"]}),
    (RepositoryTabReadError("vehicle_master", "x"), "VEHICLE_MASTER_READ_FAILED", 503, None),
    (RepositoryTabReadError("model_master", "x"), "MODEL_MASTER_READ_FAILED", 503, None),
    (RepositoryTabReadError("maintenance_plan", "x"), "MODEL_MASTER_READ_FAILED", 503, {"tab": "maintenance_plan"}),
    (RepositoryTabReadError("vehicle_component", "x"), "VEHICLE_COMPONENT_READ_FAILED", 503, None),
    (RepositoryTabReadError("vehicle_status_history", "x"), "VEHICLE_STATUS_HISTORY_READ_FAILED", 503, None),
]


@pytest.mark.parametrize(("error", "code", "status_code", "details"), _MAPPING_CASES)
def test_error_mapping_table(error, code, status_code, details) -> None:
    mapped = vehicle_path_error(error)
    assert (mapped.code, mapped.status_code, mapped.details) == (code, status_code, details)


def test_unknown_outcome_messages_do_not_claim_absence() -> None:
    vehicle = vehicle_path_error(RepositoryWriteError("vehicle_master", "unknown", None, "x"))
    history = vehicle_path_error(RepositoryWriteError("vehicle_status_history", "unknown", None, "x"))
    assert "may have been applied" in vehicle.message
    assert "may or may not have been recorded" in history.message
    for message in (vehicle.message, history.message):
        assert "was not recorded" not in message and "not updated" not in message


def test_unrecognised_repository_errors_are_not_mapped() -> None:
    assert vehicle_path_error(RepositoryError("plain")) is None
    assert vehicle_path_error(RepositoryTabReadError("some_other_tab", "x")) is None


@pytest.mark.asyncio
async def test_service_routes_every_validated_path_through_the_mapping() -> None:
    service = VehicleService(RaisingRepository(RepositoryWriteError("vehicle_status_history", "unknown", None, "x")))
    with pytest.raises(ApiError) as info:
        await service.change_status("VEH-1046", OperationalStatus.WORKING, "u", None)
    assert info.value.details == {"vehicle_status_updated": True, "history_write_outcome": "unknown"}
    service = VehicleService(RaisingRepository(RepositoryTabReadError("model_master", "x")))
    for call in (service.list_models(None, PageParams()), service.get_model("MODEL-0001")):
        with pytest.raises(ApiError) as info:
            await call
        assert info.value.code == "MODEL_MASTER_READ_FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [LookupError("bug"), RepositoryFeatureNotImplementedError("vehicle"), RepositoryError("plain")])
async def test_t14_unexpected_and_unmapped_errors_propagate_unchanged(error: Exception) -> None:
    service = VehicleService(RaisingRepository(error))
    for call in (service.get_vehicle_detail("VEH-1046"), service.update_machine_no("VEH-1046", "X"),
                 service.change_status("VEH-1046", OperationalStatus.WORKING, "u", None)):
        with pytest.raises(type(error)) as info:
            await call
        assert info.value is error


@pytest.mark.asyncio
async def test_http_envelopes_for_write_outcomes() -> None:
    cases = [
        (RepositoryWriteError("vehicle_master", "unknown", None, "x"), "PATCH", "/api/v1/vehicles/VEH-1046", {"machine_no": "X"},
         503, "VEHICLE_MASTER_WRITE_FAILED"),
        (RepositoryWriteError("vehicle_status_history", "rejected", 400, "x"), "PATCH", "/api/v1/vehicles/VEH-1046/status",
         {"status": "READY"}, 503, "VEHICLE_STATUS_HISTORY_WRITE_FAILED"),
        (RepositoryIdentityAmbiguousError("vehicle_master", 2), "GET", "/api/v1/vehicles/VEH-1046", None, 409, "VEHICLE_ID_AMBIGUOUS"),
        (LookupError("bug"), "GET", "/api/v1/vehicles/VEH-1046", None, 500, "INTERNAL_ERROR"),
    ]
    for error, method, path, body, status_code, code in cases:
        response = await _http(RaisingRepository(error), method, path, json=body)
        assert (response.status_code, response.json()["error"]["code"]) == (status_code, code)
        assert "Traceback" not in response.text


@pytest.mark.asyncio
async def test_authorization_and_list_paths_unchanged() -> None:
    listed = await _http(None, "GET", "/api/v1/vehicles", headers={"X-Dev-Role": "UNKNOWN"})
    assert listed.status_code == 200 and listed.json()["total_items"] == 3
    patched = await _http(None, "PATCH", "/api/v1/vehicles/VEH-1047", json={"machine_no": "TC-13"}, headers={"X-Dev-Role": "UNKNOWN"})
    assert patched.status_code == 200  # ungated before and after 7H2 (M02 recorded, not changed)
    dashboard = await _http(None, "GET", "/api/v1/dashboard/fleet-status", headers={"X-Dev-Role": "UNKNOWN"})
    assert dashboard.status_code == 403
