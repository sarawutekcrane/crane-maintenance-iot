"""R2 Batch R2f-h4 precondition — read-only frontend signals (owner decision
D-H4-1), mock / service level. Every row is SYNTHETIC.

- `assignment_model` on the Repair / PM DETAIL surfaces: the PERSISTED marker,
  "LEGACY" / "TECHNICIAN_V2" / "INVALID" (fail closed), never the cutover flag.
- `/me`: the effective `data_context` ("REAL" / "TEST" / "UNCONFIGURED"; never
  REAL unless the server is exactly REAL). R2 Batch R2f-h4 B6 Rev2 (owner final
  decision: Technician V2 only): the former `technician_assignment_v2_enabled`
  signal is removed together with the setting (deliberate test migration below).

Governance list 1-16: R2FH4P-MODEL (1-6), -ME (7-10), -SAFE (11, 12, 14-16);
item 13 (legacy tests) is evidenced by the candidate diff.
"""
from __future__ import annotations

import copy
import uuid

import pytest

from app.api.v1.me_schemas import MeResponse
from app.api.v1.pm_schemas import PmWorkOrderResponse, PmWorkOrderSummaryResponse
from app.api.v1.repair_schemas import RepairResponse, RepairSummaryResponse
from app.config import Settings
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.read_signals import assignment_model_signal, data_context_signal
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    VEHICLE,
    assign,
    body,
    new_pm,
    new_repair,
    repo_with,
    T1,
)

MOCK = Settings(technician_assignment_v2_enabled=False)  # B6 Rev2: a leftover former OFF value, ignored
GO_LIVE = "/api/v1/technician-assignment/go-live-readiness"  # R2f-h3, read only (unchanged)


async def call(method: str, path: str, repo=None, *, settings: Settings | None = None, role: str = "MAINTENANCE",
               json=None, request_id: bool = False):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings or MOCK
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": role}
    if request_id:
        headers["X-Request-Id"] = str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def v2(enabled: bool) -> Settings:
    # R2 Batch R2f-h4 B6 Rev2: a LEFTOVER value of the removed setting — ignored by Settings (extra="ignore").
    return Settings(technician_assignment_v2_enabled=enabled)


async def repair_model(repo, repair_id: str, settings: Settings | None = None) -> str:
    response = await call("GET", f"{API}/repairs/{repair_id}", repo, settings=settings)
    assert response.status_code == 200, response.text
    return response.json()["repair"]["assignment_model"]


async def pm_model(repo, wo_id: str, settings: Settings | None = None) -> str:
    response = await call("GET", f"{API}/pm/work-orders/{wo_id}", repo, settings=settings)
    assert response.status_code == 200, response.text
    return response.json()["work_order"]["assignment_model"]


# ---------------------------------------------------------------------------
# R2FH4P-MODEL — the persisted assignment model (governance 1-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh4p_model_01_legacy_and_v2_jobs_report_their_persisted_model() -> None:
    repo = repo_with()
    legacy_repair, v2_repair = await new_repair(repo, legacy=True), await new_repair(repo)
    legacy_pm, v2_pm = await new_pm(repo, legacy=True), await new_pm(repo)
    assert await repair_model(repo, legacy_repair) == "LEGACY"
    assert await repair_model(repo, v2_repair) == "TECHNICIAN_V2"
    assert await pm_model(repo, legacy_pm) == "LEGACY"
    assert await pm_model(repo, v2_pm) == "TECHNICIAN_V2"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["technician_v2", " TECHNICIAN_V2", "TECHNICIAN_V2 ", "LEGACY", "V2", "UNKNOWN"])
async def test_r2fh4p_model_02_an_unknown_stored_marker_fails_closed_as_invalid(stored) -> None:
    repo = repo_with()
    repair_id, wo_id = await new_repair(repo), await new_pm(repo)
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(update={"assignment_model": stored})
    repo._pm_work_orders[wo_id] = repo._pm_work_orders[wo_id].model_copy(update={"assignment_model": stored})
    assert await repair_model(repo, repair_id) == "INVALID"
    assert await pm_model(repo, wo_id) == "INVALID"
    # The V2 and legacy operations keep refusing such a job, unchanged (R2f-h1).
    for path in (f"{API}/repairs/{repair_id}/technician-assignments",
                 f"{API}/pm/work-orders/{wo_id}/technician-assignments"):
        response = await call("GET", path, repo)
        assert (response.status_code, response.json()["error"]["code"]) == (500, "ASSIGNMENT_MODEL_DATA_INVALID")
    assert assignment_model_signal(None) == assignment_model_signal(0) == "INVALID"


@pytest.mark.asyncio
async def test_r2fh4p_model_03_the_signal_never_follows_the_cutover_setting() -> None:
    repo = repo_with()
    legacy_repair, v2_repair = await new_repair(repo, legacy=True), await new_repair(repo)
    legacy_pm, v2_pm = await new_pm(repo, legacy=True), await new_pm(repo)
    for enabled in (False, True, False):
        assert await repair_model(repo, legacy_repair, v2(enabled)) == "LEGACY"
        assert await repair_model(repo, v2_repair, v2(enabled)) == "TECHNICIAN_V2"
        assert await pm_model(repo, legacy_pm, v2(enabled)) == "LEGACY"
        assert await pm_model(repo, v2_pm, v2(enabled)) == "TECHNICIAN_V2"
    assert repo._repairs[legacy_repair].assignment_model == "" and repo._repairs[v2_repair].assignment_model \
        == "TECHNICIAN_V2"


@pytest.mark.asyncio
async def test_r2fh4p_model_04_every_repair_detail_surface_carries_the_same_signal() -> None:
    # create, GET, legacy assign, action, part, close: one consistent value.
    repo = repo_with()
    created = await call("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEHICLE,
                                                               "source_type": "MANUAL"})
    assert created.status_code == 200, created.text
    repair_id = created.json()["repair"]["repair_id"]
    seen = [created.json()["repair"]["assignment_model"]]
    seen.append(await repair_model(repo, repair_id))
    # R2 Batch R2f-h4 B6 (deliberate test migration): the legacy assign route is retired (410, no detail body), so
    # it is no longer a detail surface; every remaining Repair detail surface still carries the same signal.
    for path, payload in ((f"/repairs/{repair_id}/actions", {"action_text": "ตรวจสอบ (ทดสอบ)"}),
                          (f"/repairs/{repair_id}/parts", {"part_description": "SYN-PART", "quantity": 1}),
                          (f"/repairs/{repair_id}/close", {"close_note": "ทดสอบ"})):
        response = await call("POST", f"{API}{path}", repo, json=payload)
        assert response.status_code == 200, (path, response.text)
        seen.append(response.json()["repair"]["assignment_model"])
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): every created job is a V2 job (V2 only), so every
    # surface reports TECHNICIAN_V2 even with a leftover former OFF value in the settings.
    assert seen == ["TECHNICIAN_V2"] * 5
    # A leftover former ON value changes nothing either: create and GET agree.
    v2_created = await call("POST", f"{API}/repairs", repo, settings=v2(True),
                            json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL"})
    assert v2_created.status_code == 200, v2_created.text
    v2_id = v2_created.json()["repair"]["repair_id"]
    assert v2_created.json()["repair"]["assignment_model"] == await repair_model(repo, v2_id) == "TECHNICIAN_V2"


@pytest.mark.asyncio
async def test_r2fh4p_model_05_pm_detail_surfaces_agree_and_summaries_are_unchanged() -> None:
    repo = repo_with()
    wo_id = await new_pm(repo, legacy=True)
    v2_id = await new_pm(repo)
    assert await pm_model(repo, wo_id) == "LEGACY" and await pm_model(repo, v2_id) == "TECHNICIAN_V2"
    closed = await call("POST", f"{API}/pm/work-orders/{wo_id}/close", repo, json={})
    assert closed.status_code == 200, closed.text
    assert closed.json()["work_order"]["assignment_model"] == "LEGACY"
    # Summary / list surfaces are deliberately unchanged (frozen 7C2 exact shape and parity; see result doc).
    listed = await call("GET", f"{API}/pm/work-orders?asset_type=VEHICLE&asset_id={VEHICLE}", repo)
    assert listed.status_code == 200 and listed.json()["items"]
    assert all("assignment_model" not in item for item in listed.json()["items"])
    repairs = await call("GET", f"{API}/repairs?status=OPEN", repo)
    assert repairs.status_code == 200
    assert all("assignment_model" not in item for item in repairs.json()["items"])
    assert "assignment_model" not in RepairSummaryResponse.model_fields
    assert "assignment_model" not in PmWorkOrderSummaryResponse.model_fields


@pytest.mark.asyncio
async def test_r2fh4p_model_06_v2_set_reads_are_unchanged_and_the_signal_agrees() -> None:
    repo = repo_with()
    v2_id = await new_repair(repo)
    await assign(repo, v2_id, body(T1))
    read = await call("GET", f"{API}/repairs/{v2_id}/technician-assignments", repo)
    assert read.status_code == 200 and read.json()["assignment_model"] == "TECHNICIAN_V2"
    assert read.json()["current"]["primary_technician_id"] == T1
    assert await repair_model(repo, v2_id) == "TECHNICIAN_V2"


# ---------------------------------------------------------------------------
# R2FH4P-ME — /me server facts (governance 7-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_r2fh4p_me_01_reports_no_v2_cutover_signal_whatever_a_leftover_value(enabled) -> None:
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): the setting and its /me signal are removed.
    settings = v2(enabled)
    response = await call("GET", f"{API}/me", settings=settings)
    assert response.status_code == 200
    assert "technician_assignment_v2_enabled" not in response.json()
    assert set(response.json()) == {"user_id", "roles", "capabilities", "data_context"}
    assert not hasattr(settings, "technician_assignment_v2_enabled")


@pytest.mark.asyncio
@pytest.mark.parametrize(("settings", "expected"), [
    (Settings(), "TEST"),  # mock is always TEST
    (Settings(data_repository="google_sheets", registry_data_context="TEST"), "TEST"),
    (Settings(data_repository="google_sheets", registry_data_context="REAL"), "REAL"),
    (Settings(data_repository="google_sheets"), "UNCONFIGURED"),
])
async def test_r2fh4p_me_02_reports_the_effective_data_context(settings, expected) -> None:
    response = await call("GET", f"{API}/me", settings=settings)
    assert response.status_code == 200 and response.json()["data_context"] == expected


@pytest.mark.parametrize("value", ["TEST", "test", "Test", " REAL", "REAL ", "real", "", None, "UNCONFIGURED", 1])
def test_r2fh4p_me_03_test_or_unknown_is_never_represented_as_real(value) -> None:
    assert data_context_signal(value) != "REAL"
    assert data_context_signal(value) == ("TEST" if value == "TEST" else "UNCONFIGURED")


def test_r2fh4p_me_04_mock_can_never_be_configured_real() -> None:
    with pytest.raises(ValueError):
        Settings(data_repository="mock", registry_data_context="REAL")


# ---------------------------------------------------------------------------
# R2FH4P-SAFE — additive, read-only, no bypass (governance 11, 12, 14-16)
# ---------------------------------------------------------------------------


EXISTING = {
    RepairResponse: {"repair_id", "asset_type", "asset_id", "source_type", "source_id", "category", "symptom",
                     "meter_snapshot_id", "status", "opened_at", "opened_by", "closed_at", "closed_by",
                     "close_note", "closed_snapshot_id", "primary_technician", "collaborators"},
    PmWorkOrderResponse: {"pm_work_order_id", "asset_type", "asset_id", "pm_plan_id", "revision_id", "due_reason",
                          "status", "opened_at", "opened_by", "closed_at", "closed_by", "note",
                          "opened_snapshot_id", "closed_snapshot_id", "scope_task_ids", "scope_approved_at",
                          "scope_approved_by", "primary_technician", "collaborators"},
    MeResponse: {"user_id", "roles", "capabilities"},
}
ADDED = {RepairResponse: {"assignment_model",
                          # R3 (deliberate migration): round marker, completion event, cancellation.
                          "finding_id", "completion_submitted_at", "completion_submitted_by",
                          "completion_technician_id", "completion_note",
                          "cancelled_at", "cancelled_by", "cancel_reason"},
         PmWorkOrderResponse: {"assignment_model"},
         # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): the V2 cutover signal is removed (V2 only).
         MeResponse: {"data_context"}}


@pytest.mark.parametrize("model", list(EXISTING))
def test_r2fh4p_safe_01_every_existing_field_is_kept_and_only_the_signals_are_added(model) -> None:
    assert set(model.model_fields) == EXISTING[model] | ADDED[model]


@pytest.mark.asyncio
async def test_r2fh4p_safe_02_no_authorization_bypass_and_no_new_write_route() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert set(paths["/api/v1/me"]) == {"get"}
    assert not [p for p in paths if "cutover" in p or "context" in p or "go-live" in p and p != GO_LIVE]
    repo = repo_with()
    repair_id = await new_repair(repo, legacy=True)
    # Write capabilities are unchanged: a TECHNICIAN still cannot assign / close. R2 Batch R2f-h4 B6 (deliberate
    # test migration): the legacy assign route is retired for every caller (410, nothing read or written).
    denied = await call("POST", f"{API}/repairs/{repair_id}/assign", repo, role="TECHNICIAN",
                        json={"primary_technician": "u-x", "collaborators": []})
    assert denied.status_code == 410 and repo._repair_assignment_history.get(repair_id, []) == []
    v2_id = await new_repair(repo)
    denied_v2 = await call("POST", f"{API}/repairs/{v2_id}/technician-assignments", repo, role="TECHNICIAN",
                           json=body(T1), request_id=True)
    assert denied_v2.status_code == 403
    # /me is still answered for any caller and adds no capability.
    me = (await call("GET", f"{API}/me", role="DRIVER")).json()
    assert "can_manage_repair" not in me["capabilities"] and me["data_context"] == "TEST"


@pytest.mark.asyncio
async def test_r2fh4p_safe_03_signals_are_read_only() -> None:
    repo = repo_with()
    legacy_id, v2_id = await new_repair(repo, legacy=True), await new_repair(repo)
    wo_id = await new_pm(repo)
    await assign(repo, v2_id, body(T1))
    before = (copy.deepcopy(repo._repairs), copy.deepcopy(repo._pm_work_orders),
              copy.deepcopy(repo._technician_assignment_rows), len(repo.registry_write_log))
    repo.calls.clear()
    for path in (f"{API}/me", f"{API}/repairs/{legacy_id}", f"{API}/repairs/{v2_id}", f"{API}/pm/work-orders/{wo_id}"):
        assert (await call("GET", path, repo)).status_code == 200
    after = (repo._repairs, repo._pm_work_orders, repo._technician_assignment_rows, len(repo.registry_write_log))
    assert after == before
    assert repo.calls and all(name.startswith(("get_", "read_", "list_")) for name in repo.calls), repo.calls


@pytest.mark.asyncio
async def test_r2fh4p_safe_04_no_go_live_activation() -> None:
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): with V2 the only model there is no setting to activate;
    # "no Go-live" is now: the default (mock) server stays TEST, and a created job is a TEST-scoped V2 job of the
    # mock batch — never REAL.
    assert not hasattr(Settings(), "technician_assignment_v2_enabled")
    response = await call("GET", f"{API}/me", settings=Settings())
    assert "technician_assignment_v2_enabled" not in response.json() and response.json()["data_context"] == "TEST"
    repo = repo_with()
    created = await call("POST", f"{API}/repairs", repo, settings=Settings(),
                         json={"asset_type": "VEHICLE", "asset_id": VEHICLE, "source_type": "MANUAL"})
    assert created.json()["repair"]["assignment_model"] == "TECHNICIAN_V2"
    job = repo._repairs[created.json()["repair"]["repair_id"]]
    assert (job.is_test_data, job.test_batch_id) == ("TRUE", MOCK_TEST_BATCH_ID)
