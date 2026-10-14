"""R2 Batch R2f-h4 B6 test support — seed LEGACY technician assignments.

The legacy assign routes and service methods are retired (410
LEGACY_ASSIGNMENT_RETIRED); the legacy assignment storage writer
(`Repository.assign_repair` / `assign_pm_work_order`) is retained, unreachable
from the API, so tests of the RETAINED legacy behaviour (legacy-history
recording / evidence authorization, close termination, history reads) can
still create exactly the rows the old route used to write.

R2 Batch R2f-h4 B6 Rev2 (owner final decision: Technician V2 only): no service
or route can create a LEGACY job any more. A historical LEGACY job (blank
`assignment_model` and scope flags — the shape stored rows may still have) is
therefore a TEST FIXTURE only: `seed_historical_legacy_repair` / `_pm` create
one through the repository with no V2 marker, and `legacy_assign` gives a
freshly created synthetic job that historical marker in the mock store before
seeding its legacy rows. Nothing here is reachable from the application.
"""
from __future__ import annotations

from collections.abc import Iterable

HISTORICAL_LEGACY_MARKER = {"assignment_model": "", "is_test_data": "", "test_batch_id": ""}


async def seed_historical_legacy_repair(repo, *, asset_id: str = "VEH-1046", opened_by: str = "dev-user") -> str:
    """A historical LEGACY Repair (fixture only): the repository create with NO V2 marker."""
    from app.domain.asset import AssetType
    from app.domain.repair import RepairSourceType

    repair = await repo.create_repair(asset_type=AssetType.VEHICLE, asset_id=asset_id,
                                      source_type=RepairSourceType.MANUAL, source_id=None, category=None,
                                      symptom=None, meter_snapshot_id=None, opened_by=opened_by)
    assert repair.assignment_model == ""
    return repair.repair_id


async def seed_historical_legacy_pm(repo, *, asset_id: str = "VEH-1046", opened_by: str = "dev-user") -> str:
    """A historical LEGACY PM work order (fixture only): the repository create with NO V2 marker."""
    from app.domain.asset import AssetType
    from app.domain.meter_service import MeterService
    from app.domain.pm_service import PmService

    status = (await PmService(repo, MeterService(repo)).list_applicable_plan_status(AssetType.VEHICLE, asset_id))[0]
    work_order = await repo.create_pm_work_order(asset_type=AssetType.VEHICLE, asset_id=asset_id,
                                                 pm_plan_id=status.plan.pm_plan_id,
                                                 revision_id=status.active_revision.revision_id, due_reason=None,
                                                 opened_by=opened_by, note=None)
    assert work_order.assignment_model == ""
    return work_order.pm_work_order_id


def mark_historical_legacy(kind: str, job_id: str, *, repo=None) -> None:
    """Give a synthetic mock job the historical LEGACY marker (fixture only). Refused when the job already
    has V2 assignment rows: an assigned V2 job is never re-labelled."""
    repo = repo or app_repository()
    store = repo._repairs if kind == "repairs" else repo._pm_work_orders
    key = "REPAIR" if kind == "repairs" else "PM"
    column = "repair_id" if kind == "repairs" else "pm_work_order_id"
    assert not [r for r in repo._technician_assignment_rows[key] if r.get(column) == job_id], job_id
    store[job_id] = store[job_id].model_copy(update=HISTORICAL_LEGACY_MARKER)


def app_repository():
    """The repository instance the default test app (`client` fixture) uses."""
    from app.dependencies import get_repository

    return get_repository()


async def seed_legacy_repair_assignment(repair_id: str, primary: str | None, collaborators: Iterable[str] = (), *,
                                        repo=None, assigned_by: str = "dev-user") -> None:
    await (repo or app_repository()).assign_repair(repair_id=repair_id, primary_technician=primary,
                                                   collaborators=list(collaborators), assigned_by=assigned_by)


async def seed_legacy_pm_assignment(pm_work_order_id: str, primary: str | None, collaborators: Iterable[str] = (), *,
                                    repo=None, assigned_by: str = "dev-user") -> None:
    await (repo or app_repository()).assign_pm_work_order(pm_work_order_id=pm_work_order_id,
                                                          primary_technician=primary,
                                                          collaborators=list(collaborators), assigned_by=assigned_by)


async def legacy_assign(client, path: str, json: dict | None = None, headers: dict | None = None):
    """Drop-in for the retired `client.post("/api/v1/{repairs|pm/work-orders}/{id}/assign", json=...)` test
    fixture call: the same legacy rows are seeded through the retained storage writer, and the job's GET detail
    — exactly the response model the retired route returned — is returned. (The retired route's own
    capability check is no longer exercised: the route answers 410, see test_v2_policy_batch_r2f_h4_b6.)"""
    import re

    match = re.fullmatch(r"/api/v1/(repairs|pm/work-orders)/([^/]+)/assign", path)
    assert match, f"not a legacy assign path: {path}"
    kind, job_id = match.groups()
    payload = json or {}
    mark_historical_legacy(kind, job_id)  # B6 Rev2: the job the retired route served was a LEGACY job
    seed = seed_legacy_repair_assignment if kind == "repairs" else seed_legacy_pm_assignment
    await seed(job_id, payload.get("primary_technician"), payload.get("collaborators") or [])
    return await client.get(f"/api/v1/{kind}/{job_id}", headers=headers or {})


class _QueueResponse:
    status_code = 200

    def __init__(self, body: dict) -> None:
        self._body = body

    def json(self) -> dict:
        return self._body


async def legacy_queue_page(path: str, *, repo=None, user: str | None = "dev-user", page: int = 1,
                            page_size: int = 50) -> dict:
    """The retired legacy queue `path`, answered by the RETAINED shared repository filters
    (`list_repairs` / `list_pm_work_orders` with `assigned_to` / `unassigned_only`) — the exact derivation
    the retired routes delegated to, so the tests of "membership follows ACTIVE legacy history" keep running
    against the code that still exists. The retired routes themselves answer 410."""
    from app.domain.common import PageParams
    from app.domain.pm import PmWorkOrderStatus
    from app.domain.repair import RepairStatus

    repo = repo or app_repository()
    params = PageParams(page=page, page_size=page_size)
    path = path.removeprefix("/api/v1")
    if path == "/repairs/my-work":
        items, total = await repo.list_repairs(None, None, RepairStatus.OPEN, params, assigned_to=user)
    elif path == "/repairs/waiting-assignment":
        items, total = await repo.list_repairs(None, None, RepairStatus.OPEN, params, unassigned_only=True)
    elif path == "/pm/work-orders/my-work":
        items, total = await repo.list_pm_work_orders(None, None, params, status=PmWorkOrderStatus.OPEN,
                                                      assigned_to=user)
    else:
        raise AssertionError(f"not a retired legacy queue: {path}")
    return {"items": [i.model_dump(mode="json") for i in items], "page": page, "page_size": page_size,
            "total_items": total}


async def legacy_queue(client, path: str, headers: dict | None = None, params: dict | None = None):
    """Drop-in for the retired `client.get(<legacy queue>, headers=...)` test call (see `legacy_queue_page`);
    the actor is the request's `X-Dev-User-Id` (DEV auth default `dev-user`)."""
    user = (headers or {}).get("X-Dev-User-Id", "dev-user")
    page = int((params or {}).get("page", 1))
    page_size = int((params or {}).get("page_size", 50))
    return _QueueResponse(await legacy_queue_page(path, user=user, page=page, page_size=page_size))
