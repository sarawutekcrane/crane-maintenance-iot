from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    app_env: str


class ReadinessCheck(BaseModel):
    name: str
    ready: bool
    reason: str | None = None


class ReadinessResponse(BaseModel):
    ready: bool
    repository_mode: str
    checks: list[ReadinessCheck]
