/**
 * Web/API Phase 7 Batch 7D2 — conservative link eligibility for the
 * certificate expiry report. A vehicle id gets links only when the
 * ORIGINAL value consists entirely of ASCII unreserved URL characters
 * (`A-Z a-z 0-9 . _ ~ -`) and is neither "." nor "..", so the id is placed
 * into the path verbatim, with no encoding and no normalization. The
 * whole-string test (no multiline flag) rejects trailing newlines and any
 * control, space, Unicode or reserved character. Other ids are shown as
 * stored text without links.
 *
 * Eligibility says nothing about the destination: it does not promise the
 * vehicle exists or that vehicle ids are globally unique. No filter query
 * strings are ever added.
 */
const LINKABLE_VEHICLE_ID = /^[A-Za-z0-9._~-]+$/

export interface CertificateReportLinks {
  vehicleDetail: string
  vehicleCertificates: string
}

export function isLinkableVehicleId(vehicleId: string): boolean {
  return LINKABLE_VEHICLE_ID.test(vehicleId) && vehicleId !== '.' && vehicleId !== '..'
}

export function certificateReportLinks(vehicleId: string): CertificateReportLinks | null {
  if (!isLinkableVehicleId(vehicleId)) return null
  return {
    vehicleDetail: `/vehicle/${vehicleId}`,
    vehicleCertificates: `/vehicle/${vehicleId}/certificates`,
  }
}
