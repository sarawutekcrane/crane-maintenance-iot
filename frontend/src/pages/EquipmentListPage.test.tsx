import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EquipmentListPage } from './EquipmentListPage'
import type { Equipment, EquipmentCategory, Page } from '../lib/types'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('EquipmentListPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              equipment_id: 'EQP-0001',
              equipment_code: 'LATHE-01',
              name: 'เครื่องกลึงเบอร์ 1',
              category: 'LATHE',
              serial_number: 'LT-2019-0021',
              location: 'โรงซ่อมกลาง',
              operational_status: 'IN_USE',
              created_at: '2026-01-15T08:00:00Z',
              updated_at: '2026-01-15T08:00:00Z',
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders equipment separately from vehicles with a link to its detail page', async () => {
    render(
      <BrowserRouter>
        <EquipmentListPage />
      </BrowserRouter>,
    )

    await waitFor(() =>
      expect(screen.getByText('เครื่องกลึงเบอร์ 1')).toBeInTheDocument(),
    )
    expect(screen.getAllByText('เครื่องกลึง').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'EQP-0001' })).toHaveAttribute(
      'href',
      '/equipment/EQP-0001',
    )
  })
})

// ---------------------------------------------------------------------------
// Phase 7 Batch 7F2 — search completeness (synthetic payloads only).
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50
const LIST_PATH = '/api/v1/equipment'

function eq(id: string, overrides: Partial<Equipment> = {}): Equipment {
  return {
    equipment_id: id,
    equipment_code: `CODE-${id}`,
    name: `เครื่องมือ ${id}`,
    category: 'LATHE',
    serial_number: null,
    location: null,
    operational_status: 'READY',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
    ...overrides,
  }
}

function seq(count: number, prefix = 'EQP', overrides: Partial<Equipment> = {}): Equipment[] {
  return Array.from({ length: count }, (_, i) => eq(`${prefix}-${String(i + 1).padStart(4, '0')}`, overrides))
}

interface Call {
  path: string
  params: URLSearchParams
  method: string
}

type Reply = { status: number; body: unknown }

/** A backend-like responder: whole-population filter, then page slice. */
function serve(dataset: Equipment[], params: URLSearchParams): Reply {
  const q = (params.get('q') ?? '').toLowerCase()
  const category = params.get('category')
  const page = Number(params.get('page') ?? '1')
  const size = Number(params.get('page_size') ?? '20')
  const matching = dataset.filter(
    (e) =>
      (!q || e.name.toLowerCase().includes(q) || e.equipment_code.toLowerCase().includes(q)) &&
      (!category || e.category === category),
  )
  const body: Page<Equipment> = {
    items: matching.slice((page - 1) * size, page * size),
    page,
    page_size: size,
    total_items: matching.length,
  }
  return { status: 200, body }
}

function errorReply(status: number, code: string, requestId = 'req-err'): Reply {
  return { status, body: { error: { code, message: code, request_id: requestId } } }
}

/**
 * Installs a fetch stub. Every call is recorded; `respond` decides the
 * reply. When `respond` returns undefined the call stays pending until the
 * test resolves it through `pending` — used for real response reordering.
 */
function installFetch(respond: (call: Call) => Reply | undefined) {
  const calls: Call[] = []
  const pending: Array<{ call: Call; resolve: (reply: Reply) => void }> = []
  const stub = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const call: Call = { path: url.pathname, params: url.searchParams, method: init?.method ?? 'GET' }
    calls.push(call)
    const toResponse = (reply: Reply) =>
      new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    const reply = respond(call)
    if (reply) return Promise.resolve(toResponse(reply))
    return new Promise<Response>((resolve) => {
      pending.push({ call, resolve: (r) => resolve(toResponse(r)) })
    })
  })
  vi.stubGlobal('fetch', stub)
  return { calls, pending }
}

function renderPage() {
  return render(
    <BrowserRouter>
      <EquipmentListPage />
    </BrowserRouter>,
  )
}

const rangeText = (first: number, last: number, total: number) =>
  `พบ ${total} รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ ${first}–${last} จาก ${total} รายการ`

function bodyRows(): HTMLElement[] {
  const table = screen.getByRole('table')
  return within(table).getAllByRole('row').slice(1)
}

const next = () => screen.getByRole('button', { name: 'ถัดไป' })
const prev = () => screen.getByRole('button', { name: 'ก่อนหน้า' })
const qInput = () => screen.getByLabelText('ค้นหา (ชื่อ หรือ รหัส)')
const categorySelect = () => screen.getByLabelText('ประเภท')

describe('EquipmentListPage — 7F2 paging, totals and applied criteria', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows the whole result through explicit paging with accurate totals and boundaries', async () => {
    const data = seq(120)
    const { calls } = installFetch((c) => serve(data, c.params))
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText(rangeText(1, 50, 120))).toBeInTheDocument()
    expect(screen.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeInTheDocument()
    expect(screen.getByText('หน้า 1 จาก 3')).toBeInTheDocument()
    expect(bodyRows()).toHaveLength(50)
    expect(prev()).toBeDisabled()
    expect(next()).toBeEnabled()
    expect(calls).toHaveLength(1)
    expect(calls[0].path).toBe(LIST_PATH)
    expect(calls[0].params.get('page')).toBe('1')
    expect(calls[0].params.get('page_size')).toBe('50')
    expect(calls[0].params.has('q')).toBe(false)
    expect(calls[0].params.has('category')).toBe(false)

    await user.click(next())
    expect(await screen.findByText(rangeText(51, 100, 120))).toBeInTheDocument()
    await user.click(next())
    expect(await screen.findByText(rangeText(101, 120, 120))).toBeInTheDocument()
    expect(screen.getByText('หน้า 3 จาก 3')).toBeInTheDocument()
    expect(bodyRows()).toHaveLength(20)
    expect(within(bodyRows()[19]).getByRole('link', { name: 'EQP-0120' })).toBeInTheDocument()
    expect(next()).toBeDisabled()
    expect(prev()).toBeEnabled()

    await user.click(prev())
    expect(await screen.findByText(rangeText(51, 100, 120))).toBeInTheDocument()
    expect(calls.map((c) => c.params.get('page'))).toEqual(['1', '2', '3', '2'])
  })

  it('exactly 50 matches is a single page with both navigation buttons disabled', async () => {
    const data = seq(50)
    installFetch((c) => serve(data, c.params))
    renderPage()
    expect(await screen.findByText(rangeText(1, 50, 50))).toBeInTheDocument()
    expect(screen.getByText('หน้า 1 จาก 1')).toBeInTheDocument()
    expect(prev()).toBeDisabled()
    expect(next()).toBeDisabled()
  })

  it('editing sends nothing; "ค้นหา" applies q and category together from page 1', async () => {
    const data = [
      ...seq(60, 'LAT', { category: 'LATHE', name: 'เครื่องกลึงพิเศษ' }),
      ...seq(5, 'WLD', { category: 'WELDING', name: 'เครื่องเชื่อมพิเศษ' }),
      ...seq(5, 'OTH', { category: 'LATHE', name: 'อื่น' }),
    ]
    const { calls } = installFetch((c) => serve(data, c.params))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 70))

    await user.type(qInput(), '  พิเศษ ')
    await user.selectOptions(categorySelect(), 'LATHE')
    expect(calls).toHaveLength(1)
    expect(screen.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    expect(await screen.findByText(rangeText(1, 50, 60))).toBeInTheDocument()
    expect(calls).toHaveLength(2)
    expect(calls[1].params.get('q')).toBe('พิเศษ')
    expect(calls[1].params.get('category')).toBe('LATHE')
    expect(calls[1].params.get('page')).toBe('1')
    expect(screen.getByText('เงื่อนไขที่ใช้: คำค้น "พิเศษ" · ประเภท เครื่องกลึง')).toBeInTheDocument()
  })

  it('unsubmitted draft changes do not affect paging', async () => {
    const data = seq(80, 'LAT', { name: 'เครื่องกลึง' })
    const { calls } = installFetch((c) => serve(data, c.params))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 80))
    await user.type(qInput(), 'กลึง')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('เงื่อนไขที่ใช้: คำค้น "กลึง"')

    await user.clear(qInput())
    await user.type(qInput(), 'ไม่ได้ส่ง')
    await user.selectOptions(categorySelect(), 'WELDING')
    await user.click(next())
    expect(await screen.findByText(rangeText(51, 80, 80))).toBeInTheDocument()
    const last = calls[calls.length - 1]
    expect(last.params.get('q')).toBe('กลึง')
    expect(last.params.has('category')).toBe(false)
    expect(last.params.get('page')).toBe('2')
    expect(screen.getByText('เงื่อนไขที่ใช้: คำค้น "กลึง"')).toBeInTheDocument()
  })

  it('"ล้างตัวกรอง" clears draft and applied filters and requests unfiltered page 1 in one action', async () => {
    const data = seq(120, 'LAT', { name: 'เครื่องกลึง' })
    const { calls } = installFetch((c) => serve(data, c.params))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 120))
    await user.type(qInput(), 'กลึง')
    await user.selectOptions(categorySelect(), 'LATHE')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('เงื่อนไขที่ใช้: คำค้น "กลึง" · ประเภท เครื่องกลึง')
    await user.click(next())
    await screen.findByText(rangeText(51, 100, 120))

    const before = calls.length
    await user.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }))
    expect(await screen.findByText(rangeText(1, 50, 120))).toBeInTheDocument()
    expect(calls).toHaveLength(before + 1)
    const last = calls[calls.length - 1]
    expect(last.params.get('page')).toBe('1')
    expect(last.params.has('q')).toBe(false)
    expect(last.params.has('category')).toBe(false)
    expect(qInput()).toHaveValue('')
    expect(categorySelect()).toHaveValue('')
    expect(screen.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeInTheDocument()
  })
})

describe('EquipmentListPage — 7F2 failures, retry, empty and out-of-range', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('initial failure shows an error without rows; retry repeats the same request and recovers', async () => {
    const data = seq(3)
    let fail = true
    const { calls } = installFetch((c) =>
      fail ? errorReply(503, 'REPOSITORY_UNAVAILABLE', 'req-503') : serve(data, c.params),
    )
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByText('โหลดรายการเครื่องมือไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.getByText('รหัสอ้างอิง: req-503')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'เปลี่ยนหน้ารายการเครื่องมือ' })).not.toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(await screen.findByText(rangeText(1, 3, 3))).toBeInTheDocument()
    expect(calls).toHaveLength(2)
    expect(calls[1].params.toString()).toBe(calls[0].params.toString())
  })

  it('later-page failure hides old rows/totals/pager; retry repeats the applied page, not the draft', async () => {
    const data = seq(120, 'LAT', { name: 'เครื่องกลึง' })
    let failPage2 = true
    const { calls } = installFetch((c) =>
      failPage2 && c.params.get('page') === '2' ? errorReply(500, 'INTERNAL_ERROR') : serve(data, c.params),
    )
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 120))
    await user.click(next())
    expect(await screen.findByText('โหลดรายการเครื่องมือไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/พบ 120 รายการ/)).not.toBeInTheDocument()
    expect(screen.queryByText(/เงื่อนไขที่ใช้/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ถัดไป' })).not.toBeInTheDocument()

    await user.type(qInput(), 'ร่างที่ยังไม่ส่ง')
    failPage2 = false
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(await screen.findByText(rangeText(51, 100, 120))).toBeInTheDocument()
    const last = calls[calls.length - 1]
    expect(last.params.get('page')).toBe('2')
    expect(last.params.has('q')).toBe(false)
  })

  it('total_items=0 shows a clear no-match state without a pager', async () => {
    installFetch((c) => serve([], c.params))
    renderPage()
    expect(await screen.findByText('ไม่พบเครื่องมือที่ตรงกับเงื่อนไข')).toBeInTheDocument()
    expect(screen.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ถัดไป' })).not.toBeInTheDocument()
  })

  it('a shrinking dataset yields a separate out-of-range state; "กลับไปหน้าแรก" keeps the applied filters', async () => {
    let data = seq(60, 'LAT', { category: 'WELDING' })
    const { calls } = installFetch((c) => serve(data, c.params))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 60))
    await user.selectOptions(categorySelect(), 'WELDING')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('เงื่อนไขที่ใช้: ประเภท เครื่องเชื่อม')

    data = seq(40, 'LAT', { category: 'WELDING' })
    await user.click(next())
    expect(await screen.findByText('ไม่มีรายการในหน้านี้')).toBeInTheDocument()
    expect(screen.getByText('ขณะนี้ระบบส่งกลับ 40 รายการตามเงื่อนไขนี้')).toBeInTheDocument()
    expect(screen.queryByText('ไม่พบเครื่องมือที่ตรงกับเงื่อนไข')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'กลับไปหน้าแรก' }))
    expect(await screen.findByText(rangeText(1, 40, 40))).toBeInTheDocument()
    const last = calls[calls.length - 1]
    expect(last.params.get('page')).toBe('1')
    expect(last.params.get('category')).toBe('WELDING')
  })
})

describe('EquipmentListPage — 7F2 stale-response protection (deferred responses)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  async function setupTwoPendingSearches() {
    const initial = seq(2, 'INI')
    const { calls, pending } = installFetch((c) => (c.params.has('q') ? undefined : serve(initial, c.params)))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 2, 2))
    await user.type(qInput(), 'old')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await user.clear(qInput())
    await user.type(qInput(), 'new')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await waitFor(() => expect(pending).toHaveLength(2))
    expect(pending[0].call.params.get('q')).toBe('old')
    expect(pending[1].call.params.get('q')).toBe('new')
    return { calls, pending }
  }

  it('an older success arriving after a newer success cannot overwrite it', async () => {
    const { pending } = await setupTwoPendingSearches()
    pending[1].resolve(serve(seq(3, 'NEW'), pending[1].call.params))
    expect(await screen.findByText('เงื่อนไขที่ใช้: คำค้น "new"')).toBeInTheDocument()
    pending[0].resolve({ status: 200, body: { items: seq(7, 'OLD'), page: 1, page_size: 50, total_items: 7 } })
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByText(rangeText(1, 3, 3))).toBeInTheDocument()
    expect(screen.queryByText(/OLD-/)).not.toBeInTheDocument()
    expect(screen.queryByText('เงื่อนไขที่ใช้: คำค้น "old"')).not.toBeInTheDocument()
  })

  it('an older failure arriving after a newer success cannot replace it with an error', async () => {
    const { pending } = await setupTwoPendingSearches()
    pending[1].resolve(serve(seq(3, 'NEW'), pending[1].call.params))
    await screen.findByText(rangeText(1, 3, 3))
    pending[0].resolve(errorReply(503, 'REPOSITORY_UNAVAILABLE'))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText('โหลดรายการเครื่องมือไม่สำเร็จ')).not.toBeInTheDocument()
    expect(screen.getByText(rangeText(1, 3, 3))).toBeInTheDocument()
  })

  it('an older success arriving after a newer failure cannot replace the error with old rows', async () => {
    const { pending, calls } = await setupTwoPendingSearches()
    pending[1].resolve(errorReply(500, 'INTERNAL_ERROR'))
    expect(await screen.findByText('โหลดรายการเครื่องมือไม่สำเร็จ')).toBeInTheDocument()
    pending[0].resolve({ status: 200, body: { items: seq(7, 'OLD'), page: 1, page_size: 50, total_items: 7 } })
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByText('โหลดรายการเครื่องมือไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    // Retry targets the NEWER (failed) request, not the older one.
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    await waitFor(() => expect(calls[calls.length - 1].params.get('q')).toBe('new'))
  })

  it('while a newer request loads, stale rows, totals, echo and pager are hidden and the form stays usable', async () => {
    const data = seq(120)
    const { pending } = installFetch((c) => (c.params.get('page') === '2' ? undefined : serve(data, c.params)))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 120))
    await user.click(next())
    expect(screen.getByText('กำลังโหลดรายการเครื่องมือ...')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/พบ 120 รายการ/)).not.toBeInTheDocument()
    expect(screen.queryByText(/เงื่อนไขที่ใช้/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ถัดไป' })).not.toBeInTheDocument()
    expect(qInput()).toBeEnabled()
    expect(screen.getByRole('button', { name: 'ค้นหา' })).toBeEnabled()
    pending[0].resolve(serve(data, pending[0].call.params))
    expect(await screen.findByText(rangeText(51, 100, 120))).toBeInTheDocument()
  })
})

describe('EquipmentListPage — 7F2 links, row identity and request discipline', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('links only safe ids, keeps original text for suppressed links, preserves every row and leading zeros', async () => {
    const consoleError = vi.spyOn(console, 'error')
    const items = [
      eq('EQP-0001'),
      eq('000123'),
      eq('a/b'),
      eq('a\\b'),
      eq('%2F'),
      eq('a?b'),
      eq('a#b'),
      eq('..'),
      eq(' EQP-9'),
      eq('เครื่อง-1'),
      eq(''),
      eq('DUP-1', { name: 'ซ้ำ A' }),
      eq('DUP-1', { name: 'ซ้ำ B' }),
    ]
    installFetch(() => ({ status: 200, body: { items, page: 1, page_size: 50, total_items: 13 } }))
    renderPage()
    expect(await screen.findByText(rangeText(1, 13, 13))).toBeInTheDocument()
    expect(bodyRows()).toHaveLength(13)

    expect(screen.getByRole('link', { name: 'EQP-0001' })).toHaveAttribute('href', '/equipment/EQP-0001')
    expect(screen.getByRole('link', { name: '000123' })).toHaveAttribute('href', '/equipment/000123')
    expect(screen.getAllByRole('link')).toHaveLength(2)

    const unsafe = '(ไม่มีลิงก์: รหัสมีอักขระที่หน้ารายละเอียดยังรองรับไม่ได้)'
    for (const id of ['a/b', 'a\\b', '%2F', 'a?b', 'a#b', '..', 'เครื่อง-1']) {
      const cell = screen.getByText(id, { exact: true })
      expect(cell.parentElement).toHaveTextContent(unsafe)
    }
    expect(screen.getByText((_, el) => el?.textContent === ' EQP-9' && el.tagName === 'SPAN')).toBeInTheDocument()
    expect(screen.getAllByText(unsafe)).toHaveLength(8)
    expect(screen.getAllByText('(ไม่มีลิงก์: ไม่มีรหัส)')).toHaveLength(1)
    expect(screen.getAllByText('(ไม่มีลิงก์: รหัสนี้ซ้ำกันในหน้านี้)')).toHaveLength(2)
    expect(screen.getByText('ซ้ำ A')).toBeInTheDocument()
    expect(screen.getByText('ซ้ำ B')).toBeInTheDocument()

    const keyWarnings = consoleError.mock.calls.filter((args) => String(args[0]).includes('same key'))
    expect(keyWarnings).toHaveLength(0)
  })

  it('list actions are GET-only and cost one request each, independent of row count', async () => {
    const data = seq(120)
    const { calls } = installFetch((c) => serve(data, c.params))
    const user = userEvent.setup()
    renderPage()
    await screen.findByText(rangeText(1, 50, 120))
    expect(calls).toHaveLength(1)
    await user.click(next())
    await screen.findByText(rangeText(51, 100, 120))
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText(rangeText(1, 50, 120))
    await user.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }))
    await screen.findByText(rangeText(1, 50, 120))
    expect(calls).toHaveLength(4)
    expect(calls.every((c) => c.method === 'GET' && c.path === LIST_PATH)).toBe(true)
  })

  it('category options keep the existing codes and labels', async () => {
    installFetch((c) => serve([], c.params))
    renderPage()
    await screen.findByText('ไม่พบเครื่องมือที่ตรงกับเงื่อนไข')
    const values = within(categorySelect() as HTMLSelectElement)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value)
    const expected: Array<EquipmentCategory | ''> = [
      '',
      'LATHE',
      'MILLING',
      'AIR_COMPRESSOR',
      'WELDING',
      'PRESS',
      'DRILL_PRESS',
      'GRINDER',
      'FORKLIFT',
      'OTHER',
    ]
    expect(values).toEqual(expected)
    expect(PAGE_SIZE).toBe(50)
  })
})
