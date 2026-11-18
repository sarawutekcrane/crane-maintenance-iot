"""R8 early workstream — Resource Calendar read model (read-only, Mock/TEST).

Governance: Master Roadmap 2026-11-11 R8 addendum ("Calendar is primary
visualization. User can switch VEHICLES / PERSONNEL / BOTH and click a day to
inspect assignment details including each person and their own start/end times,
vehicle, role and corresponding work period"); R8 Owner source approval
2026-11-18 (OD-7 = A: the fleet-wide read needs a trusted actor holding
can_assign_crane_driver or can_assign_crane_crew — checked at the route).

One read of both streams (`CrewAssignmentService.read_resources`) for a bounded
window of at most 42 Bangkok calendar days. Every in-scope E2 driver interval,
crew interval and E2 UNKNOWN span overlapping the window is returned with its
person identity and status:
- VALID, CONFLICTED (a person-axis RESOURCE_CONFLICT, or an E2 axis conflict),
  IDENTITY_UNVERIFIED (an unlinked/ambiguous driver overlapping crew),
- UNKNOWN for an E2 elapsed span whose assignee cannot be stated.
Nothing is filled, guessed or resolved: an empty day means no recorded
assignment, not a verified free person. Names are the public personnel name
(and, for an unlinked driver, the Driver Master display name) only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import status

from app.domain.common import PageParams
from app.domain.crew_assignment import CrewAssignmentService, ResourceRead
from app.domain.operational_driver_timeline import bangkok, bangkok_date
from app.domain.personnel_resource_conflict import (
    CODE_IDENTITY_UNVERIFIED,
    IDENTITY_LINKED,
    KIND_CREW,
    KIND_DRIVER,
    PersonConflict,
    PersonInterval,
)
from app.domain.registry_write_support import error, require_write_context
from app.domain.vehicle_service import VehicleService, vehicle_master_read_error
from app.repositories.base import Repository, RepositoryError

MAX_WINDOW_DAYS = 42
VIEWS = ("VEHICLES", "PERSONNEL", "BOTH")


@dataclass(frozen=True)
class CalendarEntry:
    kind: str  # DRIVER | CREW | UNKNOWN
    event_id: str
    vehicle_id: str
    machine_no: str | None
    personnel_id: str | None
    personnel_name: str | None
    driver_id: str | None
    driver_name: str | None
    identity: str | None
    role: str | None
    role_note_th: str | None
    mode: str | None
    label_date: date
    start: object
    end: object
    status: str


@dataclass(frozen=True)
class ResourceCalendar:
    view: str
    date_from: date
    date_to: date
    entries: tuple[CalendarEntry, ...]
    conflicts: tuple[PersonConflict, ...]


def window_error(message: str, field: str):
    return error("CALENDAR_WINDOW_INVALID", message, status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": field})


class ResourceCalendarService:
    def __init__(self, repository: Repository, crew: CrewAssignmentService, data_context: str | None,
                 test_batch_id: str) -> None:
        self._repository = repository
        self._crew = crew
        self._context = data_context
        self._batch_id = test_batch_id

    async def _vehicle_rows(self, branch_id: str | None) -> dict[str, str]:
        """vehicle_id -> machine_no of the validated vehicle master (the SAME gates and
        exact branch predicate as GET /vehicles; one invalid record fails closed)."""
        service = VehicleService(self._repository)
        out: dict[str, str] = {}
        number = 1
        while True:
            try:
                page = await service.list_vehicles_with_registry(None, None, None,
                                                                 PageParams(page=number, page_size=200), branch_id)
            except RepositoryError as exc:
                raise vehicle_master_read_error(exc) from exc
            out.update({e.vehicle.vehicle_id: e.vehicle.machine_no for e in page.items})
            if number * 200 >= page.total_items:
                return out
            number += 1

    async def _driver_names(self, driver_ids: set[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        for driver_id in sorted(driver_ids):
            driver = await self._repository.get_driver(driver_id)
            if driver is not None and driver.driver_name_th:
                names[driver_id] = driver.driver_name_th  # display name only: no phone / licence
        return names

    async def calendar(self, *, date_from: date, date_to: date, view: str, vehicle_id: str | None = None,
                       personnel_id: str | None = None, branch_id: str | None = None) -> ResourceCalendar:
        if date_to < date_from:
            raise window_error("to must not be before from", "to")
        if (date_to - date_from).days + 1 > MAX_WINDOW_DAYS:
            raise window_error(f"The calendar window is at most {MAX_WINDOW_DAYS} days", "to")
        if view not in VIEWS:
            raise window_error("view must be VEHICLES, PERSONNEL or BOTH", "view")
        self._crew._require_mock()  # noqa: SLF001 - the same Mock/TEST-only rule as the crew service
        context = require_write_context(self._context, self._batch_id)
        res: ResourceRead = await self._crew.read_resources(context)
        lo, hi = bangkok(date_from), bangkok(date_to + timedelta(1))
        vehicles = await self._vehicle_rows(branch_id)
        intervals, conflicts = self._crew.person_view(res)
        names = self._crew.names(res)
        axis_conflicted = {e for c in res.e2.conflicts for e in (c.first.event_id, c.second.event_id)}

        def keep(p_vehicle: str, p_person: str | None) -> bool:
            if branch_id is not None and p_vehicle not in vehicles:
                return False  # outside the branch filter (a branch cannot be proven for it)
            # Without a branch filter an interval whose vehicle has no master record is still
            # shown (machine_no null): hiding it would be a false "free" day.
            if vehicle_id is not None and p_vehicle != vehicle_id:
                return False
            if personnel_id is not None and p_person != personnel_id:
                return False
            return True

        visible: list[PersonInterval] = [p for p in intervals if p.end > lo and p.start < hi
                                         and keep(p.vehicle_id, p.personnel_id)]
        unlinked = {p.driver_id for p in visible if p.kind == KIND_DRIVER and p.identity != IDENTITY_LINKED
                    and p.driver_id}
        driver_names = await self._driver_names(unlinked)
        entries: list[CalendarEntry] = []
        for p in visible:
            status_value = self._crew.status_of(p.event_id, conflicts)
            if status_value == "VALID" and p.event_id in axis_conflicted:
                status_value = "CONFLICTED"
            entries.append(CalendarEntry(
                kind=p.kind, event_id=p.event_id, vehicle_id=p.vehicle_id, machine_no=vehicles.get(p.vehicle_id),
                personnel_id=p.personnel_id, personnel_name=names.get(p.personnel_id or ""),
                driver_id=p.driver_id, driver_name=driver_names.get(p.driver_id or "") if p.kind == KIND_DRIVER
                and p.identity != IDENTITY_LINKED else None,
                identity=p.identity if p.kind == KIND_DRIVER else IDENTITY_LINKED,
                role=p.role, role_note_th=p.role_note_th or None, mode=p.mode, label_date=p.label_date,
                start=p.start, end=p.end, status=status_value))
        if view != "PERSONNEL" and personnel_id is None:
            for v, start, end, _handover in res.e2.unknown:
                if end > lo and start < hi and keep(v, None):
                    entries.append(CalendarEntry(
                        kind="UNKNOWN", event_id=_handover, vehicle_id=v, machine_no=vehicles.get(v),
                        personnel_id=None, personnel_name=None, driver_id=None, driver_name=None, identity=None,
                        role=None, role_note_th=None, mode=None, label_date=bangkok_date(start), start=start,
                        end=end, status="UNKNOWN"))
        entries.sort(key=lambda e: (e.start, e.vehicle_id, e.kind, e.event_id))
        shown = {e.event_id for e in entries}
        window_conflicts = tuple(c for c in conflicts if c.first.event_id in shown or c.second.event_id in shown)
        return ResourceCalendar(view, date_from, date_to, tuple(entries), window_conflicts)


__all__ = ["CODE_IDENTITY_UNVERIFIED", "KIND_CREW", "MAX_WINDOW_DAYS", "VIEWS", "CalendarEntry", "ResourceCalendar",
           "ResourceCalendarService"]
