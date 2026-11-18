"""R8 (R8-01 / R8-S1, Owner source approval 2026-11-18): the fleet status summary's
optional exact `branch_id` filter and its parity with `GET /vehicles?branch_id=`.

SYNTHETIC Mock data only. Parity is proven per status, so every dashboard card's
drill-through link (`/vehicles?status=S&branch_id=B`) lands on a list whose total equals
the card. The filter is a filter, not an authorization boundary (no branch-level data
authorization exists in source); the read guard is the trusted can_view reader.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.repositories.mock.repository import MockRepository

API = "/api/v1"
STATUSES = ["WORKING", "READY", "MAINTENANCE", "OUT_OF_SERVICE", "LONG_TERM_PARKING"]


async def _get(path: str, repo=None, *, role: str = "ADMIN", params=None):
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    headers = {"X-Request-Id": str(uuid.uuid4()), "X-Dev-Role": role, "X-Dev-User-Id": "USR-R8-DASH"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(path, headers=headers, params=params)
    reset_dependency_cache()
    get_settings.cache_clear()
    return response


@pytest.mark.parametrize("branch", ["BR-LAEM-CHABANG", "BR-BANGNA-KM6", "BR-UNKNOWN", "br-laem-chabang"])
async def test_branch_counts_equal_the_filtered_list_per_status(branch) -> None:
    repo = MockRepository()
    summary = await _get(f"{API}/dashboard/fleet-status", repo, params={"branch_id": branch})
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["branch_id"] == branch
    listed = await _get(f"{API}/vehicles", repo, params={"branch_id": branch, "page_size": 1})
    assert body["vehicle_total"] == listed.json()["total_items"]
    for status in STATUSES:
        per = await _get(f"{API}/vehicles", repo, params={"branch_id": branch, "status": status, "page_size": 1})
        assert body["status_counts"][status] == per.json()["total_items"], (branch, status)


async def test_branch_filter_is_exact_and_known_branches_have_their_vehicle() -> None:
    body = (await _get(f"{API}/dashboard/fleet-status", params={"branch_id": "BR-LAEM-CHABANG"})).json()
    assert body["vehicle_total"] == 1
    assert (await _get(f"{API}/dashboard/fleet-status", params={"branch_id": " BR-LAEM-CHABANG"})).json()[
        "vehicle_total"] == 0


async def test_unfiltered_body_is_unchanged() -> None:
    body = (await _get(f"{API}/dashboard/fleet-status")).json()
    assert list(body) == ["population", "vehicle_total", "status_counts"]


@pytest.mark.parametrize("value", ["", "B" * 101])
async def test_branch_value_validation(value) -> None:
    response = await _get(f"{API}/dashboard/fleet-status", params={"branch_id": value})
    assert response.status_code == 422


async def test_branch_filter_without_the_column_is_409_like_the_list() -> None:
    class NoBranchColumn(MockRepository):
        async def read_vehicle_master_with_registry(self):
            read = await super().read_vehicle_master_with_registry()
            from dataclasses import replace

            return replace(read, registry_columns=frozenset(c for c in read.registry_columns
                                                             if c != "responsible_branch_id"))

    repo = NoBranchColumn()
    dash = await _get(f"{API}/dashboard/fleet-status", repo, params={"branch_id": "BR-LAEM-CHABANG"})
    listed = await _get(f"{API}/vehicles", repo, params={"branch_id": "BR-LAEM-CHABANG"})
    assert dash.status_code == listed.status_code == 409
    assert dash.json()["error"]["code"] == listed.json()["error"]["code"] == "VEHICLE_BRANCH_FILTER_UNAVAILABLE"
    # without the filter the dashboard still answers from its own read
    assert (await _get(f"{API}/dashboard/fleet-status", repo)).status_code == 200


async def test_one_invalid_vehicle_row_fails_the_branch_summary_closed() -> None:
    class Invalid(MockRepository):
        async def read_vehicle_master_with_registry(self):
            read = await super().read_vehicle_master_with_registry()
            from dataclasses import replace

            return replace(read, issue_counts={"BLANK_STATUS": 1})

    response = await _get(f"{API}/dashboard/fleet-status", Invalid(), params={"branch_id": "BR-LAEM-CHABANG"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "VEHICLE_MASTER_DATA_INVALID"
    assert "status_counts" not in response.json()
