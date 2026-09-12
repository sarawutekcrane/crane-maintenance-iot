"""Repository interface.

Frozen in Phase 1: the domain/service layer depends only on this
interface, never on a concrete storage technology. Phase 1 only defines
the readiness/self-check contract; domain-entity repository methods
(vehicles, inspections, PM, parts, ...) are added starting Phase 2 as
extensions of `Repository`, without changing this base shape.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RepositoryError(Exception):
    """Raised when a repository cannot serve a request (connectivity,
    missing schema, etc.). Domain/service code should translate this into
    an ApiError; it must never leak raw driver exceptions (e.g. Google API
    exceptions) upward.
    """


class Repository(ABC):
    """Base interface every concrete repository (mock, Google Sheets,
    PostgreSQL) must implement.
    """

    @property
    @abstractmethod
    def mode(self) -> str:
        """Short identifier of the backing mode, e.g. "mock", "google_sheets"."""

    @abstractmethod
    async def check_ready(self) -> tuple[bool, str | None]:
        """Return (is_ready, reason_if_not_ready).

        Used by GET /api/v1/readiness. Mock repositories are always ready.
        Google Sheets / PostgreSQL repositories should verify connectivity
        and required schema here.
        """
