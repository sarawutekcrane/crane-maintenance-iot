import { expect, test } from '@playwright/test'

// Web/API Phase 6 Batch 6F — Model Document revision UI. Runs across every
// viewport project configured in playwright.config.ts (smartphone
// portrait/landscape, tablet portrait/landscape, desktop), all sharing one
// backend/mock repository process — every test creates its own
// project-unique document (mirroring driver-phase6-batch1.spec.ts's own
// `${test.info().project.name}` uniqueness technique) rather than
// asserting against a specific shared row other parallel projects also
// mutate.

const MODEL_ID = 'MODEL-0001'

async function createDocument(
  page: import('@playwright/test').Page,
  overrides: Record<string, unknown> = {},
) {
  const suffix = `${test.info().project.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const response = await page.request.post(`/api/v1/models/${MODEL_ID}/documents`, {
    data: {
      document_type: 'LOAD_CHART',
      document_name_th: `E2E เอกสาร ${suffix}`,
      version: `1.0-${suffix}`,
      effective_from: '2026-01-01',
      ...overrides,
    },
  })
  return (await response.json()) as { model_document_id: string; version: string }
}

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

test('creating a revision shows the successor link on the source and the new record in history, with no overflow while the form is open (including its expanded set-mode inputs) or after success', async ({
  page,
}) => {
  const source = await createDocument(page)

  await page.goto(`/models/${MODEL_ID}/documents`)
  const sourceCard = page.locator('.card', { hasText: source.model_document_id })
  await expect(sourceCard).toBeVisible()

  const newVersion = `2.0-${test.info().project.name}-${Date.now()}`
  await sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' }).click()
  await page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่').fill(newVersion)
  await page.getByLabel('วันที่เริ่มมีผลใช้ฉบับใหม่').fill('2026-06-01')

  // Expand both "set" inputs (the widest the form ever gets) before
  // checking overflow, then revert to inherit so the revise payload below
  // stays minimal/predictable.
  await page.getByLabel('ชื่อเอกสาร (ภาษาไทย)', { exact: true }).selectOption('set')
  await page.getByLabel('สถานะการใช้งาน', { exact: true }).selectOption('set')
  await expect(page.getByLabel('ชื่อเอกสารใหม่')).toBeVisible()
  await expect(page.getByLabel('สถานะการใช้งานใหม่')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.getByLabel('ชื่อเอกสาร (ภาษาไทย)', { exact: true }).selectOption('inherit')
  await page.getByLabel('สถานะการใช้งาน', { exact: true }).selectOption('inherit')

  await page.getByRole('button', { name: 'ยืนยันสร้างฉบับปรับปรุง' }).click()

  // The source card now shows a successor link instead of the revise action.
  await expect(sourceCard.getByText('ถูกแทนที่ด้วยฉบับปรับปรุง')).toBeVisible()
  await expect(sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' })).toHaveCount(0)
  const successorId = await sourceCard
    .locator('.status-card__row', { hasText: 'ถูกแทนที่ด้วยฉบับปรับปรุง' })
    .locator('a')
    .textContent()

  // The new revision appears in the authoritative refreshed history, linked
  // from the source card via its own in-page anchor.
  const newCard = page.locator(`#model-document-${successorId}`)
  await expect(newCard).toBeVisible()
  await expect(newCard.getByText(newVersion)).toBeVisible()

  await expectNoHorizontalOverflow(page)
})

test('a source document with no effective_from explains why it cannot be revised, without a button', async ({
  page,
}) => {
  const source = await createDocument(page, { effective_from: null })

  await page.goto(`/models/${MODEL_ID}/documents`)
  const sourceCard = page.locator('.card', { hasText: source.model_document_id })
  await expect(sourceCard).toBeVisible()

  await expect(sourceCard.getByText('ยังไม่มีวันที่เริ่มมีผลใช้')).toBeVisible()
  await expect(sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' })).toHaveCount(0)
})

test('an unchanged version is blocked before any network call (zero revise POSTs), with inputs preserved', async ({
  page,
}) => {
  const source = await createDocument(page)

  let reviseRequestCount = 0
  await page.route(`**/api/v1/model-documents/${source.model_document_id}/revise`, (route) => {
    reviseRequestCount += 1
    return route.continue()
  })

  await page.goto(`/models/${MODEL_ID}/documents`)
  const sourceCard = page.locator('.card', { hasText: source.model_document_id })
  await sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' }).click()

  // Deliberately reuse the exact source version. The client-side guard
  // (mirroring the backend's own authoritative MODEL_DOCUMENT_VERSION_DUPLICATE
  // rejection, Locked Rule 6) catches this before any POST is sent.
  await page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่').fill(source.version)
  await page.getByLabel('วันที่เริ่มมีผลใช้ฉบับใหม่').fill('2026-06-01')
  await page.getByRole('button', { name: 'ยืนยันสร้างฉบับปรับปรุง' }).click()

  await expect(
    page.getByText('เวอร์ชัน/ฉบับที่ใหม่ต้องไม่ซ้ำกับเวอร์ชันเดิมของเอกสารต้นทาง'),
  ).toBeVisible()
  await expect(page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่')).toHaveValue(source.version)
  // Actually count network calls to the revise endpoint, not just assert
  // the message — the client-side rejection must never reach the network.
  expect(reviseRequestCount).toBe(0)
})

test('cancelling the revision form discards its inputs and leaves the source document untouched', async ({
  page,
}) => {
  const source = await createDocument(page)

  await page.goto(`/models/${MODEL_ID}/documents`)
  const sourceCard = page.locator('.card', { hasText: source.model_document_id })
  await sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' }).click()

  await page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่').fill(`ยกเลิก-${test.info().project.name}`)
  await page.getByLabel('วันที่เริ่มมีผลใช้ฉบับใหม่').fill('2026-06-01')
  await page.getByRole('button', { name: 'ยกเลิก' }).click()

  // The form is gone, the revise action is offered again (source untouched:
  // no successor link, still eligible), and re-opening starts blank again.
  await expect(page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่')).toHaveCount(0)
  await expect(sourceCard.getByText('ถูกแทนที่ด้วยฉบับปรับปรุง')).toHaveCount(0)
  await expect(sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' })).toBeVisible()

  await sourceCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' }).click()
  await expect(page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่')).toHaveValue('')
})
