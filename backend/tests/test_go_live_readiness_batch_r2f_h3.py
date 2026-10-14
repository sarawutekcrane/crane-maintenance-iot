"""R2 Batch R2f-h3 — pre-Go-live verification report, mock / service level.

Every row is SYNTHETIC. The report runs only in the REAL context, which mock
mode (always TEST) refuses at the API, so report content is exercised against
the service directly with REAL-scoped synthetic fixtures; the HTTP route is used
for authorization / REAL-only enforcement (and over the fake Sheets transport in
the `_sheets_` companion file). Governance list 1-27: R2FH3-AUTH (1, 2, 21, 24),
-INPUT (3-6, 27), -LINK (7, 8, 10), -ACTIVE (9), -REF (11, 16), -TEST (12, 13),
-SCHEMA (14, 15), -OVERALL (17, 18), -CTX (19, 20), -RO (22, 23), -FAIL (25),
-COUNT (26).
"""
from __future__ import annotations

import copy
import uuid

import pytest

from app.context import RequestContext
from app.domain import authz
from app.domain.go_live_readiness import GoLiveReadinessService
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_TEST, RepositoryError, RepositorySchemaError
from tests.test_relationship_read_batch_r2f_a import RelSpy, account, person, tech
from tests.test_technician_assignment_batch_r2f_h1 import assign, body, new_pm, new_repair, v2_rows
from tests.legacy_assignment_seed import seed_legacy_repair_assignment

API = "/api/v1"
PATH = f"{API}/technician-assignment/go-live-readiness"
REAL = {"context": "REAL", "batch": ""}
R = "intended_recipient_personnel_ids"
M = "intended_my_work_personnel_ids"
OMIT = object()


def people(n: int = 2) -> list[dict[str, str]]:
    return [person(f"P-{i}", technician_id=f"T-{i}", user_id=f"U-{i}") for i in range(1, n + 1)]


def repo_with(rows=None, technicians=None, accounts=None, n: int = 2) -> RelSpy:
    return RelSpy(people=rows if rows is not None else people(n),
                  technicians=technicians if technicians is not None else [tech(f"T-{i}") for i in range(1, n + 1)],
                  accounts=accounts if accounts is not None else [account(f"U-{i}") for i in range(1, n + 1)])


def svc(repo, context: str | None = "REAL") -> GoLiveReadinessService:
    # R2 Batch R2f-h4 B6 Rev2: the report no longer carries the removed V2 cutover setting.
    return GoLiveReadinessService(repo, data_context=context, dev_auth_effective=True)


async def run(repo, recipients=("P-1", "P-2"), my_work=("P-1", "P-2"), **kw):
    payload: dict = {}
    if recipients is not OMIT:
        payload[R] = None if recipients is None else list(recipients)
    if my_work is not OMIT:
        payload[M] = None if my_work is None else list(my_work)
    return await svc(repo, **kw).report(payload, frozenset(payload))


def check(report, check_id: str):
    return next(c for c in report.checks if c.id == check_id)


def codes(report, check_id: str) -> list[str]:
    return [i["code"] for i in check(report, check_id).issues]


async def ready_repo() -> RelSpy:
    """A fully consistent REAL fixture with one REAL V2 Repair job assigned."""
    repo = repo_with()
    job = await new_repair(repo, **REAL)
    await assign(repo, job, body("T-1", "T-2"), **REAL)
    return repo


async def http(repo, *, role: str = "ADMIN", json=None, caps: frozenset[str] | None = None):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_current_context, get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if caps is not None:
        app.dependency_overrides[get_current_context] = lambda: RequestContext(
            request_id=str(uuid.uuid4()), user_id="synthetic-caller", is_dev_auth=True, capabilities=caps)
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(PATH, json=json if json is not None else {R: ["P-1"], M: ["P-1"]},
                                     headers={"X-Dev-Role": role})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# ---------------------------------------------------------------------------
# R2FH3-AUTH — D1 dual capability, before any read (governance 1, 2, 21, 24)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "allowed"), [
    ("ADMIN", True), ("MAINTENANCE_MANAGER", True), ("MAINTENANCE", False), ("SUPERVISOR", False),
    ("TECHNICIAN", False), ("DRIVER", False), ("DRIVER_DEPARTMENT_MANAGER", False), ("NOBODY", False),
])
async def test_r2fh3_auth_01_every_dev_role(role, allowed) -> None:
    repo = repo_with()
    repo.calls.clear()
    response = await http(repo, role=role)
    if allowed:  # passes D1, then mock (TEST) is refused before any read
        assert _code(response) == (409, "GO_LIVE_READINESS_REQUIRES_REAL_CONTEXT")
    else:
        assert response.status_code == 403
        assert "P-1" not in response.text and "U-1" not in response.text
    assert repo.calls == [] and repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("caps", [
    frozenset(), frozenset({authz.CAN_VIEW}), frozenset({authz.CAN_LINK_PERSONNEL_TECHNICIAN}),
    frozenset({authz.CAN_LINK_PERSONNEL_ACCOUNT}),
    frozenset({authz.CAN_LINK_PERSONNEL_DRIVER, authz.CAN_MANAGE_REPAIR, authz.CAN_MANAGE_PM, authz.CAN_VIEW}),
])
async def test_r2fh3_auth_02_logical_and_of_exactly_the_two_link_capabilities(caps) -> None:
    repo = repo_with()
    repo.calls.clear()
    response = await http(repo, caps=caps)
    assert response.status_code == 403 and repo.calls == []
    both = await http(repo, caps=frozenset({authz.CAN_LINK_PERSONNEL_TECHNICIAN, authz.CAN_LINK_PERSONNEL_ACCOUNT}))
    assert both.status_code == 409 and repo.calls == []  # authorized; then REAL-only, still zero reads


@pytest.mark.asyncio
async def test_r2fh3_auth_03_authorization_runs_before_body_validation() -> None:
    repo = repo_with()
    response = await http(repo, role="TECHNICIAN", json={"unexpected": 1})
    assert response.status_code == 403  # never a 422 that would reveal the contract to an unauthorized caller


def test_r2fh3_auth_04_no_role_or_capability_grant_changed() -> None:
    both = {r for r, caps in authz.ROLE_CAPABILITIES.items()
            if authz.CAN_LINK_PERSONNEL_TECHNICIAN in caps and authz.CAN_LINK_PERSONNEL_ACCOUNT in caps}
    assert both == {"ADMIN", "MAINTENANCE_MANAGER"}
    assert set(authz.ROLE_CAPABILITIES) == {"ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER",
                                            "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"}
    assert authz.PENDING_CAPABILITIES == {authz.CAN_MOVE_PERSONNEL_DEPARTMENT}
    import inspect

    import app.api.v1.go_live_readiness_routes as routes

    source = inspect.getsource(routes)
    for role in authz.ROLE_CAPABILITIES:
        assert f'"{role}"' not in source  # no role name is hard-coded


@pytest.mark.asyncio
async def test_r2fh3_auth_05_authorized_population_discloses_exact_user_ids() -> None:
    report = await run(await ready_repo())
    assert [(p["personnel_id"], p["account"]["user_id"]) for p in report.population] == [("P-1", "U-1"),
                                                                                         ("P-2", "U-2")]


# ---------------------------------------------------------------------------
# R2FH3-INPUT — D2 owner lists (governance 3-6, 27)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("recipients", "my_work", "states"), [
    (OMIT, ("P-1",), ("OMITTED", "SUPPLIED")),
    (("P-1",), OMIT, ("SUPPLIED", "OMITTED")),
    ((), ("P-1",), ("EMPTY", "SUPPLIED")),
    (("P-1",), (), ("SUPPLIED", "EMPTY")),
    (None, None, ("NULL", "NULL")),
    (OMIT, OMIT, ("OMITTED", "OMITTED")),
])
async def test_r2fh3_input_01_missing_null_or_empty_lists_never_pass(recipients, my_work, states) -> None:
    report = await run(await ready_repo(), recipients=recipients, my_work=my_work)
    assert (report.inputs[R]["state"], report.inputs[M]["state"]) == states
    for check_id, state in (("C1-26-1", states[0]), ("C1-26-2", states[1])):
        result = check(report, check_id)
        if state == "SUPPLIED":
            assert result.status == "PASS"
        else:
            assert (result.status, result.evidence["blocked_reason"]) == ("BLOCKED", f"INPUT_{state}")
    assert check(report, "C1-26-3").status == "BLOCKED"
    assert report.overall == "BLOCKED" and any("INPUT_" in g for g in report.gaps)


@pytest.mark.asyncio
async def test_r2fh3_input_02_duplicate_unknown_ambiguous_and_out_of_scope_ids_are_reported_never_dropped() -> None:
    rows = [*people(2), person("P-AMB"), person("P-AMB"), person("P-TEST", test=True, batch="SYN-B"),
            {**person("P-BAD"), "is_test_data": "maybe"}]
    repo = repo_with(rows=rows)
    supplied = ["P-1", "P-1", "P-404", "P-AMB", "P-TEST", "P-BAD", " ", "p-1", " P-1"]
    report = await run(repo, recipients=supplied, my_work=("P-2",))
    assert report.inputs[R]["ids"] == supplied and report.inputs[R]["duplicates"] == ["P-1"]
    issues = {(i["code"], i["personnel_id"]) for i in check(report, "C1-26-1").issues}
    assert issues == {("INPUT_DUPLICATE", "P-1"), ("PERSONNEL_NOT_FOUND", "P-404"), ("PERSONNEL_AMBIGUOUS", "P-AMB"),
                      ("PERSONNEL_SCOPE_MISMATCH", "P-TEST"), ("PERSONNEL_SCOPE_INVALID", "P-BAD"),
                      ("INPUT_ID_BLANK", " "), ("PERSONNEL_NOT_FOUND", "p-1"), ("PERSONNEL_NOT_FOUND", " P-1")}
    assert check(report, "C1-26-1").status == "FAIL" and report.overall == "NOT_READY"


@pytest.mark.asyncio
async def test_r2fh3_input_03_no_inference_from_names_or_identifiers() -> None:
    rows = people(1)
    rows[0]["first_name"] = "P-DECOY"
    repo = repo_with(rows=rows, n=1)
    report = await run(repo, recipients=("P-DECOY", "T-1", "U-1"), my_work=("P-1",))
    assert {i["code"] for i in check(report, "C1-26-1").issues} == {"PERSONNEL_NOT_FOUND"}


# ---------------------------------------------------------------------------
# R2FH3-LINK — C1-26-1 / -2 (governance 7, 8, 10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh3_link_01_resolved_links_pass_for_every_listed_person() -> None:
    report = await run(await ready_repo())
    for check_id in ("C1-26-1", "C1-26-2"):
        assert check(report, check_id).status == "PASS"
        assert check(report, check_id).evidence["resolved"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "check_id", "code"), [
    ("technician_unset", "C1-26-1", "LINK_UNSET"),
    ("technician_missing", "C1-26-1", "LINK_MISSING"),
    ("technician_shared", "C1-26-1", "LINK_AMBIGUOUS"),
    ("technician_two_rows", "C1-26-1", "LINK_AMBIGUOUS"),
    ("technician_test_only", "C1-26-1", "LINK_MISSING"),
    ("account_unset", "C1-26-2", "LINK_UNSET"),
    ("account_missing", "C1-26-2", "LINK_MISSING"),
    ("account_shared", "C1-26-2", "LINK_AMBIGUOUS"),
])
async def test_r2fh3_link_02_missing_or_ambiguous_links_fail(change, check_id, code) -> None:
    rows, technicians, accounts = people(2), [tech("T-1"), tech("T-2")], [account("U-1"), account("U-2")]
    if change == "technician_unset":
        rows[0]["technician_id"] = ""
    elif change == "technician_missing":
        technicians = [tech("T-2")]
    elif change == "technician_shared":
        rows[1]["technician_id"] = "T-1"
    elif change == "technician_two_rows":
        technicians.append(tech("T-1"))
    elif change == "technician_test_only":
        technicians = [tech("T-1", scope=REFERENCE_SCOPE_TEST, batch="SYN-B"), tech("T-2")]
    elif change == "account_unset":
        rows[0]["user_id"] = ""
    elif change == "account_missing":
        accounts = [account("U-2")]
    elif change == "account_shared":
        rows[1]["user_id"] = "U-1"
    report = await run(repo_with(rows=rows, technicians=technicians, accounts=accounts))
    assert check(report, check_id).status == "FAIL" and code in codes(report, check_id)
    assert report.overall == "NOT_READY"


# ---------------------------------------------------------------------------
# R2FH3-ACTIVE — D4 for both groups (governance 9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "status", "code"), [
    ("personnel_inactive", "FAIL", "PERSONNEL_NOT_ACTIVE"),
    ("personnel_lowercase", "FAIL", "PERSONNEL_NOT_ACTIVE"),
    ("personnel_blank", "FAIL", "PERSONNEL_NOT_ACTIVE"),
    ("technician_inactive", "FAIL", "TECHNICIAN_NOT_ACTIVE"),
    ("technician_padded", "FAIL", "TECHNICIAN_NOT_ACTIVE"),
    ("technician_unresolved", "UNDETERMINED", "TECHNICIAN_UNRESOLVED"),
])
async def test_r2fh3_active_01_exact_active_for_my_work_users_too(change, status, code) -> None:
    """P-2 is ONLY a My Work user: D4 checks it exactly like a recipient."""
    rows, technicians = people(2), [tech("T-1"), tech("T-2")]
    if change == "personnel_inactive":
        rows[1]["active_status"] = "INACTIVE"
    elif change == "personnel_lowercase":
        rows[1]["active_status"] = "active"
    elif change == "personnel_blank":
        rows[1]["active_status"] = ""
    elif change == "technician_inactive":
        technicians = [tech("T-1"), tech("T-2", status="INACTIVE")]
    elif change == "technician_padded":
        technicians = [tech("T-1"), tech("T-2", status="ACTIVE ")]
    elif change == "technician_unresolved":
        rows[1]["technician_id"] = ""
    report = await run(repo_with(rows=rows, technicians=technicians), recipients=("P-1",), my_work=("P-1", "P-2"))
    result = check(report, "C1-26-3")
    assert result.status == status and code in [i["code"] for i in result.issues]
    assert [i["groups"] for i in result.issues if i["code"] == code] == [[M]]
    assert report.overall == "NOT_READY"


@pytest.mark.asyncio
async def test_r2fh3_active_02_a_person_in_both_lists_is_evaluated_once() -> None:
    rows = people(1)
    rows[0]["active_status"] = "INACTIVE"
    report = await run(repo_with(rows=rows, n=1), recipients=("P-1",), my_work=("P-1",))
    result = check(report, "C1-26-3")
    assert result.evidence["unique_people"] == 1
    assert [(i["code"], i["groups"]) for i in result.issues] == [("PERSONNEL_NOT_ACTIVE", [R, M])]


# ---------------------------------------------------------------------------
# R2FH3-REF — C1-26-5 REAL reference integrity (governance 11, 16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "code"), [
    ("other_personnel_technician_missing", "REFERENCE_MISSING"),
    ("technician_rows_duplicated", "REFERENCE_AMBIGUOUS"),
    ("other_personnel_shares_technician", "TECHNICIAN_LINK_SHARED"),
    ("account_scope_test_only", "REFERENCE_SCOPE_UNPROVEN"),
    ("personnel_id_duplicated", "PERSONNEL_ID_DUPLICATE"),
    ("caretaker_equipment_missing", "REFERENCE_MISSING"),
])
async def test_r2fh3_ref_01_real_reference_defects_fail(change, code) -> None:
    repo = await ready_repo()
    if change == "other_personnel_technician_missing":
        repo._personnel_master.append(person("P-9", technician_id="T-GONE"))
    elif change == "technician_rows_duplicated":
        repo._technician_master.append(tech("T-2"))
    elif change == "other_personnel_shares_technician":
        repo._personnel_master.append(person("P-9", technician_id="T-1"))
    elif change == "account_scope_test_only":
        repo._personnel_master.append(person("P-9", user_id="U-TEST"))
        repo._user_account.append(account("U-TEST", scope=REFERENCE_SCOPE_TEST, batch="SYN-B"))
    elif change == "personnel_id_duplicated":
        repo._personnel_master.append(person("P-9"))
        repo._personnel_master.append(person("P-9"))
    elif change == "caretaker_equipment_missing":
        repo._equipment_caretaker_history.append({"record_id": "ECH-SYN", "equipment_id": "EQ-GONE",
                                                  "technician_id": "T-1", "is_test_data": "FALSE",
                                                  "test_batch_id": ""})
    report = await run(repo)
    assert check(report, "C1-26-5").status == "FAIL" and code in codes(report, "C1-26-5")
    assert report.overall == "NOT_READY"


@pytest.mark.asyncio
async def test_r2fh3_ref_02_unset_optional_links_are_not_references() -> None:
    repo = await ready_repo()
    repo._personnel_master.append(person("P-9"))  # no technician / account / driver link at all
    report = await run(repo)
    assert check(report, "C1-26-5").status == "PASS"


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "code"), [
    ("lose_collaborator", "V2_SET_INCOMPLETE"),
    ("swap_assignee", "V2_SET_DIGEST_MISMATCH"),
    ("job_gone", "V2_ROW_JOB_MISSING"),
    ("job_legacy", "V2_ROW_ON_LEGACY_JOB"),
    ("same_instant", "V2_CURRENT_SET_AMBIGUOUS"),
    ("assignee_left_master", "REFERENCE_MISSING"),
])
async def test_r2fh3_ref_03_h1_01_damaged_real_v2_history_fails(damage, code) -> None:
    repo = await ready_repo()
    job = next(iter(repo._repairs))
    rows = v2_rows(repo)
    if damage == "lose_collaborator":
        del rows[1]
    elif damage == "swap_assignee":
        repo._technician_master.append(tech("T-3"))
        rows[1]["assignee_id"] = "T-3"
    elif damage == "job_gone":
        del repo._repairs[job]
    elif damage == "job_legacy":
        repo._repairs[job] = repo._repairs[job].model_copy(update={"assignment_model": "", "is_test_data": "",
                                                                    "test_batch_id": ""})
    elif damage == "same_instant":
        await assign(repo, job, body("T-2", expected=("T-1", "T-2")), **REAL)
        rows[-1]["assigned_at"] = rows[0]["assigned_at"]
    elif damage == "assignee_left_master":
        repo._technician_master = [tech("T-1")]
    report = await run(repo, recipients=("P-1",), my_work=("P-1",))
    assert check(report, "C1-26-5").status == "FAIL" and code in codes(report, "C1-26-5")


# ---------------------------------------------------------------------------
# R2FH3-TEST — C1-26-4 TEST segregation and coverage (governance 12, 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "code"), [
    ("test_personnel_links_real_technician", "TEST_REFERENCES_REAL"),
    ("test_personnel_links_real_account", "TEST_REFERENCES_REAL"),
    ("test_link_history_names_real_personnel", "TEST_REFERENCES_REAL"),
    ("test_caretaker_on_real_equipment", "TEST_REFERENCES_REAL"),
    ("test_v2_job_on_real_vehicle", "TEST_REFERENCES_REAL"),
    ("test_v2_row_on_real_job", "TEST_REFERENCES_REAL"),
    ("flag_invalid", "TEST_FLAG_INVALID"),
    ("test_batch_missing", "TEST_BATCH_MISSING"),
])
async def test_r2fh3_test_01_test_to_real_references_fail(change, code) -> None:
    repo = await ready_repo()
    if change == "test_personnel_links_real_technician":
        repo._personnel_master.append(person("P-T", technician_id="T-1", test=True, batch="SYN-B"))
    elif change == "test_personnel_links_real_account":
        repo._personnel_master.append(person("P-T", user_id="U-1", test=True, batch="SYN-B"))
    elif change == "test_link_history_names_real_personnel":
        repo._personnel_technician_link_history.append({"link_event_id": "PTL-SYN", "personnel_id": "P-1",
                                                        "is_test_data": "TRUE", "test_batch_id": "SYN-B"})
    elif change == "test_caretaker_on_real_equipment":
        equipment = repo._equipment_reference[0].values["equipment_id"] if repo._equipment_reference else "EQP-1"
        repo._equipment_caretaker_history.append({"record_id": "ECH-SYN", "equipment_id": equipment,
                                                  "is_test_data": "TRUE", "test_batch_id": "SYN-B"})
    elif change == "test_v2_job_on_real_vehicle":
        await new_repair(repo)  # a mock TEST V2 job on the seed (REAL-scoped) vehicle
    elif change == "test_v2_row_on_real_job":
        row = dict(v2_rows(repo)[0], is_test_data="TRUE", test_batch_id="SYN-B", request_id="other",
                   repair_assignment_id="RTA-" + "0" * 32 + "-1-1")
        v2_rows(repo).append(row)
    elif change == "flag_invalid":
        repo._personnel_department_history.append({"record_id": "PDH-SYN", "is_test_data": "yes"})
    elif change == "test_batch_missing":
        repo._personnel_master.append(person("P-T", test=True, batch=""))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL" and code in codes(report, "C1-26-4")
    assert report.overall == "NOT_READY"


@pytest.mark.asyncio
async def test_r2fh3_test_02_test_rows_with_test_only_references_are_clean() -> None:
    repo = await ready_repo()
    repo._technician_master.append(tech("T-TEST", scope=REFERENCE_SCOPE_TEST, batch="SYN-B"))
    repo._personnel_master.append(person("P-T", technician_id="T-TEST", test=True, batch="SYN-B"))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "PASS"
    personnel = next(e for e in report.coverage if e.source == "personnel")
    assert (personnel.status, personnel.test_rows, personnel.real_rows) == ("EXAMINED", 1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read_equipment_caretaker_history_validated",
                                    "read_personnel_department_history_validated",
                                    "read_crane_driver_responsibility_history_validated"])
async def test_r2fh3_test_03_an_unassessable_source_blocks_and_is_never_clean(method) -> None:
    repo = await ready_repo()

    async def broken(*_a, **_k):
        raise RepositorySchemaError("synthetic_tab", "MISSING_HEADERS", ("is_test_data",))

    setattr(repo, method, broken)
    report = await run(repo)
    assert check(report, "C1-26-4").status == "BLOCKED" and report.overall == "BLOCKED"
    assert any(e.status == "NOT_ASSESSABLE" for e in report.coverage)
    assert any("TEST segregation not provable" in g for g in report.gaps)


@pytest.mark.asyncio
async def test_r2fh3_test_04_an_absent_history_tab_is_listed_and_never_proven_clean() -> None:
    # H3-01: an absent tagged tab is listed ABSENT and blocks C1-26-4 (no C1
    # clause makes absence sufficient evidence; owner decision D5 PENDING).
    repo = await ready_repo()

    async def absent(*_a, **_k):
        raise RepositorySchemaError("personnel_department_history", "TAB_MISSING")

    repo.read_personnel_department_history_validated = absent
    report = await run(repo)
    entry = next(e for e in report.coverage if e.source == "department_history")
    assert entry.status == "ABSENT" and check(report, "C1-26-4").status == "BLOCKED"


@pytest.mark.asyncio
async def test_r2fh3_test_05_coverage_inventory_lists_every_source_and_exclusion() -> None:
    report = await run(await ready_repo())
    by_source = {e.source: e for e in report.coverage}
    for key in ("personnel", "departments", "link_technician", "link_account", "link_driver", "lifecycle_personnel",
                "lifecycle_department", "caretaker", "crane_driver", "department_history", "v2_repair", "v2_pm",
                "jobs_repair", "jobs_pm", "technicians", "accounts", "drivers", "vehicles", "equipment"):
        assert by_source[key].status == "EXAMINED", key
    assert by_source["asset_branch_history"].status == "EXCLUDED_BY_CONTRACT"
    assert by_source["vehicle_registration_history"].status == "EXCLUDED_BY_CONTRACT"
    assert by_source["vehicle_driver"].status == "UNTAGGED"
    assert "assignee_id->TECHNICIAN" in by_source["v2_repair"].references_verified


# ---------------------------------------------------------------------------
# R2FH3-SCHEMA — C1-26-6 (governance 14, 15)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "kind"), [
    ("read_work_order_v2_rows", "REPAIR"), ("read_work_order_v2_rows", "PM"),
    ("read_work_assignment_v2_rows", "REPAIR"), ("read_work_assignment_v2_rows", "PM"),
])
async def test_r2fh3_schema_01_each_v2_runtime_tab_without_its_headers_fails(method, kind) -> None:
    repo = await ready_repo()
    original = getattr(repo, method)

    async def maybe_missing(k):
        if k == kind:
            raise RepositorySchemaError("v2_tab", "MISSING_HEADERS", ("assignment_model",))
        return await original(k)

    setattr(repo, method, maybe_missing)
    report = await run(repo)
    assert check(report, "C1-26-6").status == "FAIL"
    assert codes(report, "C1-26-6") == ["SCHEMA_MISSING_HEADERS"]
    assert check(report, "C1-26-5").status == "BLOCKED" and report.overall == "NOT_READY"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read_personnel_relationship_master", "read_technician_master_reference",
                                    "read_user_account_reference", "read_driver_master_reference"])
async def test_r2fh3_schema_02_missing_master_headers_fail_and_block_dependants(method) -> None:
    repo = await ready_repo()

    async def missing(*_a, **_k):
        raise RepositorySchemaError("master", "MISSING_HEADERS", ("x",))

    setattr(repo, method, missing)
    report = await run(repo)
    assert check(report, "C1-26-6").status == "FAIL"
    if method != "read_driver_master_reference":
        assert {check(report, c).status for c in ("C1-26-1", "C1-26-2", "C1-26-3")} == {"BLOCKED"}
        assert report.population is None
    assert report.overall == "NOT_READY"


# ---------------------------------------------------------------------------
# R2FH3-OVERALL — READY only when all six PASS (governance 17, 18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh3_overall_01_ready_only_with_six_passes_and_it_enables_nothing() -> None:
    from app.config import Settings

    repo = await ready_repo()
    report = await run(repo)
    assert [c.status for c in report.checks] == ["PASS"] * 6 and report.overall == "READY"
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): the V2 cutover setting no longer exists, so the
    # report neither carries nor can enable it.
    assert not hasattr(report, "cutover_enabled") and not report.gaps
    assert not hasattr(Settings(_env_file=None), "technician_assignment_v2_enabled")


@pytest.mark.asyncio
async def test_r2fh3_overall_02_any_fail_blocked_or_undetermined_is_never_ready() -> None:
    base = await run(await ready_repo())
    assert base.overall == "READY"
    variants = []
    repo = await ready_repo()
    repo._personnel_master[0]["active_status"] = "INACTIVE"
    variants.append(await run(repo))  # FAIL
    variants.append(await run(await ready_repo(), recipients=OMIT))  # BLOCKED
    repo = await ready_repo()
    repo._personnel_master[1]["technician_id"] = ""
    variants.append(await run(repo, recipients=("P-1",), my_work=("P-1", "P-2")))  # UNDETERMINED (+ FAIL 5? no)
    for report in variants:
        assert report.overall in ("NOT_READY", "BLOCKED")
    assert check(variants[2], "C1-26-3").status == "UNDETERMINED" and variants[2].overall == "NOT_READY"


# ---------------------------------------------------------------------------
# R2FH3-CTX — REAL only; environment reported unchanged (governance 19, 20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh3_ctx_01_real_only_with_zero_reads_otherwise() -> None:
    repo = repo_with()
    repo.calls.clear()
    with pytest.raises(ApiError) as exc:
        await run(repo, context="TEST")
    assert (exc.value.code, exc.value.status_code) == ("GO_LIVE_READINESS_REQUIRES_REAL_CONTEXT", 409)
    with pytest.raises(ApiError) as exc:
        await run(repo, context=None)
    assert exc.value.code == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2fh3_ctx_02_the_environment_is_reported_never_changed() -> None:
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): the removed V2 cutover setting is no longer part of
    # the reported environment; the data context and the authentication mode still are.
    report = await run(await ready_repo())
    assert report.data_context == "REAL" and report.dev_auth_effective is True
    assert not hasattr(report, "cutover_enabled")


# ---------------------------------------------------------------------------
# R2FH3-RO — zero writes, legacy untouched (governance 22, 23)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh3_ro_01_the_report_writes_nothing_and_leaves_legacy_records_untouched() -> None:
    repo = await ready_repo()
    legacy = await new_repair(repo, legacy=True, **REAL)
    await seed_legacy_repair_assignment(legacy, "u-legacy", [], repo=repo)  # B6: legacy storage seed
    await new_pm(repo, **REAL)
    snapshot = (copy.deepcopy(v2_rows(repo)), copy.deepcopy(repo._personnel_master),
                copy.deepcopy(repo._repair_assignment_history), {k: v.model_dump() for k, v in repo._repairs.items()},
                list(repo.registry_write_log))
    repo.calls.clear()
    report = await run(repo)
    assert {c for c in repo.calls if not c.startswith("read_")} == set()
    assert (v2_rows(repo), repo._personnel_master, repo._repair_assignment_history,
            {k: v.model_dump() for k, v in repo._repairs.items()}, repo.registry_write_log) == snapshot
    jobs = next(e for e in report.coverage if e.source == "jobs_repair")
    assert "untagged legacy row" in jobs.detail  # the legacy job is never treated as TEST or REAL V2 data


# ---------------------------------------------------------------------------
# R2FH3-FAIL — a read failure is 503, never an empty result (governance 25)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read_personnel_relationship_master", "read_technician_master_reference",
                                    "read_work_assignment_v2_rows", "read_work_order_v2_rows",
                                    "read_personnel_link_history_validated", "read_lifecycle_history_validated"])
async def test_r2fh3_fail_01_transport_failures_fail_the_whole_report(method) -> None:
    repo = await ready_repo()

    async def broken(*_a, **_k):
        raise RepositoryError("simulated transport failure")

    setattr(repo, method, broken)
    with pytest.raises(ApiError) as exc:
        await run(repo)
    assert (exc.value.code, exc.value.status_code) == ("GO_LIVE_READINESS_READ_FAILED", 503)


# ---------------------------------------------------------------------------
# R2FH3-COUNT — no hard-coded counts (governance 26)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("n", [1, 3, 5])
async def test_r2fh3_count_01_evidence_counts_follow_the_data(n) -> None:
    repo = repo_with(n=n)
    ids = tuple(f"P-{i}" for i in range(1, n + 1))
    report = await run(repo, recipients=ids, my_work=ids)
    assert report.overall == "READY"
    assert check(report, "C1-26-1").evidence["resolved"] == n
    assert check(report, "C1-26-3").evidence["unique_people"] == n
    assert len(report.population) == n


# ---------------------------------------------------------------------------
# R2FH3-H301 — independent-review finding H3-01: an unproven TEST reference is
# never clean (C1 §15: a TEST reference must be PROVEN to target a TEST record
# of the same batch; anything unproven fails closed)
# ---------------------------------------------------------------------------


def _schema_error(tab: str, problem: str):
    async def broken(*_a, **_k):
        raise RepositorySchemaError(tab, problem, ("equipment_id",) if problem != "TAB_MISSING" else ())

    return broken


def _test_caretaker(repo, equipment_id: str, batch: str = "SYN-B") -> None:
    repo._equipment_caretaker_history.append({"record_id": "ECH-SYN", "equipment_id": equipment_id,
                                              "is_test_data": "TRUE", "test_batch_id": batch})


@pytest.mark.asyncio
async def test_r2fh3_h301_01_test_reference_into_an_absent_target_master_is_blocked() -> None:
    repo = await ready_repo()
    _test_caretaker(repo, "EQP-SYN-ANY")
    repo.read_equipment_reference = _schema_error("equipment_master", "TAB_MISSING")
    report = await run(repo)
    assert check(report, "C1-26-4").status == "BLOCKED", (check(report, "C1-26-4").status, report.gaps)
    assert any("equipment_master" in g and "TAB_MISSING" in g for g in report.gaps)
    assert report.overall != "READY"


@pytest.mark.asyncio
async def test_r2fh3_h301_02_test_reference_into_an_invalid_target_schema_is_blocked() -> None:
    repo = await ready_repo()
    _test_caretaker(repo, "EQP-SYN-ANY")
    repo.read_equipment_reference = _schema_error("equipment_master", "MISSING_HEADERS")
    report = await run(repo)
    assert check(report, "C1-26-4").status == "BLOCKED"
    assert any("equipment_master" in g and "MISSING_HEADERS" in g for g in report.gaps)
    assert report.overall != "READY"


@pytest.mark.asyncio
async def test_r2fh3_h301_03_test_reference_of_unprovable_scope_fails() -> None:
    repo = await ready_repo()
    repo._personnel_master.append(person("P-X", test=True, batch="SYN-B") | {"is_test_data": "maybe"})
    repo._personnel_technician_link_history.append({"link_event_id": "PTL-SYN", "personnel_id": "P-X",
                                                    "is_test_data": "TRUE", "test_batch_id": "SYN-B"})
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL"
    assert "TEST_REFERENCE_SCOPE_UNPROVEN" in codes(report, "C1-26-4")


@pytest.mark.asyncio
async def test_r2fh3_h301_04_test_reference_to_a_real_entity_fails() -> None:
    repo = await ready_repo()
    repo._personnel_master.append(person("P-T", technician_id="T-1", test=True, batch="SYN-B"))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL" and "TEST_REFERENCES_REAL" in codes(report, "C1-26-4")


@pytest.mark.asyncio
async def test_r2fh3_h301_05_test_reference_to_a_proven_test_entity_of_the_same_batch_is_clean() -> None:
    repo = await ready_repo()
    repo._technician_master.append(tech("T-TEST", scope=REFERENCE_SCOPE_TEST, batch="SYN-B"))
    repo._personnel_master.append(person("P-T", technician_id="T-TEST", test=True, batch="SYN-B"))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "PASS" and codes(report, "C1-26-4") == []


@pytest.mark.asyncio
async def test_r2fh3_h301_05b_test_reference_to_a_test_entity_of_another_batch_fails() -> None:
    repo = await ready_repo()
    repo._technician_master.append(tech("T-TEST", scope=REFERENCE_SCOPE_TEST, batch="SYN-OTHER"))
    repo._personnel_master.append(person("P-T", technician_id="T-TEST", test=True, batch="SYN-B"))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL", check(report, "C1-26-4").status
    assert "TEST_REFERENCE_BATCH_MISMATCH" in codes(report, "C1-26-4")


@pytest.mark.asyncio
async def test_r2fh3_h301_05c_test_reference_missing_from_a_validated_master_fails() -> None:
    repo = await ready_repo()
    repo._personnel_master.append(person("P-T", technician_id="T-NOWHERE", test=True, batch="SYN-B"))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL", check(report, "C1-26-4").status
    assert "TEST_REFERENCE_MISSING" in codes(report, "C1-26-4")


@pytest.mark.asyncio
async def test_r2fh3_h301_06_test_row_without_a_batch_fails() -> None:
    repo = await ready_repo()
    repo._personnel_master.append(person("P-T", test=True, batch=""))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL" and "TEST_BATCH_MISSING" in codes(report, "C1-26-4")


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "tab"), [
    ("read_personnel_department_history_validated", "personnel_department_history"),
    ("read_equipment_caretaker_history_validated", "equipment_caretaker_history"),
    ("read_crane_driver_responsibility_history_validated", "crane_driver_responsibility_history"),
    ("read_department_reference", "department_master"),
])
async def test_r2fh3_h301_07_an_absent_tagged_source_never_proves_complete_test_coverage(method, tab) -> None:
    repo = await ready_repo()
    setattr(repo, method, _schema_error(tab, "TAB_MISSING"))
    report = await run(repo)
    entry = next(e for e in report.coverage if e.tab == tab)
    assert entry.status == "ABSENT"
    assert check(report, "C1-26-4").status == "BLOCKED", check(report, "C1-26-4").status
    assert check(report, "C1-26-4").evidence["coverage_complete"] is False
    assert any(tab in g and "absent" in g for g in report.gaps) and report.overall == "BLOCKED"


@pytest.mark.asyncio
async def test_r2fh3_h301_08_real_side_keeps_missing_row_and_missing_tab_distinct() -> None:
    # A REAL row naming an id absent from a VALIDATED master: REFERENCE_MISSING
    # (FAIL). The same row while the master tab is ABSENT: not provable (BLOCKED).
    repo = await ready_repo()
    repo._equipment_caretaker_history.append({"record_id": "ECH-SYN-R", "equipment_id": "EQP-SYN-NONE",
                                              "is_test_data": "FALSE", "test_batch_id": ""})
    report = await run(repo)
    assert check(report, "C1-26-5").status == "FAIL" and "REFERENCE_MISSING" in codes(report, "C1-26-5")
    repo.read_equipment_reference = _schema_error("equipment_master", "TAB_MISSING")
    report = await run(repo)
    assert check(report, "C1-26-5").status == "BLOCKED" and codes(report, "C1-26-5") == []
    assert any("target equipment_master ABSENT" in g for g in report.gaps)


@pytest.mark.asyncio
async def test_r2fh3_h301_05d_test_reference_to_a_duplicated_test_entity_is_not_proven() -> None:
    repo = await ready_repo()
    repo._technician_master += [tech("T-TEST", scope=REFERENCE_SCOPE_TEST, batch="SYN-B")] * 2
    repo._personnel_master.append(person("P-T", technician_id="T-TEST", test=True, batch="SYN-B"))
    report = await run(repo)
    assert check(report, "C1-26-4").status == "FAIL" and "TEST_REFERENCE_AMBIGUOUS" in codes(report, "C1-26-4")
