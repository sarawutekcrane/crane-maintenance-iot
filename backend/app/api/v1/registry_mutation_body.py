"""Phase 7 Batch 7O2c — request-body helpers shared by the registry mutation
routes (registration, 7O2b; responsible branch, 7O2c). Moved from
`registration_routes` without any behaviour change.

The body is parsed and validated INSIDE the handler, after the capability and
client request-id dependencies, so that even a malformed JSON body from an
unauthorized caller is a 403 (FastAPI would otherwise parse a declared body
parameter before any dependency). Error details never echo the input.
"""
from __future__ import annotations

from typing import Any, TypeVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from app.config import DataRepositoryMode, Settings
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID

M = TypeVar("M", bound=BaseModel)


async def parse_body(request: Request, model: type[M]) -> tuple[M, dict[str, Any]]:
    """The validated body and the body EXACTLY as accepted (every key the
    client sent, values unchanged) for the request fingerprint."""
    raw = await request.body()
    try:
        parsed = model.model_validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(
            exc.errors(include_url=False, include_context=False, include_input=False)
        ) from exc
    return parsed, parsed.model_dump(exclude_unset=True)


def _inline_refs(schema: Any, defs: dict[str, Any]) -> Any:
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return _inline_refs(defs[ref.removeprefix("#/$defs/")], defs)
        return {k: _inline_refs(v, defs) for k, v in schema.items() if k != "$defs"}
    if isinstance(schema, list):
        return [_inline_refs(v, defs) for v in schema]
    return schema


def openapi_body(model: type[BaseModel]) -> dict[str, Any]:
    """The documented request body (nested models inlined, so no reference
    points outside the operation)."""
    schema = model.model_json_schema()
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _inline_refs(schema, schema.get("$defs", {}))}},
        }
    }


def effective_test_batch_id(settings: Settings) -> str:
    """REGISTRY_TEST_BATCH_ID, or the labelled synthetic id in mock mode."""
    batch_id = settings.registry_test_batch_id
    if settings.data_repository == DataRepositoryMode.MOCK and not batch_id.strip():
        batch_id = MOCK_TEST_BATCH_ID
    return batch_id
