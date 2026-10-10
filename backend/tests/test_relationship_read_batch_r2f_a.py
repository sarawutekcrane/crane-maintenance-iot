"""R2 Batch R2f-a — relationship read foundation (READ ONLY), mock / service level.

Final Contract C1 §5 / §6 / §15 / §23 / §28 / §30. Every row is SYNTHETIC and
labelled; no live workbook value is used and no production count is assumed.
TEST-scoped references are explicit synthetic fixtures (`ScopedReferenceRow`
with scope TEST and a batch id): the scope is never derived from an id prefix
or any other cell value.

Batch-local ids: R2FA-01 technician read, R2FA-02 account read, R2FA-03
Personnel ↔ Technician, R2FA-04 Personnel ↔ Account, R2FA-05 reverse,
R2FA-06 read errors, R2FA-07 no fuzzy matching, R2FA-08 authorization,
R2FA-09 zero writes / read-only surface, R2FA-10 legacy separation.
"""
from __future__ import annotations

import inspect

import pytest

from app.domain.common import PageParams
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS
from app.domain.personnel_relationship import (
    AMBIGUOUS,
    MISSING,
    RESOLVED,
    SCOPE_UNPROVEN,
    UNSET,
    PersonnelRelationshipService,
)
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.technician import TECHNICIAN_READ_COLUMNS, TechnicianService
from app.errors import ApiError
from app.repositories.base import (
    REFERENCE_SCOPE_REAL,
    REFERENCE_SCOPE_TEST,
    RepositorySchemaError,
    RepositoryTabReadError,
    ScopedReferenceRow,
)
from tests.test_personnel_read_batch_r2c1 import Spy, error, get

API = "/api/v1"
SYN = " (สังเคราะห์)"
BATCH = "SYN-R2FA-BATCH"
OTHER_BATCH = "SYN-R2FA-OTHER"


# ---------------------------------------------------------------------------
# Shared read-only-surface proof (also used by the two amended legacy guards)
# ---------------------------------------------------------------------------


def assert_reference_surface_is_read_only() -> None:
    """R2f-a may READ technician_master / user_account; no write path exists for
    either tab. R2 Batch R2f-b (deliberate evolution of this R2f-a guard): the
    ONLY relationship-change surface is the approved Personnel ↔ Technician
    link — four link methods keyed by link, with TECHNICIAN as the only
    registered key — which writes personnel_master.technician_id and its own
    history tab, never technician_master or user_account."""
    from app.repositories import base as repository_base
    from app.repositories.google_sheets import repository as sheets_repository
    from app.repositories.google_sheets import schemas as sheet_schemas

    names = [n for n in dir(repository_base.Repository) if not n.startswith("_")]
    assert [n for n in names if "technician" in n.lower()] == ["read_technician_master_reference"]
    assert [n for n in names if "account" in n.lower()] == ["read_user_account_reference"]
    assert [n for n in names if "relationship" in n.lower() or "link" in n.lower()] == [
        "append_personnel_link_history", "read_personnel_link_history_validated", "read_personnel_link_master",
        "read_personnel_relationship_master", "write_personnel_link_cell",
    ]
    # R2 Batch R2f-c (deliberate evolution): ACCOUNT joins TECHNICIAN; no driver link key exists.
    assert repository_base.PERSONNEL_LINKS == (repository_base.PERSONNEL_LINK_TECHNICIAN,
                                              repository_base.PERSONNEL_LINK_ACCOUNT)
    tabs = {k: v for k, v in vars(sheet_schemas).items() if hasattr(v, "tab_name")}
    assert {k for k, v in tabs.items() if v.tab_name == "technician_master"} == {"TECHNICIAN_MASTER_READ_SHEET"}
    assert {k for k, v in tabs.items() if "technician" in v.tab_name} == {
        "TECHNICIAN_MASTER_READ_SHEET", "PERSONNEL_TECHNICIAN_LINK_HISTORY_SHEET"}
    assert {k for k, v in tabs.items() if v.tab_name == "user_account"} == {"USER_ACCOUNT_READ_SHEET"}
    assert sheet_schemas.TECHNICIAN_MASTER_READ_SHEET.required_headers == TECHNICIAN_READ_COLUMNS
    assert sheet_schemas.USER_ACCOUNT_READ_SHEET.required_headers == ("user_id",)
    link_writes = inspect.getsource(sheets_repository.GoogleSheetsRepository.write_personnel_link_cell)
    assert "TECHNICIAN_MASTER" not in link_writes and "USER_ACCOUNT" not in link_writes
    assert not [n for n in names if "driver" in n.lower() and "link" in n.lower()]
    # The Sheets repository only ever READS these schemas, and only through the
    # truly column-limited path (review fix R1): never the whole-tab
    # `_registry_table` / `_validated_read` readers, never a write.
    source = inspect.getsource(sheets_repository.GoogleSheetsRepository)
    for schema in ("TECHNICIAN_MASTER_READ_SHEET", "USER_ACCOUNT_READ_SHEET", "PERSONNEL_RELATIONSHIP_READ_SHEET"):
        lines = [line for line in source.splitlines() if schema in line]
        assert lines and all("_reference_master(" in line or "_bounded_table(" in line for line in lines), schema
    bounded = inspect.getsource(sheets_repository.GoogleSheetsRepository._bounded_table)
    assert "read_bounded_columns(" in bounded and "_registry_table" not in bounded
    reference = inspect.getsource(sheets_repository.GoogleSheetsRepository._reference_master)
    assert "_bounded_table(" in reference and "_registry_table" not in reference


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


def person(pid: str, *, technician_id: str = "", user_id: str = "", test: bool = False,
           batch: str = "") -> dict[str, str]:
    """A synthetic personnel_master row (all 12 verified columns). FALSE means
    "synthetic fixture simulating an operational-scope row"."""
    row = dict.fromkeys(PERSONNEL_MASTER_COLUMNS, "")
    row.update(personnel_id=pid, first_name="ชื่อ" + SYN, last_name="สกุล" + SYN, active_status="ACTIVE",
               technician_id=technician_id, user_id=user_id, is_test_data="TRUE" if test else "FALSE",
               test_batch_id=batch, department="SYN-DEPT", position="SYN-POSITION", branch_id="SYN-BRANCH")
    return row


def tech(tid: str, *, scope: str = REFERENCE_SCOPE_REAL, batch: str = "", first: str = "ช่าง" + SYN,
         last: str = "ทดสอบ" + SYN, status: str = "ACTIVE") -> ScopedReferenceRow:
    return ScopedReferenceRow(
        values={"technician_id": tid, "first_name": first, "last_name": last, "active_status": status},
        scope=scope, test_batch_id=batch,
    )


def account(uid: str, *, scope: str = REFERENCE_SCOPE_REAL, batch: str = "") -> ScopedReferenceRow:
    return ScopedReferenceRow(values={"user_id": uid}, scope=scope, test_batch_id=batch)


class RelSpy(Spy):
    """Spy with replaceable reference rows; logs every public coroutine call."""

    def __init__(self, people=None, technicians=None, accounts=None, *, fail=None) -> None:
        super().__init__(people, fail=fail)
        if technicians is not None:
            self._technician_master = list(technicians)
        if accounts is not None:
            self._user_account = list(accounts)


def service(repo, context: str = "REAL", batch: str = BATCH) -> PersonnelRelationshipService:
    return PersonnelRelationshipService(repo, context, batch)


async def links(repo, pid: str, context: str = "REAL", batch: str = BATCH):
    return await service(repo, context, batch).personnel_relationships(pid)


# ---------------------------------------------------------------------------
# R2FA-01 — technician_master bounded read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_01_list_is_sorted_real_scope_only_and_bounded() -> None:
    repo = RelSpy(technicians=[tech("TEC-SYN-2"), tech("TEC-SYN-1", status=""),
                               tech("TEC-SYN-9", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    page = await TechnicianService(repo).list_technicians(PageParams(page=1, page_size=20))
    assert [t.technician_id for t in page.items] == ["TEC-SYN-1", "TEC-SYN-2"]  # TEST fixture never listed
    assert page.total_items == 2
    assert page.items[0].active_status is None  # blank = unknown, never defaulted
    response = await get(f"{API}/technicians", RelSpy(technicians=[tech("TEC-SYN-1")]))
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == {"technician_id", "first_name", "last_name", "active_status"}


@pytest.mark.asyncio
async def test_r2fa_01_detail_exact_id_missing_and_duplicate() -> None:
    repo = RelSpy(technicians=[tech("TEC-SYN-1"), tech("TEC-SYN-D"), tech("TEC-SYN-D")])
    ok = await get(f"{API}/technicians/TEC-SYN-1", repo)
    assert ok.status_code == 200 and ok.json()["technician_id"] == "TEC-SYN-1"
    for wrong in ("tec-syn-1", " TEC-SYN-1", "TEC-SYN-1 ", "TEC-SYN", "%20"):
        assert error(await get(f"{API}/technicians/{wrong}", repo))["code"] == "TECHNICIAN_NOT_FOUND", wrong
    dup = await get(f"{API}/technicians/TEC-SYN-D", repo)
    assert (dup.status_code, error(dup)["code"], error(dup)["details"]) == (
        409, "TECHNICIAN_ID_AMBIGUOUS", {"match_count": 2})


@pytest.mark.asyncio
async def test_r2fa_01_list_fails_closed_on_duplicate_or_blank_id() -> None:
    for rows, issue in (([tech("TEC-SYN-1"), tech("TEC-SYN-1")], "DUPLICATE_TECHNICIAN_ID"),
                        ([tech("TEC-SYN-1"), tech("", first="x")], "BLANK_TECHNICIAN_ID")):
        response = await get(f"{API}/technicians", RelSpy(technicians=rows))
        assert (response.status_code, error(response)["code"]) == (500, "TECHNICIAN_MASTER_DATA_INVALID")
        assert issue in error(response)["details"]["issues"]
        assert "TEC-SYN" not in response.text  # counts only, never ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [(RepositorySchemaError("technician_master", "MISSING_HEADERS", ("active_status",)), 500,
      "TECHNICIAN_MASTER_SCHEMA_INVALID"),
     (RepositoryTabReadError("technician_master", "down"), 503, "TECHNICIAN_MASTER_READ_FAILED")],
)
@pytest.mark.parametrize("path", ["technicians", "technicians/TEC-TEST-001"])
async def test_r2fa_01_06_read_failure_is_an_error_never_empty(exc, status, code, path) -> None:
    response = await get(f"{API}/{path}", RelSpy(fail={"read_technician_master_reference": exc}))
    assert (response.status_code, error(response)["code"]) == (status, code)
    assert "items" not in response.json()


# ---------------------------------------------------------------------------
# R2FA-03 — Personnel ↔ Technician
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_03_real_unset_resolved_missing_ambiguous() -> None:
    repo = RelSpy(
        people=[person("P-UNSET"), person("P-OK", technician_id="TEC-SYN-1"),
                person("P-MISS", technician_id="TEC-SYN-404"),
                person("P-DUPA", technician_id="TEC-SYN-SHARED"), person("P-DUPB", technician_id="TEC-SYN-SHARED"),
                person("P-TDUP", technician_id="TEC-SYN-D")],
        technicians=[tech("TEC-SYN-1"), tech("TEC-SYN-SHARED"), tech("TEC-SYN-D"), tech("TEC-SYN-D")],
    )
    assert (await links(repo, "P-UNSET")).technician.resolution == UNSET
    assert (await links(repo, "P-UNSET")).technician.linked_id is None
    ok = await links(repo, "P-OK")
    assert (ok.technician.resolution, ok.technician.linked_id) == (RESOLVED, "TEC-SYN-1")
    assert ok.technician_record.technician_id == "TEC-SYN-1"
    missing = await links(repo, "P-MISS")
    assert (missing.technician.resolution, missing.technician.linked_id, missing.technician_record) == (
        MISSING, "TEC-SYN-404", None)
    # 0..1: two in-scope personnel holding one technician -> AMBIGUOUS for both, nothing selected
    for pid in ("P-DUPA", "P-DUPB"):
        result = await links(repo, pid)
        assert (result.technician.resolution, result.technician_record) == (AMBIGUOUS, None)
    # a duplicated technician_id in the master never silently selects the first row
    assert (await links(repo, "P-TDUP")).technician.resolution == AMBIGUOUS


@pytest.mark.asyncio
async def test_r2fa_03_real_never_resolves_a_test_fixture() -> None:
    repo = RelSpy(people=[person("P-1", technician_id="TEC-SYN-T")],
                  technicians=[tech("TEC-SYN-T", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    result = await links(repo, "P-1", "REAL")
    assert (result.technician.resolution, result.technician_record) == (MISSING, None)


@pytest.mark.asyncio
async def test_r2fa_03_test_synthetic_reference_resolves_in_its_batch_only() -> None:
    people = [person("P-T", technician_id="TEC-SYN-T", test=True, batch=BATCH)]
    repo = RelSpy(people=people, technicians=[tech("TEC-SYN-T", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    result = await links(repo, "P-T", "TEST", BATCH)
    assert (result.technician.resolution, result.technician_record.technician_id) == (RESOLVED, "TEC-SYN-T")
    # the same fixture in ANOTHER batch is not this scope: never resolved
    other = RelSpy(people=people, technicians=[tech("TEC-SYN-T", scope=REFERENCE_SCOPE_TEST, batch=OTHER_BATCH)])
    assert (await links(other, "P-T", "TEST", BATCH)).technician.resolution == SCOPE_UNPROVEN


@pytest.mark.asyncio
async def test_r2fa_03_test_never_resolves_to_a_real_operational_technician() -> None:
    """OD-13: a TEST personnel whose technician_id exists only as a REAL
    (untagged operational) row is SCOPE_UNPROVEN, never RESOLVED."""
    repo = RelSpy(people=[person("P-T", technician_id="TEC-SYN-REAL", test=True, batch=BATCH)],
                  technicians=[tech("TEC-SYN-REAL")])
    result = await links(repo, "P-T", "TEST", BATCH)
    assert (result.technician.resolution, result.technician_record) == (SCOPE_UNPROVEN, None)


@pytest.mark.asyncio
async def test_r2fa_03_test_missing_only_when_test_scope_is_supported_and_no_scope_has_it() -> None:
    repo = RelSpy(people=[person("P-T", technician_id="TEC-SYN-NONE", test=True, batch=BATCH)],
                  technicians=[tech("TEC-SYN-OTHER", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert (await links(repo, "P-T", "TEST", BATCH)).technician.resolution == MISSING


@pytest.mark.asyncio
async def test_r2fa_03_personnel_scope_and_test_flag_rules() -> None:
    real, test_row = person("P-R"), person("P-T", test=True, batch=BATCH)
    repo = RelSpy(people=[real, test_row, person("P-X", test=True, batch=OTHER_BATCH)])
    with pytest.raises(ApiError) as exc:
        await links(repo, "P-T", "REAL")  # a TEST row is not in REAL scope
    assert exc.value.code == "PERSONNEL_NOT_FOUND"
    with pytest.raises(ApiError) as exc:
        await links(repo, "P-R", "TEST", BATCH)  # a REAL row is not in TEST scope
    assert exc.value.code == "PERSONNEL_NOT_FOUND"
    with pytest.raises(ApiError) as exc:
        await links(repo, "P-X", "TEST", BATCH)  # another batch is not this scope
    assert exc.value.code == "PERSONNEL_NOT_FOUND"
    with pytest.raises(ApiError) as exc:
        await links(RelSpy(people=[real, {**person("P-Q"), "is_test_data": "yes"}]), "P-R")
    assert (exc.value.code, exc.value.details["issues"]) == ("PERSONNEL_MASTER_DATA_INVALID", {"TEST_FLAG_INVALID": 1})
    with pytest.raises(ApiError) as exc:
        await links(RelSpy(people=[real, person("P-R")]), "P-R")
    assert exc.value.code == "PERSONNEL_ID_AMBIGUOUS"


# ---------------------------------------------------------------------------
# R2FA-02 / R2FA-04 — user_account bounded read and Personnel ↔ Account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_04_real_unset_resolved_missing_ambiguous() -> None:
    repo = RelSpy(
        people=[person("P-UNSET"), person("P-OK", user_id="USR-SYN-1"), person("P-MISS", user_id="USR-SYN-404"),
                person("P-A", user_id="USR-SYN-SHARED"), person("P-B", user_id="USR-SYN-SHARED"),
                person("P-ADUP", user_id="USR-SYN-D")],
        accounts=[account("USR-SYN-1"), account("USR-SYN-SHARED"), account("USR-SYN-D"), account("USR-SYN-D")],
    )
    expected = {"P-UNSET": UNSET, "P-OK": RESOLVED, "P-MISS": MISSING, "P-A": AMBIGUOUS, "P-B": AMBIGUOUS,
                "P-ADUP": AMBIGUOUS}
    for pid, resolution in expected.items():
        assert (await links(repo, pid)).account.resolution == resolution, pid
    assert (await links(repo, "P-UNSET")).account.linked_id is None
    # exact text only
    near = RelSpy(people=[person("P-1", user_id="usr-syn-1")], accounts=[account("USR-SYN-1")])
    assert (await links(near, "P-1")).account.resolution == MISSING


@pytest.mark.asyncio
async def test_r2fa_04_scope_rules_for_accounts() -> None:
    real_only = RelSpy(people=[person("P-T", user_id="USR-SYN-REAL", test=True, batch=BATCH)],
                       accounts=[account("USR-SYN-REAL")])
    assert (await links(real_only, "P-T", "TEST", BATCH)).account.resolution == SCOPE_UNPROVEN
    test_ok = RelSpy(people=[person("P-T", user_id="USR-SYN-T", test=True, batch=BATCH)],
                     accounts=[account("USR-SYN-T", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert (await links(test_ok, "P-T", "TEST", BATCH)).account.resolution == RESOLVED
    real_vs_fixture = RelSpy(people=[person("P-R", user_id="USR-SYN-T")],
                             accounts=[account("USR-SYN-T", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert (await links(real_vs_fixture, "P-R", "REAL")).account.resolution == MISSING


@pytest.mark.asyncio
async def test_r2fa_02_account_read_is_bounded_to_user_id() -> None:
    repo = RelSpy(accounts=[ScopedReferenceRow(
        values={"user_id": "USR-SYN-1", "email": "x@example.invalid", "display_name_th": "ผู้ใช้" + SYN},
        scope=REFERENCE_SCOPE_REAL)])
    read = await repo.read_user_account_reference()
    assert [r.values for r in read.rows] == [{"user_id": "USR-SYN-1"}]
    assert read.columns == frozenset({"user_id"})


@pytest.mark.asyncio
async def test_r2fa_08_api_redacts_the_raw_user_id() -> None:
    repo = RelSpy(people=[person("P-T", technician_id="TEC-TEST-901", user_id="USR-TEST-901", test=True,
                                 batch=MOCK_TEST_BATCH_ID)])
    # R2 Batch R2f-c (deliberate evolution): a can_view-only caller still gets
    # the resolution only; a holder of can_link_personnel_account (ADMIN here)
    # also gets the raw linked user_id, and nothing else from the account.
    holder = (await get(f"{API}/personnel/P-T/relationships", repo)).json()
    assert holder["account"] == {"resolution": "RESOLVED", "user_id": "USR-TEST-901"}
    response = await get(f"{API}/personnel/P-T/relationships", repo, role="TECHNICIAN")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "personnel_id": "P-T",
        "technician": {
            "resolution": "RESOLVED", "technician_id": "TEC-TEST-901",
            "technician": {"technician_id": "TEC-TEST-901", "first_name": "ช่างแถวทดสอบ",
                           "last_name": "อ้างอิงทดสอบเท่านั้น", "active_status": "ACTIVE"},
        },
        "account": {"resolution": "RESOLVED"},
    }
    assert "USR-TEST-901" not in response.text  # never returned to a caller without the capability
    assert "SYN-DEPT" not in response.text and "SYN-BRANCH" not in response.text


# ---------------------------------------------------------------------------
# R2FA-05 — reverse Technician -> Personnel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_05_reverse_one_none_duplicate_and_scope() -> None:
    repo = RelSpy(
        people=[person("P-1", technician_id="TEC-SYN-1"), person("P-A", technician_id="TEC-SYN-D"),
                person("P-B", technician_id="TEC-SYN-D"), person("P-T", technician_id="TEC-SYN-2", test=True,
                                                                  batch=BATCH)],
        technicians=[tech("TEC-SYN-1"), tech("TEC-SYN-2"), tech("TEC-SYN-D"),
                     tech("TEC-SYN-T", scope=REFERENCE_SCOPE_TEST, batch=BATCH)],
    )
    svc = service(repo)
    one = await svc.technician_personnel("TEC-SYN-1")
    assert (one.resolution, one.personnel_id, one.match_count) == (RESOLVED, "P-1", 1)
    none = await svc.technician_personnel("TEC-SYN-2")  # only a TEST personnel holds it: not in REAL scope
    assert (none.resolution, none.personnel_id, none.match_count) == (UNSET, None, 0)
    dup = await svc.technician_personnel("TEC-SYN-D")
    assert (dup.resolution, dup.personnel_id, dup.match_count) == (AMBIGUOUS, None, 2)
    for missing in ("TEC-SYN-404", "TEC-SYN-T", "tec-syn-1"):  # a TEST fixture is not a REAL technician
        with pytest.raises(ApiError) as exc:
            await svc.technician_personnel(missing)
        assert exc.value.code == "TECHNICIAN_NOT_FOUND", missing
    with pytest.raises(ApiError) as exc:  # TEST context never targets a REAL technician
        await service(repo, "TEST", BATCH).technician_personnel("TEC-SYN-1")
    assert exc.value.code == "TECHNICIAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_r2fa_05_reverse_api_in_mock_test_scope() -> None:
    repo = RelSpy(people=[person("P-T", technician_id="TEC-TEST-901", test=True, batch=MOCK_TEST_BATCH_ID)])
    response = await get(f"{API}/technicians/TEC-TEST-901/personnel", repo)
    assert response.status_code == 200
    assert response.json() == {"technician_id": "TEC-TEST-901", "resolution": "RESOLVED", "personnel_id": "P-T",
                               "match_count": 1}
    real = await get(f"{API}/technicians/TEC-TEST-001/personnel", repo)  # a REAL-scope row in the TEST context
    assert (real.status_code, error(real)["code"]) == (404, "TECHNICIAN_NOT_FOUND")


# ---------------------------------------------------------------------------
# R2FA-06 — read errors are never states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "code", "status"),
    [("read_personnel_relationship_master", "PERSONNEL_MASTER", None),
     ("read_technician_master_reference", "TECHNICIAN_MASTER", None),
     ("read_user_account_reference", "USER_ACCOUNT", None)],
)
@pytest.mark.parametrize("kind", ["schema", "read"])
async def test_r2fa_06_any_failed_read_is_an_error_never_unset(method, code, status, kind) -> None:
    tab = {"PERSONNEL_MASTER": "personnel_master", "TECHNICIAN_MASTER": "technician_master",
           "USER_ACCOUNT": "user_account"}[code]
    exc = RepositorySchemaError(tab, "MISSING_HEADERS", ("x",)) if kind == "schema" else RepositoryTabReadError(tab, "x")
    repo = RelSpy(people=[person("P-T", test=True, batch=MOCK_TEST_BATCH_ID)], fail={method: exc})
    response = await get(f"{API}/personnel/P-T/relationships", repo)
    expected = (500, f"{code}_SCHEMA_INVALID") if kind == "schema" else (503, f"{code}_READ_FAILED")
    assert (response.status_code, error(response)["code"]) == expected
    assert "resolution" not in response.text


@pytest.mark.asyncio
async def test_r2fa_06_unconfigured_context_fails_before_any_read() -> None:
    repo = RelSpy()
    with pytest.raises(ApiError) as exc:
        await service(repo, None).personnel_relationships("P-1")
    assert exc.value.code == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    with pytest.raises(ApiError) as exc:
        await PersonnelRelationshipService(repo, "TEST", " ").technician_personnel("T-1")
    assert exc.value.code == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert repo.calls == []


# ---------------------------------------------------------------------------
# R2FA-07 — no fuzzy / name / email matching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_07_matching_name_or_email_with_a_wrong_id_never_resolves() -> None:
    same_name = "สมมติ" + SYN
    row = person("P-1", technician_id="TEC-SYN-WRONG", user_id="someone@example.invalid")
    row.update(first_name=same_name, last_name=same_name)
    repo = RelSpy(
        people=[row],
        technicians=[tech("TEC-SYN-RIGHT", first=same_name, last=same_name)],
        accounts=[ScopedReferenceRow(values={"user_id": "USR-SYN-RIGHT", "email": "someone@example.invalid"},
                                     scope=REFERENCE_SCOPE_REAL)],
    )
    result = await links(repo, "P-1")
    assert (result.technician.resolution, result.account.resolution) == (MISSING, MISSING)
    # and a blank link is UNSET even when a same-named technician exists
    blank = RelSpy(people=[{**row, "technician_id": "", "user_id": ""}],
                   technicians=[tech("TEC-SYN-RIGHT", first=same_name, last=same_name)])
    blank_result = await links(blank, "P-1")
    assert (blank_result.technician.resolution, blank_result.account.resolution) == (UNSET, UNSET)


# ---------------------------------------------------------------------------
# R2FA-08 — authorization (can_view; backend-authoritative; zero reads on 403)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["technicians", "technicians/TEC-TEST-001", "personnel/P-T/relationships",
                                  "technicians/TEC-TEST-901/personnel"])
async def test_r2fa_08_requires_can_view_and_reads_nothing_on_403(path) -> None:
    repo = RelSpy()
    response = await get(f"{API}/{path}", repo, role="NO_SUCH_ROLE")
    assert response.status_code == 403
    assert repo.calls == []
    for role in ("TECHNICIAN", "DRIVER", "MAINTENANCE_MANAGER"):
        assert (await get(f"{API}/{path}", RelSpy(people=[person("P-T", test=True, batch=MOCK_TEST_BATCH_ID)]),
                          role=role)).status_code in (200, 404), role


def test_r2fa_08_no_role_or_capability_was_widened() -> None:
    from app.domain import authz

    # R2 Batch R2f-b (deliberate evolution): the ONE approved relationship
    # capability is can_link_personnel_technician; no account / driver link
    # capability exists and no read role was widened.
    # R2 Batch R2f-c (deliberate evolution): can_link_personnel_account joins it. Still no driver capability.
    related = {c for c in authz.ALL_CAPABILITIES if "relationship" in c or "link" in c or "technician" in c}
    assert related == {"can_link_personnel_technician", "can_link_personnel_account"}
    assert not any("driver" in c for c in authz.ALL_CAPABILITIES)


# ---------------------------------------------------------------------------
# R2FA-09 — zero writes and a read-only surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_09_every_r2f_a_route_performs_zero_writes() -> None:
    repo = RelSpy(people=[person("P-T", technician_id="TEC-TEST-901", user_id="USR-TEST-901", test=True,
                                 batch=MOCK_TEST_BATCH_ID)])
    before = (repo._personnel_master, list(repo._technician_master), list(repo._user_account))
    import copy

    snapshot = copy.deepcopy(before)
    for path in ("technicians", "technicians/TEC-TEST-001", "personnel/P-T/relationships",
                 "technicians/TEC-TEST-901/personnel"):
        assert (await get(f"{API}/{path}", repo)).status_code == 200, path
    assert set(repo.calls) <= {"read_technician_master_reference", "read_user_account_reference",
                               "read_personnel_relationship_master"}
    assert repo.registry_write_log == []
    assert (repo._personnel_master, list(repo._technician_master), list(repo._user_account)) == snapshot


def test_r2fa_09_reference_surface_is_read_only_and_routes_are_get_only() -> None:
    from app.main import create_app

    assert_reference_surface_is_read_only()
    new_paths = {"/api/v1/technicians", "/api/v1/technicians/{technician_id}",
                 "/api/v1/personnel/{personnel_id}/relationships", "/api/v1/technicians/{technician_id}/personnel"}
    routes = {(m.upper(), path) for path, ops in create_app().openapi()["paths"].items() for m in ops}
    related = {(m, p) for m, p in routes if "technician" in p or "relationship" in p or "user-account" in p}
    # R2f-a's reads stay GET-only; R2 Batch R2f-b (deliberate evolution) adds exactly the three
    # Personnel ↔ Technician link routes. No account / driver relationship route exists.
    r2fb = {("POST", "/api/v1/personnel/{personnel_id}/technician-links"),
            ("POST", "/api/v1/personnel/{personnel_id}/technician-links/reconcile"),
            ("GET", "/api/v1/personnel/{personnel_id}/technician-links/history")}
    # R2 Batch R2f-d (deliberate evolution): exactly the one read-only reverse caretaker route.
    r2fd = {("GET", "/api/v1/technicians/{technician_id}/equipment")}
    assert related == {("GET", p) for p in new_paths} | r2fb | r2fd


# ---------------------------------------------------------------------------
# R2FA-10 — R2c-1 personnel GET stays join-free; no driver handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_10_personnel_get_is_unchanged_and_join_free() -> None:
    repo = RelSpy(people=[person("P-1", technician_id="TEC-SYN-1", user_id="USR-SYN-1")])
    response = await get(f"{API}/personnel/P-1", repo)
    assert response.status_code == 200
    assert set(response.json()) == {"personnel_id", "first_name", "last_name", "active_status"}
    assert repo.calls == ["read_personnel_master_validated"]


def test_r2fa_10_no_driver_relationship_in_r2f_a() -> None:
    from app.api.v1 import relationship_routes, relationship_schemas
    from app.domain import personnel_relationship

    for module in (personnel_relationship, relationship_routes, relationship_schemas):
        source = inspect.getsource(module)
        assert "driver_id" not in source and "app.domain.driver" not in source
        assert not [name for name in vars(module) if "driver" in name.lower()]
    from app.api.v1.relationship_schemas import PersonnelRelationshipsResponse

    assert set(PersonnelRelationshipsResponse.model_fields) == {"personnel_id", "technician", "account"}
