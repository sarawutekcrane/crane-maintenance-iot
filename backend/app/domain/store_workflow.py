"""R8 PRE-UAT Whole-Web Completion — repair material (Store) workflow, workstream D.

Owner source approval Rev 1 (2026-11-18), Decision 1: complete repair-related material
workflow; future stock integration only. NO warehouse stock ledger, opening inventory,
purchasing, costing, supplier, live stock deduction or second stock system.

One append-only journal STORE_EVENTS, linked to the existing material request / line
records (DEC-STORE-001…005):

  REQUESTED        a line of a request raised through the store route (repair OPEN only:
                   DEC-STORE-004 stops new requests after technical close)
  APPROVED/DENIED  per line, qty <= requested (grant can_test_store_approve)
  ISSUED           per line, part_id (+ optional instance), qty <= approved - issued
                   (grant can_test_store_issue). Issued is NOT installed (DEC-STORE-005)
  USE_CONFIRMED    current V2 member of the repair, part_id among the issued parts,
                   position_code, qty <= issued - used
  RETURN_DECLARED  current V2 member, qty <= issued - used - declared (unused parts)
  RETURN_ACCEPTED  Store physical acceptance, qty <= declared - accepted
                   (grant can_test_store_receive_return)

Reconciliation is derived from the journal, never stored as a mutable total:
unreconciled = issued - used - return_accepted; pending_return = declared - accepted.
A repair is RECONCILED when no line awaits a decision, no approved quantity awaits
issue, and every line has unreconciled = 0 and pending_return = 0. No return is ever
invented: issued == used needs no return event.

Exceptions (lost / damaged / post-close corrections) have no approved policy (OPEN-003):
they are not implemented and are reported as EXCEPTION_POLICY_PENDING.

Future stock-integration contract: docs/contracts/r8-store-material-event-contract.md.
Every event carries an immutable event_id, part identity, quantity / unit, request /
line / work order, actor, timestamps, type, version and the replay identity
(request_id + fingerprint). Replay returns the original event(s); quantity guards are
checked against the journal before the append, so a replayed or duplicate submission
can never create a second ISSUED.
"""
from __future__ import annotations

import asyncio
import hashlib
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from fastapi import status

from app.domain.asset import AssetType
from app.domain.authz import CAN_MANAGE_REPAIR
from app.domain.master_records import (
    api_error,
    fingerprint,
    guarded_append,
    new_event_id,
    now_iso,
    replay_rows,
    require_mock_test,
)
from app.domain.material_request_service import MaterialRequestService, RequisitionLineInput
from app.domain.repair import RepairStatus
from app.domain.requisition import RequisitionSourceType
from app.domain.technician_assignment import REPAIR, AssignmentCutover, TechnicianAssignmentService
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryConcurrentChangeError

JOURNAL_STORE_EVENTS = "STORE_EVENTS"
EVENT_VERSION = "1"

REQUESTED, APPROVED, DENIED, ISSUED = "REQUESTED", "APPROVED", "DENIED", "ISSUED"
USE_CONFIRMED, RETURN_DECLARED, RETURN_ACCEPTED = "USE_CONFIRMED", "RETURN_DECLARED", "RETURN_ACCEPTED"
EVENT_TYPES = (REQUESTED, APPROVED, DENIED, ISSUED, USE_CONFIRMED, RETURN_DECLARED, RETURN_ACCEPTED)

RECONCILED, UNRECONCILED = "RECONCILED", "UNRECONCILED"
EXCEPTION_POLICY_PENDING = "EXCEPTION_POLICY_PENDING"

EVENT_COLUMNS = (
    "event_id", "event_type", "event_version", "material_request_id", "requisition_line_id", "source_type",
    "source_work_order_id", "asset_type", "asset_id", "part_id", "part_instance_id", "part_code_snapshot",
    "quantity", "unit", "position_code", "reason", "actor_user_id", "actor_personnel_id", "occurred_at",
    "recorded_at", "request_id", "fingerprint", "supersedes_event_id", "data_context", "test_batch_id",
)

_MAX_QTY = Decimal("100000")
# Internal (never in the feed): one PENDING row per store request id before its material request is created,
# and one CREATED row with the material request id right after (second independent review 2026-11-18).
JOURNAL_STORE_INTENTS = "STORE_REQUEST_INTENTS"
INTENT_PENDING, INTENT_CREATED = "PENDING", "CREATED"
# In-process serialization of retries of ONE store request id (one-process Mock guard; R11): a fixed set
# of striped locks, so the same id always maps to the same lock and memory stays bounded.
_REQUEST_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[asyncio.Lock, ...]] = \
    weakref.WeakKeyDictionary()


def _request_lock(request_id: str) -> asyncio.Lock:
    stripes = _REQUEST_LOCKS.setdefault(asyncio.get_running_loop(), tuple(asyncio.Lock() for _ in range(64)))
    return stripes[int(hashlib.sha256(request_id.encode("utf-8")).hexdigest(), 16) % len(stripes)]


def parse_quantity(raw: object, field_name: str = "quantity") -> Decimal:
    """A positive decimal with at most 3 decimal places (never a float round trip)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise api_error("VALIDATION_ERROR", f"'{field_name}' must be a positive number", 422, {"field": field_name})
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise api_error("VALIDATION_ERROR", f"'{field_name}' must be a positive number", 422,
                        {"field": field_name}) from exc
    if not value.is_finite() or value <= 0 or value > _MAX_QTY or value != value.quantize(Decimal("0.001")):
        raise api_error("VALIDATION_ERROR", f"'{field_name}' must be a positive number (max 3 decimals)", 422,
                        {"field": field_name})
    return value.normalize()


def qty_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _d(text: str | None) -> Decimal:
    return Decimal(text) if text else Decimal(0)


@dataclass
class PartBalance:
    """One physical identity issued on a line: (actual part_id, part_instance_id or "")."""
    part_id: str
    part_instance_id: str = ""
    part_code_snapshot: str = ""
    issued: Decimal = Decimal(0)
    used: Decimal = Decimal(0)
    return_declared: Decimal = Decimal(0)
    return_accepted: Decimal = Decimal(0)

    @property
    def usable(self) -> Decimal:  # still out and not yet declared for return
        return self.issued - self.used - self.return_declared

    @property
    def acceptable(self) -> Decimal:  # declared, not yet accepted, and physically still out
        return min(self.return_declared - self.return_accepted, self.issued - self.used - self.return_accepted)

    @property
    def unreconciled(self) -> Decimal:
        return self.issued - self.used - self.return_accepted

    def as_dict(self) -> dict[str, str]:
        return {"part_id": self.part_id, "part_instance_id": self.part_instance_id,
                "part_code_snapshot": self.part_code_snapshot, "issued": qty_text(self.issued),
                "used": qty_text(self.used), "return_declared": qty_text(self.return_declared),
                "return_accepted": qty_text(self.return_accepted), "unreconciled": qty_text(self.unreconciled)}


@dataclass
class LineBalance:
    requisition_line_id: str
    material_request_id: str
    part_id: str
    part_description: str
    unit: str
    requested: Decimal = Decimal(0)
    decision: str = ""  # "" (awaiting) | APPROVED | DENIED
    approved: Decimal = Decimal(0)
    issued: Decimal = Decimal(0)
    used: Decimal = Decimal(0)
    return_declared: Decimal = Decimal(0)
    return_accepted: Decimal = Decimal(0)
    issued_part_ids: list[str] = field(default_factory=list)
    # Per physical identity (independent review 2026-11-18): every use / return names its actual part.
    parts: dict[tuple[str, str], PartBalance] = field(default_factory=dict)
    identity_unknown: int = 0  # a use / return event without a part identity (never defaulted)
    journaled: bool = False  # a REQUESTED event exists for this line

    @property
    def unreconciled(self) -> Decimal:
        return self.issued - self.used - self.return_accepted

    @property
    def pending_return(self) -> Decimal:
        return self.return_declared - self.return_accepted

    @property
    def awaiting_issue(self) -> Decimal:
        return self.approved - self.issued if self.decision == APPROVED else Decimal(0)

    def blockers(self) -> list[str]:
        reasons: list[str] = []
        if not self.journaled:
            reasons.append("REQUEST_NOT_JOURNALED")
        if not self.decision:
            reasons.append("LINE_AWAITING_DECISION")
        if self.awaiting_issue > 0:
            reasons.append("APPROVED_NOT_FULLY_ISSUED")
        if self.unreconciled != 0:
            reasons.append("ISSUED_NOT_USED_OR_RETURNED")
        if self.pending_return != 0:
            reasons.append("RETURN_NOT_ACCEPTED")
        if self.identity_unknown or any(b.unreconciled < 0 for b in self.parts.values()):
            reasons.append("PART_IDENTITY_UNRECONCILED")
        return reasons

    def as_dict(self) -> dict[str, object]:
        return {"requisition_line_id": self.requisition_line_id, "material_request_id": self.material_request_id,
                "part_id": self.part_id, "part_description": self.part_description, "unit": self.unit,
                "requested": qty_text(self.requested), "decision": self.decision or "AWAITING",
                "approved": qty_text(self.approved), "issued": qty_text(self.issued), "used": qty_text(self.used),
                "return_declared": qty_text(self.return_declared), "return_accepted": qty_text(self.return_accepted),
                "unreconciled": qty_text(self.unreconciled), "pending_return": qty_text(self.pending_return),
                "awaiting_issue": qty_text(self.awaiting_issue), "issued_part_ids": list(self.issued_part_ids),
                "issued_parts": [b.as_dict() for b in self.parts.values()], "blockers": self.blockers()}


@dataclass
class Reconciliation:
    repair_id: str
    state: str
    lines: list[LineBalance]
    events: list[dict[str, str]]

    def blockers(self) -> list[str]:
        return sorted({b for line in self.lines for b in line.blockers()})


def derive_balances(lines_by_id: Mapping[str, LineBalance], events: Sequence[Mapping[str, str]]) -> None:
    for e in events:
        line = lines_by_id.get(e.get("requisition_line_id", ""))
        if line is None:
            continue
        qty = _d(e.get("quantity"))
        kind = e.get("event_type")
        if kind == REQUESTED:
            line.requested, line.journaled = qty, True
        elif kind == APPROVED:
            line.decision, line.approved = APPROVED, qty
        elif kind == DENIED:
            line.decision, line.approved = DENIED, Decimal(0)
        elif kind in (ISSUED, USE_CONFIRMED, RETURN_DECLARED, RETURN_ACCEPTED):
            part_id, instance = e.get("part_id") or "", e.get("part_instance_id") or ""
            if kind == ISSUED:
                line.issued += qty
                if part_id and part_id not in line.issued_part_ids:
                    line.issued_part_ids.append(part_id)
            elif kind == USE_CONFIRMED:
                line.used += qty
            elif kind == RETURN_DECLARED:
                line.return_declared += qty
            else:
                line.return_accepted += qty
            if not part_id:
                line.identity_unknown += 1  # never attributed to a guessed part
                continue
            bucket = line.parts.get((part_id, instance))
            if bucket is None:
                if kind != ISSUED:
                    line.identity_unknown += 1  # a movement for an identity that was never issued
                    continue
                bucket = line.parts[(part_id, instance)] = PartBalance(part_id, instance,
                                                                       e.get("part_code_snapshot") or "")
            if kind == ISSUED:
                bucket.issued += qty
            elif kind == USE_CONFIRMED:
                bucket.used += qty
            elif kind == RETURN_DECLARED:
                bucket.return_declared += qty
            else:
                bucket.return_accepted += qty


def resolve_identity(line: LineBalance, body: Mapping[str, object]) -> PartBalance:
    """The issued identity a use / return names. The client must name the actual part; an
    instance-tracked issue must also name its instance. Nothing is guessed: a part that was not
    issued on this line, an unknown instance, or an ambiguous request is refused."""
    part_id = body.get("part_id")
    if not isinstance(part_id, str) or not part_id.strip():
        raise api_error("STORE_PART_IDENTITY_REQUIRED", "part_id of the actual issued part is required", 422,
                        {"field": "part_id"})
    instance = body.get("part_instance_id") or ""
    if not isinstance(instance, str):
        raise api_error("VALIDATION_ERROR", "part_instance_id must be text", 422, {"field": "part_instance_id"})
    candidates = {key: b for key, b in line.parts.items() if key[0] == part_id}
    if not candidates:
        raise api_error("STORE_PART_NOT_ISSUED", "This part was not issued on this line", 422, {"field": "part_id"})
    if instance:
        bucket = candidates.get((part_id, instance))
        if bucket is None:
            raise api_error("STORE_PART_INSTANCE_NOT_ISSUED", "This part instance was not issued on this line", 422,
                            {"field": "part_instance_id"})
        return bucket
    bucket = candidates.get((part_id, ""))
    if bucket is None:
        raise api_error("STORE_PART_INSTANCE_REQUIRED", "This part was issued as tracked instances; name the "
                        "instance", 422, {"field": "part_instance_id",
                                          "issued_instances": sorted(k[1] for k in candidates)})
    return bucket


@dataclass
class StoreOutcome:
    replayed: bool
    events: list[dict[str, str]]
    material_request_id: str = ""


class StoreWorkflowService:
    def __init__(self, repository: Repository, cutover: AssignmentCutover, *, mock_repository: bool) -> None:
        self._repository = repository
        self._cutover = cutover
        self._mock = mock_repository

    @property
    def _context(self) -> str | None:
        return self._cutover.data_context

    def _require_mode(self) -> None:
        require_mock_test(self._mock, self._context, "store_workflow", "STORE_REAL_NOT_ENABLED")

    async def _repair(self, repair_id: str):
        detail = await self._repository.get_repair(repair_id)
        if detail is None:
            raise api_error("REPAIR_NOT_FOUND", "No repair has exactly this id", status.HTTP_404_NOT_FOUND)
        return detail.repair

    async def _is_member(self, repair, context) -> bool:
        return await TechnicianAssignmentService(self._repository, self._cutover).is_current_member(
            REPAIR, repair, getattr(context, "user_id", None), context)

    async def _repair_lines(self, repair_id: str) -> dict[str, LineBalance]:
        requests = await self._repository.list_material_requests_for_work_order(repair_id)
        lines: dict[str, LineBalance] = {}
        for header in requests:
            if getattr(header.source_type, "value", header.source_type) != RequisitionSourceType.REPAIR.value:
                continue
            detail = await self._repository.get_material_request(header.material_request_id)
            if detail is None:
                continue
            for line in detail.lines:
                lines[line.requisition_line_id] = LineBalance(
                    requisition_line_id=line.requisition_line_id, material_request_id=line.material_request_id,
                    part_id=line.part_id or "", part_description=line.part_description, unit=line.unit or "",
                    requested=Decimal(str(line.requested_quantity)) if line.requested_quantity is not None
                    else Decimal(0))
        return lines

    async def reconciliation(self, repair_id: str) -> Reconciliation:
        self._require_mode()
        await self._repair(repair_id)
        lines = await self._repair_lines(repair_id)
        journal = await self._repository.read_preuat_journal(JOURNAL_STORE_EVENTS)
        events = [e for e in journal if e.get("source_work_order_id") == repair_id]
        derive_balances(lines, events)
        ordered = list(lines.values())
        state = RECONCILED if not any(line.blockers() for line in ordered) else UNRECONCILED
        return Reconciliation(repair_id, state, ordered, events)

    # ------------------------------------------------------------------ writes

    def _event(self, kind: str, line: LineBalance | None, repair, context, request_id: str, fp: str, *,
               material_request_id: str = "", quantity: Decimal | None = None, part_id: str = "",
               part_instance_id: str = "", part_code: str = "", unit: str = "", position_code: str = "",
               reason: str = "") -> dict[str, str]:
        asset_type = getattr(repair.asset_type, "value", repair.asset_type)
        return {
            "event_id": new_event_id("STE"), "event_type": kind, "event_version": EVENT_VERSION,
            "material_request_id": material_request_id or (line.material_request_id if line else ""),
            "requisition_line_id": line.requisition_line_id if line else "", "source_type": "REPAIR",
            "source_work_order_id": repair.repair_id, "asset_type": str(asset_type), "asset_id": repair.asset_id,
            "part_id": part_id, "part_instance_id": part_instance_id, "part_code_snapshot": part_code,
            "quantity": qty_text(quantity) if quantity is not None else "", "unit": unit,
            "position_code": position_code, "reason": reason,
            "actor_user_id": getattr(context, "user_id", "") or "",
            "actor_personnel_id": getattr(context, "personnel_id", "") or "", "occurred_at": now_iso(),
            "recorded_at": now_iso(), "request_id": request_id, "fingerprint": fp, "supersedes_event_id": "",
            "data_context": self._context or "", "test_batch_id": self._cutover.test_batch_id or "",
        }

    async def request(self, repair_id: str, body: Mapping[str, object], context, *, request_id: str,
                      material_requests: MaterialRequestService) -> StoreOutcome:
        """One store request. Write boundary (second independent review, 2026-11-18): the material request is
        created first and its REQUESTED events second; Mock has no transaction across the two. Retries of ONE
        request id are serialized (in-process lock), a material request whose events were not recorded is
        flagged REQUEST_NOT_JOURNALED and frozen, and resending the same request adopts it instead of creating
        a second one. R11 owes a real transaction / unique key across both writes."""
        self._require_mode()
        async with _request_lock(request_id):
            return await self._request_locked(repair_id, body, context, request_id=request_id,
                                              material_requests=material_requests)

    async def _request_locked(self, repair_id: str, body: Mapping[str, object], context, *, request_id: str,
                              material_requests: MaterialRequestService) -> StoreOutcome:
        fp = fingerprint("store_request", repair_id, body)
        journal = await self._repository.read_preuat_journal(JOURNAL_STORE_EVENTS)
        replay = replay_rows(journal, request_id, fp)
        if replay:
            return StoreOutcome(True, replay, replay[0].get("material_request_id", ""))
        repair = await self._repair(repair_id)
        # Recovery is keyed on THIS request id only (second independent review): an intent row recorded
        # before the material request was created proves the request was authorized at that time.
        intents = await self._repository.read_preuat_journal(JOURNAL_STORE_INTENTS)
        mine = [r for r in intents if r.get("request_id") == request_id]
        if any(r.get("fingerprint") != fp for r in mine):
            raise api_error("REQUEST_ID_REUSED", "This X-Request-Id was already used for a different change; "
                            "nothing was written", status.HTTP_409_CONFLICT)
        if not mine:
            await self._require_may_request(repair, context)
        raw_lines = body.get("lines")
        if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 20:
            raise api_error("VALIDATION_ERROR", "1–20 lines are required", 422, {"field": "lines"})
        inputs: list[RequisitionLineInput] = []
        for index, raw in enumerate(raw_lines):
            if not isinstance(raw, dict) or set(raw) - {"part_id", "part_description", "quantity", "unit"}:
                raise api_error("VALIDATION_ERROR", "Unknown line field", 422, {"line": index})
            description = raw.get("part_description")
            if not isinstance(description, str) or not description.strip() or len(description) > 200:
                raise api_error("VALIDATION_ERROR", "part_description is required", 422, {"line": index})
            unit = raw.get("unit")
            if not isinstance(unit, str) or not unit.strip() or len(unit) > 20:
                raise api_error("VALIDATION_ERROR", "unit is required", 422, {"line": index})
            qty = parse_quantity(raw.get("quantity"))
            part_id = raw.get("part_id")
            if part_id is not None and (not isinstance(part_id, str) or
                                        await self._repository.get_part_master(part_id) is None):
                raise api_error("PART_NOT_FOUND", "The requested part does not exist", 422, {"line": index})
            inputs.append(RequisitionLineInput(part_description=description.strip(), quantity=float(qty),
                                               unit=unit.strip(), part_id=part_id or None,
                                               line_source="REPAIR_PART_MASTER" if part_id else "REPAIR_UNREGISTERED"))
        note = body.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 300):
            raise api_error("VALIDATION_ERROR", "note must be text (max 300)", 422, {"field": "note"})
        asset_type = AssetType(getattr(repair.asset_type, "value", repair.asset_type))
        detail = None
        if mine:  # an earlier attempt of THIS request: adopt what it created, never create a second one
            created = [r for r in mine if r.get("kind") == INTENT_CREATED]
            if created:
                detail = await self._repository.get_material_request(created[-1]["material_request_id"])
            else:
                detail = await self._unjournaled_match(repair_id, inputs, journal, intents, mine[0].get("actor", ""))
            if detail is None:  # nothing was created: a new creation must satisfy today's rules again
                await self._require_may_request(repair, context)
        if detail is None:
            actor = getattr(context, "user_id", None) or ""
            if not mine:
                await self._append_internal(JOURNAL_STORE_INTENTS, {"kind": INTENT_PENDING, "request_id": request_id,
                                                                    "fingerprint": fp, "repair_id": repair_id,
                                                                    "actor": actor, "material_request_id": "",
                                                                    "recorded_at": now_iso()})
            detail = await material_requests.create(RequisitionSourceType.REPAIR, repair_id, asset_type,
                                                    repair.asset_id, inputs, actor or None, note or None)
            try:
                await self._append_internal(JOURNAL_STORE_INTENTS, {
                    "kind": INTENT_CREATED, "request_id": request_id, "fingerprint": fp, "repair_id": repair_id,
                    "actor": actor, "material_request_id": detail.request.material_request_id,
                    "recorded_at": now_iso()})
            except ApiError:
                pass  # recovery then falls back to the exact-lines match for THIS request id
        events = []
        for line in detail.lines:
            balance = LineBalance(line.requisition_line_id, line.material_request_id, line.part_id or "",
                                  line.part_description, line.unit or "")
            events.append(self._event(REQUESTED, balance, repair, context, request_id, fp,
                                      quantity=Decimal(str(line.requested_quantity)), part_id=line.part_id or "",
                                      unit=line.unit or ""))
        await self._append_requested(events, request_id, fp, detail.request.material_request_id)
        return StoreOutcome(False, events, detail.request.material_request_id)

    async def _require_may_request(self, repair, context) -> None:
        if getattr(repair.status, "value", repair.status) != RepairStatus.OPEN.value:
            raise api_error("STORE_REQUEST_AFTER_CLOSE_NOT_ALLOWED", "New material requests stop once the repair is "
                            "technically closed (DEC-STORE-004); return and reconciliation continue",
                            status.HTTP_409_CONFLICT)
        if CAN_MANAGE_REPAIR not in getattr(context, "capabilities", frozenset()) and \
                not await self._is_member(repair, context):
            raise api_error("STORE_REQUEST_NOT_AUTHORIZED", "Only a current V2 member of this repair or a repair "
                            "manager may request parts", status.HTTP_403_FORBIDDEN)

    async def _append_internal(self, journal: str, row: dict[str, str]) -> None:
        """Append one internal row against a fresh count (rows of other requests never conflict)."""
        for _ in range(5):
            count = len(await self._repository.read_preuat_journal(journal))
            try:
                await self._repository.append_preuat_journal(journal, expected_count=count, rows=[row])
                return
            except RepositoryConcurrentChangeError:
                continue
        raise api_error("STORE_CONCURRENT_CHANGE", "Another change kept being recorded at the same time; nothing "
                        "was written. Reload and try again", status.HTTP_409_CONFLICT)

    async def _unjournaled_match(self, repair_id: str, inputs: Sequence[RequisitionLineInput],
                                 journal: Sequence[Mapping[str, str]], intents: Sequence[Mapping[str, str]],
                                 actor: str):
        """Recovery for ONE request id whose creation was not recorded: the material request of this repair,
        by the intent's actor, with exactly these lines, that has NO recorded event and is not claimed by any
        other request's CREATED intent. More than one candidate is ambiguous and refused."""
        recorded = {e.get("material_request_id") for e in journal}
        claimed = {r.get("material_request_id") for r in intents if r.get("kind") == INTENT_CREATED}
        want = sorted((i.part_id or "", i.part_description, Decimal(str(i.quantity)), i.unit) for i in inputs)
        found = []
        for header in await self._repository.list_material_requests_for_work_order(repair_id):
            mr = header.material_request_id
            if mr in recorded or mr in claimed or (getattr(header, "created_by", None) or "") != actor:
                continue
            detail = await self._repository.get_material_request(mr)
            if detail is None:
                continue
            have = sorted((ln.part_id or "", ln.part_description, Decimal(str(ln.requested_quantity)), ln.unit or "")
                          for ln in detail.lines)
            if have == want:
                found.append(detail)
        if len(found) > 1:
            raise api_error("STORE_REQUEST_RECOVERY_AMBIGUOUS", "More than one unrecorded material request matches; "
                            "nothing was written (exception policy pending)", status.HTTP_409_CONFLICT)
        return found[0] if found else None

    async def _append_requested(self, events: list[dict[str, str]], request_id: str, fp: str,
                                material_request_id: str) -> None:
        """REQUESTED events of lines created just now (independent review): the material request already
        exists, so a concurrent append elsewhere must not leave it orphaned. New line ids cannot collide with
        any other line's quantity guard, so the append is retried against a fresh journal count; only a
        concurrent use of the SAME request id (replay race) stops it."""
        for _ in range(5):
            journal = await self._repository.read_preuat_journal(JOURNAL_STORE_EVENTS)
            replay_rows(journal, request_id, fp)  # 409 REQUEST_ID_REUSED on a different body
            if any(r.get("request_id") == request_id for r in journal):  # unreachable under the lock
                raise api_error("STORE_CONCURRENT_CHANGE", "The same request was recorded concurrently; reload",
                                status.HTTP_409_CONFLICT)
            try:
                await self._repository.append_preuat_journal(JOURNAL_STORE_EVENTS, expected_count=len(journal),
                                                             rows=events)
                return
            except RepositoryConcurrentChangeError:
                continue
        raise api_error("STORE_REQUEST_RECOVERY_PENDING", "The material request was created but its events could "
                        "not be recorded yet; resend the SAME request (same X-Request-Id) to finish it. It is frozen "
                        "until then", status.HTTP_409_CONFLICT, {"material_request_id": material_request_id})

    async def _verify_issued_instance(self, journal: Sequence[Mapping[str, str]], part_id: str, instance: str,
                                      qty: Decimal) -> None:
        """A tracked instance is one physical unit of the issued part, and it cannot be out twice."""
        if qty != 1:
            raise api_error("STORE_INSTANCE_QUANTITY_INVALID", "A tracked part instance is issued one at a time",
                            422, {"field": "quantity"})
        detail = await self._repository.get_part_instance(instance)
        if detail is None:
            raise api_error("PART_INSTANCE_NOT_FOUND", "The part instance does not exist", 422,
                            {"field": "part_instance_id"})
        if getattr(detail.instance, "part_id", None) != part_id:
            raise api_error("STORE_PART_INSTANCE_MISMATCH", "The instance belongs to another part", 422,
                            {"field": "part_instance_id"})
        # Independent review 2026-11-18: the instance's own lifecycle status must allow an issue.
        instance_status = getattr(getattr(detail.instance, "status", None), "value", None)
        if instance_status in ("INSTALLED", "IN_REPAIR", "SCRAPPED"):
            raise api_error("STORE_PART_INSTANCE_NOT_AVAILABLE", "This instance is installed, in repair or scrapped; "
                            "it cannot be issued", status.HTTP_409_CONFLICT,
                            {"field": "part_instance_id", "instance_status": instance_status})
        # An instance confirmed as USED stays out of Store custody here: returning it to stock after a
        # later removal is a stock / exception-policy matter (future integration, OPEN-003), never guessed.
        out = Decimal(0)
        for e in journal:
            if e.get("part_instance_id") == instance:
                if e.get("event_type") == ISSUED:
                    out += _d(e.get("quantity"))
                elif e.get("event_type") == RETURN_ACCEPTED:
                    out -= _d(e.get("quantity"))
        if out > 0:
            raise api_error("STORE_PART_INSTANCE_ALREADY_ISSUED", "This instance is already issued and not returned",
                            status.HTTP_409_CONFLICT, {"field": "part_instance_id"})

    async def act(self, repair_id: str, line_id: str, kind: str, body: Mapping[str, object], context, *,
                  request_id: str) -> StoreOutcome:
        """One line-level event (APPROVED / DENIED / ISSUED / USE_CONFIRMED /
        RETURN_DECLARED / RETURN_ACCEPTED); the route has already checked the grant."""
        self._require_mode()
        fp = fingerprint(f"store_{kind.lower()}", f"{repair_id}:{line_id}", body)
        journal = await self._repository.read_preuat_journal(JOURNAL_STORE_EVENTS)
        replay = replay_rows(journal, request_id, fp)
        if replay:
            return StoreOutcome(True, replay, replay[0].get("material_request_id", ""))
        repair = await self._repair(repair_id)
        lines = await self._repair_lines(repair_id)
        line = lines.get(line_id)
        if line is None:
            raise api_error("STORE_LINE_NOT_FOUND", "This request line does not belong to the repair",
                            status.HTTP_404_NOT_FOUND)
        derive_balances(lines, [e for e in journal if e.get("source_work_order_id") == repair_id])
        if not line.journaled:
            raise api_error("STORE_REQUEST_NOT_JOURNALED", "This request's events were not recorded yet; resend the "
                            "original request (same X-Request-Id) first. Nothing was written", status.HTTP_409_CONFLICT)
        allowed = {"APPROVED": {"quantity"}, "DENIED": {"reason"},
                   "ISSUED": {"quantity", "part_id", "part_instance_id", "unit"},
                   "USE_CONFIRMED": {"quantity", "part_id", "part_instance_id", "position_code"},
                   "RETURN_DECLARED": {"quantity", "part_id", "part_instance_id", "reason"},
                   "RETURN_ACCEPTED": {"quantity", "part_id", "part_instance_id"}}[kind]
        unknown = sorted(set(body) - allowed)
        if unknown:
            raise api_error("VALIDATION_ERROR", "Unknown field(s)", 422, {"fields": unknown})
        if kind in (USE_CONFIRMED, RETURN_DECLARED) and not await self._is_member(repair, context):
            raise api_error("STORE_TECHNICIAN_NOT_ASSIGNED", "Only a current V2 member of this repair confirms use or "
                            "declares a return", status.HTTP_403_FORBIDDEN)

        def over(limit: Decimal, qty: Decimal) -> None:
            if qty > limit:
                raise api_error("STORE_QUANTITY_EXCEEDED", f"At most {qty_text(limit)} is allowed for this step",
                                status.HTTP_409_CONFLICT, {"allowed": qty_text(limit)})

        event: dict[str, str]
        if kind == DENIED:
            if line.decision:
                raise api_error("STORE_LINE_ALREADY_DECIDED", "This line already has a decision (corrections: "
                                f"{EXCEPTION_POLICY_PENDING})", status.HTTP_409_CONFLICT)
            reason = body.get("reason")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                raise api_error("REASON_REQUIRED", "A reason is required to deny a line", 422, {"field": "reason"})
            event = self._event(DENIED, line, repair, context, request_id, fp, reason=reason.strip(),
                                part_id=line.part_id, unit=line.unit)
        else:
            qty = parse_quantity(body.get("quantity"))
            if kind == APPROVED:
                if line.decision:
                    raise api_error("STORE_LINE_ALREADY_DECIDED", "This line already has a decision (corrections: "
                                    f"{EXCEPTION_POLICY_PENDING})", status.HTTP_409_CONFLICT)
                over(line.requested, qty)
                event = self._event(APPROVED, line, repair, context, request_id, fp, quantity=qty,
                                    part_id=line.part_id, unit=line.unit)
            elif kind == ISSUED:
                if line.decision != APPROVED:
                    raise api_error("STORE_LINE_NOT_APPROVED", "Only an approved line can be issued",
                                    status.HTTP_409_CONFLICT)
                over(line.approved - line.issued, qty)
                part_id = body.get("part_id")
                if not isinstance(part_id, str) or not part_id.strip():
                    raise api_error("VALIDATION_ERROR", "part_id of the actual stock part is required", 422,
                                    {"field": "part_id"})
                part = await self._repository.get_part_master(part_id)
                if part is None:
                    raise api_error("PART_NOT_FOUND", "The issued part does not exist", 422, {"field": "part_id"})
                unit = body.get("unit", line.unit)
                if not isinstance(unit, str) or not unit.strip() or (line.unit and unit.strip() != line.unit):
                    raise api_error("STORE_UNIT_MISMATCH", "The unit must equal the requested unit", 422,
                                    {"field": "unit"})
                instance = body.get("part_instance_id") or ""
                if not isinstance(instance, str):
                    raise api_error("VALIDATION_ERROR", "part_instance_id must be text", 422)
                if instance:
                    await self._verify_issued_instance(journal, part_id, instance, qty)
                event = self._event(ISSUED, line, repair, context, request_id, fp, quantity=qty, part_id=part_id,
                                    part_instance_id=instance, part_code=getattr(part, "part_code", "") or "",
                                    unit=unit.strip())
            elif kind in (USE_CONFIRMED, RETURN_DECLARED, RETURN_ACCEPTED):
                # Every movement names its verified physical identity (independent review 2026-11-18):
                # guards are per identity, so the line totals can never go negative or mix parts.
                bucket = resolve_identity(line, body)
                if bucket.part_instance_id and qty != 1:
                    raise api_error("STORE_INSTANCE_QUANTITY_INVALID", "A tracked part instance moves as one whole "
                                    "unit", 422, {"field": "quantity"})
                identity = {"part_id": bucket.part_id, "part_instance_id": bucket.part_instance_id,
                            "part_code": bucket.part_code_snapshot, "unit": line.unit}
                if kind == USE_CONFIRMED:
                    over(bucket.usable, qty)
                    position = body.get("position_code")
                    if not isinstance(position, str) or not position.strip() or len(position) > 60:
                        raise api_error("VALIDATION_ERROR", "position_code (where it was installed) is required",
                                        422, {"field": "position_code"})
                    event = self._event(USE_CONFIRMED, line, repair, context, request_id, fp, quantity=qty,
                                        position_code=position.strip(), **identity)
                elif kind == RETURN_DECLARED:
                    over(bucket.usable, qty)
                    reason = body.get("reason") or ""
                    event = self._event(RETURN_DECLARED, line, repair, context, request_id, fp, quantity=qty,
                                        reason=str(reason)[:300], **identity)
                else:
                    over(bucket.acceptable, qty)
                    event = self._event(RETURN_ACCEPTED, line, repair, context, request_id, fp, quantity=qty,
                                        **identity)
            else:  # pragma: no cover - the route only passes known kinds
                raise api_error("VALIDATION_ERROR", "Unknown store step", 422)
        await guarded_append(self._repository, JOURNAL_STORE_EVENTS, len(journal), [event], "STORE_CONCURRENT_CHANGE")
        return StoreOutcome(False, [event], line.material_request_id)


__all__ = ["StoreWorkflowService", "Reconciliation", "LineBalance", "StoreOutcome", "JOURNAL_STORE_EVENTS",
           "EVENT_TYPES", "EVENT_COLUMNS", "RECONCILED", "UNRECONCILED", "parse_quantity", "derive_balances",
           "APPROVED", "DENIED", "ISSUED", "USE_CONFIRMED", "RETURN_DECLARED", "RETURN_ACCEPTED", "REQUESTED"]
