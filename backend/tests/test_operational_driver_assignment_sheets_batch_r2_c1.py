"""R2 Batch R2-C1 — E2 over the Google Sheets repository: FAIL CLOSED, ZERO calls.

DQ-1 / O1: E2 is Mock/TEST only before R11. The real installed gspread client
is wired to the FAKE HTTP transport (no credentials, network or live
workbook) and EVERY transport request is counted. For all four E2 routes, in
the TEST and the REAL context alike, the Google Sheets repository answers
before any request: no E2 tab (nor vehicle_master, driver_master, the R2f-f
history or vehicle_driver) is read, written or created. E2 is not a readiness
or health prerequisite (not in `_CORE_SCHEMAS`, no E2 Sheets schema).
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.operational_driver_timeline import OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB
from app.repositories.google_sheets import schemas
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from tests.test_crane_driver_responsibility_sheets_batch_r2f_f import _backend as r2ff_backend
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
BATCH = "SYN-R2C1-BATCH"
V1 = "VEH-SYN-1"
BODY = {"operation": "CREATE", "driver_id": "DRV-SYN-1", "mode": "FULL_DAY", "start_date": "2027-01-01",
        "end_date": "2027-01-02"}


class CountingBackend(RangeBackend):
    """Counts EVERY transport request (reads, metadata and writes alike)."""

    def __init__(self, tabs) -> None:
        super().__init__(tabs)
        self.transport_calls = 0

    def request(self, *args, **kwargs):  # noqa: D401 - transport hook
        self.transport_calls += 1
        return super().request(*args, **kwargs)


def _counting() -> CountingBackend:
    return CountingBackend(copy.deepcopy(r2ff_backend().tabs))


def _settings(context: str) -> Settings:
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                    google_application_credentials="fake.json", registry_data_context=context,
                    registry_test_batch_id=BATCH)


async def _call(repo, method: str, path: str, *, context: str, json=None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = _settings(context)
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": "DRIVER_DEPARTMENT_MANAGER", "X-Request-Id": str(uuid.uuid4())}
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


ROUTES = [
    ("GET", f"{API}/vehicles/{V1}/operational-driver-assignments", None),
    ("GET", f"{API}/vehicles/{V1}/operational-driver-assignment-history", None),
    ("GET", f"{API}/drivers/DRV-SYN-1/operational-driver-assignments", None),
    ("POST", f"{API}/vehicles/{V1}/operational-driver-assignment-operations", BODY),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_e2_sheets_test_context_fails_closed_with_zero_transport_calls(method, path, body) -> None:
    backend = _counting()
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), method, path, context="TEST", json=body)
    assert response.status_code == 501, response.text
    assert response.json()["error"]["code"] == "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE"
    assert backend.transport_calls == 0 and backend.requests == [] and backend.write_log == []
    assert backend.tabs == before and OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB not in backend.tabs


@pytest.mark.asyncio
async def test_e2_sheets_counter_positive_control() -> None:
    """The counter is real: the (unchanged) R2f-f read does reach the fake transport."""
    backend = _counting()
    response = await _call(_repo(backend), "GET", f"{API}/vehicles/{V1}/responsible-drivers", context="REAL")
    assert response.status_code == 200 and backend.transport_calls > 0


@pytest.mark.asyncio
async def test_e2_sheets_real_writes_are_refused_before_any_call_o1() -> None:
    backend = _counting()
    response = await _call(_repo(backend), "POST", ROUTES[3][1], context="REAL", json=BODY)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "E2_REAL_WRITES_NOT_ENABLED")
    assert backend.transport_calls == 0 and backend.write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ROUTES[:3])
async def test_e2_sheets_real_reads_fail_closed_with_zero_transport_calls(method, path, body) -> None:
    backend = _counting()
    response = await _call(_repo(backend), method, path, context="REAL", json=body)
    assert response.status_code == 501 and backend.transport_calls == 0


@pytest.mark.asyncio
async def test_e2_sheets_repository_methods_refuse_directly() -> None:
    from app.repositories.base import RegistryTableRead, RepositoryFeatureNotImplementedError

    backend = _counting()
    repo = _repo(backend)
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await repo.read_operational_driver_assignment_history_validated()
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await repo.append_operational_driver_assignment_rows(RegistryTableRead(rows=[], columns=frozenset()), [{}])
    assert backend.transport_calls == 0


def test_e2_sheets_is_not_a_readiness_or_schema_prerequisite() -> None:
    tabs = {s.tab_name for s in GoogleSheetsRepository._CORE_SCHEMAS}
    assert OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB not in tabs
    declared = {getattr(schemas, n).tab_name for n in dir(schemas) if hasattr(getattr(schemas, n), "tab_name")}
    assert OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB not in declared  # no E2 Sheets schema at all
    assert "vehicle_driver" in tabs  # unchanged until the separately authorized R2-C3 cutover
