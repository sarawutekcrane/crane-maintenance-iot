"""R8 early workstream — the person-axis check added to E2 coverage writes
(CC-08 / CC-09, OD-2 = A). SYNTHETIC Mock/TEST data only.

Proves: an E2 CREATE / REVISE that would double-book a person who is on a crew is
refused (linked driver -> RESOURCE_CONFLICT; unlinked / ambiguous driver
overlapping any crew -> CROSS_ROLE_IDENTITY_UNVERIFIED), interval-scoped; CANCEL /
EARLY_END are never refused by it; with no overlapping crew the E2 outcome is the
pre-R8 one; and the two-stream guard refuses an E2 append when the crew stream moved
after the read (one-process proof only — R11 owes the PostgreSQL equivalent).
"""
from __future__ import annotations

import uuid

import pytest

from app.errors import ApiError
from app.repositories.base import RepositoryConcurrentChangeError
from tests.test_r8_crew_assignment import (
    DRV_A,
    DRV_B,
    E2,
    NOW,
    P1,
    P2,
    V1,
    V2,
    code_of,
    create,
    crew_rows,
    e2_create,
    link,
    store,
)


def e2_rows(repo) -> list[dict[str, str]]:
    return repo._operational_driver_assignment_history


async def test_e2_create_for_a_linked_driver_on_crew_is_refused() -> None:
    repo = store()
    await create(repo, personnel=P1, vehicle=V2)
    link(repo, P1, DRV_A)
    with pytest.raises(ApiError) as exc:
        await e2_create(repo, DRV_A)
    assert exc.value.code == "RESOURCE_CONFLICT" and exc.value.details["axis"] == "PERSON"
    assert e2_rows(repo) == []


async def test_e2_create_for_an_unlinked_driver_overlapping_crew_is_unverified() -> None:
    repo = store()
    await create(repo, personnel=P2, vehicle=V2)
    assert await code_of(e2_create(repo, DRV_B)) == "CROSS_ROLE_IDENTITY_UNVERIFIED"
    assert e2_rows(repo) == []
    assert (await e2_create(repo, DRV_B, start="2026-11-21", end="2026-11-21")).changed  # interval-scoped


async def test_e2_create_for_a_linked_driver_of_another_person_is_allowed() -> None:
    repo = store()
    await create(repo, personnel=P2, vehicle=V2)
    link(repo, P1, DRV_A)
    assert (await e2_create(repo, DRV_A)).changed


async def test_e2_revise_that_extends_into_crew_time_is_refused() -> None:
    repo = store()
    link(repo, P1, DRV_A)
    event = (await e2_create(repo, DRV_A, start="2026-11-20", end="2026-11-20")).event_ids[0]
    await create(repo, personnel=P1, vehicle=V2, start="2026-11-21", end="2026-11-21")
    revise = {"operation": "REVISE", "event_id": event, "expected_revision_no": "1", "reason_th": "ขยายวัน",
              "driver_id": DRV_A, "start_date": "2026-11-20", "end_date": "2026-11-21"}
    assert await code_of(E2(repo).apply(V1, revise, request_id=str(uuid.uuid4()), user_id="dev-user")) == \
        "RESOURCE_CONFLICT"
    assert len(e2_rows(repo)) == 1


async def test_e2_cancel_and_early_end_are_never_refused_by_the_person_check() -> None:
    repo = store()
    future = (await e2_create(repo, DRV_B, start="2026-11-25", end="2026-11-25")).event_ids[0]
    current = (await e2_create(repo, DRV_B, vehicle=V2, start="2026-11-18", end="2026-11-19")).event_ids[0]
    # a pre-existing conflicting crew row injected directly (data written before R8 rules)
    await create(repo, personnel=P2, start="2026-11-28", end="2026-11-28")
    row = crew_rows(repo)[0]
    row.update(start_date="2026-11-25", end_date="2026-11-25")
    svc = E2(repo)
    cancel = {"operation": "CANCEL", "event_id": future, "expected_revision_no": "1", "reason_th": "ยกเลิก"}
    assert (await svc.apply(V1, cancel, request_id=str(uuid.uuid4()), user_id="dev-user")).changed
    early = {"operation": "EARLY_END", "event_id": current, "expected_revision_no": "1", "reason_th": "จบงาน",
             "end": {"mode": "NOW"}}
    assert (await svc.apply(V2, early, request_id=str(uuid.uuid4()), user_id="dev-user")).changed


class Spy(type(store())):
    def __init__(self) -> None:
        super().__init__(access_management_seed=True)
        self.calls: list[str] = []

    async def read_crew_assignment_history_validated(self):
        self.calls.append("read_crew")
        return await super().read_crew_assignment_history_validated()

    async def append_resource_assignment_rows(self, *args):
        self.calls.append("append_two_stream")
        return await super().append_resource_assignment_rows(*args)

    async def append_operational_driver_assignment_rows(self, *args):
        self.calls.append("append_e2_only")
        return await super().append_operational_driver_assignment_rows(*args)


async def test_coverage_writes_use_the_two_stream_append_and_removals_do_not() -> None:
    repo = Spy()
    event = (await e2_create(repo, DRV_B, start="2026-11-25", end="2026-11-25")).event_ids[0]
    assert repo.calls == ["read_crew", "append_two_stream"]
    repo.calls.clear()
    cancel = {"operation": "CANCEL", "event_id": event, "expected_revision_no": "1", "reason_th": "ยกเลิก"}
    await E2(repo).apply(V1, cancel, request_id=str(uuid.uuid4()), user_id="dev-user")
    assert repo.calls == ["append_e2_only"]


async def test_e2_append_refused_when_crew_moved_after_the_read() -> None:
    repo = store()
    crew_before = await repo.read_crew_assignment_history_validated()
    e2_before = await repo.read_operational_driver_assignment_history_validated()
    await create(repo, personnel=P2)  # a crew write lands between the E2 read and append
    with pytest.raises(RepositoryConcurrentChangeError):
        await repo.append_resource_assignment_rows(e2_before, crew_before, "E2", [{}])
    assert e2_rows(repo) == []


def test_now_constant_is_shared() -> None:
    assert NOW.tzinfo is not None
