"""R8 early workstream — person-level resource conflict across E2 driver
assignments and crew assignments (pure; no I/O).

Governance: Master Roadmap 2026-11-11 R8 addendum ("reject overlapping
assignments for the same person across all vehicles and roles; fail closed on
unknown/ambiguous cross-role identity, never silently treat missing link as no
conflict"); DEC-R8-CREW-CALENDAR-20261111; R8 Owner source approval 2026-11-18
OD-2 = A.

Identity of an E2 interval: the ONE in-scope Personnel whose `driver_id` equals
the E2 driver (the R2f-e Personnel <-> Driver link, 0..1 <-> 0..1). Zero such
Personnel -> UNLINKED; more than one -> AMBIGUOUS. A crew interval is always
keyed by its `personnel_id`.

Rules (half-open intervals; touching is not overlap):
- crew x crew, same personnel_id, different events          -> RESOURCE_CONFLICT
- crew(P) x E2 interval whose driver is LINKED to P          -> RESOURCE_CONFLICT
- crew(any) x E2 interval whose driver is UNLINKED/AMBIGUOUS -> CROSS_ROLE_IDENTITY_UNVERIFIED
  (OD-2 = A: interval-scoped — only where they actually overlap in time)
- E2 x E2 pairs are NOT judged here: the unchanged E2 driver and vehicle axes
  already own them, so E2 behaviour without overlapping crew is identical.
The vehicle axis does not apply to crew (crew members are not operators).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.crew_assignment_timeline import CrewInterval
from app.domain.operational_driver_timeline import Interval
from app.domain.registration import text

IDENTITY_LINKED = "LINKED"
IDENTITY_UNLINKED = "UNLINKED"
IDENTITY_AMBIGUOUS = "AMBIGUOUS"

KIND_DRIVER = "DRIVER"
KIND_CREW = "CREW"

CODE_RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
CODE_IDENTITY_UNVERIFIED = "CROSS_ROLE_IDENTITY_UNVERIFIED"
W_PERSON_ADJACENT = "PERSON_ADJACENT_ASSIGNMENT_REST_WARNING"


@dataclass(frozen=True)
class DriverIdentity:
    status: str  # LINKED | UNLINKED | AMBIGUOUS
    personnel_id: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonInterval:
    kind: str  # DRIVER | CREW
    event_id: str
    revision_no: str
    vehicle_id: str
    personnel_id: str | None  # None for an UNLINKED / AMBIGUOUS driver
    driver_id: str | None
    identity: str  # LINKED | UNLINKED | AMBIGUOUS (CREW intervals are LINKED by definition)
    role: str  # DRIVER, or the crew role code
    role_note_th: str
    mode: str
    label_date: date
    start: datetime
    end: datetime


@dataclass(frozen=True)
class PersonConflict:
    code: str
    first: PersonInterval
    second: PersonInterval


def driver_identities(personnel_rows: Iterable[Mapping[str, object]],
                      driver_ids: Iterable[str]) -> dict[str, DriverIdentity]:
    """The identity of each driver from the IN-SCOPE personnel rows (the caller
    passes `scoped_personnel(...)`, which already fails closed on bad flags)."""
    holders: dict[str, list[str]] = {}
    for row in personnel_rows:
        driver_id = text(row.get("driver_id"))
        if driver_id:
            holders.setdefault(driver_id, []).append(text(row.get("personnel_id")))
    out: dict[str, DriverIdentity] = {}
    for driver_id in set(driver_ids):
        found = sorted(holders.get(driver_id, []))
        if len(found) == 1:
            out[driver_id] = DriverIdentity(IDENTITY_LINKED, found[0], tuple(found))
        elif not found:
            out[driver_id] = DriverIdentity(IDENTITY_UNLINKED)
        else:
            out[driver_id] = DriverIdentity(IDENTITY_AMBIGUOUS, None, tuple(found))
    return out


def from_driver(i: Interval, identity: DriverIdentity) -> PersonInterval:
    return PersonInterval(KIND_DRIVER, i.event_id, i.revision_no, i.vehicle_id, identity.personnel_id, i.driver_id,
                          identity.status, "DRIVER", "", i.mode, i.label_date, i.start, i.end)


def from_crew(i: CrewInterval) -> PersonInterval:
    return PersonInterval(KIND_CREW, i.event_id, i.revision_no, i.vehicle_id, i.personnel_id, None,
                          IDENTITY_LINKED, i.role, i.role_note_th, i.mode, i.label_date, i.start, i.end)


def person_intervals(e2: Sequence[Interval], crew: Sequence[CrewInterval],
                     identities: Mapping[str, DriverIdentity]) -> list[PersonInterval]:
    out = [from_driver(i, identities.get(i.driver_id, DriverIdentity(IDENTITY_UNLINKED))) for i in e2]
    out += [from_crew(i) for i in crew]
    out.sort(key=lambda p: (p.start, p.end, p.kind, p.event_id))
    return out


def _judge(a: PersonInterval, b: PersonInterval) -> str | None:
    """The code of an overlapping pair of different events (None = allowed)."""
    if a.kind == KIND_DRIVER and b.kind == KIND_DRIVER:
        return None  # owned by the unchanged E2 axes
    if a.kind == KIND_CREW and b.kind == KIND_CREW:
        return CODE_RESOURCE_CONFLICT if a.personnel_id == b.personnel_id else None
    crew, driver = (a, b) if a.kind == KIND_CREW else (b, a)
    if driver.identity == IDENTITY_LINKED:
        return CODE_RESOURCE_CONFLICT if driver.personnel_id == crew.personnel_id else None
    return CODE_IDENTITY_UNVERIFIED  # never "no conflict" on doubt


def find_person_conflicts(intervals: Sequence[PersonInterval]) -> list[PersonConflict]:
    """Every overlapping pair that the rules above refuse (sweep by start)."""
    items = sorted(intervals, key=lambda p: (p.start, p.end, p.kind, p.event_id))
    out: list[PersonConflict] = []
    for n, a in enumerate(items):
        for b in items[n + 1:]:
            if b.start >= a.end:
                break
            if a.event_id == b.event_id:
                continue
            code = _judge(a, b)
            if code is not None:
                out.append(PersonConflict(code, a, b))
    return out


def person_adjacency(intervals: Sequence[PersonInterval]) -> list[tuple[PersonInterval, PersonInterval]]:
    """Same verified person, different events, one ending exactly when the other
    starts, at least one of them crew (the non-blocking rest/fitness warning, as
    A2-4.2 for drivers; saving is never a safety clearance)."""
    by_start: dict[datetime, list[PersonInterval]] = {}
    for p in intervals:
        by_start.setdefault(p.start, []).append(p)
    out: list[tuple[PersonInterval, PersonInterval]] = []
    for a in intervals:
        for b in by_start.get(a.end, []):
            if a.event_id == b.event_id or KIND_CREW not in (a.kind, b.kind):
                continue
            if a.personnel_id is not None and a.personnel_id == b.personnel_id:
                out.append((a, b))
    return out


def new_conflicts(before: Sequence[PersonConflict], after: Sequence[PersonConflict], touched: set[str],
                  new_events: set[str]) -> list[PersonConflict]:
    """The conflicts a change creates or worsens: involving a touched event, and
    not a residual pair (same events, same code) that existed before between
    events this change did not create (mirrors the E2 commit rule)."""
    residual = {(c.code, frozenset((c.first.event_id, c.second.event_id))) for c in before}
    out: list[PersonConflict] = []
    for c in after:
        pair = frozenset((c.first.event_id, c.second.event_id))
        if not (pair & touched):
            continue
        if (c.code, pair) in residual and not (pair & new_events):
            continue
        out.append(c)
    return out


__all__ = [
    "CODE_IDENTITY_UNVERIFIED",
    "CODE_RESOURCE_CONFLICT",
    "IDENTITY_AMBIGUOUS",
    "IDENTITY_LINKED",
    "IDENTITY_UNLINKED",
    "KIND_CREW",
    "KIND_DRIVER",
    "W_PERSON_ADJACENT",
    "DriverIdentity",
    "PersonConflict",
    "PersonInterval",
    "driver_identities",
    "find_person_conflicts",
    "new_conflicts",
    "person_adjacency",
    "person_intervals",
]
