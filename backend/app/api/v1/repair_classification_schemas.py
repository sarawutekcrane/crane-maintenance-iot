"""R8 PRE-UAT — TEST repair classification schemas (Mock/TEST only)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CatalogueResponse(BaseModel):
    summary: dict[str, Any]
    tree: list[dict[str, Any]]
    symptoms: dict[str, str]
    actions: dict[str, str]
    excluded: list[dict[str, Any]]
    position_fields: dict[str, list[str] | None]


class ClassificationResponse(BaseModel):
    repair_id: str
    state: str  # NOT_ELIGIBLE | BLOCKED_STORE_UNRECONCILED | WAITING_FOR_CLASSIFICATION | CLASSIFIED
    blockers: list[str]
    draft_revision: int
    draft_rows: list[dict[str, Any]]
    final: dict[str, Any] | None
    replayed: bool = False
    note_th: str = "TEST candidate — ไม่อนุมัติสำหรับ REAL"
