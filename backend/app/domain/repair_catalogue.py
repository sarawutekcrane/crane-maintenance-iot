"""R8 PRE-UAT (Owner source approval Rev 1, Decision 2) — TEST repair code catalogue.

Source: the Owner-supplied workbook `Repair_Code_3_Levels_Reviewed_S01-S05.xlsx`
(SHA-256 eec02999…1560), kept as a RAW extract
(app/data/repair_catalogue/repair_code_3_levels_reviewed_s01_s05.source.json). Every cell
is preserved; no code is invented, remapped or re-described.

The TEST candidate subset is computed here by the fixed rule TEST-CANDIDATE-R1 — never a
hand-picked list. A selector relationship SYSTEM-ASSEMBLY-POINT is a candidate only when
ALL of the following hold:
  1. the composite code parses as SYSTEM-ASSEMBLY-POINT and all three codes are registered;
  2. the selector's system / assembly / point names equal the registry names exactly;
  3. the point status is "จัดประเภทได้";
  4. the system is listed among the assembly's paired systems;
  5. at least one symptom reference is registered in the symptom registry (S01–S05)
     with an IDENTICAL label (cross-checked with the point registry); only those
     references become the allowed symptoms of that relationship.
Repair actions are the separate global registry (A01–A15), chosen per work actually done.

Everything else stays in the catalogue with its exclusion reasons. Release status
TEST_CANDIDATE_R1: TEST only, never an approved REAL taxonomy.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

SOURCE_PATH = Path(__file__).resolve().parent.parent / "data" / "repair_catalogue" / \
    "repair_code_3_levels_reviewed_s01_s05.source.json"
EXPECTED_SOURCE_SHA256 = "eec029991568c63a41ef21e3ee1afdcd525ea5392d24eb5bcafdd6a9cfed1560"
# Pinned in code (independent review): an edited extract with a recomputed hash is still refused.
EXPECTED_EXTRACT_SHA256 = "06764530d6f6104dfcf4dd706d1de88838edbdcd4cd68c31654a97ef085c5b3e"
RULE_VERSION = "TEST-CANDIDATE-R1"
RELEASE_STATUS = "TEST_CANDIDATE_R1"
NOT_FOR_REAL_NOTE_TH = "TEST candidate — ไม่อนุมัติสำหรับ REAL"
CLASSIFIABLE_TH = "จัดประเภทได้"

_CODE = re.compile(r"^[A-Z]{2,4}$")
_POINT = re.compile(r"^P\d{3}$")
_SYMPTOM = re.compile(r"^S\d\d$")
_ACTION = re.compile(r"^A\d\d$")
_COMPOSITE = re.compile(r"^([A-Z]{2,4})-([A-Z]{2,4})-(P\d{3})$")
_SYMPTOM_REF = re.compile(r"(S\d\d)\s*—\s*([^\n]+)")


class CatalogueIntegrityError(Exception):
    """The raw extract is missing, not the Owner's workbook, or was edited."""


@dataclass(frozen=True)
class Relationship:
    code: str
    system: str
    assembly: str
    point: str
    system_name: str
    assembly_name: str
    point_name: str
    candidate: bool
    exclusion_reasons: tuple[str, ...]
    allowed_symptoms: tuple[str, ...]
    source_symptom_text: str
    source_row: int


@dataclass(frozen=True)
class Catalogue:
    source_sha256: str
    extract_sha256: str
    systems: dict[str, str]
    assemblies: dict[str, dict[str, object]]
    points: dict[str, dict[str, str]]
    symptoms: dict[str, str]
    actions: dict[str, str]
    relationships: dict[str, Relationship]
    open_questions: int
    rule_version: str = RULE_VERSION
    release_status: str = RELEASE_STATUS
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def candidates(self) -> dict[str, Relationship]:
        return {k: r for k, r in self.relationships.items() if r.candidate}

    def summary(self) -> dict[str, object]:
        reasons: dict[str, int] = {}
        for rel in self.relationships.values():
            for reason in rel.exclusion_reasons:
                reasons[reason] = reasons.get(reason, 0) + 1
        cands = self.candidates
        return {"rule_version": self.rule_version, "release_status": self.release_status,
                "not_for_real": True, "note_th": NOT_FOR_REAL_NOTE_TH, "source_sha256": self.source_sha256,
                "extract_sha256": self.extract_sha256, "systems": len(self.systems),
                "assemblies": len(self.assemblies), "points": len(self.points), "symptoms": len(self.symptoms),
                "actions": len(self.actions), "relationships": len(self.relationships),
                "candidates": len(cands), "candidate_points": len({r.point for r in cands.values()}),
                "exclusion_reasons": dict(sorted(reasons.items())), "open_owner_questions": self.open_questions}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sheet_rows(sheets: list[Mapping[str, object]], index: int) -> list[list[str]]:
    for sheet in sheets:
        if sheet.get("index") == index:
            return [list(r["cells"]) for r in sheet["rows"]]  # type: ignore[index]
    raise CatalogueIntegrityError(f"sheet {index} missing")


def _rows_with_numbers(sheets: list[Mapping[str, object]], index: int) -> list[tuple[int, list[str]]]:
    for sheet in sheets:
        if sheet.get("index") == index:
            return [(int(r["row"]), list(r["cells"])) for r in sheet["rows"]]  # type: ignore[index]
    raise CatalogueIntegrityError(f"sheet {index} missing")


def _cell(cells: list[str], i: int) -> str:
    return cells[i] if i < len(cells) else ""


def _symptom_refs(text: str) -> list[tuple[str, str]]:
    return [(c, t.strip()) for c, t in _SYMPTOM_REF.findall(text)]


def build_catalogue(payload: Mapping[str, object]) -> Catalogue:
    sheets = payload.get("sheets")
    if payload.get("source_sha256") != EXPECTED_SOURCE_SHA256 or not isinstance(sheets, list):
        raise CatalogueIntegrityError("not the Owner-supplied workbook extract")
    digest = hashlib.sha256(_canonical(sheets).encode("utf-8")).hexdigest()
    if digest != EXPECTED_EXTRACT_SHA256 or payload.get("extract_sha256") != EXPECTED_EXTRACT_SHA256:
        raise CatalogueIntegrityError("the raw extract was edited after extraction")
    systems = {c[0]: _cell(c, 1) for c in _sheet_rows(sheets, 2) if c and _CODE.match(c[0])}
    assemblies: dict[str, dict[str, object]] = {}
    for c in _sheet_rows(sheets, 3):
        if c and _CODE.match(c[0]):
            paired = [p.strip() for p in _cell(c, 2).split("/") if p.strip()]
            assemblies[c[0]] = {"name": _cell(c, 1), "paired_systems": paired}
    points = {c[0]: {"name": _cell(c, 1), "symptoms": _cell(c, 2), "status": _cell(c, 5).strip()}
              for c in _sheet_rows(sheets, 4) if c and _POINT.match(c[0])}
    symptoms, actions = {}, {}
    for c in _sheet_rows(sheets, 5):
        if c and _SYMPTOM.match(c[0]):
            symptoms[c[0]] = _cell(c, 1)
        elif c and _ACTION.match(c[0]):
            actions[c[0]] = _cell(c, 1)
    questions = sum(1 for c in _sheet_rows(sheets, 6) if c and re.match(r"^Q\d+$", c[0]))
    relationships: dict[str, Relationship] = {}
    header_seen = False
    for number, c in _rows_with_numbers(sheets, 1):
        if c and c[0] == "1 ระบบหลัก":
            header_seen = True
            continue
        code = _cell(c, 5).strip()
        if not header_seen or not code:
            continue
        reasons: list[str] = []
        match = _COMPOSITE.match(code)
        s = a = p = ""
        if not match:
            reasons.append("CODE_FORMAT")
        else:
            s, a, p = match.groups()
            if s not in systems:
                reasons.append("UNKNOWN_SYSTEM")
            elif systems[s].strip() != _cell(c, 0).strip():
                reasons.append("SYSTEM_NAME_MISMATCH")
            if a not in assemblies:
                reasons.append("UNKNOWN_ASSEMBLY")
            else:
                if str(assemblies[a]["name"]).strip() != _cell(c, 1).strip():
                    reasons.append("ASSEMBLY_NAME_MISMATCH")
                if s not in assemblies[a]["paired_systems"]:  # type: ignore[operator]
                    reasons.append("SYSTEM_NOT_PAIRED_WITH_ASSEMBLY")
            if p not in points:
                reasons.append("UNKNOWN_POINT")
            else:
                if points[p]["name"].strip() != _cell(c, 2).strip():
                    reasons.append("POINT_NAME_MISMATCH")
                if points[p]["status"] != CLASSIFIABLE_TH:
                    reasons.append("POINT_PENDING_MEANING")
        refs = _symptom_refs(_cell(c, 3))
        consistent = [code_ for code_, label in refs if symptoms.get(code_) == label]
        point_codes = {code_ for code_, _ in _symptom_refs(points[p]["symptoms"])} if p in points else set()
        allowed = [code_ for code_ in consistent if not point_codes or code_ in point_codes]
        if not refs:
            reasons.append("NO_SYMPTOM_IN_SOURCE")
        elif not allowed:
            reasons.append("NO_CONSISTENT_SYMPTOM")
        candidate = not reasons
        relationships[code] = Relationship(
            code=code, system=s, assembly=a, point=p, system_name=_cell(c, 0), assembly_name=_cell(c, 1),
            point_name=_cell(c, 2), candidate=candidate, exclusion_reasons=tuple(reasons),
            allowed_symptoms=tuple(allowed) if candidate else (), source_symptom_text=_cell(c, 3),
            source_row=number)
    return Catalogue(source_sha256=str(payload["source_sha256"]), extract_sha256=str(payload["extract_sha256"]),
                     systems=systems, assemblies=assemblies, points=points, symptoms=symptoms, actions=actions,
                     relationships=relationships, open_questions=questions)


@lru_cache(maxsize=1)
def load_catalogue() -> Catalogue:
    try:
        payload = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogueIntegrityError("raw extract unreadable") from exc
    return build_catalogue(payload)


__all__ = ["Catalogue", "CatalogueIntegrityError", "Relationship", "build_catalogue", "load_catalogue",
           "RULE_VERSION", "RELEASE_STATUS", "NOT_FOR_REAL_NOTE_TH", "SOURCE_PATH"]
