"""R2 Batch R2f-h4 B3 — U1 V2 waiting-assignment queues over Google Sheets,
exercised with the REAL installed gspread client on the FAKE HTTP transport (an
emulation, not live Google Sheets; every row SYNTHETIC; the additive V2 columns do
NOT exist live).

Proves at the transport, through the HTTP routes: the CURRENT live state (no V2
columns) fails closed (500 schema, never an empty queue); with the columns
present REAL NONE jobs wait, a VALID one leaves after assignment, a damaged set
is DATA_INVALID; the TEST context never lists REAL jobs; 403 makes ZERO
requests; a transport failure is 503; and no request writes anything.
"""
from __future__ import annotations

import copy

import pytest

from app.repositories.google_sheets import schemas
from tests.test_technician_assignment_sheets_batch_r2f_h1 import (
    ASSIGN_LEGACY,
    OTHER_V2,
    ORDER_LEGACY,
    T1,
    T2,
    V2_JOB,
    _backend as _h1_backend,
    _repo,
    _settings,
    assign,
    body,
    http,
)

API = "/api/v1"
REPAIR_Q = f"{API}/repairs/v2-waiting-assignment"
PM_Q = f"{API}/pm/work-orders/v2-waiting-assignment"


def _backend(*, migrated: bool = True):
    if not migrated:
        return _h1_backend(order_header=ORDER_LEGACY, assign_header=ASSIGN_LEGACY)
    backend = _h1_backend()
    backend.tabs["pm_work_order"] = [list(schemas.PM_WORK_ORDER_V2_SHEET.required_headers)]
    backend.tabs["pm_work_assignment"] = [list(schemas.PM_WORK_ASSIGNMENT_V2_SHEET.required_headers)]
    return backend


async def get(backend, path: str, *, role: str = "MAINTENANCE", context: str | None = "REAL"):
    return await http("GET", path, _repo(backend), role=role, settings=_settings(context))


def waiting(response) -> list[tuple[str, str]]:
    assert response.status_code == 200, response.text
    return [(i["job_id"], i["assignment_status"]) for i in response.json()["items"]]


@pytest.mark.asyncio
async def test_r2fh4b3_s01_the_current_live_state_fails_closed_never_empty() -> None:
    backend = _backend(migrated=False)
    before = copy.deepcopy(backend.tabs)
    response = await get(backend, REPAIR_Q)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID"
    assert "items" not in response.json()
    assert backend.write_log == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2fh4b3_s02_none_waits_and_a_valid_assignment_leaves() -> None:
    backend = _backend()
    response = await get(backend, REPAIR_Q)
    assert sorted(waiting(response)) == sorted([(V2_JOB, "NONE"), (OTHER_V2, "NONE")])
    assert response.json()["data_context"] == "REAL"
    await assign(_repo(backend), body(T1, T2))
    writes = len(backend.write_log)
    assert waiting(await get(backend, REPAIR_Q)) == [(OTHER_V2, "NONE")]
    assert waiting(await get(backend, PM_Q)) == []
    assert len(backend.write_log) == writes  # the queue reads only


@pytest.mark.asyncio
async def test_r2fh4b3_s03_a_damaged_set_is_data_invalid() -> None:
    backend = _backend()
    await assign(_repo(backend), body(T1, T2))
    header, *rows = backend.tabs["repair_assignment"]
    role = header.index("assignment_role")
    backend.tabs["repair_assignment"] = [header, *(r for r in rows if r[role] != "COLLABORATOR")]
    response = await get(backend, REPAIR_Q)
    by_id = {i["job_id"]: i for i in response.json()["items"]}
    assert by_id[V2_JOB]["assignment_status"] == "DATA_INVALID"
    assert "SET_INCOMPLETE" in by_id[V2_JOB]["issues"]
    assert by_id[OTHER_V2]["assignment_status"] == "NONE"


@pytest.mark.asyncio
async def test_r2fh4b3_s04_test_context_never_lists_real_jobs() -> None:
    response = await get(_backend(), REPAIR_Q, context="TEST")
    assert waiting(response) == [] and response.json()["data_context"] == "TEST"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [REPAIR_Q, PM_Q])
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER", "NO_SUCH_ROLE"])
async def test_r2fh4b3_s05_403_makes_zero_requests(path, role) -> None:
    backend = _backend()
    response = await get(backend, path, role=role)
    assert response.status_code == 403
    assert backend.requests == [] and backend.write_log == []


@pytest.mark.asyncio
async def test_r2fh4b3_s06_unconfigured_is_503_with_zero_requests() -> None:
    backend = _backend()
    response = await get(backend, REPAIR_Q, context=None)
    assert (response.status_code, response.json()["error"]["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert backend.requests == []


@pytest.mark.asyncio
async def test_r2fh4b3_s07_a_transport_failure_is_503_never_a_partial_queue() -> None:
    backend = _backend()
    backend.fail_values_get = True
    response = await get(backend, REPAIR_Q)
    assert response.status_code == 503 and response.json()["error"]["code"].endswith("_READ_FAILED")
    assert "items" not in response.json()


def _set_job_cell(backend, job_id: str, column: str, value: str) -> None:
    header, *rows = backend.tabs["repair_order"]
    index = header.index(column)
    for row in rows:
        if row[header.index("repair_id")] == job_id:
            row[index] = value


@pytest.mark.asyncio
@pytest.mark.parametrize(("column", "value", "issue"), [
    ("status", "WAITING", "JOB_STATUS_INVALID"),
    ("status", "open", "JOB_STATUS_INVALID"),
    ("opened_at", "not-a-time", "JOB_OPENED_AT_INVALID"),
    ("is_test_data", "maybe", "JOB_SCOPE_FLAG_INVALID"),
    ("test_batch_id", "ANY-BATCH", "JOB_SCOPE_FLAG_INVALID"),  # FALSE + a batch: contradictory
])
async def test_r2fh4b3_s08_integrity_fix_fails_the_whole_queue_with_counts_only(column, value, issue) -> None:
    backend = _backend()
    _set_job_cell(backend, V2_JOB, column, value)
    before = copy.deepcopy(backend.tabs)
    response = await get(backend, REPAIR_Q)
    assert response.status_code == 500
    error = response.json()["error"]
    assert (error["code"], error["details"]) == ("TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", {"issues": {issue: 1}})
    assert V2_JOB not in response.text and "VEH-SYN-1" not in response.text and "items" not in response.json()
    assert backend.write_log == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2fh4b3_s09_a_closed_job_with_a_bad_opened_at_does_not_block() -> None:
    backend = _backend()
    _set_job_cell(backend, V2_JOB, "status", "CLOSED")
    _set_job_cell(backend, V2_JOB, "opened_at", "not-a-time")
    response = await get(backend, REPAIR_Q)
    assert waiting(response) == [(OTHER_V2, "NONE")]
    assert all(i["status"] == "OPEN" and i["opened_at"] for i in response.json()["items"])
