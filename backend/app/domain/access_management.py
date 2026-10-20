"""Access Management — per-employee permissions, root administration and scoped
delegation (Owner-approved Mock implementation; includes R3 L11).

Owner rules implemented here:
- Every ordinary functional permission is stored PER EMPLOYEE (`personnel_id`).
  There are no department baselines, role templates or job-title grants;
  department and position are selection and filtering information only. A
  "whole department" change is a bulk operation that writes one event per
  currently eligible employee; it is never a department rule, so a later
  employee inherits nothing.
- In Access Management mode (`Settings.access_management_mode`) the provisional
  development role table grants NOTHING operational: an employee's capabilities
  are exactly their effective grants. New employees start with none.
- Root business administration belongs to the Maintenance Department Manager
  POSITION: the employee named by the latest root appointment. A handover is
  made by the current holder to another active, account-linked employee (never
  to themselves); the former holder loses the authority at once; historical
  events keep their actual actor. Technical recovery (the development ADMIN
  role in this Mock) may appoint a holder ONLY while no valid holder exists.
- Delegation: the root holder delegates the administration of an exact
  capability list for one department to another employee; a delegate can never
  delegate onward, act outside the department or the list, or change their own
  permissions. Revocation ends the authority at once and never reverses grants
  the delegate made to others.
- Department transfer: a grant or delegation counts only if it was recorded
  AFTER the employee's current department period began (the head revision of the
  latest in-force movement). An effective transfer therefore revokes every
  functional permission and delegation of the transferred employee at once,
  atomically and without rewriting history; nothing of the new department is
  granted.
- Inactive employees (active_status other than exactly ACTIVE), employees
  without exactly one account link, and unresolvable identities hold nothing
  (fail closed).
- Root protection (B1): the root appointment records the holder's verified
  account; the holder counts only while that exact account is still the one
  linked. The appointed employee's account link, lifecycle and department are
  protected: ordinary capabilities (whoever granted them) cannot change them, so
  they can neither take over nor lock out the position (`require_root_protection`).
- Security-sensitive capabilities (D7: account / technician / driver links,
  personnel lifecycle, department movement, access audit) act system-wide, so
  only the root holder can grant them; they are never delegable.
- Every department-history record (transfer, insertion, correction or
  cancellation) is a permission reset boundary (D4): a later cancellation or
  correction never restores permissions an earlier movement ended; re-granting
  is always an explicit, audited operation.
- So is every EFFECTIVE employee–account or employee–technician link change
  (A1/A2, Owner Option 1): grants, delegations and assignment-based authority
  recorded before it count for nothing, so a newly linked account starts with
  zero permissions and a re-linked technician identity carries no PRIMARY
  authority until an administrator re-grants or a manager re-confirms the team.

Persistence is ONE append-only, revision-checked event log (`access_event`):
grants, revocations, bulk-batch summaries, delegations, delegation revocations
and root appointments. Nothing is ever updated or deleted. Mock only: the base
repository answers 501 FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE in Google
Sheets mode; the mock guard is single-process (not production atomicity, R11).
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fastapi import status

from app.domain import authz
from app.domain.master_lifecycle import in_scope
from app.domain.personnel_department_history import scoped_history_rows
from app.domain.personnel_department_timeline import (
    STATUS_VALID,
    derive_department_timeline,
)
from app.domain.registration import text
from app.domain.request_replay import request_fingerprint
from app.errors import ApiError
from app.repositories.base import PERSONNEL_LINK_ACCOUNT, PERSONNEL_LINK_TECHNICIAN

ACCESS_EVENT_COLUMNS: tuple[str, ...] = (
    "event_id", "kind", "personnel_id", "capability", "delegation_id", "department_id", "capabilities",
    "actor_personnel_id", "actor_user_id", "actor_name_snapshot", "recorded_at", "reason_th", "request_id",
    "request_fingerprint", "batch_id", "target_kind", "details_json",
)
KIND_GRANT = "GRANT"
KIND_REVOKE = "REVOKE"
KIND_BATCH = "GRANT_BATCH"
KIND_DELEGATION_GRANT = "DELEGATION_GRANT"
KIND_DELEGATION_REVOKE = "DELEGATION_REVOKE"
KIND_ROOT_APPOINTMENT = "ROOT_APPOINTMENT"
ROOT_POSITION_TH = "ผู้จัดการแผนกซ่อมบำรุง"
ACTIVE = "ACTIVE"
TARGET_EMPLOYEE = "EMPLOYEE"
TARGET_DEPARTMENT = "DEPARTMENT"
MAX_REASON_LENGTH = 500

# The bounded personnel_master columns Access Management reads (no new master).
ACCESS_PERSONNEL_COLUMNS: tuple[str, ...] = (
    "personnel_id", "first_name", "last_name", "position", "active_status", "user_id", "is_test_data",
    "test_batch_id",
)


# ---------------------------------------------------------------------------
# Capability catalog — the existing capabilities only, each in ONE category.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityEntry:
    code: str
    category: str
    label_th: str
    effect_th: str  # what the one capability actually controls (never split in the UI)


CATEGORIES: tuple[tuple[str, str], ...] = (
    ("A", "การตรวจเช็คยานพาหนะและเครื่องมือ"),
    ("B", "การแจ้งซ่อม"),
    ("C", "ใบงานซ่อม"),
    ("D", "การมอบหมายช่าง (V2)"),
    ("E", "การติดตามรายการผิดปกติ (Finding)"),
    ("F", "งานบำรุงรักษาตามแผน (PM)"),
    ("G", "บุคลากรและแผนก"),
    ("H", "คนขับ ความรับผิดชอบเครน และงานปฏิบัติการ"),
    ("I", "รายงาน แดชบอร์ด และประวัติ"),
    ("J", "การจัดการสิทธิ์"),
)

CATALOG: tuple[CapabilityEntry, ...] = (
    CapabilityEntry(authz.CAN_RECORD_INSPECTION, "A", "บันทึกผลการตรวจเช็ค",
                    "ส่งผลการตรวจเช็ครายวันของยานพาหนะและเครื่องมือ"),
    CapabilityEntry(authz.CAN_REPORT_REPAIR, "B", "แจ้งปัญหา/แจ้งซ่อม",
                    "ส่งคำขอแจ้งซ่อม ดูคำขอของตนเอง และตรวจสอบการแจ้งซ้ำจากแหล่งเดียวกัน"),
    CapabilityEntry(authz.CAN_CANCEL_REPAIR_REQUEST, "B", "ยกเลิกคำขอแจ้งซ่อมที่ซ้ำซ้อน",
                    "ยกเลิกคำขอที่ยังรอตรวจรับและยังไม่เคยเปิดใบงาน พร้อมเหตุผล"),
    CapabilityEntry(authz.CAN_MANAGE_REPAIR, "C", "จัดการงานซ่อม",
                    "เปิดใบงานซ่อม รับคำขอแจ้งซ่อมเป็นใบงาน ดูคิวงานค้าง บันทึกงานและอะไหล่ "
                    "และมอบหมาย/ถอนช่าง V2 ของงานซ่อมที่ไม่ได้มาจากรายการผิดปกติ (สิทธิ์เดียวครอบคลุมทั้งหมด)"),
    CapabilityEntry(authz.CAN_CLOSE_REPAIR, "C", "ปิดใบงานซ่อม",
                    "ปิดใบงานซ่อมที่ไม่ได้มาจากรายการผิดปกติ (ปิดงานแบบบริหาร แยกจากการส่งงานของช่าง)"),
    CapabilityEntry(authz.CAN_MANAGE_FINDING_REPAIR, "E", "จัดการงานจากรายการผิดปกติ",
                    "เปิดใบงานจากรายการผิดปกติ รับคำขอที่มาจากรายการผิดปกติ มอบหมาย/เปลี่ยนทีมช่างของรอบงานนั้น "
                    "ยกเลิกก่อนเริ่มงาน ปิดงานหลังช่างส่งงาน และยุติการติดตาม — เฉพาะงานจากรายการผิดปกติเท่านั้น"),
    CapabilityEntry(authz.CAN_MANAGE_PM, "F", "จัดการงาน PM",
                    "เปิด กำหนดขอบเขต มอบหมาย/ถอนช่าง และปิดใบงาน PM"),
    CapabilityEntry(authz.CAN_MANAGE_PERSONNEL, "G", "จัดการสถานะบุคลากร", "เปิด/ปิดการใช้งานข้อมูลบุคลากร"),
    CapabilityEntry(authz.CAN_MANAGE_DEPARTMENT, "G", "จัดการสถานะแผนก", "เปิด/ปิดการใช้งานข้อมูลแผนก"),
    CapabilityEntry(authz.CAN_LINK_PERSONNEL_TECHNICIAN, "G", "เชื่อมบุคลากรกับช่าง", "เชื่อม/ยกเลิกการเชื่อมบุคลากรกับข้อมูลช่าง"),
    CapabilityEntry(authz.CAN_LINK_PERSONNEL_ACCOUNT, "G", "เชื่อมบุคลากรกับบัญชีผู้ใช้",
                    "เชื่อม/ยกเลิกการเชื่อมบุคลากรกับบัญชีผู้ใช้ และดูรหัสบัญชีที่เชื่อมอยู่"),
    CapabilityEntry(authz.CAN_MOVE_PERSONNEL_DEPARTMENT, "G", "ย้ายแผนกของบุคลากร",
                    "บันทึกการย้ายแผนก (เมื่อมีผล สิทธิ์ทั้งหมดของผู้ถูกย้ายสิ้นสุดลง) — ไม่รวมสิทธิ์จัดการสิทธิ์"),
    CapabilityEntry(authz.CAN_LINK_PERSONNEL_DRIVER, "H", "เชื่อมบุคลากรกับคนขับ", "เชื่อม/ยกเลิกการเชื่อมบุคลากรกับข้อมูลคนขับ"),
    CapabilityEntry(authz.CAN_ASSIGN_CRANE_DRIVER, "H", "กำหนดผู้รับผิดชอบเครน", "บันทึกช่วงเวลาความรับผิดชอบของคนขับเครน"),
    CapabilityEntry(authz.CAN_ASSIGN_EQUIPMENT_CARETAKER, "H", "กำหนดผู้ดูแลเครื่องมือ", "บันทึกช่วงเวลาผู้ดูแลเครื่องมือ"),
    CapabilityEntry(authz.CAN_EDIT_VEHICLE_REGISTRATION, "H", "แก้ไขทะเบียนรถ", "แก้ไขและกระทบยอดประวัติทะเบียนรถ"),
    CapabilityEntry(authz.CAN_TRANSFER_VEHICLE_BRANCH, "H", "ย้ายสาขารถ", "ย้ายสาขาที่รับผิดชอบของรถ"),
    CapabilityEntry(authz.CAN_TRANSFER_EQUIPMENT_BRANCH, "H", "ย้ายสาขาเครื่องมือ", "กำหนด/ย้ายสาขาที่รับผิดชอบของเครื่องมือ"),
    CapabilityEntry(authz.CAN_CORRECT_BRANCH_HISTORY, "H", "แก้ไขประวัติสาขา", "แทรก แก้ไข และยกเลิกประวัติสาขาย้อนหลัง"),
    CapabilityEntry(authz.CAN_VIEW, "I", "ดูข้อมูล รายงาน และประวัติ",
                    "ดูข้อมูลหลัก รายงาน แดชบอร์ด และประวัติที่ระบบเปิดให้ดู (สิทธิ์อ่านเพียงสิทธิ์เดียว)"),
    CapabilityEntry(authz.CAN_VIEW_ACCESS_AUDIT, "J", "ดูประวัติการเปลี่ยนสิทธิ์", "ดูบันทึกการให้/ถอนสิทธิ์และการมอบอำนาจ (อ่านอย่างเดียว)"),
)
CATEGORY_NOTES_TH: dict[str, str] = {
    "D": "ไม่มีสิทธิ์แยก: การมอบหมายช่างของงานซ่อมทั่วไปใช้ 'จัดการงานซ่อม', ของงาน PM ใช้ 'จัดการงาน PM' "
         "และของรอบงานจากรายการผิดปกติใช้ 'จัดการงานจากรายการผิดปกติ' การส่งงานซ่อมทำได้เฉพาะช่างหลักคนปัจจุบันเสมอ",
    "J": "การให้/ถอนสิทธิ์และการมอบอำนาจไม่ใช่สวิตช์สิทธิ์: เป็นอำนาจของผู้จัดการแผนกซ่อมบำรุง "
         "และผู้ที่ได้รับมอบอำนาจตามขอบเขตเท่านั้น",
}
GRANTABLE: frozenset[str] = frozenset(e.code for e in CATALOG)
# D7: capabilities that change identity links, personnel lifecycle, department
# membership or read the whole access audit. Their effect is global, so only the
# root holder grants them; they are never delegable.
SENSITIVE: frozenset[str] = frozenset({
    authz.CAN_LINK_PERSONNEL_ACCOUNT, authz.CAN_LINK_PERSONNEL_TECHNICIAN, authz.CAN_LINK_PERSONNEL_DRIVER,
    authz.CAN_MANAGE_PERSONNEL, authz.CAN_MOVE_PERSONNEL_DEPARTMENT, authz.CAN_VIEW_ACCESS_AUDIT,
})
SENSITIVE_NOTE_TH = ("สิทธิ์ที่มีผลทั้งระบบ (บัญชีผู้ใช้/การเชื่อมข้อมูล สถานะบุคลากร การย้ายแผนก หรือประวัติสิทธิ์ทั้งหมด): "
                     "ผู้จัดการแผนกซ่อมบำรุงเท่านั้นที่ให้ได้ มอบอำนาจไม่ได้ และใช้กับผู้ดำรงตำแหน่งผู้จัดการไม่ได้")
_CATALOG_BY_CODE = {e.code: e for e in CATALOG}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AccessConflict(Exception):
    """Raised inside the atomic repository append (stale revision). Nothing was
    written; the service maps it to 409."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def _error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=http_status, details=details)


def _forbidden(message: str, details: dict[str, object] | None = None) -> ApiError:
    return _error("ACCESS_NOT_AUTHORIZED", message, status.HTTP_403_FORBIDDEN, details)


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return _error(code, message, status.HTTP_422_UNPROCESSABLE_CONTENT, details)


def not_enabled() -> ApiError:
    return _error("ACCESS_MANAGEMENT_NOT_ENABLED", "Access Management mode is not enabled",
                  status.HTTP_409_CONFLICT)


# ---------------------------------------------------------------------------
# Derived state
# ---------------------------------------------------------------------------


def _instant(value: object) -> datetime | None:
    raw = text(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _details(event: Mapping[str, str]) -> dict[str, object]:
    try:
        value = json.loads(text(event.get("details_json")) or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def normalize_position(raw: object) -> str:
    """A filter key only (trim, collapse whitespace, casefold); the stored
    personnel text is never changed."""
    return re.sub(r"\s+", " ", text(raw)).strip().casefold()


@dataclass(frozen=True)
class Person:
    personnel_id: str
    first_name: str
    last_name: str
    position: str
    active_status: str
    user_id: str
    department_id: str | None
    reset_at: datetime | None  # the latest department-history record (D4): earlier grants count for nothing
    department_status: str  # VALID, or the timeline status that made it unusable

    @property
    def active(self) -> bool:
        return self.active_status == ACTIVE

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(frozen=True)
class Delegation:
    delegation_id: str
    delegate_personnel_id: str
    department_id: str
    capabilities: frozenset[str]
    granted_by_personnel_id: str
    granted_at: str
    reason_th: str
    delegate_user_id: str = ""  # the delegate's verified account when granted (B1/D3)
    revoked: bool = False
    revoked_at: str | None = None
    revoked_by_personnel_id: str | None = None
    revoke_reason_th: str | None = None


@dataclass(frozen=True)
class AccessState:
    persons: dict[str, Person]
    departments: dict[str, dict[str, str]]
    events: list[dict[str, str]]
    revision: int

    def by_user(self, user_id: str) -> list[Person]:
        return [p for p in self.persons.values() if p.user_id and p.user_id == user_id]

    def _counts_after_period(self, person: Person, event: Mapping[str, str]) -> bool:
        if person.department_status != STATUS_VALID:
            return False
        if person.reset_at is None:
            return True
        recorded = _instant(event.get("recorded_at"))
        return recorded is not None and recorded > person.reset_at

    def grants(self, personnel_id: str) -> frozenset[str]:
        person = self.persons.get(personnel_id)
        if person is None or not person.active:
            return frozenset()
        current: dict[str, str] = {}
        for event in self.events:
            if text(event.get("personnel_id")) != personnel_id or event.get("kind") not in (KIND_GRANT, KIND_REVOKE):
                continue
            if self._counts_after_period(person, event):
                current[text(event.get("capability"))] = text(event.get("kind"))
        return frozenset(c for c, kind in current.items() if kind == KIND_GRANT and c in GRANTABLE)

    def root_appointments(self) -> list[dict[str, str]]:
        return [e for e in self.events if e.get("kind") == KIND_ROOT_APPOINTMENT]

    def root_target_personnel_id(self) -> str | None:
        """The employee named by the latest root appointment (valid or not):
        the record whose identity, lifecycle and department are protected."""
        appointments = self.root_appointments()
        return text(appointments[-1].get("personnel_id")) or None if appointments else None

    def root_holder(self) -> Person | None:
        """The employee of the latest root appointment, when that employee is
        active, has exactly one account link, and that link is still the account
        verified at the appointment (B1); otherwise None (no valid root)."""
        appointments = self.root_appointments()
        if not appointments:
            return None
        person = self.persons.get(text(appointments[-1].get("personnel_id")))
        if person is None or not person.active or not person.user_id or len(self.by_user(person.user_id)) != 1:
            return None
        bound = _details(appointments[-1]).get("holder_user_id")
        if not isinstance(bound, str) or bound != person.user_id:
            return None
        return person

    def delegations(self) -> list[Delegation]:
        found: dict[str, Delegation] = {}
        for event in self.events:
            kind = event.get("kind")
            if kind == KIND_DELEGATION_GRANT:
                found[text(event["delegation_id"])] = Delegation(
                    delegation_id=text(event["delegation_id"]),
                    delegate_personnel_id=text(event["personnel_id"]),
                    department_id=text(event["department_id"]),
                    capabilities=frozenset(c for c in text(event["capabilities"]).split(",") if c),
                    granted_by_personnel_id=text(event["actor_personnel_id"]),
                    granted_at=text(event["recorded_at"]),
                    reason_th=text(event["reason_th"]),
                    delegate_user_id=text(_details(event).get("delegate_user_id")),
                )
            elif kind == KIND_DELEGATION_REVOKE and text(event.get("delegation_id")) in found:
                d = found[text(event["delegation_id"])]
                found[d.delegation_id] = replace(d, revoked=True, revoked_at=text(event["recorded_at"]),
                                                 revoked_by_personnel_id=text(event["actor_personnel_id"]) or None,
                                                 revoke_reason_th=text(event["reason_th"]) or None)
        return list(found.values())

    def active_delegations(self, personnel_id: str) -> list[Delegation]:
        person = self.persons.get(personnel_id)
        if person is None or not person.active:
            return []
        out = []
        for d in self.delegations():
            if d.delegate_personnel_id != personnel_id or d.revoked:
                continue
            if not d.delegate_user_id or d.delegate_user_id != person.user_id:
                continue  # the account verified at the delegation is no longer this employee's (B1/D3)
            if self._counts_after_period(person, {"recorded_at": d.granted_at}):
                out.append(d)
        return out

    def employees_in(self, department_id: str) -> list[Person]:
        return sorted((p for p in self.persons.values() if p.department_id == department_id),
                      key=lambda p: (p.first_name, p.last_name, p.personnel_id))


@dataclass(frozen=True)
class AccessAuthority:
    """The acting employee and their permission-administration authority."""

    personnel_id: str | None
    name: str
    is_root: bool
    delegations: tuple[Delegation, ...] = ()
    recovery: bool = False
    reset_at: datetime | None = None  # assignment-based authority must be newer (B2/D5)
    department_valid: bool = False

    @property
    def administers(self) -> bool:
        return self.is_root or bool(self.delegations)

    def grantable_for(self, department_id: str | None) -> frozenset[str]:
        if self.is_root:
            return GRANTABLE
        caps: set[str] = set()
        for d in self.delegations:
            if department_id is not None and d.department_id == department_id:
                caps |= d.capabilities
        return frozenset(caps - SENSITIVE)

    def departments(self, state: AccessState) -> list[str]:
        if self.is_root:
            return sorted(state.departments)
        return sorted({d.department_id for d in self.delegations if d.department_id in state.departments})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _reason(raw: object, *, required: bool = True) -> str:
    value = text(raw).strip()
    if required and not value:
        raise _unprocessable("ACCESS_REASON_REQUIRED", "A reason is required")
    if len(value) > MAX_REASON_LENGTH:
        raise _unprocessable("ACCESS_REASON_TOO_LONG", "The reason is too long", {"max_length": MAX_REASON_LENGTH})
    return value


DEPARTMENT_OPERATIONS = frozenset({"TRANSFER", "INSERTION", "CORRECTION", "CANCELLATION"})
EXCLUDED_INACTIVE = "INACTIVE"
EXCLUDED_SELF = "SELF_NOT_EDITABLE"
EXCLUDED_ROOT = "ROOT_PROTECTED"


def _exclusion(person: Person, authority: AccessAuthority, root: Person | None) -> str | None:
    """Why this actor may not change this employee's permissions (None = may).
    D1/D2/D3: the root holder may manage everyone including themself; a delegate
    never themself nor the root holder; nobody grants to an inactive employee."""
    if not person.active:
        return EXCLUDED_INACTIVE
    if authority.is_root:
        return None
    if person.personnel_id == authority.personnel_id:
        return EXCLUDED_SELF
    if root is not None and person.personnel_id == root.personnel_id:
        return EXCLUDED_ROOT
    return None


class AccessService:
    def __init__(self, repository, data_context: str | None, batch_id: str) -> None:
        self._repository = repository
        self._context = data_context or "TEST"
        self._batch_id = batch_id

    # ---- state ----

    async def state(self) -> AccessState:
        personnel = await self._repository.read_access_personnel()
        departments = await self._repository.read_department_master_validated()
        history = await self._repository.read_personnel_department_history_validated()
        events = await self._repository.read_access_events()
        # A1/A2: identity-link history (written only for an EFFECTIVE change — a no-op, a refused change
        # or a replay writes nothing, so it never resets).
        identity_links = [row for link in (PERSONNEL_LINK_ACCOUNT, PERSONNEL_LINK_TECHNICIAN)
                          for row in (await self._repository.read_personnel_link_history_validated(link)).rows]
        persons: dict[str, Person] = {}
        for row in personnel.rows:
            if not in_scope(row, self._context, self._batch_id):
                continue
            pid = text(row.get("personnel_id"))
            if not pid.strip() or pid in persons:
                continue  # never guessed: a blank or duplicate id is not a person here
            timeline = derive_department_timeline(
                scoped_history_rows(history.rows, pid, self._context, self._batch_id))
            # D4: every department-history record (any operation) is a reset boundary;
            # A1/A2: so is every effective account-link or technician-link change.
            recorded = [_instant(r.get("recorded_at")) for r in
                        scoped_history_rows(history.rows, pid, self._context, self._batch_id)]
            recorded += [_instant(r.get("recorded_at")) for r in identity_links
                         if text(r.get("personnel_id")) == pid and in_scope(r, self._context, self._batch_id)]
            start = max((r for r in recorded if r is not None), default=None)
            persons[pid] = Person(
                personnel_id=pid, first_name=text(row.get("first_name")), last_name=text(row.get("last_name")),
                position=text(row.get("position")), active_status=text(row.get("active_status")),
                user_id=text(row.get("user_id")), department_id=timeline.current_department_id,
                reset_at=start, department_status=timeline.status,
            )
        depts = {text(r.get("department_id")): dict(r) for r in departments.rows
                 if in_scope(r, self._context, self._batch_id) and text(r.get("department_id")).strip()}
        return AccessState(persons=persons, departments=depts, events=list(events), revision=len(events))

    def resolve(self, state: AccessState, user_id: str | None, roles: Sequence[str]) -> tuple[Person | None, AccessAuthority]:
        recovery = "ADMIN" in roles  # technical recovery (development login in this Mock only)
        person = None
        if user_id and user_id.strip():
            matches = state.by_user(user_id)
            person = matches[0] if len(matches) == 1 else None
        if person is None or not person.active:
            return None, AccessAuthority(personnel_id=None, name="", is_root=False, recovery=recovery)
        root = state.root_holder()
        return person, AccessAuthority(
            personnel_id=person.personnel_id, name=person.name,
            is_root=root is not None and root.personnel_id == person.personnel_id,
            delegations=tuple(state.active_delegations(person.personnel_id)), recovery=recovery,
            reset_at=person.reset_at, department_valid=person.department_status == STATUS_VALID,
        )

    async def effective_context(self, context):
        """The request context of Access Management mode: capabilities are EXACTLY
        the actor's effective grants (nothing from the development role table)."""
        state = await self.state()
        person, authority = self.resolve(state, context.user_id, context.roles)
        capabilities = state.grants(person.personnel_id) if person else frozenset()
        return replace(context, capabilities=capabilities,
                       personnel_id=person.personnel_id if person else None, access=authority)

    # ---- helpers ----

    @staticmethod
    def authority(context) -> AccessAuthority:
        access = getattr(context, "access", None)
        if not isinstance(access, AccessAuthority):
            raise not_enabled()
        return access

    def _event(self, kind: str, actor, *, request_id: str, fingerprint: str, **cells: str) -> dict[str, str]:
        authority = self.authority(actor)
        row = dict.fromkeys(ACCESS_EVENT_COLUMNS, "")
        row.update(event_id=f"ACE-{uuid.uuid4().hex}", kind=kind, actor_personnel_id=authority.personnel_id or "",
                   actor_user_id=text(actor.user_id), actor_name_snapshot=authority.name,
                   recorded_at=_now_iso(), request_id=request_id, request_fingerprint=fingerprint)
        row.update(cells)
        return row

    def _fingerprint(self, operation: str, context, body: Mapping[str, object], target: str = "") -> str:
        """The request fingerprint scoped to the verified actor: another actor
        reusing the id gets REQUEST_ID_REUSED, never this actor's result."""
        authority = self.authority(context)
        actor = f"{authority.personnel_id or ''}|{text(context.user_id)}"
        return request_fingerprint(operation, target, actor, body)

    def require_root_protection(self, state: AccessState, context, personnel_id: str, operation: str) -> None:
        """B1 — the employee named by the latest root appointment keeps their
        account link, lifecycle and department unless the trusted pathway acts:
        - IDENTITY / LIFECYCLE: only technical recovery while no valid holder
          exists (the holder hands the position over first; no self-lockout);
        - DEPARTMENT: the holder themself, or recovery while no valid holder exists.
        Ordinary capabilities never suffice, whoever granted them."""
        if personnel_id != state.root_target_personnel_id():
            return
        authority = self.authority(context)
        holder = state.root_holder()
        recovery = authority.recovery and holder is None
        if recovery or (operation == "DEPARTMENT" and authority.is_root):
            return
        raise _error("ACCESS_ROOT_PROTECTED", "The Maintenance Department Manager position holder's account, "
                     "status and department are protected; hand the position over first",
                     status.HTTP_403_FORBIDDEN, {"personnel_id": personnel_id, "operation": operation})

    @staticmethod
    def _replay(state: AccessState, request_id: str, fingerprint: str) -> list[dict[str, str]] | None:
        rows = [e for e in state.events if e.get("request_id") == request_id]
        if not rows:
            return None
        if any(e.get("request_fingerprint") != fingerprint for e in rows):
            raise _error("REQUEST_ID_REUSED", "This X-Request-Id was already used for a different change",
                         status.HTTP_409_CONFLICT, {"request_id": request_id})
        return rows

    async def _append(self, rows: list[dict[str, str]], expected_revision: int) -> None:
        try:
            await self._repository.append_access_events(rows, expected_revision)
        except AccessConflict as conflict:
            raise _error(conflict.code, conflict.message, status.HTTP_409_CONFLICT, conflict.details) from conflict

    @staticmethod
    def _expected_revision(body: Mapping[str, object], state: AccessState) -> int:
        raw = body.get("expected_revision")
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise _unprocessable("VALIDATION_ERROR", "expected_revision (integer) is required",
                                 {"field": "expected_revision"})
        if raw != state.revision:
            raise _error("ACCESS_STALE_REVISION", "Permissions changed since this screen was loaded; reload",
                         status.HTTP_409_CONFLICT, {"expected_revision": raw, "current_revision": state.revision})
        return raw

    # ---- reads ----

    def me(self, state: AccessState, context) -> dict[str, object]:
        authority = self.authority(context)
        root = state.root_holder()
        return {
            "personnel_id": authority.personnel_id, "name": authority.name, "is_root": authority.is_root,
            "recovery": authority.recovery, "revision": state.revision,
            "root_holder_personnel_id": root.personnel_id if root else None,
            "delegations": [self._delegation_view(state, d) for d in authority.delegations],
            "capabilities": sorted(context.capabilities),
        }

    def catalog(self) -> dict[str, object]:
        return {
            "categories": [
                {"code": code, "label_th": label, "note_th": CATEGORY_NOTES_TH.get(code),
                 "capabilities": [{"code": e.code, "label_th": e.label_th, "effect_th": e.effect_th,
                                   "sensitive": e.code in SENSITIVE}
                                  for e in CATALOG if e.category == code]}
                for code, label in CATEGORIES
            ],
            "sensitive_note_th": SENSITIVE_NOTE_TH,
        }

    def require_admin(self, context) -> AccessAuthority:
        authority = self.authority(context)
        if not authority.administers:
            raise _forbidden("Permission administration requires the root position or an active delegation")
        return authority

    def departments(self, state: AccessState, context) -> list[dict[str, object]]:
        authority = self.require_admin(context)
        out = []
        for dept_id in authority.departments(state):
            row = state.departments[dept_id]
            out.append({"department_id": dept_id, "department_name_th": text(row.get("department_name_th")),
                        "is_active": text(row.get("is_active")) == "TRUE",
                        "employee_count": len([p for p in state.employees_in(dept_id) if p.active]),
                        "grantable": sorted(authority.grantable_for(dept_id))})
        return out

    def employees(self, state: AccessState, context, department_id: str) -> dict[str, object]:
        authority = self.require_admin(context)
        if department_id not in authority.departments(state):
            raise _forbidden("This department is outside your administration scope",
                             {"department_id": department_id})
        people = state.employees_in(department_id)
        positions: dict[str, str] = {}
        for p in people:
            key = normalize_position(p.position)
            if key:
                positions.setdefault(key, " ".join(p.position.split()))
        active = [p for p in people if p.active]
        root = state.root_holder()
        counts = {cap: sum(1 for p in active if cap in state.grants(p.personnel_id)) for cap in sorted(GRANTABLE)}
        return {
            "department_id": department_id, "revision": state.revision,
            "grantable": sorted(authority.grantable_for(department_id)),
            "positions": [{"key": k, "label": v} for k, v in sorted(positions.items(), key=lambda kv: kv[1])],
            "employees": [{
                "personnel_id": p.personnel_id, "name": p.name, "position": " ".join(p.position.split()),
                "position_key": normalize_position(p.position), "active": p.active,
                "is_self": p.personnel_id == authority.personnel_id,
                "is_root": root is not None and root.personnel_id == p.personnel_id,
                "exclusion": _exclusion(p, authority, root),
                "capabilities": sorted(state.grants(p.personnel_id)),
            } for p in people],
            "active_employee_count": len(active),
            "capability_counts": counts,
        }

    # ---- grants ----

    def _plan(self, state: AccessState, context, body: Mapping[str, object]) -> dict[str, object]:
        authority = self.require_admin(context)
        target = body.get("target")
        changes = body.get("changes")
        if not isinstance(target, Mapping) or not isinstance(changes, Mapping) or not changes:
            raise _unprocessable("VALIDATION_ERROR", "target and a non-empty changes map are required")
        unknown = sorted(str(c) for c in changes if c not in GRANTABLE)
        if unknown or not all(isinstance(v, bool) for v in changes.values()):
            raise _unprocessable("ACCESS_CAPABILITY_NOT_GRANTABLE", "Only catalog capabilities with true/false "
                                 "values can be changed", {"capabilities": unknown})
        root = state.root_holder()
        kind = target.get("kind")
        if kind == TARGET_EMPLOYEE:
            pid = text(target.get("personnel_id"))
            person = state.persons.get(pid)
            if person is None:
                raise _error("ACCESS_EMPLOYEE_NOT_FOUND", "Employee not found in scope", status.HTTP_404_NOT_FOUND)
            department_id = person.department_id
            if not authority.is_root and (department_id is None or department_id not in authority.departments(state)):
                raise _forbidden("This employee is outside your administration scope", {"personnel_id": pid})
            reason = _exclusion(person, authority, root)
            if reason == EXCLUDED_INACTIVE:
                raise _error("ACCESS_EMPLOYEE_INACTIVE", "An inactive employee cannot receive permissions",
                             status.HTTP_409_CONFLICT, {"personnel_id": pid})
            if reason == EXCLUDED_SELF:
                raise _forbidden("You cannot change your own permissions")
            if reason == EXCLUDED_ROOT:
                raise _error("ACCESS_ROOT_PROTECTED", "Only the Maintenance Department Manager manages their own "
                             "permissions", status.HTTP_403_FORBIDDEN, {"personnel_id": pid})
            eligible, targets, excluded = [person], [person], []
        elif kind == TARGET_DEPARTMENT:
            department_id = text(target.get("department_id"))
            if department_id not in state.departments:
                raise _error("ACCESS_DEPARTMENT_NOT_FOUND", "Department not found in scope", status.HTTP_404_NOT_FOUND)
            if department_id not in authority.departments(state):
                raise _forbidden("This department is outside your administration scope",
                                 {"department_id": department_id})
            # D1: "everyone in the department" is every current member; nobody is dropped silently —
            # anyone this actor may not edit is listed with the reason before the confirmation.
            people = state.employees_in(department_id)
            eligible = [p for p in people if p.active]
            excluded = [{"personnel_id": p.personnel_id, "name": p.name, "reason": r}
                        for p in people if (r := _exclusion(p, authority, root))]
            targets = [p for p in eligible if not _exclusion(p, authority, root)]
        else:
            raise _unprocessable("VALIDATION_ERROR", "target.kind must be EMPLOYEE or DEPARTMENT")
        allowed = authority.grantable_for(department_id)
        denied = sorted(c for c in changes if c not in allowed)
        if denied:
            raise _forbidden("These capabilities are outside your administration authority", {"capabilities": denied})
        per_capability = []
        events: list[tuple[str, str, str]] = []
        for cap, on in sorted(changes.items()):
            change = [p.personnel_id for p in targets if (cap in state.grants(p.personnel_id)) != on]
            events.extend((pid, cap, KIND_GRANT if on else KIND_REVOKE) for pid in change)
            per_capability.append({"capability": cap, "action": "GRANT" if on else "REVOKE",
                                   "changed": len(change), "unchanged": len(targets) - len(change)})
        return {"target_kind": kind, "department_id": department_id, "eligible_count": len(eligible),
                "target_count": len(targets), "target_personnel_ids": [p.personnel_id for p in targets],
                "excluded": excluded, "skipped_personnel_ids": [e["personnel_id"] for e in excluded],
                "per_capability": per_capability, "events": events}

    async def preview(self, context, body: Mapping[str, object]) -> dict[str, object]:
        state = await self.state()
        plan = self._plan(state, context, body)
        plan.pop("events")
        plan["revision"] = state.revision
        return plan

    async def apply(self, context, body: Mapping[str, object], *, request_id: str) -> dict[str, object]:
        state = await self.state()
        self.require_admin(context)  # authority before any replay is disclosed
        fingerprint = self._fingerprint("access_grants", context, body)
        replayed = self._replay(state, request_id, fingerprint)
        if replayed is not None:
            batch = next(e for e in replayed if e["kind"] == KIND_BATCH)
            return {"replayed": True, "batch_id": batch["batch_id"], **json.loads(batch["details_json"])}
        reason = _reason(body.get("reason_th"))
        expected = self._expected_revision(body, state)
        plan = self._plan(state, context, body)
        batch_id = f"ACB-{uuid.uuid4().hex}"
        rows = [self._event(kind, context, request_id=request_id, fingerprint=fingerprint, personnel_id=pid,
                            capability=cap, batch_id=batch_id, target_kind=plan["target_kind"],
                            department_id=plan["department_id"] or "", reason_th=reason)
                for pid, cap, kind in plan["events"]]
        summary = {k: plan[k] for k in ("target_kind", "department_id", "eligible_count", "target_count",
                                        "target_personnel_ids", "excluded", "skipped_personnel_ids",
                                        "per_capability")}
        rows.append(self._event(KIND_BATCH, context, request_id=request_id, fingerprint=fingerprint,
                                batch_id=batch_id, target_kind=plan["target_kind"],
                                department_id=plan["department_id"] or "", reason_th=reason,
                                details_json=json.dumps(summary, ensure_ascii=False, sort_keys=True)))
        await self._append(rows, expected)
        return {"replayed": False, "batch_id": batch_id, **summary, "revision": expected + len(rows)}

    # ---- delegation ----

    def _require_root(self, context) -> AccessAuthority:
        authority = self.authority(context)
        if not authority.is_root:
            raise _forbidden("Only the Maintenance Department Manager can delegate or revoke administration")
        return authority

    def _delegation_view(self, state: AccessState, d: Delegation) -> dict[str, object]:
        delegate = state.persons.get(d.delegate_personnel_id)
        effective = (not d.revoked and delegate is not None and d in state.active_delegations(delegate.personnel_id))
        dept = state.departments.get(d.department_id, {})
        return {"delegation_id": d.delegation_id, "delegate_personnel_id": d.delegate_personnel_id,
                "delegate_name": delegate.name if delegate else "", "department_id": d.department_id,
                "department_name_th": text(dept.get("department_name_th")), "capabilities": sorted(d.capabilities),
                "granted_by_personnel_id": d.granted_by_personnel_id, "granted_at": d.granted_at,
                "reason_th": d.reason_th, "revoked": d.revoked, "revoked_at": d.revoked_at,
                "revoked_by_personnel_id": d.revoked_by_personnel_id, "revoke_reason_th": d.revoke_reason_th,
                "effective": effective}

    async def delegations(self, context) -> list[dict[str, object]]:
        state = await self.state()
        authority = self.authority(context)
        if not authority.is_root and CAN_AUDIT not in context.capabilities:
            raise _forbidden("Only the Maintenance Department Manager or an audit viewer can list delegations")
        return [self._delegation_view(state, d) for d in state.delegations()]

    async def delegate(self, context, body: Mapping[str, object], *, request_id: str) -> dict[str, object]:
        state = await self.state()
        authority = self._require_root(context)  # authority before any replay is disclosed
        fingerprint = self._fingerprint("access_delegation", context, body)
        replayed = self._replay(state, request_id, fingerprint)
        if replayed is not None:
            return {"replayed": True, **self._delegation_view(state, next(
                d for d in state.delegations() if d.delegation_id == replayed[0]["delegation_id"]))}
        reason = _reason(body.get("reason_th"))
        expected = self._expected_revision(body, state)
        pid = text(body.get("delegate_personnel_id"))
        delegate = state.persons.get(pid)
        if delegate is None:
            raise _error("ACCESS_EMPLOYEE_NOT_FOUND", "Employee not found in scope", status.HTTP_404_NOT_FOUND)
        if pid == authority.personnel_id:
            raise _forbidden("The root administrator cannot delegate to themselves")
        if not delegate.active or not delegate.user_id or len(state.by_user(delegate.user_id)) != 1:
            raise _error("ACCESS_EMPLOYEE_NOT_ELIGIBLE", "The delegate must be active with exactly one account link",
                         status.HTTP_409_CONFLICT, {"personnel_id": pid})
        department_id = text(body.get("department_id"))
        if department_id not in state.departments:
            raise _error("ACCESS_DEPARTMENT_NOT_FOUND", "Department not found in scope", status.HTTP_404_NOT_FOUND)
        caps = body.get("capabilities")
        if not isinstance(caps, list) or not caps or not all(isinstance(c, str) for c in caps):
            raise _unprocessable("VALIDATION_ERROR", "capabilities must be a non-empty list")
        unknown = sorted(c for c in caps if c not in GRANTABLE)
        if unknown:
            raise _unprocessable("ACCESS_CAPABILITY_NOT_GRANTABLE", "Only catalog capabilities can be delegated",
                                 {"capabilities": unknown})
        sensitive = sorted(c for c in caps if c in SENSITIVE)
        if sensitive:
            raise _unprocessable("ACCESS_CAPABILITY_NOT_DELEGABLE", "Security-sensitive capabilities act "
                                 "system-wide and can only be granted by the Maintenance Department Manager",
                                 {"capabilities": sensitive})
        delegation_id = f"ACD-{uuid.uuid4().hex}"
        row = self._event(KIND_DELEGATION_GRANT, context, request_id=request_id, fingerprint=fingerprint,
                          personnel_id=pid, delegation_id=delegation_id, department_id=department_id,
                          capabilities=",".join(sorted(set(caps))), reason_th=reason,
                          details_json=json.dumps({"delegate_user_id": delegate.user_id}))
        await self._append([row], expected)
        after = await self.state()
        return {"replayed": False, **self._delegation_view(after, next(
            d for d in after.delegations() if d.delegation_id == delegation_id))}

    async def revoke_delegation(self, context, delegation_id: str, body: Mapping[str, object], *,
                                request_id: str) -> dict[str, object]:
        state = await self.state()
        self._require_root(context)  # authority before any replay is disclosed
        fingerprint = self._fingerprint("access_delegation_revocation", context, body, delegation_id)
        if self._replay(state, request_id, fingerprint) is not None:
            return {"replayed": True, **self._delegation_view(state, next(
                d for d in state.delegations() if d.delegation_id == delegation_id))}
        reason = _reason(body.get("reason_th"))
        expected = self._expected_revision(body, state)
        delegation = next((d for d in state.delegations() if d.delegation_id == delegation_id), None)
        if delegation is None:
            raise _error("ACCESS_DELEGATION_NOT_FOUND", "Delegation not found", status.HTTP_404_NOT_FOUND)
        if delegation.revoked:
            raise _error("ACCESS_DELEGATION_ALREADY_REVOKED", "This delegation was already revoked",
                         status.HTTP_409_CONFLICT, {"delegation_id": delegation_id})
        row = self._event(KIND_DELEGATION_REVOKE, context, request_id=request_id, fingerprint=fingerprint,
                          delegation_id=delegation_id, personnel_id=delegation.delegate_personnel_id,
                          department_id=delegation.department_id, reason_th=reason)
        await self._append([row], expected)
        after = await self.state()
        return {"replayed": False, **self._delegation_view(after, next(
            d for d in after.delegations() if d.delegation_id == delegation_id))}

    # ---- root position ----

    def root_view(self, state: AccessState) -> dict[str, object]:
        holder = state.root_holder()
        return {
            "position_th": ROOT_POSITION_TH,
            "holder": {"personnel_id": holder.personnel_id, "name": holder.name} if holder else None,
            "valid": holder is not None, "revision": state.revision,
            "appointments": [{
                "personnel_id": e["personnel_id"], "name": (state.persons[e["personnel_id"]].name
                                                            if e["personnel_id"] in state.persons else ""),
                "appointed_at": e["recorded_at"], "mode": json.loads(e["details_json"] or "{}").get("mode"),
                "actor_personnel_id": e["actor_personnel_id"] or None, "actor_user_id": e["actor_user_id"] or None,
                "actor_name_snapshot": e["actor_name_snapshot"] or None, "reason_th": e["reason_th"],
            } for e in state.root_appointments()],
        }

    async def appoint_root(self, context, body: Mapping[str, object], *, request_id: str) -> dict[str, object]:
        state = await self.state()
        authority = self.authority(context)
        # The fingerprint is actor-scoped, so a replay hit is this actor's own appointment; it discloses only
        # the root view every Access Management actor may read. Another actor's id answers REQUEST_ID_REUSED.
        fingerprint = self._fingerprint("access_root_appointment", context, body)
        if self._replay(state, request_id, fingerprint) is not None:
            return {"replayed": True, **self.root_view(state)}
        current = state.root_holder()
        if authority.is_root:
            mode = "HANDOVER"
        elif authority.recovery and current is None:
            mode = "RECOVERY"
        else:
            raise _forbidden("Only the current Maintenance Department Manager (or technical recovery while no "
                             "valid holder exists) can appoint the position holder")
        reason = _reason(body.get("reason_th"))
        expected = self._expected_revision(body, state)
        pid = text(body.get("personnel_id"))
        successor = state.persons.get(pid)
        if successor is None:
            raise _error("ACCESS_EMPLOYEE_NOT_FOUND", "Employee not found in scope", status.HTTP_404_NOT_FOUND)
        if pid == authority.personnel_id or (current is not None and pid == current.personnel_id):
            raise _forbidden("The position holder cannot be re-appointed or self-appointed")
        if not successor.active or not successor.user_id or len(state.by_user(successor.user_id)) != 1:
            raise _error("ACCESS_EMPLOYEE_NOT_ELIGIBLE", "The holder must be active with exactly one account link",
                         status.HTTP_409_CONFLICT, {"personnel_id": pid})
        row = self._event(KIND_ROOT_APPOINTMENT, context, request_id=request_id, fingerprint=fingerprint,
                          personnel_id=pid, reason_th=reason,
                          details_json=json.dumps({"mode": mode, "holder_user_id": successor.user_id}))
        await self._append([row], expected)
        return {"replayed": False, **self.root_view(await self.state())}

    # ---- audit ----

    async def audit(self, context, *, personnel_id: str | None = None,
                    department_id: str | None = None) -> list[dict[str, object]]:
        state = await self.state()
        authority = self.authority(context)
        viewer = CAN_AUDIT in context.capabilities
        if not (authority.is_root or viewer or authority.delegations):
            raise _forbidden("Audit history requires the root position, an active delegation or the audit capability")
        scope = None if (authority.is_root or viewer) else set(authority.departments(state))
        out: list[dict[str, object]] = []
        for e in state.events:
            target = state.persons.get(e["personnel_id"]) if e["personnel_id"] else None
            dept = e["department_id"] or (target.department_id if target else None)
            if scope is not None and dept not in scope:
                continue
            if personnel_id and e["personnel_id"] != personnel_id:
                continue
            if department_id and dept != department_id:
                continue
            out.append({k: e[k] for k in ("event_id", "kind", "personnel_id", "capability", "delegation_id",
                                         "department_id", "capabilities", "actor_personnel_id", "actor_user_id",
                                         "actor_name_snapshot", "recorded_at", "reason_th", "batch_id",
                                         "target_kind")} | {
                "target_name": target.name if target else ""})
        # D4: every department-history record is itself a reset boundary (derived); each is
        # labelled by its own operation (transfer / insertion / correction / cancellation).
        history = await self._repository.read_personnel_department_history_validated()
        for row in history.rows:
            pid = text(row.get("personnel_id"))
            if pid not in state.persons or not in_scope(row, self._context, self._batch_id):
                continue
            dept = text(row.get("department_id")) or state.persons[pid].department_id
            if scope is not None and dept not in scope:
                continue
            if (personnel_id and pid != personnel_id) or (department_id and dept != department_id):
                continue
            operation = text(row.get("entry_operation"))
            kind = (f"DEPARTMENT_{operation}_PERMISSIONS_RESET" if operation in DEPARTMENT_OPERATIONS
                    else "DEPARTMENT_MOVEMENT_PERMISSIONS_RESET")
            out.append({"event_id": text(row.get("record_id")), "kind": kind,
                        "personnel_id": pid, "capability": "", "delegation_id": "", "department_id": dept or "",
                        "capabilities": "", "actor_personnel_id": "", "actor_user_id": text(row.get("recorded_by")),
                        "actor_name_snapshot": "", "recorded_at": text(row.get("recorded_at")),
                        "reason_th": text(row.get("reason_th")), "batch_id": "", "target_kind": TARGET_EMPLOYEE,
                        "target_name": state.persons[pid].name})
        out.sort(key=lambda r: str(r["recorded_at"]), reverse=True)
        return out


CAN_AUDIT = authz.CAN_VIEW_ACCESS_AUDIT


def build_access_event_row(**cells: str) -> dict[str, str]:
    """A complete access_event row (seed / test helper)."""
    row = dict.fromkeys(ACCESS_EVENT_COLUMNS, "")
    row.update(cells)
    return row


__all__ = [
    "ACCESS_EVENT_COLUMNS",
    "ACCESS_PERSONNEL_COLUMNS",
    "CATALOG",
    "CATEGORIES",
    "GRANTABLE",
    "KIND_ROOT_APPOINTMENT",
    "AccessAuthority",
    "AccessConflict",
    "AccessService",
    "AccessState",
    "build_access_event_row",
    "normalize_position",
    "not_enabled",
]
