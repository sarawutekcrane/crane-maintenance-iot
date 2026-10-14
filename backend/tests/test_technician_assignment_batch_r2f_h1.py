"""R2 Batch R2f-h1 — V2 Technician assignment core, mock / service level.

The R2f-h1 implementation authorization (Option A). Every row is SYNTHETIC and
labelled; no live workbook value or production count is used. TEST-scoped
personnel / technicians / accounts are explicit synthetic fixtures (scope TEST
+ batch), never derived from an id. REAL-context cases run against the
services directly (mock mode is always the TEST context at the API).

Batch-local ids (the governance list 1-20): R2FH1-CUT (1, 20), -MARK (2),
-SEP (3), -GATE (4, 5), -SCOPE (6, 18), -REPLAY (7), -STALE (8), -SET (9),
-TIE (10), -APPEND (11, 13), -LEGACY (14, 19), -REC (15), -ATT (16),
-AUTH (17), -W1. Missing V2 live columns (12) and live-header byte equivalence
are proven at the transport in the `_sheets_` companion file.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.context import RequestContext
from app.domain import authz
from app.domain.asset import AssetType
from app.domain.equipment_caretaker import EquipmentCaretakerService
from app.domain.meter_service import MeterService
from app.domain.pm_service import PmService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.repair import RepairSourceType
from app.domain.repair_service import RepairService
from app.domain.technician_assignment import (
    PM,
    REPAIR,
    derive_assignment_state,
    AssignmentCutover,
    TechnicianAssignmentService,
    cutover_from_settings,
)
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_TEST
from tests.test_relationship_read_batch_r2f_a import RelSpy, account, person, tech

API = "/api/v1"
BATCH = MOCK_TEST_BATCH_ID
VEHICLE = "VEH-1046"
T1, T2, T3, T4 = "TEC-SYN-1", "TEC-SYN-2", "TEC-SYN-3", "TEC-SYN-4"
U1, U2, U3 = "USR-SYN-1", "USR-SYN-2", "USR-SYN-3"
REASON = "มอบหมายช่าง (ทดสอบ)"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def tp(pid: str, **kw) -> dict[str, str]:
    """A TEST-scope personnel row of the server batch."""
    return person(pid, test=True, batch=BATCH, **kw)


def tt(tid: str, **kw):
    return tech(tid, scope=REFERENCE_SCOPE_TEST, batch=BATCH, **kw)


def ta(uid: str):
    return account(uid, scope=REFERENCE_SCOPE_TEST, batch=BATCH)


def repo_with(people=None, technicians=None, accounts=None) -> RelSpy:
    return RelSpy(
        people=people if people is not None else [tp("P-1", technician_id=T1, user_id=U1),
                                                  tp("P-2", technician_id=T2, user_id=U2),
                                                  tp("P-3", technician_id=T3, user_id=U3),
                                                  tp("P-4", technician_id=T4)],
        technicians=technicians if technicians is not None else [tt(T1), tt(T2), tt(T3), tt(T4)],
        accounts=accounts if accounts is not None else [ta(U1), ta(U2), ta(U3)],
    )


def cut(enabled: bool = True, context: str | None = "TEST", batch: str = BATCH, live: bool = False):
    return AssignmentCutover(enabled=enabled, data_context=context, test_batch_id=batch, live=live)


def repair_service(repo, **kw) -> RepairService:
    return RepairService(repo, MeterService(repo), assignment_cutover=cut(**kw))


def pm_service(repo, **kw) -> PmService:
    return PmService(repo, MeterService(repo), assignment_cutover=cut(**kw))


def ta_service(repo, **kw) -> TechnicianAssignmentService:
    return TechnicianAssignmentService(repo, cut(**kw))


async def new_repair(repo, **kw) -> str:
    detail = await repair_service(repo, **kw).create_repair(AssetType.VEHICLE, VEHICLE, RepairSourceType.MANUAL,
                                                            None, None, None, None, "dev-user")
    return detail.repair.repair_id


async def new_pm(repo, **kw) -> str:
    service = pm_service(repo, **kw)
    plan_id = (await service.list_applicable_plan_status(AssetType.VEHICLE, VEHICLE))[0].plan.pm_plan_id
    detail = await service.open_work_order(AssetType.VEHICLE, VEHICLE, plan_id, None, "dev-user", None)
    return detail.work_order.pm_work_order_id


def body(primary: str, *collaborators: str, expected: tuple[str, ...] | None = None, reason: str | None = None):
    out: dict = {"primary_technician_id": primary, "collaborator_technician_ids": list(collaborators),
                 "expected_current": None if expected is None else {
                     "primary_technician_id": expected[0], "collaborator_technician_ids": list(expected[1:])}}
    if reason is not None:
        out["reason_th"] = reason
    return out


async def assign(repo, job_id: str, payload: dict, *, kind=REPAIR, request_id: str | None = None, **kw):
    return await ta_service(repo, **kw).assign(kind, job_id, payload, request_id=request_id or str(uuid.uuid4()),
                                               user_id="dev-user")


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


def v2_rows(repo, kind: str = "REPAIR") -> list[dict[str, str]]:
    return repo._technician_assignment_rows[kind]


def settings(v2: bool) -> Settings:
    return Settings(technician_assignment_v2_enabled=v2)


async def http(method: str, path: str, repo, *, role: str = "MAINTENANCE", user: str | None = None, json=None,
               request_id: str | None = "auto", v2: bool = False):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings(v2)
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": role}
    if user is not None:
        headers["X-Dev-User-Id"] = user
    if request_id is not None:
        headers["X-Request-Id"] = str(uuid.uuid4()) if request_id == "auto" else request_id
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def ctx(user: str | None, *caps: str) -> RequestContext:
    return RequestContext(request_id=str(uuid.uuid4()), user_id=user, is_dev_auth=True, capabilities=frozenset(caps))


# ---------------------------------------------------------------------------
# R2FH1-CUT — the cutover setting (governance 1, 20)
# ---------------------------------------------------------------------------


def test_r2fh1_cut_01_setting_defaults_off_and_is_never_auto_enabled(monkeypatch) -> None:
    monkeypatch.delenv("TECHNICIAN_ASSIGNMENT_V2_ENABLED", raising=False)
    assert Settings(_env_file=None).technician_assignment_v2_enabled is False
    assert cutover_from_settings(Settings(_env_file=None)).enabled is False
    assert RepairService(RelSpy(), MeterService(RelSpy()))._cutover.enabled is False
    assert PmService(RelSpy(), MeterService(RelSpy()))._cutover.enabled is False


@pytest.mark.asyncio
async def test_r2fh1_cut_02_off_creates_legacy_jobs_exactly_as_before() -> None:
    repo = repo_with()
    response = await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEHICLE,
                                                                 "source_type": "MANUAL", "primary_technician": "u-a"})
    assert response.status_code == 200
    job = repo._repairs[response.json()["repair"]["repair_id"]]
    assert (job.assignment_model, job.is_test_data, job.test_batch_id) == ("", "", "")
    assert set(response.json()["repair"]) == {"repair_id", "asset_type", "asset_id", "source_type", "source_id",
                                              "category", "symptom", "meter_snapshot_id", "status", "opened_at",
                                              "opened_by", "closed_at", "closed_by", "close_note",
                                              "closed_snapshot_id", "primary_technician", "collaborators",
                                              # R2 Batch R2f-h4 precondition (deliberate evolution, owner
                                              # decision D-H4-1): the additive read-only model signal.
                                              "assignment_model"}
    assert response.json()["repair"]["assignment_model"] == "LEGACY"
    assert v2_rows(repo) == []


@pytest.mark.asyncio
async def test_r2fh1_cut_03_on_marks_new_jobs_only_and_existing_jobs_never_change() -> None:
    repo = repo_with()
    legacy_id = await new_repair(repo, enabled=False)
    legacy_pm = await new_pm(repo, enabled=False)
    v2_id = await new_repair(repo)
    v2_pm = await new_pm(repo)
    assert repo._repairs[legacy_id].assignment_model == "" and repo._pm_work_orders[legacy_pm].assignment_model == ""
    for job in (repo._repairs[v2_id], repo._pm_work_orders[v2_pm]):
        assert (job.assignment_model, job.is_test_data, job.test_batch_id) == ("TECHNICIAN_V2", "TRUE", BATCH)
    # Turning the setting OFF again changes no existing job.
    await new_repair(repo, enabled=False)
    assert repo._repairs[v2_id].assignment_model == "TECHNICIAN_V2"
    assert repo._repairs[legacy_id].assignment_model == ""
    assert (await assign(repo, v2_id, body(T1))).changed
    assert await code_of(repair_service(repo, enabled=False).assign(v2_id, "u-a", [])) == "ASSIGNMENT_MODEL_MISMATCH"


@pytest.mark.asyncio
async def test_r2fh1_cut_04_on_refuses_an_inline_legacy_assignee_before_any_write() -> None:
    repo = repo_with()
    before = (len(repo._repairs), len(repo._meter_snapshots))
    response = await http("POST", f"{API}/repairs", repo, v2=True,
                          json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL",
                                "collaborators": ["u-b"]})
    assert _code(response) == (422, "ASSIGNMENT_MODEL_MISMATCH")
    assert (len(repo._repairs), len(repo._meter_snapshots)) == before
    ok = await http("POST", f"{API}/repairs", repo, v2=True,
                    json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL"})
    assert ok.status_code == 200
    assert repo._repairs[ok.json()["repair"]["repair_id"]].assignment_model == "TECHNICIAN_V2"


@pytest.mark.asyncio
async def test_r2fh1_cut_05_a_request_converted_while_on_becomes_a_v2_job() -> None:
    from app.domain.repair_request_service import RepairRequestService

    repo = repo_with()
    service = repair_service(repo)
    requests = RepairRequestService(repo, service, MeterService(repo))
    created, _ = await requests.create(vehicle_id=VEHICLE, reported_by_user_id="dev-user", reporter_type=None,
                                       reporter_driver_id=None, reporter_name_snapshot_th=None, report_channel=None,
                                       symptom_th="ทดสอบ", priority=None, note_th=None)
    rid = created.repair_request_id
    assert await code_of(requests.convert(rid, "dev-user", None, "u-a", None)) == "ASSIGNMENT_MODEL_MISMATCH"
    assert (await requests.get(rid)).request_status != "CONVERTED"
    detail = await requests.convert(rid, "dev-user", None, None, None)
    assert repo._repairs[detail.repair.repair_id].assignment_model == "TECHNICIAN_V2"


@pytest.mark.asyncio
async def test_r2fh1_cut_06_on_requires_the_write_context_before_any_write() -> None:
    repo = repo_with()
    before = (len(repo._repairs), len(repo._meter_snapshots))
    assert await code_of(new_repair(repo, context=None)) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert await code_of(new_repair(repo, batch=" ")) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert await code_of(new_pm(repo, context=None)) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert (len(repo._repairs), len(repo._meter_snapshots)) == before


# ---------------------------------------------------------------------------
# R2FH1-MARK — marker integrity across later job updates (governance 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_mark_01_marker_survives_actions_parts_close_and_assignment() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    service = repair_service(repo)
    await assign(repo, job_id, body(T1))
    await service.add_action(job_id, "ทำงาน", "dev-user", [])
    await service.add_part(job_id, "ชิ้นส่วน", 1, "ea", "dev-user")
    await service.close_repair(job_id, "dev-user", "ปิดงาน")
    job = repo._repairs[job_id]
    assert (job.assignment_model, job.is_test_data, job.test_batch_id) == ("TECHNICIAN_V2", "TRUE", BATCH)
    assert (job.primary_technician, job.collaborators) == (None, [])  # mirrors stay blank on a V2 job


# ---------------------------------------------------------------------------
# R2FH1-SEP — legacy / V2 endpoint separation (governance 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_sep_01_legacy_routes_refuse_v2_jobs_with_zero_assignment_writes() -> None:
    repo = repo_with()
    repair_id, pm_id = await new_repair(repo), await new_pm(repo)
    for path, payload in ((f"{API}/repairs/{repair_id}/assign", {"primary_technician": "u-a"}),
                          (f"{API}/pm/work-orders/{pm_id}/assign", {"primary_technician": "u-a"})):
        assert _code(await http("POST", path, repo, json=payload)) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    for path in (f"{API}/repairs/{repair_id}/assignment-history", f"{API}/pm/work-orders/{pm_id}/assignment-history"):
        assert _code(await http("GET", path, repo)) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert repo._repair_assignment_history.get(repair_id, []) == []
    assert repo._pm_assignment_history.get(pm_id, []) == []
    assert "assign_repair" not in repo.calls and "assign_pm_work_order" not in repo.calls


@pytest.mark.asyncio
async def test_r2fh1_sep_02_v2_routes_refuse_legacy_jobs() -> None:
    repo = repo_with()
    repair_id, pm_id = await new_repair(repo, enabled=False), await new_pm(repo, enabled=False)
    for path in (f"{API}/repairs/{repair_id}/technician-assignments",
                 f"{API}/pm/work-orders/{pm_id}/technician-assignments"):
        assert _code(await http("POST", path, repo, json=body(T1))) == (409, "ASSIGNMENT_MODEL_MISMATCH")
        assert _code(await http("GET", path, repo)) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert v2_rows(repo) == [] and v2_rows(repo, "PM") == []
    assert "read_work_assignment_v2_rows" not in repo.calls


@pytest.mark.asyncio
async def test_r2fh1_sep_03_unknown_marker_fails_closed_on_every_branch() -> None:
    repo = repo_with()
    job_id = await new_repair(repo, enabled=False)
    repo._repairs[job_id] = repo._repairs[job_id].model_copy(update={"assignment_model": "SOMETHING"})
    assert await code_of(repair_service(repo).assign(job_id, "u-a", [])) == "ASSIGNMENT_MODEL_DATA_INVALID"
    assert await code_of(assign(repo, job_id, body(T1))) == "ASSIGNMENT_MODEL_DATA_INVALID"
    assert await code_of(repair_service(repo).authorize_recording(job_id, ctx("u-a"), authz.CAN_MANAGE_REPAIR,
                                                                  "x")) == "ASSIGNMENT_MODEL_DATA_INVALID"


@pytest.mark.asyncio
async def test_r2fh1_sep_04_legacy_queues_never_list_v2_jobs() -> None:
    repo = repo_with()
    legacy_id = await new_repair(repo, enabled=False)
    v2_id = await new_repair(repo)
    waiting = await http("GET", f"{API}/repairs/waiting-assignment", repo)
    ids = [r["repair_id"] for r in waiting.json()["items"]]
    assert legacy_id in ids and v2_id not in ids
    await assign(repo, v2_id, body(T1))
    mine = await http("GET", f"{API}/repairs/my-work", repo, role="TECHNICIAN", user=U1)
    assert v2_id not in [r["repair_id"] for r in mine.json()["items"]]  # V2 My Work is R2f-h2
    everything = await http("GET", f"{API}/repairs", repo)
    assert v2_id in [r["repair_id"] for r in everything.json()["items"]]  # plain lists are unchanged


# ---------------------------------------------------------------------------
# R2FH1-GATE — BOTH-ACTIVE gate, missing / ambiguous links (governance 4, 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("people", "technicians", "expected"), [
    ([tp("P-1", technician_id=T1)], [tt(T1, status="INACTIVE")], "TECHNICIAN_NOT_ACTIVE"),
    ([tp("P-1", technician_id=T1)], [tt(T1, status="active")], "TECHNICIAN_NOT_ACTIVE"),
    ([tp("P-1", technician_id=T1)], [tt(T1, status="")], "TECHNICIAN_NOT_ACTIVE"),
    ([{**tp("P-1", technician_id=T1), "active_status": "INACTIVE"}], [tt(T1)], "PERSONNEL_NOT_ACTIVE"),
    ([tp("P-9", technician_id=T2)], [tt(T1)], "TECHNICIAN_PERSONNEL_UNRESOLVED"),
    ([tp("P-1", technician_id=T1), tp("P-2", technician_id=T1)], [tt(T1)], "TECHNICIAN_PERSONNEL_AMBIGUOUS"),
    ([tp("P-1", technician_id=T1)], [tt(T1), tt(T1)], "TECHNICIAN_ID_AMBIGUOUS"),
    ([tp("P-1", technician_id=T1)], [tt(T2)], "TECHNICIAN_NOT_FOUND"),
])
async def test_r2fh1_gate_01_every_new_assignee_passes_the_both_active_gate(people, technicians, expected) -> None:
    for role_index in (0, 1):  # the PRIMARY and a COLLABORATOR are gated alike
        extra_t, extra_p = tt("TEC-OK"), tp("P-OK", technician_id="TEC-OK")
        repo = repo_with(people=[*people, extra_p], technicians=[*technicians, extra_t])
        job_id = await new_repair(repo)
        payload = body(T1) if role_index == 0 else body("TEC-OK", T1)
        assert await code_of(assign(repo, job_id, payload)) == expected
        assert v2_rows(repo) == []


@pytest.mark.asyncio
async def test_r2fh1_gate_02_parity_with_the_r2f_d_gate() -> None:
    """Same fixtures -> the same code (or success) as the accepted R2f-d gate."""
    scenarios = [
        ([tp("P-1", technician_id=T1)], [tt(T1)]),
        ([tp("P-1", technician_id=T1)], [tt(T1, status="INACTIVE")]),
        ([{**tp("P-1", technician_id=T1), "active_status": "INACTIVE"}], [tt(T1)]),
        ([], [tt(T1)]),
        ([tp("P-1", technician_id=T1), tp("P-2", technician_id=T1)], [tt(T1)]),
        ([tp("P-1", technician_id=T1)], [tt(T1), tt(T1)]),
        ([tp("P-1", technician_id=T1)], []),
        ([tp("P-1", technician_id=T1)], [tech(T1)]),  # REAL-only technician, TEST request
    ]
    for people, technicians in scenarios:
        repo = repo_with(people=people, technicians=technicians)
        try:
            await EquipmentCaretakerService(repo, "TEST", BATCH)._check_new_caretaker(T1, "TEST")
            r2fd = None
        except ApiError as exc:
            r2fd = (exc.code, exc.status_code)
        job_id = await new_repair(repo)
        try:
            await assign(repo, job_id, body(T1))
            r2fh = None
        except ApiError as exc:
            r2fh = (exc.code, exc.status_code)
        assert r2fh == r2fd, (people, technicians)


@pytest.mark.asyncio
async def test_r2fh1_gate_03_only_new_members_are_gated_and_no_lifecycle_cascade() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1))
    repo._technician_master = [tt(T1, status="INACTIVE"), tt(T2), tt(T3), tt(T4)]
    # T1 stays (not a new assignee); T2 joins and passes the gate.
    outcome = await assign(repo, job_id, body(T1, T2, expected=(T1,)))
    assert outcome.changed and outcome.current.members == {T1, T2}
    # Re-adding the inactive T1 after removing it is a NEW assignment: refused.
    await assign(repo, job_id, body(T2, expected=(T1, T2)))
    assert await code_of(assign(repo, job_id, body(T2, T1, expected=(T2,)))) == "TECHNICIAN_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_r2fh1_gate_04_body_shape_rules() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    assert await code_of(assign(repo, job_id, body(T1, T1))) == "TECHNICIAN_ASSIGNMENT_DUPLICATE_ASSIGNEE"
    assert await code_of(assign(repo, job_id, body(T1, T2, T2))) == "TECHNICIAN_ASSIGNMENT_DUPLICATE_ASSIGNEE"
    assert await code_of(assign(repo, job_id, body(" "))) == "TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED"
    assert await code_of(assign(repo, job_id, body(T1, ""))) == "VALIDATION_ERROR"
    assert await code_of(assign(repo, job_id, body(T1, reason=" "))) == "REASON_REQUIRED"
    assert await code_of(assign(repo, job_id, body(T1, reason="x" * 501))) == "REASON_REQUIRED"
    assert v2_rows(repo) == []
    path = f"{API}/repairs/{job_id}/technician-assignments"
    for payload in ({"primary_technician_id": T1},  # expected_current is required
                    {**body(T1), "user_id": "u-a"},  # server-set fields are refused
                    {**body(T1), "assignee_type": "TECHNICIAN"},
                    {**body(T1), "is_test_data": "TRUE"},
                    {"primary_technician_id": None, "expected_current": None},
                    {**body(T1), "collaborator_technician_ids": []} | {"assigned_at": "2026-01-01T00:00:00+00:00"}):
        response = await http("POST", path, repo, json=payload)
        assert response.status_code == 422, payload
    assert v2_rows(repo) == []


# ---------------------------------------------------------------------------
# R2FH1-SCOPE — cross-scope references; live TEST refused (governance 6, 18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_scope_01_test_never_resolves_real_or_other_batch_references() -> None:
    cases = [
        ([tp("P-1", technician_id=T1)], [tech(T1)], "TECHNICIAN_SCOPE_UNPROVEN"),
        ([tp("P-1", technician_id=T1)], [tech(T1, scope=REFERENCE_SCOPE_TEST, batch="OTHER")],
         "TECHNICIAN_SCOPE_UNPROVEN"),
        ([person("P-1", technician_id=T1)], [tt(T1)], "TECHNICIAN_PERSONNEL_UNRESOLVED"),  # REAL personnel
        ([person("P-1", technician_id=T1, test=True, batch="OTHER")], [tt(T1)], "TECHNICIAN_PERSONNEL_UNRESOLVED"),
    ]
    for people, technicians, expected in cases:
        repo = repo_with(people=people, technicians=technicians)
        job_id = await new_repair(repo)
        assert await code_of(assign(repo, job_id, body(T1))) == expected
        assert v2_rows(repo) == []


@pytest.mark.asyncio
async def test_r2fh1_scope_02_real_never_resolves_test_fixtures_and_jobs_stay_in_their_scope() -> None:
    real_kw = {"context": "REAL", "batch": ""}
    repo = repo_with(people=[person("P-R", technician_id=T1), tp("P-T", technician_id=T2)],
                     technicians=[tech(T1), tt(T2)])
    real_job = await new_repair(repo, **real_kw)
    test_job = await new_repair(repo)
    assert (repo._repairs[real_job].is_test_data, repo._repairs[real_job].test_batch_id) == ("FALSE", "")
    assert await code_of(assign(repo, real_job, body(T2), **real_kw)) == "TECHNICIAN_NOT_FOUND"
    assert (await assign(repo, real_job, body(T1), **real_kw)).changed
    # A request of the other scope never touches the job.
    assert await code_of(assign(repo, real_job, body(T2))) == "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    assert await code_of(assign(repo, test_job, body(T1), **real_kw)) == "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    assert await code_of(ta_service(repo, **real_kw).read(REPAIR, test_job)) == "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    rows = v2_rows(repo)
    assert [(r["is_test_data"], r["test_batch_id"]) for r in rows] == [("FALSE", "")]


@pytest.mark.asyncio
async def test_r2fh1_scope_03_live_test_v2_fails_closed_with_zero_calls() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    repo.calls.clear()
    assert await code_of(assign(repo, job_id, body(T1), live=True)) == "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED"
    assert repo.calls == []
    assert await code_of(new_repair(repo, live=True)) == "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED"
    assert await code_of(new_pm(repo, live=True)) == "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED"
    assert "create_repair" not in repo.calls and "create_pm_work_order" not in repo.calls
    assert v2_rows(repo) == []


@pytest.mark.asyncio
async def test_r2fh1_scope_04_invalid_job_scope_flags_fail_closed() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    repo._repairs[job_id] = repo._repairs[job_id].model_copy(update={"is_test_data": "yes"})
    assert await code_of(assign(repo, job_id, body(T1))) == "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID"


# ---------------------------------------------------------------------------
# R2FH1-REPLAY / -STALE (governance 7, 8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_replay_01_identical_resend_replays_and_a_reused_id_is_refused() -> None:
    repo = repo_with()
    job_a, job_b = await new_repair(repo), await new_repair(repo)
    rid = str(uuid.uuid4())
    first = await assign(repo, job_a, body(T1, T2), request_id=rid)
    count = len(v2_rows(repo))
    again = await assign(repo, job_a, body(T1, T2), request_id=rid)
    assert again.replayed and again.record_ids == first.record_ids and len(v2_rows(repo)) == count
    assert await code_of(assign(repo, job_a, body(T1, T3, expected=(T1, T2)), request_id=rid)) == "REQUEST_ID_REUSED"
    assert await code_of(assign(repo, job_b, body(T1, T2), request_id=rid)) == "REQUEST_ID_REUSED"
    assert len(v2_rows(repo)) == count


@pytest.mark.asyncio
async def test_r2fh1_replay_03_a_matching_fingerprint_on_another_job_is_never_a_replay() -> None:
    """Defence in depth: stored rows of ANOTHER job that carry this request's id
    and this job's fingerprint (only possible through tampering) are refused."""
    from app.domain.request_replay import request_fingerprint

    repo = repo_with()
    job_a, job_b = await new_repair(repo), await new_repair(repo)
    rid = str(uuid.uuid4())
    await assign(repo, job_b, body(T1), request_id=rid)
    for row in v2_rows(repo):
        row["request_fingerprint"] = request_fingerprint(REPAIR.fingerprint_op, job_a, None, body(T1))
    assert await code_of(assign(repo, job_a, body(T1), request_id=rid)) == "REQUEST_ID_REUSED"


@pytest.mark.asyncio
async def test_r2fh1_replay_02_a_pm_request_id_is_independent_of_a_repair_one() -> None:
    repo = repo_with()
    rid = str(uuid.uuid4())
    repair_id, pm_id = await new_repair(repo), await new_pm(repo)
    await assign(repo, repair_id, body(T1), request_id=rid)
    assert (await assign(repo, pm_id, body(T1), kind=PM, request_id=rid)).changed  # a different tab


@pytest.mark.asyncio
async def test_r2fh1_stale_01_stale_is_checked_before_no_op() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1, T2))
    count = len(v2_rows(repo))
    # Requested == current, but the expectation is wrong: STALE, never a silent no-op.
    assert await code_of(assign(repo, job_id, body(T1, T2))) == "TECHNICIAN_ASSIGNMENT_STALE"
    assert await code_of(assign(repo, job_id, body(T1, T2, expected=(T1,)))) == "TECHNICIAN_ASSIGNMENT_STALE"
    assert await code_of(assign(repo, job_id, body(T3, expected=(T2, T1)))) == "TECHNICIAN_ASSIGNMENT_STALE"
    # A correct expectation of the same set is a no-op; collaborator order is irrelevant.
    noop = await assign(repo, job_id, body(T1, T2, expected=(T1, T2)))
    assert noop.changed is False and noop.replayed is False
    assert (await assign(repo, job_id, body(T1, T2, expected=(T1, T2))) ).changed is False
    assert len(v2_rows(repo)) == count


# ---------------------------------------------------------------------------
# R2FH1-SET / -TIE — set integrity and same-instant ambiguity (governance 9, 10)
# ---------------------------------------------------------------------------


def _tamper(name: str, rows: list[dict[str, str]], job_id: str, other_job: str) -> None:
    first = rows[0]
    if name == "TWO_PRIMARIES":
        rows.append({**first, "repair_assignment_id": "RTA-x2", "assignee_id": T2})
    elif name == "NO_PRIMARY":
        first["assignment_role"] = "COLLABORATOR"
    elif name == "DUPLICATE_ASSIGNEE":
        rows.append({**first, "repair_assignment_id": "RTA-x3", "assignment_role": "COLLABORATOR"})
    elif name == "NON_UNIFORM_TIME":
        rows.append({**first, "repair_assignment_id": "RTA-x4", "assignee_id": T2, "assignment_role": "COLLABORATOR",
                     "assigned_at": "2020-01-01T00:00:00+00:00"})
    elif name == "LEGACY_ROW":
        rows.append({**dict.fromkeys(first, ""), "repair_assignment_id": "RASG-9001", "repair_id": job_id,
                     "user_id": "u-a", "assignment_role": "PRIMARY", "assigned_at": first["assigned_at"],
                     "active_status": "TRUE"})
    elif name == "USER_ID":
        first["user_id"] = "u-a"
    elif name == "LEGACY_STATUS":
        first["active_status"] = "TRUE"
    elif name == "ASSIGNEE_TYPE":
        first["assignee_type"] = "USER"
    elif name == "SPANS_TWO_JOBS":
        rows.append({**first, "repair_assignment_id": "RTA-x5", "repair_id": other_job})
    elif name == "DUPLICATE_RECORD_ID":
        rows.append({**first, "repair_id": other_job, "request_id": "other"})
    elif name == "RECORD_PREFIX":
        first["repair_assignment_id"] = "RASG-0001"
    elif name == "ROW_SCOPE":
        first["test_batch_id"] = "OTHER"
    elif name == "REFERENCE_MISSING":
        pass  # the stored row is untouched; its technician leaves the master (see the test body)
    elif name == "BLANK_REQUEST_ID":
        first["request_id"] = ""
    elif name == "BAD_TIME":
        first["assigned_at"] = "yesterday"


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "issue"), [
    ("TWO_PRIMARIES", "SET_PRIMARY_COUNT_INVALID"), ("NO_PRIMARY", "SET_PRIMARY_COUNT_INVALID"),
    ("DUPLICATE_ASSIGNEE", "SET_DUPLICATE_ASSIGNEE"), ("NON_UNIFORM_TIME", "SET_FIELDS_INCONSISTENT"),
    ("LEGACY_ROW", "LEGACY_ROW_ON_V2_JOB"), ("USER_ID", "V2_USER_ID_NOT_BLANK"),
    ("LEGACY_STATUS", "V2_LEGACY_STATUS_NOT_BLANK"), ("ASSIGNEE_TYPE", "ASSIGNEE_TYPE_INVALID"),
    ("SPANS_TWO_JOBS", "REQUEST_ID_INCONSISTENT"), ("DUPLICATE_RECORD_ID", "DUPLICATE_RECORD_ID"),
    ("RECORD_PREFIX", "RECORD_ID_INVALID"), ("ROW_SCOPE", "ROW_SCOPE_MISMATCH"),
    ("REFERENCE_MISSING", "TECHNICIAN_REFERENCE_MISSING"), ("BLANK_REQUEST_ID", "REQUEST_ID_BLANK"),
    ("BAD_TIME", "ASSIGNED_AT_INVALID"),
])
async def test_r2fh1_set_01_partial_duplicated_or_conflicting_history_fails_closed(name, issue) -> None:
    repo = repo_with()
    job_id, other = await new_repair(repo), await new_repair(repo)
    await assign(repo, job_id, body(T1))
    _tamper(name, v2_rows(repo), job_id, other)
    if name == "REFERENCE_MISSING":
        repo._technician_master = [tt(T2), tt(T3), tt(T4)]
    snapshot = copy.deepcopy(v2_rows(repo))
    for call in (assign(repo, job_id, body(T3, expected=(T1,))), ta_service(repo).read(REPAIR, job_id),
                 repair_service(repo).authorize_recording(job_id, ctx(U1), authz.CAN_MANAGE_REPAIR, "x")):
        with pytest.raises(ApiError) as exc:
            await call
        assert exc.value.code == "TECHNICIAN_ASSIGNMENT_DATA_INVALID"
        assert issue in exc.value.details["issues"]
    assert v2_rows(repo) == snapshot


# ---------------------------------------------------------------------------
# H1-01 — a set must be COMPLETE: a lost, extra, moved or altered member row
# is proven from the stored rows alone and fails closed.
# ---------------------------------------------------------------------------


def _ids(rows) -> list[str]:
    return [r["repair_assignment_id"] for r in rows]


@pytest.mark.asyncio
async def test_r2fh1_h101_01_the_reviewed_case_primary_only_is_never_valid() -> None:
    """Requested PRIMARY A + COLLABORATOR B; persisted PRIMARY A only."""
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1, T2))
    rows = v2_rows(repo)
    assert [r.split("-")[-2:] for r in _ids(rows)] == [["1", "2"], ["2", "2"]]
    del rows[1]
    scope = {"is_test_data": "TRUE", "test_batch_id": BATCH}
    state = derive_assignment_state(REPAIR, job_id, rows, scope)
    assert (state.status, state.current, state.issues) == ("NONE", None, {"SET_INCOMPLETE": 1})
    for call in (ta_service(repo).read(REPAIR, job_id), assign(repo, job_id, body(T3, expected=(T1,))),
                 assign(repo, job_id, body(T3, expected=(T1, T2))),
                 repair_service(repo).authorize_recording(job_id, ctx(U1), authz.CAN_MANAGE_REPAIR, "x")):
        with pytest.raises(ApiError) as exc:
            await call
        assert (exc.value.code, exc.value.details["issues"]) == ("TECHNICIAN_ASSIGNMENT_DATA_INVALID",
                                                                 {"SET_INCOMPLETE": 1})
    assert len(v2_rows(repo)) == 1  # nothing was written on top of the damaged set


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "issue"), [
    ("lose_primary", "SET_PRIMARY_COUNT_INVALID"),
    ("lose_middle", "SET_INCOMPLETE"),
    ("lose_last", "SET_INCOMPLETE"),
    ("duplicate_row", "DUPLICATE_RECORD_ID"),
    ("swap_assignee", "SET_DIGEST_MISMATCH"),
    ("swap_roles", "SET_DIGEST_MISMATCH"),
    ("shrink_size", "SET_DIGEST_MISMATCH"),
    ("row_from_other_set", "SET_INCOMPLETE"),
    ("bad_id", "SET_COMPLETENESS_UNPROVEN"),
])
async def test_r2fh1_h101_02_every_member_row_is_proven(damage, issue) -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T4))
    await assign(repo, job_id, body(T1, T2, T3, expected=(T4,)))
    rows = v2_rows(repo)
    older, newer = rows[:1], rows[1:]
    if damage == "lose_primary":
        rows.remove(newer[0])
    elif damage == "lose_middle":
        rows.remove(newer[1])
    elif damage == "lose_last":
        rows.remove(newer[2])
    elif damage == "duplicate_row":
        rows.append(dict(newer[1]))
    elif damage == "swap_assignee":
        newer[2]["assignee_id"] = T4
    elif damage == "swap_roles":
        newer[0]["assignment_role"], newer[1]["assignment_role"] = "COLLABORATOR", "PRIMARY"
    elif damage == "shrink_size":
        rows.remove(newer[2])
        for row in newer[:2]:
            row["repair_assignment_id"] = row["repair_assignment_id"].rsplit("-", 1)[0] + "-2"
    elif damage == "row_from_other_set":
        moved = dict(older[0], request_id=newer[0]["request_id"], assigned_at=newer[0]["assigned_at"],
                     request_fingerprint=newer[0]["request_fingerprint"], assignment_role="COLLABORATOR")
        rows.remove(older[0])
        rows.remove(newer[2])
        rows.append(moved)
    elif damage == "bad_id":
        newer[1]["repair_assignment_id"] = "RTA-" + "0" * 32
    with pytest.raises(ApiError) as exc:
        await ta_service(repo).read(REPAIR, job_id)
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_DATA_INVALID" and issue in exc.value.details["issues"]


@pytest.mark.asyncio
async def test_r2fh1_h101_03_complete_sets_of_every_size_stay_valid_and_ids_are_unique() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1))
    await assign(repo, job_id, body(T2, T1, expected=(T1,)))
    await assign(repo, job_id, body(T3, T1, T2, T4, expected=(T2, T1)))
    read = await ta_service(repo).read(REPAIR, job_id)
    assert read.state.status == "VALID" and [len(s.record_ids) for s in read.state.sets] == [1, 2, 4]
    assert read.state.current.collaborator_technician_ids == (T1, T2, T4)  # written order is kept
    assert len(set(_ids(v2_rows(repo)))) == 7
    # Physical row order inside a set does not matter: indices, not positions, are proven.
    v2_rows(repo)[3:7] = list(reversed(v2_rows(repo)[3:7]))
    again = await ta_service(repo).read(REPAIR, job_id)
    assert again.state.current == read.state.current


@pytest.mark.asyncio
async def test_r2fh1_tie_01_same_instant_latest_sets_are_never_guessed() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1))
    await assign(repo, job_id, body(T2, expected=(T1,)))
    rows = v2_rows(repo)
    rows[1]["assigned_at"] = rows[0]["assigned_at"]  # the two sets now share one instant
    read = await ta_service(repo).read(REPAIR, job_id)
    assert (read.state.status, read.state.current) == ("AMBIGUOUS", None)
    assert await code_of(assign(repo, job_id, body(T3, expected=(T2,)))) == "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS"
    assert await code_of(repair_service(repo).authorize_recording(job_id, ctx(U2), authz.CAN_MANAGE_REPAIR, "x")) \
        == "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS"
    # The management capability still records (no V2 read is needed for it).
    await repair_service(repo).authorize_recording(job_id, ctx("m", authz.CAN_MANAGE_REPAIR),
                                                   authz.CAN_MANAGE_REPAIR, "x")


# ---------------------------------------------------------------------------
# R2FH1-APPEND — append-only sets, blank user_id (governance 11, 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_append_01_sets_are_appended_never_edited_and_carry_a_blank_user_id() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    first = await assign(repo, job_id, body(T1, T2, reason=REASON))
    snapshot = copy.deepcopy(v2_rows(repo))
    second = await assign(repo, job_id, body(T3, expected=(T1, T2)))
    rows = v2_rows(repo)
    assert rows[: len(snapshot)] == snapshot and len(rows) == 3
    assert repo.registry_write_log == ["W1", "W1"]
    for row in rows:
        assert (row["user_id"], row["ended_at"], row["active_status"], row["note_th"]) == ("", "", "", "")
        assert row["assignee_type"] == "TECHNICIAN" and row["repair_assignment_id"].startswith("RTA-")
        assert (row["is_test_data"], row["test_batch_id"]) == ("TRUE", BATCH)
        assert row["assigned_by_user_id"] == "dev-user"
    assert [(r["assignment_role"], r["assignee_id"]) for r in rows] == [("PRIMARY", T1), ("COLLABORATOR", T2),
                                                                         ("PRIMARY", T3)]
    assert {r["request_id"] for r in rows[:2]} == {first.request_id} and rows[2]["request_id"] == second.request_id
    assert rows[0]["reason_th"] == REASON
    read = await ta_service(repo).read(REPAIR, job_id)
    assert read.state.current.primary_technician_id == T3 and len(read.state.sets) == 2


@pytest.mark.asyncio
async def test_r2fh1_append_02_http_round_trip_for_repair_and_pm() -> None:
    repo = repo_with()
    repair_id, pm_id = await new_repair(repo), await new_pm(repo)
    for path in (f"{API}/repairs/{repair_id}/technician-assignments",
                 f"{API}/pm/work-orders/{pm_id}/technician-assignments"):
        empty = await http("GET", path, repo, role="TECHNICIAN")
        assert empty.status_code == 200 and empty.json()["status"] == "NONE" and empty.json()["current"] is None
        written = await http("POST", path, repo, json=body(T1, T2, reason=REASON))
        assert written.status_code == 200, written.text
        assert written.json()["changed"] is True and written.json()["current"]["primary_technician_id"] == T1
        read = (await http("GET", path, repo, role="TECHNICIAN")).json()
        assert read["status"] == "VALID" and read["current"]["collaborator_technician_ids"] == [T2]
        assert read["current"]["reason_th"] == REASON and len(read["sets"]) == 1
    assert len(v2_rows(repo, "PM")) == 2 and v2_rows(repo, "PM")[0]["pm_work_order_id"] == pm_id


@pytest.mark.asyncio
async def test_r2fh1_w1_01_failed_write_is_reported_never_retried_and_replay_recovers() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    repo.registry_write_faults["W1"] = "rejected"
    with pytest.raises(ApiError) as exc:
        await assign(repo, job_id, body(T1))
    assert (exc.value.code, exc.value.details["write_outcome"]) == ("TECHNICIAN_ASSIGNMENT_WRITE_FAILED", "rejected")
    assert v2_rows(repo) == [] and repo.registry_write_log == ["W1"]
    repo.registry_write_faults["W1"] = "unknown_applied"
    rid = str(uuid.uuid4())
    with pytest.raises(ApiError) as exc:
        await assign(repo, job_id, body(T1), request_id=rid)
    assert exc.value.details["write_outcome"] == "unknown" and len(v2_rows(repo)) == 1
    repo.registry_write_faults["W1"] = None
    assert (await assign(repo, job_id, body(T1), request_id=rid)).replayed
    assert repo.registry_write_log == ["W1", "W1"]


# ---------------------------------------------------------------------------
# R2FH1-LEGACY — legacy records preserved, no migration (governance 14, 19)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_legacy_01_legacy_jobs_and_rows_are_untouched_by_v2_activity() -> None:
    repo = repo_with()
    legacy_id = await new_repair(repo, enabled=False)
    await repair_service(repo, enabled=False).assign(legacy_id, "u-legacy-1", ["u-legacy-2"])
    legacy_pm = await new_pm(repo, enabled=False)
    await pm_service(repo, enabled=False).assign(legacy_pm, "u-legacy-3", [])
    before = (copy.deepcopy(repo._repair_assignment_history), copy.deepcopy(repo._pm_assignment_history),
              repo._repairs[legacy_id].model_dump(), repo._pm_work_orders[legacy_pm].model_dump())
    v2_id, v2_pm = await new_repair(repo), await new_pm(repo)
    await assign(repo, v2_id, body(T1, T2))
    await assign(repo, v2_pm, body(T1), kind=PM)
    after = (repo._repair_assignment_history, repo._pm_assignment_history,
             repo._repairs[legacy_id].model_dump(), repo._pm_work_orders[legacy_pm].model_dump())
    assert after == before
    assert {r["repair_id"] for r in v2_rows(repo)} == {v2_id}
    assert {r["pm_work_order_id"] for r in v2_rows(repo, "PM")} == {v2_pm}
    # The legacy history still reads the opaque user_id strings, unchanged.
    history = await repair_service(repo).list_assignment_history(legacy_id)
    assert sorted(e.user_id for e in history) == ["u-legacy-1", "u-legacy-2"]


@pytest.mark.asyncio
async def test_r2fh1_legacy_02_a_legacy_user_id_is_never_read_as_a_technician_id() -> None:
    repo = repo_with()
    legacy_id = await new_repair(repo, enabled=False)
    # A legacy assignee string that happens to equal a technician id stays an opaque user_id.
    await repair_service(repo, enabled=False).assign(legacy_id, T1, [])
    assert await code_of(assign(repo, legacy_id, body(T1))) == "ASSIGNMENT_MODEL_MISMATCH"
    # Legacy recording compares the actor's user_id, exactly as before — never the V2 chain.
    service = repair_service(repo)
    await service.authorize_recording(legacy_id, ctx(T1), authz.CAN_MANAGE_REPAIR, "x")
    repo.calls.clear()
    with pytest.raises(Exception) as exc:
        await service.authorize_recording(legacy_id, ctx(U1), authz.CAN_MANAGE_REPAIR, "x")
    assert getattr(exc.value, "status_code", None) == 403
    assert "read_work_assignment_v2_rows" not in repo.calls and "read_user_account_reference" not in repo.calls


# ---------------------------------------------------------------------------
# R2FH1-REC — actor -> technician recording authorization (governance 15)
# ---------------------------------------------------------------------------


async def _record(repo, job_id: str, user: str, *, role: str = "TECHNICIAN"):
    return await http("POST", f"{API}/repairs/{job_id}/actions", repo, role=role, user=user,
                      json={"action_text": "ทำงาน"})


@pytest.mark.asyncio
async def test_r2fh1_rec_01_only_current_set_members_record_through_the_in_scope_chain() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1, T2))
    assert (await _record(repo, job_id, U1)).status_code == 200  # PRIMARY
    assert (await _record(repo, job_id, U2)).status_code == 200  # COLLABORATOR
    assert (await _record(repo, job_id, U3)).status_code == 403  # linked, not a member
    assert (await _record(repo, job_id, "USR-NOBODY")).status_code == 403  # no personnel
    assert (await _record(repo, job_id, T1)).status_code == 403  # a technician id is not an account
    await assign(repo, job_id, body(T3, expected=(T1, T2)))
    assert (await _record(repo, job_id, U1)).status_code == 403  # no longer current
    assert (await _record(repo, job_id, U3)).status_code == 200
    response = await http("POST", f"{API}/repairs/{job_id}/parts", repo, role="TECHNICIAN", user=U3,
                          json={"part_description": "ชิ้นส่วน", "quantity": 1, "unit": "ea"})
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("break_chain", ["account_missing", "account_other_scope", "two_personnel_same_user",
                                         "personnel_unlinked", "technician_missing", "technician_two_holders",
                                         "personnel_real_scope"])
async def test_r2fh1_rec_02_an_unresolved_chain_never_authorizes(break_chain) -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1))
    if break_chain == "account_missing":
        repo._user_account = [ta(U2), ta(U3)]
    elif break_chain == "account_other_scope":
        repo._user_account = [account(U1)]
    elif break_chain == "two_personnel_same_user":
        repo._personnel_master.append(tp("P-9", technician_id=T4, user_id=U1))
    elif break_chain == "personnel_unlinked":
        repo._personnel_master[0]["technician_id"] = ""
    elif break_chain == "technician_missing":
        repo._technician_master = [tt(T2), tt(T3), tt(T4)]
        # the persisted reference proof then fails closed first
        assert (await _record(repo, job_id, U1)).status_code == 500
        return
    elif break_chain == "technician_two_holders":
        repo._personnel_master.append(tp("P-9", technician_id=T1))
    elif break_chain == "personnel_real_scope":
        repo._personnel_master[0] = person("P-1", technician_id=T1, user_id=U1)
    assert (await _record(repo, job_id, U1)).status_code == 403


@pytest.mark.asyncio
async def test_r2fh1_rec_03_no_lifecycle_gate_on_recording_an_existing_assignment() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1))
    repo._technician_master = [tt(T1, status="INACTIVE"), tt(T2), tt(T3), tt(T4)]
    repo._personnel_master[0]["active_status"] = "INACTIVE"
    assert (await _record(repo, job_id, U1)).status_code == 200  # owner decision PENDING: unchanged


@pytest.mark.asyncio
async def test_r2fh1_rec_04_capability_records_without_any_v2_read_and_pm_results_follow_the_same_rule() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    repo.calls.clear()
    assert (await _record(repo, job_id, "manager-1", role="MAINTENANCE")).status_code == 200
    assert "read_work_assignment_v2_rows" not in repo.calls
    pm_id = await new_pm(repo)
    await assign(repo, pm_id, body(T2), kind=PM)
    task_id = repo._pm_work_orders[pm_id].scope_task_ids[0]
    path = f"{API}/pm/work-orders/{pm_id}/results"
    result = {"pm_task_id": task_id, "completed": True}
    assert (await http("POST", path, repo, role="TECHNICIAN", user=U1, json=result)).status_code == 403
    assert (await http("POST", path, repo, role="TECHNICIAN", user=U2, json=result)).status_code == 200


# ---------------------------------------------------------------------------
# R2FH1-ATT — Repair / PM attachment authorization (governance 16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_att_01_attachment_sources_follow_the_job_model(tmp_path) -> None:
    from app.domain.attachment_service import AttachmentService
    from app.storage.local import LocalFileStorageProvider

    repo = repo_with()
    service = AttachmentService(repo, LocalFileStorageProvider(str(tmp_path)), settings(False))
    repair_id, pm_id = await new_repair(repo), await new_pm(repo)
    await assign(repo, repair_id, body(T1))
    await assign(repo, pm_id, body(T2), kind=PM)
    await service.authorize_source(ctx(U1), "REPAIR", repair_id, "x")
    await service.authorize_source(ctx(U2), "PM_WORK_ORDER", pm_id, "x")
    for user, source, job in ((U2, "REPAIR", repair_id), (U1, "PM_WORK_ORDER", pm_id), (None, "REPAIR", repair_id)):
        assert await code_of(service.authorize_source(ctx(user), source, job, "x")) == \
            "ATTACHMENT_SOURCE_NOT_AUTHORIZED"
    await service.authorize_source(ctx("m", authz.CAN_MANAGE_REPAIR), "REPAIR", repair_id, "x")
    await service.authorize_source(ctx("m", authz.CAN_MANAGE_PM), "PM_WORK_ORDER", pm_id, "x")
    # Legacy jobs keep the opaque user_id compare.
    legacy_id = await new_repair(repo, enabled=False)
    await repair_service(repo, enabled=False).assign(legacy_id, "u-legacy", [])
    await service.authorize_source(ctx("u-legacy"), "REPAIR", legacy_id, "x")
    assert await code_of(service.authorize_source(ctx(U1), "REPAIR", legacy_id, "x")) == \
        "ATTACHMENT_SOURCE_NOT_AUTHORIZED"


# ---------------------------------------------------------------------------
# R2FH1-AUTH — no role or capability grant (governance 17)
# ---------------------------------------------------------------------------


def test_r2fh1_auth_01_no_role_or_capability_grant_changed() -> None:
    holders = {cap: {r for r, caps in authz.ROLE_CAPABILITIES.items() if cap in caps}
               for cap in (authz.CAN_MANAGE_REPAIR, authz.CAN_MANAGE_PM)}
    assert holders == {authz.CAN_MANAGE_REPAIR: {"ADMIN", "MAINTENANCE", "SUPERVISOR"},
                       authz.CAN_MANAGE_PM: {"ADMIN", "MAINTENANCE", "SUPERVISOR"}}
    assert set(authz.ROLE_CAPABILITIES) == {"ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER",
                                            "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"}
    assert not any("assign" in c and "technician" in c for c in authz.ALL_CAPABILITIES)
    assert authz.PENDING_CAPABILITIES == {authz.CAN_MOVE_PERSONNEL_DEPARTMENT}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER",
                                  "NOBODY"])
async def test_r2fh1_auth_02_writes_without_the_capability_are_403_with_zero_repository_calls(role) -> None:
    repo = repo_with()
    repair_id, pm_id = await new_repair(repo), await new_pm(repo)
    repo.calls.clear()
    for path in (f"{API}/repairs/{repair_id}/technician-assignments",
                 f"{API}/pm/work-orders/{pm_id}/technician-assignments"):
        response = await http("POST", path, repo, role=role, json=body(T1))
        assert response.status_code == 403
    assert repo.calls == [] and v2_rows(repo) == []


@pytest.mark.asyncio
async def test_r2fh1_auth_03_request_id_is_required_before_any_read() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    repo.calls.clear()
    response = await http("POST", f"{API}/repairs/{job_id}/technician-assignments", repo, json=body(T1),
                          request_id=None)
    assert _code(response) == (422, "REQUEST_ID_REQUIRED") and repo.calls == []
