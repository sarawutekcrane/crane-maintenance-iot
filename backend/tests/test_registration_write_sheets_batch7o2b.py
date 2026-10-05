"""Phase 7 Batch 7O2b — registration writes over Google Sheets, exercised with
the REAL installed gspread client on the 7H2 WRITABLE FAKE transport
(`WritableBackend`, imported unchanged): an emulation, not live Google Sheets.
USER_ENTERED storage is the 7H2 simplified model (a leading apostrophe forces
text and is not stored; a plain number is stored as a number). No
credentials, no network, no live workbook. Every fixture is synthetic.

Acceptance rows: W-09 (targeted cells after a header reorder), W-10
(interleaved registrations of one pair), W-12 (byte-exact text after write and
read), the uniqueness scope over the R1 response (phantom rows, blank-id rows,
rows failing the record gates), C3 (a cleared value is an empty cell), the
missing-column refusal before any request, W1/W2 failure classification, the
request counts of each path, and mock/fake parity.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.registration import REGISTRATION_HISTORY_COLUMNS, registration_history_revision
from app.repositories.mock import MockRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import HEADER, TS, VEHICLE_TAB, _repo, _row
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend

API = "/api/v1"
VRH_TAB, PROVINCE_TAB = "vehicle_registration_history", "province_master"
REG_COLUMNS = ("registration_no", "registration_province_code", "responsible_branch_id")
PROVINCES = [
    ["province_code", "province_name_th", "is_active"],
    ["TH-10", "กรุงเทพมหานคร", "TRUE"],
    ["TH-20", "ชลบุรี", "TRUE"],
    ["TH-21", "ระยอง", "TRUE"],
    ["TH-76", "เพชรบุรี", "FALSE"],
]
BATCH = "FAKE-7O2B-BATCH"


def _settings() -> Settings:
    return Settings(
        data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
        google_application_credentials="fake.json", registry_data_context="TEST", registry_test_batch_id=BATCH,
    )


def _vehicle_tab(rows, columns=REG_COLUMNS, header=None) -> list[list[str]]:
    head = header or [*HEADER, *columns]
    out = [list(head)]
    for base, cells in rows:
        full = dict(zip(HEADER, base))
        full.update(cells)
        out.append([full.get(h, "") for h in head])
    return out


ROWS = [
    (_row("VEH-1", "WORKING"), {"registration_no": "0012", "registration_province_code": "TH-21", "responsible_branch_id": "BR-A"}),
    (_row("VEH-2", "READY"), {"registration_no": "กข-1234", "registration_province_code": "TH-20"}),
    (_row("VEH-3", "MAINTENANCE"), {}),
]


def _backend(rows=ROWS, *, columns=REG_COLUMNS, header=None, history=None, provinces=PROVINCES) -> WritableBackend:
    return WritableBackend({
        VEHICLE_TAB: _vehicle_tab(rows, columns, header),
        VRH_TAB: [list(REGISTRATION_HISTORY_COLUMNS), *(history or [])],
        PROVINCE_TAB: copy.deepcopy(provinces),
    })


async def _http(repo, method: str, path: str, *, json_body=None, request_id: str | None = None):
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
        headers["X-Request-Id"] = request_id or str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, json=json_body)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _body(no, pv, exp_no, exp_pv) -> dict:
    return {"registration_no": no, "registration_province_code": pv,
            "expected_registration_no": exp_no, "expected_registration_province_code": exp_pv}


def _cells(backend: WritableBackend, vid: str) -> dict[str, str]:
    rows = backend.tabs[VEHICLE_TAB]
    head = rows[0]
    at = head.index("vehicle_id")
    for row in rows[1:]:
        if len(row) > at and row[at] == vid:
            return {h: (row[i] if i < len(row) else "") for i, h in enumerate(head)}
    raise KeyError(vid)


def _history_rows(backend: WritableBackend) -> list[dict[str, str]]:
    head = backend.tabs[VRH_TAB][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[VRH_TAB][1:]]


def _writes(backend: WritableBackend) -> list[str]:
    return [w["kind"] for w in backend.write_log]


# ---------------------------------------------------------------------------
# Payloads: history-first, text forcing, C3 clearing, whitelist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_sends_one_append_then_one_targeted_batch_update() -> None:
    backend = _backend()
    repo = _repo(backend)
    response = await _http(repo, "PATCH", f"{API}/vehicles/VEH-2/registration", json_body=_body("0099", "TH-10", "กข-1234", "TH-20"))
    assert response.status_code == 200, response.text
    assert _writes(backend) == ["append", "batchUpdate"]  # W1 then W2
    append, update = backend.write_log
    assert append["tab"] == VRH_TAB and append["valueInputOption"] == "USER_ENTERED" and append["insertDataOption"] == "INSERT_ROWS"
    sent = dict(zip(REGISTRATION_HISTORY_COLUMNS, append["values"]))
    assert all(v == "" or v.startswith("'") for v in sent.values()), sent  # every non-empty cell text-forced
    assert sent["new_registration_no"] == "'0099" and sent["old_registration_no"] == "'กข-1234"
    assert sent["related_request_id"] == "" and sent["note_th"] == "" and sent["accepted_exceptions"] == ""
    assert sent["is_test_data"] == "'TRUE" and sent["test_batch_id"] == f"'{BATCH}"
    assert update["valueInputOption"] == "USER_ENTERED"
    # columns H, I = registration_no, registration_province_code; G = updated_at; row 3 = VEH-2
    by_col = {d["range"].split("!")[-1]: d["values"][0][0] for d in update["data"]}
    assert set(by_col) == {"H3", "I3", "G3"}
    assert by_col["H3"] == "'0099" and by_col["I3"] == "'TH-10"
    stored = _cells(backend, "VEH-2")
    assert (stored["registration_no"], stored["registration_province_code"]) == ("0099", "TH-10")
    assert stored["vehicle_id"] == "VEH-2" and stored["machine_no"] == "M-VEH-2"  # untouched
    history = (await _http(repo, "GET", f"{API}/vehicles/VEH-2/registration-history")).json()
    assert history["consistency"] == "CONSISTENT"
    assert history["items"][-1]["new_registration_no"] == "0099"


@pytest.mark.asyncio
async def test_c3_cleared_values_are_written_as_empty_cells_never_an_apostrophe() -> None:
    backend = _backend()
    repo = _repo(backend)
    response = await _http(repo, "PATCH", f"{API}/vehicles/VEH-1/registration", json_body=_body(None, None, "0012", "TH-21"))
    assert response.status_code == 200, response.text
    by_col = {d["range"].split("!")[-1]: d["values"][0][0] for d in backend.write_log[1]["data"]}
    assert by_col["H2"] == "" and by_col["I2"] == ""
    sent = dict(zip(REGISTRATION_HISTORY_COLUMNS, backend.write_log[0]["values"]))
    assert sent["new_registration_no"] == "" and sent["new_registration_province_code"] == ""
    stored = _cells(backend, "VEH-1")
    assert (stored["registration_no"], stored["registration_province_code"]) == ("", "")
    history = (await _http(repo, "GET", f"{API}/vehicles/VEH-1/registration-history")).json()
    assert history["current"]["registration_no"] == {"state": "NOT_RECORDED", "value": None}
    assert history["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["registration_no", "registration_province_code"])
async def test_missing_registration_column_is_refused_before_any_write_request(missing) -> None:
    columns = tuple(c for c in REG_COLUMNS if c != missing)
    backend = _backend(columns=columns)
    response = await _http(_repo(backend), "PATCH", f"{API}/vehicles/VEH-1/registration", json_body=_body("1", None, None, None))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "VEHICLE_MASTER_SCHEMA_INVALID"
    assert response.json()["error"]["details"]["headers"] == [missing]
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_whitelist_refuses_unknown_keys_before_any_request() -> None:
    from app.repositories.base import RepositoryError
    from app.repositories.google_sheets import schemas

    backend = _backend()
    repo = _repo(backend)
    header = tuple(backend.tabs[VEHICLE_TAB][0])
    with pytest.raises(RepositoryError):
        await repo._client.batch_update_cells(schemas.VEHICLE_REGISTRATION_WRITE_SHEET, 2, header, {"responsible_branch_id": "x"})
    assert backend.mutation_count() == 0
    assert schemas.VEHICLE_SHEET.required_headers == tuple(HEADER)  # the read schema keeps its seven headers


# ---------------------------------------------------------------------------
# W-09 header reorder; W-12 byte-exact text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w09_targeted_cells_after_a_header_reorder() -> None:
    header = ["registration_province_code", "updated_at", "vehicle_id", "responsible_branch_id", "machine_no",
              "model_id", "registration_no", "serial_number", "operational_status", "created_at"]
    backend = _backend(header=header)
    response = await _http(_repo(backend), "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body("ใหม่ 3", "TH-10", None, None))
    assert response.status_code == 200, response.text
    by_col = {d["range"].split("!")[-1]: d["values"][0][0] for d in backend.write_log[1]["data"]}
    assert by_col == {"G4": "'ใหม่ 3", "A4": "'TH-10", "B4": by_col["B4"]}  # columns found by name, row 4 = VEH-3
    stored = _cells(backend, "VEH-3")
    assert (stored["registration_no"], stored["registration_province_code"]) == ("ใหม่ 3", "TH-10")
    assert stored["responsible_branch_id"] == "" and stored["machine_no"] == "M-VEH-3"


TEXTS = ["0012", " 0012 ", "กข ๑๒๓๔", "=1+1", "+66", "'quoted", "1,234", "1e3", "TRUE", " ก ข "]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", TEXTS)
async def test_w12_text_is_byte_exact_after_write_and_read(value) -> None:
    backend = _backend()
    repo = _repo(backend)
    response = await _http(repo, "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body(value, "TH-10", None, None))
    assert response.status_code == 200, response.text
    assert _cells(backend, "VEH-3")["registration_no"] == value
    history = (await _http(repo, "GET", f"{API}/vehicles/VEH-3/registration-history")).json()
    assert history["current"]["registration_no"] == {"state": "RECORDED", "value": value}
    assert history["items"][-1]["new_registration_no"] == value
    assert history["consistency"] == "CONSISTENT"
    replay = await _http(repo, "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body(value, "TH-10", value, "TH-10"))
    assert replay.json()["changed"] is False  # stored text compares equal to what was sent


# ---------------------------------------------------------------------------
# Uniqueness scope over the R1 response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_includes_blank_id_and_gate_failing_rows_and_ignores_phantom_rows() -> None:
    rows = [
        *ROWS,
        (_row("", "WORKING"), {"registration_no": "บล 1", "registration_province_code": "TH-21"}),  # blank id
        (_row("VEH-BAD", "NOT_A_STATUS"), {"registration_no": "ผิด 2", "registration_province_code": "TH-21"}),  # fails gates
    ]
    backend = _backend(rows)
    # a phantom row: no canonical cell, only registry cells
    head = backend.tabs[VEHICLE_TAB][0]
    backend.tabs[VEHICLE_TAB].append(["" if h not in ("registration_no", "registration_province_code") else
                                      {"registration_no": "ผี 3", "registration_province_code": "TH-21"}[h] for h in head])
    repo = _repo(backend)
    blank = await _http(repo, "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body("บล-1", "TH-21", None, None))
    assert blank.status_code == 409 and blank.json()["error"]["details"] == {"conflict_count": 1, "conflict_vehicle_ids": []}
    bad = await _http(repo, "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body("ผิด2", "TH-21", None, None))
    assert bad.status_code == 409 and bad.json()["error"]["details"]["conflict_vehicle_ids"] == ["VEH-BAD"]
    phantom = await _http(repo, "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body("ผี 3", "TH-21", None, None))
    assert phantom.status_code == 200, phantom.text
    assert _writes(backend) == ["append", "batchUpdate"]


# ---------------------------------------------------------------------------
# W-10 interleaved registrations of one pair (disclosed race)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_w10_interleaved_requests_can_both_pass_and_the_duplicate_is_visible_afterwards() -> None:
    backend = _backend()
    repo = _repo(backend)
    original = repo.read_vehicle_registration_master
    pending: dict[str, object] = {}

    async def stale_r1(vehicle_id):
        # both requests use an R1 taken before either wrote (the interleaving)
        if "snapshot" not in pending:
            pending["snapshot"] = copy.deepcopy(backend.tabs[VEHICLE_TAB])
        live = backend.tabs[VEHICLE_TAB]
        backend.tabs[VEHICLE_TAB] = copy.deepcopy(pending["snapshot"])
        try:
            return await original(vehicle_id)
        finally:
            backend.tabs[VEHICLE_TAB] = live

    repo.read_vehicle_registration_master = stale_r1  # type: ignore[method-assign]
    first = await _http(repo, "PATCH", f"{API}/vehicles/VEH-2/registration", json_body=_body("ชน 1", "TH-10", "กข-1234", "TH-20"))
    second = await _http(repo, "PATCH", f"{API}/vehicles/VEH-3/registration", json_body=_body("ชน-1", "TH-10", None, None))
    assert first.status_code == 200 and second.status_code == 200  # Sheets has no unique constraint
    repo.read_vehicle_registration_master = original  # type: ignore[method-assign]
    third = await _http(repo, "PATCH", f"{API}/vehicles/VEH-1/registration", json_body=_body("ชน1", "TH-10", "0012", "TH-21"))
    assert third.status_code == 409
    assert third.json()["error"]["details"] == {"conflict_count": 2, "conflict_vehicle_ids": ["VEH-2", "VEH-3"]}
    noop = await _http(repo, "PATCH", f"{API}/vehicles/VEH-2/registration", json_body=_body("ชน 1", "TH-10", "ชน 1", "TH-10"))
    assert noop.json()["warnings"] == ["EXISTING_DUPLICATE_PAIR"]  # the duplicate is visible


# ---------------------------------------------------------------------------
# W-07 failure classification over the fake transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,mode,code,outcome",
    [
        ("append", "reject", "REGISTRATION_HISTORY_WRITE_FAILED", "rejected"),
        ("append", "server_error", "REGISTRATION_HISTORY_WRITE_FAILED", "unknown"),
        ("append", "apply_then_timeout", "REGISTRATION_HISTORY_WRITE_FAILED", "unknown"),
        ("batchUpdate", "reject", "VEHICLE_MASTER_WRITE_FAILED", "rejected"),
        ("batchUpdate", "server_error", "VEHICLE_MASTER_WRITE_FAILED", "unknown"),
        ("batchUpdate", "apply_then_timeout", "VEHICLE_MASTER_WRITE_FAILED", "unknown"),
    ],
)
async def test_w07_write_failures_are_classified_and_never_retried(kind, mode, code, outcome) -> None:
    backend = _backend()
    backend.fail[kind] = mode
    repo = _repo(backend)
    rid = str(uuid.uuid4())
    response = await _http(repo, "PATCH", f"{API}/vehicles/VEH-1/registration", json_body=_body("0013", "TH-21", "0012", "TH-21"), request_id=rid)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == code and error["request_id"] == rid
    key = "history_write_outcome" if kind == "append" else "master_write_outcome"
    assert error["details"][key] == outcome
    expected_writes = ["append"] if kind == "append" else ["append", "batchUpdate"]
    assert _writes(backend) == expected_writes  # one request each, never retried
    backend.fail[kind] = None
    history = (await _http(repo, "GET", f"{API}/vehicles/VEH-1/registration-history")).json()
    applied_history = kind == "batchUpdate" or mode == "apply_then_timeout"
    applied_master = kind == "batchUpdate" and mode == "apply_then_timeout"
    assert any(item["request_id"] == rid for item in history["items"]) is applied_history
    expected = "CONSISTENT" if (applied_master or not applied_history) else "MISMATCH"
    assert history["consistency"] == ("NO_HISTORY" if not applied_history else expected)


# ---------------------------------------------------------------------------
# Request counts (fake transport; not a claim about live quota)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_counts_per_path() -> None:
    backend = _backend()
    repo = _repo(backend)
    await _http(repo, "GET", f"{API}/vehicles/VEH-1/registration-history")  # warm metadata
    cases = [
        (_body("0012", "TH-21", "0012", "TH-21"), 2, []),  # no-op
        (_body("0013", "TH-21", "0011", "TH-21"), 2, []),  # stale
        (_body("ไม่มีจังหวัด", None, "0012", "TH-21"), 2, ["append", "batchUpdate"]),  # change without a code
        (_body("0014", "TH-20", "ไม่มีจังหวัด", None), 3, ["append", "batchUpdate"]),  # change with a code
    ]
    for body, reads, writes in cases:
        backend.requests.clear()
        backend.write_log.clear()
        response = await _http(repo, "PATCH", f"{API}/vehicles/VEH-1/registration", json_body=body)
        assert response.status_code in (200, 409), response.text
        assert backend.values_reads() == reads, body
        assert _writes(backend) == writes, body


# ---------------------------------------------------------------------------
# Reconciliation over the fake transport
# ---------------------------------------------------------------------------


def _history_row(**cells) -> list[str]:
    import hashlib

    row = dict.fromkeys(REGISTRATION_HISTORY_COLUMNS, "")
    row.update(change_kind="CHANGE", recorded_by="u-1", is_test_data="TRUE", test_batch_id=BATCH,
               request_fingerprint=hashlib.sha256(b"seed").hexdigest())
    row.update(cells)
    return [row[c] for c in REGISTRATION_HISTORY_COLUMNS]


SEED_HISTORY = [
    _history_row(change_id="VRH-" + "e" * 32, vehicle_id="VEH-1", old_registration_no="", new_registration_no="0012",
                 new_registration_province_code="TH-21", recorded_at="2026-09-01T00:00:00+00:00", request_id="seed-1"),
]


@pytest.mark.asyncio
async def test_apply_and_accept_over_the_fake_transport() -> None:
    rows = [(_row("VEH-1", "WORKING"), {"registration_no": "0099", "registration_province_code": "TH-20"}), *ROWS[1:]]
    for mode, writes, master in (("APPLY_RECORDED", ["append", "batchUpdate"], ("0012", "TH-21")),
                                 ("ACCEPT_MASTER", ["append"], ("0099", "TH-20"))):
        backend = _backend(rows, history=copy.deepcopy(SEED_HISTORY))
        repo = _repo(backend)
        before = _history_rows(backend)
        body = {"mode": mode, "expected_registration_no": "0099", "expected_registration_province_code": "TH-20",
                "expected_history_revision": registration_history_revision(before), "reason_th": "แก้ให้ตรง",
                "related_request_id": "seed-1"}
        response = await _http(repo, "POST", f"{API}/vehicles/VEH-1/registration-history/reconciliations", json_body=body)
        assert response.status_code == 200, response.text
        assert response.json()["master_write"] == ("WRITTEN" if mode == "APPLY_RECORDED" else "NOT_NEEDED")
        assert _writes(backend) == writes
        after = _history_rows(backend)
        assert after[:-1] == before  # earlier rows never edited
        assert after[-1]["related_request_id"] == "seed-1" and after[-1]["note_th"] == "แก้ให้ตรง"
        stored = _cells(backend, "VEH-1")
        assert (stored["registration_no"], stored["registration_province_code"]) == master
        history = (await _http(repo, "GET", f"{API}/vehicles/VEH-1/registration-history")).json()
        assert history["consistency"] == "CONSISTENT"


# ---------------------------------------------------------------------------
# Mock / fake parity
# ---------------------------------------------------------------------------


async def _mock_http(repo, method, path, json_body=None, request_id=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
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


def _mock_like_fake() -> MockRepository:
    """A mock repository holding the same three vehicles' registry cells and
    no history, so both sides start from the same registry state."""
    repo = MockRepository()
    ids = list(repo._vehicles)[:3]
    repo._vehicles = {f"VEH-{i + 1}": repo._vehicles[k].model_copy(update={"vehicle_id": f"VEH-{i + 1}"}) for i, k in enumerate(ids)}
    repo._vehicle_registry = {
        "VEH-1": {"registration_no": "0012", "registration_province_code": "TH-21", "responsible_branch_id": "BR-A"},
        "VEH-2": {"registration_no": "กข-1234", "registration_province_code": "TH-20", "responsible_branch_id": ""},
        "VEH-3": {"registration_no": "", "registration_province_code": "", "responsible_branch_id": ""},
    }
    repo._registration_history = []
    repo._province_master = [dict(zip(PROVINCES[0], r)) for r in PROVINCES[1:]]
    return repo


PARITY_STEPS = [
    ("PATCH", "VEH-3", _body("กข ๑๒๓๔", "TH-20", None, None)),  # duplicate of VEH-2 under RK1
    ("PATCH", "VEH-3", _body("กข 1234", "TH-21", None, None)),  # other province: ok
    ("PATCH", "VEH-3", _body("x", "TH-76", "กข 1234", "TH-21")),  # inactive
    ("PATCH", "VEH-3", _body("x", "TH-99", "กข 1234", "TH-21")),  # unknown
    ("PATCH", "VEH-1", _body("0013", "TH-21", "0011", "TH-21")),  # stale
    ("PATCH", "VEH-1", _body("0012", "TH-21", "0012", "TH-21")),  # no-op
    ("PATCH", "VEH-1", _body(None, "TH-21", "0012", "TH-21")),  # text required
    ("PATCH", "VEH-1", _body(None, None, "0012", "TH-21")),  # clear
    ("PATCH", "VEH-NONE", _body("1", None, None, None)),  # not found
]


@pytest.mark.asyncio
async def test_mock_and_fake_give_identical_results() -> None:
    backend = _backend()
    fake = _repo(backend)
    mock = _mock_like_fake()

    def shape(response) -> tuple:
        body = response.json()
        if "error" in body:
            details = body["error"]["details"] or {}
            return response.status_code, body["error"]["code"], details
        return response.status_code, body.get("changed"), body.get("warnings"), (body.get("vehicle") or {}).get("registry")

    for method, vid, body in PARITY_STEPS:
        rid = str(uuid.uuid4())
        a = await _http(fake, method, f"{API}/vehicles/{vid}/registration", json_body=body, request_id=rid)
        b = await _mock_http(mock, method, f"{API}/vehicles/{vid}/registration", json_body=body, request_id=rid)
        assert shape(a) == shape(b), (vid, body)
    for vid in ("VEH-1", "VEH-2", "VEH-3"):
        ha = (await _http(fake, "GET", f"{API}/vehicles/{vid}/registration-history")).json()
        hb = (await _mock_http(mock, "GET", f"{API}/vehicles/{vid}/registration-history")).json()
        strip = lambda h: (h["current"], h["consistency"], [  # noqa: E731
            {k: v for k, v in i.items() if k not in ("change_id", "recorded_at", "request_id")} for i in h["items"]])
        assert strip(ha) == strip(hb), vid
    assert TS  # fixture timestamps are synthetic
