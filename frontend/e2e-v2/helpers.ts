import { expect, type Browser, type Page, type TestInfo } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/** Synthetic B2 fixtures (mock batch MOCK-7O2B-SYNTHETIC, all TEST and ACTIVE). */
export const TEST_TECHNICIANS = ['TEC-TEST-901', 'TEC-TEST-911', 'TEC-TEST-912']
export const REAL_SEED_TECHNICIANS = ['TEC-TEST-001', 'TEC-TEST-002']
export const LINKED = [
  { technicianId: 'TEC-TEST-911', userId: 'USR-TEST-911', name: 'ช่างทดสอบ ลำดับหนึ่ง' },
  { technicianId: 'TEC-TEST-912', userId: 'USR-TEST-912', name: 'ช่างทดสอบ ลำดับสอง' },
]
export const VEHICLE = 'VEH-1046'

export interface TraceEntry {
  method: string
  url: string
  status?: number
  body?: unknown
}

/** Records every /api request the page makes (method, path, JSON body, status). */
export function recordApi(page: Page): TraceEntry[] {
  const entries: TraceEntry[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) return
    let body: unknown
    try {
      body = request.postDataJSON() ?? undefined
    } catch {
      body = request.postData() ?? undefined
    }
    entries.push({ method: request.method(), url: url.pathname + url.search, body })
  })
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (!url.pathname.startsWith('/api/')) return
    const entry = [...entries].reverse().find((e) => e.url === url.pathname + url.search && e.status === undefined)
    if (entry) entry.status = response.status()
  })
  return entries
}

/** Optional happy-path trace evidence (V2_E2E_TRACE_DIR), never required for the test result. */
export function saveTrace(testInfo: TestInfo, name: string, data: unknown) {
  const dir = process.env.V2_E2E_TRACE_DIR
  if (!dir) return
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, `${testInfo.project.name}--${name}.json`), JSON.stringify(data, null, 2))
}

export async function asRole(browser: Browser, baseURL: string, role: string, userId: string) {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'X-Dev-Role': role, 'X-Dev-User-Id': userId } })
  return { context, page: await context.newPage() }
}

export function jobIdFrom(page: Page, pattern: RegExp): string {
  const match = page.url().match(pattern)
  if (!match) throw new Error(`no job id in ${page.url()}`)
  return decodeURIComponent(match[1])
}

/** No horizontal page overflow and touch-sized primary buttons (responsive check). */
export async function expectResponsive(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  for (const button of await page.locator('.page .button--primary:visible').all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
}

export function queueRow(page: Page, kind: 'REPAIR' | 'PM', jobId: string) {
  return page
    .getByTestId(`v2-waiting-${kind}`)
    .locator('tr', { has: page.getByRole('link', { name: jobId, exact: true }) })
}
