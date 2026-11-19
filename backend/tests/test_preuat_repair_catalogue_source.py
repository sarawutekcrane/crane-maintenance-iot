"""R8 PRE-UAT (Owner Decision 2) — the TEST repair code catalogue built from the RAW extract of
the Owner workbook (SHA-256 eec02999…). Proves the deterministic TEST-CANDIDATE-R1 rule,
every exclusion reason, the integrity check and that nothing is remapped or invented."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.domain.repair_catalogue import (
    RELEASE_STATUS,
    RULE_VERSION,
    SOURCE_PATH,
    CatalogueIntegrityError,
    build_catalogue,
    load_catalogue,
)


def payload() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def test_counts_match_the_source_and_the_owner_audit() -> None:
    c = load_catalogue()
    s = c.summary()
    assert (s["systems"], s["assemblies"], s["points"], s["symptoms"], s["actions"]) == (11, 34, 258, 5, 15)
    assert (s["relationships"], s["open_owner_questions"]) == (205, 46)
    assert set(c.systems) >= {"DASH", "SVC", "KWO"} and "AC" in c.assemblies  # 2–4 letter codes kept
    assert c.symptoms == {"S01": "ไม่ทำงาน", "S02": "รั่วซึม", "S03": "แตกหัก", "S04": "สึกหรอ", "S05": "ผิดปกติ"}
    assert sorted(c.actions) == [f"A{n:02d}" for n in range(1, 16)]
    statuses = [p["status"] for p in c.points.values()]
    assert statuses.count("จัดประเภทได้") == 231 and statuses.count("รอยืนยันความหมาย") == 27


def test_test_candidate_subset_is_deterministic_and_test_only() -> None:
    c = load_catalogue()
    s = c.summary()
    assert (s["candidates"], s["candidate_points"]) == (24, 23)
    assert (s["rule_version"], s["release_status"], s["not_for_real"]) == (RULE_VERSION, RELEASE_STATUS, True)
    assert s["exclusion_reasons"] == {"ASSEMBLY_NAME_MISMATCH": 15, "NO_CONSISTENT_SYMPTOM": 126,
                                      "NO_SYMPTOM_IN_SOURCE": 52, "POINT_NAME_MISMATCH": 4}
    by_system: dict[str, int] = {}
    for rel in c.candidates.values():
        by_system[rel.system] = by_system.get(rel.system, 0) + 1
        # every allowed symptom is registered with the IDENTICAL label in the selector text
        for code in rel.allowed_symptoms:
            assert f"{code} — {c.symptoms[code]}" in rel.source_symptom_text
        assert rel.system in c.assemblies[rel.assembly]["paired_systems"]
        assert c.points[rel.point]["status"] == "จัดประเภทได้"
    assert by_system == {"ELE": 17, "HYD": 2, "ACM": 1, "COL": 1, "ENG": 1, "MEC": 1, "PNE": 1}
    assert build_catalogue(payload()).summary() == s  # same input -> same subset


def test_conflicting_symptom_ids_are_never_remapped() -> None:
    c = load_catalogue()
    conflicted = [r for r in c.relationships.values() if "S03 — รั่วซึม" in r.source_symptom_text]
    assert len(conflicted) >= 1
    for rel in conflicted:
        assert "S03" not in rel.allowed_symptoms and "S02" not in rel.allowed_symptoms
    s42 = [r for r in c.relationships.values() if "S42" in r.source_symptom_text]
    assert s42 and all("S42" not in r.allowed_symptoms for r in s42)
    assert all(not r.candidate for r in c.relationships.values() if r.system in ("SVC", "KWO", "DASH"))


def test_assembly_name_variants_stay_excluded_and_unedited() -> None:
    c = load_catalogue()
    mismatched = [r for r in c.relationships.values() if "ASSEMBLY_NAME_MISMATCH" in r.exclusion_reasons]
    assert {r.assembly for r in mismatched} == {"CWT", "OEX", "OJK"}
    assert c.assemblies["CWT"]["name"] == "ระบบเวท (CW)"
    assert any(r.assembly_name == "ระบบตุ้มน้ำหนัก (CW)" for r in mismatched)


def test_integrity_check_refuses_an_edited_or_foreign_extract() -> None:
    edited = payload()
    edited["sheets"][5]["rows"][3]["cells"][1] = "แก้ไขแล้ว"
    with pytest.raises(CatalogueIntegrityError):
        build_catalogue(edited)
    # Independent review: the extract hash is pinned in code, so recomputing it after an edit does not help.
    rehashed = payload()
    rehashed["sheets"][5]["rows"][3]["cells"][1] = "แก้ไขแล้ว"
    rehashed["extract_sha256"] = hashlib.sha256(json.dumps(rehashed["sheets"], ensure_ascii=False,
                                                           sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(CatalogueIntegrityError):
        build_catalogue(rehashed)
    foreign = copy.deepcopy(payload())
    foreign["source_sha256"] = "0" * 64
    with pytest.raises(CatalogueIntegrityError):
        build_catalogue(foreign)


def test_raw_extract_keeps_provenance_and_no_workbook_is_committed() -> None:
    p = payload()
    assert p["source_sha256"] == "eec029991568c63a41ef21e3ee1afdcd525ea5392d24eb5bcafdd6a9cfed1560"
    assert p["extractor_version"] == "1" and "NOT an approved REAL taxonomy" in p["status_note"]
    assert sum(len(s["rows"]) for s in p["sheets"]) == 625
    assert SOURCE_PATH.suffix == ".json"
