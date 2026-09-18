"""Google Sheets client/adapter — real read/write I/O (Core Demo Fixes
Delta REV05 section 11).

Web -> Backend API -> Domain/Service -> Repository -> Google Sheets. The
browser never calls Google Sheets directly; only this module (via
`GoogleSheetsRepository`) does.

Auth: a service-account JSON key file named by
`GOOGLE_APPLICATION_CREDENTIALS`, scoped to Sheets read/write only
(`https://www.googleapis.com/auth/spreadsheets`) — never the broader
Drive scope, since nothing here needs to create/list/move files, only
read/write cell ranges in one already-shared spreadsheet named by
`GOOGLE_SHEET_ID`. The credential file itself is never committed and its
key material is never logged (see `_wrap_error`, which reports only the
exception's class name/message from the `google-auth`/`gspread`
libraries — those libraries do not embed the private key in their own
error text).

`gspread` is a synchronous HTTP client; every call here runs in a worker
thread via `asyncio.to_thread` so it never blocks the event loop.

Concurrency/idempotency (REV05 section 11F): this prototype does not
implement a distributed lock or transaction. `append_row`/`update_row`
each touch exactly one row via a targeted range write — never a
full-sheet rewrite — and `find_row_by_id` always re-reads before a write
decision, but two concurrent writers can still race (last-write-wins on
`update_row`, or two rows for the same logical create on `append_row` if
a caller does not itself de-duplicate — `RepairRequestService.convert`
is the one place in this codebase that needs that guarantee, and it
re-reads the request's `request_status` immediately before deciding
whether to create a Repair). This matches the explicit scope: a
production-grade guarantee is out of scope for this prototype branch.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.repositories.base import RepositoryError

_SHEETS_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


@dataclass(frozen=True)
class SheetTabSchema:
    """Declares the tab name and required header row for one logical table."""

    tab_name: str
    required_headers: tuple[str, ...]


def _wrap_error(action: str, exc: Exception) -> RepositoryError:
    """Never leak a raw Google API/driver exception upward (frozen
    storage rule) — only the exception's own class/message, never its
    args/repr, which for some google-auth exceptions can otherwise
    include request bodies."""
    return RepositoryError(f"Google Sheets {action} failed: {type(exc).__name__}: {exc}")


class GoogleSheetsClient:
    """Thin async wrapper around a real `gspread` client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._gspread_client: Any = None
        self._spreadsheet: Any = None
        self._worksheets: dict[str, Any] = {}
        self._header_cache: dict[str, tuple[str, ...]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(
            self._settings.google_sheet_id and self._settings.google_application_credentials
        )

    def _require_configured_or_raise(self) -> None:
        if not self.is_configured:
            raise RepositoryError(
                "GOOGLE_SHEET_ID / GOOGLE_APPLICATION_CREDENTIALS are not configured. See "
                "docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt "
                "section 7 for local setup."
            )

    def _build_client_sync(self) -> Any:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:  # pragma: no cover - dependency always pinned in requirements.txt
            raise RepositoryError(
                "gspread/google-auth are not installed — add them to requirements.txt"
            ) from exc
        try:
            credentials = Credentials.from_service_account_file(
                self._settings.google_application_credentials, scopes=list(_SHEETS_SCOPES)
            )
            return gspread.authorize(credentials)
        except Exception as exc:  # noqa: BLE001 - normalized into RepositoryError below
            raise _wrap_error("authentication", exc) from exc

    def _get_client_sync(self) -> Any:
        if self._gspread_client is None:
            self._gspread_client = self._build_client_sync()
        return self._gspread_client

    def _get_spreadsheet_sync(self) -> Any:
        if self._spreadsheet is None:
            client = self._get_client_sync()
            try:
                self._spreadsheet = client.open_by_key(self._settings.google_sheet_id)
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(
                    f"opening spreadsheet '{self._settings.google_sheet_id}'", exc
                ) from exc
        return self._spreadsheet

    def _get_worksheet_sync(self, tab_name: str) -> Any:
        if tab_name not in self._worksheets:
            spreadsheet = self._get_spreadsheet_sync()
            try:
                self._worksheets[tab_name] = spreadsheet.worksheet(tab_name)
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"opening tab '{tab_name}'", exc) from exc
        return self._worksheets[tab_name]

    def _get_header_sync(self, tab_name: str) -> tuple[str, ...]:
        if tab_name not in self._header_cache:
            worksheet = self._get_worksheet_sync(tab_name)
            try:
                header = tuple(worksheet.row_values(1))
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"reading header row of '{tab_name}'", exc) from exc
            self._header_cache[tab_name] = header
        return self._header_cache[tab_name]

    # ---- Connectivity / schema validation ----

    async def verify_connectivity(self) -> tuple[bool, str | None]:
        if not self.is_configured:
            return False, "GOOGLE_SHEET_ID / GOOGLE_APPLICATION_CREDENTIALS not configured"

        def _check() -> tuple[bool, str | None]:
            try:
                spreadsheet = self._get_spreadsheet_sync()
                spreadsheet.worksheets()  # proves read access, not just that the key opened
                return True, None
            except RepositoryError as exc:
                return False, str(exc)
            except Exception as exc:  # noqa: BLE001
                return False, str(_wrap_error("connectivity check", exc))

        return await asyncio.to_thread(_check)

    async def validate_schema(self, schema: SheetTabSchema) -> tuple[bool, str | None]:
        """Validate that `schema.tab_name` exists with every one of
        `schema.required_headers` present (order-independent — columns
        are mapped by name, never position). Never auto-creates/renames a
        live sheet (REV05 section 11D)."""
        if not self.is_configured:
            return False, "GOOGLE_SHEET_ID / GOOGLE_APPLICATION_CREDENTIALS not configured"

        def _check() -> tuple[bool, str | None]:
            try:
                spreadsheet = self._get_spreadsheet_sync()
                titles = {w.title for w in spreadsheet.worksheets()}
            except RepositoryError as exc:
                return False, str(exc)
            except Exception as exc:  # noqa: BLE001
                return False, str(_wrap_error("listing tabs", exc))
            if schema.tab_name not in titles:
                return False, f"Tab '{schema.tab_name}' does not exist in the spreadsheet"
            try:
                header = set(self._get_header_sync(schema.tab_name))
            except RepositoryError as exc:
                return False, str(exc)
            missing = [h for h in schema.required_headers if h not in header]
            if missing:
                return (
                    False,
                    f"Tab '{schema.tab_name}' is missing required header(s): {', '.join(missing)}",
                )
            return True, None

        return await asyncio.to_thread(_check)

    # ---- Generic header-mapped row CRUD (never row-position-dependent) ----

    @staticmethod
    def _has_any_canonical_value(record: dict[str, str], schema: SheetTabSchema) -> bool:
        """A physical sheet row counts as a real record only if at least
        one of its canonical `schema.required_headers` cells is
        non-blank. Values sitting only in extraneous/non-canonical
        columns never count — they cannot make an otherwise
        canonical-empty row a repository record. This deliberately never
        flags a *partially* populated row (any one canonical field
        non-blank is enough): only a row that is blank across every
        canonical field is a phantom, not a malformed business row."""
        return any(str(record.get(header, "")).strip() for header in schema.required_headers)

    @staticmethod
    def _numericise_ignore_columns(
        schema: SheetTabSchema, text_only_headers: tuple[str, ...]
    ) -> list[int]:
        """Translate header names into the 1-indexed column positions
        `gspread.Worksheet.get_all_records`'s own `numericise_ignore`
        parameter expects (never row/column position elsewhere in this
        codebase — this is purely an internal detail of one specific
        gspread call, isolated here).

        LIVE UAT DEFECT FIX (phone leading-zero loss, follow-up finding):
        `get_all_records()` performs its own **client-side** numeric
        coercion (`gspread.utils.numericise_all`) on every column's
        FORMATTED_VALUE string, independent of how the cell is actually
        stored server-side — so even a cell correctly written as literal
        text (see `GoogleSheetsRepository._force_text_for_sheet`) is
        still converted back into an `int`/`float` locally by gspread on
        every subsequent read if its formatted text happens to look like
        a plain number (e.g. "0999999999" -> `int` `999999999`, losing
        the leading zero again). `numericise_ignore` is gspread's own
        established mechanism for exactly this — reused here rather than
        inventing a parallel conversion layer."""
        return [
            schema.required_headers.index(header) + 1
            for header in text_only_headers
            if header in schema.required_headers
        ]

    async def read_rows(
        self, schema: SheetTabSchema, text_only_headers: tuple[str, ...] = ()
    ) -> list[dict[str, str]]:
        """Every data row (excluding the header) that has at least one
        non-blank canonical field, as header-name-keyed dicts, in sheet
        order.

        A row whose every `schema.required_headers` cell is blank is a
        phantom physical row — e.g. left over after a live tab is
        cleared/rebuilt, where Google Sheets can still report thousands
        of empty formatted rows — never a real repository record.
        Filtering it out once here, generically, protects every
        `list_*`/`get_*` repository method built on `read_rows` without
        each one reimplementing the same check (REV07 live UAT defect:
        `GET /api/v1/vehicles` returning 236 rows for one real vehicle).

        `text_only_headers` (optional, default none — no behavior change
        for any existing caller): header names that must never be
        client-side numericised by gspread on this read — see
        `_numericise_ignore_columns`."""
        self._require_configured_or_raise()

        def _read() -> list[dict[str, str]]:
            worksheet = self._get_worksheet_sync(schema.tab_name)
            ignore = self._numericise_ignore_columns(schema, text_only_headers)
            try:
                records = worksheet.get_all_records(
                    head=1, default_blank="", numericise_ignore=ignore
                )
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"reading rows from '{schema.tab_name}'", exc) from exc
            return [r for r in records if self._has_any_canonical_value(r, schema)]

        return await asyncio.to_thread(_read)

    async def find_row(
        self,
        schema: SheetTabSchema,
        id_column: str,
        id_value: str,
        text_only_headers: tuple[str, ...] = (),
    ) -> tuple[int, dict[str, str]] | None:
        """Return `(1-indexed sheet row number, row dict)` for the first
        row whose `id_column` equals `id_value`, or `None`. See
        `read_rows` for `text_only_headers`."""
        self._require_configured_or_raise()

        def _find() -> tuple[int, dict[str, str]] | None:
            worksheet = self._get_worksheet_sync(schema.tab_name)
            ignore = self._numericise_ignore_columns(schema, text_only_headers)
            try:
                records = worksheet.get_all_records(
                    head=1, default_blank="", numericise_ignore=ignore
                )
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"reading rows from '{schema.tab_name}'", exc) from exc
            for index, record in enumerate(records):
                if str(record.get(id_column, "")) == id_value:
                    return index + 2, record  # +1 header row, +1 to 1-index
            return None

        return await asyncio.to_thread(_find)

    async def append_row(self, schema: SheetTabSchema, row: dict[str, object]) -> None:
        """Append one row, deliberately (never a full-sheet rewrite).
        Values are mapped to the sheet's own current header order; any
        header not present in `row` is written blank.

        See `append_rows` below for why `table_range`/`insert_data_option`
        are always passed explicitly (REV08 live UAT defect: several
        tabs — `inspection_header`, `meter_snapshot` among them — had
        every prior row silently destroyed by the next unrelated
        append)."""
        self._require_configured_or_raise()

        def _append() -> None:
            worksheet = self._get_worksheet_sync(schema.tab_name)
            header = self._get_header_sync(schema.tab_name)
            values = [_serialize(row.get(column)) for column in header]
            try:
                worksheet.append_row(
                    values,
                    value_input_option="USER_ENTERED",
                    insert_data_option="INSERT_ROWS",
                    table_range=f"A1:{_column_letter(len(header))}",
                )
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"appending a row to '{schema.tab_name}'", exc) from exc

        await asyncio.to_thread(_append)

    async def append_rows(self, schema: SheetTabSchema, rows: list[dict[str, object]]) -> None:
        """Append multiple rows as a single Sheets API request — never as
        several independent `append_row` calls for what is logically one
        write (e.g. every result row of one submitted Inspection);
        several independent calls give the Sheets API's own table
        detection N separate, independent chances to disagree about
        "the next row", instead of resolving it once for the whole batch.

        `table_range`/`insert_data_option` are always passed explicitly,
        never left to the API's own defaults:

        - Neither `append_row` nor this method used to pass a
          `table_range`, so gspread asked the Sheets API to locate "the
          table" by searching the *entire, unbounded* tab (sheet name
          only, no A1 restriction) — a search whose result depends on
          the tab's live formatting/history in ways this codebase cannot
          fully control or verify (REV07/REV08 live UAT: `inspection_
          result`, `inspection_header`, and `meter_snapshot` each showed
          this "table" being consistently misdetected as ending at the
          header row, i.e. row 1, no matter how much real data already
          existed below it). Anchoring the search to an explicit
          `A1:<last schema column>` range removes that ambiguity: the
          search is always bounded to exactly the tab's own declared
          columns.
        - Neither call passed `insert_data_option`, so the Sheets API
          applied its own documented default, `OVERWRITE` — which writes
          the new values directly into whatever cells the (possibly
          misdetected) target row occupies, destroying any pre-existing
          row there. `INSERT_ROWS` instead always inserts new rows and
          shifts anything below them down, so even in the worst case
          where the table's end is still misdetected, no existing row is
          ever destroyed — only ever mis-ordered, which this codebase
          does not otherwise observe.

        This is a client-wide fix, not a per-tab one: every tab reached
        through `append_row`/`append_rows` gets the same explicit,
        bounded, non-destructive semantics."""
        if not rows:
            return
        self._require_configured_or_raise()

        def _append() -> None:
            worksheet = self._get_worksheet_sync(schema.tab_name)
            header = self._get_header_sync(schema.tab_name)
            values = [[_serialize(row.get(column)) for column in header] for row in rows]
            try:
                worksheet.append_rows(
                    values,
                    value_input_option="USER_ENTERED",
                    insert_data_option="INSERT_ROWS",
                    table_range=f"A1:{_column_letter(len(header))}",
                )
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"appending {len(rows)} rows to '{schema.tab_name}'", exc) from exc

        await asyncio.to_thread(_append)

    async def update_row(
        self, schema: SheetTabSchema, row_number: int, row: dict[str, object]
    ) -> None:
        """Overwrite exactly one existing row (`row_number`, 1-indexed
        including the header) with `row`'s values, mapped onto the
        sheet's current header order. Only that single row's range is
        written — every other row is untouched."""
        self._require_configured_or_raise()

        def _update() -> None:
            worksheet = self._get_worksheet_sync(schema.tab_name)
            header = self._get_header_sync(schema.tab_name)
            values = [_serialize(row.get(column)) for column in header]
            last_column = _column_letter(len(header))
            try:
                worksheet.update(
                    f"A{row_number}:{last_column}{row_number}",
                    [values],
                    value_input_option="USER_ENTERED",
                )
            except Exception as exc:  # noqa: BLE001
                raise _wrap_error(f"updating row {row_number} of '{schema.tab_name}'", exc) from exc

        await asyncio.to_thread(_update)


def _serialize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _column_letter(count: int) -> str:
    """1 -> 'A', 26 -> 'Z', 27 -> 'AA', ... (A1-notation column name for
    the `count`-th column)."""
    letters = ""
    n = count
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
