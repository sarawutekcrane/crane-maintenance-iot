"""R2 Batch R2f-h4 B6 — D1 / D2 over Google Sheets, exercised with the REAL
installed gspread client on the FAKE HTTP transport (an emulation, not live
Google Sheets; every row SYNTHETIC; the additive V2 columns do not exist live).

Proves at the transport: a withdrawal is ONE appended row in the live header
order, every existing row byte-identical; the shared legacy readers of the same
tabs (`list_repairs`, `list_pm_work_orders`, the PM detail load and both legacy
history views) skip V2 rows — so a V2 WITHDRAWAL row (a role the legacy
`AssignmentRole` does not know) can never break them; a CLOSED job is refused
with zero writes.
"""
from __future__ import annotations

import copy

import pytest

from app.domain.common import PageParams
from app.domain.technician_assignment import ROLE_WITHDRAWAL
from app.repositories.google_sheets import schemas
from tests.test_technician_assignment_sheets_batch_r2f_h1 import (
    API,
    LEGACY_JOB,
    T1,
    T2,
    V2_JOB,
    _backend,
    _repo,
    _rows,
    _settings,
    assign,
    body,
    http,
)

PAGE = PageParams(page=1, page_size=50)


def wbody(*expected: str) -> dict:
    return {"expected_current": {"primary_technician_id": expected[0],
                                 "collaborator_technician_ids": list(expected[1:])}}


async def post_withdrawal(repo, job_id: str = V2_JOB, payload: dict | None = None):
    return await http("POST", f"{API}/repairs/{job_id}/technician-assignment-withdrawals", repo, role="MAINTENANCE",
                      json=payload or wbody(T1, T2), settings=_settings(v2=True))


@pytest.mark.asyncio
async def test_r2fh4b6_s01_withdrawal_appends_one_row_and_leaves_every_row_byte_identical() -> None:
    backend = _backend()
    repo = _repo(backend)
    await assign(repo, body(T1, T2))
    before = copy.deepcopy(backend.tabs["repair_assignment"])
    writes = len(backend.write_log)
    response = await post_withdrawal(repo)
    assert response.status_code == 200, response.text
    tab = backend.tabs["repair_assignment"]
    assert tab[: len(before)] == before and len(tab) == len(before) + 1
    assert len(backend.write_log) == writes + 1  # ONE append request
    row = _rows(backend, "repair_assignment")[-1]
    assert (row["assignment_role"], row["assignee_type"], row["assignee_id"], row["user_id"]) == (
        ROLE_WITHDRAWAL, "TECHNICIAN", "", "")
    read = await http("GET", f"{API}/repairs/{V2_JOB}/technician-assignments", repo, settings=_settings(v2=True))
    assert (read.json()["status"], read.json()["current"], len(read.json()["withdrawals"])) == ("NONE", None, 1)
    queue = await http("GET", f"{API}/repairs/v2-waiting-assignment", repo, role="MAINTENANCE",
                       settings=_settings(v2=True))
    assert {i["job_id"]: i["assignment_status"] for i in queue.json()["items"]}[V2_JOB] == "NONE"


@pytest.mark.asyncio
async def test_r2fh4b6_s02_shared_legacy_readers_skip_v2_withdrawal_rows() -> None:
    backend = _backend()
    repo = _repo(backend)
    await assign(repo, body(T1))
    assert (await post_withdrawal(repo, payload=wbody(T1))).status_code == 200
    # the Repair readers that parse every assignment row of the tab
    waiting, _ = await repo.list_repairs(None, None, None, PAGE, unassigned_only=True)
    mine, _ = await repo.list_repairs(None, None, None, PAGE, assigned_to="u-legacy")
    assert [r.repair_id for r in mine] == [LEGACY_JOB] and LEGACY_JOB not in [r.repair_id for r in waiting]
    history = await repo.list_repair_assignment_history(V2_JOB)
    assert history == []  # V2 rows are never legacy history entries
    assert [e.user_id for e in await repo.list_repair_assignment_history(LEGACY_JOB)] == ["u-legacy-old", "u-legacy"]


@pytest.mark.asyncio
async def test_r2fh4b6_s03_pm_list_and_detail_loads_skip_v2_withdrawal_rows() -> None:
    backend = _backend()
    header = list(schemas.PM_WORK_ASSIGNMENT_V2_SHEET.required_headers)
    pm_header = list(schemas.PM_WORK_ORDER_V2_SHEET.required_headers)
    backend.tabs["pm_work_order"] = [pm_header, [{
        "pm_work_order_id": "PMWO-SYN-1", "asset_type": "VEHICLE", "asset_id": "VEH-SYN-1", "pm_plan_id": "PMP-SYN",
        "revision_id": "PMREV-SYN", "status": "OPEN", "opened_at": "2026-01-05T08:00:00+00:00",
        "assignment_model": "TECHNICIAN_V2", "is_test_data": "FALSE"}.get(h, "") for h in pm_header]]
    withdrawal = {"pm_assignment_id": "PTA-" + "a" * 32 + "-1-1", "pm_work_order_id": "PMWO-SYN-1",
                  "assignment_role": ROLE_WITHDRAWAL, "assigned_at": "2026-01-06T08:00:00+00:00",
                  "assigned_by_user_id": "dev-user", "assignee_type": "TECHNICIAN", "assignee_id": "",
                  "request_id": "req-w", "request_fingerprint": "f", "is_test_data": "FALSE"}
    backend.tabs["pm_work_assignment"] = [header, [withdrawal.get(h, "") for h in header]]
    for sheet in (schemas.PM_WORK_RESULT_SHEET, schemas.PM_USED_PART_SHEET, schemas.PM_WORK_SCOPE_SHEET):
        backend.tabs[sheet.tab_name] = [list(sheet.required_headers)]
    repo = _repo(backend)
    items, total = await repo.list_pm_work_orders(None, None, PAGE)  # parses every assignment row of the tab
    assert total == 1 and items[0].primary_technician is None
    detail = await repo.get_pm_work_order("PMWO-SYN-1")  # the detail load parses this job's rows
    assert detail is not None and detail.work_order.collaborators == []
    assert await repo.list_pm_work_order_assignment_history("PMWO-SYN-1") == []


@pytest.mark.asyncio
async def test_r2fh4b6_s04_closed_job_refuses_assign_and_withdraw_with_zero_writes() -> None:
    backend = _backend()
    repo = _repo(backend)
    await assign(repo, body(T1))
    header, *rows = backend.tabs["repair_order"]
    for row in rows:
        if row[header.index("repair_id")] == V2_JOB:
            row[header.index("status")] = "CLOSED"
    before = copy.deepcopy(backend.tabs)
    writes = len(backend.write_log)
    for response in (await post_withdrawal(repo, payload=wbody(T1)),
                     await http("POST", f"{API}/repairs/{V2_JOB}/technician-assignments", repo, role="MAINTENANCE",
                                json=body(T2, expected=(T1,)), settings=_settings(v2=True))):
        assert (response.status_code, response.json()["error"]["code"]) == (409, "TECHNICIAN_ASSIGNMENT_JOB_CLOSED")
    assert backend.tabs == before and len(backend.write_log) == writes
