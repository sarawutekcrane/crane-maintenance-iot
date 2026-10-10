"""R2 Batch R2c-1 — read-only personnel master (mock repository, domain, API).

Test ids R2C1-01..R2C1-22 are batch-local PROPOSED identifiers, not owner
business codes. Every fixture is SYNTHETIC: invented ids (the PER-TEST- form
is TEST-ONLY, not a production id format) and invented, labelled names. No
live workbook row, real person, technician or account is used. The Google
Sheets fake-transport counterpart is test_personnel_read_sheets_batch_r2c1.py.
"""
from __future__ import annotations

import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import authz
from app.domain.personnel import (
    PERSONNEL_MASTER_COLUMNS,
    identity_issues,
    operational_rows,
    personnel_record,
)
from app.repositories.base import RepositorySchemaError, RepositoryTabReadError
from app.repositories.mock import MockRepository

API = "/api/v1"
SYN = " (สังเคราะห์)"  # synthetic-data label on every name

PUBLIC_FIELDS = {"personnel_id", "first_name", "last_name", "active_status"}
NON_PUBLIC = ("department", "position", "branch_id", "technician_id", "user_id", "is_test_data", "test_batch_id",
              "note_th")


def person(pid: str, first: str = "ชื่อ" + SYN, last: str = "สกุล" + SYN, status: str = "ACTIVE",
           **extra: str) -> dict[str, str]:
    """A synthetic row with all 12 verified columns. The non-public columns get
    recognisable synthetic markers so tests can prove they never leak.
    is_test_data "FALSE" means "synthetic fixture simulating an
    operational-scope row", NOT real production personnel."""
    row = dict.fromkeys(PERSONNEL_MASTER_COLUMNS, "")
    row.update(personnel_id=pid, first_name=first, last_name=last, active_status=status,
               department="SYN-DEPT-LEAK", position="SYN-POSITION-LEAK", branch_id="SYN-BRANCH-LEAK",
               technician_id="SYN-TECH-LEAK", user_id="SYN-USER-LEAK", is_test_data="FALSE",
               test_batch_id="SYN-BATCH-LEAK", note_th="SYN-NOTE-LEAK")
    row.update(extra)
    return row


PEOPLE = [
    person("PER-TEST-002", "สอง" + SYN, "ทดสอบ" + SYN),
    person("PER-TEST-001", "หนึ่ง" + SYN, "ทดสอบ" + SYN),
    person("PER-TEST-003", "สาม" + SYN, "ทดสอบ" + SYN, status=""),
]


class Spy(MockRepository):
    """MockRepository with replaceable personnel rows, injected failures and a
    log of every public repository coroutine called from outside."""

    def __init__(self, rows=None, *, fail=None) -> None:
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "_depth", [0])
        super().__init__()
        if rows is not None:
            self._personnel_master = rows
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


def _no_leak(text: str) -> None:
    assert "LEAK" not in text, text


# ---------------------------------------------------------------------------
# R2C1-01 / 02 / 03 — list, detail, not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c1_01_valid_personnel_list() -> None:
    repo = Spy(PEOPLE)
    response = await get(f"{API}/personnel", repo)
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 3 and body["page"] == 1
    assert [p["personnel_id"] for p in body["items"]] == ["PER-TEST-001", "PER-TEST-002", "PER-TEST-003"]
    assert body["items"][0] == {"personnel_id": "PER-TEST-001", "first_name": "หนึ่ง" + SYN,
                                "last_name": "ทดสอบ" + SYN, "active_status": "ACTIVE"}
    assert repo.calls == ["read_personnel_master_validated"]


@pytest.mark.asyncio
async def test_r2c1_01_list_paging() -> None:
    body = (await get(f"{API}/personnel", Spy(PEOPLE), params={"page": 2, "page_size": 2})).json()
    assert body["total_items"] == 3 and [p["personnel_id"] for p in body["items"]] == ["PER-TEST-003"]


@pytest.mark.asyncio
async def test_r2c1_01_seeded_mock_is_synthetic_and_served() -> None:
    body = (await get(f"{API}/personnel", MockRepository())).json()
    assert [p["personnel_id"] for p in body["items"]] == ["PER-TEST-001", "PER-TEST-002", "PER-TEST-003"]
    assert body["items"][2]["active_status"] is None  # blank seed status stays unknown
    assert body["total_items"] == 3  # the synthetic TRUE seed row (PER-TEST-901) is excluded


@pytest.mark.asyncio
async def test_r2c1_02_exact_personnel_detail() -> None:
    repo = Spy(PEOPLE)
    response = await get(f"{API}/personnel/PER-TEST-002", repo)
    assert response.status_code == 200
    assert response.json() == {"personnel_id": "PER-TEST-002", "first_name": "สอง" + SYN,
                               "last_name": "ทดสอบ" + SYN, "active_status": "ACTIVE"}
    assert repo.calls == ["read_personnel_master_validated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pid", ["PER-TEST-999", "per-test-001", " PER-TEST-001", "PER-TEST-001 ", "PER-TEST-01",
                                 "1", " "])
async def test_r2c1_03_unknown_or_non_exact_id_is_404(pid) -> None:
    rows = [*PEOPLE, person("0001"), person("001")]
    response = await get(f"{API}/personnel/{pid}", Spy(rows))
    assert response.status_code == 404 and error(response)["code"] == "PERSONNEL_NOT_FOUND"
    assert error(response)["details"] is None


@pytest.mark.asyncio
async def test_r2c1_03_numeric_looking_ids_match_exactly() -> None:
    rows = [person("0001"), person("001"), person("1")]
    for pid in ("0001", "001", "1"):
        body = (await get(f"{API}/personnel/{pid}", Spy(rows))).json()
        assert body["personnel_id"] == pid


# ---------------------------------------------------------------------------
# R2C1-04 / 05 — duplicate and blank identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c1_04_duplicate_id_fails_the_list_and_is_ambiguous_in_detail() -> None:
    rows = [*PEOPLE, person("PER-TEST-001", "ซ้ำ" + SYN)]
    listed = await get(f"{API}/personnel", Spy(rows))
    assert listed.status_code == 500 and error(listed)["code"] == "PERSONNEL_MASTER_DATA_INVALID"
    assert error(listed)["details"] == {"tab": "personnel_master", "issues": {"DUPLICATE_PERSONNEL_ID": 2}}
    detail = await get(f"{API}/personnel/PER-TEST-001", Spy(rows))
    assert detail.status_code == 409 and error(detail)["code"] == "PERSONNEL_ID_AMBIGUOUS"
    assert error(detail)["details"] == {"match_count": 2}
    other = await get(f"{API}/personnel/PER-TEST-002", Spy(rows))  # an unaffected id stays readable
    assert other.status_code == 200
    for response in (listed, detail):
        assert "PER-TEST" not in str(error(response)["details"]) and SYN not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", " ", "\t"])
async def test_r2c1_05_blank_id_fails_the_list(blank) -> None:
    rows = [*PEOPLE, person(blank, "ไม่มีรหัส" + SYN)]
    response = await get(f"{API}/personnel", Spy(rows))
    assert response.status_code == 500 and error(response)["code"] == "PERSONNEL_MASTER_DATA_INVALID"
    assert error(response)["details"] == {"tab": "personnel_master", "issues": {"BLANK_PERSONNEL_ID": 1}}
    assert SYN not in response.text


def test_r2c1_04_05_identity_issue_counting() -> None:
    rows = [person("A"), person("A"), person("A"), person(""), person("B")]
    assert identity_issues(rows) == {"DUPLICATE_PERSONNEL_ID": 3, "BLANK_PERSONNEL_ID": 1}
    assert identity_issues([person("A"), person("a"), person(" A")]) == {}  # exact text, no folding


# ---------------------------------------------------------------------------
# R2C1-06 / 07 — read and schema failures are coded, never empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (RepositoryTabReadError("personnel_master", "down"), 503, "PERSONNEL_MASTER_READ_FAILED"),
        (RepositorySchemaError("personnel_master", "TAB_MISSING"), 500, "PERSONNEL_MASTER_SCHEMA_INVALID"),
        (RepositorySchemaError("personnel_master", "MISSING_HEADERS", ("first_name",)), 500,
         "PERSONNEL_MASTER_SCHEMA_INVALID"),
    ],
)
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001"])
async def test_r2c1_06_07_failures_are_coded_never_empty(failure, status, code, path) -> None:
    response = await get(f"{API}/{path}", Spy(PEOPLE, fail={"read_personnel_master_validated": failure}))
    assert response.status_code == status and error(response)["code"] == code
    assert "items" not in response.text and "personnel_id" not in response.text
    assert error(response)["details"]["tab"] == "personnel_master"


# ---------------------------------------------------------------------------
# R2C1-08..R2C1-11 — status and name text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ACTIVE", "active", " ACTIVE", "INACTIVE", "RESIGNED", "ลาออก", "TRUE", "0"])
async def test_r2c1_08_10_active_status_is_exact_source_text(status) -> None:
    body = (await get(f"{API}/personnel/PER-TEST-001", Spy([person("PER-TEST-001", status=status)]))).json()
    assert body["active_status"] == status  # preserved, not normalized, not rejected


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", " ", "  \t"])
async def test_r2c1_09_blank_active_status_is_null_never_active(blank) -> None:
    rows = [person("PER-TEST-001", status=blank)]
    detail = (await get(f"{API}/personnel/PER-TEST-001", Spy(rows))).json()
    listed = (await get(f"{API}/personnel", Spy(rows))).json()["items"][0]
    for body in (detail, listed):
        assert body["active_status"] is None
        assert body["active_status"] != "ACTIVE"


@pytest.mark.asyncio
async def test_r2c1_11_names_preserve_exact_source_text() -> None:
    odd = ["  นำหน้าเว้นวรรค", "ท้ายเว้นวรรค  ", "0012", "=1+1", "Mc'Donald-ทดสอบ", "x" * 200]
    rows = [person(f"PER-TEST-{i:03d}", first=v, last=v) for i, v in enumerate(odd)]
    items = (await get(f"{API}/personnel", Spy(rows), params={"page_size": 50})).json()["items"]
    assert [(p["first_name"], p["last_name"]) for p in items] == [(v, v) for v in odd]


@pytest.mark.asyncio
async def test_r2c1_11_blank_names_are_null_not_substituted() -> None:
    rows = [person("PER-TEST-001", first="", last=" ")]
    body = (await get(f"{API}/personnel/PER-TEST-001", Spy(rows))).json()
    assert body == {"personnel_id": "PER-TEST-001", "first_name": None, "last_name": None, "active_status": "ACTIVE"}
    listed = await get(f"{API}/personnel", Spy(rows))
    assert listed.status_code == 200  # a blank display name does not invalidate the record


def test_r2c1_11_record_mapping() -> None:
    record = personnel_record(person("PER-TEST-001", first="ก", last="", status=""))
    assert (record.personnel_id, record.first_name, record.last_name, record.active_status) == (
        "PER-TEST-001", "ก", None, None)


# ---------------------------------------------------------------------------
# R2C1-12..R2C1-16 — no joins, permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001"])
async def test_r2c1_12_15_only_the_personnel_read_happens(path) -> None:
    """No user_account / role_permission / technician / driver / branch_master /
    assignment read: the only repository call is the personnel read."""
    repo = Spy(PEOPLE)
    assert (await get(f"{API}/{path}", repo)).status_code == 200
    assert repo.calls == ["read_personnel_master_validated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001"])
async def test_r2c1_16_can_view_required_with_zero_reads(path) -> None:
    repo = Spy(PEOPLE)
    response = await get(f"{API}/{path}", repo, role="NO_SUCH_ROLE")  # holds no capability (fails closed)
    assert response.status_code == 403 and error(response)["code"] == "HTTP_ERROR"
    assert repo.calls == []
    for role in ("ADMIN", "TECHNICIAN"):  # explicit callers holding can_view
        assert authz.CAN_VIEW in authz.capabilities_for_roles((role,))
        allowed = Spy(PEOPLE)
        assert (await get(f"{API}/{path}", allowed, role=role)).status_code == 200
        assert allowed.calls == ["read_personnel_master_validated"]


# ---------------------------------------------------------------------------
# R2C1-19 — public response excludes every non-public column
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c1_19_public_response_excludes_non_public_columns() -> None:
    listed = await get(f"{API}/personnel", Spy(PEOPLE))
    detail = await get(f"{API}/personnel/PER-TEST-001", Spy(PEOPLE))
    for item in [*listed.json()["items"], detail.json()]:
        assert set(item) == PUBLIC_FIELDS
    for response in (listed, detail):
        _no_leak(response.text)
        for column in NON_PUBLIC:
            assert f'"{column}"' not in response.text


def test_r2c1_19_openapi_schema_has_only_public_fields() -> None:
    from app.main import create_app

    schema = create_app().openapi()["components"]["schemas"]["PersonnelResponse"]
    assert set(schema["properties"]) == PUBLIC_FIELDS
    assert schema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# R2C1-20..R2C1-22 — guardrails (permanent: only R2c-1 itself and frozen rules)
# ---------------------------------------------------------------------------


def _routes() -> set[tuple[str, str]]:
    from app.main import create_app

    spec = create_app().openapi()
    return {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}


def test_r2c1_22_routes_exist_without_freezing_the_future_personnel_surface() -> None:
    routes = _routes()
    assert ("GET", "/api/v1/personnel") in routes
    assert ("GET", "/api/v1/personnel/{personnel_id}") in routes
    # Referenced masters are deactivated, never hard-deleted (approved R2 principle).
    assert ("DELETE", "/api/v1/personnel/{personnel_id}") not in routes
    # Frozen R1 registry capabilities keep their exact holders. New capabilities
    # (e.g. R2e personnel lifecycle) may be added later without breaking this.
    for capability in ("can_edit_vehicle_registration", "can_transfer_vehicle_branch", "can_correct_branch_history"):
        holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if capability in caps}
        assert holders == {"ADMIN", "MAINTENANCE_MANAGER"}, capability


def test_r2c1_20_legacy_technician_identity_rules_are_intact() -> None:
    """INTENTIONAL CONTRACT EVOLUTION (R2 Batch R2f-a, Final Contract C1 §23):
    amended, not deleted. R2f supersedes "no technician master", so R2f-a may
    add technician_master / user_account READ support. What stays true: the
    R2c-1 personnel read itself adds no technician / account method or tab and
    stays join-free; legacy Repair / PM assignments keep their opaque user_id
    strings; and no technician_master or user_account WRITE method exists."""
    from app.domain.personnel import PersonnelService
    from app.repositories.google_sheets import schemas as sheet_schemas
    from tests.test_relationship_read_batch_r2f_a import assert_reference_surface_is_read_only

    assert_reference_surface_is_read_only()
    # The R2c-1 read path itself calls only its own personnel read.
    source = inspect.getsource(PersonnelService)
    assert "technician" not in source.lower() and "user_account" not in source
    assert sheet_schemas.PERSONNEL_MASTER_SHEET.required_headers == PERSONNEL_MASTER_COLUMNS
    assert sheet_schemas.PERSONNEL_MASTER_READ_SHEET.required_headers == (
        "personnel_id", "first_name", "last_name", "active_status", "is_test_data")


# ---------------------------------------------------------------------------
# Operational data scope (independent-review fix R1): FALSE included, TRUE
# excluded, blank/invalid flag fails closed — classified BEFORE identity checks.
# All rows synthetic; "TRUE" rows simulate explicitly-test source rows.
# ---------------------------------------------------------------------------


def synthetic_test_row(pid: str, **extra: str) -> dict[str, str]:
    return person(pid, "แถวทดสอบ" + SYN, "ไม่แสดง" + SYN, is_test_data="TRUE", test_batch_id="SYN-TEST-BATCH", **extra)


@pytest.mark.asyncio
async def test_r2c1_scope_a_list_returns_only_false_rows_and_counts_after_exclusion() -> None:
    rows = [*PEOPLE, synthetic_test_row("PER-TEST-901"), synthetic_test_row("PER-TEST-902")]
    body = (await get(f"{API}/personnel", Spy(rows), params={"page_size": 2})).json()
    assert body["total_items"] == 3
    assert [p["personnel_id"] for p in body["items"]] == ["PER-TEST-001", "PER-TEST-002"]
    page2 = (await get(f"{API}/personnel", Spy(rows), params={"page": 2, "page_size": 2})).json()
    assert [p["personnel_id"] for p in page2["items"]] == ["PER-TEST-003"]


@pytest.mark.asyncio
async def test_r2c1_scope_b_detail_of_a_test_only_id_is_404() -> None:
    response = await get(f"{API}/personnel/PER-TEST-901", Spy([*PEOPLE, synthetic_test_row("PER-TEST-901")]))
    assert response.status_code == 404 and error(response)["code"] == "PERSONNEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_r2c1_scope_c_test_row_sharing_an_operational_id_causes_no_ambiguity() -> None:
    rows = [*PEOPLE, synthetic_test_row("PER-TEST-001")]
    detail = await get(f"{API}/personnel/PER-TEST-001", Spy(rows))
    assert detail.status_code == 200 and detail.json()["first_name"] == "หนึ่ง" + SYN
    listed = await get(f"{API}/personnel", Spy(rows))
    assert listed.status_code == 200 and listed.json()["total_items"] == 3


@pytest.mark.asyncio
async def test_r2c1_scope_d_two_operational_rows_with_one_id_keep_duplicate_behaviour() -> None:
    rows = [*PEOPLE, person("PER-TEST-001", "ซ้ำ" + SYN), synthetic_test_row("PER-TEST-001")]
    listed = await get(f"{API}/personnel", Spy(rows))
    assert error(listed)["details"] == {"tab": "personnel_master", "issues": {"DUPLICATE_PERSONNEL_ID": 2}}
    detail = await get(f"{API}/personnel/PER-TEST-001", Spy(rows))
    assert detail.status_code == 409 and error(detail)["details"] == {"match_count": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["", " ", "\t", "true", "false", "True", "YES", "NO", "0", "1", " FALSE", "TRUE "])
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001"])
async def test_r2c1_scope_e_f_blank_or_invalid_test_flag_fails_closed(flag, path) -> None:
    rows = [*PEOPLE, person("PER-TEST-004", is_test_data=flag)]
    response = await get(f"{API}/{path}", Spy(rows))
    assert response.status_code == 500 and error(response)["code"] == "PERSONNEL_MASTER_DATA_INVALID"
    assert error(response)["details"] == {"tab": "personnel_master", "issues": {"TEST_FLAG_INVALID": 1}}
    assert "PER-TEST" not in response.text and SYN not in response.text and "LEAK" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["", " "])
async def test_r2c1_scope_g_malformed_test_rows_do_not_affect_the_operational_scope(bad_id) -> None:
    rows = [*PEOPLE, synthetic_test_row(bad_id), synthetic_test_row("PER-TEST-901"), synthetic_test_row("PER-TEST-901")]
    listed = await get(f"{API}/personnel", Spy(rows))
    assert listed.status_code == 200 and listed.json()["total_items"] == 3
    assert (await get(f"{API}/personnel/PER-TEST-002", Spy(rows))).status_code == 200


@pytest.mark.asyncio
async def test_r2c1_scope_h_flag_and_batch_never_exposed() -> None:
    rows = [*PEOPLE, synthetic_test_row("PER-TEST-901")]
    for path in ("personnel", "personnel/PER-TEST-001"):
        response = await get(f"{API}/{path}", Spy(rows))
        assert "is_test_data" not in response.text and "test_batch_id" not in response.text
        assert "SYN-TEST-BATCH" not in response.text and "LEAK" not in response.text


@pytest.mark.asyncio
async def test_r2c1_scope_rows_without_personnel_content_are_skipped_whatever_the_flag() -> None:
    """A row whose four public columns are all blank is not a personnel record
    (e.g. an unchecked checkbox left in an otherwise empty row)."""
    empty = dict.fromkeys(PERSONNEL_MASTER_COLUMNS, "")
    rows = [*PEOPLE, {**empty, "is_test_data": "FALSE"}, {**empty, "is_test_data": "TRUE"}, dict(empty)]
    listed = await get(f"{API}/personnel", Spy(rows))
    assert listed.status_code == 200 and listed.json()["total_items"] == 3


def test_r2c1_scope_classification_happens_before_identity_checks() -> None:
    rows = [person("A"), synthetic_test_row("A"), synthetic_test_row(""), person("B", is_test_data="maybe")]
    kept, issues = operational_rows(rows)
    assert [r["personnel_id"] for r in kept] == ["A"]
    assert issues == {"TEST_FLAG_INVALID": 1}
    assert identity_issues(kept) == {}  # the test rows never reach identity validation
