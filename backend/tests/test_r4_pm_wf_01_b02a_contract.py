"""R4-PM-WF-01 B02-A: pure contract tests (A01 outcome, A02 Outstanding,
A03 resolution reference). No repository, runtime, API or Sheets access."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.pm import (
    PmItemContractDisposition as Disposition,
    PmOutstandingResolutionReference,
    PmWorkOrderStatus,
    PmWorkResult,
    build_pm_item_outcome,
    build_pm_outstanding_item,
    pm_outstanding_source_identity,
    validate_pm_outstanding_resolution_reference,
)

# Synthetic markers: NOT Owner's business codes. The production vocabulary must
# come from an approved source, not from this test module.
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


def outstanding(**kwargs):
    return build_pm_outstanding_item(outcome(**kwargs), created_by="SYNTH-SUP", created_at=T0 + timedelta(hours=1))


def test_b02a_01_performed_requires_one_or_two_distinct_approved_actions():
    for actions in [("TEST-CHECK",), ("TEST-CHECK", "TEST-CLEAN")]:
        assert outcome(Disposition.PERFORMED, performed_actions=actions).performed_actions == actions
    for actions in [(), ("TEST-CHECK", "TEST-CLEAN", "TEST-REPLACE-REFILL"), ("TEST-CHECK", "TEST-CHECK"),
                    ("INVENTED",)]:
        with pytest.raises(ValueError, match="PM_PERFORMED_ACTION_INVALID"):
            outcome(Disposition.PERFORMED, performed_actions=actions)
    with pytest.raises(ValueError, match="PM_PERFORMED_REASON_CONFLICT"):
        outcome(Disposition.PERFORMED, performed_actions=("TEST-CHECK",), reason_code="TEST-NOT-DONE")


def test_b02a_02_not_performed_requires_an_approved_reason():
    assert outcome().reason_code == "TEST-NOT-DONE"
    for bad in (None, "", "NOT-APPROVED"):
        with pytest.raises(ValueError, match="PM_NOT_PERFORMED_REASON_REQUIRED"):
            outcome(reason_code=bad)
    with pytest.raises(ValueError, match="PM_NOT_PERFORMED_ACTION_CONFLICT"):
        outcome(performed_actions=("TEST-CHECK",))


def test_b02a_03_other_reason_requires_written_explanation():
    for blank in (None, "", "   "):
        with pytest.raises(ValueError, match="PM_OTHER_REASON_TEXT_REQUIRED"):
            outcome(reason_code="TEST-OTHER", other_text=blank)
    assert outcome(reason_code="TEST-OTHER", other_text="พื้นที่ปิดซ่อม").other_text == "พื้นที่ปิดซ่อม"


def test_b02a_04_outstanding_preserves_frozen_source_identity():
    item = outstanding(other_text=None, source_pm_work_result_id="SYNTH-PMWR-9")
    assert (item.pm_work_order_id, item.pm_task_id, item.revision_id) == ("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-1")
    assert (item.origin_reason_code, item.origin_recorded_by, item.origin_recorded_at,
            item.origin_pm_work_result_id) == ("TEST-NOT-DONE", "SYNTH-TECH", T0, "SYNTH-PMWR-9")
    same = pm_outstanding_source_identity("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-1")
    assert item.outstanding_id == same.outstanding_id == outstanding().outstanding_id  # stable
    assert item.outstanding_id != pm_outstanding_source_identity("SYNTH-PMWO-1", "SYNTH-T1", "SYNTH-REV-2").outstanding_id
    assert item.outstanding_id != pm_outstanding_source_identity("SYNTH-PMWO-2", "SYNTH-T1", "SYNTH-REV-1").outstanding_id
    with pytest.raises(ValidationError):
        item.revision_id = "SYNTH-REV-2"  # frozen
    assert not {"status", "state", "resolved", "resolved_at"} & set(type(item).model_fields)  # no lifecycle codes


def test_b02a_04n_missing_or_invalid_source_identity_is_refused():
    for wo, task, rev in [("", "T", "R"), ("W", "  ", "R"), ("W", "T", None)]:
        with pytest.raises(ValueError, match="PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"):
            pm_outstanding_source_identity(wo, task, rev)
    with pytest.raises(ValueError, match="PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"):
        outcome(pm_task_id=" ")
    with pytest.raises(ValueError, match="PM_OUTSTANDING_REQUIRES_NOT_PERFORMED"):
        build_pm_outstanding_item(outcome(Disposition.PERFORMED, performed_actions=("TEST-CHECK",)),
                                  created_by="SYNTH-SUP", created_at=T0)


def test_b02a_06_creation_fingerprint_separates_replay_from_conflict():
    first = outstanding()
    replay = build_pm_outstanding_item(outcome(), created_by="SYNTH-OTHER", created_at=T0 + timedelta(days=1))
    assert replay.creation_fingerprint == first.creation_fingerprint  # same identity + same origin
    conflict = outstanding(reason_code="TEST-OTHER", other_text="อื่น ๆ")
    assert conflict.outstanding_id == first.outstanding_id and conflict.creation_fingerprint != first.creation_fingerprint


def test_b02a_08_resolution_reference_is_provenance_only_never_proof():
    item = outstanding(source_pm_work_result_id="SYNTH-PMWR-9")
    before = item.model_dump()
    ref = PmOutstandingResolutionReference(outstanding_id=item.outstanding_id, later_pm_work_result_id="SYNTH-PMWR-20",
                                           evidence_attachment_ids=("SYNTH-ATT-1",), referenced_by="SYNTH-SUP",
                                           referenced_at=T0 + timedelta(days=2))
    assert validate_pm_outstanding_resolution_reference(ref, item) is None  # validates; resolves nothing
    repair_ref = ref.model_copy(update={"later_pm_work_result_id": None, "later_repair_id": "SYNTH-RPR-3"})
    assert validate_pm_outstanding_resolution_reference(repair_ref, item) is None
    assert item.model_dump() == before  # original Outstanding and its origin provenance untouched
    import app.domain.pm as pm_module
    assert not [n for n in vars(pm_module) if "resolve" in n.lower() and "reference" not in n.lower()]


@pytest.mark.parametrize("update,code", [
    ({"outstanding_id": "PMOS-OTHER"}, "PM_RESOLUTION_REFERENCE_OUTSTANDING_MISMATCH"),
    ({"later_pm_work_result_id": None}, "PM_RESOLUTION_REFERENCE_SOURCE_INVALID"),
    ({"later_repair_id": "SYNTH-RPR-3"}, "PM_RESOLUTION_REFERENCE_SOURCE_INVALID"),
    ({"later_pm_work_result_id": "SYNTH-PMWR-9"}, "PM_RESOLUTION_REFERENCE_SELF"),
    ({"evidence_attachment_ids": ()}, "PM_RESOLUTION_REFERENCE_EVIDENCE_REQUIRED"),
    ({"evidence_attachment_ids": (" ",)}, "PM_RESOLUTION_REFERENCE_EVIDENCE_REQUIRED"),
    ({"referenced_at": T0}, "PM_RESOLUTION_REFERENCE_PREDATES_OUTSTANDING"),
])
def test_b02a_08n_invalid_resolution_reference_evidence_is_refused(update, code):
    item = outstanding(source_pm_work_result_id="SYNTH-PMWR-9")
    ref = PmOutstandingResolutionReference(outstanding_id=item.outstanding_id, later_pm_work_result_id="SYNTH-PMWR-20",
                                           evidence_attachment_ids=("SYNTH-ATT-1",),
                                           referenced_at=T0 + timedelta(days=2)).model_copy(update=update)
    with pytest.raises(ValueError, match=code):
        validate_pm_outstanding_resolution_reference(ref, item)


def test_b02a_10_existing_immutable_models_unchanged():
    assert {s.value for s in PmWorkOrderStatus} == {"OPEN", "CLOSED"}
    fields = PmWorkResult.model_fields
    assert fields["completed"].annotation is bool
    assert not {"disposition", "outstanding", "performed_actions", "reason_code"} & set(fields)


def test_b02a_negative_missing_approved_vocabulary_fails_closed():
    with pytest.raises(ValueError, match="PM_APPROVED_REASON_SOURCE_REQUIRED"):
        outcome(approved_not_performed_reasons=frozenset())
    with pytest.raises(ValueError, match="PM_APPROVED_ACTION_SOURCE_REQUIRED"):
        outcome(Disposition.PERFORMED, performed_actions=("TEST-CHECK",), approved_performed_actions=frozenset())


B02A_NAMES = ("PmItemOutcome", "build_pm_item_outcome", "PmOutstandingSourceIdentity", "pm_outstanding_source_identity",
              "PmOutstandingItem", "build_pm_outstanding_item", "PmOutstandingResolutionReference",
              "validate_pm_outstanding_resolution_reference", "create_pm_outstanding_item",
              "get_pm_outstanding_item", "list_pm_outstanding_items")
ALLOWED = {Path("app/domain/pm.py"), Path("app/repositories/base.py"), Path("app/repositories/mock/repository.py")}


# R4-PM-WF-01 B02-B2A (Owner-authorized amendment): `app/domain/pm_service.py`
# is the one authorized INTERNAL consumer. Everything else stays forbidden:
# routes, API schemas, dependencies, other services, the Sheets adapter and the
# frontend. The checks below prove that use stays internal and unreachable.
INTERNAL_SERVICE = Path("app/domain/pm_service.py")
INTERNAL_METHODS = ("record_item_outcome", "list_item_outcomes", "list_outstanding_items")
INTERNAL_SCOPES = {"_authorize_outcome_access", "list_item_outcomes", "list_outstanding_items",
                   "record_item_outcome", "_store_item_outcome", "_store_outstanding_from",
                   "PmItemOutcomeRecording"}


def _scopes_using(path: Path, names) -> set[str]:
    """Top-level functions / classes / PmService methods of `path` that use any of `names`."""
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


def _assert_internal_only(names) -> None:
    """Negative guard: fails as soon as the internal service use becomes
    reachable from a public API or any other runtime consumer."""
    import inspect

    from app.main import create_app

    app_files = list((BACKEND / "app").rglob("*.py"))
    callers = sorted(str(p.relative_to(BACKEND)) for p in app_files
                     if p.relative_to(BACKEND) != INTERNAL_SERVICE
                     and any(m in p.read_text(encoding="utf-8") for m in INTERNAL_METHODS))
    assert callers == []  # no route, dependency, schema or other service calls the internal methods
    for route in create_app().routes:
        assert not {"outcome", "outstanding"} & set(getattr(route, "path", "").lower().replace("-", "/").split("/"))
        endpoint = getattr(route, "endpoint", None)
        try:
            source = inspect.getsource(endpoint) if endpoint is not None else ""
        except (OSError, TypeError):
            source = ""
        assert not any(n in source for n in (*INTERNAL_METHODS, *names))
    frontend = BACKEND.parent / "frontend" / "src"
    if frontend.is_dir():
        assert not [p for p in frontend.rglob("*.ts*")
                    if any(m in p.read_text(encoding="utf-8") for m in INTERNAL_METHODS)]
    # Inside the service only the B02-B2A methods use these names; the legacy
    # result / close / scope paths never do.
    assert _scopes_using(BACKEND / INTERNAL_SERVICE, set(names)) <= INTERNAL_SCOPES


def test_b02a_12_new_functionality_is_dormant():
    users = sorted(str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
                   if any(n in p.read_text(encoding="utf-8") for n in B02A_NAMES)
                   and p.relative_to(BACKEND) not in ALLOWED | {INTERNAL_SERVICE})
    assert users == []  # no route, schema, dependency, other service or Sheets adapter uses B02-A
    sheets = (BACKEND / "app/repositories/google_sheets").rglob("*.py")
    assert not any("outstanding" in p.read_text(encoding="utf-8").lower() for p in sheets)
    for path in ALLOWED:  # every module still parses
        ast.parse((BACKEND / path).read_text(encoding="utf-8"))


def test_b02a_12b_internal_service_use_is_not_reachable_from_runtime():
    """B02-B2A: the authorized internal service use of B02-A stays
    unreachable from every public API, route, dependency and the frontend."""
    _assert_internal_only(B02A_NAMES)
