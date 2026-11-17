import { readdirSync, readFileSync, unlinkSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Browser, type APIRequestContext } from '@playwright/test'
import { expectNoHorizontalOverflow, uuidFrom } from './r3Support'

// R7 (Owner-approved bounded Mock/TEST scope): document PDF binding display and
// alert read authorization, against the suite's dedicated mock TEST backend
// (DEV auth only; synthetic data; not production or PostgreSQL evidence). R7
// TEST-only PDF Management opens the upload ONLY to a verified TEST employee with
// the dedicated Access Management grant; this suite's backend runs in legacy
// development-role mode, where every role is refused. These tests prove the
// honest "no verified file / unavailable" display, the server-side refusals,
// that a picker shown by a forged /me answer is still refused by the server, and
// that no historical storage_ref is ever a link.

const VEHICLE_ID = 'VEH-1046'
const MODEL_ID = 'MODEL-0001'

function unique(): string {
  return `${test.info().project.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// R7 Whole-Phase: the tests below run against the legacy development-role backend only.
const AM_E2E = process.env.ACCESS_MANAGEMENT_E2E === '1'

test.describe('legacy development-role backend', () => {
test.skip(AM_E2E, 'runs against the legacy development-role backend')

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
  await expect(panel.getByText('ไม่มีสิทธิ์แนบไฟล์ (เฉพาะผู้จัดการเอกสารที่ได้รับสิทธิ์ในบริบท TEST)')).toBeVisible()
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

test('a picker revealed by a forged /me answer is still refused by the server, with no retry', async ({ page }) => {
  // Frontend hiding is not the security boundary: the browser is told (falsely)
  // that this actor holds the TEST grant, and the real backend still refuses.
  const suffix = unique()
  const created = await page.request.post(`/api/v1/vehicles/${VEHICLE_ID}/certificates`, {
    data: { certificate_type_code: `R7-E2E-UP-${suffix}`, certificate_type_name_th: `R7 E2E UP ${suffix}` },
  })
  const certificate = (await created.json()) as { certificate_id: string }
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({
      json: { user_id: 'USR-FORGED', roles: [], capabilities: ['can_view', 'can_manage_test_document_file'], data_context: 'TEST' },
    }),
  )
  const posts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/v1/attachments')) posts.push(request.url())
  })
  await page.goto(`/vehicle/${VEHICLE_ID}/certificates`)
  const panel = page.getByTestId(`document-file-panel-${certificate.certificate_id}`)
  const upload = panel.getByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
  // The dev server's StrictMode may re-render the list once after load; choose
  // the file again until the (settled) panel shows the choice.
  await expect(async () => {
    await panel.getByLabel('แนบไฟล์ PDF (TEST)').setInputFiles({
      name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n'),
    })
    await expect(upload).toBeEnabled({ timeout: 1000 })
  }).toPass({ timeout: 15000 })
  await upload.click()
  await expect(panel.getByRole('alert')).toContainText('คุณไม่มีสิทธิ์แนบไฟล์ PDF ให้เอกสารนี้ — ไม่มีการบันทึกไฟล์')
  await expect(panel.getByText('synthetic.pdf', { exact: true })).toBeVisible() // the choice is kept
  await expect(upload).toBeEnabled()
  expect(posts).toHaveLength(1)
  const listed = await page.request.get(`/api/v1/attachments/by-source/VEHICLE_CERTIFICATE/${certificate.certificate_id}`)
  expect(await listed.json()).toEqual([])
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
})

// ---------------------------------------------------------------------------
// R7 Whole-Phase Mock/TEST (Owner gate 2026-11-17): the Access Management backend
// (ACCESS_MANAGEMENT_E2E=1 … --workers=1). Every permission comes from a REAL root
// grant through the audited API — no forged /me, no injected context. TEST parents:
// VEH-1048 / MODEL-0003 (server reference); REAL negative: VEH-1046.
// ---------------------------------------------------------------------------

test.describe('Access Management TEST workflow (real audited grants)', () => {
  test.skip(!AM_E2E, 'needs the Access Management mode backend (ACCESS_MANAGEMENT_E2E=1)')

  const as = (user: string) => ({ 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': user })
  const MGR = as('USR-TEST-AM-MGR')
  const CLERK = as('USR-TEST-AM-CLERK')
  const DRV1 = as('USR-TEST-AM-DRV1')
  const PDF_BYTES = Buffer.from('%PDF-1.4\n% R7 TEST synthetic\n%%EOF\n')

  async function grantTo(request: APIRequestContext, personnelId: string, changes: Record<string, boolean>) {
    const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
    const response = await request.post('/api/v1/access/grants', {
      headers: { ...MGR, 'X-Request-Id': uuidFrom(`r7-e2e-${personnelId}-${JSON.stringify(changes)}-${Date.now()}`) },
      data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'R7 E2E',
        expected_revision: revision },
    })
    expect(response.ok(), await response.text()).toBe(true)
  }

  const PM_INCOMPLETE = 'PM ถึงกำหนด: ยังยืนยันไม่ได้: แหล่งข้อมูลไม่ครบหรืออ่านไม่สำเร็จ (ไม่ใช่ "ไม่มีรายการ")'
  // The dedicated E2E backend's local upload directory (Settings.local_upload_dir, relative to backend/).
  const UPLOAD_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'backend', 'data', 'uploads')

  async function open(browser: Browser, baseURL: string | undefined, headers: Record<string, string>) {
    const context = await browser.newContext({ baseURL, extraHTTPHeaders: headers })
    return context.newPage()
  }

  test('@mutation certificate and model document: create, upload, renew, revise with real grants', async ({
    browser, baseURL, request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
    await grantTo(request, 'PER-TEST-AM-CLERK', { can_view: true, can_manage_test_document_master: true,
      can_manage_test_document_file: true })
    const suffix = `${Date.now()}`
    const refused = await request.post('/api/v1/vehicles/VEH-1046/certificates', {
      headers: CLERK, data: { certificate_type_code: `R7-REAL-${suffix}`, certificate_type_name_th: 'REAL' } })
    expect(refused.status()).toBe(403)
    expect((await refused.json()).error.code).toBe('DOCUMENT_PARENT_SCOPE_UNPROVEN')

    const page = await open(browser, baseURL, CLERK)
    await page.goto('/vehicle/VEH-1048/certificates')
    await page.getByRole('button', { name: '+ เพิ่มเอกสาร/ใบรับรอง' }).click()
    await page.getByLabel('ประเภทเอกสาร (รหัส)').fill(`R7-E2E-${suffix}`)
    await page.getByLabel('ประเภทเอกสาร (ชื่อภาษาไทย)').fill(`ใบรับรอง R7 ${suffix}`)
    await page.getByLabel('วันหมดอายุ').fill('2099-12-31')
    await page.getByLabel('สถานะ').selectOption('ACTIVE')
    const created = page.waitForResponse((r) => r.url().endsWith('/api/v1/vehicles/VEH-1048/certificates')
      && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'บันทึก', exact: true }).click()
    const certificate = await (await created).json()
    expect(certificate.vehicle_id).toBe('VEH-1048')

    const panel = page.getByTestId(`document-file-panel-${certificate.certificate_id}`)
    const upload = panel.getByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
    await expect(async () => {
      await panel.getByLabel('แนบไฟล์ PDF (TEST)').setInputFiles({ name: 'r7.pdf', mimeType: 'application/pdf',
        buffer: PDF_BYTES })
      await expect(upload).toBeEnabled({ timeout: 1000 })
    }).toPass({ timeout: 15000 })
    await upload.click()
    await expect(panel.getByRole('status').filter({ hasText: 'อัปโหลดไฟล์ r7.pdf แล้ว' })).toBeVisible()
    const [download] = await Promise.all([page.waitForEvent('download'),
      panel.getByRole('button', { name: 'ดาวน์โหลดไฟล์ PDF' }).click()])
    expect(readFileSync((await download.path()) ?? '').equals(PDF_BYTES)).toBe(true)

    const card = page.locator('.card', { has: panel })
    await card.getByRole('button', { name: 'ต่ออายุ/ออกใหม่' }).click()
    await page.getByLabel('วันหมดอายุใหม่').fill('2100-12-31')
    const renewed = page.waitForResponse((r) => r.url().endsWith(`/certificates/${certificate.certificate_id}/renew`)
      && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'ยืนยันต่ออายุ/ออกใหม่' }).click()
    expect((await renewed).status()).toBe(200)
    const old = await request.get(`/api/v1/certificates/${certificate.certificate_id}`, { headers: CLERK })
    expect((await old.json()).certificate_status).toBe('REPLACED')
    const oldFiles = await request.get(`/api/v1/attachments/by-source/VEHICLE_CERTIFICATE/${certificate.certificate_id}`,
      { headers: CLERK })
    expect((await oldFiles.json()).length).toBe(1)  // the old file stays with the old certificate

    await page.goto('/models/MODEL-0003/documents')
    await page.getByRole('button', { name: '+ เพิ่มเอกสาร' }).click()
    await page.getByLabel('ประเภทเอกสาร').fill('LOAD_CHART')
    await page.getByLabel('ชื่อเอกสาร (ภาษาไทย)').fill(`ตารางพิกัดยก R7 ${suffix}`)
    await page.getByLabel('เวอร์ชัน/ฉบับที่').fill(`R7-${suffix}`)
    await page.getByLabel('มีผลใช้ตั้งแต่วันที่').fill('2026-01-01')
    const docCreated = page.waitForResponse((r) => r.url().endsWith('/api/v1/models/MODEL-0003/documents')
      && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'บันทึก', exact: true }).click()
    const doc = await (await docCreated).json()
    const docPanel = page.getByTestId(`document-file-panel-${doc.model_document_id}`)
    const docUpload = docPanel.getByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
    await expect(async () => {
      await docPanel.getByLabel('แนบไฟล์ PDF (TEST)').setInputFiles({ name: 'chart.pdf',
        mimeType: 'application/pdf', buffer: PDF_BYTES })
      await expect(docUpload).toBeEnabled({ timeout: 1000 })
    }).toPass({ timeout: 15000 })
    await docUpload.click()
    await expect(docPanel.getByRole('status').filter({ hasText: 'อัปโหลดไฟล์ chart.pdf แล้ว' })).toBeVisible()
    const docCard = page.locator('.card', { has: docPanel })
    await docCard.getByRole('button', { name: 'สร้างเอกสารฉบับปรับปรุง' }).click()
    await page.getByLabel('เวอร์ชัน/ฉบับที่ใหม่').fill(`R7-${suffix}-B`)
    await page.getByLabel('วันที่เริ่มมีผลใช้ฉบับใหม่').fill('2026-06-01')
    const revised = page.waitForResponse((r) => r.url().includes('/revise') && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'ยืนยันสร้างฉบับปรับปรุง' }).click()
    expect((await revised).status()).toBe(200)
    await page.context().close()
  })

  test('@mutation alerts: evaluate, acknowledge and mute with real grants', async ({ browser, baseURL, request },
    testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
    await grantTo(request, 'PER-TEST-AM-CLERK', { can_view: true, can_run_test_alert_evaluation: true })
    await grantTo(request, 'PER-TEST-AM-DRV1', { can_view: true, can_act_on_test_alert: true })
    const clerk = await open(browser, baseURL, CLERK)
    await clerk.goto('/vehicle/VEH-1048/alerts')
    await clerk.getByRole('button', { name: 'ประเมินการแจ้งเตือน (TEST)' }).click()
    await expect(clerk.getByRole('status').filter({ hasText: 'ประเมินแล้ว' })).toBeVisible()
    await expect(clerk.getByText(/อะไหล่ถึงกำหนด \(REPLACE\)/).first()).toBeVisible()
    await expect(clerk.getByTestId('alert-provenance')).toContainText('อะไหล่ถึงกำหนด: มีการแจ้งเตือน')
    // C2: the dormant PM Master leaves the PM source incomplete — never a verified zero.
    await expect(clerk.getByTestId('alert-provenance')).toContainText(PM_INCOMPLETE)
    const link = clerk.getByRole('link', { name: /PART_LIFETIME_DUE_KEY/ }).first()
    await expect(link).toHaveAttribute('href', '/part-instances/PINST-TEST-R7-0001')
    await clerk.context().close()

    const drv1 = await open(browser, baseURL, DRV1)
    await drv1.goto('/vehicle/VEH-1048/alerts')
    await drv1.getByRole('button', { name: 'รับทราบ' }).first().click()
    await expect(drv1.getByRole('status').filter({ hasText: 'รับทราบแล้ว' })).toBeVisible()
    await drv1.getByRole('button', { name: 'ปิดเสียงชั่วคราว' }).first().click()
    await drv1.getByLabel('ปิดเสียงถึง').fill('2099-01-01T10:00')
    await drv1.getByLabel('เหตุผล').fill('รออะไหล่ (R7 E2E)')
    await drv1.getByRole('button', { name: 'ยืนยันปิดเสียง' }).click()
    await expect(drv1.getByRole('status').filter({ hasText: 'ปิดเสียงแล้ว' })).toBeVisible()
    const alerts = await (await request.get('/api/v1/vehicles/VEH-1048/alerts', { headers: DRV1 })).json()
    const part = alerts.find((a: { alert_type: string }) => a.alert_type === 'PART_LIFETIME_DUE')
    expect(part.alert_status).toBe('MUTED')
    expect(part.acknowledged_by_user_id).toBe('USR-TEST-AM-DRV1')
    await drv1.context().close()
  })

  test('read views fit every viewport (central list, provenance, documents)', async ({ browser, baseURL, request }) => {
    await grantTo(request, 'PER-TEST-AM-CLERK', { can_view: true })
    const page = await open(browser, baseURL, CLERK)
    await page.goto('/alerts')
    await expect(page.getByRole('heading', { name: 'การแจ้งเตือนทั้งหมด' })).toBeVisible()
    await expect(page.getByText(/งานในความรับผิดชอบของฉัน: ยังไม่พร้อมใช้งาน/)).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.goto('/vehicle/VEH-1048/alerts')
    await expect(page.getByTestId('alert-provenance')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.goto('/vehicle/VEH-1048/certificates')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.context().close()
  })
  test('C2: provenance after a TEST evaluation is never a false zero on every viewport', async ({ browser, baseURL,
    request }) => {
    await grantTo(request, 'PER-TEST-AM-CLERK', { can_view: true, can_run_test_alert_evaluation: true })
    const evaluated = await request.post('/api/v1/alerts/test-evaluations', {
      headers: { ...CLERK, 'X-Request-Id': uuidFrom(`r7-c2-${test.info().project.name}-${Date.now()}`) },
      data: { vehicle_id: 'VEH-1048' } })
    expect(evaluated.status(), await evaluated.text()).toBe(200)
    const pm = (await evaluated.json()).outcomes.find((o: { alert_type: string }) => o.alert_type === 'PM_DUE')
    expect(pm.source).toBe('INCOMPLETE')
    const provenance = await (await request.get('/api/v1/vehicles/VEH-1048/alert-provenance', { headers: CLERK }))
      .json()
    expect(provenance.types.PM_DUE).toBe('SOURCE_INCOMPLETE')
    const page = await open(browser, baseURL, CLERK)
    await page.goto('/vehicle/VEH-1048/alerts')
    const panel = page.getByTestId('alert-provenance')
    await expect(panel).toContainText(PM_INCOMPLETE)
    await expect(panel).not.toContainText('PM ถึงกำหนด: ประเมินแล้ว')
    await expect(panel).toContainText('อะไหล่ถึงกำหนด: มีการแจ้งเตือน')
    await expectNoHorizontalOverflow(page)
    await page.context().close()
  })

  test('U-16 / U-20: every viewport downloads exact PDF bytes; a lost file is marked on its own row', async ({
    browser, baseURL, request,
  }) => {
    await grantTo(request, 'PER-TEST-AM-CLERK', { can_view: true, can_manage_test_document_master: true,
      can_manage_test_document_file: true })
    const project = test.info().project.name
    const stamp = `${project}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const bytesOf = (label: string) => Buffer.from(`%PDF-1.4\n% R7 TEST ${label} ${stamp}\n%%EOF\n`)
    const page = await open(browser, baseURL, CLERK)

    async function upload(panelId: string, name: string, bytes: Buffer) {
      const panel = page.getByTestId(`document-file-panel-${panelId}`)
      await panel.scrollIntoViewIfNeeded()
      const button = panel.getByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
      await expect(async () => {
        await panel.getByLabel('แนบไฟล์ PDF (TEST)').setInputFiles({ name, mimeType: 'application/pdf', buffer: bytes })
        await expect(button).toBeEnabled({ timeout: 1000 })
      }).toPass({ timeout: 15000 })
      await button.click()
      await expect(panel.getByRole('status').filter({ hasText: `อัปโหลดไฟล์ ${name} แล้ว` })).toBeVisible()
    }
    function row(panelId: string, filename: string) {
      return page.getByTestId(`document-file-panel-${panelId}`).locator('[data-testid^="document-file-row-"]',
        { hasText: filename })
    }
    async function downloadExact(panelId: string, filename: string, bytes: Buffer) {
      const target = row(panelId, filename)
      const [download] = await Promise.all([page.waitForEvent('download'),
        target.getByRole('button', { name: /ดาวน์โหลดไฟล์ PDF|ลองดาวน์โหลดอีกครั้ง/ }).click()])
      expect(download.suggestedFilename()).toBe(filename)
      expect(readFileSync((await download.path()) ?? '').equals(bytes)).toBe(true)  // native browser download
      await expect(target.getByRole('status')).toHaveText('ดาวน์โหลดไฟล์แล้ว')
    }
    function removeStoredBytes(bytes: Buffer) {  // controlled Mock fault in the scratch upload dir
      const stored = readdirSync(UPLOAD_DIR).filter((name) => readFileSync(join(UPLOAD_DIR, name)).equals(bytes))
      expect(stored).toHaveLength(1)
      unlinkSync(join(UPLOAD_DIR, stored[0]))
      return stored[0]
    }
    async function expectMissingOnItsRow(panelId: string, filename: string, storedName: string) {
      const target = row(panelId, filename)
      await target.getByRole('button', { name: 'ดาวน์โหลดไฟล์ PDF' }).click()
      await expect(target.getByRole('alert')).toHaveText('ไม่พบไฟล์ (ไฟล์สูญหาย)')
      await expect(target).not.toContainText('uploads')
      await expect(target).not.toContainText(storedName)
    }
    const listOf = async (sourceType: string, sourceId: string) =>
      (await request.get(`/api/v1/attachments/by-source/${sourceType}/${sourceId}`, { headers: CLERK })).json()

    // --- certificate (VEH-1048): two files; one is lost, the other keeps working ---
    const created = await request.post('/api/v1/vehicles/VEH-1048/certificates', { headers: CLERK, data: {
      certificate_type_code: `R7-VP-${stamp}`, certificate_type_name_th: `R7 ${project}`, expiry_date: '2099-12-31',
      certificate_status: 'ACTIVE' } })
    expect(created.status(), await created.text()).toBe(200)
    const certId = (await created.json()).certificate_id
    const present = bytesOf('present'); const lost = bytesOf('lost')
    await page.goto('/vehicle/VEH-1048/certificates')
    await upload(certId, 'present.pdf', present)
    await upload(certId, 'lost.pdf', lost)
    await downloadExact(certId, 'present.pdf', present)
    await downloadExact(certId, 'lost.pdf', lost)
    await expectNoHorizontalOverflow(page)
    const metaBefore = await listOf('VEHICLE_CERTIFICATE', certId)
    expect(metaBefore).toHaveLength(2)
    const lostId = metaBefore.find((f: { filename: string }) => f.filename === 'lost.pdf').attachment_id
    const storedName = removeStoredBytes(lost)
    const api404 = await request.get(`/api/v1/attachments/${lostId}/file`, { headers: CLERK })
    expect(api404.status()).toBe(404)
    expect((await api404.json()).error.code).toBe('ATTACHMENT_FILE_MISSING')
    await page.reload()
    await page.getByTestId(`document-file-panel-${certId}`).getByRole('button', { name: 'ตรวจสอบไฟล์ PDF' }).click()
    await expectMissingOnItsRow(certId, 'lost.pdf', storedName)
    await expect(row(certId, 'present.pdf').getByRole('alert')).toHaveCount(0)  // the other row is unaffected
    await downloadExact(certId, 'present.pdf', present)  // and still downloads its exact bytes
    await expect(row(certId, 'lost.pdf').getByRole('alert')).toHaveText('ไม่พบไฟล์ (ไฟล์สูญหาย)')
    expect(await listOf('VEHICLE_CERTIFICATE', certId)).toEqual(metaBefore)  // metadata unchanged, nothing deleted
    await expectNoHorizontalOverflow(page)

    // --- model document (MODEL-0003): exact bytes, then the same per-row missing state ---
    const doc = await request.post('/api/v1/models/MODEL-0003/documents', { headers: CLERK, data: {
      document_type: 'LOAD_CHART', document_name_th: `R7 VP ${project}`, version: `VP-${stamp}` } })
    expect(doc.status(), await doc.text()).toBe(200)
    const docId = (await doc.json()).model_document_id
    const docBytes = bytesOf('doc')
    await page.goto('/models/MODEL-0003/documents')
    await upload(docId, 'doc.pdf', docBytes)
    await downloadExact(docId, 'doc.pdf', docBytes)
    const docMeta = await listOf('MODEL_DOCUMENT', docId)
    const docStored = removeStoredBytes(docBytes)
    await page.reload()
    await page.getByTestId(`document-file-panel-${docId}`).getByRole('button', { name: 'ตรวจสอบไฟล์ PDF' }).click()
    await expectMissingOnItsRow(docId, 'doc.pdf', docStored)
    expect(await listOf('MODEL_DOCUMENT', docId)).toEqual(docMeta)
    await expectNoHorizontalOverflow(page)

    // --- authorization still holds: an unknown actor cannot read either file or list ---
    const stranger = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-UNKNOWN-R7' }
    const presentId = metaBefore.find((f: { filename: string }) => f.filename === 'present.pdf').attachment_id
    expect((await request.get(`/api/v1/attachments/${presentId}/file`, { headers: stranger })).status()).toBe(403)
    expect((await request.get(`/api/v1/attachments/by-source/VEHICLE_CERTIFICATE/${certId}`,
      { headers: stranger })).status()).toBe(403)
    await page.context().close()
  })
})
