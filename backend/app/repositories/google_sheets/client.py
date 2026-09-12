"""Base Google Sheets client/adapter.

Phase 1 only creates the adapter architecture (connection + schema
validation hooks). It does not implement any domain table read/write;
those arrive with each domain phase (Phase 2+) as they need sheet access.

Design notes (see docs/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt
section 6-7):

- Never depend on hard-coded row positions for identity.
- Map columns by header name, not column index.
- Verify expected tab + required headers before writing.
- Credentials are read from GOOGLE_APPLICATION_CREDENTIALS; the JSON file
  itself is never committed to the repository.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class SheetTabSchema:
    """Declares the tab name and required header row for one logical table."""

    tab_name: str
    required_headers: tuple[str, ...]


class GoogleSheetsClient:
    """Thin wrapper around the Google Sheets API connection.

    Phase 1 intentionally does not import `google-api-python-client` /
    `gspread` yet, so the application can run with zero Google
    dependencies installed in mock mode. The real client construction is
    implemented when the first domain phase needs to read/write a sheet.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(
            self._settings.google_sheet_id
            and self._settings.google_application_credentials
        )

    async def verify_connectivity(self) -> tuple[bool, str | None]:
        """Read-only connectivity + schema check.

        Returns (ok, reason_if_not_ok). Phase 1 only validates that the
        required configuration is present; actual network calls and
        header validation are added when a domain phase defines its first
        `SheetTabSchema`.
        """
        if not self.is_configured:
            return False, "GOOGLE_SHEET_ID / GOOGLE_APPLICATION_CREDENTIALS not configured"
        return True, None

    async def validate_schema(self, schema: SheetTabSchema) -> tuple[bool, str | None]:
        """Validate that `schema.tab_name` exists with `required_headers`.

        Not yet wired to a real Sheets call in Phase 1 (no domain tables
        exist yet). Raises to make accidental use obvious rather than
        silently pretending success.
        """
        raise NotImplementedError(
            "Schema validation is implemented starting with the phase that "
            "introduces the first Google Sheets-backed domain table."
        )
