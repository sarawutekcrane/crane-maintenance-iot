import { isLinkableVehicleId } from './certificateReportLinks'
import type { InspectionFindingReportAssetType } from './types'

/**
 * Web/API Phase 7 Batch 7E2 — link eligibility for the recorded inspection
 * findings report. Reuses the UNCHANGED 7D2 rule (`isLinkableVehicleId`:
 * the whole ORIGINAL id consists of ASCII unreserved URL characters
 * `A-Z a-z 0-9 . _ ~ -` and is neither "." nor ".."), so an eligible id is
 * placed into the path verbatim — no trimming, encoding or normalization.
 * Blank or ineligible ids get no link.
 *
 * Eligibility says nothing about the destination: the report performs no
 * join, so the inspection, vehicle or equipment may not exist and ids are
 * not promised to be unique. No query strings are ever added.
 */
export function inspectionDetailLink(inspectionId: string): string | null {
  return isLinkableVehicleId(inspectionId) ? `/inspections/${inspectionId}` : null
}

export function assetDetailLink(assetType: InspectionFindingReportAssetType, assetId: string): string | null {
  if (!isLinkableVehicleId(assetId)) return null
  return assetType === 'VEHICLE' ? `/vehicle/${assetId}` : `/equipment/${assetId}`
}
