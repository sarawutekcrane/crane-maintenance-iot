"""B01 Rev2: pure contract tests only, no application runtime mutation."""
import pytest
from app.domain.pm import (
    PmE01ContractAction as Action, PmE01ContractState as State,
    PmItemContractDisposition as Disposition, PmWorkOrderStatus, PmWorkResult,
    assess_pm_contract_completion, pm_e01_contract_transition, pm_e01_state,
    validate_pm_item_contract,
)

# Synthetic markers: NOT Owner's business codes. The production vocabulary must
# come from an approved source, not from this test module.
REASONS = frozenset({"TEST-NOT-DONE", "TEST-OTHER"})
ACTIONS = frozenset({"TEST-CHECK", "TEST-CLEAN", "TEST-REPLACE-REFILL"})


def check(disposition, **kwargs):
    return validate_pm_item_contract(
        disposition, approved_not_performed_reasons=REASONS,
        approved_other_reason_code="TEST-OTHER",
        approved_performed_actions=ACTIONS, **kwargs,
    )


def test_b01_01_lifecycle_approved_edges():
    assert pm_e01_contract_transition(State.OPEN, Action.START) == State.IN_PROGRESS
    assert pm_e01_contract_transition(State.IN_PROGRESS, Action.SUBMIT) == State.PENDING_REVIEW
    assert pm_e01_contract_transition(State.PENDING_REVIEW, Action.RETURN, return_reason="แก้ไข") == State.IN_PROGRESS
    assert pm_e01_contract_transition(State.PENDING_REVIEW, Action.CLOSE) == State.CLOSED


@pytest.mark.parametrize("state,action", [
    (State.OPEN, Action.CLOSE), (State.CLOSED, Action.START),
    (State.IN_PROGRESS, Action.CLOSE), (State.CANCELLED, Action.SUBMIT),
])
def test_b01_02_illegal_edges(state, action):
    with pytest.raises(ValueError, match="PM_E01_INVALID_TRANSITION"):
        pm_e01_contract_transition(state, action)


def test_b01_03_not_performed_reason_is_mandatory():
    with pytest.raises(ValueError, match="PM_NOT_PERFORMED_REASON_REQUIRED"):
        check(Disposition.NOT_PERFORMED)
    check(Disposition.NOT_PERFORMED, reason_code="TEST-NOT-DONE")
    with pytest.raises(ValueError, match="PM_NOT_PERFORMED_REASON_REQUIRED"):
        check(Disposition.NOT_PERFORMED, reason_code="NOT-APPROVED")


def test_b01_04_other_requires_explanation():
    with pytest.raises(ValueError, match="PM_OTHER_REASON_TEXT_REQUIRED"):
        check(Disposition.NOT_PERFORMED, reason_code="TEST-OTHER", other_text="  ")
    check(Disposition.NOT_PERFORMED, reason_code="TEST-OTHER", other_text="ทดสอบ")


def test_b01_05_zero_actual_work_rejected():
    with pytest.raises(ValueError, match="PM_ZERO_ACTUAL_WORK_FORBIDDEN"):
        assess_pm_contract_completion(in_scope_task_ids=tuple("abcde"),
            performed_task_ids=(), accounted_not_performed_ids=tuple("abcde"))


def test_b01_06_partial_requires_outstanding():
    assert assess_pm_contract_completion(in_scope_task_ids=tuple("abcde"),
        performed_task_ids=tuple("abcd"), accounted_not_performed_ids=("e",)) == ("PARTIAL", ("e",))
    for p, n in [(('a',), ()), (('a', 'a'), ('b',)), (('a',), ('a', 'b'))]:
        with pytest.raises(ValueError, match="PM_ITEM_SCOPE_ACCOUNTING_INVALID"):
            assess_pm_contract_completion(in_scope_task_ids=('a', 'b'),
                performed_task_ids=p, accounted_not_performed_ids=n)


def test_b01_07_complete_five_of_five():
    assert assess_pm_contract_completion(in_scope_task_ids=tuple("abcde"),
        performed_task_ids=tuple("abcde"), accounted_not_performed_ids=()) == ("COMPLETE", ())


def test_b01_08_old_open_closed_enum_unchanged():
    # R4 PM Workflow (Owner E01 A3, EV-044): the runtime status is exactly the approved
    # E01 lifecycle (was: only OPEN / CLOSED). The original OPEN / CLOSED values keep
    # their exact spelling, so every historical work order still parses unchanged.
    assert {s.value for s in PmWorkOrderStatus} == {
        "OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED", "CANCELLED"}
    assert PmWorkOrderStatus("OPEN") == PmWorkOrderStatus.OPEN
    assert PmWorkOrderStatus("CLOSED") == PmWorkOrderStatus.CLOSED
    for unapproved in ("COMPLETED", "DONE", "PARTIAL", "open"):
        with pytest.raises(ValueError):
            PmWorkOrderStatus(unapproved)


def test_b01_09_existing_immutable_result_has_no_new_update_fields():
    fields = PmWorkResult.model_fields
    assert fields["completed"].annotation is bool
    assert "disposition" not in fields and "outstanding" not in fields
    assert "revision_id" in fields and "task_description" in fields


def test_b01_10_contract_is_dormant_and_not_runtime_enum():
    # R4 PM Workflow (was: the contract was dormant, PENDING_REVIEW was not a runtime value):
    # the contract stays a separate pure type, and the transition validator and the runtime
    # statuses now agree exactly: same value set, every validator outcome is a runtime
    # status, and every runtime status maps 1:1 onto a contract state.
    assert State is not PmWorkOrderStatus
    assert {v.value for v in PmWorkOrderStatus} == {v.value for v in State}
    for status in PmWorkOrderStatus:
        assert pm_e01_state(status) == State(status.value)
    proven_cancel = {"cancellation_eligibility_proven": True, "cancellation_reason": "เหตุผล"}
    reachable = set()
    for state in State:
        for action in Action:
            kwargs = {"return_reason": "แก้ไข"} if action == Action.RETURN else (
                proven_cancel if action == Action.CANCEL else {})
            try:
                target = pm_e01_contract_transition(state, action, **kwargs)
            except ValueError:
                continue
            reachable.add((state, action, target))
            assert PmWorkOrderStatus(target.value).value == target.value
    assert reachable == {
        (State.OPEN, Action.START, State.IN_PROGRESS),
        (State.IN_PROGRESS, Action.SUBMIT, State.PENDING_REVIEW),
        (State.PENDING_REVIEW, Action.RETURN, State.IN_PROGRESS),
        (State.PENDING_REVIEW, Action.CLOSE, State.CLOSED),
        (State.OPEN, Action.CANCEL, State.CANCELLED),
        (State.IN_PROGRESS, Action.CANCEL, State.CANCELLED),
    }  # terminal CLOSED / CANCELLED have no outgoing edge
    assert "status" not in PmWorkResult.model_fields  # a factual result never carries a status


def test_b01_11_cancel_only_open_or_in_progress_zero_work_and_proven():
    for state in (State.OPEN, State.IN_PROGRESS):
        assert pm_e01_contract_transition(state, Action.CANCEL,
            cancellation_eligibility_proven=True,
            cancellation_reason="ไม่สามารถดำเนินงาน") == State.CANCELLED
    for state in (State.PENDING_REVIEW, State.CLOSED, State.CANCELLED):
        with pytest.raises(ValueError, match="PM_CANCEL_NOT_ELIGIBLE"):
            pm_e01_contract_transition(state, Action.CANCEL,
                cancellation_eligibility_proven=True, cancellation_reason="เหตุผล")
    for kwargs in ({"actual_performed_count": 1}, {"existing_result_count": 1},
                   {"existing_evidence_count": 1}):
        with pytest.raises(ValueError, match="PM_CANCEL_NOT_ELIGIBLE"):
            pm_e01_contract_transition(State.OPEN, Action.CANCEL,
                cancellation_eligibility_proven=True, cancellation_reason="เหตุผล", **kwargs)
    with pytest.raises(ValueError, match="PM_CANCEL_NOT_ELIGIBLE"):
        pm_e01_contract_transition(State.OPEN, Action.CANCEL, cancellation_reason="เหตุผล")
    with pytest.raises(ValueError, match="PM_CANCEL_NOT_ELIGIBLE"):
        pm_e01_contract_transition(State.OPEN, Action.CANCEL,
            cancellation_eligibility_proven=True)


def test_b01_12_return_requires_reason():
    with pytest.raises(ValueError, match="PM_RETURN_REASON_REQUIRED"):
        pm_e01_contract_transition(State.PENDING_REVIEW, Action.RETURN)


def test_b01_13_performed_requires_one_or_two_approved_distinct_actions():
    for actions in [(), ("TEST-CHECK", "TEST-CLEAN", "TEST-REPLACE-REFILL"),
                    ("TEST-CHECK", "TEST-CHECK"), ("INVENTED",)]:
        with pytest.raises(ValueError, match="PM_PERFORMED_ACTION_INVALID"):
            check(Disposition.PERFORMED, performed_actions=actions)
    check(Disposition.PERFORMED, performed_actions=("TEST-CHECK",))
    check(Disposition.PERFORMED, performed_actions=("TEST-CHECK", "TEST-CLEAN"))
    with pytest.raises(ValueError, match="PM_PERFORMED_REASON_CONFLICT"):
        check(Disposition.PERFORMED, performed_actions=("TEST-CHECK",), reason_code="TEST-NOT-DONE")
    with pytest.raises(ValueError, match="PM_NOT_PERFORMED_ACTION_CONFLICT"):
        check(Disposition.NOT_PERFORMED, reason_code="TEST-NOT-DONE", performed_actions=("TEST-CHECK",))


def test_b01_14_reject_missing_official_reason_or_action_source():
    with pytest.raises(ValueError, match="PM_APPROVED_REASON_SOURCE_REQUIRED"):
        validate_pm_item_contract(Disposition.NOT_PERFORMED,
            approved_not_performed_reasons=frozenset(),
            approved_other_reason_code="TEST-OTHER")
    with pytest.raises(ValueError, match="PM_APPROVED_ACTION_SOURCE_REQUIRED"):
        validate_pm_item_contract(Disposition.PERFORMED,
            approved_not_performed_reasons=REASONS,
            approved_other_reason_code="TEST-OTHER",
            performed_actions=("TEST-CHECK",))
