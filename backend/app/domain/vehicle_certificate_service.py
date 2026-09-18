"""Vehicle Certificate service (Web/API Phase 6 Batch 2A — create/list/get
only; see `app.domain.vehicle_certificate` module docstring for scope)."""
from __future__ import annotations

from datetime import date

from fastapi import status

from app.domain.common import utc_now
from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
from app.errors import ApiError
from app.repositories.base import Repository


class VehicleCertificateService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _require_vehicle_exists(self, vehicle_id: str) -> None:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def create_certificate(
        self,
        vehicle_id: str,
        certificate_type_code: str | None,
        certificate_type_name_th: str | None,
        document_no: str | None,
        issue_date: date | None,
        expiry_date: date | None,
        alert_lead_days: int | None,
        certificate_status: CertificateStatus | None,
        storage_ref: str | None,
        note_th: str | None,
        created_by_user_id: str | None,
    ) -> VehicleCertificate:
        """Batch 2A: a plain append — never touches any other row. No
        `replaced_by_certificate_id` is ever set here (deferred to
        Batch 2B)."""
        await self._require_vehicle_exists(vehicle_id)
        return await self._repository.create_vehicle_certificate(
            vehicle_id=vehicle_id,
            certificate_type_code=certificate_type_code,
            certificate_type_name_th=certificate_type_name_th,
            document_no=document_no,
            issue_date=issue_date,
            expiry_date=expiry_date,
            alert_lead_days=alert_lead_days,
            certificate_status=certificate_status,
            storage_ref=storage_ref,
            note_th=note_th,
            created_by_user_id=created_by_user_id,
            created_at=utc_now(),
        )

    async def get_certificate(self, certificate_id: str) -> VehicleCertificate:
        certificate = await self._repository.get_vehicle_certificate(certificate_id)
        if certificate is None:
            raise ApiError(
                code="VEHICLE_CERTIFICATE_NOT_FOUND",
                message=f"Vehicle certificate '{certificate_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return certificate

    async def list_for_vehicle(self, vehicle_id: str) -> list[VehicleCertificate]:
        await self._require_vehicle_exists(vehicle_id)
        return await self._repository.list_vehicle_certificates_for_vehicle(vehicle_id)


__all__ = ["VehicleCertificateService"]
