"""Live UAT defect fix: `GoogleSheetsClient.read_rows` used to return
every physical row `get_all_records` reported, including phantom rows
left over after a live tab is cleared/rebuilt (Google Sheets can report
thousands of blank-but-formatted rows). With one real vehicle in
`vehicle_master`, `GET /api/v1/vehicles` reported `total_items=236`, most
of them blank `Vehicle` objects with `vehicle_id=""`/epoch timestamps.

Exercised against a FAKE in-memory `gspread`-shaped client (never the
real Google API/network — see `tests/test_google_sheets_real_io.py`'s
module docstring and REV05 section 11G): no live-sheet I/O happens here.

Fix: `read_rows` now drops a physical row only when every one of
`schema.required_headers` is blank on it — a canonical-empty phantom row
— never a row with at least one populated canonical field, and never
based on values sitting only in extraneous/non-canonical columns.
`find_row` is deliberately left unchanged: an exact-ID lookup against a
blank row's `id_column=""` only ever matches a lookup for `id_value=""`,
which is not a realistic call, so there is no demonstrated bug there.
"""
from __future__ import annotations

import pytest

from app.domain.common import PageParams
from app.repositories.google_sheets import schemas
from app.repositories.google_sheets.client import GoogleSheetsClient
from tests.test_google_sheets_real_io import (
    FakeSpreadsheet,
    FakeWorksheet,
    _configured_settings,
    _repo_with_fake_sheets,
    _ws,
)


def _client_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsClient:
    client = GoogleSheetsClient(_configured_settings())
    client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return client


def _blank_vehicle_row() -> list[str]:
    return ["", "", "", "", "", "", ""]


def _vehicle_row(vehicle_id: str, machine_no: str, model_id: str = "MDL-1") -> list[str]:
    return [
        vehicle_id,
        machine_no,
        model_id,
        "",
        "READY",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
    ]


# ---------------------------------------------------------------------------
# A. Completely blank physical rows are ignored.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completely_blank_rows_are_excluded() -> None:
    ws = _ws(schemas.VEHICLE_SHEET)
    ws.append_row(_blank_vehicle_row())
    ws.append_row(_blank_vehicle_row())
    ws.append_row(_vehicle_row("UAT-VEH-001", "UAT/001"))
    ws.append_row(_blank_vehicle_row())

    client = _client_with_fake_sheets(ws)
    records = await client.read_rows(schemas.VEHICLE_SHEET)

    assert len(records) == 1
    assert records[0]["vehicle_id"] == "UAT-VEH-001"
    assert records[0]["machine_no"] == "UAT/001"


# ---------------------------------------------------------------------------
# B. A partially populated row is NOT silently removed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partially_populated_row_is_preserved() -> None:
    ws = _ws(schemas.VEHICLE_SHEET)
    # Only machine_no is populated; every other canonical field is blank.
    # This is a malformed/partial business row, not a phantom, and must
    # never be silently hidden by this fix.
    partial_row = ["", "220/9", "", "", "", "", ""]
    ws.append_row(partial_row)

    client = _client_with_fake_sheets(ws)
    records = await client.read_rows(schemas.VEHICLE_SHEET)

    assert len(records) == 1
    assert records[0]["machine_no"] == "220/9"
    assert records[0]["vehicle_id"] == ""  # preserved as blank, never defaulted here


# ---------------------------------------------------------------------------
# C. Extra/non-canonical column data alone does not count.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_canonical_column_data_does_not_rescue_a_canonical_empty_row() -> None:
    header = tuple(schemas.VEHICLE_SHEET.required_headers) + ("extra_note",)
    ws = FakeWorksheet(schemas.VEHICLE_SHEET.tab_name, header)
    # Every canonical column is blank; only the extraneous column has data.
    ws.append_row(["", "", "", "", "", "", "", "leftover formatting junk"])
    ws.append_row(list(_vehicle_row("UAT-VEH-001", "UAT/001")) + [""])

    client = _client_with_fake_sheets(ws)
    records = await client.read_rows(schemas.VEHICLE_SHEET)

    assert len(records) == 1
    assert records[0]["vehicle_id"] == "UAT-VEH-001"


# ---------------------------------------------------------------------------
# D. Existing normal rows still preserve order.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_order_is_preserved_around_filtered_blank_rows() -> None:
    ws = _ws(schemas.VEHICLE_SHEET)
    ws.append_row(_vehicle_row("VEH-A", "220/1"))
    ws.append_row(_blank_vehicle_row())
    ws.append_row(_vehicle_row("VEH-B", "220/2"))
    ws.append_row(_blank_vehicle_row())
    ws.append_row(_vehicle_row("VEH-C", "220/3"))

    client = _client_with_fake_sheets(ws)
    records = await client.read_rows(schemas.VEHICLE_SHEET)

    assert [r["vehicle_id"] for r in records] == ["VEH-A", "VEH-B", "VEH-C"]


# ---------------------------------------------------------------------------
# E. Vehicle list regression — repository level.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicles_excludes_phantom_rows_and_preserves_machine_no() -> None:
    ws = _ws(schemas.VEHICLE_SHEET)
    for _ in range(50):
        ws.append_row(_blank_vehicle_row())
    ws.append_row(_vehicle_row("UAT-VEH-001", "UAT/001"))
    for _ in range(50):
        ws.append_row(_blank_vehicle_row())

    repo = _repo_with_fake_sheets(ws)
    items, total = await repo.list_vehicles(
        q=None, operational_status=None, model_id=None, params=PageParams()
    )

    assert total == 1
    assert len(items) == 1
    assert items[0].vehicle_id == "UAT-VEH-001"
    assert items[0].machine_no == "UAT/001"  # opaque machine number preserved exactly

    # Exact-ID read continues to work unaffected (was already correct).
    exact = await repo.get_vehicle("UAT-VEH-001")
    assert exact is not None
    assert exact.machine_no == "UAT/001"


# ---------------------------------------------------------------------------
# F. Model list regression — repository level.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_models_excludes_phantom_rows() -> None:
    model_ws = _ws(schemas.VEHICLE_MODEL_SHEET)
    blank_model_row = ["", "", "", "", "", "", "", "", ""]
    for _ in range(50):
        model_ws.append_row(blank_model_row)
    model_ws.append_row(
        [
            "UAT-MDL-001",
            "UAT-MC-001",
            "UAT Model",
            "",
            "",
            "",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "",
        ]
    )
    for _ in range(50):
        model_ws.append_row(blank_model_row)
    plan_ws = _ws(schemas.PM_PLAN_SHEET)

    repo = _repo_with_fake_sheets(model_ws, plan_ws)
    items, total = await repo.list_vehicle_models(q=None, params=PageParams())

    assert total == 1
    assert len(items) == 1
    assert items[0].model_id == "UAT-MDL-001"
