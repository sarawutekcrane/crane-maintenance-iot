"""R2 Batch R2e — helpers shared by the personnel and department lifecycle
routes: service construction from settings and response serialisation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.lifecycle_schemas import LifecycleNoOpResponse, LifecycleReplayResponse
from app.domain.master_lifecycle import LifecycleOutcome


def respond(outcome: LifecycleOutcome, changed_model: type[BaseModel], state: Callable[[str], Any]) -> JSONResponse:
    if outcome.replayed:
        body: BaseModel = LifecycleReplayResponse(
            request_id=outcome.request_id, replayed=True, record_ids=list(outcome.record_ids)
        )
    elif not outcome.changed:
        body = LifecycleNoOpResponse(request_id=outcome.request_id, changed=False)
    else:
        body = changed_model(
            request_id=outcome.request_id,
            changed=True,
            record_id=outcome.record_id or "",
            previous_state=state(outcome.previous_state or ""),
            new_state=state(outcome.new_state or ""),
            lifecycle_consistency_after=outcome.lifecycle_consistency_after,
        )
    return JSONResponse(content=body.model_dump(mode="json"))


def responses(label: str, changed_model: type[BaseModel]) -> dict[int | str, dict[str, Any]]:
    return {
        200: {"model": changed_model, "description": "changed / no-op {request_id, changed:false} / replayed"},
        403: {"description": "HTTP_ERROR — the caller lacks the capability. Zero repository calls."},
        404: {"description": f"{label}_NOT_FOUND (in the request's data-context scope)."},
        409: {
            "description": f"{label}_ID_AMBIGUOUS {{match_count}}; {label}_LIFECYCLE_STALE {{field}}; "
            f"{label}_LIFECYCLE_MISMATCH (reconcile first); REQUEST_ID_REUSED."
        },
        422: {
            "description": f"REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; {label}_LIFECYCLE_STATE_INVALID "
            "(the record's current lifecycle value is not a known state)."
        },
        500: {
            "description": f"{label}_MASTER_SCHEMA_INVALID / {label}_MASTER_DATA_INVALID {{issues}} / "
            f"{label}_LIFECYCLE_HISTORY_SCHEMA_INVALID / {label}_LIFECYCLE_HISTORY_DATA_INVALID {{issues}}."
        },
        503: {
            "description": f"REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; {label}_LIFECYCLE_HISTORY_WRITE_FAILED "
            f"{{history_write_outcome, request_id}} (nothing written to the record); {label}_LIFECYCLE_STATE_WRITE_FAILED "
            "{event_recorded: true, record_id, request_id} (history recorded; reconcile to finish)."
        },
    }
