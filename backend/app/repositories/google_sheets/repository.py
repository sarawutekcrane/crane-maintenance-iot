"""Google Sheets-backed repository (base adapter).

Implements the same `Repository` interface as `MockRepository`. The
domain/service layer must not know or care which one is active; only
`app.dependencies` (composition root) decides based on `DATA_REPOSITORY`.
"""
from __future__ import annotations

from app.config import Settings
from app.repositories.base import Repository
from app.repositories.google_sheets.client import GoogleSheetsClient


class GoogleSheetsRepository(Repository):
    def __init__(self, settings: Settings) -> None:
        self._client = GoogleSheetsClient(settings)

    @property
    def mode(self) -> str:
        return "google_sheets"

    async def check_ready(self) -> tuple[bool, str | None]:
        return await self._client.verify_connectivity()
