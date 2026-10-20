"""R3 daily inspection and Finding follow-up — pure rules (no I/O, no clock).

Source of truth: docs/project-governance/r3-implementation-contract.md.
Owner rules are cited by their decision id; proposed mechanisms by TS-n.

- Checklist resolution (R3-02, O-4, §5 M1): ASSET override → exact MODEL →
  explicit MISSING_CHECKLIST; never a fallback to another model or type.
- Due logic (R3-03, R3-22, R3-23, §6 D1–D2): every DAILY item, plus every
  EVERY_7_DAYS item with no earlier submitted result for asset + item_key or
  whose last result date is at least 7 Bangkok calendar days ago. Every accepted
  result value counts. Shown items must all be answered; unshown are refused.
- Results (R3-01, R3-15, R3-16, §4): PASS / FAIL / USABLE_PENDING_REPAIR /
  NOT_INSTALLED; both abnormal results need a non-empty remark; photos are
  optional; legacy NA is never accepted for a new submission.
- Finding episodes (R3-12..R3-14, R3-24, Q3, O-5.1, §7): `plan_findings`.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from fastapi import status

from app.domain.checklist import (
    ABNORMAL_RESULTS,
    CHECKLIST_SCOPE_ASSET,
    CHECKLIST_SCOPE_MODEL,
    FREQUENCY_DAILY,
    FREQUENCY_EVERY_7_DAYS,
    NEW_ENTRY_RESULTS,
    R3_FREQUENCIES,
    ChecklistAssignment,
    ChecklistItem,
    InspectionResultValue,
)
from app.domain.common import _BANGKOK_TZ
from app.domain.inspection import FindingStatus, InspectionFinding
from app.domain.repair import Repair, RepairStatus
from app.errors import ApiError

WEEKLY_INTERVAL_DAYS = 7

DUE_DAILY = "DAILY"
DUE_FIRST_WEEKLY = "FIRST_WEEKLY"
DUE_WEEKLY = "WEEKLY_DUE"


class R3Conflict(Exception):
    """A state conflict detected inside an atomic repository operation (the
    mock's single-process guard). Nothing was written. The service maps it to
    a 409 ApiError with the same code."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_api_error(self) -> ApiError:
        return ApiError(code=self.code, message=self.message, status_code=status.HTTP_409_CONFLICT,
                        details=self.details or None)


def bangkok_date_of(instant: datetime) -> date:
    return instant.astimezone(_BANGKOK_TZ).date()


# ---------------------------------------------------------------------------
# Checklist resolution
# ---------------------------------------------------------------------------


def missing_checklist(asset_type: str, asset_id: str, model_id: str | None) -> ApiError:
    return ApiError(
        code="MISSING_CHECKLIST",
        message="No checklist is assigned to this asset or to its exact model",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"asset_type": asset_type, "asset_id": asset_id, "model_id": model_id},
    )


def choose_assignment(
    assignments: Sequence[ChecklistAssignment], asset_id: str, model_id: str | None
) -> ChecklistAssignment | None:
    """ASSET override first, then the exact MODEL. Two candidates at the same
    level are never guessed between (409 CHECKLIST_ASSIGNMENT_AMBIGUOUS)."""
    for scope, key, value in ((CHECKLIST_SCOPE_ASSET, "asset_id", asset_id),
                              (CHECKLIST_SCOPE_MODEL, "model_id", model_id)):
        if value is None:
            continue
        matches = [a for a in assignments if a.scope == scope and getattr(a, key) == value]
        if len(matches) > 1:
            raise ApiError(
                code="CHECKLIST_ASSIGNMENT_AMBIGUOUS",
                message="More than one checklist is assigned at the same level; the system does not choose",
                status_code=status.HTTP_409_CONFLICT,
                details={"scope": scope, "assignment_ids": sorted(a.assignment_id for a in matches)},
            )
        if matches:
            return matches[0]
    return None


# ---------------------------------------------------------------------------
# Due logic
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DueItem:
    item: ChecklistItem
    due_reason: str
    last_result_date: date | None


def require_r3_ready(items: Sequence[ChecklistItem]) -> None:
    """Every item of an R3 revision needs a stable item_key and an R3
    frequency; a revision without them cannot drive the R3 form."""
    keys = [i.item_key for i in items]
    bad = sorted(i.item_id for i in items if not i.item_key or i.frequency not in R3_FREQUENCIES)
    if bad or len(set(keys)) != len(keys):
        raise ApiError(
            code="CHECKLIST_REVISION_NOT_R3_READY",
            message="The checklist revision has items without a stable item_key or frequency",
            status_code=status.HTTP_409_CONFLICT,
            details={"item_ids": bad},
        )


def due_items(
    items: Sequence[ChecklistItem], last_result_dates: Mapping[str, date], today: date
) -> list[DueItem]:
    require_r3_ready(items)
    shown: list[DueItem] = []
    for item in sorted(items, key=lambda i: i.sequence):
        last = last_result_dates.get(item.item_key or "")
        if item.frequency == FREQUENCY_DAILY:
            shown.append(DueItem(item, DUE_DAILY, last))
        elif item.frequency == FREQUENCY_EVERY_7_DAYS:
            if last is None:
                shown.append(DueItem(item, DUE_FIRST_WEEKLY, None))
            elif today >= last + timedelta(days=WEEKLY_INTERVAL_DAYS):
                shown.append(DueItem(item, DUE_WEEKLY, last))
    return shown


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    item_id: str
    result: InspectionResultValue
    remark: str | None
    evidence_attachment_ids: tuple[str, ...]


def _validation(message: str, details: dict[str, object]) -> ApiError:
    return ApiError(code="VALIDATION_ERROR", message=message,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


def validate_answers(shown: Sequence[DueItem], answers: Sequence[Answer]) -> dict[str, Answer]:
    by_id: dict[str, Answer] = {}
    for answer in answers:
        if answer.item_id in by_id:
            raise _validation(f"Item '{answer.item_id}' was answered more than once", {"item_id": answer.item_id})
        by_id[answer.item_id] = answer
    shown_ids = {d.item.item_id for d in shown}
    missing = shown_ids - set(by_id)
    unknown = set(by_id) - shown_ids
    if missing or unknown:
        raise _validation(
            "The submission must answer exactly the items shown for today",
            {"missing_item_ids": sorted(missing), "unknown_item_ids": sorted(unknown)},
        )
    for answer in by_id.values():
        if answer.result not in NEW_ENTRY_RESULTS:
            raise ApiError(
                code="INSPECTION_RESULT_NOT_ALLOWED",
                message=f"Result '{answer.result.value}' is not accepted for a new inspection",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"item_id": answer.item_id, "result": answer.result.value},
            )
        if answer.result in ABNORMAL_RESULTS and not (answer.remark and answer.remark.strip()):
            raise ApiError(
                code="INSPECTION_REMARK_REQUIRED",
                message=f"A remark is required when item '{answer.item_id}' is abnormal",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"item_id": answer.item_id, "result": answer.result.value},
            )
    return by_id


def submission_fingerprint(asset_type: str, asset_id: str, overall_remark: str | None,
                           answers: Sequence[Answer]) -> str:
    """S2: the same request_id must carry the same payload. Order-independent."""
    payload = {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "overall_remark": overall_remark,
        "items": sorted(
            [[a.item_id, a.result.value, a.remark, sorted(a.evidence_attachment_ids)] for a in answers],
            key=lambda row: row[0],
        ),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Finding episodes
# ---------------------------------------------------------------------------


def has_active_repair(orders: Sequence[Repair]) -> bool:
    """An OPEN order with no completion event (contract §9 P2 / §7)."""
    return any(o.status == RepairStatus.OPEN and not o.completion_submitted for o in orders)


def auto_end_allowed(orders: Sequence[Repair]) -> bool:
    """§7 E1 exactly: no linked Work Order, or every linked one CANCELLED."""
    return all(o.status == RepairStatus.CANCELLED for o in orders)


PLAN_CREATE = "CREATE"
PLAN_OBSERVE = "OBSERVE"
PLAN_END_NORMAL = "END_NORMAL"


@dataclass(frozen=True)
class FindingStep:
    kind: str
    item_key: str
    result_id: str
    finding_id: str | None = None
    previous_finding_id: str | None = None


@dataclass
class FindingPlan:
    steps: list[FindingStep] = field(default_factory=list)


@dataclass(frozen=True)
class ResultRef:
    result_id: str
    item_key: str
    result: InspectionResultValue


def plan_findings(
    results: Sequence[ResultRef],
    open_findings: Mapping[str, InspectionFinding],
    linked_orders: Mapping[str, Sequence[Repair]],
    last_ended: Mapping[str, str],
) -> FindingPlan:
    """A1/A2: abnormal → continue the OPEN Finding for the key, else create a
    new one (never reusing an id). E1: PASS on an OPEN Finding whose linked
    orders are none or all CANCELLED → ENDED. E2: PASS otherwise → observation
    only. N1: NOT_INSTALLED changes nothing."""
    plan = FindingPlan()
    for ref in results:
        current = open_findings.get(ref.item_key)
        if current is not None and current.status != FindingStatus.OPEN:
            current = None
        if ref.result in ABNORMAL_RESULTS:
            if current is None:
                plan.steps.append(FindingStep(PLAN_CREATE, ref.item_key, ref.result_id,
                                              previous_finding_id=last_ended.get(ref.item_key)))
            else:
                plan.steps.append(FindingStep(PLAN_OBSERVE, ref.item_key, ref.result_id, current.finding_id))
        elif ref.result == InspectionResultValue.PASS and current is not None:
            orders = linked_orders.get(current.finding_id, ())
            kind = PLAN_END_NORMAL if auto_end_allowed(orders) else PLAN_OBSERVE
            plan.steps.append(FindingStep(kind, ref.item_key, ref.result_id, current.finding_id))
    return plan


__all__ = [
    "Answer",
    "DUE_DAILY",
    "DUE_FIRST_WEEKLY",
    "DUE_WEEKLY",
    "DueItem",
    "FindingPlan",
    "FindingStep",
    "PLAN_CREATE",
    "PLAN_END_NORMAL",
    "PLAN_OBSERVE",
    "R3Conflict",
    "ResultRef",
    "auto_end_allowed",
    "bangkok_date_of",
    "choose_assignment",
    "due_items",
    "has_active_repair",
    "missing_checklist",
    "plan_findings",
    "require_r3_ready",
    "submission_fingerprint",
    "validate_answers",
]
