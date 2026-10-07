"""R2 Batch R2c-2 — read-only department master (mock repository, domain, API).

Test ids R2C2-01..R2C2-28 are batch-local PROPOSED identifiers, not owner
business codes. Every fixture is SYNTHETIC: invented ids (the DEPT-TEST- form
is TEST-ONLY and is NOT a production department id convention — the
production format is owner business data) and invented, labelled names. No
live workbook label or row is used. The Google Sheets fake-transport
counterpart is test_department_read_sheets_batch_r2c2.py.
"""
from __future__ import annotations

import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import authz
from app.domain.department import (
    DEPARTMENT_MASTER_COLUMNS,
    department_record,
    operational_rows,
    row_issues,
    table_issues,
)
from app.repositories.base import RepositorySchemaError, RepositoryTabReadError
from app.repositories.mock import MockRepository

API = "/api/v1"
TAB = "department_master"
SYN = " (สังเคราะห์)"  # synthetic-data label on every name

PUBLIC_FIELDS = {"department_id", "department_name_th", "is_active"}


def dept(did: str, name: str = "แผนก" + SYN, active: str = "TRUE", **extra: str) -> dict[str, str]:
    """A synthetic row with all 5 frozen columns. is_test_data "FALSE" means
    "synthetic fixture simulating an operational-scope row", NOT a real
    department. test_batch_id carries a marker so tests can prove it never
    leaks."""
    row = {"department_id": did, "department_name_th": name, "is_active": active, "is_test_data": "FALSE",
           "test_batch_id": "SYN-BATCH-LEAK"}
    row.update(extra)
    return row


def synthetic_test_row(did: str, **extra: str) -> dict[str, str]:
    """A synthetic explicitly-TEST row (excluded from the operational API)."""
    return dept(did, "แถวทดสอบ" + SYN, is_test_data="TRUE", test_batch_id="SYN-TEST-BATCH", **extra)


DEPTS = [
    dept("DEPT-TEST-002", "แผนกสอง" + SYN, "FALSE"),
    dept("DEPT-TEST-001", "แผนกหนึ่ง" + SYN),
    dept("DEPT-TEST-003", "แผนกสาม" + SYN),
]


class Spy(MockRepository):
    """MockRepository with replaceable department rows, injected failures and
    a log of every public repository coroutine called from outside."""

    def __init__(self, rows=None, *, fail=None) -> None:
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "_depth", [0])
        super().__init__()
        if rows is not None:
            self._department_master = rows
        self.fail = fail or {}

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if not name.startswith("_") and inspect.iscoroutinefunction(attr):
            calls = object.__getattribute__(self, "calls")
            fail = object.__getattribute__(self, "fail")
            depth = object.__getattribute__(self, "_depth")

            async def wrapper(*args, **kwargs):
                if depth[0] == 0:
                    calls.append(name)
                if name in fail:
                    raise fail[name]
                depth[0] += 1
                try:
                    return await attr(*args, **kwargs)
                finally:
                    depth[0] -= 1

            return wrapper
        return attr


async def get(path: str, repo, *, role: str | None = None, params=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, params=params, headers={"X-Dev-Role": role} if role else None)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def error(response) -> dict:
    return response.json()["error"]


def _no_row_values(response) -> None:
    """Error responses carry issue counts only: no ids, names or batch ids."""
    for marker in ("DEPT-TEST", SYN, "LEAK", "SYN-TEST-BATCH"):
        assert marker not in response.text, marker


READ = ["read_department_master_validated"]


# ---------------------------------------------------------------------------
# R2C2-01 / 02 / 03 — list, detail, not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c2_01_valid_operational_list() -> None:
    repo = Spy(DEPTS)
    response = await get(f"{API}/departments", repo)
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 3 and body["page"] == 1 and body["page_size"] == 20
    assert [d["department_id"] for d in body["items"]] == ["DEPT-TEST-001", "DEPT-TEST-002", "DEPT-TEST-003"]
    assert body["items"][0] == {"department_id": "DEPT-TEST-001", "department_name_th": "แผนกหนึ่ง" + SYN,
                                "is_active": True}
    assert repo.calls == READ


@pytest.mark.asyncio
async def test_r2c2_01_list_paging_and_bounds() -> None:
    body = (await get(f"{API}/departments", Spy(DEPTS), params={"page": 2, "page_size": 2})).json()
    assert body["total_items"] == 3 and [d["department_id"] for d in body["items"]] == ["DEPT-TEST-003"]
    for params in ({"page": 0}, {"page_size": 0}, {"page_size": 201}):
        repo = Spy(DEPTS)
        assert (await get(f"{API}/departments", repo, params=params)).status_code == 422
        assert repo.calls == []
    assert (await get(f"{API}/departments", Spy(DEPTS), params={"page_size": 200})).status_code == 200


@pytest.mark.asyncio
async def test_r2c2_01_sort_is_exact_source_text_order() -> None:
    ids = ["b", "B", "10", "9", "a", "ก"]
    body = (await get(f"{API}/departments", Spy([dept(i) for i in ids]))).json()
    assert [d["department_id"] for d in body["items"]] == sorted(ids)


@pytest.mark.asyncio
async def test_r2c2_01_seeded_mock_is_synthetic_and_served() -> None:
    body = (await get(f"{API}/departments", MockRepository())).json()
    assert [(d["department_id"], d["is_active"]) for d in body["items"]] == [
        ("DEPT-TEST-001", True), ("DEPT-TEST-002", False)]
    assert body["total_items"] == 2  # the synthetic TRUE seed row (DEPT-TEST-901) is excluded


@pytest.mark.asyncio
async def test_r2c2_02_exact_operational_detail() -> None:
    repo = Spy(DEPTS)
    response = await get(f"{API}/departments/DEPT-TEST-002", repo)
    assert response.status_code == 200
    assert response.json() == {"department_id": "DEPT-TEST-002", "department_name_th": "แผนกสอง" + SYN,
                               "is_active": False}
    assert repo.calls == READ


@pytest.mark.asyncio
@pytest.mark.parametrize("did", ["DEPT-TEST-999", "dept-test-001", " DEPT-TEST-001", "DEPT-TEST-001 ",
                                 "DEPT-TEST-01", "1", " "])
async def test_r2c2_03_unknown_or_non_exact_id_is_404(did) -> None:
    rows = [*DEPTS, dept("0001"), dept("001")]
    response = await get(f"{API}/departments/{did}", Spy(rows))
    assert response.status_code == 404 and error(response)["code"] == "DEPARTMENT_NOT_FOUND"
    assert error(response)["details"] is None


@pytest.mark.asyncio
async def test_r2c2_03_numeric_looking_ids_match_exactly() -> None:
    rows = [dept("0001"), dept("001"), dept("1")]
    for did in ("0001", "001", "1"):
        assert (await get(f"{API}/departments/{did}", Spy(rows))).json()["department_id"] == did


# ---------------------------------------------------------------------------
# R2C2-04 / 05 / 06 — duplicate id, blank id, blank name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c2_04_duplicate_id_fails_the_list_and_is_ambiguous_in_detail() -> None:
    rows = [*DEPTS, dept("DEPT-TEST-001", "ซ้ำ" + SYN)]
    listed = await get(f"{API}/departments", Spy(rows))
    assert listed.status_code == 500 and error(listed)["code"] == "DEPARTMENT_MASTER_DATA_INVALID"
    assert error(listed)["details"] == {"tab": TAB, "issues": {"DUPLICATE_DEPARTMENT_ID": 2}}
    detail = await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))
    assert detail.status_code == 409 and error(detail)["code"] == "DEPARTMENT_ID_AMBIGUOUS"
    assert error(detail)["details"] == {"match_count": 2}
    assert (await get(f"{API}/departments/DEPT-TEST-002", Spy(rows))).status_code == 200  # unaffected id
    for response in (listed, detail):
        _no_row_values(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", " ", "\t"])
async def test_r2c2_05_blank_operational_id_fails_the_list(blank) -> None:
    rows = [*DEPTS, dept(blank, "ไม่มีรหัส" + SYN)]
    response = await get(f"{API}/departments", Spy(rows))
    assert response.status_code == 500 and error(response)["code"] == "DEPARTMENT_MASTER_DATA_INVALID"
    assert error(response)["details"] == {"tab": TAB, "issues": {"BLANK_DEPARTMENT_ID": 1}}
    _no_row_values(response)
    # Detail is target-focused: an unrelated blank-id row does not block a valid exact id.
    assert (await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", " ", "\t "])
async def test_r2c2_06_blank_operational_name_is_data_invalid(blank) -> None:
    rows = [*DEPTS, dept("DEPT-TEST-004", blank)]
    listed = await get(f"{API}/departments", Spy(rows))
    assert listed.status_code == 500 and error(listed)["code"] == "DEPARTMENT_MASTER_DATA_INVALID"
    assert error(listed)["details"] == {"tab": TAB, "issues": {"BLANK_DEPARTMENT_NAME": 1}}
    detail = await get(f"{API}/departments/DEPT-TEST-004", Spy(rows))
    assert detail.status_code == 500 and error(detail)["details"] == {
        "tab": TAB, "issues": {"BLANK_DEPARTMENT_NAME": 1}}
    for response in (listed, detail):
        _no_row_values(response)
    # Target-focused detail: the unrelated malformed row does not block a valid department.
    assert (await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))).status_code == 200


@pytest.mark.asyncio
async def test_r2c2_06_names_are_exact_text_not_unique_not_substituted() -> None:
    odd = ["  นำหน้าเว้นวรรค" + SYN, "ท้ายเว้นวรรค" + SYN + "  ", "0012", "=1+1", "x" * 200]
    rows = [dept(f"DEPT-TEST-{i:03d}", v) for i, v in enumerate(odd)]
    items = (await get(f"{API}/departments", Spy(rows), params={"page_size": 50})).json()["items"]
    assert [d["department_name_th"] for d in items] == odd
    same = [dept("DEPT-TEST-001", "ชื่อเดียวกัน" + SYN), dept("DEPT-TEST-002", "ชื่อเดียวกัน" + SYN)]
    body = (await get(f"{API}/departments", Spy(same))).json()
    assert body["total_items"] == 2  # two ids, one display name: not a duplicate identity


# ---------------------------------------------------------------------------
# R2C2-07 / 08 / 09 — is_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c2_07_08_active_true_and_false_are_both_readable() -> None:
    rows = [dept("DEPT-TEST-001", active="TRUE"), dept("DEPT-TEST-002", active="FALSE")]
    listed = (await get(f"{API}/departments", Spy(rows))).json()["items"]
    assert [(d["department_id"], d["is_active"]) for d in listed] == [("DEPT-TEST-001", True),
                                                                       ("DEPT-TEST-002", False)]
    assert (await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))).json()["is_active"] is True
    inactive = await get(f"{API}/departments/DEPT-TEST-002", Spy(rows))
    assert inactive.status_code == 200 and inactive.json()["is_active"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["", " ", "true", "false", "True", "1", "0", "YES", "NO", "ACTIVE", " TRUE",
                                  "FALSE "])
async def test_r2c2_09_blank_or_invalid_active_flag_is_data_invalid(flag) -> None:
    rows = [*DEPTS, dept("DEPT-TEST-004", active=flag)]
    for path in ("departments", "departments/DEPT-TEST-004"):
        response = await get(f"{API}/{path}", Spy(rows))
        assert response.status_code == 500 and error(response)["code"] == "DEPARTMENT_MASTER_DATA_INVALID"
        assert error(response)["details"] == {"tab": TAB, "issues": {"ACTIVE_FLAG_INVALID": 1}}
        _no_row_values(response)
    assert (await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))).status_code == 200


# ---------------------------------------------------------------------------
# R2C2-10..R2C2-15 — TEST / REAL boundary and phantom rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c2_10_only_false_rows_returned_and_counted_after_exclusion() -> None:
    rows = [*DEPTS, synthetic_test_row("DEPT-TEST-901"), synthetic_test_row("DEPT-TEST-902")]
    body = (await get(f"{API}/departments", Spy(rows), params={"page_size": 2})).json()
    assert body["total_items"] == 3
    assert [d["department_id"] for d in body["items"]] == ["DEPT-TEST-001", "DEPT-TEST-002"]
    page2 = (await get(f"{API}/departments", Spy(rows), params={"page": 2, "page_size": 2})).json()
    assert [d["department_id"] for d in page2["items"]] == ["DEPT-TEST-003"]


@pytest.mark.asyncio
async def test_r2c2_11_test_only_id_is_404() -> None:
    response = await get(f"{API}/departments/DEPT-TEST-901", Spy([*DEPTS, synthetic_test_row("DEPT-TEST-901")]))
    assert response.status_code == 404 and error(response)["code"] == "DEPARTMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_r2c2_12_test_row_sharing_an_operational_id_causes_no_ambiguity() -> None:
    rows = [*DEPTS, synthetic_test_row("DEPT-TEST-001")]
    detail = await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))
    assert detail.status_code == 200 and detail.json()["department_name_th"] == "แผนกหนึ่ง" + SYN
    listed = await get(f"{API}/departments", Spy(rows))
    assert listed.status_code == 200 and listed.json()["total_items"] == 3


@pytest.mark.asyncio
async def test_r2c2_12_two_operational_rows_keep_duplicate_behaviour_beside_a_test_row() -> None:
    rows = [*DEPTS, dept("DEPT-TEST-001", "ซ้ำ" + SYN), synthetic_test_row("DEPT-TEST-001")]
    listed = await get(f"{API}/departments", Spy(rows))
    assert error(listed)["details"] == {"tab": TAB, "issues": {"DUPLICATE_DEPARTMENT_ID": 2}}
    detail = await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))
    assert detail.status_code == 409 and error(detail)["details"] == {"match_count": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"department_id": ""},
    {"department_id": " "},
    {"department_name_th": ""},
    {"is_active": ""},
    {"is_active": "maybe"},
])
async def test_r2c2_13_malformed_test_rows_do_not_invalidate_the_operational_scope(bad) -> None:
    rows = [*DEPTS, synthetic_test_row("DEPT-TEST-901", **bad), synthetic_test_row("DEPT-TEST-001"),
            synthetic_test_row("DEPT-TEST-001")]
    listed = await get(f"{API}/departments", Spy(rows))
    assert listed.status_code == 200 and listed.json()["total_items"] == 3
    assert (await get(f"{API}/departments/DEPT-TEST-002", Spy(rows))).status_code == 200
    assert (await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["", " ", "\t", "true", "false", "True", "YES", "NO", "0", "1", " FALSE", "TRUE "])
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001", "departments/DEPT-TEST-404"])
async def test_r2c2_14_blank_or_invalid_test_flag_fails_closed_on_list_and_detail(flag, path) -> None:
    rows = [*DEPTS, dept("DEPT-TEST-004", is_test_data=flag)]
    response = await get(f"{API}/{path}", Spy(rows))
    assert response.status_code == 500 and error(response)["code"] == "DEPARTMENT_MASTER_DATA_INVALID"
    assert error(response)["details"] == {"tab": TAB, "issues": {"TEST_FLAG_INVALID": 1}}
    _no_row_values(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [{"department_id": "DEPT-TEST-004"}, {"department_name_th": "ชื่อ" + SYN},
                                     {"is_active": "TRUE"}])
async def test_r2c2_14_any_business_content_forces_strict_classification(content) -> None:
    empty = dict.fromkeys(DEPARTMENT_MASTER_COLUMNS, "")
    response = await get(f"{API}/departments", Spy([*DEPTS, {**empty, **content}]))  # flag blank
    assert error(response)["details"] == {"tab": TAB, "issues": {"TEST_FLAG_INVALID": 1}}


@pytest.mark.asyncio
async def test_r2c2_15_checkbox_only_phantom_rows_are_skipped_whatever_the_flag() -> None:
    """A row whose three business columns are all blank is not a department
    record (e.g. a checkbox left FALSE in an otherwise empty row)."""
    empty = dict.fromkeys(DEPARTMENT_MASTER_COLUMNS, "")
    rows = [*DEPTS, {**empty, "is_test_data": "FALSE"}, {**empty, "is_test_data": "TRUE"},
            {**empty, "is_test_data": "junk", "test_batch_id": "SYN-ONLY"}, dict(empty)]
    listed = await get(f"{API}/departments", Spy(rows))
    assert listed.status_code == 200 and listed.json()["total_items"] == 3
    assert (await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))).status_code == 200


def test_r2c2_10_15_classification_happens_before_any_row_validation() -> None:
    rows = [dept("A"), synthetic_test_row("A"), synthetic_test_row("", is_active="x", department_name_th=""),
            dept("B", is_test_data="maybe")]
    kept, issues = operational_rows(rows)
    assert [r["department_id"] for r in kept] == ["A"]
    assert issues == {"TEST_FLAG_INVALID": 1}
    assert table_issues(kept) == {}  # the test rows never reach id/name/active validation


def test_r2c2_04_09_issue_counting() -> None:
    rows = [dept("A"), dept("A"), dept("A"), dept(""), dept("B", " ", "no")]
    assert table_issues(rows) == {"DUPLICATE_DEPARTMENT_ID": 3, "BLANK_DEPARTMENT_ID": 1,
                                  "BLANK_DEPARTMENT_NAME": 1, "ACTIVE_FLAG_INVALID": 1}
    assert table_issues([dept("A"), dept("a"), dept(" A")]) == {}  # exact text, no folding or trim
    assert row_issues(dept("A")) == {}
    record = department_record(dept("A", "  ชื่อ ", "FALSE"))
    assert (record.department_id, record.department_name_th, record.is_active) == ("A", "  ชื่อ ", False)


# ---------------------------------------------------------------------------
# R2C2-16 / 17 / 18 — schema and read failures are coded, never empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (RepositoryTabReadError(TAB, "down"), 503, "DEPARTMENT_MASTER_READ_FAILED"),
        (RepositorySchemaError(TAB, "TAB_MISSING"), 500, "DEPARTMENT_MASTER_SCHEMA_INVALID"),
        (RepositorySchemaError(TAB, "MISSING_HEADERS", ("is_active",)), 500, "DEPARTMENT_MASTER_SCHEMA_INVALID"),
    ],
)
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001"])
async def test_r2c2_16_18_failures_are_coded_never_empty_or_404(failure, status, code, path) -> None:
    response = await get(f"{API}/{path}", Spy(DEPTS, fail={"read_department_master_validated": failure}))
    assert response.status_code == status and error(response)["code"] == code
    assert "items" not in response.text and "department_id" not in response.text
    assert error(response)["details"]["tab"] == TAB


# ---------------------------------------------------------------------------
# R2C2-19..R2C2-23 — permission, public shape, no joins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001"])
async def test_r2c2_19_can_view_required_with_zero_reads(path) -> None:
    repo = Spy(DEPTS)
    response = await get(f"{API}/{path}", repo, role="NO_SUCH_ROLE")  # holds no capability (fails closed)
    assert response.status_code == 403 and error(response)["code"] == "HTTP_ERROR"
    assert repo.calls == []
    for role in ("ADMIN", "TECHNICIAN"):  # explicit callers holding can_view
        assert authz.CAN_VIEW in authz.capabilities_for_roles((role,))
        allowed = Spy(DEPTS)
        assert (await get(f"{API}/{path}", allowed, role=role)).status_code == 200
        assert allowed.calls == READ


@pytest.mark.asyncio
async def test_r2c2_20_public_response_is_exactly_three_fields() -> None:
    rows = [*DEPTS, synthetic_test_row("DEPT-TEST-901")]
    listed = await get(f"{API}/departments", Spy(rows))
    detail = await get(f"{API}/departments/DEPT-TEST-001", Spy(rows))
    for item in [*listed.json()["items"], detail.json()]:
        assert set(item) == PUBLIC_FIELDS
    for response in (listed, detail):
        for hidden in ('"is_test_data"', '"test_batch_id"', "LEAK", "SYN-TEST-BATCH"):
            assert hidden not in response.text


def test_r2c2_20_openapi_schema_has_only_public_fields() -> None:
    from app.main import create_app

    schema = create_app().openapi()["components"]["schemas"]["DepartmentResponse"]
    assert set(schema["properties"]) == PUBLIC_FIELDS
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001", "departments/DEPT-TEST-404"])
async def test_r2c2_21_23_only_the_department_read_happens(path) -> None:
    """No personnel_master, branch_master, user_account, role_permission,
    technician, driver, assignment or workshop read: the only repository call
    is the department read."""
    repo = Spy(DEPTS)
    await get(f"{API}/{path}", repo)
    assert repo.calls == READ


# ---------------------------------------------------------------------------
# R2C2-26..R2C2-28 — regression and guardrails (permanent rules only)
# ---------------------------------------------------------------------------


def _routes() -> set[tuple[str, str]]:
    from app.main import create_app

    spec = create_app().openapi()
    return {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}


@pytest.mark.asyncio
async def test_r2c2_26_personnel_contract_unchanged() -> None:
    from app.domain.personnel import PERSONNEL_MASTER_COLUMNS, PERSONNEL_READ_COLUMNS
    from app.main import create_app
    from app.repositories.google_sheets import schemas as sheet_schemas

    assert "department" in PERSONNEL_MASTER_COLUMNS and "department_id" not in PERSONNEL_MASTER_COLUMNS
    assert PERSONNEL_READ_COLUMNS == ("personnel_id", "first_name", "last_name", "active_status", "is_test_data")
    assert sheet_schemas.PERSONNEL_MASTER_READ_SHEET.required_headers == PERSONNEL_READ_COLUMNS
    schema = create_app().openapi()["components"]["schemas"]["PersonnelResponse"]
    assert set(schema["properties"]) == {"personnel_id", "first_name", "last_name", "active_status"}
    body = (await get(f"{API}/personnel", MockRepository())).json()
    assert body["total_items"] == 3 and "department" not in str(body)


def test_r2c2_27_r2a_branch_model_part_support_remains_present() -> None:
    """Existing R2a support stays available. Forward-compatible: a later
    approved relationship batch may add e.g. a DEPARTMENT kind and
    resolve_departments without breaking this test."""
    from app.domain import master_reference

    kinds = {v for k, v in vars(master_reference).items() if k.startswith("MASTER_KIND_")}
    assert {"BRANCH", "MODEL", "PART"} <= kinds
    resolvers = {n for n in dir(master_reference.MasterReferenceResolver) if n.startswith("resolve_")}
    assert {"resolve_branches", "resolve_models", "resolve_parts"} <= resolvers


def test_r2c2_27_schema_declarations() -> None:
    from app.repositories.google_sheets import schemas as sheet_schemas

    assert sheet_schemas.DEPARTMENT_MASTER_SHEET.tab_name == TAB
    assert sheet_schemas.DEPARTMENT_MASTER_SHEET.required_headers == (
        "department_id", "department_name_th", "is_active", "is_test_data", "test_batch_id")
    assert sheet_schemas.DEPARTMENT_MASTER_READ_SHEET.required_headers == (
        "department_id", "department_name_th", "is_active", "is_test_data")
    # No branch, workshop or personnel relationship field in the department master.
    for column in sheet_schemas.DEPARTMENT_MASTER_SHEET.required_headers:
        assert not any(word in column for word in ("branch", "workshop", "personnel", "parent"))


def test_r2c2_28_routes_exist_without_freezing_the_future_department_surface() -> None:
    routes = _routes()
    assert ("GET", "/api/v1/departments") in routes
    assert ("GET", "/api/v1/departments/{department_id}") in routes
    # Referenced masters are deactivated, never hard-deleted (approved R2 principle).
    # Lifecycle writes (R2e) and new capabilities may be added later without
    # breaking this test.
    assert ("DELETE", "/api/v1/departments/{department_id}") not in routes
    for capability in ("can_edit_vehicle_registration", "can_transfer_vehicle_branch", "can_correct_branch_history"):
        holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if capability in caps}
        assert holders == {"ADMIN", "MAINTENANCE_MANAGER"}, capability
