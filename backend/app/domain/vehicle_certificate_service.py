"""Vehicle Certificate service (Web/API Phase 6 Batch 2A create/list/get +
Batch 2B renewal/REPLACED/EXPIRED lifecycle; see
`app.domain.vehicle_certificate` module docstring for scope)."""
from __future__ import annotations

from datetime import date

from fastapi import status

from app.domain.common import bangkok_today, utc_now
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

    # ---- Expiry reconciliation (Web/API Phase 6 Batch 2B) ----

    async def _reconcile_expiry(self, certificate: VehicleCertificate) -> VehicleCertificate:
        """Idempotent, backend-authoritative ACTIVE -> EXPIRED transition
        (B2B-4/B2B-5). Never touches REPLACED, already-EXPIRED, or
        null-status rows — only a currently-ACTIVE row with a non-null
        `expiry_date` strictly before today's Bangkok calendar date
        (`expiry_date == today` stays ACTIVE) is mutated, and then only
        once (re-running this against an already-EXPIRED result is a
        pure no-op). No scheduler/background worker exists — this is
        invoked inline by every read/write path below that needs an
        up-to-date status (get, list, ordinary create's exclusivity
        check, renewal eligibility) so a stale raw Sheet row can never
        keep blocking those checks merely because nothing has read it
        since it expired."""
        if certificate.certificate_status != CertificateStatus.ACTIVE:
            return certificate
        if certificate.expiry_date is None:
            return certificate
        if certificate.expiry_date >= bangkok_today():
            return certificate
        return await self._repository.mark_vehicle_certificate_expired(certificate.certificate_id)

    async def _list_and_reconcile(self, vehicle_id: str) -> list[VehicleCertificate]:
        certificates = await self._repository.list_vehicle_certificates_for_vehicle(vehicle_id)
        return [await self._reconcile_expiry(c) for c in certificates]

    # ---- Create (Batch 2A, + Batch 2B ACTIVE-exclusivity guard) ----

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
        `replaced_by_certificate_id` is ever set here.

        Batch 2B (the one approved change to this method's behavior,
        B2B-3/section 6): when `certificate_status == ACTIVE`, this now
        rejects the create with `422 VEHICLE_CERTIFICATE_ACTIVE_ALREADY_
        EXISTS` if an ACTIVE certificate already exists for the same
        `vehicle_id + certificate_type_code` (reconciling expiry first,
        so a stale expired-but-unread row never wrongly blocks this).
        Creating `REPLACED`/`EXPIRED`/`None` status is unaffected."""
        await self._require_vehicle_exists(vehicle_id)
        if certificate_status == CertificateStatus.ACTIVE:
            existing = await self._list_and_reconcile(vehicle_id)
            if any(
                c.certificate_type_code == certificate_type_code
                and c.certificate_status == CertificateStatus.ACTIVE
                for c in existing
            ):
                raise ApiError(
                    code="VEHICLE_CERTIFICATE_ACTIVE_ALREADY_EXISTS",
                    message=(
                        f"Vehicle '{vehicle_id}' already has an ACTIVE certificate for "
                        f"certificate_type_code={certificate_type_code!r}"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        return await self._append_certificate(
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
        )

    async def _append_certificate(
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
        """Shared unconditional append, used by both `create_certificate`
        (after its exclusivity check above) and `renew_certificate`
        below. Renewal's internal create step MUST use this rather than
        `create_certificate` itself — going through the public method
        would re-run the ACTIVE-exclusivity guard while the certificate
        being renewed is still ACTIVE (write 2 hasn't run yet), which
        would always self-reject the very operation meant to produce
        that transient state (see the Batch 2B audit, section 6/11)."""
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

    # ---- Get / List (Batch 2A, + Batch 2B read-time reconciliation) ----

    async def get_certificate(self, certificate_id: str) -> VehicleCertificate:
        certificate = await self._repository.get_vehicle_certificate(certificate_id)
        if certificate is None:
            raise ApiError(
                code="VEHICLE_CERTIFICATE_NOT_FOUND",
                message=f"Vehicle certificate '{certificate_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return await self._reconcile_expiry(certificate)

    async def list_for_vehicle(self, vehicle_id: str) -> list[VehicleCertificate]:
        await self._require_vehicle_exists(vehicle_id)
        return await self._list_and_reconcile(vehicle_id)

    # ---- Renewal (Web/API Phase 6 Batch 2B) ----

    async def renew_certificate(
        self,
        certificate_id: str,
        certificate_type_name_th: str | None,
        document_no: str | None,
        issue_date: date | None,
        expiry_date: date | None,
        alert_lead_days: int | None,
        storage_ref: str | None,
        note_th: str | None,
        created_by_user_id: str | None,
        fields_set: frozenset[str] = frozenset(),
    ) -> VehicleCertificate:
        """Renew an ACTIVE certificate (B2B-1/B2B-2): creates a brand new
        ACTIVE row (`vehicle_id`/`certificate_type_code` inherited from
        the source certificate unconditionally), then marks the source
        `REPLACED` with `replaced_by_certificate_id` pointing at the new
        row. The source row is never deleted or overwritten beyond that
        one status/link change (B2B-6).

        `certificate_type_name_th`/`alert_lead_days` have LOCKED
        three-way semantics (the same omission-vs-explicit-null
        distinction Batch 1's PATCH /drivers/{id} fix established):
        omitted from the request -> inherit the source certificate's
        existing value; present with a non-null value -> use it; present
        as explicit JSON `null` -> the new certificate gets `None` for
        that field (never silently inherited). `fields_set` (the route's
        `body.model_fields_set`) is what makes "omitted" distinguishable
        from "explicit null" here, since both otherwise read as a plain
        `None` parameter value. Every other field
        (`document_no`/`issue_date`/`expiry_date`/`storage_ref`/
        `note_th`) is passed through exactly as given — `None` if
        omitted, never auto-copied, never computed — unaffected by this
        `fields_set` mechanism.

        Write ordering (B2B-8): the new row is created FIRST, the source
        is updated SECOND. If the second write fails, the state
        transiently has two ACTIVE rows for the same vehicle+type — an
        inconsistency, but a recoverable one: the new row is fully valid
        on its own and the source can still be linked to it later. The
        reverse order was rejected because a failure after only the
        first write would leave the vehicle with ZERO active
        certificates for that type plus a source row already pointing at
        a certificate_id that doesn't exist yet — a worse, harder-to-spot
        failure mode.

        This method does NOT provide true atomicity (Google Sheets has
        none) and does NOT add a transaction/idempotency-key framework.
        See the completed-retry and corruption-guard checks below for
        the two safeguards it does provide, and their documented limits."""
        source = await self._repository.get_vehicle_certificate(certificate_id)
        if source is None:
            raise ApiError(
                code="VEHICLE_CERTIFICATE_NOT_FOUND",
                message=f"Vehicle certificate '{certificate_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        source = await self._reconcile_expiry(source)

        if source.certificate_status == CertificateStatus.REPLACED:
            # Completed-renewal retry (section 9.A): if this certificate
            # was already renewed (by an earlier, successful call, or an
            # earlier attempt that completed both writes), do not create
            # a second replacement — return the existing successor.
            # Anything inconsistent about that linkage is a corrupted
            # state this method refuses to silently paper over.
            successor_id = source.replaced_by_certificate_id
            successor = (
                await self._repository.get_vehicle_certificate(successor_id)
                if successor_id
                else None
            )
            if (
                successor is None
                or successor.vehicle_id != source.vehicle_id
                or successor.certificate_type_code != source.certificate_type_code
            ):
                raise ApiError(
                    code="VEHICLE_CERTIFICATE_ACTIVE_STATE_CONFLICT",
                    message=(
                        f"Vehicle certificate '{certificate_id}' is REPLACED but its "
                        "replaced_by_certificate_id linkage is missing or inconsistent; "
                        "this requires manual reconciliation."
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            return successor

        if source.certificate_status != CertificateStatus.ACTIVE:
            # EXPIRED or null status: renewal is only defined for ACTIVE
            # (B2B-2's own wording) — anything else is out of scope,
            # never silently renewed.
            raise ApiError(
                code="VEHICLE_CERTIFICATE_NOT_ACTIVE",
                message=(
                    f"Vehicle certificate '{certificate_id}' is not ACTIVE "
                    f"(current status: {source.certificate_status}); only an ACTIVE "
                    "certificate can be renewed"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Corruption guard (section 9.B / 7): the source's own
        # certificate_type_code group, after reconciling every sibling's
        # expiry too, must contain EXACTLY ONE ACTIVE certificate, and it
        # must be the source itself. This catches a prior partial
        # failure (write 1 of an earlier renewal attempt succeeded,
        # write 2 did not, leaving old+new both ACTIVE) before compounding
        # it with a third row.
        siblings = await self._list_and_reconcile(source.vehicle_id)
        active_group = [
            c
            for c in siblings
            if c.certificate_type_code == source.certificate_type_code
            and c.certificate_status == CertificateStatus.ACTIVE
        ]
        if len(active_group) != 1 or active_group[0].certificate_id != source.certificate_id:
            raise ApiError(
                code="VEHICLE_CERTIFICATE_ACTIVE_STATE_CONFLICT",
                message=(
                    f"Vehicle '{source.vehicle_id}' has an inconsistent ACTIVE-certificate "
                    f"state for certificate_type_code={source.certificate_type_code!r} "
                    f"({len(active_group)} ACTIVE record(s) found); refusing to renew "
                    "until this is reconciled."
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # WRITE 1: create the new ACTIVE row first (B2B-8).
        # LOCKED RENEWAL SEMANTICS: "omitted" (not in fields_set) means
        # inherit from source; "present" (in fields_set) means use the
        # supplied value exactly as given, including an explicit null —
        # never re-substitute the source value once the caller has
        # actually addressed the field.
        resolved_type_name_th = (
            certificate_type_name_th
            if "certificate_type_name_th" in fields_set
            else source.certificate_type_name_th
        )
        resolved_alert_lead_days = (
            alert_lead_days if "alert_lead_days" in fields_set else source.alert_lead_days
        )
        new_certificate = await self._append_certificate(
            vehicle_id=source.vehicle_id,
            certificate_type_code=source.certificate_type_code,
            certificate_type_name_th=resolved_type_name_th,
            document_no=document_no,
            issue_date=issue_date,
            expiry_date=expiry_date,
            alert_lead_days=resolved_alert_lead_days,
            certificate_status=CertificateStatus.ACTIVE,
            storage_ref=storage_ref,
            note_th=note_th,
            created_by_user_id=created_by_user_id,
        )
        # WRITE 2: mark the source REPLACED, linked to the new row.
        await self._repository.mark_vehicle_certificate_replaced(
            certificate_id=source.certificate_id,
            replaced_by_certificate_id=new_certificate.certificate_id,
        )
        return new_certificate


__all__ = ["VehicleCertificateService"]
