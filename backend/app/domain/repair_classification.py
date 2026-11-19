"""R8 PRE-UAT (Owner source approval Rev 1, Decision 2) — TEST repair classification.

Flow: technical repair closure -> Store reconciliation -> WAITING_FOR_CLASSIFICATION ->
TEST classification (staged draft revisions, then one finalization) -> CLASSIFIED.

The state is DERIVED; RepairStatus stays OPEN / CLOSED / CANCELLED and the repair, its
technician time, parts and store history are never modified here.
  NOT_ELIGIBLE                 repair OPEN or CANCELLED
  BLOCKED_STORE_UNRECONCILED   CLOSED, store journal not reconciled
  WAITING_FOR_CLASSIFICATION   CLOSED and reconciled, no final classification
  CLASSIFIED                   one FINAL record exists

A draft holds 1..n failure-point rows. Each row has:
- SYSTEM -> ASSEMBLY -> POINT, from the TEST candidate subset only;
- symptom(s), from that relationship's allowed list;
- action(s), from the global A01–A15 registry;
- position as separate fields (side / end / axle / level / hoist), never a 4th code segment.

Fail-closed codes: REPAIR_CODE_UNKNOWN, REPAIR_CODE_HIERARCHY_INVALID,
REPAIR_CODE_ENTRY_NOT_IN_TEST_SUBSET (with the source reasons), REPAIR_SYMPTOM_NOT_ALLOWED,
REPAIR_ACTION_UNKNOWN, CLASSIFICATION_BLOCKED_STORE_UNRECONCILED,
CLASSIFICATION_NOT_ELIGIBLE, REPAIR_ALREADY_CLASSIFIED, CLASSIFICATION_DRAFT_STALE,
CLASSIFICATION_REAL_NOT_ENABLED (409). Google Sheets answers 501.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fastapi import status

from app.domain.master_records import (
    api_error,
    canonical,
    fingerprint,
    guarded_append,
    new_event_id,
    now_iso,
    replay_rows,
    require_mock_test,
)
from app.domain.repair import RepairStatus
from app.domain.repair_catalogue import (
    NOT_FOR_REAL_NOTE_TH,
    Catalogue,
    CatalogueIntegrityError,
    load_catalogue,
)
from app.domain.store_workflow import RECONCILED, StoreWorkflowService
from app.repositories.base import Repository

JOURNAL_CLASSIFICATION = "CLASSIFICATION"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
BLOCKED_STORE_UNRECONCILED = "BLOCKED_STORE_UNRECONCILED"
WAITING_FOR_CLASSIFICATION = "WAITING_FOR_CLASSIFICATION"
CLASSIFIED = "CLASSIFIED"
KIND_DRAFT, KIND_FINAL = "DRAFT", "FINAL"
MAX_ROWS = 20

POSITION_CHOICES: dict[str, tuple[str, ...] | None] = {
    "side": ("LEFT", "RIGHT"), "end": ("FRONT", "REAR"), "axle": None, "level": ("UPPER", "LOWER"),
    "hoist": ("MAIN", "AUXILIARY"),
}


def catalogue_or_error() -> Catalogue:
    try:
        return load_catalogue()
    except CatalogueIntegrityError as exc:
        raise api_error("REPAIR_CATALOGUE_INTEGRITY_FAILED", "The TEST repair code catalogue failed its integrity "
                        "check; nothing can be classified", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


def validate_rows(catalogue: Catalogue, raw_rows: object) -> list[dict[str, object]]:
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= MAX_ROWS:
        raise api_error("VALIDATION_ERROR", f"1–{MAX_ROWS} failure-point rows are required", 422, {"field": "rows"})
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict) or set(raw) - {"system", "assembly", "point", "symptoms", "actions",
                                                     "position", "note"}:
            raise api_error("VALIDATION_ERROR", "Unknown failure-point field", 422, {"row": index})
        s, a, p = (raw.get(k) for k in ("system", "assembly", "point"))
        if not all(isinstance(x, str) and x.strip() for x in (s, a, p)):
            raise api_error("VALIDATION_ERROR", "system, assembly and point are required", 422, {"row": index})
        s, a, p = s.strip(), a.strip(), p.strip()  # type: ignore[union-attr]
        if s not in catalogue.systems or a not in catalogue.assemblies or p not in catalogue.points:
            raise api_error("REPAIR_CODE_UNKNOWN", "A system, assembly or point code is not in the source catalogue",
                            422, {"row": index})
        code = f"{s}-{a}-{p}"
        rel = catalogue.relationships.get(code)
        if rel is None:
            raise api_error("REPAIR_CODE_HIERARCHY_INVALID", "This system / assembly / point combination is not a "
                            "relationship in the source", 422, {"row": index, "code": code})
        if not rel.candidate:
            raise api_error("REPAIR_CODE_ENTRY_NOT_IN_TEST_SUBSET", "This relationship is excluded from the TEST "
                            "candidate subset", 422, {"row": index, "code": code,
                                                      "reasons": list(rel.exclusion_reasons)})
        symptoms, actions = raw.get("symptoms"), raw.get("actions")
        if not isinstance(symptoms, list) or not symptoms or not all(isinstance(x, str) for x in symptoms) \
                or len(set(symptoms)) != len(symptoms):
            raise api_error("VALIDATION_ERROR", "At least one symptom is required", 422, {"row": index})
        bad = [x for x in symptoms if x not in rel.allowed_symptoms]
        if bad:
            raise api_error("REPAIR_SYMPTOM_NOT_ALLOWED", "A symptom is not allowed for this relationship (only "
                            "registered S01–S05 codes with an identical source label)", 422,
                            {"row": index, "symptoms": bad[:5], "allowed": list(rel.allowed_symptoms)})
        if not isinstance(actions, list) or not actions or not all(isinstance(x, str) for x in actions) \
                or len(set(actions)) != len(actions):
            raise api_error("VALIDATION_ERROR", "At least one repair action is required", 422, {"row": index})
        unknown_actions = [x for x in actions if x not in catalogue.actions]
        if unknown_actions:
            raise api_error("REPAIR_ACTION_UNKNOWN", "A repair action is not in the A01–A15 registry", 422,
                            {"row": index, "actions": unknown_actions[:5]})
        position = raw.get("position") or {}
        if not isinstance(position, dict) or set(position) - set(POSITION_CHOICES):
            raise api_error("VALIDATION_ERROR", "Unknown position field", 422, {"row": index})
        clean_position: dict[str, str] = {}
        for key, value in position.items():
            if value in (None, ""):
                continue
            choices = POSITION_CHOICES[key]
            if not isinstance(value, str) or len(value) > 20 or (choices is not None and value not in choices):
                raise api_error("VALIDATION_ERROR", f"position.{key} is not an allowed value", 422, {"row": index})
            clean_position[key] = value.strip()
        note = raw.get("note") or ""
        if not isinstance(note, str) or len(note) > 300:
            raise api_error("VALIDATION_ERROR", "note must be text (max 300)", 422, {"row": index})
        key = canonical({"code": code, "position": clean_position})
        if key in seen:
            raise api_error("VALIDATION_ERROR", "The same failure point and position appear twice", 422,
                            {"row": index})
        seen.add(key)
        rows.append({"code": code, "system": s, "assembly": a, "point": p, "symptoms": list(symptoms),
                     "actions": list(actions), "position": clean_position, "note": note.strip()})
    return rows


@dataclass
class ClassificationView:
    repair_id: str
    state: str
    blockers: list[str]
    draft_revision: int
    draft_rows: list[dict[str, object]]
    final: dict[str, object] | None


class RepairClassificationService:
    def __init__(self, repository: Repository, store: StoreWorkflowService, data_context: str | None,
                 batch_id: str, *, mock_repository: bool) -> None:
        self._repository = repository
        self._store = store
        self._context = data_context
        self._batch = batch_id
        self._mock = mock_repository

    def _require_mode(self) -> None:
        require_mock_test(self._mock, self._context, "repair_classification", "CLASSIFICATION_REAL_NOT_ENABLED")

    async def view(self, repair_id: str) -> ClassificationView:
        self._require_mode()
        detail = await self._repository.get_repair(repair_id)
        if detail is None:
            raise api_error("REPAIR_NOT_FOUND", "No repair has exactly this id", status.HTTP_404_NOT_FOUND)
        journal = [r for r in await self._repository.read_preuat_journal(JOURNAL_CLASSIFICATION)
                   if r.get("repair_id") == repair_id]
        return await self._view(detail.repair, journal)

    async def _view(self, repair, journal: Sequence[Mapping[str, str]]) -> ClassificationView:
        drafts = [r for r in journal if r.get("kind") == KIND_DRAFT]
        finals = [r for r in journal if r.get("kind") == KIND_FINAL]
        draft = drafts[-1] if drafts else None
        draft_rows = json.loads(draft["rows_json"]) if draft else []
        revision = int(draft["revision"]) if draft else 0
        status_value = getattr(repair.status, "value", repair.status)
        blockers: list[str] = []
        if finals:
            final = dict(finals[-1])
            final.pop("fingerprint", None)  # the replay fingerprint is stored, never exposed
            final["rows"] = json.loads(final.pop("rows_json"))
            return ClassificationView(repair.repair_id, CLASSIFIED, [], revision, draft_rows, final)
        if status_value != RepairStatus.CLOSED.value:
            return ClassificationView(repair.repair_id, NOT_ELIGIBLE, [f"REPAIR_{status_value}"], revision,
                                      draft_rows, None)
        rec = await self._store.reconciliation(repair.repair_id)
        if rec.state != RECONCILED:
            blockers = rec.blockers()
            return ClassificationView(repair.repair_id, BLOCKED_STORE_UNRECONCILED, blockers, revision, draft_rows,
                                      None)
        return ClassificationView(repair.repair_id, WAITING_FOR_CLASSIFICATION, [], revision, draft_rows, None)

    def _require_waiting(self, view: ClassificationView) -> None:
        if view.state == CLASSIFIED:
            raise api_error("REPAIR_ALREADY_CLASSIFIED", "This repair is already classified; nothing was written",
                            status.HTTP_409_CONFLICT)
        if view.state == NOT_ELIGIBLE:
            raise api_error("CLASSIFICATION_NOT_ELIGIBLE", "Only a technically closed repair can be classified",
                            status.HTTP_409_CONFLICT, {"blockers": view.blockers})
        if view.state == BLOCKED_STORE_UNRECONCILED:
            raise api_error("CLASSIFICATION_BLOCKED_STORE_UNRECONCILED", "Material quantities are not reconciled "
                            "(DEC-STORE-005); nothing was written", status.HTTP_409_CONFLICT,
                            {"blockers": view.blockers})

    def _row(self, kind: str, repair_id: str, revision: int, rows: list[dict[str, object]], catalogue: Catalogue,
             context, request_id: str, fp: str) -> dict[str, str]:
        return {"event_id": new_event_id("RCL"), "kind": kind, "repair_id": repair_id, "revision": str(revision),
                "rows_json": canonical(rows), "catalogue_rule": catalogue.rule_version,
                "catalogue_release_status": catalogue.release_status,
                "catalogue_source_sha256": catalogue.source_sha256,
                "catalogue_extract_sha256": catalogue.extract_sha256, "not_for_real_note": NOT_FOR_REAL_NOTE_TH,
                "actor_user_id": getattr(context, "user_id", "") or "",
                "actor_personnel_id": getattr(context, "personnel_id", "") or "", "request_id": request_id,
                "fingerprint": fp, "recorded_at": now_iso(), "data_context": self._context or "",
                "test_batch_id": self._batch}

    async def stage(self, repair_id: str, body: Mapping[str, object], context, *, request_id: str
                    ) -> tuple[ClassificationView, bool]:
        self._require_mode()
        catalogue = catalogue_or_error()
        fp = fingerprint("classification_draft", repair_id, body)
        journal = await self._repository.read_preuat_journal(JOURNAL_CLASSIFICATION)
        if replay_rows(journal, request_id, fp):
            return await self.view(repair_id), True
        if set(body) - {"expected_revision", "rows"}:
            raise api_error("VALIDATION_ERROR", "Unknown field(s)", 422)
        expected = body.get("expected_revision")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise api_error("VALIDATION_ERROR", "expected_revision (integer) is required", 422)
        detail = await self._repository.get_repair(repair_id)
        if detail is None:
            raise api_error("REPAIR_NOT_FOUND", "No repair has exactly this id", status.HTTP_404_NOT_FOUND)
        mine = [r for r in journal if r.get("repair_id") == repair_id]
        view = await self._view(detail.repair, mine)
        self._require_waiting(view)
        if expected != view.draft_revision:
            raise api_error("CLASSIFICATION_DRAFT_STALE", "The draft changed since it was read; reload",
                            status.HTTP_409_CONFLICT, {"current_revision": view.draft_revision})
        rows = validate_rows(catalogue, body.get("rows"))
        event = self._row(KIND_DRAFT, repair_id, view.draft_revision + 1, rows, catalogue, context, request_id, fp)
        # Re-check the store reconciliation right before the append (independent review): a store event
        # recorded meanwhile can no longer slip past the gate (residual one-process window: R11).
        self._require_waiting(await self._view(detail.repair, mine))
        await guarded_append(self._repository, JOURNAL_CLASSIFICATION, len(journal), [event],
                             "CLASSIFICATION_CONCURRENT_CHANGE")
        return await self.view(repair_id), False

    async def finalize(self, repair_id: str, body: Mapping[str, object], context, *, request_id: str
                       ) -> tuple[ClassificationView, bool]:
        self._require_mode()
        catalogue = catalogue_or_error()
        fp = fingerprint("classification_final", repair_id, body)
        journal = await self._repository.read_preuat_journal(JOURNAL_CLASSIFICATION)
        if replay_rows(journal, request_id, fp):
            return await self.view(repair_id), True
        if set(body) - {"expected_revision"}:
            raise api_error("VALIDATION_ERROR", "Unknown field(s)", 422)
        expected = body.get("expected_revision")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            raise api_error("VALIDATION_ERROR", "expected_revision of a staged draft is required", 422)
        detail = await self._repository.get_repair(repair_id)
        if detail is None:
            raise api_error("REPAIR_NOT_FOUND", "No repair has exactly this id", status.HTTP_404_NOT_FOUND)
        mine = [r for r in journal if r.get("repair_id") == repair_id]
        view = await self._view(detail.repair, mine)
        self._require_waiting(view)
        if expected != view.draft_revision or not view.draft_rows:
            raise api_error("CLASSIFICATION_DRAFT_STALE", "Finalize the latest staged draft", status.HTTP_409_CONFLICT,
                            {"current_revision": view.draft_revision})
        rows = validate_rows(catalogue, [{k: r[k] for k in ("system", "assembly", "point", "symptoms", "actions",
                                                            "position", "note")} for r in view.draft_rows])
        event = self._row(KIND_FINAL, repair_id, view.draft_revision, rows, catalogue, context, request_id, fp)
        # Re-check the store reconciliation right before the append (independent review): a store event
        # recorded meanwhile can no longer slip past the gate (residual one-process window: R11).
        self._require_waiting(await self._view(detail.repair, mine))
        await guarded_append(self._repository, JOURNAL_CLASSIFICATION, len(journal), [event],
                             "CLASSIFICATION_CONCURRENT_CHANGE")
        return await self.view(repair_id), False


def catalogue_tree(catalogue: Catalogue) -> list[dict[str, object]]:
    """The TEST candidate subset as SYSTEM -> ASSEMBLY -> POINT for dependent dropdowns."""
    tree: dict[str, dict[str, object]] = {}
    for rel in sorted(catalogue.candidates.values(), key=lambda r: (r.system, r.assembly, r.point)):
        system = tree.setdefault(rel.system, {"code": rel.system, "name": catalogue.systems[rel.system],
                                              "assemblies": {}})
        assemblies = system["assemblies"]  # type: ignore[assignment]
        assembly = assemblies.setdefault(rel.assembly, {"code": rel.assembly,  # type: ignore[union-attr]
                                                        "name": catalogue.assemblies[rel.assembly]["name"],
                                                        "points": []})
        assembly["points"].append({"code": rel.point, "name": catalogue.points[rel.point]["name"],
                                   "relationship": rel.code, "allowed_symptoms": list(rel.allowed_symptoms)})
    return [{**s, "assemblies": list(s["assemblies"].values())} for s in tree.values()]  # type: ignore[union-attr]


__all__ = ["RepairClassificationService", "ClassificationView", "validate_rows", "catalogue_tree",
           "catalogue_or_error", "NOT_ELIGIBLE", "BLOCKED_STORE_UNRECONCILED", "WAITING_FOR_CLASSIFICATION",
           "CLASSIFIED", "JOURNAL_CLASSIFICATION"]
