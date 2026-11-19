"""R8 PRE-UAT — PM Master TEST profile (Owner Consolidated Source Expansion Gate 2026-11-18, SG-PM).

The ONE opt-in, TEST-only composition of the dormant B1 PM Master for local browser UAT. It exists only
when `PM_MASTER_TEST_PROFILE=true`, which the config validator accepts only with the Mock repository,
Access Management mode and a recognized non-production APP_ENV; `app.main` registers its routes only
then. With the profile OFF (the default) nothing here is imported or reachable, so the B1 firewall
(`test_pm_master_b1_mock.test_b1_17`, `test_pm_master_e01_due_bridge.test_23 / 23b`, `test_pm_fleet_due
.test_f25`) keeps proving the default application never loads the Master.

FIREWALL EXCEPTION (Owner-approved paths #94 / #95): this module and `app/api/v1/pm_master_test_routes.py`
are the only modules besides `pm_master_runtime.py` that reach the PM Master, and they do so LAZILY (inside
functions), never at load time. The protected domain (`pm_master.py`, `pm_master_runtime.py`,
`pm_service.py`, `pm_due.py`) is used only through its existing extension points:

- `PmMasterService(store, authorizer=...)` with a TEST-scoped `PmMasterMockStore` — a REAL-scoped Master
  refuses any custom authorizer by itself (`pm_master.py` RT1 / VAL-AM);
- `PmService.with_master_reads(...)` for the per-vehicle / fleet PM Due reads;
- `PmService.open_master_work_order(...)` (which keeps its own `can_manage_pm` check).

AUTHORITY (DEC-R4-TASK010-OPEN005-TEST-AUTH-20261106, now per-employee grants instead of test personas):
preview / review / publish / model-variant decisions need `can_test_pm_master_publish`; plan assignment
needs `can_test_pm_master_assign`. Both are A2 per-employee TEST grants with zero default holders: root,
ADMIN, any role, `can_manage_pm` or a development token never suffice. Anything else gets the
application's own fail-closed refusal (`PM_MASTER_AUTHORITY_UNPROVEN`).

SOURCE: one built-in SYNTHETIC source-shaped workbook (the B1 source shape; invented content, labelled
TEST, never a real PM standard). No upload, no Google Sheets, no workbook file. Meter verification for
completed Sets needs an IoT meter source the application does not have (NO_IOT_METER_SOURCE, R9): after
a completion the Due stays UNKNOWN with its diagnostic — nothing is invented.
"""
from __future__ import annotations

import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import status

from app.domain.authz import CAN_TEST_PM_MASTER_ASSIGN, CAN_TEST_PM_MASTER_PUBLISH, CAN_VIEW
from app.errors import ApiError

PROFILE_NOTE_TH = "โปรไฟล์ทดสอบแผน PM หลัก (TEST เท่านั้น — ข้อมูลสังเคราะห์ ไม่ใช่มาตรฐาน PM จริง)"
SOURCE_FILE = "UAT8_PM_SOURCE_SYNTHETIC.xlsx"
PLAN_CODE = "UAT8 PM Plan"
DOC_CARRIER, DOC_CRANE, DOC_B = "UAT8-DOC ล่าง", "UAT8-DOC บน", "UAT8-DOC B"
VARIANT_A, VARIANT_B = "UAT8-V-A", "UAT8-V-B"


def _cycle(variant: str, section: str, group: str, value: str, unit: str, rule: str = "") -> dict[str, object]:
    return {"source_sheet": PLAN_CODE, "model_label_corrected": variant, "component_section": section,
            "task_group": group, "interval_value": value, "interval_unit": unit, "group_rule": rule,
            "next_due_rule": ""}


def _item(doc: str, row: int, group: str, section: str, seq: int, text: str) -> dict[str, object]:
    return {"source_sheet": doc, "source_row": row, "task_group": group, "component_section": section,
            "sequence_raw": seq, "description_raw": text, "method_raw": "ตรวจสอบด้วยสายตา (ทดสอบ)",
            "standard_raw": "ตามคู่มือ (ทดสอบ)", "frequency_approved": "ตามรอบ", "interval_value": "",
            "interval_unit": "", "check_cell_raw": "", "clean_cell_raw": "", "change_fill_cell_raw": ""}


def synthetic_workbook() -> dict[str, list[dict[str, object]]]:
    """The built-in SYNTHETIC source-shaped workbook (B1 shape). Variant A (dual engine, UAT8-MDL-A) has
    distinct CARRIER 600 h, CRANE 600 h and an independent 10,000 km ODOMETER Set; variant B (UAT8-MDL-B)
    has one 250 h Set whose configuration is UNKNOWN, so the preview raises ONE REVIEW entry (meter
    decision) that must be resolved — or excluded — before the Plan can be published."""
    return {
        "source_pm_standard": [{"source_sheet": d, "source_status": "SOURCE_STANDARD", "source_google_sheet_url": ""}
                               for d in (DOC_CARRIER, DOC_CRANE, DOC_B)],
        "vehicle_pm_mapping": [
            {"vehicle_id": "UAT8-VEH-01", "source_plan": PLAN_CODE, "plan_model": VARIANT_A,
             "component_configuration": "CARRIER_AND_CRANE", "carrier_or_main_source_sheet": DOC_CARRIER,
             "crane_source_sheet": DOC_CRANE, "mapping_status": "MATCHED_PENDING_IMPLEMENTATION",
             "mapping_basis": "SYNTHETIC TEST"},
            {"vehicle_id": "UAT8-VEH-03", "source_plan": PLAN_CODE, "plan_model": VARIANT_B,
             "component_configuration": "UNKNOWN", "carrier_or_main_source_sheet": DOC_B, "crane_source_sheet": "",
             "mapping_status": "MATCHED_PENDING_IMPLEMENTATION", "mapping_basis": "SYNTHETIC TEST"},
        ],
        "source_pm_cycles": [
            _cycle(VARIANT_A, "CARRIER", "A", "600", "HOUR"),
            _cycle(VARIANT_A, "CRANE", "A", "600", "HOUR"),
            _cycle(VARIANT_A, "CARRIER", "KM1", "10,000", "KM", "INDEPENDENT_GROUP"),
            _cycle(VARIANT_B, "NOT_SEPARATED_IN_PLAN", "A", "250", "HOUR"),
        ],
        "source_pm_items": [
            _item(DOC_CARRIER, 5, "A", "CARRIER", 1, "ตรวจระดับน้ำมันเครื่อง (ทดสอบ)"),
            _item(DOC_CARRIER, 6, "A", "CARRIER", 2, "ทำความสะอาดไส้กรองอากาศ (ทดสอบ)"),
            _item(DOC_CRANE, 5, "A", "CRANE", 1, "ตรวจน้ำมันไฮดรอลิก (ทดสอบ)"),
            _item(DOC_CARRIER, 9, "KM1", "CARRIER", 1, "ตรวจลมยาง (ทดสอบ)"),
            _item(DOC_B, 5, "A", "NOT_SEPARATED_IN_FORM", 1, "ตรวจเครื่องยนต์รุ่น B (ทดสอบ)"),
        ],
    }


def _forbidden(code: str, message: str) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


def test_profile_authorizer(context: object, action: str) -> None:
    """Master write authority from per-employee TEST grants only. A verified Access Management employee
    holding `can_view` and the grant for this action passes; everyone else gets the application's own
    fail-closed refusal (never a role, root or `can_manage_pm`)."""
    from app.domain import pm_master as master

    grant = {master.KIND_PREVIEW: CAN_TEST_PM_MASTER_PUBLISH, master.KIND_REVIEW: CAN_TEST_PM_MASTER_PUBLISH,
             master.KIND_PUBLISH: CAN_TEST_PM_MASTER_PUBLISH, master.KIND_VARIANT_APPROVE: CAN_TEST_PM_MASTER_PUBLISH,
             master.KIND_ASSIGN: CAN_TEST_PM_MASTER_ASSIGN}.get(action)
    capabilities = getattr(context, "capabilities", frozenset())
    verified = (getattr(context, "access", None) is not None and bool(getattr(context, "personnel_id", None))
                and bool((getattr(context, "user_id", None) or "").strip()))
    if grant is None or not verified or CAN_VIEW not in capabilities or grant not in capabilities:
        master.deny_unproven_master_authority(context, action)


def require_profile_enabled(settings: Any) -> None:
    """Defence in depth (the routes are only registered with the profile ON): Mock, Access Management,
    the TEST context and the flag itself, or 404 — the profile does not exist otherwise."""
    from app.config import DataRepositoryMode

    if not (getattr(settings, "pm_master_test_profile", False) and settings.access_management_mode
            and settings.data_repository == DataRepositoryMode.MOCK
            and settings.registry_context_effective == "TEST"):
        raise ApiError(code="PM_MASTER_TEST_PROFILE_DISABLED", status_code=status.HTTP_404_NOT_FOUND,
                       message="The PM Master TEST profile is not enabled")


def require_trusted_viewer(context: object) -> None:
    if not (getattr(context, "user_id", None) or "").strip() or CAN_VIEW not in getattr(context, "capabilities", ()):
        raise _forbidden("PREUAT_ACTION_NOT_AUTHORIZED", "Reading the PM Master TEST profile requires 'can_view'")


@dataclass
class _ProfileState:
    master: Any  # PmMasterService
    store: Any  # PmMasterMockStore


# One TEST Master per repository object (the Mock repository is one per process); it disappears with it.
_STATES: weakref.WeakKeyDictionary[object, _ProfileState] = weakref.WeakKeyDictionary()


def master_for(repository: object, test_batch_id: str) -> Any:
    """The profile's TEST-scoped `PmMasterService`, bound to THIS repository (RT1 G2) and batch (G1)."""
    from app.domain.pm_master import MasterDataScope, MockVehicleResolver, PmMasterMockStore, PmMasterService

    state = _STATES.get(repository)
    if state is None:
        store = PmMasterMockStore(data_scope=MasterDataScope.test(test_batch_id))
        master = PmMasterService(store, authorizer=test_profile_authorizer,
                                 vehicle_resolver=MockVehicleResolver(repository))
        state = _STATES[repository] = _ProfileState(master, store)
    return state.master


def pm_with_master(pm_service: Any, master: Any, context: object) -> Any:
    """A PM service that reads THIS TEST Master and its own approved model variants (OPEN-016)."""
    return pm_service.with_master_reads(master, master.model_variant_source(context))


def preview_view(registration: Any, resolutions: tuple[Any, ...]) -> dict[str, object]:
    preview = registration.preview
    resolved = {r.entry_id for r in resolutions if r.preview_id == registration.preview_id}
    return {
        "preview_id": registration.preview_id, "source_file": registration.source_file,
        "source_digest": registration.source_digest, "registered_by": registration.registered_by,
        "ledger": [{"entry_id": e.entry_id, "action": e.action, "issue": e.issue, "row_or_key": e.row_or_key,
                    "plan_scope": list(e.plan_scope), "resolved": e.entry_id in resolved} for e in preview.ledger],
        "mapping_candidates": [{"source_row": m.source_row, "vehicle_ref": m.vehicle_ref, "plan_code": m.plan_code,
                                "plan_model": m.plan_model, "status": m.status} for m in preview.mapping_candidates],
    }


def revision_view(revision: Any) -> dict[str, object] | None:
    if revision is None:
        return None
    return {"revision_id": revision.revision_id, "plan_code": revision.plan_code,
            "revision_number": revision.revision_number, "source_digest": getattr(revision, "source_digest", ""),
            "sets": [{"set_key": s.set_key, "model_variant": s.model_variant, "section": s.section,
                      "meter_type": getattr(s.meter_type, "value", s.meter_type),
                      "interval_value": s.interval_value, "interval_unit": s.interval_unit,
                      "independent_group": s.independent_group or "",
                      "items": [{"item_key": i.item_key, "task_text": i.task_text} for i in s.items]}
                     for s in revision.sets]}


def profile_status(master: Any, store: Any) -> dict[str, object]:
    head = store.head(PLAN_CODE)
    previews = [p for p in store.previews if p.source_file == SOURCE_FILE]
    return {
        "note_th": PROFILE_NOTE_TH, "plan_code": PLAN_CODE, "source_file": SOURCE_FILE,
        "latest_preview_id": previews[-1].preview_id if previews else None,
        "head_revision": revision_view(head),
        "assignments": [{"vehicle_id": a.vehicle_id, "assembly": a.assembly, "state": a.state,
                         "plan_code": a.plan_code, "version": a.version} for a in store.assignments],
        "variant_approvals": [{"model_id": a.model_id, "plan_code": a.plan_code, "model_variant": a.model_variant,
                               "state": a.state, "version": a.version} for a in store.variant_approvals],
    }


def as_mapping(value: Mapping[str, object] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (value or {}).items()}


__all__ = ["synthetic_workbook", "test_profile_authorizer", "require_profile_enabled", "require_trusted_viewer",
           "master_for", "pm_with_master", "preview_view", "revision_view", "profile_status", "PLAN_CODE",
           "SOURCE_FILE", "VARIANT_A", "VARIANT_B", "PROFILE_NOTE_TH", "as_mapping"]
