"""Phase 7 Batch 7O2a — registry READ API over HTTP (contract Final Rev2 §4.5,
§7.1-§7.4, §8.1), mock repository.

This file deliberately imports only modules that already existed before
7O2a (app.main, app.config, app.dependencies, app.repositories.*), so the
same file runs against the baseline and fails there on BEHAVIOUR (missing
routes, missing fields, an ignored filter, an ignored setting) rather than
on an import error. Repository failures are injected by overriding methods
and data attributes of a MockRepository subclass.

Acceptance rows: R-01 (mock part), R-03, R-04, R-06, R-07, R-08, R-12
(mock side); can_view refusal with zero repository access; no mutation
routes. Synthetic data only (the mock seed's registry fixtures).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import DataRepositoryMode, Settings
from app.repositories.base import RepositorySchemaError, RepositoryTabReadError
from app.repositories.mock import MockRepository

API = "/api/v1"
REGISTRY_KEYS = {"registration_no", "registration_province", "responsible_branch"}
VEHICLE_KEYS = {"vehicle_id", "machine_no", "model_id", "serial_number", "operational_status", "created_at", "updated_at"}


class SpyRepository(MockRepository):
    """Records every invocation of a public repository method."""

    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "calls", [])

    def __getattribute__(self, name: str):
        value = object.__getattribute__(self, name)
        if name.startswith("_") or name == "calls" or not callable(value):
            return value
        calls = object.__getattribute__(self, "calls")

        def recorded(*args, **kwargs):
            calls.append(name)
            return value(*args, **kwargs)

        return recorded


async def _http(path: str, *, repo=None, settings: Settings | None = None, headers=None, method: str = "GET", params=None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers or {}, params=params)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _error(response) -> dict:
    return response.json()["error"]


def _sheets_settings(context: str | None) -> Settings:
    values = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake", "google_application_credentials": "fake.json"}
    if context is not None:
        values["registry_data_context"] = context
    return Settings(**values)


# ---------------------------------------------------------------------------
# §7.1 — registry fields on list and detail (additive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_carry_registry_with_exact_text_and_states() -> None:
    body = (await _http(f"{API}/vehicles")).json()
    by_id = {item["vehicle_id"]: item for item in body["items"]}
    assert set(by_id["VEH-1046"]) == VEHICLE_KEYS | {"registry"}
    assert set(by_id["VEH-1046"]["registry"]) == REGISTRY_KEYS
    assert by_id["VEH-1046"]["registry"]["registration_no"] == {"state": "RECORDED", "value": "0012"}
    assert by_id["VEH-1047"]["registry"]["registration_no"] == {"state": "RECORDED", "value": "กข-1234"}
    assert by_id["VEH-1047"]["registry"]["registration_province"] == {"state": "RECORDED", "value": "TH-99"}
    assert by_id["VEH-1048"]["registry"] == dict.fromkeys(REGISTRY_KEYS, {"state": "NOT_RECORDED", "value": None})
    assert body["total_items"] == 3


@pytest.mark.asyncio
async def test_detail_vehicle_carries_registry_and_patch_shape_is_unchanged() -> None:
    detail = (await _http(f"{API}/vehicles/VEH-1046")).json()
    assert detail["vehicle"]["registry"]["responsible_branch"] == {"state": "RECORDED", "value": "BR-LAEM-CHABANG"}
    assert set(detail) == {"vehicle", "model", "components"}
    patched = await _http(f"{API}/vehicles/VEH-1046", method="PATCH", repo=MockRepository())
    assert patched.status_code == 422  # no body: the existing route is unchanged


@pytest.mark.asyncio
async def test_dashboard_totals_equal_list_totals_with_registry() -> None:
    dashboard = (await _http(f"{API}/dashboard/fleet-status")).json()
    listed = (await _http(f"{API}/vehicles", params={"page_size": 1})).json()
    assert dashboard["vehicle_total"] == listed["total_items"] == 3
    assert set(dashboard) == {"population", "vehicle_total", "status_counts"}


# ---------------------------------------------------------------------------
# §7.2 — reference lists (R-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_and_province_lists() -> None:
    branches = await _http(f"{API}/branches")
    assert branches.status_code == 200
    assert branches.json() == {"items": [
        {"branch_id": "BR-BANGNA-KM6", "branch_name": "บางนา กม.6", "is_active": True},
        {"branch_id": "BR-LAEM-CHABANG", "branch_name": "แหลมฉบัง", "is_active": True},
        {"branch_id": "BR-RAYONG", "branch_name": "ระยอง", "is_active": True},
    ]}
    provinces = (await _http(f"{API}/provinces")).json()["items"]
    assert [p["province_code"] for p in provinces] == ["TH-10", "TH-20", "TH-21", "TH-76"]
    assert provinces[-1] == {"province_code": "TH-76", "province_name_th": "เพชรบุรี", "is_active": False}
    # TH-99 (VEH-1047) is absent: the UI's UNKNOWN_CODE case, decided client-side.
    assert "TH-99" not in {p["province_code"] for p in provinces}


class _BrokenReference(MockRepository):
    def __init__(self, failure) -> None:
        super().__init__()
        self.failure = failure

    async def read_branch_master_validated(self):
        raise self.failure

    async def read_province_master_validated(self):
        raise self.failure


@pytest.mark.asyncio
async def test_reference_outage_and_schema_errors_are_coded_never_empty() -> None:
    down = await _http(f"{API}/branches", repo=_BrokenReference(RepositoryTabReadError("branch_master", "down")))
    assert down.status_code == 503
    assert _error(down)["code"] == "BRANCH_MASTER_READ_FAILED" and "items" not in down.text
    broken = await _http(f"{API}/provinces", repo=_BrokenReference(
        RepositorySchemaError("province_master", "MISSING_HEADERS", ["province_code"])))
    assert broken.status_code == 500
    assert _error(broken)["code"] == "PROVINCE_MASTER_SCHEMA_INVALID"
    assert _error(broken)["details"]["problem"] == "MISSING_HEADERS"


class _BadReferenceRows(MockRepository):
    def __init__(self) -> None:
        super().__init__()
        self._province_master = [
            {"province_code": "TH-10", "province_name_th": "ก", "is_active": "TRUE"},
            {"province_code": "TH-10", "province_name_th": "ข", "is_active": "yes"},
        ]


@pytest.mark.asyncio
async def test_reference_data_invalid_is_500_with_counts_only() -> None:
    response = await _http(f"{API}/provinces", repo=_BadReferenceRows())
    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "PROVINCE_MASTER_DATA_INVALID"
    assert error["details"] == {"tab": "province_master", "issues": {"DUPLICATE_CODE": 2, "INVALID_ACTIVE_FLAG": 1}}


# ---------------------------------------------------------------------------
# §7.3 — branch filter (R-04)
# ---------------------------------------------------------------------------


async def _ids(**params) -> tuple[int, list[str], int]:
    response = await _http(f"{API}/vehicles", params=params)
    if response.status_code != 200:
        return response.status_code, [], -1
    body = response.json()
    return 200, [i["vehicle_id"] for i in body["items"]], body["total_items"]


@pytest.mark.asyncio
async def test_branch_filter_exact_and_variants() -> None:
    assert await _ids(branch_id="BR-LAEM-CHABANG") == (200, ["VEH-1046"], 1)
    assert await _ids(branch_id="BR-BANGNA-KM6") == (200, ["VEH-1047"], 1)
    for variant in ("br-laem-chabang", " BR-LAEM-CHABANG", "BR-LAEM-CHABANG ", "BR-LAEM", "BR-UNKNOWN"):
        assert await _ids(branch_id=variant) == (200, [], 0), variant
    assert (await _ids(branch_id=""))[0] == 422
    assert (await _ids(branch_id="B" * 101))[0] == 422
    assert (await _ids(branch_id="B" * 100))[0] == 200


@pytest.mark.asyncio
async def test_branch_filter_ands_with_status_model_q_and_pages() -> None:
    assert await _ids(branch_id="BR-LAEM-CHABANG", status="WORKING") == (200, ["VEH-1046"], 1)
    assert await _ids(branch_id="BR-LAEM-CHABANG", status="READY") == (200, [], 0)
    assert await _ids(branch_id="BR-LAEM-CHABANG", model_id="MODEL-0001") == (200, ["VEH-1046"], 1)
    assert await _ids(branch_id="BR-LAEM-CHABANG", model_id="MODEL-0002") == (200, [], 0)
    assert await _ids(branch_id="BR-LAEM-CHABANG", q="TC-12") == (200, ["VEH-1046"], 1)
    assert await _ids(branch_id="BR-LAEM-CHABANG", q="TC-13") == (200, [], 0)
    assert await _ids(branch_id="BR-LAEM-CHABANG", page=2) == (200, [], 1)  # out of range: empty page, true total
    assert await _ids(branch_id="BR-LAEM-CHABANG", page_size=1, page=1) == (200, ["VEH-1046"], 1)


@pytest.mark.asyncio
async def test_branch_filter_reads_no_reference_tab() -> None:
    spy = SpyRepository()
    response = await _http(f"{API}/vehicles", repo=spy, params={"branch_id": "BR-UNKNOWN"})
    assert response.status_code == 200 and response.json()["total_items"] == 0
    assert spy.calls  # the spy sees the vehicle read...
    assert not any("branch_master" in c or "province" in c for c in spy.calls)  # ...and no reference read


# ---------------------------------------------------------------------------
# §7.4 — branch history envelope (R-06)
# ---------------------------------------------------------------------------

BRANCH_HISTORY_KEYS = {"asset_type", "asset_id", "timeline_status", "current", "master", "consistency",
                       "history_revision", "baseline", "events", "records", "excluded_test_rows", "issues"}
EVENT_KEYS = {"event_id", "in_force", "head_record_id", "revision_no", "to_branch_id", "effective_at",
              "effective_precision", "derived_from_branch_id", "original_entry_from_branch_id",
              "original_entry_from_source", "head_entry_from_branch_id", "head_entry_from_source", "derived_end_at", "notes"}
RECORD_KEYS = {"record_id", "record_kind", "entry_operation", "event_id", "revision_no", "supersedes_record_id", "branch_id",
               "effective_at", "recorded_from_branch_id", "recorded_from_source", "recorded_at", "recorded_by", "request_id",
               "related_request_id", "reason_th", "reconciled_old_master_branch_id"}


@pytest.mark.asyncio
async def test_branch_history_insertion_correction_envelope() -> None:
    response = await _http(f"{API}/vehicles/VEH-1046/branch-history")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == BRANCH_HISTORY_KEYS
    assert (body["asset_type"], body["asset_id"], body["timeline_status"]) == ("VEHICLE", "VEH-1046", "VALID")
    assert body["current"] == {"branch_id": "BR-LAEM-CHABANG", "source": "EVENT"}
    assert body["master"] == {"state": "RECORDED", "value": "BR-LAEM-CHABANG"}
    assert body["consistency"] == "CONSISTENT"
    assert body["baseline"] == {"branch_id": "BR-RAYONG", "source": "IMPORTED_MASTER"}
    assert body["history_revision"].startswith("BHR1-")
    assert (body["excluded_test_rows"], body["issues"]) == (0, {})
    events = body["events"]
    assert all(set(e) == EVENT_KEYS for e in events)
    assert [(e["to_branch_id"], e["revision_no"], e["derived_from_branch_id"], e["notes"]) for e in events] == [
        ("BR-BANGNA-KM6", 2, "BR-RAYONG", []),
        ("BR-LAEM-CHABANG", 1, "BR-BANGNA-KM6", ["RECORDED_SOURCE_DIFFERS"]),
    ]
    records = body["records"]
    assert all(set(r) == RECORD_KEYS for r in records)
    assert [(r["record_kind"], r["entry_operation"], r["revision_no"]) for r in records] == [
        ("ASSIGNMENT", "TRANSFER", 1), ("ASSIGNMENT", "INSERTION", 1), ("CORRECTION", "CORRECTION", 2)]
    assert all(r["request_id"].startswith("mock-seed-7o2a-") for r in records)
    assert records[2]["supersedes_record_id"] == records[1]["record_id"]


@pytest.mark.asyncio
async def test_branch_history_cancellation_and_no_history() -> None:
    cancelled = (await _http(f"{API}/vehicles/VEH-1048/branch-history")).json()
    assert cancelled["current"] == {"branch_id": None, "source": "NONE"}
    assert cancelled["baseline"] == {"branch_id": None, "source": "NONE"}
    assert [(e["in_force"], e["notes"]) for e in cancelled["events"]] == [(False, ["CANCELLED"])]
    none = (await _http(f"{API}/vehicles/VEH-1047/branch-history")).json()
    assert none["consistency"] == "NO_HISTORY" and none["events"] == [] and none["records"] == []
    assert none["current"] == {"branch_id": "BR-BANGNA-KM6", "source": "IMPORTED_MASTER"}
    assert none["baseline"] is None


class _History(MockRepository):
    def __init__(self, branch_rows=None, registration_rows=None, branch_failure=None, registration_failure=None) -> None:
        super().__init__()
        if branch_rows is not None:
            self._asset_branch_history = branch_rows
        if registration_rows is not None:
            self._registration_history = registration_rows
        self.branch_failure = branch_failure
        self.registration_failure = registration_failure

    async def read_asset_branch_history_validated(self):
        if self.branch_failure is not None:
            raise self.branch_failure
        return await super().read_asset_branch_history_validated()

    async def read_vehicle_registration_history_validated(self):
        if self.registration_failure is not None:
            raise self.registration_failure
        return await super().read_vehicle_registration_history_validated()


def _seed_branch_rows() -> list[dict[str, str]]:
    from app.repositories.mock import seed_data

    return getattr(seed_data, "build_seed_asset_branch_history", list)()


def _seed_registration_rows() -> list[dict[str, str]]:
    from app.repositories.mock import seed_data

    return getattr(seed_data, "build_seed_registration_history", list)()


@pytest.mark.asyncio
async def test_failed_history_reads_are_errors_never_empty_lists() -> None:
    cases = [
        (_History(branch_failure=RepositoryTabReadError("asset_branch_history", "down")), "branch-history", 503, "BRANCH_HISTORY_READ_FAILED"),
        (_History(branch_failure=RepositorySchemaError("asset_branch_history", "MISSING_HEADERS", ["assignment_id"])),
         "branch-history", 500, "BRANCH_HISTORY_SCHEMA_INVALID"),
        (_History(registration_failure=RepositoryTabReadError("vehicle_registration_history", "down")),
         "registration-history", 503, "REGISTRATION_HISTORY_READ_FAILED"),
        (_History(registration_failure=RepositorySchemaError("vehicle_registration_history", "MISSING_TAB", [])),
         "registration-history", 500, "REGISTRATION_HISTORY_SCHEMA_INVALID"),
    ]
    for repo, path, status, code in cases:
        response = await _http(f"{API}/vehicles/VEH-1046/{path}", repo=repo)
        assert (response.status_code, _error(response)["code"]) == (status, code), path
        assert "items" not in response.json() and "events" not in response.json()


@pytest.mark.asyncio
async def test_branch_history_invalid_rows_are_500_with_issue_counts() -> None:
    rows = _seed_branch_rows()
    rows[2]["revision_no"] = "x"  # the correction row of VEH-1046
    response = await _http(f"{API}/vehicles/VEH-1046/branch-history", repo=_History(branch_rows=rows))
    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "BRANCH_HISTORY_DATA_INVALID"
    assert error["details"] == {"tab": "asset_branch_history", "issues": {"REVISION_INVALID": 1}}
    # Another vehicle's history is unaffected by VEH-1046's bad row (§5.2).
    other = await _http(f"{API}/vehicles/VEH-1048/branch-history", repo=_History(branch_rows=rows))
    assert other.status_code == 200


@pytest.mark.asyncio
async def test_branch_history_same_instant_is_200_ambiguous() -> None:
    rows = _seed_branch_rows()
    rows[2]["start_at"] = rows[0]["start_at"]  # corrected insertion now ties the first transfer
    body = (await _http(f"{API}/vehicles/VEH-1046/branch-history", repo=_History(branch_rows=rows))).json()
    assert body["timeline_status"] == "AMBIGUOUS_ORDER"
    assert body["current"] == {"branch_id": None, "source": "UNDETERMINED"}
    assert body["consistency"] == "UNDETERMINED"
    assert all(e["notes"] == ["SAME_INSTANT"] for e in body["events"])


@pytest.mark.asyncio
async def test_branch_history_projection_mismatch() -> None:
    rows = _seed_branch_rows()
    rows[0]["branch_id"] = "BR-RAYONG"  # history now ends at Rayong; the master says Laem Chabang
    body = (await _http(f"{API}/vehicles/VEH-1046/branch-history", repo=_History(branch_rows=rows))).json()
    assert (body["consistency"], body["current"]["branch_id"]) == ("PROJECTION_MISMATCH", "BR-RAYONG")


# ---------------------------------------------------------------------------
# §4.5 — registration history envelope (R-07)
# ---------------------------------------------------------------------------

REG_KEYS = {"vehicle_id", "current", "consistency", "history_revision", "items", "excluded_test_rows", "issues"}
REG_ITEM_KEYS = {"change_id", "change_kind", "old_registration_no", "old_registration_province_code", "new_registration_no",
                 "new_registration_province_code", "recorded_at", "recorded_by", "request_id", "related_request_id",
                 "accepted_exceptions", "note_th"}


@pytest.mark.asyncio
async def test_registration_history_envelope_and_states() -> None:
    body = (await _http(f"{API}/vehicles/VEH-1046/registration-history")).json()
    assert set(body) == REG_KEYS
    assert body["current"] == {"registration_no": {"state": "RECORDED", "value": "0012"},
                               "registration_province": {"state": "RECORDED", "value": "TH-21"}}
    assert body["consistency"] == "CONSISTENT" and body["history_revision"].startswith("RHR1-")
    assert [set(i) for i in body["items"]] == [REG_ITEM_KEYS]
    assert body["items"][0]["new_registration_no"] == "0012"  # leading zeros kept
    cleared = (await _http(f"{API}/vehicles/VEH-1048/registration-history")).json()
    assert cleared["consistency"] == "CONSISTENT"
    assert [i["new_registration_no"] for i in cleared["items"]] == ["ทดสอบ 99", None]
    none = (await _http(f"{API}/vehicles/VEH-1047/registration-history")).json()
    assert (none["consistency"], none["items"]) == ("NO_HISTORY", [])


@pytest.mark.asyncio
async def test_registration_history_mismatch_and_invalid() -> None:
    rows = _seed_registration_rows()
    rows[0]["new_registration_no"] = "12"
    mismatch = (await _http(f"{API}/vehicles/VEH-1046/registration-history", repo=_History(registration_rows=rows))).json()
    assert mismatch["consistency"] == "MISMATCH"
    rows[0]["recorded_at"] = "2026-09-05 03:00"  # naive
    invalid = await _http(f"{API}/vehicles/VEH-1046/registration-history", repo=_History(registration_rows=rows))
    assert invalid.status_code == 500
    assert _error(invalid)["details"] == {"tab": "vehicle_registration_history", "issues": {"RECORDED_AT_INVALID": 1}}


@pytest.mark.asyncio
async def test_history_vehicle_errors_follow_detail_semantics() -> None:
    assert _error(await _http(f"{API}/vehicles/VEH-9999/branch-history"))["code"] == "VEHICLE_NOT_FOUND"
    assert _error(await _http(f"{API}/vehicles/%20/registration-history"))["code"] == "VEHICLE_NOT_FOUND"
    assert _error(await _http(f"{API}/vehicles/veh-1046/branch-history"))["code"] == "VEHICLE_NOT_FOUND"  # exact id


# ---------------------------------------------------------------------------
# §8.1 — data contexts (R-08)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unset_context_in_sheets_mode_is_503_on_registry_routes_only() -> None:
    for path in ("branches", "provinces", "vehicles/VEH-1046/branch-history", "vehicles/VEH-1046/registration-history"):
        spy = SpyRepository()
        response = await _http(f"{API}/{path}", repo=spy, settings=_sheets_settings(None))
        assert response.status_code == 503, path
        assert _error(response)["code"] == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
        assert spy.calls == [], (path, spy.calls)
    # Existing routes keep working with the same unset context.
    listed = await _http(f"{API}/vehicles", repo=MockRepository(), settings=_sheets_settings(None))
    assert listed.status_code == 200
    detail = await _http(f"{API}/vehicles/VEH-1046", repo=MockRepository(), settings=_sheets_settings(None))
    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_real_context_refuses_test_rows_and_test_context_includes_them() -> None:
    real = _sheets_settings("REAL")
    for path in ("branch-history", "registration-history"):
        response = await _http(f"{API}/vehicles/VEH-1046/{path}", repo=MockRepository(), settings=real)
        assert response.status_code == 500, path
        # One issue per TRUE/blank row of this vehicle (VEH-1046: 3 branch rows, 1 registration row).
        assert _error(response)["details"]["issues"] == {"CUTOVER_INCOMPLETE": 3 if path == "branch-history" else 1}
        test = await _http(f"{API}/vehicles/VEH-1046/{path}", repo=MockRepository(), settings=_sheets_settings("TEST"))
        assert test.status_code == 200
    # A vehicle without rows has nothing to refuse in REAL.
    assert (await _http(f"{API}/vehicles/VEH-1047/branch-history", repo=MockRepository(), settings=real)).status_code == 200
    # Reference lists carry no test rows and work in REAL.
    assert (await _http(f"{API}/branches", repo=MockRepository(), settings=real)).status_code == 200


def test_mock_with_real_context_refuses_to_start() -> None:
    with pytest.raises(ValidationError):
        Settings(data_repository=DataRepositoryMode.MOCK, registry_data_context="REAL")
    Settings(data_repository=DataRepositoryMode.MOCK, registry_data_context="TEST")
    Settings(data_repository=DataRepositoryMode.MOCK)


# ---------------------------------------------------------------------------
# can_view and no mutation routes
# ---------------------------------------------------------------------------

NEW_GETS = ("branches", "provinces", "vehicles/VEH-1046/branch-history", "vehicles/VEH-1046/registration-history")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", NEW_GETS)
async def test_can_view_refusal_reads_nothing(path: str) -> None:
    spy = SpyRepository()
    response = await _http(f"{API}/{path}", repo=spy, headers={"X-Dev-Role": "UNKNOWN"})
    assert response.status_code == 403
    assert _error(response)["code"] == "HTTP_ERROR" and "can_view" in _error(response)["message"]
    assert spy.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER"])
async def test_every_can_view_role_reads(role: str) -> None:
    for path in NEW_GETS:
        assert (await _http(f"{API}/{path}", headers={"X-Dev-Role": role})).status_code == 200, (role, path)


@pytest.mark.asyncio
async def test_no_registry_mutation_route_exists() -> None:
    for path in ("vehicles/VEH-1046/registration", "vehicles/VEH-1046/branch-transfer", "vehicles/VEH-1046/branch-history",
                 "vehicles/VEH-1046/branch-history/insertions", "vehicles/VEH-1046/registration-history",
                 "vehicles/VEH-1046/registration-history/reconciliations", "branches", "provinces"):
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            response = await _http(f"{API}/{path}", method=method, repo=SpyRepository())
            assert response.status_code in (404, 405), (method, path)
    schema = (await _http("/openapi.json")).json()["paths"]
    registry_paths = {p: set(ops) for p, ops in schema.items()
                      if any(k in p for k in ("branch", "province", "registration"))}
    assert registry_paths == {
        f"{API}/branches": {"get"},
        f"{API}/provinces": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/branch-history": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/registration-history": {"get"},
    }
