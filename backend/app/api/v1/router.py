from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.alerts import router as alerts_router
from app.api.v1.daily_summaries import router as daily_summaries_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.department_lifecycle_routes import router as department_lifecycle_routes_router
from app.api.v1.department_routes import router as department_routes_router
from app.api.v1.drivers import router as drivers_router
from app.api.v1.equipment import router as equipment_router
from app.api.v1.equipment_branch_routes import router as equipment_branch_routes_router
from app.api.v1.equipment_branch_write_routes import router as equipment_branch_write_routes_router
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
from app.api.v1.personnel_lifecycle_routes import router as personnel_lifecycle_routes_router
from app.api.v1.personnel_account_link_routes import router as personnel_account_link_routes_router
from app.api.v1.personnel_driver_link_routes import router as personnel_driver_link_routes_router
from app.api.v1.crane_driver_responsibility_routes import router as crane_driver_responsibility_routes_router
from app.api.v1.equipment_caretaker_routes import router as equipment_caretaker_routes_router
from app.api.v1.personnel_routes import router as personnel_routes_router
from app.api.v1.personnel_technician_link_routes import router as personnel_technician_link_routes_router
from app.api.v1.pm import router as pm_router
from app.api.v1.reference_data import router as reference_data_router
from app.api.v1.registry_routes import router as registry_routes_router
from app.api.v1.registration_routes import router as registration_routes_router
from app.api.v1.relationship_routes import router as relationship_routes_router
from app.api.v1.branch_routes import router as branch_routes_router
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
# Phase 7 Batch 7O2a: read-only registry reference lists and histories.
api_v1_router.include_router(reference_data_router)
api_v1_router.include_router(registry_routes_router)
api_v1_router.include_router(registration_routes_router)
api_v1_router.include_router(branch_routes_router)
# R2 Batch R2b: read-only equipment responsible-branch history.
api_v1_router.include_router(equipment_branch_routes_router)
# R2 Batch R2d: equipment responsible-branch writes (history-only).
api_v1_router.include_router(equipment_branch_write_routes_router)
# R2 Batch R2c-1: read-only personnel master.
api_v1_router.include_router(personnel_routes_router)
# R2 Batch R2c-2: read-only department master.
api_v1_router.include_router(department_routes_router)
# R2 Batch R2e: personnel / department lifecycle (deactivate, reactivate, reconcile, history).
api_v1_router.include_router(personnel_lifecycle_routes_router)
api_v1_router.include_router(department_lifecycle_routes_router)
# R2 Batch R2f-a: read-only technician master and relationship resolution.
api_v1_router.include_router(relationship_routes_router)
# R2 Batch R2f-b: Personnel ↔ Technician link writes (link / unlink / relink / reconcile / history).
api_v1_router.include_router(personnel_technician_link_routes_router)
# R2 Batch R2f-c: Personnel ↔ User Account link writes (link / unlink / relink / reconcile / history).
api_v1_router.include_router(personnel_account_link_routes_router)
# R2 Batch R2f-e: Personnel ↔ Driver identity link writes (link / unlink / relink / reconcile / history).
api_v1_router.include_router(personnel_driver_link_routes_router)
# R2 Batch R2f-d: Equipment ↔ Technician caretaker periods (history-only; current, events, reverse read).
api_v1_router.include_router(equipment_caretaker_routes_router)
# R2 Batch R2f-f: Crane / Vehicle ↔ Driver responsibility periods (history-only; current, events, reverse read).
api_v1_router.include_router(crane_driver_responsibility_routes_router)
