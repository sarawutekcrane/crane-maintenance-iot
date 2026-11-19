"""R8 PRE-UAT (Owner Decision 2) — TEST repair classification, end to end on the Mock repository
(Access Management mode, per-employee TEST grants). Acceptance needs BOTH:
(1) a successful TEST classification after closure + Store reconciliation, and
(2) every fail-closed rejection. The TEST subset never implies REAL approval."""
from __future__ import annotations

import uuid

import pytest

from app.domain.repair_catalogue import load_catalogue
from app.domain.repair_classification import RepairClassificationService
from app.domain.store_workflow import StoreWorkflowService
from app.domain.technician_assignment import AssignmentCutover
from app.errors import ApiError
from tests import test_access_management as am
from tests.test_preuat_store_workflow import open_repair, recon, request_parts, step

API = am.API
MGR, TECH1 = am.MGR, am.TECH1


@pytest.fixture(autouse=True)
def am_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


def candidates(n: int = 2):
    cands = sorted(load_catalogue().candidates.values(), key=lambda r: r.code)
    return cands[:n]


def row_for(rel, **over) -> dict:
    row = {"system": rel.system, "assembly": rel.assembly, "point": rel.point,
           "symptoms": [rel.allowed_symptoms[0]], "actions": ["A03"], "position": {"side": "LEFT"}}
    row.update(over)
    return row


async def closed_reconciled_repair(store, *, reconcile: bool = True) -> str:
    rid = await open_repair(store)
    await am.grant(store, MGR, am.employee(MGR), {"can_test_classify_repair": True})
    line = (await request_parts(store, rid, lines=[{"part_id": "PART-0001", "part_description": "x", "quantity": 1,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 1})
    await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001"})
    assert (await am.http("POST", f"{API}/repairs/{rid}/close", store, MGR, json={})).status_code == 200
    if reconcile:
        await step(store, rid, line, "use-confirmations",
                   {"quantity": 1, "part_id": "PART-0001", "position_code": "P1"}, user=TECH1)
        assert (await recon(store, rid))["state"] == "RECONCILED"
    return rid


async def view(store, rid, user=MGR):
    response = await am.http("GET", f"{API}/repairs/{rid}/classification", store, user, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


async def stage(store, rid, rows, *, expected=0, user=MGR, request_id="auto"):
    return await am.http("POST", f"{API}/repairs/{rid}/classification-drafts", store, user,
                         json={"expected_revision": expected, "rows": rows}, request_id=request_id)


async def finalize(store, rid, expected, *, user=MGR, request_id="auto"):
    return await am.http("POST", f"{API}/repairs/{rid}/classification-finalizations", store, user,
                         json={"expected_revision": expected}, request_id=request_id)


async def test_successful_test_classification_end_to_end_with_two_failure_points() -> None:
    store = am.repo()
    rid = await open_repair(store)
    await am.grant(store, MGR, am.employee(MGR), {"can_test_classify_repair": True})
    assert (await view(store, rid))["state"] == "NOT_ELIGIBLE"
    line = (await request_parts(store, rid, lines=[{"part_id": "PART-0001", "part_description": "x", "quantity": 2,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    assert (await am.http("POST", f"{API}/repairs/{rid}/close", store, MGR, json={})).status_code == 200
    blocked = await view(store, rid)
    assert blocked["state"] == "BLOCKED_STORE_UNRECONCILED" and "ISSUED_NOT_USED_OR_RETURNED" in blocked["blockers"]
    a, b = candidates(2)
    assert am.code(await stage(store, rid, [row_for(a)])) == (409, "CLASSIFICATION_BLOCKED_STORE_UNRECONCILED")
    await step(store, rid, line, "use-confirmations", {"quantity": 1, "part_id": "PART-0001", "position_code": "P1"},
               user=TECH1)
    await step(store, rid, line, "return-declarations", {"quantity": 1, "part_id": "PART-0001"}, user=TECH1)
    await step(store, rid, line, "return-acceptances", {"quantity": 1, "part_id": "PART-0001"})
    assert (await view(store, rid))["state"] == "WAITING_FOR_CLASSIFICATION"
    staged = await stage(store, rid, [row_for(a), row_for(b, actions=["A01", "A13"], position={"end": "FRONT"})])
    assert staged.status_code == 200, staged.text
    assert staged.json()["draft_revision"] == 1 and len(staged.json()["draft_rows"]) == 2
    done = await finalize(store, rid, 1)
    assert done.status_code == 200, done.text
    final = done.json()
    assert final["state"] == "CLASSIFIED" and final["note_th"].startswith("TEST candidate")
    assert final["final"]["catalogue_rule"] == "TEST-CANDIDATE-R1"
    assert "fingerprint" not in final["final"]  # stored for replay, never exposed (independent review)
    assert final["final"]["catalogue_release_status"] == "TEST_CANDIDATE_R1"
    assert [r["code"] for r in final["final"]["rows"]] == [a.code, b.code]
    # Classification never modifies the repair, its parts or the store journal.
    repair = await am.http("GET", f"{API}/repairs/{rid}", store, MGR, request_id=None)
    assert repair.json()["repair"]["status"] == "CLOSED"
    assert (await recon(store, rid))["state"] == "RECONCILED"
    assert am.code(await stage(store, rid, [row_for(a)], expected=1)) == (409, "REPAIR_ALREADY_CLASSIFIED")
    assert am.code(await finalize(store, rid, 1)) == (409, "REPAIR_ALREADY_CLASSIFIED")


async def test_every_invalid_code_is_rejected_fail_closed() -> None:
    store = am.repo()
    rid = await closed_reconciled_repair(store)
    catalogue = load_catalogue()
    a = candidates(1)[0]
    excluded = next(r for r in catalogue.relationships.values() if not r.candidate and r.system in catalogue.systems
                    and r.assembly in catalogue.assemblies and r.point in catalogue.points)
    pending_point = next(p for p, v in catalogue.points.items() if v["status"] != "จัดประเภทได้")
    cases = [
        (row_for(a, system="ZZZ"), "REPAIR_CODE_UNKNOWN"),
        (row_for(a, point="P999"), "REPAIR_CODE_UNKNOWN"),
        (row_for(a, assembly=next(x for x in catalogue.assemblies if x != a.assembly
                                  and f"{a.system}-{x}-{a.point}" not in catalogue.relationships)),
         "REPAIR_CODE_HIERARCHY_INVALID"),
        (row_for(a, point=pending_point), None),  # unknown pairing or excluded: never accepted
        ({"system": excluded.system, "assembly": excluded.assembly, "point": excluded.point,
          "symptoms": ["S01"], "actions": ["A03"]}, "REPAIR_CODE_ENTRY_NOT_IN_TEST_SUBSET"),
        (row_for(a, symptoms=["S42"]), "REPAIR_SYMPTOM_NOT_ALLOWED"),
        (row_for(a, symptoms=[next(s for s in catalogue.symptoms if s not in a.allowed_symptoms)]),
         "REPAIR_SYMPTOM_NOT_ALLOWED"),
        (row_for(a, actions=["A99"]), "REPAIR_ACTION_UNKNOWN"),
        (row_for(a, symptoms=[]), "VALIDATION_ERROR"),
        (row_for(a, position={"side": "MIDDLE"}), "VALIDATION_ERROR"),
        (row_for(a, extra="x"), "VALIDATION_ERROR"),
    ]
    for row, expected in cases:
        response = await stage(store, rid, [row])
        assert response.status_code == 422, (row, response.text)
        if expected:
            assert am.code(response)[1] == expected, (row, response.text)
    duplicate = await stage(store, rid, [row_for(a), row_for(a)])
    assert am.code(duplicate) == (422, "VALIDATION_ERROR")
    excluded_reply = await stage(store, rid, [{"system": excluded.system, "assembly": excluded.assembly,
                                               "point": excluded.point, "symptoms": ["S01"], "actions": ["A03"]}])
    assert excluded_reply.json()["error"]["details"]["reasons"] == list(excluded.exclusion_reasons)
    assert (await view(store, rid))["draft_revision"] == 0  # nothing staged by any refusal


async def test_eligibility_staleness_replay_and_permissions() -> None:
    store = am.repo()
    rid = await open_repair(store)
    await am.grant(store, MGR, am.employee(MGR), {"can_test_classify_repair": True})
    a = candidates(1)[0]
    assert am.code(await stage(store, rid, [row_for(a)])) == (409, "CLASSIFICATION_NOT_ELIGIBLE")
    rid2 = await closed_reconciled_repair(store)
    assert am.code(await stage(store, rid2, [row_for(a)], user=TECH1)) == (403, "PREUAT_ACTION_NOT_AUTHORIZED")
    rq = str(uuid.uuid4())
    first = await stage(store, rid2, [row_for(a)], request_id=rq)
    again = await stage(store, rid2, [row_for(a)], request_id=rq)
    assert again.json()["replayed"] is True and again.json()["draft_revision"] == first.json()["draft_revision"] == 1
    assert am.code(await stage(store, rid2, [row_for(a, actions=["A01"])], request_id=rq)) == (409, "REQUEST_ID_REUSED")
    assert am.code(await stage(store, rid2, [row_for(a)], expected=0)) == (409, "CLASSIFICATION_DRAFT_STALE")
    assert am.code(await finalize(store, rid2, 2)) == (409, "CLASSIFICATION_DRAFT_STALE")
    assert (await stage(store, rid2, [row_for(a, actions=["A01"])], expected=1)).json()["draft_revision"] == 2
    assert (await finalize(store, rid2, 2)).json()["state"] == "CLASSIFIED"
    catalogue = await am.http("GET", f"{API}/repair-classification/catalogue", store, MGR, request_id=None)
    body = catalogue.json()
    assert body["summary"]["candidates"] == 24 and body["summary"]["not_for_real"] is True
    assert sum(len(p["points"]) for s in body["tree"] for p in s["assemblies"]) == 24
    assert len(body["excluded"]) == 181
    assert (await am.http("GET", f"{API}/repair-classification/catalogue", store, am.CLERK,
                          request_id=None)).status_code == 403


async def test_real_context_and_sheets_are_refused() -> None:
    store = am.repo()
    real = RepairClassificationService(store, StoreWorkflowService(store, AssignmentCutover(data_context="REAL"),
                                                                    mock_repository=True),
                                       "REAL", "", mock_repository=True)
    with pytest.raises(ApiError) as refused:
        await real.view("REP-0001")
    assert (refused.value.status_code, refused.value.code) == (409, "CLASSIFICATION_REAL_NOT_ENABLED")
    sheets = RepairClassificationService(store, StoreWorkflowService(store, AssignmentCutover(data_context="TEST"),
                                                                      mock_repository=False),
                                         "TEST", "B", mock_repository=False)
    with pytest.raises(ApiError) as not_mock:
        await sheets.view("REP-0001")
    assert not_mock.value.status_code == 501



async def test_the_store_reconciliation_is_rechecked_right_before_the_classification_write(monkeypatch) -> None:
    from app.domain.store_workflow import StoreWorkflowService, UNRECONCILED

    store = am.repo()
    rid = await closed_reconciled_repair(store)
    original = StoreWorkflowService.reconciliation
    calls = {"n": 0}

    async def drifting(self, repair_id):
        rec = await original(self, repair_id)
        calls["n"] += 1
        if calls["n"] >= 2:  # a store event lands after the first check, before the append
            rec.state = UNRECONCILED
            rec.lines[0].identity_unknown = 1
        return rec

    monkeypatch.setattr(StoreWorkflowService, "reconciliation", drifting)
    [a] = candidates(1)
    refused = await stage(store, rid, [row_for(a)])
    assert am.code(refused) == (409, "CLASSIFICATION_BLOCKED_STORE_UNRECONCILED")
    assert not [r for r in store._preuat_journals.get("CLASSIFICATION", []) if r.get("repair_id") == rid]
