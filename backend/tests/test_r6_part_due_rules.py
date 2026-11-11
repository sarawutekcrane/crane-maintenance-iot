"""R6 — INSPECT / REPAIR / REPLACE due evaluation (FINAL plan §7.4, §7.4b;
C3 CYCLE, C4 combinations, C8 calendar, AP-14, AP-18). Synthetic TEST rules
only — no real interval exists (G01 / G02 SOURCE-DATA-REQUIRED)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.domain.lifetime_rule import (
    DueAction,
    IntervalUnit,
    LifetimeRule,
    LifetimeRuleScope,
    LifetimeTriggerType,
    RuleCombination,
)
from app.domain.part_lifetime_due import (
    CalendarInputs,
    RuleInputs,
    add_months,
    combine_earliest,
    evaluate_rule,
)
from app.domain.part_usage import PolicyContext, Quantity
from app.domain.vehicle_model import ComponentRole

TEST = PolicyContext("TEST")
REAL = PolicyContext("REAL")
TODAY = date(2026, 11, 10)
NO_CAL = CalendarInputs(None, False)


def rule(trigger=LifetimeTriggerType.ENGINE_HOUR, *, action=DueAction.REPLACE, interval=5000.0, unit=IntervalUnit.HOUR,
         first=None, group=None, rid="LTR-T") -> LifetimeRule:
    return LifetimeRule(lifetime_rule_id=rid, part_id="P", scope=LifetimeRuleScope.MODEL, model_id="M",
                        trigger_type=trigger, component_role=ComponentRole.CARRIER_ENGINE
                        if trigger == LifetimeTriggerType.ENGINE_HOUR else None,
                        first_due_value=first, interval_value=interval, created_at=datetime.now(timezone.utc),
                        due_action=action, interval_unit=unit, condition_group_key=group,
                        combination=RuleCombination.EARLIEST if group else None)


def known(value: float, policy: str | None = "APPROVED") -> Quantity:
    return Quantity(value, "KNOWN", policy)


def unknown(*reasons: str) -> Quantity:
    return Quantity(None, "UNKNOWN", None, reasons)


def ev(r, inputs, cal=NO_CAL, policy=TEST, today=TODAY):
    return evaluate_rule(r, inputs, cal, policy, today, target_type="PART_INSTANCE", target_id="PI", lifecycle_id="L1")


# ---- calendar arithmetic (6 months != 180 days) ----


@pytest.mark.parametrize("anchor,months,expected", [
    (date(2026, 1, 31), 1, date(2026, 2, 28)),
    (date(2028, 1, 31), 1, date(2028, 2, 29)),
    (date(2026, 1, 31), 2, date(2026, 3, 31)),     # from the anchor, not chained via 28 Feb
    (date(2028, 2, 29), 12, date(2029, 2, 28)),
    (date(2028, 2, 29), 48, date(2032, 2, 29)),
    (date(2026, 4, 30), 6, date(2026, 10, 30)),
    (date(2026, 8, 31), 6, date(2027, 2, 28)),
])
def test_add_months_clamps_from_the_anchor(anchor, months, expected) -> None:
    assert add_months(anchor, months) == expected


def test_six_months_is_not_180_days() -> None:
    anchor = date(2026, 1, 1)
    assert add_months(anchor, 6) != anchor + timedelta(days=180)
    r = rule(LifetimeTriggerType.CALENDAR, action=DueAction.INSPECT, interval=6, unit=IntervalUnit.MONTH)
    day_181 = anchor + timedelta(days=180)  # 30 Jun: NOT due yet; due on 1 Jul
    assert ev(r, RuleInputs(known(0)), CalendarInputs(anchor, False), today=day_181).status == "NOT_DUE"
    assert ev(r, RuleInputs(known(0)), CalendarInputs(anchor, False), today=date(2026, 7, 1)).status == "DUE"


def test_calendar_is_pending_in_real_and_test_proposed_in_test() -> None:
    r = rule(LifetimeTriggerType.CALENDAR, interval=12, unit=IntervalUnit.MONTH)
    real = ev(r, RuleInputs(known(0)), CalendarInputs(date(2025, 1, 1), True), policy=REAL)
    assert real.status == "UNKNOWN" and real.policy_state == "PENDING"
    assert {"CALENDAR_POLICY_PENDING", "CALENDAR_STORAGE_POLICY_PENDING"} <= set(real.reasons)
    test = ev(r, RuleInputs(known(0)), CalendarInputs(date(2025, 1, 1), True))
    assert test.status == "DUE" and test.policy_state == "TEST_PROPOSED"
    assert "CALENDAR_AGEING_IN_STORAGE_PROPOSED" in test.reasons
    missing = ev(r, RuleInputs(known(0)), CalendarInputs(None, False))
    assert missing.status == "UNKNOWN" and "CALENDAR_ANCHOR_MISSING" in missing.reasons
    days = ev(rule(LifetimeTriggerType.CALENDAR, interval=10, unit=IntervalUnit.DAY), RuleInputs(known(0)),
              CalendarInputs(date(2026, 11, 1), False))
    assert days.next_due_date == date(2026, 11, 11) and days.status == "NOT_DUE"


# ---- meter-based REPLACE / INSPECT ----


def test_replace_due_at_threshold_even_if_working_and_unknown_base_is_unknown() -> None:
    due = ev(rule(), RuleInputs(known(5000)))
    assert (due.status, due.current_value, due.next_due_value, due.remaining) == ("DUE", 5000.0, 5000.0, 0.0)
    assert ev(rule(), RuleInputs(known(4999.9))).status == "NOT_DUE"
    unk = ev(rule(), RuleInputs(unknown("METER_EVIDENCE_MISSING")))
    assert unk.status == "UNKNOWN" and "METER_EVIDENCE_MISSING" in unk.reasons


def test_first_due_applies_only_to_the_enrolment_cycle() -> None:
    r = rule(first=1000.0)
    assert ev(r, RuleInputs(known(1200), cycle_number=1)).status == "DUE"
    assert ev(r, RuleInputs(known(1200), cycle_number=2)).status == "NOT_DUE"


def test_inspection_event_never_changes_replace_and_progression_is_pending_in_real() -> None:
    replace = ev(rule(), RuleInputs(known(6000), since_event_base=known(10), event_date=TODAY))
    assert replace.status == "DUE"  # the event is ignored by REPLACE
    inspect = rule(action=DueAction.INSPECT, interval=500.0)
    before_event = ev(inspect, RuleInputs(known(600)))
    assert before_event.status == "DUE"
    after_test = ev(inspect, RuleInputs(known(600), since_event_base=known(100), event_date=TODAY))
    assert after_test.status == "NOT_DUE" and after_test.policy_state == "TEST_PROPOSED"
    after_real = ev(inspect, RuleInputs(known(600), since_event_base=known(100), event_date=TODAY), policy=REAL)
    assert after_real.status == "UNKNOWN" and "INSPECTION_PROGRESSION_POLICY_PENDING" in after_real.reasons


@pytest.mark.parametrize("trigger,reason", [
    (LifetimeTriggerType.CYCLE, "UNSUPPORTED_PENDING_POLICY"),
    (LifetimeTriggerType.PTO_HOUR, "PTO_NOT_APPROVED_FOR_PART_LIFETIME"),
])
def test_cycle_and_pto_are_fail_closed(trigger, reason) -> None:
    result = ev(rule(trigger, unit=None), RuleInputs(known(99999)))
    assert result.status == "UNKNOWN" and reason in result.reasons and result.policy_state == "PENDING"


def test_missing_action_unit_or_interval_is_unknown_never_defaulted() -> None:
    assert "DUE_ACTION_NOT_DECLARED" in ev(rule(action=None), RuleInputs(known(1))).reasons
    assert "UNIT_NOT_DECLARED" in ev(rule(unit=None), RuleInputs(known(1))).reasons
    assert "UNIT_MISMATCH" in ev(rule(unit=IntervalUnit.KM), RuleInputs(known(1))).reasons
    assert "INTERVAL_NOT_DECLARED" in ev(rule(interval=None), RuleInputs(known(1))).reasons


def test_earliest_group_due_if_any_due_and_unknown_dominates_not_due() -> None:
    hours_due = ev(rule(rid="A", group="G"), RuleInputs(known(6000)))
    calendar_not = ev(rule(LifetimeTriggerType.CALENDAR, interval=12, unit=IntervalUnit.MONTH, rid="B", group="G"),
                      RuleInputs(known(0)), CalendarInputs(TODAY, False))
    hours_unknown = ev(rule(rid="C", group="G"), RuleInputs(unknown("X")))
    kw = dict(target_type="PART_INSTANCE", target_id="PI", lifecycle_id="L1")
    assert combine_earliest("G", [hours_due, calendar_not], **kw).status == "DUE"
    assert combine_earliest("G", [hours_unknown, calendar_not], **kw).status == "UNKNOWN"
    assert combine_earliest("G", [calendar_not], **kw).status == "NOT_DUE"
    assert combine_earliest("G", [hours_due, calendar_not], **kw).due_key.endswith(":GROUP:G:L1:REPLACE")


def test_due_key_changes_with_the_cycle() -> None:
    a = evaluate_rule(rule(), RuleInputs(known(1)), NO_CAL, TEST, TODAY, target_type="T", target_id="I",
                      lifecycle_id="L1")
    b = evaluate_rule(rule(), RuleInputs(known(1)), NO_CAL, TEST, TODAY, target_type="T", target_id="I",
                      lifecycle_id="L2")
    assert a.due_key != b.due_key


# ---- rule creation validation (API) ----


BASE = {"part_id": "PART-0005", "scope": "MODEL", "model_id": "MODEL-0003", "trigger_type": "ENGINE_HOUR",
        "component_role": "CARRIER_ENGINE", "interval_value": 100, "interval_unit": "HOUR", "due_action": "REPLACE"}


@pytest.mark.asyncio
async def test_pto_hour_rules_are_refused_and_cycle_rules_stay_creatable(client: AsyncClient) -> None:
    pto = await client.post("/api/v1/lifetime-rules", json=BASE | {"trigger_type": "PTO_HOUR", "component_role": "PTO",
                                                                   "interval_unit": None})
    assert pto.status_code == 422 and pto.json()["error"]["code"] == "PTO_NOT_APPROVED_FOR_PART_LIFETIME"
    cycle = await client.post("/api/v1/lifetime-rules", json=BASE | {"trigger_type": "CYCLE", "component_role": None,
                                                                     "interval_unit": None})
    assert cycle.status_code == 200 and cycle.json()["trigger_type"] == "CYCLE"


@pytest.mark.asyncio
async def test_unit_combination_and_group_compatibility_are_validated(client: AsyncClient) -> None:
    bad_unit = await client.post("/api/v1/lifetime-rules", json=BASE | {"interval_unit": "KM"})
    assert bad_unit.status_code == 422 and bad_unit.json()["error"]["code"] == "UNIT_MISMATCH"
    unsupported = await client.post("/api/v1/lifetime-rules", json=BASE | {"condition_group_key": "G1",
                                                                            "combination": "LATEST"})
    assert unsupported.status_code == 422 and unsupported.json()["error"]["code"] == "COMBINATION_UNSUPPORTED"
    ok = await client.post("/api/v1/lifetime-rules", json=BASE | {"condition_group_key": "G1", "combination": "EARLIEST"})
    assert ok.status_code == 200
    calendar_member = await client.post("/api/v1/lifetime-rules", json=BASE | {
        "trigger_type": "CALENDAR", "component_role": None, "interval_value": 6, "interval_unit": "MONTH",
        "condition_group_key": "G1", "combination": "EARLIEST"})
    assert calendar_member.status_code == 200
    mismatch = await client.post("/api/v1/lifetime-rules", json=BASE | {"due_action": "INSPECT",
                                                                        "condition_group_key": "G1",
                                                                        "combination": "EARLIEST"})
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "CONDITION_GROUP_INCOMPATIBLE"
    half = await client.post("/api/v1/lifetime-rules", json=BASE | {"condition_group_key": "G2"})
    assert half.status_code == 422


@pytest.mark.asyncio
async def test_maintenance_event_anchors_inspect_only_and_rule_must_match(client: AsyncClient) -> None:
    replace = (await client.post("/api/v1/lifetime-rules", json=BASE)).json()["lifetime_rule_id"]
    inspect = (await client.post("/api/v1/lifetime-rules", json=BASE | {"due_action": "INSPECT"})).json()[
        "lifetime_rule_id"]
    created = await client.post("/api/v1/part-instances", headers={"X-Request-Id": str(uuid.uuid4())},
                                json={"part_id": "PART-0005", "tag_label": "TAG-ME", "prior_usage": {"quality": "UNKNOWN"}})
    iid = created.json()["instance"]["part_instance_id"]
    def h() -> dict:
        return {"X-Request-Id": str(uuid.uuid4())}
    refused = await client.post(f"/api/v1/part-instances/{iid}/maintenance-events", headers=h(),
                                json={"action": "INSPECTED", "lifetime_rule_id": replace})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "MAINTENANCE_RULE_MISMATCH"
    ok = await client.post(f"/api/v1/part-instances/{iid}/maintenance-events", headers=h(),
                           json={"action": "INSPECTED", "lifetime_rule_id": inspect, "outcome": "PASS"})
    assert ok.status_code == 200 and ok.json()["action"] == "INSPECTED"
    after = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert len(after["lifecycles"]) == 1 and after["instance"]["status"] == "READY_FOR_INSTALL"
