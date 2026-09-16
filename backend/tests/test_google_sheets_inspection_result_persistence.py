"""REV07 live UAT defect (section 15, P0 BLOCKER) — Inspection persistence
in Google Sheets mode.

Live UAT reproduction: submitting a 2-item Inspection (item 1 -> PASS,
item 2 -> FAIL) against the real Google Sheet returned a correct API
response (`RES-0001`/PASS and `RES-0002`/FAIL, `INS-0001`, `FND-0001`,
`MSNAP-0007`), but the *persisted* `inspection_result` tab, and a
subsequent `GET /api/v1/inspections/INS-0001`, contained only
`RES-0002`/FAIL — `RES-0001`/PASS never made it to the sheet.

Root cause: `GoogleSheetsRepository.create_inspection` wrote each
`inspection_result` row (and each `inspection_findings` row) with its own
independent `GoogleSheetsClient.append_row` call, one per submitted item.
`append_row` asks the Sheets API to find "the table" in the tab and write
after its last row; that detection is resolved fresh on every call, so N
independent back-to-back calls give the API N independent chances to
resolve "the next row" — and in the live sheet, the second call's own
detection landed on the *same* row as the first, silently overwriting it
instead of appending after it.

Fix: `create_inspection` now builds every item's result row (and finding
row, if any) in memory first, then writes each sheet's whole batch as a
single `GoogleSheetsClient.append_rows` call (see that method's
docstring). The fake `gspread`-shaped `FakeWorksheet` used here is a
naive in-memory list, so it was never itself capable of reproducing the
live overwrite (see `tests/test_google_sheets_real_io.py`'s module
docstring) — these tests instead prove two independent things that
together rule the regression out: (1) the resulting physical rows are
exactly right (count, order, content, read-back), and (2) the code no
longer takes the per-item `append_row` path at all for these two sheets
(`FakeWorksheet.append_row_calls == 0`), which is the structural change
that eliminates the failure mode regardless of the underlying Sheets API's
own behavior.
"""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue
from app.domain.inspection import NewInspectionItemInput
from app.repositories.google_sheets import schemas
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws


def _item(item_id: str, sequence: int, result: InspectionResultValue) -> NewInspectionItemInput:
    return NewInspectionItemInput(
        item_id=item_id,
        sequence=sequence,
        title=f"Checklist item {sequence}",
        is_critical=False,
        result=result,
    )


def _repo_and_sheets():
    header_ws = _ws(schemas.INSPECTION_SHEET)
    result_ws = _ws(schemas.INSPECTION_ITEM_RESULT_SHEET)
    finding_ws = _ws(schemas.INSPECTION_FINDING_SHEET)
    repo = _repo_with_fake_sheets(header_ws, result_ws, finding_ws)
    return repo, header_ws, result_ws, finding_ws


@pytest.mark.asyncio
async def test_pass_then_fail_persists_both_result_rows_and_one_finding() -> None:
    """The exact live UAT reproduction: item 1 PASS, item 2 FAIL."""
    repo, header_ws, result_ws, finding_ws = _repo_and_sheets()
    items = [
        _item("CHKITEM-UAT-001", 1, InspectionResultValue.PASS),
        _item("CHKITEM-UAT-002", 2, InspectionResultValue.FAIL),
    ]

    created = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="UAT-VEH-001",
        checklist_id="CHK-0001",
        revision_id="REV-0001",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=items,
        machine_state_snapshot_id="MSNAP-0007",
    )

    # Physical row counts, starting from an empty sheet.
    assert len(header_ws.rows) == 1
    assert len(result_ws.rows) == 2
    assert len(finding_ws.rows) == 1

    # The fix must not reintroduce a per-item append call for these sheets.
    assert result_ws.append_row_calls == 0
    assert result_ws.append_rows_calls == 1
    assert finding_ws.append_row_calls == 0
    assert finding_ws.append_rows_calls == 1

    # Distinct, submission-ordered result IDs; both survive in the
    # returned object, not just the first.
    assert len(created.items) == 2
    result_ids = [item.result_id for item in created.items]
    assert len(set(result_ids)) == 2
    assert created.items[0].result == InspectionResultValue.PASS
    assert created.items[1].result == InspectionResultValue.FAIL
    assert len(created.findings) == 1
    assert created.findings[0].result_id == created.items[1].result_id

    # Read-back must reflect the same persisted state, not a stale/short
    # in-memory response (the exact live UAT failure: response said 2,
    # sheet + GET said 1).
    reread = await repo.get_inspection(created.header.inspection_id)
    assert reread is not None
    assert len(reread.items) == 2
    results_by_id = {item.result_id: item for item in reread.items}
    assert results_by_id[created.items[0].result_id].result == InspectionResultValue.PASS
    assert results_by_id[created.items[1].result_id].result == InspectionResultValue.FAIL
    assert len(reread.findings) == 1
    assert reread.findings[0].result_id == created.items[1].result_id


@pytest.mark.asyncio
async def test_pass_then_pass_persists_two_results_and_no_findings() -> None:
    repo, header_ws, result_ws, finding_ws = _repo_and_sheets()
    items = [
        _item("ITEM-1", 1, InspectionResultValue.PASS),
        _item("ITEM-2", 2, InspectionResultValue.PASS),
    ]

    created = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=items,
    )

    assert len(header_ws.rows) == 1
    assert len(result_ws.rows) == 2
    assert len(finding_ws.rows) == 0
    assert len(created.items) == 2
    assert len(created.findings) == 0
    assert len({item.result_id for item in created.items}) == 2

    reread = await repo.get_inspection(created.header.inspection_id)
    assert reread is not None
    assert len(reread.items) == 2
    assert len(reread.findings) == 0


@pytest.mark.asyncio
async def test_pass_fail_na_persists_three_results_and_one_finding() -> None:
    repo, header_ws, result_ws, finding_ws = _repo_and_sheets()
    items = [
        _item("ITEM-1", 1, InspectionResultValue.PASS),
        _item("ITEM-2", 2, InspectionResultValue.FAIL),
        _item("ITEM-3", 3, InspectionResultValue.NA),
    ]

    created = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=items,
    )

    assert len(header_ws.rows) == 1
    assert len(result_ws.rows) == 3
    assert len(finding_ws.rows) == 1
    assert [item.result for item in created.items] == [
        InspectionResultValue.PASS,
        InspectionResultValue.FAIL,
        InspectionResultValue.NA,
    ]
    assert len({item.result_id for item in created.items}) == 3
    assert len(created.findings) == 1
    assert created.findings[0].result_id == created.items[1].result_id

    reread = await repo.get_inspection(created.header.inspection_id)
    assert reread is not None
    assert len(reread.items) == 3
    assert len(reread.findings) == 1


@pytest.mark.asyncio
async def test_fail_then_fail_persists_two_distinct_findings_without_overwrite() -> None:
    repo, header_ws, result_ws, finding_ws = _repo_and_sheets()
    items = [
        _item("ITEM-1", 1, InspectionResultValue.FAIL),
        _item("ITEM-2", 2, InspectionResultValue.FAIL),
    ]

    created = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=items,
    )

    assert len(header_ws.rows) == 1
    assert len(result_ws.rows) == 2
    assert len(finding_ws.rows) == 2
    assert len(created.findings) == 2
    finding_ids = {finding.finding_id for finding in created.findings}
    assert len(finding_ids) == 2
    # Each Finding maps to its own distinct FAIL result — neither
    # overwrote the other's row.
    finding_result_ids = {finding.result_id for finding in created.findings}
    assert finding_result_ids == {item.result_id for item in created.items}

    reread = await repo.get_inspection(created.header.inspection_id)
    assert reread is not None
    assert len(reread.items) == 2
    assert len(reread.findings) == 2
    assert {f.result_id for f in reread.findings} == {item.result_id for item in reread.items}


@pytest.mark.asyncio
async def test_create_inspection_writes_exactly_one_header_row() -> None:
    """CORE-G01 / Task E: one submission must never create more than one
    `inspection_header` row, regardless of how many checklist items it
    carries."""
    repo, header_ws, result_ws, finding_ws = _repo_and_sheets()
    items = [_item(f"ITEM-{n}", n, InspectionResultValue.PASS) for n in range(1, 6)]

    await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1",
        checklist_id="CHK-1",
        revision_id="REV-1",
        revision_number=1,
        inspector_user_id="user-1",
        overall_remark=None,
        items=items,
    )

    assert len(header_ws.rows) == 1
    assert header_ws.append_row_calls == 1
    assert len(result_ws.rows) == 5
