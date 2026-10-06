"""R2 Batch R2b — equipment branch history over Google Sheets, exercised with
the REAL installed gspread client on the 7B2 FAKE HTTP transport
(`FakeSheetsBackend`): an emulation, not live Google Sheets. No credentials,
no network, no live workbook. Request counts are fake-transport counts, not
live latency or quota figures. Every fixture is synthetic.

Batch-local PROPOSED ids: R2B-03/04 (fake), R2B-13, R2B-14, R2B-16, R2B-19.
"""
from __future__ import annotations

import copy

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.branch_timeline import ASSET_BRANCH_HISTORY_COLUMNS
from app.repositories.google_sheets import schemas
from tests.test_equipment_branch_history_batch_r2b import (
    EQP,
    MIXED,
    NOT_IN_SCHEMA,
    Spy,
    assigned_then_cancelled,
    same_instant,
    transfer_insert_correct,
)
from tests.test_equipment_branch_history_batch_r2b import get as mock_get
from tests.test_equipment_text_preservation_sheets_batch7k2 import EQ_HEADER, eq_row
from tests.test_fleet_status_summary_sheets_batch7b2 import (
    FakeSheetsBackend,
    _FakeResponse,
    _repo,
)

API = "/api/v1"
EQ_TAB = schemas.EQUIPMENT_SHEET.tab_name
ABH_TAB = "asset_branch_history"
ABH_HEADER = list(ASSET_BRANCH_HISTORY_COLUMNS)
PATH = f"{API}/equipment/{EQP}/branch-history"


def _settings(context: str | None = "TEST") -> Settings:
    values = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake-sheet-id",
              "google_application_credentials": "fake.json"}
    if context:
        values["registry_data_context"] = context
    return Settings(**values)


def _abh(rows: list[dict[str, str]], header: list[str] | None = None) -> list[list[str]]:
    header = header or ABH_HEADER
    return [list(header), *([row.get(h, "") for h in header] for row in rows)]


def _equipment_tab(*ids: str, header: list[str] | None = None, extra: dict[str, str] | None = None) -> list[list[str]]:
    header = list(header or EQ_HEADER)
    rows = [eq_row(eid=eid, code=f"EC-{i}", name="เครื่องกลึง (ข้อมูลสังเคราะห์)") for i, eid in enumerate(ids)]
    if extra:
        header = [*header, *extra]
        rows = [[*row, *extra.values()] for row in rows]
    return [header, *rows]


class FailingTabBackend(FakeSheetsBackend):
    """Fails values reads of the named tabs only (5xx), so a failure of one
    tab can be told apart from a failure of another."""

    def __init__(self, tabs, fail_tabs=()) -> None:
        super().__init__(tabs)
        self.fail_tabs = set(fail_tabs)

    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None, timeout=None):
        match = self._VALUES_RE.search(url)
        if method.lower() == "get" and match:
            from urllib.parse import unquote

            tab = unquote(match.group(2)).partition("!")[0].strip("'")
            if tab in self.fail_tabs:
                self.requests.append(("get", "values", tab))
                return _FakeResponse({"error": {"code": 500, "message": "backend error", "status": "INTERNAL"}}, 500)
        return super().request(method, url, json=json, params=params, data=data, files=files, headers=headers,
                               timeout=timeout)


def _backend(rows=(), *, equipment=(EQP, "EQP-0002"), fail_tabs=(), **tab_overrides) -> FailingTabBackend:
    tabs = {EQ_TAB: _equipment_tab(*equipment), ABH_TAB: _abh(list(rows))}
    tabs.update(tab_overrides)
    return FailingTabBackend(copy.deepcopy(tabs), fail_tabs)


async def _http(repo, path: str = PATH, settings: Settings | None = None):
    from app.config import get_settings
    from app.dependencies import (
        get_repository,
        get_settings_dependency,
        reset_dependency_cache,
    )
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_settings_dependency] = lambda: settings or _settings()
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _error(response) -> dict:
    return response.json()["error"]


# ---------------------------------------------------------------------------
# R2B-03 / R2B-04 (fake transport)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("not-found", 404, "EQUIPMENT_NOT_FOUND"),
        ("ambiguous", 409, "EQUIPMENT_ID_AMBIGUOUS"),
        ("tab-missing", 500, "EQUIPMENT_MASTER_SCHEMA_INVALID"),
        ("header-missing", 500, "EQUIPMENT_MASTER_SCHEMA_INVALID"),
        ("record-invalid", 500, "EQUIPMENT_MASTER_DATA_INVALID"),
        ("read-failed", 503, "EQUIPMENT_MASTER_READ_FAILED"),
    ],
)
async def test_r2b_03_equipment_lookup_errors_over_sheets(case, status, code) -> None:
    rows = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    if case == "not-found":
        backend = _backend(rows, equipment=("EQP-0002",))
    elif case == "ambiguous":
        backend = _backend(rows, equipment=(EQP, EQP))
    elif case == "tab-missing":
        backend = _backend(rows)
        del backend.tabs[EQ_TAB]
    elif case == "header-missing":
        backend = _backend(rows, **{EQ_TAB: _equipment_tab(EQP, header=[h if h != "equipment_status" else "status"
                                                                          for h in EQ_HEADER])})
    elif case == "record-invalid":
        tab = _equipment_tab(EQP)
        tab[1][3] = "Lathe"  # unrecognized equipment_type (7K2 record gate)
        backend = _backend(rows, **{EQ_TAB: tab})
    else:
        backend = _backend(rows, fail_tabs={EQ_TAB})
    response = await _http(_repo(backend))
    assert response.status_code == status and _error(response)["code"] == code
    assert backend.values_reads(ABH_TAB) == 0  # history never read after a failed lookup
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("tab-missing", 500, "BRANCH_HISTORY_SCHEMA_INVALID"),
        ("no-header-row", 500, "BRANCH_HISTORY_SCHEMA_INVALID"),
        ("legacy-9-column-header", 500, "BRANCH_HISTORY_SCHEMA_INVALID"),
        ("read-failed", 503, "BRANCH_HISTORY_READ_FAILED"),
    ],
)
async def test_r2b_04_history_failure_over_sheets_is_coded_never_empty(case, status, code) -> None:
    rows = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    if case == "tab-missing":
        backend = _backend(rows)
        del backend.tabs[ABH_TAB]
    elif case == "no-header-row":
        backend = _backend(rows, **{ABH_TAB: None})
    elif case == "legacy-9-column-header":
        backend = _backend(rows, **{ABH_TAB: _abh(rows, ABH_HEADER[:9])})  # the live workbook's old shape
    else:
        backend = _backend(rows, fail_tabs={ABH_TAB})
    response = await _http(_repo(backend))
    assert response.status_code == status and _error(response)["code"] == code
    assert _error(response)["details"]["tab"] == ABH_TAB
    assert "records" not in response.text
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r2b_03_context_unset_is_503_before_any_sheets_request() -> None:
    backend = _backend(transfer_insert_correct("EQUIPMENT", EQP, "E1"))
    response = await _http(_repo(backend), settings=_settings(context=None))
    assert response.status_code == 503 and _error(response)["code"] == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert backend.requests == []


# ---------------------------------------------------------------------------
# R2B-13 / R2B-16 — cost, no branch_master read, no writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2b_13_r2b_16_request_cost_cold_and_warm() -> None:
    # No branch_master tab exists at all: the route must never ask for it.
    backend = _backend(transfer_insert_correct("EQUIPMENT", EQP, "E1"))
    assert "branch_master" not in backend.tabs
    repo = _repo(backend)
    measured = {}
    for phase in ("cold", "warm"):
        backend.requests.clear()
        response = await _http(repo)
        assert response.status_code == 200
        measured[phase] = (backend.metadata_reads(), backend.values_reads())
        assert backend.values_reads(EQ_TAB) == 1 and backend.values_reads(ABH_TAB) == 1
        assert backend.values_reads("branch_master") == 0 and backend.values_reads("maintenance_plan") == 0
    # (metadata reads, values reads): the same as the vehicle branch-history route.
    assert measured == {"cold": (3, 2), "warm": (0, 2)}
    assert backend.writes == []


# ---------------------------------------------------------------------------
# R2B-14 — mock / fake parity
# ---------------------------------------------------------------------------


PARITY = {
    "mixed-assets": (MIXED, EQP),
    "no-history": ([], EQP),
    "all-cancelled": (assigned_then_cancelled("EQUIPMENT", "EQP-0002", "E2"), "EQP-0002"),
    "imported-baseline": (assigned_then_cancelled("EQUIPMENT", EQP, "E5", baseline=("BR-BANGNA-KM6", "IMPORTED_MASTER")),
                          EQP),
    "ambiguous": (same_instant("EQUIPMENT", EQP, "E3"), EQP),
    "malformed-type": ([{**transfer_insert_correct("EQUIPMENT", EQP, "E1")[0], "asset_type": "equipment"}], EQP),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(PARITY))
async def test_r2b_14_mock_and_fake_sheets_agree(case) -> None:
    rows, equipment_id = PARITY[case]
    path = f"{API}/equipment/{equipment_id}/branch-history"
    mock = await mock_get(path, Spy(copy.deepcopy(rows)))
    backend = _backend(rows)
    fake = await _http(_repo(backend), path)
    assert (fake.status_code, _comparable(fake)) == (mock.status_code, _comparable(mock))
    assert backend.writes == []


def _comparable(response) -> dict:
    """The body without the per-request error request_id."""
    body = response.json()
    if "error" in body:
        body["error"].pop("request_id", None)
    return body


# ---------------------------------------------------------------------------
# R2B-19 — an unapproved projection-like column is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], transfer_insert_correct("EQUIPMENT", EQP, "E1")], ids=["no-history", "history"])
async def test_r2b_19_extra_responsible_branch_column_is_ignored(rows) -> None:
    tab = _equipment_tab(EQP, extra={"responsible_branch_id": "BR-RAYONG"})
    backend = _backend(rows, **{EQ_TAB: tab})
    body = (await _http(_repo(backend))).json()
    assert body["master"] == NOT_IN_SCHEMA
    assert body["current"]["branch_id"] != "BR-RAYONG"
    if rows:
        assert body["current"] == {"branch_id": "BR-LAEM-CHABANG", "source": "EVENT"}
        assert body["consistency"] == "UNDETERMINED"
    else:
        assert body["current"] == {"branch_id": None, "source": "UNDETERMINED"}
        assert body["consistency"] == "NO_HISTORY"
    plain = await _http(_repo(_backend(rows)))
    assert body == plain.json()  # the extra column changes nothing
