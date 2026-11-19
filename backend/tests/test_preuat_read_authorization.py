"""R8 PRE-UAT — every new GET refuses an untrusted reader (403) BEFORE any repository read,
and every new write refuses a caller without the per-employee TEST grant."""
from __future__ import annotations

import pytest

from app.repositories.mock.repository import MockRepository
from tests import test_access_management as am

API = am.API
READS = [
    "/master-records/vehicles", "/master-records/branches/BR-RAYONG/history",
    "/repairs/REP-0001/store-reconciliation", "/store-material-events",
    "/repair-classification/catalogue", "/repairs/REP-0001/classification",
]
WRITES = [
    ("POST", "/master-records/branches"), ("PATCH", "/master-records/branches/BR-RAYONG"),
    ("POST", "/repairs/REP-0001/store-lines/L1/approvals"), ("POST", "/repairs/REP-0001/store-lines/L1/denials"),
    ("POST", "/repairs/REP-0001/store-lines/L1/issues"), ("POST", "/repairs/REP-0001/store-lines/L1/return-acceptances"),
    ("POST", "/repairs/REP-0001/classification-drafts"), ("POST", "/repairs/REP-0001/classification-finalizations"),
]


class NoReadRepo(MockRepository):
    """Any repository read is a test failure: guards must run first."""

    def __getattribute__(self, name):
        if name.startswith(("read_", "list_", "get_")) and not name.startswith("get_effective_capab"):
            raise AssertionError(f"repository read {name} before the authorization guard")
        return super().__getattribute__(name)


@pytest.fixture(autouse=True)
def legacy_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "false"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("path", READS)
async def test_reads_need_a_trusted_can_view_reader_before_any_read(path) -> None:
    response = await am.http("GET", f"{API}{path}", NoReadRepo(), None, role="UNKNOWN", request_id=None)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("method,path", WRITES)
async def test_writes_need_the_test_grant_before_any_read(method, path) -> None:
    # The legacy ADMIN development role holds every legacy capability but no PRE-UAT TEST grant.
    response = await am.http(method, f"{API}{path}", NoReadRepo(), "USR-ADMIN", role="ADMIN", json={})
    assert am.code(response) == (403, "PREUAT_ACTION_NOT_AUTHORIZED"), response.text


async def test_member_routes_need_a_verified_employee_before_any_read() -> None:
    for path in ("store-requests", "store-lines/L1/use-confirmations", "store-lines/L1/return-declarations"):
        response = await am.http("POST", f"{API}/repairs/REP-0001/{path}", NoReadRepo(), "USR-ADMIN", role="ADMIN",
                                 json={})
        assert am.code(response) == (403, "ACCESS_ACTOR_NOT_VERIFIED"), (path, response.text)
