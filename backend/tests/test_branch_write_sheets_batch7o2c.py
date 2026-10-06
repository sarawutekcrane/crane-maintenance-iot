"""Phase 7 Batch 7O2c — responsible-branch writes over Google Sheets, exercised
with the REAL installed gspread client on the 7H2 WRITABLE FAKE transport
(`WritableBackend`, imported unchanged): an emulation, not live Google Sheets.
No credentials, no network, no live workbook. Every fixture is synthetic (the
mock seed laid out as tabs).

Acceptance rows: B-10 (interleaved transfers both pass; the later read shows
the result), B-12 / C-c7 (a branch-only vehicle master), B-16 (mock/fake
parity), targeted cells after a header reorder, byte-exact text, an empty cell
for a cleared master, the missing-column refusal before any write, W1/W2
failure classification without retry, and the request counts of each path.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.branch_timeline import ASSET_BRANCH_HISTORY_COLUMNS, validate_branch_row
from app.repositories.mock import MockRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import VEHICLE_TAB, _repo
from tests.test_registry_read_sheets_batch7o2a import ABH_TAB, BRANCH_TAB, _seed_backend
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend

API = "/api/v1"
BATCH = "MOCK-7O2B-SYNTHETIC"  # same batch as the mock, for parity
LAEM, BANGNA, RAYONG = "BR-LAEM-CHABANG", "BR-BANGNA-KM6", "BR-RAYONG"
E_LATEST = "ABH-" + "a" * 31 + "1"
E_INSERTED = "ABH-" + "a" * 31 + "2"


def _settings() -> Settings:
    return Settings(
        data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
        google_application_credentials="fake.json", registry_data_context="TEST", registry_test_batch_id=BATCH,
    )


def _backend() -> WritableBackend:
    return WritableBackend(copy.deepcopy(_seed_backend().tabs))


async def _http(repo, method: str, path: str, *, json_body=None, request_id: str | None = None, sheets: bool = True):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if sheets:
        app.dependency_overrides[get_settings_dependency] = _settings
    headers = {"X-Dev-Role": "MAINTENANCE_MANAGER"}
    if method != "GET":
        headers["X-Request-Id"] = request_id or str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, json=json_body)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _table(backend: WritableBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _vehicle(backend: WritableBackend, vid: str) -> dict[str, str]:
    return next(r for r in _table(backend, VEHICLE_TAB) if r["vehicle_id"] == vid)


def _writes(backend: WritableBackend) -> list[str]:
    return [w["kind"] for w in backend.write_log]


async def _history(repo, vid="VEH-1046", sheets=True) -> dict:
    response = await _http(repo, "GET", f"{API}/vehicles/{vid}/branch-history", sheets=sheets)
    assert response.status_code == 200, response.text
    return response.json()


async def _transfer_body(repo, vid="VEH-1046", to=RAYONG, effective=None, sheets=True, **extra) -> dict:
    h = await _history(repo, vid, sheets)
    return {"to_branch_id": to, "effective": effective or {"mode": "DATE", "date": "2026-09-15"},
            "expected_current_branch_id": h["current"]["branch_id"], "expected_history_revision": h["history_revision"], **extra}


async def _edit_body(repo, vid="VEH-1046", sheets=True, **fields) -> dict:
    h = await _history(repo, vid, sheets)
    return {"reason_th": "ทดสอบ", "expected_history_revision": h["history_revision"],
            "expected_master_branch_id": h["master"]["value"], **fields}


# ---------------------------------------------------------------------------
# Payloads and targeted cells
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfer_sends_one_append_then_one_targeted_batch_update() -> None:
    backend = _backend()
    repo = _repo(backend)
    rid = str(uuid.uuid4())
    response = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers",
                           json_body=await _transfer_body(repo, note_th="=SUM(1) 0012"), request_id=rid)
    assert response.status_code == 200, response.text
    assert response.json()["projection_write"] == "WRITTEN"
    assert _writes(backend) == ["append", "batchUpdate"]
    append, update = backend.write_log
    assert append["tab"] == ABH_TAB and append["valueInputOption"] == "USER_ENTERED"
    sent = dict(zip(ASSET_BRANCH_HISTORY_COLUMNS, append["values"]))
    assert all(v == "" or v.startswith("'") for v in sent.values()), sent  # every non-empty cell text-forced
    assert sent["note_th"] == "'=SUM(1) 0012" and sent["request_id"] == f"'{rid}"
    targeted = {d["range"].split("!")[0].strip("'") for d in update["data"]}
    assert targeted == {VEHICLE_TAB}
    assert len(update["data"]) == 2  # responsible_branch_id + updated_at only
    stored = _table(backend, ABH_TAB)[-1]
    assert stored["note_th"] == "=SUM(1) 0012" and validate_branch_row(stored) == []
    assert _vehicle(backend, "VEH-1046")["responsible_branch_id"] == RAYONG
    assert (await _history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_targeted_cells_after_a_header_reorder() -> None:
    backend = _backend()
    tab = backend.tabs[VEHICLE_TAB]
    head = tab[0]
    order = list(reversed(range(len(head))))
    backend.tabs[VEHICLE_TAB] = [[row[i] if i < len(row) else "" for i in order] for row in tab]
    history = backend.tabs[ABH_TAB]
    hhead = history[0]
    horder = list(reversed(range(len(hhead))))
    backend.tabs[ABH_TAB] = [[row[i] if i < len(row) else "" for i in horder] for row in history]
    repo = _repo(backend)
    before = {k: v for k, v in _vehicle(backend, "VEH-1046").items() if k not in ("responsible_branch_id", "updated_at")}
    response = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers", json_body=await _transfer_body(repo))
    assert response.status_code == 200, response.text
    after = _vehicle(backend, "VEH-1046")
    assert after["responsible_branch_id"] == RAYONG
    assert {k: v for k, v in after.items() if k not in ("responsible_branch_id", "updated_at")} == before
    stored = _table(backend, ABH_TAB)[-1]  # appended under the tab's own header order
    assert validate_branch_row(stored) == [] and stored["branch_id"] == RAYONG
    assert (await _history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_cancelling_to_a_baseline_none_writes_an_empty_cell() -> None:
    backend = _backend()
    for row in backend.tabs[VEHICLE_TAB][1:]:
        if row[0] == "VEH-1047":
            row[backend.tabs[VEHICLE_TAB][0].index("responsible_branch_id")] = ""
    repo = _repo(backend)
    first = await _http(repo, "POST", f"{API}/vehicles/VEH-1047/branch-transfers",
                        json_body=await _transfer_body(repo, "VEH-1047", effective={"mode": "DATE", "date": "2026-09-20"}))
    assert first.status_code == 200, first.text
    event = first.json()["event_id"]
    backend.write_log.clear()
    response = await _http(repo, "POST", f"{API}/vehicles/VEH-1047/branch-history/events/{event}/cancellations",
                           json_body=await _edit_body(repo, "VEH-1047"))
    assert response.status_code == 200, response.text
    by_value = [d["values"][0][0] for d in backend.write_log[1]["data"]]
    assert "" in by_value and "'" not in by_value
    assert _vehicle(backend, "VEH-1047")["responsible_branch_id"] == ""
    assert (await _history(repo, "VEH-1047"))["current"] == {"branch_id": None, "source": "NONE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["  นำหน้า", "ท้าย  ", "0012", "+66", "TRUE", "'quoted", "a\nb", "ไทย ๑๒๓"])
async def test_reason_text_is_byte_exact_after_write_and_read(text) -> None:
    backend = _backend()
    repo = _repo(backend)
    response = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-history/events/{E_INSERTED}/cancellations",
                           json_body=await _edit_body(repo, reason_th=text))
    assert response.status_code == 200, response.text
    record = next(r for r in (await _history(repo))["records"] if r["record_id"] == response.json()["record_id"])
    assert record["reason_th"] == text


# ---------------------------------------------------------------------------
# B-12 / C-c7 branch-only master; missing column
# ---------------------------------------------------------------------------


def _drop_columns(backend: WritableBackend, names: tuple[str, ...]) -> None:
    tab = backend.tabs[VEHICLE_TAB]
    keep = [i for i, h in enumerate(tab[0]) if h not in names]
    backend.tabs[VEHICLE_TAB] = [[row[i] if i < len(row) else "" for i in keep] for row in tab]


@pytest.mark.asyncio
async def test_b12_branch_only_master_supports_every_branch_mutation() -> None:
    backend = _backend()
    _drop_columns(backend, ("registration_no", "registration_province_code"))
    repo = _repo(backend)
    base = f"{API}/vehicles/VEH-1046"
    steps = [
        (f"{base}/branch-transfers", lambda: _transfer_body(repo, effective={"mode": "DATE", "date": "2026-09-10"})),
        (f"{base}/branch-history/insertions", lambda: _edit_body(repo, to_branch_id=LAEM, effective={"mode": "DATE", "date": "2026-08-05"})),
        (f"{base}/branch-history/events/{E_INSERTED}/corrections",
         lambda: _edit_body(repo, to_branch_id=BANGNA, effective={"mode": "DATE", "date": "2026-08-24"})),
        (f"{base}/branch-history/events/{E_LATEST}/cancellations", lambda: _edit_body(repo)),
    ]
    for path, build in steps:
        body = await build()
        if path.endswith("insertions"):
            body.pop("expected_master_branch_id")
        response = await _http(repo, "POST", path, json_body=body)
        assert response.status_code == 200, (path, response.text)
    # a hand edit, then reconciliation
    tab = backend.tabs[VEHICLE_TAB]
    col = tab[0].index("responsible_branch_id")
    next(r for r in tab[1:] if r[0] == "VEH-1046")[col] = LAEM
    response = await _http(repo, "POST", f"{base}/branch-projection/reconciliations", json_body=await _edit_body(repo))
    assert response.status_code == 200, response.text
    assert (await _history(repo))["consistency"] == "CONSISTENT"
    registration = await _http(repo, "PATCH", f"{base}/registration", json_body={
        "registration_no": "1", "registration_province_code": None,
        "expected_registration_no": None, "expected_registration_province_code": None})
    assert (registration.status_code, registration.json()["error"]["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_missing_branch_column_is_refused_before_any_write_request() -> None:
    backend = _backend()
    repo = _repo(backend)
    body = await _transfer_body(repo)
    _drop_columns(backend, ("responsible_branch_id",))
    response = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers", json_body=body)
    assert (response.status_code, response.json()["error"]["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_c_c8_branch_master_without_is_active_column() -> None:
    backend = _backend()
    tab = backend.tabs[BRANCH_TAB]
    keep = [i for i, h in enumerate(tab[0]) if h != "is_active"]
    backend.tabs[BRANCH_TAB] = [[row[i] for i in keep] for row in tab]
    repo = _repo(backend)
    for to in (RAYONG, BANGNA):
        response = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers",
                               json_body=await _transfer_body(repo, to=to, effective={"mode": "DATE", "date": f"2026-09-1{5 if to == RAYONG else 6}"}))
        assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Failures and request counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,mode,code,outcome",
    [
        ("append", "reject", "BRANCH_HISTORY_WRITE_FAILED", "rejected"),
        ("append", "server_error", "BRANCH_HISTORY_WRITE_FAILED", "unknown"),
        ("append", "apply_then_timeout", "BRANCH_HISTORY_WRITE_FAILED", "unknown"),
        ("batchUpdate", "reject", "BRANCH_PROJECTION_WRITE_FAILED", "rejected"),
        ("batchUpdate", "server_error", "BRANCH_PROJECTION_WRITE_FAILED", "unknown"),
        ("batchUpdate", "apply_then_timeout", "BRANCH_PROJECTION_WRITE_FAILED", "unknown"),
    ],
)
async def test_write_failures_are_classified_and_never_retried(kind, mode, code, outcome) -> None:
    backend = _backend()
    repo = _repo(backend)
    body = await _transfer_body(repo)
    backend.fail[kind] = mode
    rid = str(uuid.uuid4())
    response = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers", json_body=body, request_id=rid)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == code and error["request_id"] == rid
    key = "history_write_outcome" if kind == "append" else "projection_write_outcome"
    assert error["details"][key] == outcome
    assert _writes(backend) == (["append"] if kind == "append" else ["append", "batchUpdate"])
    backend.fail[kind] = None
    history = await _history(repo)
    applied_history = kind == "batchUpdate" or mode == "apply_then_timeout"
    applied_master = kind == "batchUpdate" and mode == "apply_then_timeout"
    assert any(r["request_id"] == rid for r in history["records"]) is applied_history
    assert history["consistency"] == ("CONSISTENT" if applied_master or not applied_history else "PROJECTION_MISMATCH")


@pytest.mark.asyncio
async def test_request_counts_per_path() -> None:
    backend = _backend()
    repo = _repo(backend)
    base = f"{API}/vehicles/VEH-1046"
    cases = [
        # (path, body builder, values reads, writes)
        (f"{base}/branch-transfers", lambda: _transfer_body(repo, to=LAEM), 2, []),  # no-op: R1 + R2
        (f"{base}/branch-transfers", lambda: _transfer_body(repo), 3, ["append", "batchUpdate"]),  # R1 R2 R3 W1 W2
        # 7O2c R1: a time-only correction keeps the destination: R1 + R2, no R3
        (f"{base}/branch-history/events/{E_INSERTED}/corrections",
         lambda: _edit_body(repo, to_branch_id=BANGNA, effective={"mode": "DATE", "date": "2026-08-22"}), 2, ["append"]),
        # a destination-changing correction: R1 + R2 + R3
        (f"{base}/branch-history/events/{E_INSERTED}/corrections",
         lambda: _edit_body(repo, to_branch_id=RAYONG, effective={"mode": "DATE", "date": "2026-08-22"}), 3, ["append"]),
        (f"{base}/branch-history/events/{E_INSERTED}/cancellations", lambda: _edit_body(repo), 2, ["append"]),  # no R3
        (f"{base}/branch-projection/reconciliations", lambda: _edit_body(repo), 2, []),  # CONSISTENT: no-op
    ]
    for path, build, reads, writes in cases:
        body = await build()
        backend.requests.clear()
        backend.write_log.clear()
        response = await _http(repo, "POST", path, json_body=body)
        assert response.status_code == 200, (path, response.text)
        assert backend.values_reads() == reads, (path, backend.requests)
        assert _writes(backend) == writes, path
        assert backend.values_reads(BRANCH_TAB) == (1 if reads == 3 else 0)


@pytest.mark.asyncio
async def test_b10_interleaved_transfers_both_pass_and_the_later_read_shows_the_result() -> None:
    """Two transfers prepared from the same revision: the second is checked
    against a snapshot taken before the first wrote (the documented race of
    §6.7); both are recorded, and the next read shows what the history says."""
    backend = _backend()
    repo = _repo(backend)
    first = await _transfer_body(repo, to=RAYONG, effective={"mode": "DATE", "date": "2026-09-10"})
    second = await _transfer_body(repo, to=BANGNA, effective={"mode": "DATE", "date": "2026-09-12"})
    snapshot = copy.deepcopy(backend.tabs)
    a = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers", json_body=first)
    assert a.status_code == 200, a.text
    live = backend.tabs
    stale_reads = {ABH_TAB: snapshot[ABH_TAB], VEHICLE_TAB: snapshot[VEHICLE_TAB]}
    original_get = repo.read_asset_branch_history_validated
    original_master = repo.read_vehicle_branch_master

    async def stale_history():
        backend.tabs = {**live, ABH_TAB: stale_reads[ABH_TAB]}
        try:
            return await original_get()
        finally:
            backend.tabs = live

    async def stale_master(vehicle_id):
        backend.tabs = {**live, VEHICLE_TAB: stale_reads[VEHICLE_TAB]}
        try:
            return await original_master(vehicle_id)
        finally:
            backend.tabs = live

    repo.read_asset_branch_history_validated = stale_history  # type: ignore[method-assign]
    repo.read_vehicle_branch_master = stale_master  # type: ignore[method-assign]
    b = await _http(repo, "POST", f"{API}/vehicles/VEH-1046/branch-transfers", json_body=second)
    assert b.status_code == 200, b.text
    del repo.read_asset_branch_history_validated, repo.read_vehicle_branch_master
    history = await _history(repo)
    ids = {r["request_id"] for r in history["records"]}
    assert {a.headers["X-Request-Id"], b.headers["X-Request-Id"]} <= ids
    assert history["current"]["branch_id"] == BANGNA and history["consistency"] == "CONSISTENT"


# ---------------------------------------------------------------------------
# B-16 mock / fake parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b16_mock_and_fake_give_identical_results() -> None:
    backend = _backend()
    fake = _repo(backend)
    mock = MockRepository()
    base = f"{API}/vehicles/VEH-1046"

    def shape(response) -> tuple:
        body = response.json()
        if "error" in body:
            details = {k: v for k, v in (body["error"]["details"] or {}).items() if k not in ("request_id", "record_id")}
            return response.status_code, body["error"]["code"], details
        return response.status_code, body.get("changed"), body.get("projection_write"), body.get("current_branch_id"), body.get("consistency")

    steps = [
        ("transfer", f"{base}/branch-transfers", {"to_branch_id": RAYONG, "effective": {"mode": "DATE", "date": "2026-09-15"}}),
        ("transfer", f"{base}/branch-transfers", {"to_branch_id": RAYONG, "effective": {"mode": "DATE", "date": "2026-09-16"}}),  # no-op
        ("transfer", f"{base}/branch-transfers", {"to_branch_id": "BR-NOPE", "effective": {"mode": "DATE", "date": "2026-09-16"}}),
        ("transfer", f"{base}/branch-transfers", {"to_branch_id": LAEM, "effective": {"mode": "DATE", "date": "2026-08-25"}}),
        ("edit", f"{base}/branch-history/insertions", {"to_branch_id": LAEM, "effective": {"mode": "DATE", "date": "2026-08-05"}}),
        ("edit", f"{base}/branch-history/events/{E_INSERTED}/corrections",
         {"to_branch_id": RAYONG, "effective": {"mode": "DATE", "date": "2026-08-24"}}),
        ("edit", f"{base}/branch-history/events/{E_LATEST}/cancellations", {}),
        ("edit", f"{base}/branch-history/events/{E_LATEST}/cancellations", {}),  # already cancelled
        ("edit", f"{base}/branch-projection/reconciliations", {}),
        ("edit", f"{API}/vehicles/VEH-NONE/branch-projection/reconciliations", {}),
    ]
    for kind, path, fields in steps:
        results = []
        for repo, sheets in ((fake, True), (mock, False)):
            if kind == "transfer":
                body = await _transfer_body(repo, sheets=sheets, **{k: v for k, v in fields.items() if k != "to_branch_id"},
                                            to=fields["to_branch_id"])
                body["effective"] = fields["effective"]
            elif "VEH-NONE" in path:
                body = {"reason_th": "x", "expected_history_revision": "BHR1-0", "expected_master_branch_id": None}
            else:
                body = {**(await _edit_body(repo, sheets=sheets)), **fields}
                if path.endswith("insertions"):
                    body.pop("expected_master_branch_id")
            results.append(shape(await _http(repo, "POST", path, json_body=body, sheets=sheets)))
        assert results[0] == results[1], (path, fields, results)
    ha, hb = await _history(fake), await _history(mock, sheets=False)
    strip = lambda h: (h["current"], h["consistency"], h["timeline_status"], h["master"],  # noqa: E731
                       [(e["to_branch_id"], e["effective_at"], e["in_force"]) for e in h["events"]])
    assert strip(ha) == strip(hb)
