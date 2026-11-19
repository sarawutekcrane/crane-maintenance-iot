"""R8 PRE-UAT — the config-gated uat_r8 Mock fixture profile (deterministic, synthetic, TEST)
and the fail-closed configuration of both PRE-UAT flags."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.repositories.mock.repository import MockRepository
from app.repositories.mock.uat_fixture_profile import MODELS, PERSONNEL, VEHICLES


def test_default_construction_is_unchanged() -> None:
    plain = MockRepository()
    assert not any(v.startswith("UAT8-") for v in plain._vehicles)
    assert plain._preuat_journals == {} and plain._preuat_created == {}


async def test_profile_adds_deterministic_test_scoped_fleet() -> None:
    a, b = MockRepository(fixture_profile="uat_r8"), MockRepository(fixture_profile="uat_r8")
    ids = [v[0] for v in VEHICLES]
    assert all(i in a._vehicles for i in ids)
    assert sorted({a._vehicles[i].operational_status.value for i in ids}) == \
        ["LONG_TERM_PARKING", "MAINTENANCE", "OUT_OF_SERVICE", "READY", "WORKING"]
    assert {a._vehicle_registry[i]["responsible_branch_id"] for i in ids} == \
        {"BR-BANGNA-KM6", "BR-LAEM-CHABANG", "BR-RAYONG"}
    ref = await a.read_vehicle_reference()
    assert {r.scope for r in ref.rows if r.values["vehicle_id"] in ids} == {"TEST"}
    assert "UAT8-VEH-03" not in a._current_counters  # deliberately UNKNOWN meters (never 0)
    assert "UAT8-VEH-05" not in a._current_locations  # no GPS
    assert [m.model_id for m in a._models.values() if m.model_id.startswith("UAT8-")] == [m[0] for m in MODELS]
    rows = [r for r in a._personnel_master if r["personnel_id"].startswith("UAT8-")]
    assert len(rows) == len(PERSONNEL) and {r["is_test_data"] for r in rows} == {"TRUE"}
    assert [c.certificate_id for c in a._vehicle_certificates["UAT8-VEH-04"]] == ["UAT8-CERT-03"]
    assert sorted(a._vehicles) == sorted(b._vehicles)


def test_unknown_profile_is_refused() -> None:
    with pytest.raises(ValueError):
        MockRepository(fixture_profile="prod_copy")


@pytest.mark.parametrize("kwargs", [
    {"mock_fixture_profile": "other"},
    {"mock_fixture_profile": "uat_r8", "data_repository": "google_sheets"},
    {"mock_fixture_profile": "uat_r8", "app_env": "production"},
    {"mock_fixture_profile": "uat_r8", "app_env": "staging"},
    {"pm_master_test_profile": True},
    {"pm_master_test_profile": True, "access_management_mode": True, "app_env": "production"},
])
def test_both_flags_fail_closed(kwargs) -> None:
    base = {"data_repository": "mock", "app_env": "development"}
    with pytest.raises(ValueError):
        Settings(**{**base, **kwargs})


def test_flags_are_off_by_default_and_accepted_only_in_mock_dev() -> None:
    assert Settings().mock_fixture_profile == "" and Settings().pm_master_test_profile is False
    ok = Settings(data_repository="mock", app_env="development", mock_fixture_profile="uat_r8",
                  pm_master_test_profile=True, access_management_mode=True)
    assert ok.mock_fixture_profile == "uat_r8" and ok.pm_master_test_profile is True


# PG-5 P-A (Owner gate 2026-11-18): the part writes in Access Management mode, end to end ------------


async def test_part_writes_in_access_management_need_the_explicit_test_grant(monkeypatch) -> None:
    import uuid as _uuid

    from tests import test_access_management as am

    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)
    store = MockRepository(access_management_seed=True, fixture_profile="uat_r8")
    api = am.API
    maintenance = {"action": "REPAIRED_IN_PLACE", "lifetime_rule_id": "UAT8-LTR-REPAIR", "outcome": "ปกติ"}
    path = f"{api}/part-instances/UAT8-PINST-01/maintenance-events"
    # No grant (root holder, any role): refused by D6 before the handler; nothing recorded.
    for role in ("TECHNICIAN", "ADMIN"):
        refused = await am.http("POST", path, store, am.MGR, role=role, json=maintenance)
        assert am.code(refused) == (403, "PREUAT_ACTION_NOT_AUTHORIZED")
    assert store._part_state.maintenance.get("UAT8-PINST-01", ()) == ()
    await am.grant(store, am.MGR, am.employee(am.MGR), {"can_view": True, "can_manage_repair": True,
                                                         "can_test_manage_parts": True})
    before = store._part_state.lifecycles["UAT8-PINST-01"]
    rq = str(_uuid.uuid4())
    done = await am.http("POST", path, store, am.MGR, json=maintenance, request_id=rq)
    assert done.status_code == 200, done.text
    again = await am.http("POST", path, store, am.MGR, json=maintenance, request_id=rq)
    assert again.status_code == 200 and again.json() == done.json()  # replay, not a second event
    assert len(store._part_state.maintenance["UAT8-PINST-01"]) == 1
    assert store._part_state.lifecycles["UAT8-PINST-01"] == before  # no lifecycle opened or closed
    wrong = await am.http("POST", path, store, am.MGR, json={**maintenance, "lifetime_rule_id": "UAT8-LTR-INSPECT"})
    assert am.code(wrong) == (422, "MAINTENANCE_RULE_MISMATCH")
    created = await am.http("POST", f"{api}/part-sets", store, am.MGR, json={"set_code": "UAT8-SET", "name": "ชุดทดสอบ"})
    assert created.status_code == 200, created.text
    # The other R6 part writes stay unresolved even for the grant holder.
    unresolved = await am.http("POST", f"{api}/part-instances/UAT8-PINST-01/status", store, am.MGR, json={})
    assert am.code(unresolved) == (403, "ACCESS_CAPABILITY_MAPPING_UNRESOLVED")
