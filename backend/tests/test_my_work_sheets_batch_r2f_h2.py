"""R2 Batch R2f-h2 — V2 My Work over Google Sheets, exercised with the REAL
installed gspread client on the FAKE HTTP transport (an emulation, not live
Google Sheets; every row SYNTHETIC; the additive V2 columns do not exist live).

Proves at the transport: REAL resolution through the live-style untagged
account / personnel / technician tabs; the CURRENT live state (no V2 columns)
fails closed instead of answering an empty list; a set damaged on the sheet
fails closed; live TEST cannot resolve; My Work makes ZERO writes.
"""
from __future__ import annotations

import copy

import pytest

from app.repositories.google_sheets import schemas
from tests.test_technician_assignment_sheets_batch_r2f_h1 import (
    ASSIGN_LEGACY,
    LEGACY_JOB,
    OTHER_V2,
    T1,
    T2,
    U1,
    U2,
    V2_JOB,
    _backend as _h1_backend,
    _repo,
    _settings,
    assign,
    body,
    http,
)

API = "/api/v1"


def _backend(**kw):
    """The R2f-h1 fixture with the EXTENDED pm_work_assignment header too (both
    assignment tabs migrated), unless the test passes legacy headers."""
    backend = _h1_backend(**kw)
    if kw.get("assign_header") != ASSIGN_LEGACY:
        backend.tabs["pm_work_assignment"] = [list(schemas.PM_WORK_ASSIGNMENT_V2_SHEET.required_headers)]
    return backend


async def my_work(backend, user: str | None, settings=None):
    return await http("GET", f"{API}/my-work", _repo(backend), user=user, settings=settings)


@pytest.mark.asyncio
async def test_r2fh2_s01_real_chain_resolves_on_the_live_style_tabs_with_zero_writes() -> None:
    backend = _backend()
    await assign(_repo(backend), body(T1, T2))
    await assign(_repo(backend), body(T2), job_id=OTHER_V2)
    before, writes = copy.deepcopy(backend.tabs), len(backend.write_log)
    mine = (await my_work(backend, U1)).json()
    assert (mine["resolution"], mine["technician_id"]) == ("RESOLVED", T1)
    assert [(i["job_id"], i["assignment_role"]) for i in mine["items"]] == [(V2_JOB, "PRIMARY")]
    theirs = (await my_work(backend, U2)).json()
    assert theirs["technician_id"] == "0042"  # exact text, no numeric coercion
    assert sorted((i["job_id"], i["assignment_role"]) for i in theirs["items"]) == [
        (V2_JOB, "COLLABORATOR"), (OTHER_V2, "PRIMARY")]
    assert LEGACY_JOB not in {i["job_id"] for i in mine["items"] + theirs["items"]}
    assert backend.tabs == before and len(backend.write_log) == writes


@pytest.mark.asyncio
async def test_r2fh2_s02_the_current_live_state_fails_closed_never_an_empty_list() -> None:
    backend = _backend(assign_header=ASSIGN_LEGACY)  # no V2 columns live yet
    response = await my_work(backend, U1)
    assert (response.status_code, response.json()["error"]["code"]) == (500, "TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID")
    assert backend.write_log == []


@pytest.mark.asyncio
async def test_r2fh2_s03_a_set_damaged_on_the_sheet_fails_closed() -> None:
    backend = _backend()
    await assign(_repo(backend), body(T2, T1))
    header, *rows = backend.tabs["repair_assignment"]
    role = header.index("assignment_role")
    backend.tabs["repair_assignment"] = [header, *(r for r in rows if r[role] != "COLLABORATOR")]
    response = await my_work(backend, U1)  # U1's own (lost) COLLABORATOR row
    assert (response.status_code, response.json()["error"]["code"]) == (500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID")
    assert response.json()["error"]["details"]["issues"] == {"SET_INCOMPLETE": 1}


@pytest.mark.asyncio
async def test_r2fh2_s04_live_test_cannot_resolve_and_unauthenticated_reads_nothing() -> None:
    backend = _backend()
    await assign(_repo(backend), body(T1))
    payload = (await my_work(backend, U1, settings=_settings("TEST"))).json()
    assert (payload["resolution"], payload["items"]) == ("ACCOUNT_SCOPE_UNPROVEN", None)
    unconfigured = await my_work(backend, U1, settings=_settings(None))
    assert (unconfigured.status_code, unconfigured.json()["error"]["code"]) == (
        503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
