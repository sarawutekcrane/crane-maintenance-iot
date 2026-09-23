import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OpenRepairQueuePage } from './OpenRepairQueuePage'
import type { RepairSummary } from '../lib/types'

// Phase 7 Batch 7C2 — synthetic payloads only (SYN-* ids).

const QUEUE_PATH = '/api/v1/repairs/open-queue'
const RANGE = /^แสดงรายการที่ \d+–\d+ จาก \d+ ใบงานที่ระบบส่งกลับ$/

function repair(id: string, overrides: Partial<RepairSummary> = {}): RepairSummary {
  return {
    repair_id: id,
    asset_type: 'VEHICLE',
    asset_id: 'SYN-VEH-1',
    source_type: 'MANUAL',
    source_id: null,
    status: 'OPEN',
    opened_at: '2026-01-15T02:15:00Z',
    closed_at: null,
    action_count: 0,
    primary_technician: null,
    collaborators: [],
    symptom: 'เสียงดังผิดปกติ',
    ...overrides,
  }
}

function pageOf(items: RepairSummary[], total: number, page = 1, pageSize = 50) {
  return { items, page, page_size: pageSize, total_items: total }
}

function repairs(from: number, count: number, prefix = 'SYN-RPR') {
  return Array.from({ length: count }, (_, i) => repair(`${prefix}-${from + i}`))
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function errorResponse(code: string, status: number, requestId = 'req-7c2') {
  return jsonResponse({ error: { code, message: 'synthetic', details: null, request_id: requestId } }, status)
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

interface Call {
  path: string
  method: string
  params: Record<string, string>
}

/** Each fetch takes the next queued response (or promise). */
function installFetch(queue: Array<Response | Promise<Response> | Error>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push({
      path: url.pathname,
      method: (init?.method ?? 'GET').toUpperCase(),
      params: Object.fromEntries(url.searchParams),
    })
    const next = queue.shift()
    if (next === undefined) throw new Error(`Unexpected fetch: ${url.toString()}`)
    if (next instanceof Error) throw next
    return next
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, queue }
}

function renderPage(strict = false) {
  const tree = (
    <BrowserRouter>
      <OpenRepairQueuePage />
    </BrowserRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

const rangeText = () => screen.queryByText(RANGE)
const dataRows = () => screen.queryAllByRole('row').slice(1)

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('OpenRepairQueuePage', () => {
  it('renders the Thai title, scope notes, columns and range for the first page', async () => {
    const { calls } = installFetch([jsonResponse(pageOf(repairs(1, 50), 120))])
    renderPage()

    expect(screen.getByRole('heading', { name: 'งานซ่อมค้าง' })).toBeInTheDocument()
    expect(
      screen.getByText(
        'รายการใบงานซ่อมที่ระบบจัดเป็น “ยังไม่ปิดงาน” ทั้งยานพาหนะและเครื่องมือ/อุปกรณ์ สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุง',
      ),
    ).toBeInTheDocument()
    for (const note of [
      'นับเป็นจำนวนใบงานซ่อม ไม่ใช่จำนวนคัน รถหนึ่งคันอาจมีหลายใบงาน',
      '“ยังไม่ปิดงาน” เป็นการจัดประเภทของระบบ ไม่ได้ยืนยันสภาพจริงของเครื่อง',
      'ใบงานที่ช่องสถานะว่างจะถูกจัดเป็น “ยังไม่ปิดงาน” และใบงานที่ไม่ได้ระบุประเภทสินทรัพย์จะแสดงเป็นยานพาหนะ ตามค่าเริ่มต้นของระบบเดิม',
      'เวลาที่มีเขตเวลากำกับจะแสดงตามเวลาประเทศไทย ส่วนข้อมูลที่ไม่ระบุเขตเวลาจะแสดงตามที่บันทึกพร้อมคำกำกับ',
    ]) {
      expect(screen.getByText(note)).toBeInTheDocument()
    }
    const requestNote = screen.getByText(/ไม่รวมรายการแจ้งซ่อมที่ยังรอตรวจรับ — ดูที่/)
    expect(within(requestNote).getByRole('link', { name: '“แจ้งซ่อมรอตรวจรับ”' })).toHaveAttribute(
      'href',
      '/repair-request-queue',
    )

    expect(await screen.findByText('แสดงรายการที่ 1–50 จาก 120 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual([
      'เลขที่ใบงานซ่อม',
      'วันที่เปิดใบงาน',
      'สินทรัพย์',
      'อาการ/ปัญหาที่พบ',
      'ผู้รับผิดชอบ (ตามที่บันทึกในใบงาน)',
    ])
    expect(dataRows()).toHaveLength(50)
    const pager = screen.getByRole('navigation', { name: 'เปลี่ยนหน้ารายการงานซ่อมค้าง' })
    expect(within(pager).getByText('หน้า 1 จาก 3')).toBeInTheDocument()
    expect(within(pager).getByRole('button', { name: 'ก่อนหน้า' })).toBeDisabled()
    expect(within(pager).getByRole('button', { name: 'ถัดไป' })).toBeEnabled()
    expect(screen.getByLabelText('ประเภทสินทรัพย์')).toHaveValue('')
    expect(calls).toEqual([{ path: QUEUE_PATH, method: 'GET', params: { page: '1', page_size: '50' } }])
  })

  it('pages with the filter preserved, resets to page 1 on filter change, and refreshes in place', async () => {
    const user = userEvent.setup()
    const { calls, queue } = installFetch([jsonResponse(pageOf(repairs(1, 50), 120))])
    renderPage()
    await screen.findByText('แสดงรายการที่ 1–50 จาก 120 ใบงานที่ระบบส่งกลับ')

    queue.push(jsonResponse(pageOf(repairs(51, 50), 120, 2)))
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    expect(await screen.findByText('แสดงรายการที่ 51–100 จาก 120 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
    expect(screen.getByText('หน้า 2 จาก 3')).toBeInTheDocument()

    queue.push(jsonResponse(pageOf(repairs(1, 50, 'SYN-EQP-RPR').map((r) => ({ ...r, asset_type: 'EQUIPMENT' as const })), 70)))
    await user.selectOptions(screen.getByLabelText('ประเภทสินทรัพย์'), 'EQUIPMENT')
    expect(await screen.findByText('แสดงรายการที่ 1–50 จาก 70 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()

    queue.push(jsonResponse(pageOf(repairs(51, 20, 'SYN-EQP-RPR'), 70, 2)))
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    expect(await screen.findByText('แสดงรายการที่ 51–70 จาก 70 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ถัดไป' })).toBeDisabled()

    queue.push(jsonResponse(pageOf(repairs(51, 20, 'SYN-EQP-RPR'), 70, 2)))
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    await screen.findByText('แสดงรายการที่ 51–70 จาก 70 ใบงานที่ระบบส่งกลับ')

    queue.push(jsonResponse(pageOf(repairs(1, 50), 120)))
    await user.selectOptions(screen.getByLabelText('ประเภทสินทรัพย์'), '')
    await screen.findByText('แสดงรายการที่ 1–50 จาก 120 ใบงานที่ระบบส่งกลับ')

    expect(calls.map((c) => c.params)).toEqual([
      { page: '1', page_size: '50' },
      { page: '2', page_size: '50' },
      { page: '1', page_size: '50', asset_type: 'EQUIPMENT' },
      { page: '2', page_size: '50', asset_type: 'EQUIPMENT' },
      { page: '2', page_size: '50', asset_type: 'EQUIPMENT' },
      { page: '1', page_size: '50' },
    ])
    expect(calls.every((c) => c.method === 'GET' && c.path === QUEUE_PATH)).toBe(true)
  })

  it('distinguishes the unfiltered empty state, the filtered empty state and an out-of-range page', async () => {
    const user = userEvent.setup()
    const { calls, queue } = installFetch([jsonResponse(pageOf([], 0))])
    renderPage()
    expect(await screen.findByText('ระบบไม่พบใบงานซ่อมที่ยังไม่ปิดงาน')).toBeInTheDocument()
    expect(
      screen.getByText(
        'ไม่มีใบงานซ่อมที่ตรงเงื่อนไขส่งกลับจากระบบ รายการแจ้งซ่อมที่รอตรวจรับแสดงแยกที่ “แจ้งซ่อมรอตรวจรับ”',
      ),
    ).toBeInTheDocument()
    expect(rangeText()).toBeNull()
    expect(screen.queryByRole('navigation', { name: 'เปลี่ยนหน้ารายการงานซ่อมค้าง' })).toBeNull()

    queue.push(jsonResponse(pageOf([], 0)))
    await user.selectOptions(screen.getByLabelText('ประเภทสินทรัพย์'), 'VEHICLE')
    expect(await screen.findByText('ไม่พบใบงานซ่อมที่ยังไม่ปิดงานสำหรับประเภทสินทรัพย์นี้')).toBeInTheDocument()
    expect(screen.queryByText('ระบบไม่พบใบงานซ่อมที่ยังไม่ปิดงาน')).toBeNull()

    // Out of range: the server returns no items but a non-zero total.
    queue.push(jsonResponse(pageOf(repairs(1, 50), 60)))
    queue.push(jsonResponse(pageOf([], 40, 2)))
    await user.selectOptions(screen.getByLabelText('ประเภทสินทรัพย์'), 'EQUIPMENT')
    await screen.findByText('แสดงรายการที่ 1–50 จาก 60 ใบงานที่ระบบส่งกลับ')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    expect(await screen.findByText('หน้านี้ไม่มีรายการแล้ว')).toBeInTheDocument()
    expect(screen.getByText('ข้อมูลอาจเปลี่ยนไประหว่างเปลี่ยนหน้า ขณะนี้ระบบส่งกลับ 40 ใบงานตามเงื่อนไขนี้')).toBeInTheDocument()
    expect(screen.queryByText(/ไม่พบใบงานซ่อม/)).toBeNull()
    expect(rangeText()).toBeNull()

    queue.push(jsonResponse(pageOf(repairs(1, 40), 40)))
    await user.click(screen.getByRole('button', { name: 'กลับไปหน้าแรก' }))
    expect(await screen.findByText('แสดงรายการที่ 1–40 จาก 40 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
    expect(calls.at(-1)?.params).toEqual({ page: '1', page_size: '50', asset_type: 'EQUIPMENT' })
  })

  it('shows the permission-denied state for 403 without rows or totals', async () => {
    installFetch([errorResponse('HTTP_ERROR', 403)])
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(screen.getByText('หน้านี้สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุงเท่านั้น')).toBeInTheDocument()
    expect(rangeText()).toBeNull()
    expect(dataRows()).toHaveLength(0)
  })

  it('shows schema and read errors with request ids, and retry sends one new request', async () => {
    const user = userEvent.setup()
    const { calls, queue } = installFetch([errorResponse('REPAIR_ORDER_SCHEMA_INVALID', 500, 'req-schema')])
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('ไม่แสดงรายการงานซ่อมค้าง')).toBeInTheDocument()
    expect(
      within(alert).getByText(
        'โครงสร้างข้อมูลใบงานซ่อมไม่ถูกต้อง จึงไม่แสดงรายการเพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลระบบ',
      ),
    ).toBeInTheDocument()
    expect(within(alert).getByText('รหัสอ้างอิง: req-schema')).toBeInTheDocument()
    expect(rangeText()).toBeNull()

    queue.push(errorResponse('REPAIR_ORDER_READ_FAILED', 503, 'req-read'))
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(await screen.findByText('โหลดงานซ่อมค้างไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.getByText('ไม่สามารถอ่านข้อมูลใบงานซ่อมได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()
    expect(screen.getByText('รหัสอ้างอิง: req-read')).toBeInTheDocument()

    queue.push(new TypeError('Failed to fetch'))
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(await screen.findByText('โหลดงานซ่อมค้างไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.getByText('เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()

    queue.push(jsonResponse(pageOf(repairs(1, 3), 3)))
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(await screen.findByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    // No automatic retry: exactly one request per user action.
    expect(calls).toHaveLength(4)
  })

  it('hides old rows and totals while reloading and keeps refresh available', async () => {
    const user = userEvent.setup()
    const pending = deferred<Response>()
    const { queue } = installFetch([jsonResponse(pageOf(repairs(1, 5), 5))])
    renderPage()
    await screen.findByText('แสดงรายการที่ 1–5 จาก 5 ใบงานที่ระบบส่งกลับ')

    queue.push(pending.promise)
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    expect(screen.getByText('กำลังโหลดงานซ่อมค้าง...')).toBeInTheDocument()
    expect(rangeText()).toBeNull()
    expect(dataRows()).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' })).toBeEnabled()

    await act(async () => pending.resolve(jsonResponse(pageOf(repairs(1, 2), 2))))
    expect(await screen.findByText('แสดงรายการที่ 1–2 จาก 2 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
  })

  it('never lets an older success or error replace the newest result', async () => {
    const user = userEvent.setup()
    const first = deferred<Response>()
    const second = deferred<Response>()
    const third = deferred<Response>()
    const { queue } = installFetch([first.promise])
    renderPage()

    queue.push(second.promise)
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    queue.push(third.promise)
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))

    // Newest succeeds first; the two older requests then finish late.
    await act(async () => third.resolve(jsonResponse(pageOf(repairs(1, 3), 3))))
    await screen.findByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')
    await act(async () => first.resolve(jsonResponse(pageOf(repairs(1, 9), 9))))
    await act(async () => second.resolve(errorResponse('REPAIR_ORDER_READ_FAILED', 503)))
    expect(screen.getByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()

    // Newest fails; an older success must not replace that error.
    const fourth = deferred<Response>()
    const fifth = deferred<Response>()
    queue.push(fourth.promise)
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    queue.push(fifth.promise)
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    await act(async () => fifth.resolve(errorResponse('REPAIR_ORDER_SCHEMA_INVALID', 500, 'req-newest')))
    await screen.findByText('รหัสอ้างอิง: req-newest')
    await act(async () => fourth.resolve(jsonResponse(pageOf(repairs(1, 7), 7))))
    expect(screen.getByText('รหัสอ้างอิง: req-newest')).toBeInTheDocument()
    expect(rangeText()).toBeNull()
  })

  it('builds encoded links from the original values and guards blank ids', async () => {
    installFetch([
      jsonResponse(
        pageOf(
          [
            repair('RPR/1 #?%', { asset_id: 'VEH 1/2' }),
            repair('SYN-RPR-EQ', { asset_type: 'EQUIPMENT', asset_id: 'EQP?x=1' }),
            repair('   ', { asset_id: '' }),
            repair('', { asset_id: '  ' }),
            repair(' SYN-RPR-SPACED ', { asset_id: 'SYN-VEH-9' }),
          ],
          5,
        ),
      ),
    ])
    renderPage()
    await screen.findByText('แสดงรายการที่ 1–5 จาก 5 ใบงานที่ระบบส่งกลับ')

    expect(screen.getByRole('link', { name: 'RPR/1 #?%' })).toHaveAttribute('href', '/repairs/RPR%2F1%20%23%3F%25')
    expect(screen.getByRole('link', { name: 'ยานพาหนะ VEH 1/2' })).toHaveAttribute('href', '/vehicle/VEH%201%2F2')
    expect(screen.getByRole('link', { name: 'เครื่องมือ/อุปกรณ์ EQP?x=1' })).toHaveAttribute(
      'href',
      '/equipment/EQP%3Fx%3D1',
    )
    // Original value, no trimming/normalization.
    expect(screen.getByRole('link', { name: 'SYN-RPR-SPACED' })).toHaveAttribute(
      'href',
      '/repairs/%20SYN-RPR-SPACED%20',
    )
    expect(screen.getAllByText('(ไม่มีเลขที่ใบงาน)')).toHaveLength(2)
    expect(screen.getAllByText('ยานพาหนะ (ไม่มีรหัสสินทรัพย์)')).toHaveLength(2)
    const blankRows = dataRows().filter((row) => within(row).queryByText('(ไม่มีเลขที่ใบงาน)'))
    for (const row of blankRows) expect(within(row).queryAllByRole('link')).toHaveLength(0)
    expect(dataRows()).toHaveLength(5)
  })

  it('renders every duplicate-id row without links or React key warnings, counts unchanged', async () => {
    const consoleError = vi.spyOn(console, 'error')
    installFetch([
      jsonResponse(
        pageOf(
          [
            repair('SYN-RPR-DUP', { asset_id: 'SYN-VEH-1' }),
            repair('SYN-RPR-OK'),
            repair('SYN-RPR-DUP', { asset_id: 'SYN-VEH-2' }),
            repair('syn-rpr-dup'),
          ],
          4,
        ),
      ),
    ])
    renderPage()
    await screen.findByText('แสดงรายการที่ 1–4 จาก 4 ใบงานที่ระบบส่งกลับ')

    expect(dataRows()).toHaveLength(4)
    expect(screen.getAllByText('เลขที่ใบงานซ้ำในข้อมูล — เปิดรายละเอียดจากรายการนี้ไม่ได้')).toHaveLength(2)
    expect(screen.queryByRole('link', { name: /^SYN-RPR-DUP/ })).toBeNull()
    expect(screen.getByRole('link', { name: 'SYN-RPR-OK' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'syn-rpr-dup' })).toBeInTheDocument() // exact comparison
    // Asset links of duplicate rows still work.
    expect(screen.getByRole('link', { name: 'ยานพาหนะ SYN-VEH-2' })).toBeInTheDocument()
    const keyWarnings = consoleError.mock.calls.filter((args) => String(args[0]).includes('same key'))
    expect(keyWarnings).toHaveLength(0)
  })

  it('formats opened_at for this report only and preserves the assignment rendering', async () => {
    installFetch([
      jsonResponse(
        pageOf(
          [
            repair('SYN-RPR-1', { opened_at: '2026-01-15T02:15:00Z', primary_technician: 'syn-tech-1', collaborators: ['a', 'b'] }),
            repair('SYN-RPR-2', { opened_at: '1970-01-01T00:00:00Z' }),
            repair('SYN-RPR-3', { opened_at: '2026-01-15T08:00:00', symptom: null }),
          ],
          3,
        ),
      ),
    ])
    renderPage()
    await screen.findByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')
    expect(screen.getByText('15 ม.ค. 2569 09:15')).toBeInTheDocument()
    expect(screen.getByText('ไม่มีวันที่เปิดใบงานที่อ่านได้')).toBeInTheDocument()
    expect(screen.getByText('2026-01-15T08:00:00 (ไม่ระบุเขตเวลา)')).toBeInTheDocument()
    expect(screen.getByText('syn-tech-1 +2')).toBeInTheDocument()
    expect(screen.getAllByText('ยังไม่มอบหมาย')).toHaveLength(2)
    expect(screen.getByText('-')).toBeInTheDocument()
  })

  it('uses work-order units and makes no PM, age, overdue or physical-defect claims', async () => {
    installFetch([jsonResponse(pageOf(repairs(1, 3), 3))])
    const { container } = renderPage()
    await screen.findByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/\d+ คัน/)
    expect(text).not.toMatch(/PM|อายุ|เกินกำหนด|ค้างมาแล้ว|วันที่ค้าง|ชำรุดจริง/)
    // The constant OPEN status column is removed on this page.
    expect(screen.queryByRole('columnheader', { name: 'สถานะ' })).toBeNull()
    expect(screen.queryByText('ยังไม่ปิดงาน', { selector: '.status-badge' })).toBeNull()
  })

  it('sends at most two page-owned GETs on a StrictMode mount and exactly one per refresh', async () => {
    const user = userEvent.setup()
    const { calls, queue } = installFetch([
      jsonResponse(pageOf(repairs(1, 9), 9)),
      jsonResponse(pageOf(repairs(1, 3), 3)),
    ])
    renderPage(true)
    // StrictMode (development) repeats the mount effect: only the latest applies.
    await screen.findByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')
    expect(calls.length).toBeLessThanOrEqual(2)
    const mountCalls = calls.length

    queue.push(jsonResponse(pageOf(repairs(1, 4), 4)))
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    await screen.findByText('แสดงรายการที่ 1–4 จาก 4 ใบงานที่ระบบส่งกลับ')
    expect(calls.length).toBe(mountCalls + 1)
    // Only the page's own list endpoint: no per-row or detail requests.
    expect(calls.every((c) => c.path === QUEUE_PATH && c.method === 'GET')).toBe(true)
  })
})
