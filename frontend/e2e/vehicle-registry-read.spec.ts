import { expect, test, type Page } from '@playwright/test'

// Phase 7 Batch 7O2a — registry read foundation, end to end against the
// mock backend's synthetic registry seed (contract Final Rev2 §7, §10).
// Read-only: nothing here writes registry data. Runs on every configured
// Chromium viewport project (viewport emulation, not other browser engines).

async function noHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

/** In-app navigation (no reload), as a link inside the app would do. */
async function navigateInApp(page: Page, path: string) {
  await page.evaluate((target) => {
    window.history.pushState({}, '', target)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, path)
}

test('vehicle list shows registry text, resolved names and the unknown province code', async ({ page }) => {
  await page.goto('/vehicles')
  await expect(page.getByText('ทะเบียน: 0012 · ระยอง').first()).toBeVisible()
  await expect(page.getByText('สาขา: แหลมฉบัง').first()).toBeVisible()
  await expect(page.getByText(/ทะเบียน: กข-1234 · รหัสไม่อยู่ในทะเบียน \(TH-99\)/).first()).toBeVisible()
  await expect(page.getByText('ทะเบียน: ยังไม่ได้บันทึก').first()).toBeVisible()
  await noHorizontalScroll(page)
})

test('the exact branch filter narrows the list and can be cleared', async ({ page }) => {
  await page.goto('/vehicles')
  const select = page.getByLabel('สาขาที่รับผิดชอบ')
  await expect(select.locator('option')).toHaveCount(4)
  const listed = page.waitForResponse((r) => r.url().includes('/api/v1/vehicles?') && r.url().includes('branch_id=BR-LAEM-CHABANG'))
  await select.selectOption('BR-LAEM-CHABANG')
  await listed
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByText(/เงื่อนไขที่ใช้: สาขา แหลมฉบัง/)).toBeVisible()
  await page.getByRole('button', { name: 'ล้างตัวกรอง' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–3 จาก 3 คันที่ตรงกับเงื่อนไข')).toBeVisible()
})

test('a branch-list outage keeps raw codes as unavailable and the list usable', async ({ page }) => {
  await page.route('**/api/v1/branches', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'BRANCH_MASTER_READ_FAILED', message: 'x', details: null, request_id: 'e2e' } }),
    }),
  )
  await page.goto('/vehicles')
  await expect(page.getByText('สาขา: BR-LAEM-CHABANG (ไม่สามารถโหลดชื่อได้)').first()).toBeVisible()
  await expect(page.getByText(/รหัสไม่อยู่ในทะเบียน \(BR-/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'ลองโหลดรายชื่อสาขา/จังหวัดอีกครั้ง' })).toBeVisible()
})

test('vehicle detail shows the registry card and read-only history panels', async ({ page }) => {
  await page.goto('/vehicle/VEH-1046')
  await expect(page.getByRole('heading', { name: 'ทะเบียนและสาขาที่รับผิดชอบ' })).toBeVisible()
  const branchPanel = page.getByTestId('branch-history-panel')
  await expect(branchPanel.getByText('สาขาต้นทางที่บันทึกไว้ต่างจากที่คำนวณได้ตามลำดับปัจจุบัน').filter({ visible: true }).first()).toBeVisible()
  await expect(branchPanel.getByText('ตรงกับสาขาในข้อมูลทะเบียนรถ')).toBeVisible()
  const registrationPanel = page.getByTestId('registration-history-panel')
  await expect(registrationPanel.getByText(/0012 · ระยอง/).filter({ visible: true }).first()).toBeVisible()
  await expect(branchPanel.getByRole('button')).toHaveCount(0)
  await expect(registrationPanel.getByRole('button')).toHaveCount(0)
  await noHorizontalScroll(page)
})

test('a vehicle without history shows "no history" only after a successful read', async ({ page }) => {
  await page.goto('/vehicle/VEH-1047')
  await expect(page.getByTestId('branch-history-panel').getByText('ยังไม่มีประวัติ', { exact: true })).toBeVisible()
  await expect(page.getByTestId('registration-history-panel').getByText('ยังไม่มีประวัติ', { exact: true })).toBeVisible()
})

test('a failed branch-history read is an error, while the other panel still loads', async ({ page }) => {
  await page.route('**/api/v1/vehicles/VEH-1046/branch-history', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'BRANCH_HISTORY_READ_FAILED', message: 'x', details: null, request_id: 'e2e-bh' } }),
    }),
  )
  await page.goto('/vehicle/VEH-1046')
  const branchPanel = page.getByTestId('branch-history-panel')
  await expect(branchPanel.getByText('ไม่สามารถอ่านประวัติสาขาที่รับผิดชอบได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeVisible()
  await expect(branchPanel.getByText('ยังไม่มีประวัติ', { exact: true })).toHaveCount(0)
  await expect(branchPanel.getByRole('button', { name: 'ลองโหลดประวัติสาขาอีกครั้ง' })).toBeVisible()
  await expect(page.getByTestId('registration-history-panel').getByText(/0012 · ระยอง/).filter({ visible: true }).first()).toBeVisible()
})

test('moving to another vehicle resets an open machine-number editor', async ({ page }) => {
  await page.goto('/vehicle/VEH-1046')
  await expect(page.getByRole('heading', { name: 'TC-12' })).toBeVisible()
  await page.getByRole('button', { name: 'แก้ไข' }).click()
  await page.getByLabel('เลขเครื่องจักรใหม่').fill('ค่าที่ยังไม่บันทึก')
  await navigateInApp(page, '/vehicle/VEH-1047')
  await expect(page.getByRole('heading', { name: 'TC-13' })).toBeVisible()
  await expect(page.getByLabel('เลขเครื่องจักรใหม่')).toHaveCount(0)
  await expect(page.getByTestId('registration-history-panel').getByText('ยังไม่มีประวัติ', { exact: true })).toBeVisible()
})
