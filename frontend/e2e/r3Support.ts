import { createHash } from 'node:crypto'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

/**
 * R3 E2E support (docs/project-governance/r3-implementation-contract.md §6).
 *
 * An asset accepts ONE inspection per Bangkok date, and every spec of a run
 * shares one mock backend across five viewport projects. A spec that only
 * needs "an inspection with a Finding" therefore submits the CANONICAL
 * payload for its asset with a request id derived from the asset and the
 * date: whichever project runs first creates it, every other one gets the
 * server's replay of the same inspection (S2 idempotency). The canonical
 * payload is fixed per asset: the first shown item FAIL with a fixed remark,
 * every other shown item PASS. Assets used this way must never also be
 * submitted with any other payload in the same run.
 */
export const CANONICAL_REMARK = 'E2E canonical abnormal remark'

/** A UUID-form id derived from a string (the backend requires UUID text). */
export function uuidFrom(seed: string): string {
  const hex = createHash('sha256').update(seed).digest('hex')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`
}

export interface CanonicalInspection {
  inspectionId: string
  findingId: string
}

export async function ensureCanonicalInspection(
  request: APIRequestContext,
  assetType: 'VEHICLE' | 'EQUIPMENT',
  assetId: string,
): Promise<CanonicalInspection> {
  const form = await request.get(`/api/v1/inspections/form?asset_type=${assetType}&asset_id=${assetId}`)
  expect(form.ok()).toBe(true)
  const body = await form.json()
  const requestId = uuidFrom(`r3-e2e-canonical-${assetType}-${assetId}-${body.inspection_date}`)
  let detail: { header: { inspection_id: string }; findings: { finding_id: string }[] }
  if (body.submitted_inspection_id) {
    const existing = await request.get(`/api/v1/inspections/${body.submitted_inspection_id}`)
    expect(existing.ok()).toBe(true)
    detail = await existing.json()
  } else {
    const items = (body.items as { item: { item_id: string } }[]).map((entry, index) => ({
      item_id: entry.item.item_id,
      result: index === 0 ? 'FAIL' : 'PASS',
      remark: index === 0 ? CANONICAL_REMARK : null,
    }))
    const response = await request.post('/api/v1/inspections', {
      data: { asset_type: assetType, asset_id: assetId, items },
      headers: { 'X-Request-Id': requestId },
    })
    if (response.status() === 409) {
      // A parallel project replayed / created it first with the same payload.
      const conflict = await response.json()
      const existing = await request.get(`/api/v1/inspections/${conflict.error.details.inspection_id}`)
      detail = await existing.json()
    } else {
      expect(response.ok(), await response.text()).toBe(true)
      detail = await response.json()
    }
  }
  expect(detail.findings.length, 'the canonical inspection records one Finding').toBeGreaterThan(0)
  return { inspectionId: detail.header.inspection_id, findingId: detail.findings[0].finding_id }
}

export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}
