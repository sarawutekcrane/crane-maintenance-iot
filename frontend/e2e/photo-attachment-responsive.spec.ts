import { expect, test, type Browser, type Page, type TestInfo } from '@playwright/test'

/**
 * R2 Batch R2f-h4 B5 responsive fix — no page that renders PhotoAttachmentField
 * may scroll horizontally, in any photo state, at any required viewport.
 *
 * The page-level assertion is exactly
 *   document.documentElement.scrollWidth <= document.documentElement.clientWidth
 * with NO element excluded and no tolerance (both are integer CSS pixels). The
 * defect this guards: `.form-field input` (0,1,1) out-ranked
 * `.photo-attachment-field__input` (0,1,0), so the visually hidden, absolutely
 * positioned file input got `width: 100%` of the viewport and pushed the scroll
 * width out (e.g. 1492 px on a 1280 px viewport).
 *
 * Runs in its own `responsive-photo` project: each test opens one context per
 * required viewport (mobile emulation for the phone and tablet sizes). Photo
 * upload stays real (the mock backend stores the file); route interception is
 * used only to hold an upload open long enough to measure the "uploading" state.
 */

const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 800, mobile: false },
  { name: 'tablet-portrait', width: 768, height: 1024, mobile: true },
  { name: 'tablet-landscape', width: 1024, height: 768, mobile: true },
  { name: 'smartphone-portrait', width: 375, height: 667, mobile: true },
  { name: 'smartphone-landscape', width: 667, height: 375, mobile: true },
] as const

const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
)

const R3_FORM = {
  asset_type: 'VEHICLE',
  asset_id: 'VEH-1046',
  inspection_date: '2026-10-01',
  checklist: { checklist_id: 'CHK-0001', asset_type: 'VEHICLE', code: 'VEHICLE-PLACEHOLDER', name: 'รายการตรวจเช็คยานพาหนะ' },
  revision: { revision_id: 'REV-0001', checklist_id: 'CHK-0001', revision_number: 1, effective_date: '2026-01-01', created_at: '2026-01-01T00:00:00Z' },
  items: [1, 2, 3, 4, 5].map((n) => ({
    item: {
      item_id: `ITM-V-000${n}`, revision_id: 'REV-0001', sequence: n, title: `รายการตรวจสอบตัวอย่างที่ ${n}`,
      inspection_point: null, method: null, standard: null, instruction: null, frequency: 'DAILY',
      required_photo_on_fail: false, required_remark_on_fail: false, is_critical: false, reference_image: null,
      item_key: `KEY-ITM-V-000${n}`,
    },
    due_reason: 'DAILY',
    last_result_date: null,
  })),
  submitted_inspection_id: null,
}

interface Measurement {
  page: string
  state: string
  viewport: string
  scrollWidth: number
  clientWidth: number
  inputWidth: number
  inputRight: number
}

async function measure(page: Page, label: string, state: string, viewport: string, out: Measurement[]) {
  const m = await page.evaluate(() => {
    const input = document.querySelector('.photo-attachment-field__input')
    const box = input?.getBoundingClientRect()
    return {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      inputWidth: Math.round(box?.width ?? -1),
      inputRight: Math.round(box?.right ?? -1),
    }
  })
  out.push({ page: label, state, viewport, ...m })
  expect(m.inputWidth, `${label} / ${state} / ${viewport}: the photo field must be rendered`).toBeGreaterThanOrEqual(0)
  // Soft: a failing test still measures (and reports) every viewport and state.
  expect.soft(m.scrollWidth, `${label} / ${state} / ${viewport}: no horizontal page overflow`).toBeLessThanOrEqual(m.clientWidth)
}

async function forEachViewport(browser: Browser, baseURL: string, fn: (page: Page, viewport: string) => Promise<void>) {
  for (const v of VIEWPORTS) {
    const context = await browser.newContext({
      baseURL,
      viewport: { width: v.width, height: v.height },
      isMobile: v.mobile,
      hasTouch: v.mobile,
    })
    const page = await context.newPage()
    try {
      await fn(page, v.name)
    } finally {
      await context.close()
    }
  }
}

function report(testInfo: TestInfo, rows: Measurement[]) {
  // Printed (list reporter) and attached as before/after evidence.
  console.log(rows.map((r) => `${r.page} | ${r.state} | ${r.viewport} | scroll ${r.scrollWidth} / client ${r.clientWidth} | input w ${r.inputWidth} right ${r.inputRight}`).join('\n'))
  void testInfo.attach('measurements', { body: JSON.stringify(rows, null, 2), contentType: 'application/json' })
}

test('Repair detail: no horizontal overflow with no photo, while uploading, and with a photo attached', async ({ browser, baseURL }, testInfo) => {
  const rows: Measurement[] = []
  await forEachViewport(browser, baseURL!, async (page, viewport) => {
    const created = await page.request.post('/api/v1/repairs', {
      data: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', source_type: 'MANUAL', symptom: `responsive ${viewport}` },
    })
    expect(created.status()).toBe(200)
    const repairId = (await created.json()).repair.repair_id as string
    await page.goto(`/repairs/${repairId}`)
    await expect(page.getByText('ยังไม่มีรูปแนบ')).toBeVisible()
    await measure(page, 'repair-detail', 'no-photo', viewport, rows)

    // Uploading: hold the real upload until measured, then let it through unchanged.
    let release: () => void = () => {}
    const held = new Promise<void>((resolve) => (release = resolve))
    await page.route('**/api/v1/attachments', async (route) => {
      await held
      await route.continue()
    })
    const input = page.locator('#action-photo')
    await expect(input).toHaveAttribute('accept', 'image/*')
    await expect(input).toHaveAttribute('capture', 'environment')
    await input.setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: TINY_PNG })
    await expect(page.getByText('กำลังอัปโหลดรูปภาพ...')).toBeVisible()
    await measure(page, 'repair-detail', 'uploading', viewport, rows)
    release()
    await expect(page.getByText('แนบแล้ว 1 รูป')).toBeVisible()
    await expect(page.getByRole('button', { name: 'ลบรูป' })).toBeVisible()
    await measure(page, 'repair-detail', 'photo-attached', viewport, rows)
    await page.unrouteAll()

    // The photo still records with the action (upload and evidence unchanged).
    await page.getByLabel('เพิ่มการดำเนินการ').fill(`responsive evidence ${viewport}`)
    await page.getByRole('button', { name: 'บันทึกการดำเนินการ' }).click()
    // Wait for the reloaded page itself (the saved action and the cleared field), not just
    // an image: the pre-submit thumbnail carries the same alt text, and the page is briefly
    // in its loading state while it reloads after the save.
    await expect(page.getByText(`responsive evidence ${viewport}`)).toBeVisible()
    await expect(page.getByText('ยังไม่มีรูปแนบ')).toBeVisible()
    await expect(page.getByAltText('รูปแนบการดำเนินการ')).toBeVisible()
    await measure(page, 'repair-detail', 'evidence-recorded', viewport, rows)
  })
  report(testInfo, rows)
})

test('PM work-order detail: no horizontal overflow with no photo and with a photo attached', async ({ browser, baseURL }, testInfo) => {
  const rows: Measurement[] = []
  await forEachViewport(browser, baseURL!, async (page, viewport) => {
    const opened = await page.request.post('/api/v1/pm/work-orders', {
      data: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', pm_plan_id: 'PMP-0001' },
    })
    expect(opened.status()).toBe(200)
    const workOrderId = (await opened.json()).work_order.pm_work_order_id as string
    await page.goto(`/pm/work-orders/${workOrderId}`)
    const input = page.locator('input[id^="pm-evidence-"]').first()
    await expect(input).toBeAttached()
    await measure(page, 'pm-detail', 'no-photo', viewport, rows)
    await input.setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: TINY_PNG })
    await expect(page.getByText('แนบแล้ว 1 รูป').first()).toBeVisible()
    await measure(page, 'pm-detail', 'photo-attached', viewport, rows)
  })
  report(testInfo, rows)
})

test('Inspection form (failed item): no horizontal overflow with no photo and with a photo attached', async ({ browser, baseURL }, testInfo) => {
  const rows: Measurement[] = []
  await forEachViewport(browser, baseURL!, async (page, viewport) => {
    // R3 (deliberate migration, contract §4–§6): the form now reads today's due items from
    // GET /inspections/form, and VEH-1046 is inspected for real by another spec today
    // (one inspection per asset per Bangkok date), so only that form READ is intercepted
    // with five due items. Nothing is submitted; the photo upload stays real. The failed
    // result is now labelled 'ผิดปกติ' (R3-15).
    await page.route(/\/api\/v1\/inspections\/form\?/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(R3_FORM) }))
    await page.goto('/vehicle/VEH-1046/inspect')
    await expect(page.getByText('รายการตรวจสอบตัวอย่างที่ 5')).toBeVisible()
    // On the 667x375 landscape phone only a 116 px band is left between the sticky navbar
    // (190 px, unchanged from the base) and the sticky actions (69 px); Playwright's own
    // scroll alignments all land under one of them. Scroll the radio into that band as a
    // user would, then click normally (the hit-target check still applies).
    const failRadio = page.getByRole('radio', { name: 'ผิดปกติ', exact: true }).nth(4)
    await failRadio.evaluate((el) => {
      const top = document.querySelector('header.app-navbar')?.getBoundingClientRect().bottom ?? 0
      const bottom = document.querySelector('.sticky-actions')?.getBoundingClientRect().top ?? window.innerHeight
      const box = el.getBoundingClientRect()
      window.scrollBy(0, box.top + box.height / 2 - (top + bottom) / 2)
    })
    await failRadio.click()
    await expect(page.getByText('รูปถ่ายหลักฐาน (ถ้ามี)')).toBeVisible()
    await measure(page, 'inspection-form', 'no-photo', viewport, rows)
    await page.locator('input[type="file"]').setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: TINY_PNG })
    await expect(page.getByRole('button', { name: 'ลบรูป' })).toBeVisible()
    await measure(page, 'inspection-form', 'photo-attached', viewport, rows)
  })
  report(testInfo, rows)
})

test('the photo input stays operable and keyboard-focusable (never removed from the layout)', async ({ page }) => {
  const created = await page.request.post('/api/v1/repairs', {
    data: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', source_type: 'MANUAL', symptom: 'responsive a11y' },
  })
  const repairId = (await created.json()).repair.repair_id as string
  await page.goto(`/repairs/${repairId}`)
  const input = page.locator('#action-photo')
  await expect(input).toBeEnabled()
  const style = await input.evaluate((el) => {
    const s = getComputedStyle(el)
    return { display: s.display, visibility: s.visibility }
  })
  expect(style.display).not.toBe('none')
  expect(style.visibility).toBe('visible')
  await input.focus()
  await expect(input).toBeFocused()
  // The visible trigger is the field's own label (clicking it opens the chooser).
  await expect(page.locator('label[for="action-photo"]')).toHaveText('ถ่ายรูป / เลือกรูป')
})
