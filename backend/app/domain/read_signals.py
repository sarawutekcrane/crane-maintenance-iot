"""R2 Batch R2f-h4 precondition — read-only signals for the frontend (owner
decision D-H4-1). Pure functions over values the server already holds; no
repository call, no setting change, no write.

- `assignment_model_signal`: the PERSISTED per-job marker (C1 §12), never the
  current cutover setting. Blank -> "LEGACY"; exactly "TECHNICIAN_V2" ->
  "TECHNICIAN_V2"; anything else -> "INVALID" (fail closed: an unknown marker
  is never reported as either model, so a client can offer neither model's
  actions; the V2 and legacy write / recording paths keep refusing such a job
  with 500 ASSIGNMENT_MODEL_DATA_INVALID, unchanged).
- `data_context_signal`: the server's effective registry data context (C1 §15,
  `Settings.registry_context_effective`). Exactly "REAL" or "TEST"; anything
  else, including unset, is "UNCONFIGURED" — never REAL. Informational only:
  it replaces neither server-side authorization nor TEST/REAL isolation.
"""
from __future__ import annotations

from app.domain.registration import DATA_CONTEXT_REAL, DATA_CONTEXT_TEST
from app.domain.technician_assignment import ASSIGNMENT_MODEL_LEGACY, ASSIGNMENT_MODEL_TECHNICIAN_V2

ASSIGNMENT_MODEL_SIGNAL_LEGACY = "LEGACY"
ASSIGNMENT_MODEL_SIGNAL_TECHNICIAN_V2 = ASSIGNMENT_MODEL_TECHNICIAN_V2
ASSIGNMENT_MODEL_SIGNAL_INVALID = "INVALID"

DATA_CONTEXT_SIGNAL_REAL = DATA_CONTEXT_REAL
DATA_CONTEXT_SIGNAL_TEST = DATA_CONTEXT_TEST
DATA_CONTEXT_SIGNAL_UNCONFIGURED = "UNCONFIGURED"


def assignment_model_signal(stored: object) -> str:
    """The persisted marker as exact text (no trimming or case folding)."""
    if not isinstance(stored, str):
        return ASSIGNMENT_MODEL_SIGNAL_INVALID
    if stored == ASSIGNMENT_MODEL_LEGACY:
        return ASSIGNMENT_MODEL_SIGNAL_LEGACY
    if stored == ASSIGNMENT_MODEL_TECHNICIAN_V2:
        return ASSIGNMENT_MODEL_SIGNAL_TECHNICIAN_V2
    return ASSIGNMENT_MODEL_SIGNAL_INVALID


def data_context_signal(effective: object) -> str:
    if effective == DATA_CONTEXT_REAL:
        return DATA_CONTEXT_SIGNAL_REAL
    if effective == DATA_CONTEXT_TEST:
        return DATA_CONTEXT_SIGNAL_TEST
    return DATA_CONTEXT_SIGNAL_UNCONFIGURED


__all__ = [
    "ASSIGNMENT_MODEL_SIGNAL_INVALID",
    "ASSIGNMENT_MODEL_SIGNAL_LEGACY",
    "ASSIGNMENT_MODEL_SIGNAL_TECHNICIAN_V2",
    "DATA_CONTEXT_SIGNAL_REAL",
    "DATA_CONTEXT_SIGNAL_TEST",
    "DATA_CONTEXT_SIGNAL_UNCONFIGURED",
    "assignment_model_signal",
    "data_context_signal",
]
