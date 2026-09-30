import { isLinkableVehicleId } from './certificateReportLinks'

/**
 * Web/API Phase 7 Batch 7F2 — link eligibility for the equipment list.
 * Reuses the UNCHANGED 7D2 rule (`isLinkableVehicleId`: the whole ORIGINAL
 * id consists of ASCII unreserved URL characters `A-Z a-z 0-9 . _ ~ -` and
 * is neither "." nor ".."), so an eligible id is placed into the path
 * verbatim — no trimming, encoding, decoding or normalization. The
 * destination (`EquipmentDetailPage`) interpolates the decoded route
 * parameter into its API path, so ids with "/", "\", "%", "?", "#",
 * whitespace or non-ASCII characters get no link.
 *
 * Eligibility says nothing about the destination: the equipment may not
 * exist or its page may fail to load. No query strings are ever added.
 */
export function equipmentDetailLink(equipmentId: string): string | null {
  return isLinkableVehicleId(equipmentId) ? `/equipment/${equipmentId}` : null
}

/**
 * Ids that occur more than once within ONE returned page. Only the given
 * rows are inspected — nothing is claimed about other pages.
 */
export function duplicateIdsInPage(ids: readonly string[]): Set<string> {
  const seen = new Set<string>()
  const duplicates = new Set<string>()
  for (const id of ids) {
    if (seen.has(id)) duplicates.add(id)
    else seen.add(id)
  }
  return duplicates
}
