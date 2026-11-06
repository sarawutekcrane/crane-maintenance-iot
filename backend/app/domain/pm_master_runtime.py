"""R4 / TASK-010 (DEC-R4-TASK010-B1-E01-BRIDGE-D1-20261106): the DORMANT B1 PM
Master -> E01 runtime -> per-Set Due bridge. Pure functions and immutable records
only: no I/O, clock, route or authority here.

B1 FIREWALL EXCEPTION: this is the ONLY application module allowed to import
`app.domain.pm_master`. It is itself imported only lazily (inside the dormant
`PmService` bridge methods) or for type checking, so the running application never
loads the PM Master. OPEN-005 is untouched: a Master revision exists only once the
fail-closed Master authorizer let it be published, and a vehicle reaches a Plan only
through an explicit (equally fail-closed) assignment.

1. Runtime catalogue: ONE E01 `PmTaskRevision` per immutable Master revision (its id
   IS the Master `revision_id`) with ONE `PmTask` per (revision, Set, Item). The task
   id is derived from exactly that triple, so an Item shared by two Sets gets two
   tasks (no shared credit) and an Item is never matched by its text. The Set-level
   meter, interval and unit ride in the existing `PmTask` fields; `group` is the
   Set key.
2. Membership: the write-once record of which Master Sets (each with its COMPLETE
   Item list and frozen Set facts) one Work Order was opened for. It is stored in
   the same repository write as the Work Order.
3. Due: a `FrozenSet` is built only from stored membership checked against the
   stored catalogue and the deterministic ids; the physical engine is resolved from
   the vehicle's own component records (exactly one with the role, else UNKNOWN).
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from app.domain.asset import AssetType
from app.domain.pm import PmPlan, PmTask, PmTaskRevision, PmTaskRevisionDetail
from app.domain.pm_due_evidence import FrozenSet, MappedItem
from app.domain.pm_master import (
    ASSEMBLY_ROLE,
    MasterRevision,
    MasterSet,
    MasterWorkOrderSnapshot,
)
from app.domain.request_replay import canonical_json

OP_PM_MASTER_WORK_ORDER_OPEN = "pm_master_work_order_open"
_ENGINE_ROLES = ("CARRIER_ENGINE", "CRANE_ENGINE")

# OPEN-016 (DEC-R4-TASK010-MODEL-VARIANT-MAPPING-OPEN016-20261106): the Master
# `model_variant`(s) an evidence-backed, APPROVED association gives for
# (VehicleModel.model_id, exact Master plan_code). The vehicle only resolves its
# registered model; there are no per-vehicle exceptions. A source returns nothing for
# a pending, unapproved or provenance-less record. None is wired into the application:
# the MAINTENANCE `vehicle_pm_mapping` rows are reference candidates whose cycles are
# still PENDING_IMPLEMENTATION, never an active runtime mapping. A shared Plan,
# matching component roles, model names or similar text never prove it.
ModelVariantSource = Callable[[str, str], Collection[str]]


def no_proven_model_variant(model_id: str, plan_code: str) -> frozenset[str]:
    """The runtime default: nothing is proven, so no Master Set can be opened on any
    vehicle (fail closed) until an approved association is published."""
    return frozenset()


def model_variant_proven(source: ModelVariantSource, *, model_id: str, plan_code: str, model_variant: str) -> bool:
    """True only when the source gives EXACTLY this one variant for this model in this
    exact Master Plan: none (missing) or several (ambiguous, conflicting) never prove it."""
    if not (model_id.strip() and plan_code.strip() and model_variant.strip()):
        return False
    return frozenset(source(model_id, plan_code)) == {model_variant}


@dataclass(frozen=True)
class MasterSetMembership:
    """One selected Master Set as frozen into one Work Order: its source facts and
    its COMPLETE Item list as (Master item_key, E01 pm_task_id), in Master order."""

    set_key: str
    model_variant: str
    section: str
    meter_type: str
    interval_value: float
    interval_unit: str
    driving_component_role: str | None
    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PmMasterWorkOrderMembership:
    """Write-once: the Master revision and Sets one Work Order was opened for, with
    the creation request it answers. `pm_work_order_id` is "" until the repository
    allocates the Work Order in the same write."""

    pm_work_order_id: str
    request_id: str
    request_fingerprint: str
    asset_id: str
    vehicle_model_id: str  # the runtime model whose Master variant was proven at opening
    plan_code: str
    master_revision_id: str
    master_revision_number: int
    pm_plan_id: str
    sets: tuple[MasterSetMembership, ...]
    is_test_data: str = ""
    test_batch_id: str = ""

    @property
    def task_ids(self) -> list[str]:
        return [task_id for s in self.sets for _, task_id in s.items]


def _digest(*parts: object) -> str:
    return hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()


def runtime_plan_id(plan_code: str) -> str:
    return f"PMMP-{_digest('plan', plan_code)[:20]}"


def runtime_task_id(revision_id: str, set_key: str, item_key: str) -> str:
    return f"PMMT-{_digest('task', revision_id, set_key, item_key)[:24]}"


def assembly_of(master_set: MasterSet) -> str:
    """The B1 assignment level a Set is resolved at (`resolve_plan` falls back to
    the whole-vehicle record)."""
    return master_set.section if master_set.section in ASSEMBLY_ROLE else ""


def _checked_items(master_set: MasterSet) -> None:
    keys = [i.item_key for i in master_set.items]
    if not keys or any(not k.strip() for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("PM_MASTER_MAPPING_INVALID")


def build_catalogue(revision: MasterRevision) -> PmTaskRevisionDetail:
    """The E01 runtime catalogue of one immutable Master revision (every Set).
    Deterministic: the same revision always yields an equal catalogue."""
    set_keys = [s.set_key for s in revision.sets]
    if not set_keys or len(set(set_keys)) != len(set_keys):
        raise ValueError("PM_MASTER_MAPPING_INVALID")
    plan_id = runtime_plan_id(revision.plan_code)
    tasks: list[PmTask] = []
    for master_set in sorted(revision.sets, key=lambda s: s.set_key):
        _checked_items(master_set)
        for item in master_set.items:
            tasks.append(PmTask(
                pm_task_id=runtime_task_id(revision.revision_id, master_set.set_key, item.item_key),
                revision_id=revision.revision_id, sequence=len(tasks) + 1, group=master_set.set_key,
                description=item.task_text, trigger_type=master_set.meter_type,
                interval_value=master_set.interval_value, interval_unit=master_set.interval_unit))
    if len({t.pm_task_id for t in tasks}) != len(tasks):
        raise ValueError("PM_MASTER_MAPPING_INVALID")
    at = revision.published_at
    return PmTaskRevisionDetail(
        plan=PmPlan(pm_plan_id=plan_id, plan_code=revision.plan_code, asset_type=AssetType.VEHICLE,
                    name=revision.plan_code, model_ids=[], created_at=at, updated_at=at),
        revision=PmTaskRevision(revision_id=revision.revision_id, pm_plan_id=plan_id,
                                revision_number=revision.revision_number, effective_date=at.date(),
                                source_revision_note=f"PM Master {revision.plan_code} rev {revision.revision_number}",
                                created_at=at),
        tasks=tasks)


def build_membership(snapshot: MasterWorkOrderSnapshot, *, asset_id: str, vehicle_model_id: str, request_id: str,
                     fingerprint: str, scope: Mapping[str, str]) -> PmMasterWorkOrderMembership:
    """The membership of one new Work Order from the authoritative B1 snapshot:
    every Item of every selected Set, one model variant per Work Order."""
    keys = [s.set_key for s in snapshot.sets]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("PM_MASTER_MAPPING_INVALID")
    if len({s.model_variant for s in snapshot.sets}) != 1:
        raise ValueError("PM_MASTER_MIXED_MODEL_VARIANT")
    sets = []
    for s in snapshot.sets:
        _checked_items(s)
        sets.append(MasterSetMembership(
            set_key=s.set_key, model_variant=s.model_variant, section=s.section, meter_type=s.meter_type.value,
            interval_value=float(s.interval_value), interval_unit=s.interval_unit,
            driving_component_role=s.driving_component.value if s.driving_component is not None else None,
            items=tuple((i.item_key, runtime_task_id(snapshot.revision_id, s.set_key, i.item_key)) for i in s.items)))
    return PmMasterWorkOrderMembership(
        pm_work_order_id="", request_id=request_id, request_fingerprint=fingerprint, asset_id=asset_id,
        vehicle_model_id=vehicle_model_id, plan_code=snapshot.plan_code, master_revision_id=snapshot.revision_id,
        master_revision_number=snapshot.revision_number, pm_plan_id=runtime_plan_id(snapshot.plan_code),
        sets=tuple(sets), is_test_data=scope["is_test_data"], test_batch_id=scope["test_batch_id"])


def frozen_set(memberships: Sequence[PmMasterWorkOrderMembership], set_key: str,
               catalogue: PmTaskRevisionDetail | None, components: Sequence[tuple[str, str]],
               vehicle_model_id: str | None) -> FrozenSet | None:
    """The DUE-02A `FrozenSet` of one Master Set on one vehicle, or None when no
    Work Order was opened for it. Every membership must carry the identical frozen
    Set, which must equal the stored catalogue task for task (ids re-derived), and
    the vehicle must still be the model whose variant was proven at opening, or the
    mapping stays unverified. Nothing here is taken from a caller's flag."""
    headers = {(m.asset_id, m.vehicle_model_id, m.plan_code, m.pm_plan_id, m.master_revision_id)
               for m in memberships}
    definitions = {s for m in memberships for s in m.sets if s.set_key == set_key}
    if not definitions:
        return None
    (asset_id, model_id, plan_code, pm_plan_id, revision_id), *rest = sorted(headers)
    definition, *others = sorted(definitions, key=repr)
    group = [t for t in catalogue.tasks if t.group == set_key] if catalogue is not None else []
    verified = (not rest and not others and catalogue is not None and bool(model_id) and model_id == vehicle_model_id
                and len({s.model_variant for m in memberships for s in m.sets}) == 1
                and (catalogue.plan.pm_plan_id, catalogue.revision.revision_id) == (pm_plan_id, revision_id)
                and pm_plan_id == runtime_plan_id(plan_code)
                and [t.pm_task_id for t in group] == [task_id for _, task_id in definition.items]
                and all(task_id == runtime_task_id(revision_id, set_key, item_key)
                        for item_key, task_id in definition.items)
                and all((t.trigger_type.value if t.trigger_type else None, t.interval_value, t.interval_unit)
                        == (definition.meter_type, definition.interval_value, definition.interval_unit)
                        for t in group))
    role, component_id = definition.driving_component_role, None
    if definition.meter_type == "ENGINE_HOUR" and role in _ENGINE_ROLES:
        matches = [cid for cid, component_role in components if component_role == role]
        component_id = matches[0] if len(matches) == 1 else None
    return FrozenSet(
        set_ref=f"{plan_code}|{revision_id}|{set_key}", asset_type=AssetType.VEHICLE.value, asset_id=asset_id,
        pm_plan_id=pm_plan_id, revision_id=revision_id,
        items=tuple(MappedItem(item_key, task_id, verified) for item_key, task_id in definition.items),
        meter_type=definition.meter_type, interval=definition.interval_value, interval_unit=definition.interval_unit,
        driving_component_role=role, component_id=component_id, source_verified=verified,
        lineage_verified=verified, component_verified=component_id is not None)


__all__ = ["OP_PM_MASTER_WORK_ORDER_OPEN", "MasterSetMembership", "ModelVariantSource", "PmMasterWorkOrderMembership",
           "assembly_of", "build_catalogue", "build_membership", "frozen_set", "model_variant_proven",
           "no_proven_model_variant", "runtime_plan_id", "runtime_task_id"]
