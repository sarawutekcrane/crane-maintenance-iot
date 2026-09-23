from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.alerts import router as alerts_router
from app.api.v1.daily_summaries import router as daily_summaries_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.drivers import router as drivers_router
from app.api.v1.equipment import router as equipment_router
from app.api.v1.health import router as health_router
from app.api.v1.inspections import router as inspections_router
from app.api.v1.latest_locations import router as latest_locations_router
from app.api.v1.lifetime_rules import router as lifetime_rules_router
from app.api.v1.location_snapshots import router as location_snapshots_router
from app.api.v1.material_requests import router as material_requests_router
from app.api.v1.me import router as me_router
from app.api.v1.meter import router as meter_router
from app.api.v1.model_documents import router as model_documents_router
from app.api.v1.part_instances import router as part_instances_router
from app.api.v1.parts import router as parts_router
from app.api.v1.pm import router as pm_router
from app.api.v1.position_lifetime import router as position_lifetime_router
from app.api.v1.repair_requests import router as repair_requests_router
from app.api.v1.repairs import router as repairs_router
from app.api.v1.reports import router as reports_router
from app.api.v1.vehicle_certificates import router as vehicle_certificates_router
from app.api.v1.vehicle_events import router as vehicle_events_router
from app.api.v1.vehicles import router as vehicles_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(me_router)
api_v1_router.include_router(vehicles_router)
api_v1_router.include_router(equipment_router)
api_v1_router.include_router(inspections_router)
api_v1_router.include_router(meter_router)
api_v1_router.include_router(pm_router)
api_v1_router.include_router(repairs_router)
api_v1_router.include_router(repair_requests_router)
api_v1_router.include_router(parts_router)
api_v1_router.include_router(part_instances_router)
api_v1_router.include_router(position_lifetime_router)
api_v1_router.include_router(lifetime_rules_router)
api_v1_router.include_router(material_requests_router)
api_v1_router.include_router(location_snapshots_router)
api_v1_router.include_router(latest_locations_router)
api_v1_router.include_router(drivers_router)
api_v1_router.include_router(vehicle_certificates_router)
api_v1_router.include_router(model_documents_router)
api_v1_router.include_router(vehicle_events_router)
api_v1_router.include_router(daily_summaries_router)
api_v1_router.include_router(alerts_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(reports_router)
