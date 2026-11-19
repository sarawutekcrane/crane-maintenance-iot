"""R8 PRE-UAT Whole-Web Completion — TEST master records (Owner source approval Rev 1,
2026-11-18, workstream A) and the shared PRE-UAT write helpers.

Mock/TEST only. Create / edit for the organisation and fleet masters named in Roadmap
R2: vehicle, model, equipment, branch, department, personnel and technician.

- Only columns of the existing schemas are accepted; unknown keys are refused (422).
  No field is inferred.
- IDs are allocated by the server as `<PREFIX>-TEST-<n>` (collision-checked). They are
  never derived from a row number or a name; the real ID policy belongs to R12.
- Every new record is TEST-scoped (mock batch). Edits are allowed only on TEST-scoped
  records, so a TEST write never changes an operational row.
- Every change appends one MASTER_AUDIT journal row (history first). It carries the
  actor, the client X-Request-Id and a payload fingerprint. A replay returns the
  original outcome; reusing an id with another payload is 409 REQUEST_ID_REUSED.
- No delete. Deactivation stays with the existing lifecycle routes (personnel /
  department) or the existing status routes (vehicle / equipment). Model and branch
  have no approved lifecycle vocabulary (Owner D-8) and are not deactivated here.
- Installation positions have no master schema (standard-data dependency); not built.

Google Sheets inherits the repository's 501 for these methods. A REAL data context is
refused with 409 MASTER_RECORD_REAL_NOT_ENABLED.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import status

from app.domain.authz import CAN_VIEW
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryConcurrentChangeError

# ---------------------------------------------------------------------------
# Shared PRE-UAT helpers (used by master records, store workflow and repair classification)
# ---------------------------------------------------------------------------

DATA_CONTEXT_TEST = "TEST"


def api_error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=http_status, details=details)


def forbidden(code: str, message: str) -> ApiError:
    return api_error(code, message, status.HTTP_403_FORBIDDEN)


def require_preuat_actor(context, capability: str, action_th: str) -> None:
    """Before ANY repository read: a trusted actor holding `capability` and `can_view`,
    resolved by Access Management to exactly one active employee. No development role
    holds a PRE-UAT capability, so legacy mode always refuses here."""
    if not (getattr(context, "user_id", None) or "").strip():
        raise forbidden("ACCESS_ACTOR_NOT_VERIFIED", f"{action_th} requires a trusted, authenticated actor")
    capabilities = getattr(context, "capabilities", frozenset())
    if capability not in capabilities or CAN_VIEW not in capabilities:
        raise forbidden("PREUAT_ACTION_NOT_AUTHORIZED",
                        f"{action_th} requires the per-employee TEST grant '{capability}' and '{CAN_VIEW}'")
    if getattr(context, "access", None) is None or not getattr(context, "personnel_id", None):
        raise forbidden("ACCESS_ACTOR_NOT_VERIFIED",
                        f"{action_th} requires an active TEST employee linked to exactly one account")


def require_mock_test(mock_repository: bool, data_context: str | None, feature: str, real_code: str) -> None:
    """Mock/TEST only: another repository answers 501, a non-TEST context 409."""
    if not mock_repository:
        raise api_error("FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE",
                        f"'{feature}' is available only in the synthetic Mock/TEST repository",
                        status.HTTP_501_NOT_IMPLEMENTED, {"feature": feature})
    if data_context != DATA_CONTEXT_TEST:
        raise api_error(real_code, f"'{feature}' is enabled only in the TEST data context; nothing was written",
                        status.HTTP_409_CONFLICT)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(op: str, target: str, body: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical({"op": op, "target": target, "body": dict(body)}).encode("utf-8")).hexdigest()


def replay_rows(rows: Sequence[Mapping[str, str]], request_id: str, request_fingerprint: str) -> list[dict[str, str]]:
    """The rows already appended under `request_id` (empty: a new request). Rows under
    the same id with another fingerprint mean 409 REQUEST_ID_REUSED."""
    matches = [dict(r) for r in rows if r.get("request_id") == request_id]
    if matches and any(r.get("fingerprint") != request_fingerprint for r in matches):
        raise api_error("REQUEST_ID_REUSED", "This X-Request-Id was already used for a different change; "
                        "nothing was written", status.HTTP_409_CONFLICT)
    return matches


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_event_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


async def guarded_append(repository: Repository, journal: str, read_count: int, rows: list[dict[str, str]],
                         conflict_code: str) -> None:
    try:
        await repository.append_preuat_journal(journal, expected_count=read_count, rows=rows)
    except RepositoryConcurrentChangeError as exc:
        raise api_error(conflict_code, "Another change was recorded at the same time; nothing was written. "
                        "Reload and try again", status.HTTP_409_CONFLICT) from exc


# ---------------------------------------------------------------------------
# Master records
# ---------------------------------------------------------------------------

JOURNAL_MASTER_AUDIT = "MASTER_AUDIT"
MAX_TEXT = 120

_VEHICLE_STATUSES = ("WORKING", "READY", "MAINTENANCE", "OUT_OF_SERVICE", "LONG_TERM_PARKING")


def _enum_values(module: str, name: str) -> tuple[str, ...]:
    import importlib

    enum = getattr(importlib.import_module(module), name)
    return tuple(member.value for member in enum)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    required: bool = True
    choices: tuple[str, ...] | None = None
    multi: bool = False  # comma-separated list of choices


@dataclass(frozen=True)
class EntitySpec:
    entity: str
    prefix: str
    id_column: str
    create: tuple[FieldSpec, ...]
    edit: tuple[FieldSpec, ...] = ()
    unique: tuple[str, ...] = ()
    label_th: str = ""


def _specs() -> dict[str, EntitySpec]:
    equipment_categories = _enum_values("app.domain.equipment", "EquipmentCategory")
    equipment_statuses = _enum_values("app.domain.equipment", "EquipmentOperationalStatus")
    roles = _enum_values("app.domain.vehicle_model", "ComponentRole")
    return {
        "VEHICLE": EntitySpec("VEHICLE", "VEH-TEST", "vehicle_id", (
            FieldSpec("machine_no"), FieldSpec("model_id"), FieldSpec("serial_number", required=False),
            FieldSpec("operational_status", choices=_VEHICLE_STATUSES)),
            unique=("machine_no",), label_th="รถ"),
        "MODEL": EntitySpec("MODEL", "MODEL-TEST", "model_id", (
            FieldSpec("model_code"), FieldSpec("model_name"), FieldSpec("brand", required=False),
            FieldSpec("description", required=False), FieldSpec("component_roles", choices=roles, multi=True)),
            edit=(FieldSpec("model_name"), FieldSpec("brand", required=False),
                  FieldSpec("description", required=False)),
            unique=("model_code",), label_th="รุ่นรถ"),
        "EQUIPMENT": EntitySpec("EQUIPMENT", "EQP-TEST", "equipment_id", (
            FieldSpec("equipment_code"), FieldSpec("name"), FieldSpec("category", choices=equipment_categories),
            FieldSpec("serial_number", required=False), FieldSpec("location", required=False),
            FieldSpec("operational_status", choices=equipment_statuses)),
            edit=(FieldSpec("name"), FieldSpec("serial_number", required=False),
                  FieldSpec("location", required=False)),
            unique=("equipment_code",), label_th="เครื่องมือ"),
        "BRANCH": EntitySpec("BRANCH", "BR-TEST", "branch_id", (FieldSpec("branch_name"),),
                             edit=(FieldSpec("branch_name"),), unique=("branch_name",), label_th="สาขา"),
        "DEPARTMENT": EntitySpec("DEPARTMENT", "DEPT-TEST", "department_id", (FieldSpec("department_name_th"),),
                                 edit=(FieldSpec("department_name_th"),), unique=("department_name_th",),
                                 label_th="แผนก"),
        "PERSONNEL": EntitySpec("PERSONNEL", "PER-TEST", "personnel_id", (
            FieldSpec("first_name"), FieldSpec("last_name"), FieldSpec("position", required=False)),
            edit=(FieldSpec("first_name"), FieldSpec("last_name"), FieldSpec("position", required=False)),
            label_th="บุคลากร"),
        "TECHNICIAN": EntitySpec("TECHNICIAN", "TEC-TEST", "technician_id", (
            FieldSpec("first_name"), FieldSpec("last_name")),
            edit=(FieldSpec("first_name"), FieldSpec("last_name")), label_th="ช่าง"),
    }


ENTITY_SPECS = _specs()
PATH_ENTITIES = {"vehicles": "VEHICLE", "models": "MODEL", "equipment": "EQUIPMENT", "branches": "BRANCH",
                 "departments": "DEPARTMENT", "personnel": "PERSONNEL", "technicians": "TECHNICIAN"}


def entity_of(path_entity: str) -> EntitySpec:
    entity = PATH_ENTITIES.get(path_entity)
    if entity is None:
        raise api_error("MASTER_ENTITY_UNKNOWN", "Unknown master type", status.HTTP_404_NOT_FOUND,
                        {"entity": path_entity[:40]})
    return ENTITY_SPECS[entity]


def _validate(fields: Sequence[FieldSpec], body: Mapping[str, object], *, partial: bool) -> dict[str, str]:
    allowed = {f.name for f in fields}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise api_error("VALIDATION_ERROR", "Unknown or non-editable field(s)", 422, {"fields": unknown[:10]})
    values: dict[str, str] = {}
    for spec in fields:
        if spec.name not in body:
            if spec.required and not partial:
                raise api_error("VALIDATION_ERROR", f"'{spec.name}' is required", 422, {"field": spec.name})
            continue
        raw = body[spec.name]
        if raw is None:
            raw = ""
        if spec.multi:
            if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
                raise api_error("VALIDATION_ERROR", f"'{spec.name}' must be a list of codes", 422,
                                {"field": spec.name})
            items = [x.strip() for x in raw]
            if not items or any(x not in (spec.choices or ()) for x in items) or len(set(items)) != len(items):
                raise api_error("VALIDATION_ERROR", f"'{spec.name}' holds an unknown or repeated code", 422,
                                {"field": spec.name})
            values[spec.name] = ",".join(items)
            continue
        if not isinstance(raw, str):
            raise api_error("VALIDATION_ERROR", f"'{spec.name}' must be text", 422, {"field": spec.name})
        text = raw.strip()
        if len(text) > MAX_TEXT:
            raise api_error("VALIDATION_ERROR", f"'{spec.name}' is too long", 422, {"field": spec.name})
        if spec.required and not text:
            raise api_error("VALIDATION_ERROR", f"'{spec.name}' is required", 422, {"field": spec.name})
        if spec.choices is not None and text not in spec.choices:
            raise api_error("VALIDATION_ERROR", f"'{spec.name}' is not an allowed value", 422, {"field": spec.name})
        values[spec.name] = text
    if partial and not values:
        raise api_error("VALIDATION_ERROR", "Nothing to change", 422)
    return values


@dataclass
class MasterOutcome:
    entity: str
    record_id: str
    action: str
    replayed: bool
    event_id: str
    values: dict[str, str] = field(default_factory=dict)


class MasterRecordService:
    def __init__(self, repository: Repository, data_context: str | None, batch_id: str, *,
                 mock_repository: bool) -> None:
        self._repository = repository
        self._data_context = data_context
        self._batch_id = batch_id
        self._mock = mock_repository

    def _require_mode(self) -> None:
        require_mock_test(self._mock, self._data_context, "master_records", "MASTER_RECORD_REAL_NOT_ENABLED")

    async def list_records(self, spec: EntitySpec) -> list[dict[str, str]]:
        self._require_mode()
        return await self._repository.list_preuat_master_records(spec.entity)

    def _allocate(self, spec: EntitySpec, rows: Sequence[Mapping[str, str]]) -> str:
        used = {r.get(spec.id_column, "") for r in rows}
        n = 5001
        while f"{spec.prefix}-{n}" in used:
            n += 1
        return f"{spec.prefix}-{n}"

    async def create(self, spec: EntitySpec, body: Mapping[str, object], context, *, request_id: str) -> MasterOutcome:
        self._require_mode()
        values = _validate(spec.create, body, partial=False)
        fp = fingerprint("master_create", spec.entity, body)
        audit = await self._repository.read_preuat_journal(JOURNAL_MASTER_AUDIT)
        replay = replay_rows(audit, request_id, fp)
        if replay:
            row = replay[0]
            return MasterOutcome(spec.entity, row["record_id"], "CREATE", True, row["event_id"],
                                 json.loads(row["values_json"]))
        rows = await self._repository.list_preuat_master_records(spec.entity)
        for column in spec.unique:
            if any((r.get(column) or "").strip().casefold() == values[column].casefold() for r in rows):
                raise api_error("MASTER_RECORD_DUPLICATE", f"Another {spec.label_th or spec.entity} already uses "
                                f"this {column}; nothing was written", status.HTTP_409_CONFLICT, {"field": column})
        if spec.entity == "VEHICLE":
            models = await self._repository.list_preuat_master_records("MODEL")
            if not any(m.get("model_id") == values["model_id"] for m in models):
                raise api_error("MODEL_NOT_FOUND", "The model does not exist", 422, {"field": "model_id"})
        record_id = self._allocate(spec, rows)
        values[spec.id_column] = record_id
        event = self._audit_row(spec, record_id, "CREATE", values, context, request_id, fp)
        # Second independent review (2026-11-18): record + audit as one unit — never a CREATE audit row
        # without its record, never a record without its audit row.
        await self._commit(spec, "CREATE", record_id, {**values, "created_by": getattr(context, "user_id", "") or ""},
                           len(audit), event)
        return MasterOutcome(spec.entity, record_id, "CREATE", False, event["event_id"], values)

    async def edit(self, spec: EntitySpec, record_id: str, body: Mapping[str, object], context, *,
                   request_id: str) -> MasterOutcome:
        self._require_mode()
        if not spec.edit:
            raise api_error("MASTER_RECORD_EDIT_NOT_SUPPORTED", f"{spec.label_th or spec.entity} is edited through its "
                            "existing page", status.HTTP_409_CONFLICT)
        values = _validate(spec.edit, body, partial=True)
        fp = fingerprint("master_edit", f"{spec.entity}:{record_id}", body)
        audit = await self._repository.read_preuat_journal(JOURNAL_MASTER_AUDIT)
        replay = replay_rows(audit, request_id, fp)
        if replay:
            row = replay[0]
            return MasterOutcome(spec.entity, record_id, "UPDATE", True, row["event_id"], json.loads(row["values_json"]))
        rows = await self._repository.list_preuat_master_records(spec.entity)
        matches = [r for r in rows if r.get(spec.id_column) == record_id]
        if not matches:
            raise api_error("MASTER_RECORD_NOT_FOUND", "No record has exactly this id", status.HTTP_404_NOT_FOUND)
        if len(matches) > 1:
            raise api_error("MASTER_RECORD_AMBIGUOUS", "More than one record has this id", status.HTTP_409_CONFLICT)
        current = matches[0]
        if current.get("scope") != "TEST" or (current.get("test_batch_id") or "") != self._batch_id:
            raise api_error("MASTER_RECORD_NOT_TEST_SCOPED", "Only TEST records of this batch can be edited here; "
                            "nothing was written", status.HTTP_409_CONFLICT)
        for column in spec.unique:
            if column in values and any(r.get(spec.id_column) != record_id and
                                        (r.get(column) or "").strip().casefold() == values[column].casefold()
                                        for r in rows):
                raise api_error("MASTER_RECORD_DUPLICATE", f"Another record already uses this {column}",
                                status.HTTP_409_CONFLICT, {"field": column})
        changes = {k: v for k, v in values.items() if (current.get(k) or "") != v}
        if not changes:
            return MasterOutcome(spec.entity, record_id, "NO_CHANGE", False, "", {})
        event = self._audit_row(spec, record_id, "UPDATE", changes, context, request_id, fp,
                                previous={k: current.get(k) or "" for k in changes})
        await self._commit(spec, "UPDATE", record_id, changes, len(audit), event)
        return MasterOutcome(spec.entity, record_id, "UPDATE", False, event["event_id"], changes)

    async def _commit(self, spec: EntitySpec, action: str, record_id: str, values: dict[str, str], audit_count: int,
                      event: dict[str, str]) -> None:
        try:
            await self._repository.commit_preuat_master_change(
                spec.entity, action, record_id, values, test_batch_id=self._batch_id,
                audit_journal=JOURNAL_MASTER_AUDIT, expected_audit_count=audit_count, audit_row=event)
        except RepositoryConcurrentChangeError as exc:
            raise api_error("MASTER_RECORD_CONCURRENT_CHANGE", "Another change was recorded at the same time; "
                            "nothing was written. Reload and try again", status.HTTP_409_CONFLICT) from exc

    async def history(self, spec: EntitySpec, record_id: str) -> list[dict[str, str]]:
        self._require_mode()
        audit = await self._repository.read_preuat_journal(JOURNAL_MASTER_AUDIT)
        return [{k: r[k] for k in ("event_id", "action", "values_json", "previous_json", "actor_user_id",
                                   "recorded_at")}
                for r in audit if r.get("entity") == spec.entity and r.get("record_id") == record_id]

    def _audit_row(self, spec: EntitySpec, record_id: str, action: str, values: Mapping[str, str], context,
                   request_id: str, fp: str, previous: Mapping[str, str] | None = None) -> dict[str, str]:
        return {"event_id": new_event_id("MRA"), "entity": spec.entity, "record_id": record_id, "action": action,
                "values_json": canonical(dict(values)), "previous_json": canonical(dict(previous or {})),
                "actor_user_id": getattr(context, "user_id", "") or "",
                "actor_personnel_id": getattr(context, "personnel_id", "") or "",
                "request_id": request_id, "fingerprint": fp, "recorded_at": now_iso(),
                "data_context": self._data_context or "", "test_batch_id": self._batch_id}


__all__ = ["ENTITY_SPECS", "MasterRecordService", "MasterOutcome", "entity_of", "require_preuat_actor", "forbidden",
           "require_mock_test", "fingerprint", "replay_rows", "guarded_append", "api_error", "now_iso",
           "new_event_id", "canonical", "JOURNAL_MASTER_AUDIT", "PATH_ENTITIES"]
