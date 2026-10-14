"""R2 Batch R2f-h4 B6 Rev2 — owner final decision: Technician V2 is the ONLY
technician assignment model. No V2 ON/OFF setting, no legacy creation, no
legacy fallback.

Proves, on the mock repository with the B2 synthetic TEST fixtures (and the
service level for the server contexts a mock cannot express):

- every creation entry point (direct Repair, PM open, Repair Request
  conversion) creates a TECHNICIAN_V2 job, whatever a LEFTOVER value of the
  removed `TECHNICIAN_ASSIGNMENT_V2_ENABLED` setting (environment variable or
  settings value) says;
- creation is never blocked by such a value, and a failed V2 precondition (no
  data context, live TEST, missing extended header) fails the creation CLOSED
  with zero writes — never a silent LEGACY job;
- authentication / capability and input validation still decide first; the
  Repair Request submission is unaffected; `/me` carries no V2 flag.
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.pm_service import PmService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.repair import RepairSourceType
from app.domain.repair_service import RepairService
from app.domain.technician_assignment import AssignmentCutover, cutover_from_settings
from app.errors import ApiError
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    BATCH,
    T1,
    VEHICLE,
    _code,
    assign,
    body,
    http,
    repo_with,
    v2_rows,
)

LEFTOVERS = [False, True]
LEFTOVER_IDS = ["leftover-off", "leftover-on"]
V2_TEST_MARKER = ("TECHNICIAN_V2", "TRUE", BATCH)


def _marker(job) -> tuple[str, str, str]:
    return job.assignment_model, job.is_test_data, job.test_batch_id


def _writes(repo) -> tuple[int, int, int]:
    return len(repo._repairs), len(repo._pm_work_orders), len(repo._meter_snapshots)


async def _plan_id(repo) -> str:
    statuses = await PmService(repo, MeterService(repo)).list_applicable_plan_status(AssetType.VEHICLE, VEHICLE)
    return statuses[0].plan.pm_plan_id


# ---------------------------------------------------------------------------
# 1-5, 19 — every creation path is V2, whatever a leftover value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["false", "0", "", "true"])
def test_b6r2_01_a_leftover_environment_variable_neither_configures_nor_changes_anything(monkeypatch, value) -> None:
    monkeypatch.setenv("TECHNICIAN_ASSIGNMENT_V2_ENABLED", value)
    settings = Settings(_env_file=None)
    assert "technician_assignment_v2_enabled" not in Settings.model_fields
    cutover = cutover_from_settings(settings)
    assert cutover == AssignmentCutover(data_context="TEST", test_batch_id=MOCK_TEST_BATCH_ID, live=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("leftover", LEFTOVERS, ids=LEFTOVER_IDS)
async def test_b6r2_02_direct_repair_creation_is_always_v2(leftover) -> None:
    repo = repo_with()
    response = await http("POST", f"{API}/repairs", repo, v2=leftover,
                          json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL", "symptom": "x"})
    assert response.status_code == 200, response.text
    assert response.json()["repair"]["assignment_model"] == "TECHNICIAN_V2"
    assert _marker(repo._repairs[response.json()["repair"]["repair_id"]]) == V2_TEST_MARKER


@pytest.mark.asyncio
@pytest.mark.parametrize("leftover", LEFTOVERS, ids=LEFTOVER_IDS)
async def test_b6r2_03_pm_creation_is_always_v2(leftover) -> None:
    repo = repo_with()
    response = await http("POST", f"{API}/pm/work-orders", repo, v2=leftover,
                          json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "pm_plan_id": await _plan_id(repo)})
    assert response.status_code == 200, response.text
    assert response.json()["work_order"]["assignment_model"] == "TECHNICIAN_V2"
    assert _marker(repo._pm_work_orders[response.json()["work_order"]["pm_work_order_id"]]) == V2_TEST_MARKER


@pytest.mark.asyncio
@pytest.mark.parametrize("leftover", LEFTOVERS, ids=LEFTOVER_IDS)
async def test_b6r2_04_repair_request_submission_is_unaffected_and_conversion_is_always_v2(leftover) -> None:
    repo = repo_with()
    reported = await http("POST", f"{API}/repair-requests", repo, role="DRIVER", user="d-1", v2=leftover,
                          json={"vehicle_id": VEHICLE, "symptom_th": "เสียงดัง (ทดสอบ)"})
    assert reported.status_code == 200, reported.text
    request = reported.json()["request"]
    assert (request["request_status"], request["repair_id"]) == ("PENDING", None)
    assert repo._repairs == {}  # reporting a problem never creates a job
    converted = await http("POST", f"{API}/repair-requests/{request['repair_request_id']}/convert", repo,
                           role="MAINTENANCE", v2=leftover, json={})
    assert converted.status_code == 200, converted.text
    repair = converted.json()["repair"]
    assert (repair["assignment_model"], repair["source_type"], repair["source_id"]) == (
        "TECHNICIAN_V2", "REPAIR_REQUEST", request["repair_request_id"])
    assert _marker(repo._repairs[repair["repair_id"]]) == V2_TEST_MARKER
    after = (await http("GET", f"{API}/repair-requests/{request['repair_request_id']}", repo, v2=leftover)).json()
    assert (after["request_status"], after["repair_id"], after["symptom_th"]) == (
        "CONVERTED", repair["repair_id"], "เสียงดัง (ทดสอบ)")
    # Idempotent: converting again reuses the same job, never a second one.
    again = await http("POST", f"{API}/repair-requests/{request['repair_request_id']}/convert", repo,
                       role="MAINTENANCE", v2=leftover, json={})
    assert (again.status_code, again.json()["repair"]["repair_id"], len(repo._repairs)) == (200, repair["repair_id"], 1)


@pytest.mark.asyncio
async def test_b6r2_05_a_new_v2_job_starts_unassigned_in_u1_and_is_assignable_directly() -> None:
    repo = repo_with()
    created = await http("POST", f"{API}/repairs", repo, v2=False,
                         json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL"})
    job_id = created.json()["repair"]["repair_id"]
    queue = await http("GET", f"{API}/repairs/v2-waiting-assignment", repo, role="MAINTENANCE", request_id=None)
    assert {i["job_id"]: i["assignment_status"] for i in queue.json()["items"]}[job_id] == "NONE"
    assert (await assign(repo, job_id, body(T1))).changed  # no intermediate legacy step
    queue = await http("GET", f"{API}/repairs/v2-waiting-assignment", repo, role="MAINTENANCE", request_id=None)
    assert job_id not in {i["job_id"] for i in queue.json()["items"]}


# ---------------------------------------------------------------------------
# 6, 7, 16, 19 — safeguards decide first; a failed V2 precondition fails closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "payload"), [
    ("/repairs", {"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL"}),
    ("/pm/work-orders", {"asset_type": "VEHICLE", "asset_id": VEHICLE, "pm_plan_id": "PMP-0001"}),
])
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "MAINTENANCE_MANAGER"])
async def test_b6r2_06_creation_still_requires_the_management_capability(path, payload, role) -> None:
    repo = repo_with()
    before = _writes(repo)
    response = await http("POST", f"{API}{path}", repo, role=role, v2=True, json=payload)
    assert response.status_code == 403, response.text
    assert _writes(repo) == before


@pytest.mark.asyncio
async def test_b6r2_07_input_validation_still_decides_before_the_v2_proof() -> None:
    repo = repo_with()
    response = await http("POST", f"{API}/repairs", repo, v2=True,
                          json={"asset_type": "VEHICLE", "asset_id": "VEH-DOES-NOT-EXIST", "source_type": "MANUAL"})
    assert response.status_code in (404, 422) and _writes(repo) == (0, 0, 0)


def _services(repo, cutover: AssignmentCutover):
    meter = MeterService(repo)
    return RepairService(repo, meter, assignment_cutover=cutover), PmService(repo, meter, assignment_cutover=cutover)


@pytest.mark.asyncio
@pytest.mark.parametrize(("cutover", "code"), [
    (AssignmentCutover(), "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"),  # no context configured
    (AssignmentCutover(data_context="TEST", test_batch_id=""), "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"),
    (AssignmentCutover(data_context="TEST", test_batch_id="B-1", live=True), "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED"),
], ids=["context-unset", "test-batch-unset", "live-test"])
async def test_b6r2_08_a_failed_v2_precondition_fails_closed_with_zero_writes_never_legacy(cutover, code) -> None:
    repo = repo_with()
    repair_service, pm_service = _services(repo, cutover)
    plan_id = await _plan_id(repo)
    for create in (
        repair_service.create_repair(AssetType.VEHICLE, VEHICLE, RepairSourceType.MANUAL, None, None, None, None, "u"),
        pm_service.open_work_order(AssetType.VEHICLE, VEHICLE, plan_id, None, "u", None),
    ):
        with pytest.raises(ApiError) as exc:
            await create
        assert exc.value.code == code
    assert _writes(repo) == (0, 0, 0)  # no snapshot, no job, no legacy fallback
    assert v2_rows(repo) == [] and v2_rows(repo, "PM") == []


@pytest.mark.asyncio
async def test_b6r2_09_a_real_context_creates_a_real_scoped_v2_job_and_a_test_context_a_test_one() -> None:
    for cutover, expected in (
        (AssignmentCutover(data_context="REAL", test_batch_id="", live=False), ("TECHNICIAN_V2", "FALSE", "")),
        (AssignmentCutover(data_context="TEST", test_batch_id=BATCH, live=False), V2_TEST_MARKER),
    ):
        repo = repo_with()
        repair_service, _ = _services(repo, cutover)
        detail = await repair_service.create_repair(AssetType.VEHICLE, VEHICLE, RepairSourceType.MANUAL, None,
                                                    None, None, None, "u")
        assert _marker(repo._repairs[detail.repair.repair_id]) == expected


@pytest.mark.asyncio
async def test_b6r2_10_a_missing_extended_job_header_fails_creation_closed() -> None:
    from app.repositories.base import RepositorySchemaError

    repo = repo_with()

    async def missing_header(kind: str):
        raise RepositorySchemaError("repair_order" if kind == "REPAIR" else "pm_work_order",
                                    "MISSING_HEADERS", ("assignment_model",))

    repo.verify_work_order_v2_schema = missing_header  # type: ignore[method-assign]
    response = await http("POST", f"{API}/repairs", repo, v2=False,
                          json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL"})
    assert _code(response) == (500, "TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID")
    assert _writes(repo) == (0, 0, 0)


# ---------------------------------------------------------------------------
# 17 — /me carries no V2 ON/OFF signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("leftover", LEFTOVERS, ids=LEFTOVER_IDS)
async def test_b6r2_11_me_has_no_v2_enablement_signal(leftover) -> None:
    me = await http("GET", f"{API}/me", repo_with(), role="DRIVER", request_id=None, v2=leftover)
    assert me.status_code == 200 and set(me.json()) == {"user_id", "roles", "capabilities", "data_context"}
