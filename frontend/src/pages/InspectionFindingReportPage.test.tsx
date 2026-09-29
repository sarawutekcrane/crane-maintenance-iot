// Run in a zone west of UTC so any browser-local time formatting would show
// a different time than Asia/Bangkok.
;(globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.TZ =
  'America/Los_Angeles'

import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InspectionFindingReportPage } from './InspectionFindingReportPage'
import type { InspectionFindingReport, InspectionFindingReportItem } from '../lib/types'

// Phase 7 Batch 7E2 — synthetic payloads only. Test ids from the 7E1 Final
// PLANNED matrix are noted per case (T54-T58).

const REPORT_PATH = '/api/v1/reports/inspection-findings'
const TITLE = 'รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)'
const SUPPRESSED = '(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)'
const PARTIAL_BANNER = (n: number) => `ข้อมูลไม่ครบ: มี ${n} แถวที่อ่านไม่ได้ จึงไม่แสดงในรายงาน`
const PARTIAL_EMPTY = (n: number) => `ไม่พบรายการที่อ่านได้ตามเงื่อนไข แต่มี ${n} แถวที่อ่านไม่ได้ ซึ่งอาจตรงเงื่อนไข`
const SCOPE_NOTES = [
  "รายงานนี้แสดงข้อบกพร่องที่ระบบบันทึกไว้เมื่อมีรายการตรวจเช็คถูกส่งผลว่า 'ไม่ผ่าน' (รายการที่ไม่ผ่าน 1 รายการ = ข้อบกพร่อง 1 รายการ) เป็นประวัติ ไม่ใช่รายการงานค้าง",
  'สถานะ OPEN คือค่าที่บันทึกไว้ตอนสร้าง ระบบยังไม่มีขั้นตอนปิดหรือแก้ไขข้อบกพร่อง จึงไม่ได้ยืนยันว่ายังชำรุดอยู่',
  'การแจ้งซ่อม การปิดงานซ่อม หรือผลตรวจครั้งหลังที่ผ่าน ไม่เปลี่ยนรายการในรายงานนี้',
  'จำนวนรายการไม่เท่ากับจำนวนครั้งที่ตรวจไม่ผ่าน จำนวนเครื่อง หรือจำนวนข้อบกพร่องที่ยังไม่ได้แก้ไข และไม่ใช่ตัวชี้วัด',
  'การไม่พบรายการ ไม่ได้หมายความว่าได้ตรวจแล้วหรือผ่านการตรวจ',
  'ผลตรวจที่บันทึกไม่สำเร็จครบทุกขั้นตอนอาจไม่ปรากฏในรายงานนี้',
  'ระบบไม่ได้ตรวจสอบว่าข้อมูลปลายทางของลิงก์มีอยู่จริง',
]

function item(id: string, overrides: Partial<InspectionFindingReportItem> = {}): InspectionFindingReportItem {
  return {
    finding_id: id,
    inspection_id: 'INS-0001',
    result_id: 'RES-0001',
    asset_type: 'VEHICLE',
    asset_id: 'VEH-1046',
    item_title: 'รายการตรวจ 1',
    recorded_status: 'OPEN',
    created_at: '2026-09-28T02:10:00Z',
    flags: [],
    ...overrides,
  }
}

function report(overrides: Partial<InspectionFindingReport> = {}): InspectionFindingReport {
  const items = overrides.items ?? [item('FND-0001')]
  return {
    timezone: 'Asia/Bangkok',
    filter: { asset_type: null, created_from: null, created_to: null },
    items,
    page: 1,
    page_size: 50,
    total_items: items.length,
    complete: true,
    population: { read_record_count: items.length, readable_count: items.length, issue_row_count: 0 },
    data_issues: {
      issue_defect_counts: {},
      issue_defect_counts_are_occurrences: true,
      issue_rows_without_usable_id: 0,
      sample_finding_ids: [],
    },
    ...overrides,
  }
}

function partial(overrides: Partial<InspectionFindingReport> = {}, issues = 3): InspectionFindingReport {
  const base = report(overrides)
  return {
    ...base,
    complete: false,
    population: {
      read_record_count: base.population.readable_count + issues,
      readable_count: base.population.readable_count,
      issue_row_count: issues,
    },
    data_issues: {
      issue_defect_counts: { BLANK_STATUS: 2, MISSING_CREATED_AT: 1, UNREPRESENTABLE_CREATED_AT: 1 },
      issue_defect_counts_are_occurrences: true,
      issue_rows_without_usable_id: 1,
      sample_finding_ids: ['FND-BAD-1', 'FND-BAD-2'],
    },
    ...overrides,
  }
}

function items(from: number, count: number) {
  return Array.from({ length: count }, (_, i) => item(`FND-${from + i}`))
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function errorResponse(code: string, status: number, details: unknown = null, requestId = 'req-7e2') {
  return jsonResponse({ error: { code, message: 'synthetic', details, request_id: requestId } }, status)
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
      <InspectionFindingReportPage />
    </BrowserRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

const dataRows = () => screen.queryAllByRole('row').slice(1)
const assetTypeSelect = () => screen.getByLabelText('ประเภททรัพย์สิน') as HTMLSelectElement
const fromInput = () => screen.getByLabelText('บันทึกตั้งแต่วันที่') as HTMLInputElement
const toInput = () => screen.getByLabelText('ถึงวันที่') as HTMLInputElement
const submitButton = () => screen.getByRole('button', { name: 'แสดงรายงาน' })
const refreshButton = () => screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' })
const INITIAL_PARAMS = { page: '1', page_size: '50' }

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('InspectionFindingReportPage', () => {
  it('T58: renders the Thai title, every scope note and the filter controls', async () => {
    installFetch([jsonResponse(report())])
    renderPage()
    expect(screen.getByRole('heading', { name: TITLE })).toBeInTheDocument()
    for (const note of SCOPE_NOTES) expect(screen.getByText(note)).toBeInTheDocument()
    expect(assetTypeSelect().value).toBe('')
    expect([...assetTypeSelect().options].map((o) => o.textContent)).toEqual(['ทั้งหมด', 'ยานพาหนะ', 'เครื่องมือ/อุปกรณ์'])
    expect(screen.getAllByText('วันที่ตามเวลาไทย รวมวันที่เลือก · เว้นว่าง = ไม่จำกัด')).toHaveLength(2)
    expect(screen.getByText('กำลังโหลดรายงาน...')).toBeInTheDocument()
    await screen.findByText('FND-0001')
    // No mutation, export or repair control is offered.
    for (const name of [/แจ้งซ่อม/, /ส่งออก/, /ปิด/, /ลบ/]) expect(screen.queryByRole('button', { name })).toBeNull()
  })

  it('T54: sends one initial request without filters and echoes the backend filter', async () => {
    const { calls } = installFetch([jsonResponse(report())])
    renderPage()
    await screen.findByText('FND-0001')
    expect(calls).toEqual([{ path: REPORT_PATH, method: 'GET', params: INITIAL_PARAMS }])
    expect(
      screen.getByText('เงื่อนไข: ประเภททรัพย์สิน ทั้งหมด · วันที่บันทึก (เวลาไทย) ตั้งแต่ ไม่จำกัดวันเริ่มต้น ถึง ไม่จำกัดวันสิ้นสุด'),
    ).toBeInTheDocument()
  })

  it('T58/T57: renders rows with Bangkok time, Thai labels, flags and verified links', async () => {
    installFetch([
      jsonResponse(
        report({
          items: [
            item('FND-0003', { flags: ['DUPLICATE_FINDING_ID'], created_at: '2026-09-28T18:30:00Z', asset_id: 'VEH-1048', inspection_id: 'INS-0003' }),
            item('FND-0004', { asset_type: 'EQUIPMENT', asset_id: 'EQP-0001', inspection_id: '', flags: ['BLANK_INSPECTION_ID'] }),
            item('', { result_id: '', item_title: '   ', asset_id: '0012', flags: ['BLANK_FINDING_ID', 'BLANK_RESULT_ID'] }),
          ],
        }),
      ),
    ])
    renderPage()
    await screen.findByText('FND-0003')
    const [first, second, third] = dataRows()
    expect(within(first).getByText('29 ก.ย. 2569 01:30')).toBeInTheDocument() // Bangkok, not Los Angeles
    expect(within(first).getByText('ยานพาหนะ')).toBeInTheDocument()
    expect(within(first).getByText('OPEN (ค่าที่บันทึก)')).toBeInTheDocument()
    expect(within(first).getByText('รหัสข้อบกพร่องซ้ำ')).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: 'ดูรายละเอียด' })).toHaveAttribute('href', '/vehicle/VEH-1048')
    expect(within(first).getByRole('link', { name: 'ดูผลการตรวจ' })).toHaveAttribute('href', '/inspections/INS-0003')

    expect(within(second).getByText('เครื่องมือ/อุปกรณ์')).toBeInTheDocument()
    expect(within(second).getByRole('link', { name: 'ดูรายละเอียด' })).toHaveAttribute('href', '/equipment/EQP-0001')
    expect(within(second).queryByRole('link', { name: 'ดูผลการตรวจ' })).toBeNull()
    expect(within(second).getAllByText('ไม่มีรหัสผลการตรวจ')).toHaveLength(2) // cell text + flag label

    expect(within(third).getByText('(ไม่มีรหัสข้อบกพร่อง)')).toBeInTheDocument()
    expect(within(third).getByText('(ไม่มีชื่อรายการ)')).toBeInTheDocument()
    expect(within(third).getByText('ไม่มีรหัสข้อบกพร่อง')).toBeInTheDocument()
    expect(within(third).getByText('ไม่มีรหัสผลรายการตรวจ')).toBeInTheDocument()
    expect(within(third).getByRole('link', { name: 'ดูรายละเอียด' })).toHaveAttribute('href', '/vehicle/0012')
    expect(screen.getByText('แสดงรายการที่ 1–3 จาก 3 รายการข้อบกพร่องที่บันทึกไว้')).toBeInTheDocument()
    expect(screen.getByText('ข้อมูลอาจเลื่อนหรือซ้ำระหว่างหน้า หากมีการบันทึกใหม่ระหว่างดู')).toBeInTheDocument()
  })

  it('T57: keeps rows but suppresses links for ineligible ids and shows them as stored', async () => {
    const ids = ['INS 0010', 'EQP/0002', ' VEH-1047', 'INS-1\n', 'ผล-1', '..']
    installFetch([
      jsonResponse(report({ items: ids.map((id, i) => item(`FND-${i}`, { inspection_id: id, asset_id: id })) })),
    ])
    renderPage()
    await screen.findByText('FND-0')
    const rows = dataRows()
    expect(rows).toHaveLength(ids.length)
    rows.forEach((row, index) => {
      expect(within(row).queryByRole('link')).toBeNull()
      expect(within(row).getAllByText(SUPPRESSED)).toHaveLength(2)
      const stored = within(row).getAllByText(
        (_, el) => el?.textContent === ids[index] && el.classList.contains('inspection-finding-report__text'),
      )
      expect(stored).toHaveLength(2)
    })
  })

  it('T54: editing sends nothing; submit applies the draft and resets to page 1', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([
      jsonResponse(report({ items: items(1, 50), total_items: 120 })),
      jsonResponse(report({ items: items(51, 50), total_items: 120, page: 2 })),
      jsonResponse(report({ items: items(1, 1), filter: { asset_type: 'EQUIPMENT', created_from: '2026-01-01', created_to: '2026-12-31' } })),
    ])
    renderPage()
    await screen.findByText('FND-1')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('FND-51')
    expect(calls[1].params).toEqual({ ...INITIAL_PARAMS, page: '2' })

    await user.selectOptions(assetTypeSelect(), 'EQUIPMENT')
    await user.type(fromInput(), '2026-01-01')
    await user.type(toInput(), '2026-12-31')
    expect(calls).toHaveLength(2)

    await user.click(submitButton())
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[2].params).toEqual({
      asset_type: 'EQUIPMENT',
      created_from: '2026-01-01',
      created_to: '2026-12-31',
      page: '1',
      page_size: '50',
    })
    expect(
      await screen.findByText('เงื่อนไข: ประเภททรัพย์สิน เครื่องมือ/อุปกรณ์ · วันที่บันทึก (เวลาไทย) ตั้งแต่ 1 ม.ค. 2569 ถึง 31 ธ.ค. 2569'),
    ).toBeInTheDocument()
  })

  it('T54: refresh, retry and paging resend the APPLIED filter and ignore unsubmitted drafts', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([
      jsonResponse(report({ items: items(1, 50), total_items: 120 })),
      jsonResponse(report({ items: items(1, 50), total_items: 120 })),
      errorResponse('INSPECTION_FINDING_READ_FAILED', 503),
      jsonResponse(report({ items: items(51, 50), total_items: 120, page: 2 })),
    ])
    renderPage()
    await screen.findByText('FND-1')
    await user.type(fromInput(), '2026-01-01')
    await user.selectOptions(assetTypeSelect(), 'VEHICLE')
    await user.click(refreshButton())
    await screen.findByText('FND-1')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('อ่านข้อมูลข้อบกพร่องไม่สำเร็จ กรุณาลองใหม่')
    await user.click(screen.getByRole('button', { name: /ลองใหม่/ }))
    await screen.findByText('FND-51')
    expect(calls.map((c) => c.params)).toEqual([
      INITIAL_PARAMS,
      INITIAL_PARAMS,
      { ...INITIAL_PARAMS, page: '2' },
      { ...INITIAL_PARAMS, page: '2' },
    ])
    expect(fromInput().value).toBe('2026-01-01') // the draft is kept, just not applied
  })

  it('T54: "ล้างเงื่อนไข" clears the draft only and sends nothing', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([jsonResponse(report())])
    renderPage()
    await screen.findByText('FND-0001')
    await user.type(fromInput(), '2026-01-01')
    await user.selectOptions(assetTypeSelect(), 'EQUIPMENT')
    await user.click(screen.getByRole('button', { name: 'ล้างเงื่อนไข' }))
    expect(fromInput().value).toBe('')
    expect(assetTypeSelect().value).toBe('')
    expect(calls).toHaveLength(1)
  })

  it('T58: shows the partial banner, occurrence-counted defects and samples with readable rows', async () => {
    installFetch([jsonResponse(partial({ items: [item('FND-OK')] }, 3))])
    renderPage()
    await screen.findByText('FND-OK')
    expect(screen.getByText(PARTIAL_BANNER(3))).toBeInTheDocument()
    expect(screen.getByText('ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)')).toBeInTheDocument()
    expect(screen.getByText('ไม่มีสถานะ: 2')).toBeInTheDocument()
    expect(screen.getByText('ไม่มีวันที่บันทึก: 1')).toBeInTheDocument()
    expect(screen.getByText('วันที่บันทึกอยู่นอกช่วงที่ระบบแสดงได้: 1')).toBeInTheDocument()
    expect(screen.getByText('ตัวอย่างรหัสข้อบกพร่องที่อ่านไม่ได้: FND-BAD-1, FND-BAD-2')).toBeInTheDocument()
    expect(screen.getByText('แถวที่อ่านไม่ได้และไม่มีรหัสข้อบกพร่อง: 1')).toBeInTheDocument()
    expect(dataRows()).toHaveLength(1)
  })

  it('T58/T24: distinguishes all-unreadable, genuine empty, filtered empty and out-of-range', async () => {
    const user = userEvent.setup()
    installFetch([
      jsonResponse(partial({ items: [], total_items: 0 }, 4)),
      jsonResponse(report({ items: [], total_items: 0, population: { read_record_count: 0, readable_count: 0, issue_row_count: 0 } })),
      jsonResponse(report({ items: [], total_items: 0, population: { read_record_count: 3, readable_count: 3, issue_row_count: 0 } })),
      jsonResponse(report({ items: [], total_items: 3, page: 5 })),
      jsonResponse(report({ items: items(1, 3), total_items: 3 })),
    ])
    renderPage()
    expect(await screen.findByText(PARTIAL_EMPTY(4))).toBeInTheDocument()
    expect(screen.getByText(PARTIAL_BANNER(4))).toBeInTheDocument()
    expect(screen.queryByText('ยังไม่มีข้อบกพร่องที่บันทึกไว้')).toBeNull()

    await user.click(refreshButton())
    expect(await screen.findByText('ยังไม่มีข้อบกพร่องที่บันทึกไว้')).toBeInTheDocument()
    expect(screen.getAllByText(SCOPE_NOTES[4]).length).toBeGreaterThanOrEqual(2)

    await user.click(refreshButton())
    expect(await screen.findByText('ไม่พบข้อบกพร่องที่บันทึกไว้ตามเงื่อนไข')).toBeInTheDocument()

    await user.click(refreshButton())
    expect(await screen.findByText('ไม่มีรายการในหน้านี้')).toBeInTheDocument()
    expect(screen.getByText('ขณะนี้ระบบส่งกลับ 3 รายการตามเงื่อนไขนี้')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'กลับไปหน้าแรก' }))
    await screen.findByText('FND-1')
  })

  it('T55: ignores a stale success; loading hides older rows, totals and disclosures', async () => {
    const user = userEvent.setup()
    const slow = deferred<Response>()
    installFetch([
      jsonResponse(partial({ items: [item('FND-OLD')] }, 2)),
      slow.promise,
      jsonResponse(report({ items: [item('FND-NEW')] })),
    ])
    renderPage()
    await screen.findByText('FND-OLD')
    await user.click(refreshButton()) // older request (slow)
    expect(screen.queryByText('FND-OLD')).toBeNull()
    expect(screen.queryByText(PARTIAL_BANNER(2))).toBeNull()
    expect(screen.queryByText(/เงื่อนไข: ประเภททรัพย์สิน/)).toBeNull()
    expect(screen.getByText('กำลังโหลดรายงาน...')).toBeInTheDocument()
    expect(refreshButton()).toBeEnabled()
    await user.click(refreshButton()) // newer request
    await screen.findByText('FND-NEW')
    await act(async () => {
      slow.resolve(jsonResponse(partial({ items: [item('FND-STALE')] }, 9)))
      await slow.promise
    })
    expect(screen.getByText('FND-NEW')).toBeInTheDocument()
    expect(screen.queryByText('FND-STALE')).toBeNull()
    expect(screen.queryByText(PARTIAL_BANNER(9))).toBeNull()
  })

  it('T55: ignores a stale error, and a stale success after a newer error', async () => {
    const user = userEvent.setup()
    const slowError = deferred<Response>()
    const slowSuccess = deferred<Response>()
    installFetch([
      jsonResponse(report()),
      slowError.promise,
      jsonResponse(report({ items: [item('FND-NEW')] })),
      slowSuccess.promise,
      errorResponse('INSPECTION_FINDING_READ_FAILED', 503),
    ])
    renderPage()
    await screen.findByText('FND-0001')
    await user.click(refreshButton())
    await user.click(refreshButton())
    await screen.findByText('FND-NEW')
    await act(async () => {
      slowError.resolve(errorResponse('INSPECTION_FINDING_SCHEMA_INVALID', 500))
      await slowError.promise
    })
    expect(screen.getByText('FND-NEW')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()

    await user.click(refreshButton())
    await user.click(refreshButton())
    expect(await screen.findByText('อ่านข้อมูลข้อบกพร่องไม่สำเร็จ กรุณาลองใหม่')).toBeInTheDocument()
    await act(async () => {
      slowSuccess.resolve(jsonResponse(report({ items: [item('FND-STALE')] })))
      await slowSuccess.promise
    })
    expect(screen.queryByText('FND-STALE')).toBeNull()
    expect(screen.getByText('อ่านข้อมูลข้อบกพร่องไม่สำเร็จ กรุณาลองใหม่')).toBeInTheDocument()
  })

  it('T58: shows the denied state for 403 and no report data', async () => {
    installFetch([errorResponse('HTTP_ERROR', 403)])
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์ดูรายงานนี้')).toBeInTheDocument()
    expect(dataRows()).toHaveLength(0)
    expect(screen.queryByText(/เงื่อนไข: ประเภททรัพย์สิน/)).toBeNull()
    expect(screen.queryByText(/จำนวนที่ใช้ประกอบรายงาน/)).toBeNull()
  })

  it('T58: schema and read errors show retry and request id and hide older data', async () => {
    const user = userEvent.setup()
    installFetch([
      jsonResponse(report({ items: [item('FND-OLD')] })),
      errorResponse('INSPECTION_FINDING_SCHEMA_INVALID', 500, { tab: 'inspection_findings', problem: 'MISSING_HEADERS', headers: ['status'] }, 'req-schema'),
    ])
    renderPage()
    await screen.findByText('FND-OLD')
    await user.click(refreshButton())
    expect(await screen.findByText('โครงสร้างตารางข้อบกพร่องไม่ถูกต้อง จึงแสดงรายงานไม่ได้')).toBeInTheDocument()
    expect(screen.getByText('ไม่แสดงรายงานข้อบกพร่อง')).toBeInTheDocument()
    expect(screen.getByText(/req-schema/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ลองใหม่/ })).toBeInTheDocument()
    expect(screen.queryByText('FND-OLD')).toBeNull()
    expect(screen.queryByText(/จำนวนที่ใช้ประกอบรายงาน/)).toBeNull()
  })

  it('T58: explains INVALID_DATE and AFTER_CREATED_TO validation errors without retry', async () => {
    const user = userEvent.setup()
    installFetch([
      jsonResponse(report()),
      errorResponse('VALIDATION_ERROR', 422, { errors: [{ field: 'created_from', reason: 'AFTER_CREATED_TO' }] }),
      errorResponse('VALIDATION_ERROR', 422, { errors: [{ field: 'created_to', reason: 'INVALID_DATE' }] }),
    ])
    renderPage()
    await screen.findByText('FND-0001')
    await user.type(fromInput(), '2026-10-02')
    await user.type(toInput(), '2026-10-01')
    await user.click(submitButton())
    expect(await screen.findByText('วันที่เริ่มต้องไม่อยู่หลังวันที่สิ้นสุด')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ลองใหม่/ })).toBeNull()
    await user.click(submitButton())
    expect(await screen.findByText('วันที่ไม่ถูกต้อง')).toBeInTheDocument()
  })

  it('shows population disclosures as report counts, not KPIs', async () => {
    installFetch([jsonResponse(partial({ items: [item('FND-1')] }, 2))])
    renderPage()
    await screen.findByText('FND-1')
    expect(screen.getByText('จำนวนที่ใช้ประกอบรายงาน (ไม่ใช่ตัวชี้วัด)')).toBeInTheDocument()
    const rows = [
      ['แถวข้อบกพร่องที่อ่านจากระบบทั้งหมด', '3'],
      ['อ่านได้และแสดงในรายงานได้', '1'],
      ['อ่านไม่ได้ จึงไม่ได้แสดงในรายงาน', '2'],
    ]
    for (const [label, value] of rows) {
      const term = screen.getByText(label)
      expect(term.nextElementSibling?.textContent).toBe(value)
    }
  })

  it('uses page-position row keys, so repeated or blank finding ids never collide', async () => {
    const errors: unknown[] = []
    vi.spyOn(console, 'error').mockImplementation((...args) => errors.push(args))
    installFetch([jsonResponse(report({ items: [item('FND-SAME'), item('FND-SAME'), item(''), item('')] }))])
    renderPage()
    await screen.findAllByText('FND-SAME')
    expect(dataRows()).toHaveLength(4)
    expect(errors.filter((e) => String(e).includes('same key'))).toEqual([])
  })

  it('makes no per-row requests and, under StrictMode, applies only the latest initial response', async () => {
    const { calls } = installFetch([
      jsonResponse(report({ items: [item('FND-FIRST')] })),
      jsonResponse(report({ items: items(1, 20), total_items: 20 })),
    ])
    renderPage(true)
    await screen.findByText('FND-20')
    expect(screen.queryByText('FND-FIRST')).toBeNull()
    expect(calls.every((c) => c.path === REPORT_PATH)).toBe(true)
    expect(calls.length).toBeLessThanOrEqual(2)
  })
})
