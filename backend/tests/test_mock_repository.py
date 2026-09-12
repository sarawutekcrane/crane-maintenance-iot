from __future__ import annotations

import pytest

from app.repositories.mock import MockRepository


@pytest.mark.asyncio
async def test_mock_repository_is_always_ready() -> None:
    repo = MockRepository()
    ready, reason = await repo.check_ready()
    assert ready is True
    assert reason is None
    assert repo.mode == "mock"
