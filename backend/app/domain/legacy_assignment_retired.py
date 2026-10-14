"""R2 Batch R2f-h4 B6 — the retired legacy (user_id-based) technician
assignment workflow (C1 Amendment A1 §3 group B, owner decision D3).

Technician assignment is Technician V2-only: V2 jobs are assigned through
`/{job}/technician-assignments` (and withdrawn through
`/{job}/technician-assignment-withdrawals`). The legacy WRITE paths
(`POST /repairs/{id}/assign`, `POST /pm/work-orders/{id}/assign`, an inline
`primary_technician` / `collaborators` on Repair creation or Repair-Request
conversion) and the legacy-only READ queues (`GET /repairs/my-work`,
`GET /pm/work-orders/my-work`, `GET /repairs/waiting-assignment`) are retired:
each answers with an explicit error and touches no data.

Retained (A1 §3 group C): the shared assignment tabs and every stored legacy
row, the read-only `/{job}/assignment-history` views of legacy jobs, the
legacy-history recording / evidence authorization of legacy jobs, the
denormalized header mirror, `AssignmentRole`, identities and audit fields.
Nothing is converted, deleted or rewritten.
"""
from __future__ import annotations

from fastapi import status

from app.domain.registry_write_support import error
from app.errors import ApiError

LEGACY_ASSIGNMENT_RETIRED = "LEGACY_ASSIGNMENT_RETIRED"


def legacy_route_retired(route: str) -> ApiError:
    """410 for a retired legacy assignment route — raised before any read or write."""
    return error(LEGACY_ASSIGNMENT_RETIRED,
                 f"The legacy technician assignment route {route} is retired; technician assignment uses the "
                 "Technician V2 routes. Nothing was read or changed", status.HTTP_410_GONE, {"route": route})


def refuse_legacy_inline_assignee(primary_technician: object, collaborators: object) -> None:
    """422 when a create / convert request still carries a legacy inline
    assignee (an opaque user_id) — raised before any read or write, whatever
    the cutover setting. An empty value is accepted (no assignee)."""
    if primary_technician or collaborators:
        raise error(LEGACY_ASSIGNMENT_RETIRED,
                    "A legacy inline technician (primary_technician / collaborators) is no longer accepted; assign "
                    "technicians through the Technician V2 assignment routes. Nothing was changed",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    {"fields": [f for f, v in (("primary_technician", primary_technician),
                                               ("collaborators", collaborators)) if v]})


__all__ = ["LEGACY_ASSIGNMENT_RETIRED", "legacy_route_retired", "refuse_legacy_inline_assignee"]
