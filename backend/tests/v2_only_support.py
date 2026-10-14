"""R2 Batch R2f-h4 B6 Rev2 test support — the server context a directly
constructed `RepairService` / `PmService` needs under the owner's final
decision (Technician V2 ONLY).

Every new job is a V2 job, and a V2 job is created only with a proven data
context (TEST/REAL isolation). The application wires that context from the
settings (`cutover_from_settings`); a service constructed WITHOUT one still
fails closed (`REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`), so tests that build
services by hand pass the context they model explicitly:

- `mock_test_cutover()` — the mock repository, which is always TEST (the mock
  TEST batch), exactly what `cutover_from_settings` gives in mock mode;
- `live_real_cutover()` — a Sheets-backed repository in the REAL context (live
  TEST is refused for V2 by design).
"""
from __future__ import annotations

from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.technician_assignment import AssignmentCutover


def mock_test_cutover() -> AssignmentCutover:
    return AssignmentCutover(data_context="TEST", test_batch_id=MOCK_TEST_BATCH_ID, live=False)


def live_real_cutover() -> AssignmentCutover:
    return AssignmentCutover(data_context="REAL", test_batch_id="", live=True)
