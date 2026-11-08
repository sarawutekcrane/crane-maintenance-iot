"""HTTP test support for the Technician V2 assignment on the app's own Mock seed.

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107: the Legacy assignment runtime is
cancelled, so tests that need an assigned job assign it through the V2 route.
The Mock seed links USR-TEST-911 -> TEC-TEST-911 and USR-TEST-912 ->
TEC-TEST-912 (TEST batch); no other user resolves to a technician."""
from __future__ import annotations

import uuid

from httpx import AsyncClient

SEED_TECHNICIAN = {"USR-TEST-911": "TEC-TEST-911", "USR-TEST-912": "TEC-TEST-912"}
PRIMARY_USER, COLLABORATOR_USER = "USR-TEST-911", "USR-TEST-912"


def headers(role: str, user_id: str = "dev-user", *, request_id: bool = False) -> dict[str, str]:
    out = {"X-Dev-Role": role, "X-Dev-User-Id": user_id}
    if request_id:
        out["X-Request-Id"] = str(uuid.uuid4())
    return out


async def assign_v2(client: AsyncClient, kind_path: str, job_id: str, primary_user: str,
                    collaborator_users: tuple[str, ...] | list[str] = ()) -> dict:
    """Write a V2 set (compare-and-set on the current one) as MAINTENANCE; returns the response body."""
    path = f"/api/v1/{kind_path}/{job_id}/technician-assignments"
    current = (await client.get(path, headers=headers("MAINTENANCE"))).json().get("current")
    expected = None if not current else {"primary_technician_id": current["primary_technician_id"],
                                         "collaborator_technician_ids": current["collaborator_technician_ids"]}
    response = await client.post(path, json={
        "primary_technician_id": SEED_TECHNICIAN[primary_user],
        "collaborator_technician_ids": [SEED_TECHNICIAN[user] for user in collaborator_users],
        "expected_current": expected}, headers=headers("MAINTENANCE", request_id=True))
    assert response.status_code == 200, response.text
    return response.json()


async def start_pm(client: AsyncClient, work_order_id: str, primary_user: str = PRIMARY_USER) -> None:
    response = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/start",
                                 headers=headers("TECHNICIAN", primary_user, request_id=True))
    assert response.status_code == 200, response.text


async def save_pm_item(client: AsyncClient, work_order_id: str, task_id: str, user: str, *,
                       role: str = "TECHNICIAN"):
    return await client.post(f"/api/v1/pm/work-orders/{work_order_id}/items/{task_id}/outcome",
                             json={"disposition": "PERFORMED", "performed_actions": ["ตรวจเช็ค"]},
                             headers=headers(role, user, request_id=True))
