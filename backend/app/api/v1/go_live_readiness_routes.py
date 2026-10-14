"""R2 Batch R2f-h3 — Pre-Go-live verification report (C1 §26, owner decisions D1-D4).

POST /api/v1/technician-assignment/go-live-readiness — STRICTLY READ ONLY.
POST only carries the two owner-supplied personnel id lists (D2); nothing is
written, so no X-Request-Id is required.

Authorization (owner decision D1): BOTH existing capabilities
`can_link_personnel_technician` AND `can_link_personnel_account` (no role name,
no new capability or grant). It runs before the body is parsed and before any
repository read: a caller missing either gets 403 with zero reads. Every caller
that passes may see linked user_id values (D1).

REAL context only: a TEST context (mock is always TEST) is 409 — never evidence
of REAL readiness. The authentication mode is reported, never changed.

R2 Batch R2f-h4 B6 Rev2 (owner final decision: Technician V2 only): the former
`cutover_enabled` report field is removed together with the setting; no check
ever depended on it (H3-01 and every other check are unchanged).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.api.v1.registry_mutation_body import openapi_body, parse_body
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_LINK_PERSONNEL_ACCOUNT, CAN_LINK_PERSONNEL_TECHNICIAN
from app.domain.go_live_readiness import GoLiveReadinessService
from app.repositories.base import Repository

router = APIRouter(tags=["go-live-readiness"])

REQUIRED_CAPABILITIES = (CAN_LINK_PERSONNEL_TECHNICIAN, CAN_LINK_PERSONNEL_ACCOUNT)


def require_readiness_capabilities(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    """D1: logical AND of the two existing link capabilities, before anything else."""
    missing = [c for c in REQUIRED_CAPABILITIES if c not in context.capabilities]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="รายงานความพร้อมก่อน Go-live (pre-Go-live readiness report) requires the capabilities "
                   + " AND ".join(f"'{c}'" for c in REQUIRED_CAPABILITIES),
        )
    return context


class GoLiveReadinessRequest(BaseModel):
    """D2: two explicit lists of exact personnel_id strings. Omitted, null and
    empty are distinguished and none of them can make a check PASS."""

    model_config = ConfigDict(extra="forbid")

    intended_recipient_personnel_ids: list[str] | None = None
    intended_my_work_personnel_ids: list[str] | None = None


class CheckResponse(BaseModel):
    id: str
    requirement: str
    status: Literal["PASS", "FAIL", "BLOCKED", "UNDETERMINED"]
    evidence: dict[str, Any]
    issues: list[dict[str, Any]]


class CoverageResponse(BaseModel):
    source: str
    tab: str
    status: Literal["EXAMINED", "ABSENT", "NOT_ASSESSABLE", "EXCLUDED_BY_CONTRACT", "UNTAGGED"]
    role: str
    rows: int | None
    test_rows: int | None
    real_rows: int | None
    references_verified: list[str]
    detail: str


class GoLiveReadinessResponse(BaseModel):
    generated_at: datetime
    data_context: Literal["REAL"]
    environment: dict[str, Any]
    overall: Literal["READY", "NOT_READY", "BLOCKED"]
    checks: list[CheckResponse]
    inputs: dict[str, Any]
    coverage: list[CoverageResponse]
    issues: list[dict[str, Any]]
    gaps: list[str]
    population: list[dict[str, Any]] | None


_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks can_link_personnel_technician AND/OR "
                         "can_link_personnel_account. Zero repository reads."},
    409: {"description": "GO_LIVE_READINESS_REQUIRES_REAL_CONTEXT — the server is not in the REAL data context."},
    422: {"description": "VALIDATION_ERROR — the body is not two optional lists of strings."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; GO_LIVE_READINESS_READ_FAILED {source, tab} — "
                         "no partial report."},
}


def get_go_live_readiness_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> GoLiveReadinessService:
    return GoLiveReadinessService(
        repository, data_context=settings.registry_context_effective,
        dev_auth_effective=settings.dev_auth_effective,
    )


@router.post("/technician-assignment/go-live-readiness", response_model=GoLiveReadinessResponse,
             responses=_RESPONSES, openapi_extra=openapi_body(GoLiveReadinessRequest))
async def get_go_live_readiness(
    request: Request,
    _context: RequestContext = Depends(require_readiness_capabilities),
    service: GoLiveReadinessService = Depends(get_go_live_readiness_service),
) -> GoLiveReadinessResponse:
    parsed, body = await parse_body(request, GoLiveReadinessRequest)
    report = await service.report(body, frozenset(parsed.model_fields_set))
    checks = [CheckResponse(id=c.id, requirement=c.requirement, status=c.status,  # type: ignore[arg-type]
                            evidence=c.evidence, issues=c.issues) for c in report.checks]
    return GoLiveReadinessResponse(
        generated_at=report.generated_at, data_context=report.data_context,  # type: ignore[arg-type]
        environment={"dev_auth_effective": report.dev_auth_effective,
                     "production_authentication": "NOT_IMPLEMENTED (R11)"},
        overall=report.overall,  # type: ignore[arg-type]
        checks=checks, inputs=report.inputs,
        coverage=[CoverageResponse(source=e.source, tab=e.tab, status=e.status, role=e.role,  # type: ignore[arg-type]
                                   rows=e.rows, test_rows=e.test_rows, real_rows=e.real_rows,
                                   references_verified=list(e.references_verified), detail=e.detail)
                  for e in report.coverage],
        issues=[{"check": c.id, **i} for c in report.checks for i in c.issues],
        gaps=report.gaps, population=report.population,
    )
