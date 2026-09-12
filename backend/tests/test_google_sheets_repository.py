from __future__ import annotations

import pytest

from app.config import Settings
from app.repositories.google_sheets import GoogleSheetsRepository


@pytest.mark.asyncio
async def test_not_ready_when_unconfigured() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    ready, reason = await repo.check_ready()
    assert ready is False
    assert reason is not None
    assert repo.mode == "google_sheets"
