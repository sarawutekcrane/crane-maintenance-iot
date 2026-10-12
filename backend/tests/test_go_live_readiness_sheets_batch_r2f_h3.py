"""R2 Batch R2f-h3 — pre-Go-live report over Google Sheets, exercised with the
REAL installed gspread client on the FAKE HTTP transport (an emulation, not live
Google Sheets; every row SYNTHETIC; the additive V2 columns do NOT exist live).

Proves at the transport, through the HTTP route in the REAL context: the CURRENT
live state (no V2 columns) is reported as FAIL / BLOCKED, never READY; with the
columns present the report can reach READY; absent history tabs are listed as
ABSENT; a transport failure is 503; the D1 gate refuses before ANY request; and
every report call makes ZERO writes.
"""
from __future__ import annotations

import copy

import pytest

from app.repositories.google_sheets import schemas
from tests.test_technician_assignment_sheets_batch_r2f_h1 import (
    ASSIGN_LEGACY,
    ORDER_LEGACY,
    T1,
    T2,
    U1,
    U2,
    _backend as _h1_backend,
    _repo,
    _settings,
    assign,
    body,
    http,
)

PATH = "/api/v1/technician-assignment/go-live-readiness"
LISTS = {"intended_recipient_personnel_ids": ["P-1", "P-2"], "intended_my_work_personnel_ids": ["P-1", "P-2"]}
# Every tagged R2f source the report examines (none is live; C1 §27).
TAGGED = (schemas.PERSONNEL_TECHNICIAN_LINK_HISTORY_SHEET, schemas.PERSONNEL_ACCOUNT_LINK_HISTORY_SHEET,
          schemas.PERSONNEL_DRIVER_LINK_HISTORY_SHEET, schemas.PERSONNEL_LIFECYCLE_HISTORY_SHEET,
          schemas.DEPARTMENT_LIFECYCLE_HISTORY_SHEET, schemas.EQUIPMENT_CARETAKER_HISTORY_SHEET,
          schemas.CRANE_DRIVER_RESPONSIBILITY_HISTORY_SHEET, schemas.PERSONNEL_DEPARTMENT_HISTORY_SHEET,
          schemas.DEPARTMENT_REFERENCE_READ_SHEET)


def _backend(*, migrated: bool = True, tagged_tabs: bool = False):
    """The R2f-h1 fixture plus the reference masters the report reads. With
    `migrated=False` it is the CURRENT live state: legacy headers on all four V2
    runtime tabs. History tabs are absent (they are not live) unless
    `tagged_tabs` adds each as a header-only (empty) tab."""
    if migrated:
        backend = _h1_backend()
        backend.tabs["pm_work_order"] = [list(schemas.PM_WORK_ORDER_V2_SHEET.required_headers)]
        backend.tabs["pm_work_assignment"] = [list(schemas.PM_WORK_ASSIGNMENT_V2_SHEET.required_headers)]
    else:
        backend = _h1_backend(order_header=ORDER_LEGACY, assign_header=ASSIGN_LEGACY)
    backend.tabs["driver_master"] = [["driver_id", "driver_name_th"], ["DRV-SYN-1", "SENTINEL"]]
    backend.tabs["vehicle_master"] = [["vehicle_id", "registration_no"], ["VEH-SYN-1", "SENTINEL"]]
    backend.tabs["equipment_master"] = [["equipment_id", "equipment_name_th"], ["EQP-SYN-1", "SENTINEL"]]
    if tagged_tabs:
        for schema in TAGGED:
            backend.tabs[schema.tab_name] = [list(schema.required_headers)]
    return backend


async def report(backend, *, role: str = "ADMIN", json=None, settings=None):
    return await http("POST", PATH, _repo(backend), role=role, json=LISTS if json is None else json,
                      settings=settings or _settings())


@pytest.mark.asyncio
async def test_r2fh3_s01_the_current_live_state_is_never_ready() -> None:
    backend = _backend(migrated=False)
    before = copy.deepcopy(backend.tabs)
    response = await report(backend)
    assert response.status_code == 200, response.text
    payload = response.json()
    status = {c["id"]: c["status"] for c in payload["checks"]}
    assert status["C1-26-6"] == "FAIL" and status["C1-26-4"] == "BLOCKED" and status["C1-26-5"] == "BLOCKED"
    assert payload["overall"] == "NOT_READY"
    missing = {i["tab"] for c in payload["checks"] if c["id"] == "C1-26-6" for i in c["issues"]}
    assert missing == {"repair_order", "pm_work_order", "repair_assignment", "pm_work_assignment"}
    # Links still evaluate from the live-style masters (REAL): P-1 / P-2 resolve.
    assert status["C1-26-1"] == "PASS" and status["C1-26-2"] == "PASS"
    assert backend.write_log == [] and backend.writes == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2fh3_s02_with_the_columns_and_every_tagged_tab_present_the_report_can_be_ready() -> None:
    backend = _backend(tagged_tabs=True)
    await assign(_repo(backend), body(T1, T2))
    writes = len(backend.write_log)
    payload = (await report(backend)).json()
    assert [c["status"] for c in payload["checks"]] == ["PASS"] * 6 and payload["overall"] == "READY"
    assert payload["cutover_enabled"] is False
    assert payload["environment"]["production_authentication"] == "NOT_IMPLEMENTED (R11)"
    assert not [e for e in payload["coverage"] if e["status"] in ("ABSENT", "NOT_ASSESSABLE")]
    assert payload["gaps"] == []
    assert [(p["personnel_id"], p["account"]["user_id"]) for p in payload["population"]] == [("P-1", U1),
                                                                                             ("P-2", U2)]
    assert len(backend.write_log) == writes  # the report wrote nothing


@pytest.mark.asyncio
async def test_r2fh3_s03_a_damaged_live_style_set_fails_c1_26_5() -> None:
    backend = _backend()
    await assign(_repo(backend), body(T1, T2))
    header, *rows = backend.tabs["repair_assignment"]
    role = header.index("assignment_role")
    backend.tabs["repair_assignment"] = [header, *(r for r in rows if r[role] != "COLLABORATOR")]
    payload = (await report(backend)).json()
    check5 = next(c for c in payload["checks"] if c["id"] == "C1-26-5")
    assert check5["status"] == "FAIL" and "V2_SET_INCOMPLETE" in [i["code"] for i in check5["issues"]]
    assert payload["overall"] == "NOT_READY"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_r2fh3_s04_d1_refuses_before_any_request(role) -> None:
    backend = _backend()
    response = await report(backend, role=role)
    assert response.status_code == 403
    assert backend.requests == [] and backend.write_log == []


@pytest.mark.asyncio
async def test_r2fh3_s05_a_transport_failure_is_503_never_a_partial_report() -> None:
    backend = _backend()
    backend.fail_values_get = True
    response = await report(backend)
    assert (response.status_code, response.json()["error"]["code"]) == (503, "GO_LIVE_READINESS_READ_FAILED")


@pytest.mark.asyncio
async def test_r2fh3_s06_test_context_is_refused_with_zero_requests() -> None:
    backend = _backend()
    response = await report(backend, settings=_settings("TEST"))
    assert (response.status_code, response.json()["error"]["code"]) == (409, "GO_LIVE_READINESS_REQUIRES_REAL_CONTEXT")
    assert backend.requests == []


@pytest.mark.asyncio
async def test_r2fh3_s07_h301_absent_tagged_tabs_block_test_segregation_never_ready() -> None:
    # H3-01: the V2 columns are present, but the R2f history tabs are absent
    # (their live state today, C1 §27): listed ABSENT, C1-26-4 BLOCKED.
    backend = _backend()
    await assign(_repo(backend), body(T1, T2))
    payload = (await report(backend)).json()
    check4 = next(c for c in payload["checks"] if c["id"] == "C1-26-4")
    assert check4["status"] == "BLOCKED" and check4["evidence"]["coverage_complete"] is False
    assert payload["overall"] == "BLOCKED"
    absent = {e["tab"] for e in payload["coverage"] if e["status"] == "ABSENT"}
    assert absent == {schema.tab_name for schema in TAGGED}
    for tab in absent:
        assert any(g.startswith(f"{tab}: tab absent") for g in payload["gaps"]), tab


@pytest.mark.asyncio
async def test_r2fh3_s08_h301_test_reference_into_an_absent_target_master_is_blocked() -> None:
    # H3-01 (the review example): a TEST caretaker row names an equipment id
    # while equipment_master is absent — never clean.
    backend = _backend(tagged_tabs=True)
    await assign(_repo(backend), body(T1, T2))
    header = list(schemas.EQUIPMENT_CARETAKER_HISTORY_SHEET.required_headers)
    row = dict.fromkeys(header, "")
    row.update(record_id="ECH-SYN-1", equipment_id="EQP-SYN-9", is_test_data="TRUE", test_batch_id="SYN-B")
    backend.tabs["equipment_caretaker_history"] = [header, [row[h] for h in header]]
    del backend.tabs["equipment_master"]
    before = copy.deepcopy(backend.tabs)
    payload = (await report(backend)).json()
    check4 = next(c for c in payload["checks"] if c["id"] == "C1-26-4")
    assert check4["status"] == "BLOCKED" and payload["overall"] != "READY"
    assert any("equipment_caretaker_history.equipment_id: target equipment_master ABSENT" in g
               for g in payload["gaps"])
    assert backend.tabs == before
