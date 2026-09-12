from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.equipment import router as equipment_router
from app.api.v1.health import router as health_router
from app.api.v1.inspections import router as inspections_router
from app.api.v1.vehicles import router as vehicles_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(vehicles_router)
api_v1_router.include_router(equipment_router)
api_v1_router.include_router(inspections_router)
