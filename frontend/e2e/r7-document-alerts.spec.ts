import { expect, test } from '@playwright/test'

// R7 (Owner-approved bounded Mock/TEST scope): document PDF binding display and
// alert read authorization, against the suite's dedicated mock TEST backend
// (DEV auth only; synthetic data; not production or PostgreSQL evidence). No
// document file can be attached through any public route (no approved policy),
// so these tests prove the honest "no verified file / unavailable" display, the
// server-side refusals, and that no historical storage_ref is ever a link.

const VEHICLE_ID = 'VEH-1046'
const MODEL_ID = 'MODEL-0001'

function unique(): string {
  return `${test.info().project.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

test('a certificate shows no verified PDF, attaching is unavailable, and its legacy storage_ref is never a link', async ({
  page,
}) => {
  const suffix = unique()
  const legacyRef = `https://legacy.example.invalid/${suffix}.pdf`
  const created = await page.request.post(`/api/v1/vehicles/${VEHICLE_ID}/certificates`, {
    data: { certificate_type_code: `R7-E2E-${suffix}`, certificate_type_name_th: `R7 E2E ${suffix}`, storage_ref: legacyRef },
  })
  expect(created.ok()).toBeTruthy()
  const certificate = (await created.json()) as { certificate_id: string; storage_ref: string }
  expect(certificate.storage_ref).toBe(legacyRef)

  await page.goto(`/vehicle/${VEHICLE_ID}/certificates`)
  const panel = page.getByTestId(`document-file-panel-${certificate.certificate_id}`)
  await expect(panel).toBeVisible()
  await expect(panel.getByText('ยังไม่ได้ตรวจสอบว่าเป็นไฟล์ในระบบ', { exact: false })).toBeVisible()
  await expect(panel.getByText('ยังไม่เปิดใช้งาน (รอการอนุมัตินโยบายสิทธิ์การแนบไฟล์เอกสาร)')).toBeVisible()
  await expect(page.locator('input[type="file"]')).toHaveCount(0)
  await expect(page.locator(`a[href*="${suffix}"]`)).toHaveCount(0)

  await panel.getByRole('button', { name: 'ตรวจสอบไฟล์ PDF' }).click()
  await expect(panel.getByText('ยังไม่มีไฟล์ PDF ที่ตรวจสอบแล้วในระบบ')).toBeVisible()
  await expect(panel.getByRole('link')).toHaveCount(0)
})

test('the server refuses a public document-file upload and an unauthorized document-file read', async ({ page }) => {
  const suffix = unique()
  const created = await page.request.post(`/api/v1/models/${MODEL_ID}/documents`, {
    data: { document_type: 'LOAD_CHART', document_name_th: `R7 E2E ${suffix}`, version: `R7-${suffix}` },
  })
  const document = (await created.json()) as { model_document_id: string }

  const upload = await page.request.post('/api/v1/attachments', {
    multipart: {
      purpose: 'MODEL_DOCUMENT_FILE',
      source_type: 'MODEL_DOCUMENT',
      source_id: document.model_document_id,
      file: { name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n') },
    },
  })
  expect(upload.status()).toBe(403)
  expect((await upload.json()).error.code).toBe('DOCUMENT_FILE_UPLOAD_POLICY_UNRESOLVED')

  const unauthorized = await page.request.get(
    `/api/v1/attachments/by-source/MODEL_DOCUMENT/${document.model_document_id}`,
    { headers: { 'X-Dev-Role': 'NO_SUCH_ROLE' } },
  )
  expect(unauthorized.status()).toBe(403)
  const guessed = await page.request.get('/api/v1/attachments/by-source/MODEL_DOCUMENT/MDOC-DOES-NOT-EXIST', {
    headers: { 'X-Dev-Role': 'NO_SUCH_ROLE' },
  })
  expect(guessed.status()).toBe(403) // enumeration: a guessed id looks the same as a real one

  await page.goto(`/models/${MODEL_ID}/documents`)
  const panel = page.getByTestId(`document-file-panel-${document.model_document_id}`)
  await panel.getByRole('button', { name: 'ตรวจสอบไฟล์ PDF' }).click()
  await expect(panel.getByText('ยังไม่มีไฟล์ PDF ที่ตรวจสอบแล้วในระบบ')).toBeVisible()
})

test('alert reads need a can_view actor; the page stays GET-only with no action control', async ({ page }) => {
  const refusedList = await page.request.get(`/api/v1/vehicles/${VEHICLE_ID}/alerts`, {
    headers: { 'X-Dev-Role': 'NO_SUCH_ROLE' },
  })
  expect(refusedList.status()).toBe(403)
  const refusedDetail = await page.request.get('/api/v1/alerts/ALT-DOES-NOT-EXIST', {
    headers: { 'X-Dev-Role': 'NO_SUCH_ROLE' },
  })
  expect(refusedDetail.status()).toBe(403) // not 404: nothing is learned about the id

  const writes: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/') && request.method() !== 'GET') writes.push(request.url())
  })
  await page.goto(`/vehicle/${VEHICLE_ID}/alerts`)
  await expect(page.getByRole('heading', { name: 'การแจ้งเตือน' })).toBeVisible()
  await expect(page.getByText('ไม่มีการแจ้งเตือน', { exact: true })).toBeVisible()
  await expect(page.locator('section.page button')).toHaveCount(0)
  expect(writes).toEqual([])
})
