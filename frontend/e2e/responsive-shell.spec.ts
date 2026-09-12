import { expect, test } from '@playwright/test'

// Mobile-first acceptance check required by the Phase 1 spec update:
// "Phase 1 acceptance must include at least one smartphone-size rendering
// test." Runs across three real viewport profiles (smartphone-portrait,
// tablet-portrait, desktop — see playwright.config.ts projects) against
// the actual Vite dev server + backend, not just component unit tests.

test('home page has no unintended horizontal scrolling', async ({ page }) => {
  await page.goto('/')

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))

  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
  await expect(page.getByText('ระบบบำรุงรักษาเครน', { exact: true })).toBeVisible()
})

test('touch targets in the nav meet the 44px minimum', async ({ page }) => {
  await page.goto('/')

  const toggle = page.getByRole('button', { name: /เปิดเมนู|ปิดเมนู/ })
  if (await toggle.isVisible()) {
    const box = await toggle.boundingBox()
    expect(box?.width).toBeGreaterThanOrEqual(44)
    expect(box?.height).toBeGreaterThanOrEqual(44)
  }

  const homeLink = page.getByRole('link', { name: 'หน้าหลัก' })
  if (!(await homeLink.isVisible())) {
    await toggle.click()
  }
  const linkBox = await homeLink.boundingBox()
  expect(linkBox?.height).toBeGreaterThanOrEqual(44)
})

test('mobile menu toggle expands and collapses navigation', async ({ page }, testInfo) => {
  await page.goto('/')

  const toggle = page.getByRole('button', { name: 'เปิดเมนู' })

  if (testInfo.project.name === 'smartphone-portrait') {
    await expect(toggle).toBeVisible()
    await toggle.click()
    await expect(page.getByRole('link', { name: 'สถานะระบบ' })).toBeVisible()
    await page.getByRole('link', { name: 'สถานะระบบ' }).click()
    await expect(page).toHaveURL(/system-status/)
  } else {
    // From tablet width up the full menu is always visible and the
    // toggle button is hidden by CSS.
    await expect(toggle).toBeHidden()
    await expect(page.getByRole('link', { name: 'สถานะระบบ' })).toBeVisible()
  }
})

test('system status page renders and the confirmation dialog fits the viewport', async ({
  page,
}) => {
  await page.goto('/system-status')

  await expect(page.getByText('พร้อมใช้งาน', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'โหลดสถานะใหม่' }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()

  const viewport = page.viewportSize()
  const box = await dialog.boundingBox()
  expect(viewport).not.toBeNull()
  expect(box).not.toBeNull()
  if (viewport && box) {
    expect(box.width).toBeLessThanOrEqual(viewport.width + 1)
    expect(box.height).toBeLessThanOrEqual(viewport.height + 1)
  }

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})
