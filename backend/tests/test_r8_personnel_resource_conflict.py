"""R8 early workstream — pure person-axis conflict rules
(`personnel_resource_conflict`). SYNTHETIC data only; no I/O.

Proves CC-08 / CC-09 / OD-2 = A: same person across roles and vehicles refused;
an unlinked or ambiguous driver overlapping crew is CROSS_ROLE_IDENTITY_UNVERIFIED
(never "no conflict"); touching is allowed with a warning; E2 x E2 pairs are left
to the unchanged E2 axes; only new / worsened conflicts are refused.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.domain.crew_assignment_timeline import CrewInterval
from app.domain.operational_driver_timeline import Interval
from app.domain.personnel_resource_conflict import (
    CODE_IDENTITY_UNVERIFIED,
    CODE_RESOURCE_CONFLICT,
    driver_identities,
    find_person_conflicts,
    new_conflicts,
    person_adjacency,
    person_intervals,
)

D = date(2026, 11, 20)


def t(hour: int) -> datetime:
    return datetime(2026, 11, 20, hour, 0, tzinfo=timezone.utc)


def crew(event: str, person: str, start: int, end: int, vehicle: str = "V1") -> CrewInterval:
    return CrewInterval(event, "1", vehicle, person, "RIGGER", "", "DAY_SHIFT", D, t(start), t(end))


def drive(event: str, driver: str, start: int, end: int, vehicle: str = "V1") -> Interval:
    return Interval(event, "1", vehicle, driver, "DAY_SHIFT", D, t(start), t(end))


PERSONNEL = [{"personnel_id": "P1", "driver_id": "DRV-1"}, {"personnel_id": "P2", "driver_id": ""},
             {"personnel_id": "P3", "driver_id": "DRV-AMB"}, {"personnel_id": "P4", "driver_id": "DRV-AMB"}]


def conflicts(e2, crews):
    ids = driver_identities(PERSONNEL, {i.driver_id for i in e2})
    return find_person_conflicts(person_intervals(e2, crews, ids))


def test_identities() -> None:
    ids = driver_identities(PERSONNEL, {"DRV-1", "DRV-NONE", "DRV-AMB"})
    assert (ids["DRV-1"].status, ids["DRV-1"].personnel_id) == ("LINKED", "P1")
    assert ids["DRV-NONE"].status == "UNLINKED"
    assert (ids["DRV-AMB"].status, ids["DRV-AMB"].candidates) == ("AMBIGUOUS", ("P3", "P4"))


def test_same_person_two_crews_across_vehicles_conflicts() -> None:
    (c,) = conflicts([], [crew("C1", "P2", 8, 12, "V1"), crew("C2", "P2", 11, 15, "V2")])
    assert c.code == CODE_RESOURCE_CONFLICT


def test_different_people_and_touching_intervals_do_not_conflict() -> None:
    assert conflicts([], [crew("C1", "P2", 8, 12), crew("C2", "P5", 8, 12)]) == []
    items = person_intervals([], [crew("C1", "P2", 8, 12), crew("C2", "P2", 12, 16)], {})
    assert find_person_conflicts(items) == []
    (pair,) = person_adjacency(items)  # the non-blocking rest warning
    assert {pair[0].event_id, pair[1].event_id} == {"C1", "C2"}


def test_crew_versus_linked_driver_is_the_same_person() -> None:
    (c,) = conflicts([drive("E1", "DRV-1", 8, 16)], [crew("C1", "P1", 10, 12, "V2")])
    assert c.code == CODE_RESOURCE_CONFLICT
    assert conflicts([drive("E1", "DRV-1", 8, 16)], [crew("C1", "P2", 10, 12)]) == []  # a different person


def test_unlinked_or_ambiguous_driver_overlapping_any_crew_is_unverified() -> None:
    (c,) = conflicts([drive("E1", "DRV-NONE", 8, 16)], [crew("C1", "P2", 10, 12)])
    assert c.code == CODE_IDENTITY_UNVERIFIED
    (c,) = conflicts([drive("E1", "DRV-AMB", 8, 16)], [crew("C1", "P2", 10, 12)])
    assert c.code == CODE_IDENTITY_UNVERIFIED


def test_unlinked_driver_not_overlapping_is_allowed_interval_scoped() -> None:
    assert conflicts([drive("E1", "DRV-NONE", 8, 10)], [crew("C1", "P2", 10, 12)]) == []


def test_e2_pairs_are_left_to_the_e2_axes() -> None:
    assert conflicts([drive("E1", "DRV-1", 8, 16), drive("E2", "DRV-1", 9, 10, "V2")], []) == []


def test_only_new_or_worsened_conflicts_are_refused() -> None:
    before = conflicts([], [crew("C1", "P2", 8, 12), crew("C2", "P2", 10, 14)])
    after = conflicts([], [crew("C1", "P2", 8, 12), crew("C2", "P2", 10, 14), crew("C3", "P5", 8, 9)])
    assert new_conflicts(before, after, touched={"C3"}, new_events={"C3"}) == []  # residual pair untouched
    assert new_conflicts(before, after, touched={"C1"}, new_events=set()) == []  # a residual not worsened
    after_new = conflicts([], [crew("C1", "P2", 8, 12), crew("C2", "P2", 10, 14), crew("C4", "P2", 9, 9 + 1)])
    refused = new_conflicts(before, after_new, touched={"C4"}, new_events={"C4"})
    assert refused and all("C4" in (c.first.event_id, c.second.event_id) for c in refused)
