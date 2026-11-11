"""R6 — INSPECT / REPAIR / REPLACE due evaluation for tracked parts (FINAL
§7.4, §7.4b; AP-04, AP-05, AP-06, AP-14, AP-18; C3, C4, C8). Pure: no I/O.

- REPLACE compares the VERIFIED CURRENT CYCLE with the rule threshold and is
  due at the threshold even if the part still works (AP-14). A maintenance
  event never changes a REPLACE result.
- INSPECT / REPAIR compare usage since the cycle start, or — after a
  matching maintenance event — usage since that event. Progression from the
  actual event is Owner policy PG-3(c): REAL is PENDING, TEST runs the
  proposed actual-event progression (TEST_PROPOSED).
- CALENDAR: month arithmetic (`add_months`) clamps to the last day of the
  target month and is always computed from the step's own anchor, never by
  chaining clamped dates; 6 months is never 180 days. The cycle anchor (PG-3a)
  and storage ageing (PG-3b) are Owner policy: REAL is PENDING; TEST uses the
  proposed anchor (Asia/Bangkok date of the cycle's first installation) and
  lets calendar age run through storage, labelled TEST_PROPOSED.
- CYCLE triggers stay creatable (compatibility) but have no counting source
  or approved policy: always UNKNOWN `UNSUPPORTED_PENDING_POLICY`. PTO_HOUR has
  no approved part-lifetime use (Owner Agreements §M): UNKNOWN.
- Condition groups: EARLIEST is the only implemented combination: DUE if any
  member is DUE, else UNKNOWN if any member is UNKNOWN, else NOT_DUE.
- No DUE_SOON: warning windows are G02 (source data required).
"""
from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite

from app.domain.lifetime_rule import DueAction, IntervalUnit, LifetimeRule, LifetimeTriggerType
from app.domain.part_usage import (
    APPROVED,
    PENDING,
    TEST_PROPOSED,
    PolicyContext,
    Quantity,
    worst_policy,
)

DUE = "DUE"
NOT_DUE = "NOT_DUE"
UNKNOWN_STATUS = "UNKNOWN"

UNSUPPORTED_PENDING_POLICY = "UNSUPPORTED_PENDING_POLICY"
PTO_NOT_APPROVED = "PTO_NOT_APPROVED_FOR_PART_LIFETIME"
DUE_ACTION_NOT_DECLARED = "DUE_ACTION_NOT_DECLARED"
INTERVAL_NOT_DECLARED = "INTERVAL_NOT_DECLARED"
INTERVAL_INVALID = "INTERVAL_INVALID"
UNIT_NOT_DECLARED = "UNIT_NOT_DECLARED"
UNIT_MISMATCH = "UNIT_MISMATCH"
INSPECTION_PROGRESSION_POLICY_PENDING = "INSPECTION_PROGRESSION_POLICY_PENDING"
CALENDAR_POLICY_PENDING = "CALENDAR_POLICY_PENDING"
CALENDAR_STORAGE_POLICY_PENDING = "CALENDAR_STORAGE_POLICY_PENDING"
CALENDAR_ANCHOR_MISSING = "CALENDAR_ANCHOR_MISSING"
CALENDAR_AGEING_IN_STORAGE_PROPOSED = "CALENDAR_AGEING_IN_STORAGE_PROPOSED"
COMBINATION_UNSUPPORTED = "COMBINATION_UNSUPPORTED"

_UNIT_FOR_TRIGGER = {
    LifetimeTriggerType.ENGINE_HOUR: {IntervalUnit.HOUR},
    LifetimeTriggerType.ODOMETER: {IntervalUnit.KM},
    LifetimeTriggerType.CALENDAR: {IntervalUnit.MONTH, IntervalUnit.DAY},
}


def add_months(anchor: date, months: int) -> date:
    """Same day number `months` later, clamped to the last day of the target
    month (31 Jan + 1 -> 28/29 Feb; 31 Jan + 2 -> 31 Mar; 29 Feb 2028 + 12 ->
    28 Feb 2029; + 48 -> 29 Feb 2032). Always from the anchor itself."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass(frozen=True)
class CalendarInputs:
    """`cycle_anchor` = the Asia/Bangkok date of the current cycle's first
    installation (the TEST-proposed PG-3a anchor) or None; `has_storage` =
    the cycle contains a non-installed interval since that anchor."""

    cycle_anchor: date | None
    has_storage: bool


@dataclass(frozen=True)
class RuleInputs:
    replace_base: Quantity
    since_event_base: Quantity | None = None
    event_date: date | None = None
    cycle_number: int = 1


@dataclass(frozen=True)
class RuleResult:
    lifetime_rule_id: str | None
    condition_group_key: str | None
    due_action: str | None
    trigger_type: str | None
    status: str
    current_value: float | None = None
    next_due_value: float | None = None
    next_due_date: date | None = None
    remaining: float | None = None
    reasons: tuple[str, ...] = ()
    policy_state: str | None = None
    due_key: str = ""
    members: tuple["RuleResult", ...] = ()


def due_key(target_type: str, target_id: str, rule_or_group: str, lifecycle_id: str | None,
            action: str | None) -> str:
    """Stable per (target, rule/group, cycle, action): a new cycle gives a new
    key, which lets an R7 consumer auto-resolve and reopen correctly."""
    return f"{target_type}:{target_id}:{rule_or_group}:{lifecycle_id or '-'}:{action or '-'}"


def _unknown(rule: LifetimeRule, key: str, *reasons: str, policy_state: str | None = None) -> RuleResult:
    return RuleResult(rule.lifetime_rule_id, rule.condition_group_key,
                      rule.due_action.value if rule.due_action else None, rule.trigger_type.value,
                      UNKNOWN_STATUS, reasons=tuple(dict.fromkeys(reasons)), policy_state=policy_state,
                      due_key=key)


def _valid_interval(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and isfinite(value) and value > 0


def evaluate_rule(rule: LifetimeRule, inputs: RuleInputs, calendar_inputs: CalendarInputs, policy: PolicyContext,
                  today: date, *, target_type: str, target_id: str, lifecycle_id: str | None) -> RuleResult:
    action = rule.due_action.value if rule.due_action else None
    key = due_key(target_type, target_id, rule.lifetime_rule_id, lifecycle_id, action)
    trigger = rule.trigger_type
    if trigger == LifetimeTriggerType.CYCLE:
        return _unknown(rule, key, UNSUPPORTED_PENDING_POLICY, policy_state=PENDING)
    if trigger == LifetimeTriggerType.PTO_HOUR:
        return _unknown(rule, key, PTO_NOT_APPROVED, policy_state=PENDING)
    if rule.due_action is None:
        return _unknown(rule, key, DUE_ACTION_NOT_DECLARED)
    if rule.interval_unit is None:
        return _unknown(rule, key, UNIT_NOT_DECLARED)
    if rule.interval_unit not in _UNIT_FOR_TRIGGER.get(trigger, set()):
        return _unknown(rule, key, UNIT_MISMATCH)
    after_event = rule.due_action != DueAction.REPLACE and inputs.event_date is not None
    use_first = (not after_event and inputs.cycle_number == 1 and _valid_interval(rule.first_due_value))
    threshold = rule.first_due_value if use_first else rule.interval_value
    if not _valid_interval(threshold):
        return _unknown(rule, key, INTERVAL_NOT_DECLARED if threshold is None else INTERVAL_INVALID)
    if trigger == LifetimeTriggerType.CALENDAR:
        return _calendar(rule, key, float(threshold), inputs, calendar_inputs, policy, today, after_event)

    # Meter-based (ENGINE_HOUR / ODOMETER).
    if after_event:
        if not policy.is_test:
            return _unknown(rule, key, INSPECTION_PROGRESSION_POLICY_PENDING, policy_state=PENDING)
        base = inputs.since_event_base
        if base is None:
            return _unknown(rule, key, INSPECTION_PROGRESSION_POLICY_PENDING, policy_state=TEST_PROPOSED)
        extra_policy = TEST_PROPOSED
    else:
        base = inputs.replace_base
        extra_policy = None
    policy_state = worst_policy(base.policy_state, extra_policy)
    if not base.is_known:
        return _unknown(rule, key, *(base.reasons or ("BASE_UNKNOWN",)), policy_state=policy_state)
    current = float(base.value)
    return RuleResult(rule.lifetime_rule_id, rule.condition_group_key, action, trigger.value,
                      DUE if current >= float(threshold) else NOT_DUE, current_value=current,
                      next_due_value=float(threshold), remaining=float(threshold) - current,
                      reasons=base.reasons, policy_state=policy_state or APPROVED, due_key=key)


def _calendar(rule: LifetimeRule, key: str, interval: float, inputs: RuleInputs, cal: CalendarInputs,
              policy: PolicyContext, today: date, after_event: bool) -> RuleResult:
    if not policy.is_test:
        reasons = [CALENDAR_POLICY_PENDING]
        if cal.has_storage:
            reasons.append(CALENDAR_STORAGE_POLICY_PENDING)
        return _unknown(rule, key, *reasons, policy_state=PENDING)
    anchor = inputs.event_date if after_event else cal.cycle_anchor
    if anchor is None:
        return _unknown(rule, key, CALENDAR_ANCHOR_MISSING, policy_state=TEST_PROPOSED)
    if rule.interval_unit == IntervalUnit.MONTH:
        if interval != int(interval):
            return _unknown(rule, key, INTERVAL_INVALID, policy_state=TEST_PROPOSED)
        due_date = add_months(anchor, int(interval))
    else:
        if interval != int(interval):
            return _unknown(rule, key, INTERVAL_INVALID, policy_state=TEST_PROPOSED)
        due_date = anchor + timedelta(days=int(interval))
    reasons = (CALENDAR_AGEING_IN_STORAGE_PROPOSED,) if cal.has_storage else ()
    return RuleResult(rule.lifetime_rule_id, rule.condition_group_key, rule.due_action.value,
                      rule.trigger_type.value, DUE if today >= due_date else NOT_DUE,
                      next_due_date=due_date, remaining=float((due_date - today).days), reasons=reasons,
                      policy_state=TEST_PROPOSED, due_key=key)


def combine_earliest(group_key: str, results: Sequence[RuleResult], *, target_type: str, target_id: str,
                     lifecycle_id: str | None) -> RuleResult:
    """EARLIEST (whichever comes first): DUE if any member is DUE, else
    UNKNOWN if any member is UNKNOWN (never NOT_DUE while a condition is
    unknown), else NOT_DUE."""
    action = results[0].due_action if results else None
    statuses = {r.status for r in results}
    status = DUE if DUE in statuses else UNKNOWN_STATUS if (UNKNOWN_STATUS in statuses or not results) else NOT_DUE
    reasons = tuple(dict.fromkeys(reason for r in results for reason in r.reasons))
    return RuleResult(None, group_key, action, "MULTI_CONDITION", status, reasons=reasons,
                      policy_state=worst_policy(*(r.policy_state for r in results)),
                      due_key=due_key(target_type, target_id, f"GROUP:{group_key}", lifecycle_id, action),
                      members=tuple(results))


__all__ = [
    "DUE", "NOT_DUE", "UNKNOWN_STATUS", "add_months", "CalendarInputs", "RuleInputs", "RuleResult",
    "evaluate_rule", "combine_earliest", "due_key",
]
