"""R4-PM-WF-01 B02-B1: pure contract tests for the persisted PM item outcome
(identity, fingerprint, record check, compatibility, dormancy). Synthetic data
only; no repository, runtime, API or Google Sheets access."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.pm import (
    PmItemContractDisposition as Disposition,
    PmWorkOrderStatus,
    PmWorkResult,
    build_pm_item_outcome,
    build_pm_outstanding_item,
    pm_item_outcome_id,
    pm_outstanding_source_identity,
    validate_pm_item_outcome_record,
)

# Synthetic markers: NOT the Owner's business codes (still caller-supplied).
REASONS = frozenset({"TEST-NOT-DONE", "TEST-OTHER"})
ACTIONS = frozenset({"TEST-CHECK", "TEST-CLEAN", "TEST-REPLACE-REFILL"})
T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
BACKEND = Path(__file__).resolve().parents[1]


def outcome(disposition=Disposition.NOT_PERFORMED, **kwargs):
    base = {"pm_work_order_id": "SYNTH-PMWO-1", "pm_task_id": "SYNTH-T1", "revision_id": "SYNTH-REV-1",
            "recorded_at": T0, "approved_not_performed_reasons": REASONS, "approved_other_reason_code": "TEST-OTHER",
            "approved_performed_actions": ACTIONS, "recorded_by": "SYNTH-TECH"}
    if disposition == Disposition.NOT_PERFORMED and "reason_code" not in kwargs:
        kwargs["reason_code"] = "TEST-NOT-DONE"
    return build_pm_item_outcome(disposition=disposition, **(base | kwargs))


def performed(**kwargs):
    return outcome(Disposition.PERFORMED, performed_actions=kwargs.pop("performed_actions", ("TEST-CHECK",)), **kwargs)


def test_b02b1_03_approved_action_and_reason_validated_through_b01():
    assert performed(performed_actions=("TEST-CHECK", "TEST-CLEAN")).performed_actions == ("TEST-CHECK", "TEST-CLEAN")
    for actions in [(), ("TEST-CHECK", "TEST-CHECK"), ("TEST-CHECK", "TEST-CLEAN", "TEST-REPLACE-REFILL"),
                    ("INVENTED",)]:
        with pytest.raises(ValueError, match="PM_PERFORMED_ACTION_INVALID"):
            performed(performed_actions=actions)
    for bad in (None, "", "INVENTED"):
        with pytest.raises(ValueError, match="PM_NOT_PERFORMED_REASON_REQUIRED"):
            outcome(reason_code=bad)
    with pytest.raises(ValueError, match="PM_APPROVED_REASON_SOURCE_REQUIRED"):
        outcome(approved_not_performed_reasons=frozenset())  # no vocabulary supplied -> fail closed
    with pytest.raises(ValueError, match="PM_APPROVED_ACTION_SOURCE_REQUIRED"):
        performed(approved_performed_actions=frozenset())


def test_b02b1_04_other_requires_written_explanation():
    for blank in (None, "", "   "):
        with pytest.raises(ValueError, match="PM_OTHER_REASON_TEXT_REQUIRED"):
            outcome(reason_code="TEST-OTHER", other_text=blank)
    assert outcome(reason_code="TEST-OTHER", other_text="รออะไหล่").other_text == "รออะไหล่"


def test_b02b1_05_frozen_source_identity_and_provenance_preserved():
    item = performed(evidence_attachment_ids=("SYNTH-ATT-1",), source_pm_work_result_id="SYNTH-PMWR-1")
    assert (item.pm_work_order_id, item.pm_task_id, item.revision_id) == ("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-1")
    assert (item.recorded_by, item.recorded_at, item.evidence_attachment_ids, item.source_pm_work_result_id) == (
        "SYNTH-TECH", T0, ("SYNTH-ATT-1",), "SYNTH-PMWR-1")
    for field, value in [("revision_id", "SYNTH-REV-2"), ("disposition", Disposition.NOT_PERFORMED),
                         ("recorded_by", "SYNTH-OTHER")]:
        with pytest.raises(ValidationError):
            setattr(item, field, value)  # frozen


def test_b02b1_06_unique_deterministic_outcome_identity():
    first = outcome()
    assert first.outcome_id == outcome(recorded_by="SYNTH-OTHER").outcome_id == performed().outcome_id
    assert first.outcome_id == pm_item_outcome_id("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-1")
    assert first.outcome_id.startswith("PMOC-") and len(first.outcome_id) == 5 + 24
    others = {pm_item_outcome_id(*ids) for ids in [("SYNTH-PMWO-2", "SYNTH-T1", "SYNTH-REV-1"),
                                                    ("SYNTH-PMWO-1", "SYNTH-T2", "SYNTH-REV-1"),
                                                    ("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-2")]}
    assert len(others) == 3 and first.outcome_id not in others
    # Domain-separated from the B02-A Outstanding id of the same source identity.
    assert first.outcome_id != pm_outstanding_source_identity("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-1").outstanding_id
    for ids in [("", "T", "R"), ("W", " ", "R"), ("W", "T", None)]:
        with pytest.raises(ValueError, match="PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"):
            pm_item_outcome_id(*ids)


def test_b02b1_07_08_fingerprint_separates_identical_replay_from_changed_payload():
    first = performed(evidence_attachment_ids=("SYNTH-ATT-1",))
    assert performed(evidence_attachment_ids=("SYNTH-ATT-1",)).creation_fingerprint == first.creation_fingerprint
    changed = [performed(performed_actions=("TEST-CLEAN",), evidence_attachment_ids=("SYNTH-ATT-1",)),
               performed(evidence_attachment_ids=("SYNTH-ATT-2",)),
               performed(evidence_attachment_ids=("SYNTH-ATT-1",), recorded_by="SYNTH-OTHER"),
               performed(evidence_attachment_ids=("SYNTH-ATT-1",), recorded_at=T0 + timedelta(minutes=1)),
               performed(evidence_attachment_ids=("SYNTH-ATT-1",), source_pm_work_result_id="SYNTH-PMWR-1"),
               outcome(evidence_attachment_ids=("SYNTH-ATT-1",))]
    for other in changed:
        assert other.outcome_id == first.outcome_id and other.creation_fingerprint != first.creation_fingerprint
    assert len({o.creation_fingerprint for o in changed}) == len(changed)


@pytest.mark.parametrize("update,code", [
    ({"disposition": Disposition.PERFORMED}, "PM_ITEM_OUTCOME_RECORD_INVALID"),  # NP reason kept, no action
    ({"reason_code": None}, "PM_ITEM_OUTCOME_RECORD_INVALID"),
    ({"reason_code": "  "}, "PM_ITEM_OUTCOME_RECORD_INVALID"),
    ({"performed_actions": ("TEST-CHECK",)}, "PM_ITEM_OUTCOME_RECORD_INVALID"),
    ({"evidence_attachment_ids": (" ",)}, "PM_ITEM_OUTCOME_RECORD_INVALID"),
    ({"source_pm_work_result_id": ""}, "PM_ITEM_OUTCOME_RECORD_INVALID"),
    ({"pm_task_id": " SYNTH-T1"}, "PM_ITEM_OUTCOME_IDENTITY_INVALID"),
    ({"revision_id": ""}, "PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"),
])
def test_b02b1_negative_tampered_record_is_refused(update, code):
    """An outcome copied around the B01 builder cannot be persisted as-is."""
    validate_pm_item_outcome_record(outcome())
    validate_pm_item_outcome_record(performed())
    with pytest.raises(ValueError, match=code):
        validate_pm_item_outcome_record(outcome().model_copy(update=update))


def test_b02b1_negative_performed_record_shape_is_rechecked():
    base = performed()
    for update in [{"performed_actions": ()}, {"performed_actions": ("A", "A")}, {"performed_actions": ("A", "B", "C")},
                   {"performed_actions": ("",)}, {"reason_code": "TEST-NOT-DONE"}, {"other_text": "x"}]:
        with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_RECORD_INVALID"):
            validate_pm_item_outcome_record(base.model_copy(update=update))


def test_b02b1_12_existing_models_b01_and_b02a_remain_compatible():
    # R4 PM Workflow: exactly the Owner-approved E01 A3 set (was the OPEN / CLOSED placeholder).
    assert {s.value for s in PmWorkOrderStatus} == {"OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED", "CANCELLED"}
    assert list(PmWorkResult.model_fields) == [
        "pm_work_result_id", "pm_work_order_id", "pm_task_id", "revision_id", "sequence", "task_description",
        "completed", "meter_snapshot_id", "remark", "used_parts", "evidence_attachment_ids", "performed_by",
        "performed_at"]
    np = outcome(source_pm_work_result_id="SYNTH-PMWR-1")
    assert "outcome_id" not in type(np).model_fields  # derived only: no stored, forgeable id field
    item = build_pm_outstanding_item(np, created_by="SYNTH-SUP", created_at=T0 + timedelta(hours=1))
    assert (item.origin_reason_code, item.origin_pm_work_result_id) == ("TEST-NOT-DONE", "SYNTH-PMWR-1")
    with pytest.raises(ValueError, match="PM_OUTSTANDING_REQUIRES_NOT_PERFORMED"):
        build_pm_outstanding_item(performed(), created_by="SYNTH-SUP", created_at=T0)


NEW_NAMES = ("pm_item_outcome_id", "validate_pm_item_outcome_record", "create_pm_item_outcome",
             "get_pm_item_outcome", "list_pm_item_outcomes", "_pm_item_outcomes")
ALLOWED = {Path("app/domain/pm.py"), Path("app/repositories/base.py"), Path("app/repositories/mock/repository.py")}


# R4 PM Workflow (Owner-approved phase, amending the B02-B2A guard): the
# authorized consumers are `app/domain/pm_service.py` (the workflow service)
# and the approved PM workflow routes in `app/api/v1/pm.py`. Everything else
# stays forbidden: other routes, API schemas, dependencies, other services, the
# Sheets adapter and the frontend. The checks below prove the exposure is
# exactly the approved route set and nothing else.
INTERNAL_SERVICE = Path("app/domain/pm_service.py")
PM_ROUTES = Path("app/api/v1/pm.py")
PM_SCHEMAS = Path("app/api/v1/pm_schemas.py")  # response models only
INTERNAL_METHODS = ("record_item_outcome", "list_item_outcomes", "list_outstanding_items", "list_asset_outstanding",
                    "resolve_outstanding", "start_work_order", "submit_for_review", "return_for_rework",
                    "close_after_review", "cancel_work_order", "list_work_order_history", "get_outstanding_item")
APPROVED_ROUTE_FUNCTIONS = {"start_pm_work_order", "submit_pm_work_order", "return_pm_work_order",
                            "cancel_pm_work_order", "close_pm_work_order", "record_pm_item_outcome",
                            "list_pm_item_outcomes", "list_pm_work_order_history", "list_pm_work_order_outstanding",
                            "list_pm_asset_outstanding", "resolve_pm_outstanding", "_outcome_response",
                            "_outstanding_response"}
APPROVED_ROUTE_PATHS = {"/pm/work-orders/{pm_work_order_id}/items/{pm_task_id}/outcome",
                        "/pm/work-orders/{pm_work_order_id}/outcomes",
                        "/pm/work-orders/{pm_work_order_id}/outstanding",
                        "/pm/outstanding", "/pm/outstanding/{outstanding_id}/resolve"}
INTERNAL_SCOPES = {"_authorize_outcome_access", "list_item_outcomes", "list_outstanding_items",
                   "record_item_outcome", "_store_item_outcome", "_store_outstanding_from", "_build_outcome",
                   "PmItemOutcomeRecording", "PmOutstandingState", "close_after_review", "cancel_work_order",
                   "_require_complete_accounting", "list_asset_outstanding", "_outstanding_state",
                   "get_outstanding_item", "resolve_outstanding", "_verify_later_pm", "_verify_later_repair"}


def _scopes_using(path: Path, names) -> set[str]:
    """Top-level functions / classes / class methods of `path` that use any of `names`."""
    scopes: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def visit(node, scope):
        for sub in ast.walk(node):
            used = (sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else None)
            if used in names:
                scopes.add(scope)

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ClassDef) and node.name == "PmService":
            for member in node.body:
                visit(member, getattr(member, "name", "PmService"))
        else:
            visit(node, getattr(node, "name", type(node).__name__))
    return scopes


def _all_routes(router) -> list:
    """Every route, descending into included routers (FastAPI wraps them)."""
    found = []
    for route in getattr(router, "routes", []):
        inner = getattr(route, "original_router", None)
        found.extend(_all_routes(inner) if inner is not None else [route])
    return found


def _assert_internal_only(names) -> None:
    """Negative guard: fails as soon as the workflow becomes reachable from any
    public path other than the approved PM workflow routes."""
    import inspect

    from app.main import create_app

    app_files = list((BACKEND / "app").rglob("*.py"))
    callers = sorted(str(p.relative_to(BACKEND)) for p in app_files
                     if p.relative_to(BACKEND) not in {INTERNAL_SERVICE, PM_ROUTES, PM_SCHEMAS}
                     and any(m in p.read_text(encoding="utf-8") for m in INTERNAL_METHODS))
    assert callers == []  # no other route module, dependency, schema or service calls the workflow
    app = create_app()
    routes = _all_routes(app)
    assert len(routes) > 100  # the walk really reaches the API routes
    exposed = {r.path for r in routes
               if {"outcome", "outcomes", "outstanding"} & set(getattr(r, "path", "").lower().split("/"))}
    assert exposed == APPROVED_ROUTE_PATHS
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        try:
            source = inspect.getsource(endpoint) if endpoint is not None else ""
        except (OSError, TypeError):
            source = ""
        if any(n in source for n in (*INTERNAL_METHODS, *names)):
            assert endpoint.__name__ in APPROVED_ROUTE_FUNCTIONS and endpoint.__module__ == "app.api.v1.pm"
    assert _scopes_using(BACKEND / PM_ROUTES, set(INTERNAL_METHODS) | set(names)) <= APPROVED_ROUTE_FUNCTIONS
    frontend = BACKEND.parent / "frontend" / "src"
    if frontend.is_dir():
        assert not [p for p in frontend.rglob("*.ts*")
                    if any(m in p.read_text(encoding="utf-8") for m in INTERNAL_METHODS)]
    # Inside the service only the workflow methods use these names; the legacy
    # result / close / scope paths never do.
    assert _scopes_using(BACKEND / INTERNAL_SERVICE, set(names)) <= INTERNAL_SCOPES

def test_b02b1_14_15_new_functionality_is_dormant_and_absent_from_sheets():
    users = sorted(str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
                   if any(n in p.read_text(encoding="utf-8") for n in NEW_NAMES)
                   and p.relative_to(BACKEND) not in ALLOWED | {INTERNAL_SERVICE, PM_ROUTES, PM_SCHEMAS})
    assert users == []  # no route, schema, dependency, other service or Sheets adapter uses B02-B1
    for path in (BACKEND / "app/repositories/google_sheets").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "outcome_id" not in text and "pm_item_outcome" not in text
    for path in ALLOWED:  # every touched module still parses
        ast.parse((BACKEND / path).read_text(encoding="utf-8"))


def test_b02b1_14b_internal_service_use_is_not_reachable_from_runtime():
    """R4 PM Workflow: B02-B1 is reachable only through the workflow service and
    the approved PM workflow routes — no other public path, dependency or frontend use."""
    _assert_internal_only(NEW_NAMES)
