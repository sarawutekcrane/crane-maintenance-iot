"""GET /api/v1/health and GET /api/v1/readiness.

Frozen routes (see docs/01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt section 13).

Health: the process is alive. Never depends on external services.
Readiness: configured dependencies (repository, storage) are usable. In
mock mode, Google Sheets is not required for readiness.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.schemas import HealthResponse, ReadinessCheck, ReadinessResponse
from app.config import Settings, get_settings
from app.dependencies import get_repository
from app.repositories.base import Repository

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", app_env=settings.app_env)


@router.get("/readiness", response_model=ReadinessResponse)
async def readiness(
    repository: Repository = Depends(get_repository),
) -> ReadinessResponse:
    repo_ready, repo_reason = await repository.check_ready()
    checks = [
        ReadinessCheck(name=f"repository:{repository.mode}", ready=repo_ready, reason=repo_reason)
    ]
    return ReadinessResponse(
        ready=all(check.ready for check in checks),
        repository_mode=repository.mode,
        checks=checks,
    )
