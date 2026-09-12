"""In-memory mock repository.

Runs fully offline with no external services. Used for local development
before Google Sheets credentials exist, and for fast automated tests.
Domain-entity storage (vehicles, inspections, ...) is added starting
Phase 2; Phase 1 only proves the repository can be constructed and
reports readiness.
"""
from __future__ import annotations

from app.repositories.base import Repository


class MockRepository(Repository):
    @property
    def mode(self) -> str:
        return "mock"

    async def check_ready(self) -> tuple[bool, str | None]:
        # Mock mode has no external dependency, so it is always ready.
        return True, None
