"""Phase 7 Batch 7O2d — I-02: measured request costs of every R1 registry/branch
path versus Final Rev2 §6.8, with the REAL installed gspread client on the 7H2
WRITABLE FAKE transport (an emulation, not live Google Sheets; no credentials,
no network). The fixture is the mock seed laid out as tabs, plus the detail
page's model/plan/component tabs. Synthetic data only.

Every measurement separates:
  - values reads (spreadsheets.values.get), per tab;
  - metadata requests (spreadsheets.get);
  - append writes (values.append, W1);
  - targeted cell writes (values.batchUpdate, W2).

"Warm" = the client has already fetched the worksheet list and every tab the
operation touches in this process (the steady state). "Cold" = a brand-new
repository / client: the first request of a process.

Accepted R1 clarification (7O2c R1): a time-only correction (same destination)
skips the branch_master read (R3): 2 reads; a new destination reads it: 3.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from tests.test_fleet_status_summary_sheets_batch7b2 import VEHICLE_TAB, _repo
from tests.test_registry_read_sheets_batch7o2a import ABH_TAB, BRANCH_TAB, PROVINCE_TAB, VRH_TAB, _detail_tabs, _seed_backend
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend

API = "/api/v1"
BATCH = "MOCK-7O2B-SYNTHETIC"
LAEM, BANGNA, RAYONG = "BR-LAEM-CHABANG", "BR-BANGNA-KM6", "BR-RAYONG"
E_LATEST = "ABH-" + "a" * 31 + "1"
E_INSERTED = "ABH-" + "a" * 31 + "2"
MODEL_TAB = "model_master"


def _settings() -> Settings:
    return Settings(
        data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
        google_application_credentials="fake.json", registry_data_context="TEST", registry_test_batch_id=BATCH,
    )


def _backend() -> WritableBackend:
    tabs = copy.deepcopy(_seed_backend().tabs)
    detail = _detail_tabs()
    tabs["maintenance_plan"] = detail["maintenance_plan"]
    tabs["vehicle_component"] = detail["vehicle_component"]
    return WritableBackend(tabs)


async def _http(repo, method: str, path: str, *, json_body=None, params=None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_settings_dependency] = _settings
    headers = {"X-Dev-Role": "MAINTENANCE_MANAGER"}
    if method != "GET":
        headers["X-Request-Id"] = str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, json=json_body, params=params)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


@dataclass(frozen=True)
class Cost:
    values: int
    appends: int = 0
    batch_updates: int = 0
    metadata: int = 0


class Harness:
    def __init__(self) -> None:
        self.backend = _backend()
        self.repo = _repo(self.backend)

    def set_cell(self, tab: str, vehicle_id: str, column: str, value: str) -> None:
        rows = self.backend.tabs[tab]
        col = rows[0].index(column)
        for row in rows[1:]:
            if row and row[0] == vehicle_id:
                while len(row) <= col:
                    row.append("")
                row[col] = value
                return
        raise KeyError(vehicle_id)

    async def get(self, path: str, params=None) -> dict:
        response = await _http(self.repo, "GET", f"{API}/{path}", params=params)
        assert response.status_code == 200, (path, response.text)
        return response.json()

    async def warm(self) -> None:
        """Touch every tab once (worksheet list + each tab cached)."""
        await self.get("vehicles", {"q": "TC"})
        await self.get("vehicles/VEH-1046")
        for path in ("branches", "provinces", "vehicles/VEH-1046/branch-history", "vehicles/VEH-1046/registration-history"):
            await self.get(path)

    async def measure(self, method: str, path: str, *, body=None, params=None, status: int = 200) -> tuple[Cost, dict]:
        self.backend.requests.clear()
        self.backend.write_log.clear()
        response = await _http(self.repo, method, f"{API}/{path}", json_body=body, params=params)
        assert response.status_code == status, (path, response.text)
        kinds = [kind for _, kind, _ in self.backend.requests]
        cost = Cost(
            values=self.backend.values_reads(),
            appends=kinds.count("append"),
            batch_updates=kinds.count("batchUpdate"),
            metadata=self.backend.metadata_reads(),
        )
        tabs = {}
        for _, kind, tab in self.backend.requests:
            if kind == "values":
                tabs[tab] = tabs.get(tab, 0) + 1
        return cost, tabs

    # body builders from the current state (read before measuring)
    async def branch(self, vid: str = "VEH-1046") -> dict:
        return await self.get(f"vehicles/{vid}/branch-history")

    async def registration(self, vid: str = "VEH-1046") -> dict:
        return await self.get(f"vehicles/{vid}/registration-history")


def _date(d: str) -> dict:
    return {"mode": "DATE", "date": d}


# ---------------------------------------------------------------------------
# Warm (steady-state) costs, one assertion per §6.8 row
# ---------------------------------------------------------------------------

READS = [
    # (label, path, params, expected values reads)
    ("list", "vehicles", None, 1),
    ("list + status filter", "vehicles", {"status": "WORKING"}, 1),
    ("list + model filter", "vehicles", {"model_id": "MDL-1"}, 1),
    ("list + branch filter", "vehicles", {"branch_id": LAEM}, 1),
    ("list + usable q", "vehicles", {"q": "TC-12"}, 2),
    ("list + hyphen-only q", "vehicles", {"q": "-"}, 1),
    ("provinces", "provinces", None, 1),
    ("branches", "branches", None, 1),
    ("registration history", "vehicles/VEH-1046/registration-history", None, 2),
    ("branch history", "vehicles/VEH-1046/branch-history", None, 2),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("label,path,params,expected", READS, ids=[r[0] for r in READS])
async def test_i02_warm_read_costs(label, path, params, expected) -> None:
    h = Harness()
    await h.warm()
    cost, _ = await h.measure("GET", path, params=params)
    assert cost == Cost(values=expected), (label, cost)


@pytest.mark.asyncio
async def test_i02_vehicle_detail_registry_fields_add_no_vehicle_master_read() -> None:
    """GET /vehicles/{id}: one vehicle_master read serves the vehicle AND its
    registry fields; the other reads are the pre-existing detail reads
    (model, PM plans, components)."""
    h = Harness()
    await h.warm()
    cost, tabs = await h.measure("GET", "vehicles/VEH-1046")
    assert tabs.get(VEHICLE_TAB) == 1
    assert cost == Cost(values=sum(tabs.values()))
    assert tabs == {VEHICLE_TAB: 1, MODEL_TAB: 1, "maintenance_plan": 1, "vehicle_component": 1}
    detail = await h.get("vehicles/VEH-1046")
    assert detail["vehicle"]["registry"]["registration_no"] == {"state": "RECORDED", "value": "0012"}


# ---- registration mutations ------------------------------------------------


@pytest.mark.asyncio
async def test_i02_registration_change_costs() -> None:
    h = Harness()
    await h.warm()
    with_province = {"registration_no": "0099", "registration_province_code": "TH-10",
                     "expected_registration_no": "0012", "expected_registration_province_code": "TH-21"}
    cost, tabs = await h.measure("PATCH", "vehicles/VEH-1046/registration", body=with_province)
    assert cost == Cost(values=3, appends=1, batch_updates=1), cost
    assert tabs == {VEHICLE_TAB: 1, VRH_TAB: 1, PROVINCE_TAB: 1}
    without_province = {"registration_no": "0100", "registration_province_code": None,
                        "expected_registration_no": "0099", "expected_registration_province_code": "TH-10"}
    cost, tabs = await h.measure("PATCH", "vehicles/VEH-1046/registration", body=without_province)
    assert cost == Cost(values=2, appends=1, batch_updates=1), cost
    assert tabs == {VEHICLE_TAB: 1, VRH_TAB: 1}
    noop = {"registration_no": "0100", "registration_province_code": None,
            "expected_registration_no": "0100", "expected_registration_province_code": None}
    cost, _ = await h.measure("PATCH", "vehicles/VEH-1046/registration", body=noop)
    assert cost == Cost(values=2), cost


async def _reconcile(h: Harness, vid: str, mode: str) -> tuple[Cost, dict]:
    history = await h.registration(vid)
    detail = await h.get(f"vehicles/{vid}")
    reg = detail["vehicle"]["registry"]
    body = {"mode": mode, "reason_th": "วัดต้นทุน (ทดสอบ)", "expected_history_revision": history["history_revision"],
            "expected_registration_no": reg["registration_no"]["value"],
            "expected_registration_province_code": reg["registration_province"]["value"]}
    return await h.measure("POST", f"vehicles/{vid}/registration-history/reconciliations", body=body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,vid,master,mode,expected,tabs",
    [
        # ACCEPT_MASTER of a master pair with no province: no R3, W1 only
        ("accept, no province", "VEH-1046", ("0013", ""), "ACCEPT_MASTER", Cost(values=2, appends=1), {VEHICLE_TAB, VRH_TAB}),
        # ACCEPT_MASTER of a master pair with a province: R3 (exception check), W1 only
        ("accept, province", "VEH-1046", ("0013", "TH-21"), "ACCEPT_MASTER", Cost(values=3, appends=1),
         {VEHICLE_TAB, VRH_TAB, PROVINCE_TAB}),
        # APPLY_RECORDED of a recorded pair with a province: R3, W1 + W2
        ("apply, province", "VEH-1046", ("0013", "TH-21"), "APPLY_RECORDED", Cost(values=3, appends=1, batch_updates=1),
         {VEHICLE_TAB, VRH_TAB, PROVINCE_TAB}),
        # APPLY_RECORDED of a recorded CLEARED pair (VEH-1048): no R3, W1 + W2
        ("apply, cleared", "VEH-1048", ("ค้าง", ""), "APPLY_RECORDED", Cost(values=2, appends=1, batch_updates=1),
         {VEHICLE_TAB, VRH_TAB}),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
async def test_i02_registration_reconciliation_costs(case, vid, master, mode, expected, tabs) -> None:
    h = Harness()
    await h.warm()
    h.set_cell(VEHICLE_TAB, vid, "registration_no", master[0])
    h.set_cell(VEHICLE_TAB, vid, "registration_province_code", master[1])
    cost, touched = await _reconcile(h, vid, mode)
    assert cost == expected, (case, cost)
    assert set(touched) == tabs and all(n == 1 for n in touched.values()), touched


@pytest.mark.asyncio
async def test_i02_registration_reconciliation_noop_cost() -> None:
    h = Harness()
    await h.warm()
    cost, _ = await _reconcile(h, "VEH-1046", "APPLY_RECORDED")  # CONSISTENT: nothing to do
    assert cost == Cost(values=2), cost


# ---- branch mutations ------------------------------------------------------


async def _transfer(h: Harness, to: str, date: str) -> tuple[Cost, dict]:
    hist = await h.branch()
    body = {"to_branch_id": to, "effective": _date(date), "expected_current_branch_id": hist["current"]["branch_id"],
            "expected_history_revision": hist["history_revision"]}
    return await h.measure("POST", "vehicles/VEH-1046/branch-transfers", body=body)


async def _edit(h: Harness, path: str, **fields) -> tuple[Cost, dict]:
    hist = await h.branch()
    body = {"reason_th": "วัดต้นทุน (ทดสอบ)", "expected_history_revision": hist["history_revision"],
            "expected_master_branch_id": hist["master"]["value"], **fields}
    if path.endswith("insertions"):
        body.pop("expected_master_branch_id")
    return await h.measure("POST", f"vehicles/VEH-1046/{path}", body=body)


@pytest.mark.asyncio
async def test_i02_transfer_costs() -> None:
    h = Harness()
    await h.warm()
    cost, tabs = await _transfer(h, RAYONG, "2026-09-15")
    assert cost == Cost(values=3, appends=1, batch_updates=1), cost
    assert tabs == {VEHICLE_TAB: 1, ABH_TAB: 1, BRANCH_TAB: 1}
    cost, tabs = await _transfer(h, RAYONG, "2026-09-16")  # no-op: already Rayong
    assert cost == Cost(values=2), cost
    assert tabs == {VEHICLE_TAB: 1, ABH_TAB: 1}


@pytest.mark.asyncio
async def test_i02_insertion_cost() -> None:
    h = Harness()
    await h.warm()
    cost, tabs = await _edit(h, "branch-history/insertions", to_branch_id=RAYONG, effective=_date("2026-08-25"))
    assert cost == Cost(values=3, appends=1), cost  # projection NOT_NEEDED: never W2
    assert tabs == {VEHICLE_TAB: 1, ABH_TAB: 1, BRANCH_TAB: 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,event,to,date,expected",
    [
        # time-only (destination unchanged): no R3 (7O2c R1); projection unchanged → W1 only
        ("time-only, W1", E_INSERTED, BANGNA, "2026-08-22", Cost(values=2, appends=1)),
        # time-only on the latest event: master still equal → W1 only
        ("time-only latest, W1", E_LATEST, LAEM, "2026-09-02", Cost(values=2, appends=1)),
        # new destination on an older event: R3; current unchanged → W1 only
        ("new destination, W1", E_INSERTED, RAYONG, "2026-08-22", Cost(values=3, appends=1)),
        # new destination on the latest event: R3; current changes → W1 + W2
        ("new destination latest, W1+W2", E_LATEST, RAYONG, "2026-09-01", Cost(values=3, appends=1, batch_updates=1)),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
async def test_i02_correction_costs(case, event, to, date, expected) -> None:
    h = Harness()
    await h.warm()
    cost, tabs = await _edit(h, f"branch-history/events/{event}/corrections", to_branch_id=to, effective=_date(date))
    assert cost == expected, (case, cost)
    assert (BRANCH_TAB in tabs) is (expected.values == 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,event,expected",
    [("older event, W1", E_INSERTED, Cost(values=2, appends=1)),
     ("latest event, W1+W2", E_LATEST, Cost(values=2, appends=1, batch_updates=1))],
    ids=lambda v: v if isinstance(v, str) else None,
)
async def test_i02_cancellation_costs(case, event, expected) -> None:
    h = Harness()
    await h.warm()
    cost, tabs = await _edit(h, f"branch-history/events/{event}/cancellations")
    assert cost == expected, (case, cost)
    assert BRANCH_TAB not in tabs


@pytest.mark.asyncio
async def test_i02_projection_reconciliation_costs() -> None:
    h = Harness()
    await h.warm()
    cost, tabs = await _edit(h, "branch-projection/reconciliations")  # CONSISTENT: no-op
    assert cost == Cost(values=2), cost
    h.set_cell(VEHICLE_TAB, "VEH-1046", "responsible_branch_id", RAYONG)  # hand edit: PROJECTION_MISMATCH
    cost, tabs = await _edit(h, "branch-projection/reconciliations")
    assert cost == Cost(values=2, appends=1, batch_updates=1), cost
    assert tabs == {VEHICLE_TAB: 1, ABH_TAB: 1}  # never R3, even for an unknown historical code


# ---------------------------------------------------------------------------
# First use of a process (cold client): metadata requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,method,path,body_kind,tabs",
    [
        ("list", "GET", "vehicles", None, 1),
        ("branch history", "GET", "vehicles/VEH-1046/branch-history", None, 2),
        ("transfer", "POST", "vehicles/VEH-1046/branch-transfers", "transfer", 3),
        ("registration change", "PATCH", "vehicles/VEH-1046/registration", "registration", 3),
    ],
    ids=lambda v: v if isinstance(v, str) and " " not in v and "/" not in v else None,
)
async def test_i02_cold_metadata_is_one_plus_one_per_touched_tab(label, method, path, body_kind, tabs) -> None:
    """A brand-new client fetches the worksheet list once, then once more per
    newly touched tab; values reads and writes are the same as warm. A second
    identical request in the same process makes no metadata request."""
    body = None
    if body_kind == "transfer":
        warm_h = Harness()
        hist = await warm_h.branch()
        body = {"to_branch_id": RAYONG, "effective": _date("2026-09-15"), "expected_current_branch_id": hist["current"]["branch_id"],
                "expected_history_revision": hist["history_revision"]}
    elif body_kind == "registration":
        body = {"registration_no": "0099", "registration_province_code": "TH-10",
                "expected_registration_no": "0012", "expected_registration_province_code": "TH-21"}
    h = Harness()  # cold: nothing fetched yet
    cost, touched = await h.measure(method, path, body=body)
    assert len(touched) == tabs
    assert cost.metadata == 1 + tabs, (label, cost)
    assert cost.values == tabs
    if method == "GET":
        again, _ = await h.measure(method, path)
        assert again.metadata == 0 and again.values == tabs


# ---------------------------------------------------------------------------
# B-10 as worded in Final Rev2 §13.1: a projection reconciliation concurrent
# with a transfer (the 7O2c fake test covers two interleaved transfers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b10_reconciliation_concurrent_with_a_transfer_is_repaired_by_a_further_reconciliation() -> None:
    """Rec-A reads a mismatched state (history Laem, hand-edited master Rayong).
    Before Rec-A writes, Rec-B repairs the master and a transfer to Bangna is
    recorded. Rec-A then writes from its stale read: the master becomes Laem
    again while the history says Bangna. This is the disclosed race (§6.7; no
    conditional write in Sheets): it is visible as PROJECTION_MISMATCH on the
    next read, never hidden, and a further reconciliation repairs it."""
    h = Harness()
    await h.warm()
    h.set_cell(VEHICLE_TAB, "VEH-1046", "responsible_branch_id", RAYONG)
    hist = await h.branch()
    assert (hist["consistency"], hist["current"]["branch_id"]) == ("PROJECTION_MISMATCH", LAEM)
    rec_body = {"reason_th": "ปรับให้ตรง (ทดสอบ)", "expected_history_revision": hist["history_revision"],
                "expected_master_branch_id": RAYONG}
    stale = copy.deepcopy(h.backend.tabs)  # what Rec-A has read

    cost, _ = await h.measure("POST", "vehicles/VEH-1046/branch-projection/reconciliations", body=rec_body)  # Rec-B
    assert cost == Cost(values=2, appends=1, batch_updates=1)
    cost, _ = await _transfer(h, BANGNA, "2026-09-15")
    assert cost == Cost(values=3, appends=1, batch_updates=1)

    repo, backend = h.repo, h.backend
    read_master, read_history = repo.read_vehicle_branch_master, repo.read_asset_branch_history_validated

    async def stale_master(vehicle_id):
        live = backend.tabs
        backend.tabs = {**live, VEHICLE_TAB: stale[VEHICLE_TAB]}
        try:
            return await read_master(vehicle_id)
        finally:
            backend.tabs = live

    async def stale_history():
        live = backend.tabs
        backend.tabs = {**live, ABH_TAB: stale[ABH_TAB]}
        try:
            return await read_history()
        finally:
            backend.tabs = live

    repo.read_vehicle_branch_master = stale_master  # type: ignore[method-assign]
    repo.read_asset_branch_history_validated = stale_history  # type: ignore[method-assign]
    cost, _ = await h.measure("POST", "vehicles/VEH-1046/branch-projection/reconciliations", body=rec_body)  # Rec-A
    assert cost == Cost(values=2, appends=1, batch_updates=1)
    del repo.read_vehicle_branch_master, repo.read_asset_branch_history_validated

    after = await h.branch()
    assert (after["current"]["branch_id"], after["master"]["value"], after["consistency"]) == (BANGNA, LAEM, "PROJECTION_MISMATCH")
    repair = {"reason_th": "ปรับอีกครั้ง (ทดสอบ)", "expected_history_revision": after["history_revision"],
              "expected_master_branch_id": LAEM}
    cost, _ = await h.measure("POST", "vehicles/VEH-1046/branch-projection/reconciliations", body=repair)
    assert cost == Cost(values=2, appends=1, batch_updates=1)
    final = await h.branch()
    assert (final["current"]["branch_id"], final["master"]["value"], final["consistency"]) == (BANGNA, BANGNA, "CONSISTENT")
    assert sum(1 for r in final["records"] if r["record_kind"] == "PROJECTION_RECONCILIATION") == 3
