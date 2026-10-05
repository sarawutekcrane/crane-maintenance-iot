"""Phase 7 Batch 7O2b — route dependencies of the registry mutations
(contract Final Rev2 §3.2, §3.3 step 0; Outcome Classification Addendum A.1).

Order (declared on each route): the capability dependency, then the request-id
dependency, then FastAPI's body validation. FastAPI resolves dependencies
before it validates the body, so an unauthorized caller always gets 403 and a
caller without a usable `X-Request-Id` gets 422 REQUEST_ID_REQUIRED, both with
zero repository calls. These are the only places a registry mutation raises
`HTTPException`; after them every outcome is a coded `ApiError`.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status

from app.context import REQUEST_ID_HEADER, RequestContext
from app.dependencies import get_current_context
from app.errors import ApiError

# UUID text form (8-4-4-4-12 hex). The client generates one per user intent
# and reuses it only for an explicit re-send of the identical body (§10.3).
_UUID_TEXT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def require_capability_dependency(capability: str, action_description: str) -> Callable[..., RequestContext]:
    """A route dependency that refuses (403 HTTP_ERROR) before anything else
    runs. The actor must also carry a user id: every history row records
    `recorded_by`, and a row without it would be invalid."""

    def dependency(context: RequestContext = Depends(get_current_context)) -> RequestContext:
        if capability not in context.capabilities or not (context.user_id or "").strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{action_description} requires the '{capability}' capability",
            )
        return context

    return dependency


def require_client_request_id(request: Request) -> str:
    """The client's own `X-Request-Id`, read from the request headers — never
    the id the middleware generates when the header is absent. Missing or not
    in UUID text form -> 422 REQUEST_ID_REQUIRED (zero repository calls)."""
    value = request.headers.get(REQUEST_ID_HEADER)
    if value is None or not _UUID_TEXT.fullmatch(value):
        raise ApiError(
            code="REQUEST_ID_REQUIRED",
            message=f"A client-generated {REQUEST_ID_HEADER} header in UUID form is required for this change",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return value
