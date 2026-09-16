"""REV08 live UAT defect (P0 BLOCKER) — `GoogleSheetsClient.append_row`/
`append_rows` write semantics.

New live evidence after the REV07 Inspection-batching fix (commit
465a7c9) showed that batching alone did not solve live persistence:
`inspection_header`, `inspection_result`, and `meter_snapshot` each lost
ALL of their prior rows the next time anything was appended to them,
while `inspection_findings`, `meter_readings`, `location_snapshot`, and
`repair_request` kept full history. Every one of these tabs goes through
the exact same generic `GoogleSheetsClient.append_row`/`append_rows`
code — the only thing that differed between an affected and an
unaffected tab was something in the *live* Google Sheet itself that this
sandbox cannot reproduce or inspect (no live credentials here — this is
stated as an explicit, unresolved uncertainty, not a guess dressed up as
a finding).

What IS fully verifiable from this codebase, independent of that
uncertainty, is that `append_row`/`append_rows` never told the Sheets
API where to look for "the table" (`table_range` was always left `None`,
so gspread searched the *entire, unbounded* tab) nor how to write past
it (`insert_data_option` was always left `None`, so the Sheets API used
its own documented default, `OVERWRITE` — which *destroys* whatever was
in the target cells, as opposed to `INSERT_ROWS`, which always inserts
and shifts existing rows down instead). That is the one write-time
choice in this codebase that can turn "the API guessed the wrong row"
into permanent data loss, for any tab, at any time, regardless of why the
guess was wrong. The fix makes both parameters explicit, generically,
for every tab.

These tests assert the *exact* keyword arguments now reaching the
(fake) `gspread` worksheet, across a range of real declared schema
widths, plus the A1 column-letter conversion `_column_letter` itself
relies on for deriving `table_range`.
"""
from __future__ import annotations

import pytest

from app.repositories.google_sheets import schemas
from app.repositories.google_sheets.client import GoogleSheetsClient, SheetTabSchema, _column_letter
from tests.test_google_sheets_real_io import _configured_settings, _repo_with_fake_sheets, _ws


# ---------------------------------------------------------------------------
# A1 column-letter conversion (1=A, 26=Z, 27=AA, ...).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "A"),
        (7, "G"),
        (9, "I"),
        (10, "J"),
        (13, "M"),
        (15, "O"),
        (16, "P"),
        (26, "Z"),
        (27, "AA"),
        (52, "AZ"),
        (53, "BA"),
    ],
)
def test_column_letter_conversion(count: int, expected: str) -> None:
    assert _column_letter(count) == expected


# ---------------------------------------------------------------------------
# append_row / append_rows must always pass an explicit, bounded
# table_range and insert_data_option="INSERT_ROWS" — never leave either
# to the Sheets API's own (destructive, OVERWRITE) default.
# ---------------------------------------------------------------------------


REAL_SCHEMAS_BY_WIDTH = {
    7: schemas.METER_SNAPSHOT_SHEET,
    9: schemas.INSPECTION_FINDING_SHEET,
    10: schemas.INSPECTION_SHEET,
    13: schemas.INSPECTION_ITEM_RESULT_SHEET,
    15: schemas.LOCATION_SNAPSHOT_SHEET,
    16: schemas.REPAIR_REQUEST_SHEET,
}


def _client_for(schema: SheetTabSchema) -> tuple[GoogleSheetsClient, "object"]:
    repo = _repo_with_fake_sheets(_ws(schema))
    return repo._client, repo._client._get_worksheet_sync(schema.tab_name)  # type: ignore[attr-defined]


@pytest.mark.parametrize("width", sorted(REAL_SCHEMAS_BY_WIDTH))
@pytest.mark.asyncio
async def test_append_row_uses_explicit_bounded_insert_rows_semantics(width: int) -> None:
    schema = REAL_SCHEMAS_BY_WIDTH[width]
    assert len(schema.required_headers) == width, (
        f"fixture/schema width mismatch for {schema.tab_name}: "
        f"expected {width}, schema actually declares {len(schema.required_headers)}"
    )
    client, worksheet = _client_for(schema)

    await client.append_row(schema, {schema.required_headers[0]: "X-1"})

    assert worksheet.append_row_calls == 1
    kwargs = worksheet.append_row_kwargs[0]
    assert kwargs["insert_data_option"] == "INSERT_ROWS"
    assert kwargs["table_range"] == f"A1:{_column_letter(width)}"
    assert kwargs["value_input_option"] == "USER_ENTERED"


@pytest.mark.parametrize("width", sorted(REAL_SCHEMAS_BY_WIDTH))
@pytest.mark.asyncio
async def test_append_rows_uses_explicit_bounded_insert_rows_semantics_in_one_call(width: int) -> None:
    schema = REAL_SCHEMAS_BY_WIDTH[width]
    client, worksheet = _client_for(schema)

    await client.append_rows(
        schema,
        [
            {schema.required_headers[0]: "X-1"},
            {schema.required_headers[0]: "X-2"},
            {schema.required_headers[0]: "X-3"},
        ],
    )

    # One Sheets API request for the whole batch, not one per row.
    assert worksheet.append_rows_calls == 1
    assert worksheet.append_row_calls == 0
    kwargs = worksheet.append_rows_kwargs[0]
    assert kwargs["insert_data_option"] == "INSERT_ROWS"
    assert kwargs["table_range"] == f"A1:{_column_letter(width)}"
    assert kwargs["value_input_option"] == "USER_ENTERED"
    assert len(worksheet.rows) == 3


@pytest.mark.asyncio
async def test_append_rows_is_a_no_op_for_an_empty_batch() -> None:
    schema = schemas.INSPECTION_FINDING_SHEET
    client, worksheet = _client_for(schema)

    await client.append_rows(schema, [])

    assert worksheet.append_rows_calls == 0
    assert worksheet.rows == []
