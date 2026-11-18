"""R8 (R8-09, Owner source approval 2026-11-18) — fleet part-lifetime-due report.
SYNTHETIC Mock/TEST data only.

Proves: trusted can_view guard before any read; the R6 per-vehicle results are
reused (identical rules for the same vehicle as GET /vehicles/{id}/part-lifetime);
UNKNOWN is never NOT_DUE and "no applicable rule" is its own status; vehicles out
of the data scope are counted, not hidden; bounded paging over vehicles; branch
filter shared with the vehicle list.
"""
from __future__ import annotations

import pytest

from app.api.v1.reports import _item_status
from app.repositories.mock.repository import MockRepository
from tests.test_r8_read_authorization import NoReadRepo, _http

PATH = "/api/v1/reports/part-lifetime-due"


@pytest.mark.parametrize("statuses,expected", [
    ([], "NO_APPLICABLE_RULE"),
    (["NOT_DUE"], "NOT_DUE"),
    (["NOT_DUE", "NOT_DUE"], "NOT_DUE"),
    (["NOT_DUE", "UNKNOWN"], "UNKNOWN"),
    (["UNKNOWN", "DUE"], "DUE"),
    (["DUE_ACTION_NOT_DECLARED"], "UNKNOWN"),  # any non-proven state is never shown as not due
])
def test_item_status_rule(statuses, expected) -> None:
    assert _item_status([{"status": s} for s in statuses]) == expected


async def test_guard_before_any_read(monkeypatch) -> None:
    assert (await _http("GET", PATH, NoReadRepo(), role="UNKNOWN")).status_code == 403
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    assert (await _http("GET", PATH, NoReadRepo(), role=None, user=None)).status_code == 403


@pytest.mark.parametrize("role", ["ADMIN", "DRIVER", "TECHNICIAN"])
async def test_can_view_readers_get_the_report(role) -> None:
    response = await _http("GET", PATH, MockRepository(), role=role)
    assert response.status_code == 200, response.text


async def test_report_reuses_the_per_vehicle_results_and_discloses_scope() -> None:
    repo = MockRepository(access_management_seed=True)  # carries the R7 synthetic due part on VEH-1048
    body = (await _http("GET", PATH, repo, params={"page_size": 50})).json()
    assert body["total_vehicles"] == body["vehicles_evaluated"] + body["vehicles_out_of_scope"]
    assert body["vehicles_out_of_scope"] >= 1  # REAL-scoped mock vehicles in the TEST context: counted
    per_vehicle = (await _http("GET", "/api/v1/vehicles/VEH-1048/part-lifetime", repo)).json()
    expected = sorted(i["target_id"] for i in per_vehicle["instances"]) + sorted(
        p["target_id"] for i in per_vehicle["instances"] for p in i["hosted_positions"]) + sorted(
        p["target_id"] for p in per_vehicle["positions"])
    got = [i["target_id"] for i in body["items"] if i["vehicle_id"] == "VEH-1048"]
    assert expected and sorted(got) == sorted(expected)  # not vacuous: the seeded part is present
    (seeded,) = [i for i in body["items"] if i["target_id"] == "PINST-TEST-R7-0001"]
    assert seeded["status"] == "DUE" and [r["status"] for r in seeded["rules"]] == ["DUE"]
    for item in body["items"]:
        assert item["status"] in ("DUE", "NOT_DUE", "UNKNOWN", "NO_APPLICABLE_RULE")
        if item["status"] == "NOT_DUE":
            assert item["rules"] and all(r["status"] == "NOT_DUE" for r in item["rules"])


async def test_status_filter_paging_and_branch() -> None:
    repo = MockRepository()
    due = (await _http("GET", PATH, repo, params={"status": "DUE", "page_size": 50})).json()
    assert all(i["status"] == "DUE" for i in due["items"])
    assert (await _http("GET", PATH, repo, params={"page_size": 51})).status_code == 422
    assert (await _http("GET", PATH, repo, params={"status": "LATE"})).status_code == 422
    branch = (await _http("GET", PATH, repo, params={"branch_id": "BR-LAEM-CHABANG"})).json()
    assert branch["total_vehicles"] == 1 and branch["branch_id"] == "BR-LAEM-CHABANG"
