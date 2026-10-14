"""R2 Batch R2f-h4 precondition — response types of the read-only frontend
signals (owner decision D-H4-1). The values come only from
`app.domain.read_signals`."""
from __future__ import annotations

from typing import Literal

AssignmentModelSignal = Literal["LEGACY", "TECHNICIAN_V2", "INVALID"]
DataContextSignal = Literal["REAL", "TEST", "UNCONFIGURED"]

__all__ = ["AssignmentModelSignal", "DataContextSignal"]
