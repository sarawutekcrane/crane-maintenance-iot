"""R8 early workstream — Crew Assignment Extension service and routes
(Owner source approval 2026-11-18: OD-1…OD-4, OD-7). SYNTHETIC Mock/TEST data only.

Not PostgreSQL or production evidence: the concurrency cases prove the mock's
ONE-PROCESS two-stream guard (crew + E2); cross-process one-winner and persistent
overlap safety are R11 obligations.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app.domain import authz
from app.domain.crew_assignment import CrewAssignmentService
from app.domain.operational_driver_assignment import OperationalDriverAssignmentService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.mock.repository import MockRepository

NOW = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)  # 10:00 Bangkok, 2026-11-18
V1, V2 = "VEH-1048", "VEH-TEST-901"  # the two TEST-scoped vehicle references of the mock batch
P1, P2, P_INACTIVE = "PER-TEST-AM-DRV1", "PER-TEST-911", "PER-TEST-AM-RESIGNED"
DRV_A, DRV_B = "DRV-TEST-901", "DRV-TEST-902"


class Crew(CrewAssignmentService):
    def __init__(self, repo, *, now: datetime = NOW, context: str = "TEST", mock: bool = True) -> None:
        super().__init__(repo, context, MOCK_TEST_BATCH_ID, mock_repository=mock)
        self.fixed = now

    def _now(self) -> datetime:
        return self.fixed


class E2(OperationalDriverAssignmentService):
    def __init__(self, repo, *, now: datetime = NOW) -> None:
        super().__init__(repo, "TEST", MOCK_TEST_BATCH_ID)
        self.fixed = now

    def _now(self) -> datetime:
        return self.fixed


def store() -> MockRepository:
    return MockRepository(access_management_seed=True)


def link(repo: MockRepository, personnel_id: str, driver_id: str) -> None:
    for row in repo._personnel_master:  # synthetic R2f-e link, set directly for the test
        if row["personnel_id"] == personnel_id:
            row["driver_id"] = driver_id


def body(personnel: str = P1, *, role: str = "RIGGER", start: str = "2026-11-20", end: str = "2026-11-20",
         mode: str = "FULL_DAY", shift=None, note=None, reason=None) -> dict:
    b = {"operation": "CREATE", "personnel_id": personnel, "crew_role": role, "mode": mode, "start_date": start,
         "end_date": end}
    if shift is not None:
        b["shift"] = shift
    if note is not None:
        b["crew_role_note_th"] = note
    if reason is not None:
        b["reason_th"] = reason
    return b


async def create(repo, vehicle: str = V1, request_id: str | None = None, now: datetime = NOW, **kwargs):
    return await Crew(repo, now=now).apply(vehicle, body(**kwargs), request_id=request_id or str(uuid.uuid4()),
                                           user_id="USR-TEST-AM-CLERK")


async def e2_create(repo, driver: str, *, vehicle: str = V1, start: str = "2026-11-20", end: str = "2026-11-20",
                    request_id: str | None = None):
    return await E2(repo).apply(vehicle, {"operation": "CREATE", "driver_id": driver, "mode": "FULL_DAY",
                                          "start_date": start, "end_date": end},
                                request_id=request_id or str(uuid.uuid4()), user_id="dev-user")


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


def crew_rows(repo) -> list[dict[str, str]]:
    return repo._crew_assignment_history


# ---------------------------------------------------------------------------
# CREATE, roles, reads
# ---------------------------------------------------------------------------


async def test_create_records_one_append_only_row_and_reads_it_back() -> None:
    repo = store()
    outcome = await create(repo)
    assert outcome.changed and len(outcome.event_ids) == 1
    (row,) = crew_rows(repo)
    assert (row["record_kind"], row["entry_operation"], row["revision_no"], row["crew_role"]) == (
        "ASSIGNMENT", "CREATE", "1", "RIGGER")
    assert (row["is_test_data"], row["test_batch_id"], row["recorded_by"]) == ("TRUE", MOCK_TEST_BATCH_ID,
                                                                               "USR-TEST-AM-CLERK")
    read = await Crew(repo).vehicle_crew(V1)
    (view,) = read.intervals
    assert (view.interval.personnel_id, view.status) == (P1, "VALID")
    assert read.names[P1] == "คนขับหนึ่ง สังเคราะห์"


@pytest.mark.parametrize("role,note,code", [
    ("OTHER", None, "CREW_ROLE_NOTE_REQUIRED"),
    ("OTHER", "  ", "CREW_ROLE_NOTE_REQUIRED"),
    ("RIGGER", "หมายเหตุ", "CREW_ROLE_NOTE_NOT_ALLOWED"),
])
async def test_role_rules_od1(role, note, code) -> None:
    repo = store()
    assert await code_of(create(repo, role=role, note=note)) == code
    assert crew_rows(repo) == []


async def test_other_role_with_a_thai_note_is_accepted() -> None:
    repo = store()
    assert (await create(repo, role="OTHER", note="ผู้ช่วยผูกยึด")).changed


async def test_variable_crew_size_one_vehicle_many_people() -> None:
    repo = store()
    for person in (P1, P2, "PER-TEST-912", "PER-TEST-AM-CLERK", "PER-TEST-AM-OPM", "PER-TEST-AM-DRV2"):
        assert (await create(repo, personnel=person, role="SIGNALMAN")).changed  # no fixed crew size
    assert len((await Crew(repo).vehicle_crew(V1)).intervals) == 6


async def test_person_intervals_may_differ_from_any_driver_interval() -> None:
    repo = store()
    await e2_create(repo, DRV_A, start="2026-11-20", end="2026-11-20")
    link(repo, "PER-TEST-AM-MGR", DRV_A)
    shift = {"start_time": "13:00", "end_time": "17:00", "end_day_offset": 0}
    assert (await create(repo, personnel=P2, mode="DAY_SHIFT", shift=shift)).changed  # no containment rule


# ---------------------------------------------------------------------------
# Person-axis conflicts (CC-08 / CC-09 / OD-2 = A)
# ---------------------------------------------------------------------------


async def test_same_person_on_two_vehicles_is_refused() -> None:
    repo = store()
    await create(repo)
    assert await code_of(create(repo, vehicle=V2)) == "RESOURCE_CONFLICT"
    assert len(crew_rows(repo)) == 1


async def test_touching_is_allowed_with_a_rest_warning() -> None:
    repo = store()
    await create(repo, start="2026-11-20", end="2026-11-20")
    outcome = await create(repo, vehicle=V2, start="2026-11-21", end="2026-11-21")
    assert outcome.changed
    assert [w.code for w in outcome.warnings] == ["PERSON_ADJACENT_ASSIGNMENT_REST_WARNING"]


async def test_crew_versus_linked_driver_is_refused() -> None:
    repo = store()
    link(repo, P1, DRV_A)
    await e2_create(repo, DRV_A)
    with pytest.raises(ApiError) as exc:
        await create(repo, vehicle=V2)
    assert exc.value.code == "RESOURCE_CONFLICT"
    details = exc.value.details
    assert details["axis"] == "PERSON"
    assert {details["first"]["kind"], details["second"]["kind"]} == {"DRIVER", "CREW"}


async def test_unlinked_driver_overlap_is_identity_unverified_and_interval_scoped() -> None:
    repo = store()  # no Personnel row carries DRV_B: it is UNLINKED
    await e2_create(repo, DRV_B, vehicle=V2, start="2026-11-22", end="2026-11-22")
    assert await code_of(create(repo, start="2026-11-22", end="2026-11-22")) == "CROSS_ROLE_IDENTITY_UNVERIFIED"
    assert (await create(repo, start="2026-11-23", end="2026-11-23")).changed  # no overlap: allowed


async def test_ambiguous_driver_link_is_identity_unverified() -> None:
    repo = store()
    link(repo, "PER-TEST-AM-OPM", DRV_B)
    await e2_create(repo, DRV_B, vehicle=V2)  # recorded while the link was single
    link(repo, "PER-TEST-AM-DRV2", DRV_B)  # the identity later becomes ambiguous
    # E2 itself refuses the ambiguous driver for a NEW assignment (unchanged R2 rule) ...
    assert await code_of(e2_create(repo, DRV_B, vehicle=V2, start="2026-11-27", end="2026-11-27")) == \
        "DRIVER_PERSONNEL_AMBIGUOUS"
    # ... and a crew write overlapping the existing interval cannot rule the person out
    assert await code_of(create(repo, personnel=P2)) == "CROSS_ROLE_IDENTITY_UNVERIFIED"
    assert crew_rows(repo) == []


# ---------------------------------------------------------------------------
# Replay, duplicates, stale, lifecycle
# ---------------------------------------------------------------------------


async def test_replay_and_request_id_reuse() -> None:
    repo = store()
    first = await create(repo, request_id="req-r8-1")
    again = await create(repo, request_id="req-r8-1")
    assert again.replayed and again.record_ids == first.record_ids
    assert await code_of(create(repo, request_id="req-r8-1", start="2026-11-25", end="2026-11-25")) == \
        "REQUEST_ID_REUSED"
    assert len(crew_rows(repo)) == 1


async def test_identical_assignment_with_a_new_request_id_is_not_duplicated() -> None:
    repo = store()
    first = await create(repo)
    again = await create(repo)
    assert not again.changed and again.existing_event_id == first.event_ids[0]
    assert len(crew_rows(repo)) == 1


async def test_revise_stale_cancel_and_cancelled() -> None:
    repo = store()
    event = (await create(repo, start="2026-11-25", end="2026-11-26")).event_ids[0]
    svc = Crew(repo)
    stale = {"operation": "REVISE", "event_id": event, "expected_revision_no": "9", "reason_th": "แก้",
             "crew_role": "SIGNALMAN", "mode": "FULL_DAY", "start_date": "2026-11-25", "end_date": "2026-11-25"}
    assert await code_of(svc.apply(V1, stale, request_id="r1", user_id="u")) == "CREW_ASSIGNMENT_STALE"
    revised = await svc.apply(V1, {**stale, "expected_revision_no": "1"}, request_id="r2", user_id="u")
    assert revised.changed
    cancel = {"operation": "CANCEL", "event_id": event, "expected_revision_no": "2", "reason_th": "ยกเลิก"}
    assert (await svc.apply(V1, cancel, request_id="r3", user_id="u")).changed
    assert await code_of(svc.apply(V1, {**cancel, "expected_revision_no": "3"}, request_id="r4", user_id="u")) == \
        "CREW_ASSIGNMENT_CANCELLED"
    assert [r["record_kind"] for r in crew_rows(repo)] == ["ASSIGNMENT", "REVISION", "CANCELLATION"]
    assert (await svc.vehicle_crew(V1)).intervals == ()  # the interval is released


async def test_cancel_after_start_is_refused_and_early_end_now_clips() -> None:
    repo = store()
    event = (await create(repo, start="2026-11-18", end="2026-11-19")).event_ids[0]  # started today (same day)
    svc = Crew(repo)
    cancel = {"operation": "CANCEL", "event_id": event, "expected_revision_no": "1", "reason_th": "ยกเลิก"}
    assert await code_of(svc.apply(V1, cancel, request_id="c1", user_id="u")) == "CREW_ASSIGNMENT_ALREADY_STARTED"
    early = {"operation": "EARLY_END", "event_id": event, "expected_revision_no": "1", "reason_th": "เลิกงาน",
             "end": {"mode": "NOW"}}
    assert (await svc.apply(V1, early, request_id="e1", user_id="u")).changed
    (unit,) = (await svc.vehicle_crew(V1)).intervals
    assert unit.interval.end == NOW  # elapsed history kept, nothing after now


async def test_substitution_is_early_end_plus_create_od4() -> None:
    repo = store()
    event = (await create(repo, start="2026-11-18", end="2026-11-20")).event_ids[0]
    svc = Crew(repo)
    await svc.apply(V1, {"operation": "EARLY_END", "event_id": event, "expected_revision_no": "1",
                         "reason_th": "สลับคน", "end": {"mode": "AFTER_DATE", "date": "2026-11-18"}},
                    request_id="s1", user_id="u")
    assert (await create(repo, personnel=P2, start="2026-11-19", end="2026-11-20")).changed


# ---------------------------------------------------------------------------
# Eligibility, references, scope, REAL, Sheets
# ---------------------------------------------------------------------------


async def test_inactive_person_forward_refused_elapsed_correction_allowed() -> None:
    repo = store()
    assert await code_of(create(repo, personnel=P_INACTIVE)) == "PERSONNEL_NOT_ACTIVE"
    elapsed = await create(repo, personnel=P_INACTIVE, start="2026-11-10", end="2026-11-11",
                           reason="บันทึกย้อนหลัง")
    assert elapsed.changed


async def test_backdated_create_needs_a_reason() -> None:
    repo = store()
    assert await code_of(create(repo, start="2026-11-10", end="2026-11-10")) == "REASON_REQUIRED"


async def test_unknown_and_out_of_scope_person_and_vehicle() -> None:
    repo = store()
    assert await code_of(create(repo, personnel="PER-NOPE")) == "PERSONNEL_NOT_FOUND"
    real_person = next(r["personnel_id"] for r in repo._personnel_master if r["is_test_data"] == "FALSE")
    assert await code_of(create(repo, personnel=real_person)) == "PERSONNEL_SCOPE_UNPROVEN"
    assert await code_of(create(repo, vehicle="VEH-1046")) == "VEHICLE_SCOPE_UNPROVEN"
    assert await code_of(create(repo, vehicle="VEH-NOPE")) == "VEHICLE_NOT_FOUND"
    assert crew_rows(repo) == []


class NoCallRepo(MockRepository):
    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        if name.startswith(("read_", "append_", "list_", "get_")) and callable(value):
            raise AssertionError(f"repository call {name} before the REAL / mode refusal")
        return value


async def test_real_context_is_refused_before_any_repository_call() -> None:
    svc = Crew(NoCallRepo(), context="REAL")
    assert await code_of(svc.apply(V1, body(), request_id="x", user_id="u")) == "CREW_REAL_WRITES_NOT_ENABLED"


async def test_non_mock_repository_mode_is_501() -> None:
    svc = Crew(NoCallRepo(), mock=False)
    with pytest.raises(ApiError) as exc:
        await svc.apply(V1, body(), request_id="x", user_id="u")
    assert (exc.value.code, exc.value.status_code) == ("FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE", 501)


async def test_google_sheets_repository_refuses_both_crew_methods() -> None:
    from app.repositories.base import RegistryTableRead, RepositoryFeatureNotImplementedError
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    repo = GoogleSheetsRepository.__new__(GoogleSheetsRepository)  # no client: nothing may be requested
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await repo.read_crew_assignment_history_validated()
    empty = RegistryTableRead(rows=[], columns=frozenset())
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await repo.append_resource_assignment_rows(empty, empty, "CREW", [{}])


async def test_corrupt_crew_history_fails_closed_500() -> None:
    repo = store()
    await create(repo)
    crew_rows(repo)[0]["crew_role"] = "BOSS"
    with pytest.raises(ApiError) as exc:
        await Crew(repo).vehicle_crew(V1)
    assert (exc.value.code, exc.value.status_code) == ("CREW_HISTORY_DATA_INVALID", 500)


# ---------------------------------------------------------------------------
# Concurrency (ONE-PROCESS two-stream guard) and write faults
# ---------------------------------------------------------------------------


class Yielding(MockRepository):
    async def read_crew_assignment_history_validated(self):
        read = await super().read_crew_assignment_history_validated()
        await asyncio.sleep(0)  # let a concurrent request read the same versions
        return read


async def test_two_concurrent_overlapping_crew_writes_one_winner() -> None:
    repo = Yielding(access_management_seed=True)
    results = await asyncio.gather(create(repo), create(repo, vehicle=V2), return_exceptions=True)
    errors = [r for r in results if isinstance(r, ApiError)]
    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert [e.code for e in errors] == ["CREW_CONCURRENT_CHANGE"]
    assert len(crew_rows(repo)) == 1


async def test_crew_append_refused_when_e2_moved_after_the_read() -> None:
    repo = store()
    link(repo, P1, DRV_A)
    svc = Crew(repo)
    res = await svc.read_resources("TEST")
    await e2_create(repo, DRV_A)  # an E2 coverage write lands between the crew read and append
    from app.repositories.base import RepositoryConcurrentChangeError

    with pytest.raises(RepositoryConcurrentChangeError):
        await repo.append_resource_assignment_rows(res.e2_history, res.crew_history, "CREW", [{}])
    assert crew_rows(repo) == []


async def test_unknown_write_outcome_then_replay_learns_it() -> None:
    repo = store()
    repo.registry_write_faults["W1"] = "unknown_applied"
    with pytest.raises(ApiError) as exc:
        await create(repo, request_id="req-lost")
    assert exc.value.code == "CREW_HISTORY_WRITE_FAILED" and exc.value.details["history_write_outcome"] == "unknown"
    repo.registry_write_faults.clear()
    again = await create(repo, request_id="req-lost")
    assert again.replayed and len(crew_rows(repo)) == 1  # the lost response is recovered, no duplicate


async def test_rejected_write_changes_nothing() -> None:
    repo = store()
    repo.registry_write_faults["W1"] = "rejected"
    assert await code_of(create(repo)) == "CREW_HISTORY_WRITE_FAILED"
    assert crew_rows(repo) == []


# ---------------------------------------------------------------------------
# HTTP: OD-3 = A authorization (Access Management TEST grant only)
# ---------------------------------------------------------------------------


def _am():
    from tests import test_access_management as am

    return am


@pytest.fixture
def am_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


def test_capability_has_no_default_holder() -> None:
    assert authz.CAN_ASSIGN_CRANE_CREW not in authz.ALL_CAPABILITIES  # ADMIN does not inherit it
    assert all(authz.CAN_ASSIGN_CRANE_CREW not in caps for caps in authz.ROLE_CAPABILITIES.values())
    assert authz.CAN_ASSIGN_CRANE_CREW in authz.R8_TEST_ONLY_CAPABILITIES
    assert authz.TEST_ONLY_CAPABILITIES.isdisjoint(authz.R8_TEST_ONLY_CAPABILITIES)  # R7 set unchanged
    from app.domain.access_management import CATALOG, SENSITIVE

    (entry,) = [e for e in CATALOG if e.code == authz.CAN_ASSIGN_CRANE_CREW]
    assert entry.category == "H" and authz.CAN_ASSIGN_CRANE_CREW in SENSITIVE  # root-only, never delegable


async def test_http_granted_employee_writes_and_others_are_refused(am_env) -> None:
    am = _am()
    repo = am.repo()
    path = f"/api/v1/vehicles/{V1}/crew-assignment-operations"
    payload = body(P2, start="2026-12-01", end="2026-12-01")
    refused = await am.http("POST", path, repo, am.CLERK, json=payload)
    assert am.code(refused) == (403, "CREW_ASSIGNMENT_NOT_AUTHORIZED")  # no grant yet
    response = await am.grant(repo, am.MGR, am.employee(am.CLERK), {"can_view": True, "can_assign_crane_crew": True})
    assert response.status_code == 200, response.text
    assert "can_assign_crane_crew" not in await am.caps(repo, am.MGR)  # never automatic, root included
    ok = await am.http("POST", path, repo, am.CLERK, json=payload)
    assert ok.status_code == 200, ok.text
    assert ok.json()["changed"] is True
    missing_id = await am.http("POST", path, repo, am.CLERK, json=payload, request_id=None)
    assert missing_id.status_code == 422
    extra = await am.http("POST", path, repo, am.CLERK, json={**payload, "record_id": "X"})
    assert extra.status_code == 422  # server-set fields are refused
    driver_only = await am.grant(repo, am.MGR, am.employee(am.OPM), {"can_view": True,
                                                                       "can_assign_crane_driver": True})
    assert driver_only.status_code == 200, driver_only.text
    assert am.code(await am.http("POST", path, repo, am.OPM, json=payload))[0] == 403


async def test_http_legacy_admin_never_holds_the_crew_capability() -> None:
    from tests.test_r8_read_authorization import _http

    response = await _http("POST", f"/api/v1/vehicles/{V1}/crew-assignment-operations", MockRepository(),
                           role="ADMIN", json=body())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CREW_ASSIGNMENT_NOT_AUTHORIZED"


@pytest.mark.parametrize("path", [f"/api/v1/vehicles/{V1}/crew-assignments",
                                  f"/api/v1/vehicles/{V1}/crew-assignment-history"])
async def test_http_per_vehicle_reads_need_a_trusted_can_view_actor(path, monkeypatch) -> None:
    from tests.test_r8_read_authorization import NoReadRepo, _http

    assert (await _http("GET", path, NoReadRepo(), role="UNKNOWN")).status_code == 403
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    assert (await _http("GET", path, NoReadRepo(), role=None, user=None)).status_code == 403


@pytest.mark.parametrize("role", ["DRIVER", "TECHNICIAN", "MAINTENANCE_MANAGER"])
async def test_http_per_vehicle_reads_for_can_view_readers(role) -> None:
    from tests.test_r8_read_authorization import _http

    repo = MockRepository()
    await create_with_plain_mock(repo)
    response = await _http("GET", f"/api/v1/vehicles/{V1}/crew-assignments", repo, role=role)
    assert response.status_code == 200, response.text
    (item,) = response.json()["intervals"]
    assert set(item) == {"event_id", "revision_no", "vehicle_id", "personnel_id", "personnel_name", "crew_role",
                         "crew_role_note_th", "mode", "label_date", "effective_start", "effective_end", "status"}


async def create_with_plain_mock(repo: MockRepository) -> None:
    """A crew row in a legacy-mode mock (no AM seed): a TEST personnel of the mock batch."""
    await Crew(repo).apply(V1, body(P2, start="2026-11-20", end="2026-11-20"), request_id=str(uuid.uuid4()),
                           user_id="u")
