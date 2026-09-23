// Run in a zone west of UTC so any accidental local-midnight date parsing
// would shift displayed dates by a day (see labels.certificateReport.test.ts).
;(globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.TZ =
  'America/Los_Angeles'

import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CertificateExpiryReportPage } from './CertificateExpiryReportPage'
import type { CertificateExpiryReport, CertificateExpiryReportItem } from '../lib/types'

// Phase 7 Batch 7D2 — synthetic payloads only (SYN-* ids).

const REPORT_PATH = '/api/v1/reports/certificate-expiry'
const PARTIAL = (n: number) =>
  `มีข้อมูลใบรับรอง ${n} รายการที่ระบบอ่านสถานะ วันหมดอายุ หรือข้อมูลอื่นไม่ได้ จึงไม่ได้แสดงในรายงานนี้ และอาจตรงกับเงื่อนไขที่เลือก ผลรายงานนี้จึงอาจไม่ครบ ข้อสังเกตข้อมูลอาจไม่ครบด้วย กรุณาแจ้งผู้ดูแลระบบ`
const PARTIAL_EMPTY = (n: number) =>
  `ไม่พบรายการที่ตรงเงื่อนไขในข้อมูลที่อ่านได้ แต่มีข้อมูล ${n} รายการที่อ่านไม่ได้และอาจตรงเงื่อนไข จึงยืนยันไม่ได้ว่าไม่มีรายการ`
const SUPPRESSED = '(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)'
const DESTINATION_NOTE =
  "หน้าใบรับรองของรถเป็นหน้าที่มีอยู่เดิม เมื่อเปิด ระบบอาจบันทึกสถานะใบรับรองที่วันหมดอายุอยู่ก่อนวันนี้ให้เป็น 'หมดอายุ'"

function item(id: string, overrides: Partial<CertificateExpiryReportItem> = {}): CertificateExpiryReportItem {
  return {
    certificate_id: id,
    vehicle_id: 'SYN-VEH-1',
    certificate_type_code: 'SYN-TYPE-A',
    certificate_type_name_th: 'ใบอนุญาตสังเคราะห์',
    document_no: '000123',
    expiry_date: '2026-03-10',
    stored_status: 'ACTIVE',
    effective_status: 'ACTIVE',
    expiry_position: 'TODAY',
    flags: [],
    ...overrides,
  }
}

function report(overrides: Partial<CertificateExpiryReport> = {}): CertificateExpiryReport {
  const items = overrides.items ?? [item('SYN-C-1')]
  return {
    as_of_date: '2026-03-10',
    timezone: 'Asia/Bangkok',
    filter: {
      mode: 'RANGE',
      expiry_from: null,
      expiry_to_requested: null,
      expiry_to_resolved: '2026-03-10',
      expiry_to_is_default: true,
      effective_status: null,
    },
    items,
    page: 1,
    page_size: 50,
    total_items: items.length,
    complete: true,
    population: {
      read_record_count: items.length,
      in_scope_count: items.length,
      in_scope_with_expiry_date_count: items.length,
      in_scope_without_expiry_date_count: 0,
      excluded_replaced_count: 0,
      excluded_status_blank_count: 0,
      issue_row_count: 0,
      excluded_rows_with_other_defects: 0,
      replaced_link_observations: 0,
    },
    data_issues: {
      issue_defect_counts: {},
      issue_defect_counts_are_occurrences: true,
      issue_rows_without_usable_id: 0,
      sample_certificate_ids: [],
    },
    ...overrides,
  }
}

function partial(overrides: Partial<CertificateExpiryReport> = {}, issues = 3): CertificateExpiryReport {
  const base = report(overrides)
  return {
    ...base,
    complete: false,
    population: {
      ...base.population,
      read_record_count: base.population.read_record_count + issues,
      issue_row_count: issues,
    },
    data_issues: {
      issue_defect_counts: { UNRECOGNIZED_STATUS: 2, INVALID_EXPIRY_DATE: 2 },
      issue_defect_counts_are_occurrences: true,
      issue_rows_without_usable_id: 1,
      sample_certificate_ids: ['SYN-BAD-1', 'SYN-BAD-2'],
    },
    ...overrides,
  }
}

function items(from: number, count: number) {
  return Array.from({ length: count }, (_, i) => item(`SYN-C-${from + i}`))
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function errorResponse(code: string, status: number, details: unknown = null, requestId = 'req-7d2') {
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
      <CertificateExpiryReportPage />
    </BrowserRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

const dataRows = () => screen.queryAllByRole('row').slice(1)
const fromInput = () => screen.getByLabelText('วันหมดอายุตั้งแต่') as HTMLInputElement
const toInput = () => screen.getByLabelText('วันหมดอายุถึง') as HTMLInputElement
const statusSelect = () => screen.getByLabelText('สถานะที่คำนวณ') as HTMLSelectElement
const submitButton = () => screen.getByRole('button', { name: 'แสดงรายงาน' })
const refreshButton = () => screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' })
const modeRadio = (name: string) => screen.getByRole('radio', { name }) as HTMLInputElement
const INITIAL_PARAMS = { mode: 'RANGE', page: '1', page_size: '50' }

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('CertificateExpiryReportPage', () => {
  it('renders the Thai title, controls, hints and every scope disclosure', async () => {
    installFetch([jsonResponse(report())])
    renderPage()
    expect(screen.getByRole('heading', { name: 'รายงานใบรับรองตามวันหมดอายุ' })).toBeInTheDocument()
    for (const text of [
      'นับเป็นรายการใบรับรอง (1 แถว = 1 ใบรับรอง) ไม่ใช่จำนวนรถ',
      'ไม่รวมใบรับรองที่บันทึกว่าถูกแทนที่แล้ว และใบรับรองที่ไม่ได้ระบุสถานะ (แสดงจำนวนไว้ด้านล่าง)',
      'รายงานนี้ไม่ได้ระบุว่ารถคันใดต้องมีใบรับรองประเภทใด ไม่ใช่การยืนยันความถูกต้องตามกฎหมาย และรถที่ไม่มีรายการในรายงานไม่ได้แปลว่ามีใบรับรองครบ',
      'หมายเหตุข้อมูลเป็นเพียงข้อสังเกตจากข้อมูลที่อ่านได้ ไม่ได้ยืนยันว่าใบใดเป็นใบแทนหรือใช้ได้ตามกฎหมาย',
      DESTINATION_NOTE,
      'เว้นว่าง = ไม่จำกัดวันเริ่มต้น',
      'เว้นว่าง = วันนี้ตามเวลาประเทศไทย ณ เวลาที่โหลดข้อมูล',
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument()
    }
    expect(screen.getByText(/ใบที่บันทึกว่า “ยังใช้งานได้” จะแสดงเป็น “หมดอายุ” เฉพาะเมื่อวันหมดอายุอยู่ก่อนวันที่อ้างอิง/)).toBeInTheDocument()
    expect(screen.getByText(/ใบที่บันทึกว่า “หมดอายุ” แสดงเป็น “หมดอายุ” เสมอ และใบที่ไม่มีวันหมดอายุในระบบจะแสดงตามสถานะที่บันทึกไว้/)).toBeInTheDocument()
    expect(modeRadio('ตามช่วงวันหมดอายุ').checked).toBe(true)
    expect(modeRadio('ใบรับรองที่ไม่มีวันหมดอายุในระบบ').checked).toBe(false)
    expect(screen.getByRole('button', { name: 'ใช้วันนี้อัตโนมัติ' })).toBeDisabled()
    await screen.findByText('SYN-C-1')
  })

  it('sends one initial RANGE request with no date parameters and shows the resolved echo', async () => {
    const { calls } = installFetch([jsonResponse(report())])
    renderPage()
    await screen.findByText('SYN-C-1')
    expect(calls).toEqual([{ path: REPORT_PATH, method: 'GET', params: INITIAL_PARAMS }])
    expect(screen.getByText('ข้อมูล ณ วันที่ 10 มี.ค. 2569 (เวลาประเทศไทย)')).toBeInTheDocument()
    expect(
      screen.getByText('เงื่อนไข: วันหมดอายุตั้งแต่ ไม่จำกัดวันเริ่มต้น ถึง 10 มี.ค. 2569 (วันนี้ตามเวลาประเทศไทย) · สถานะที่คำนวณ: ทั้งหมด'),
    ).toBeInTheDocument()
    // The echoed resolved date is never copied into the form.
    expect(toInput().value).toBe('')
  })

  it('renders a row per record with position keys, links, flags and calendar dates without zone shift', async () => {
    installFetch([
      jsonResponse(
        report({
          items: [
            item('SYN-DUP', {
              flags: ['SAME_TYPE_ACTIVE_EXISTS', 'STORED_ACTIVE_PAST_EXPIRY', 'DUPLICATE_CERTIFICATE_ID'],
              stored_status: 'ACTIVE',
              effective_status: 'EXPIRED',
              expiry_date: '2026-03-09',
              expiry_position: 'BEFORE_TODAY',
            }),
            item('SYN-DUP', { flags: ['DUPLICATE_CERTIFICATE_ID'], expiry_date: '2028-02-29', expiry_position: 'AFTER_TODAY' }),
            item('', { vehicle_id: '', flags: ['BLANK_CERTIFICATE_ID', 'BLANK_VEHICLE_ID'], certificate_type_code: null, certificate_type_name_th: null, document_no: null }),
          ],
        }),
      ),
    ])
    renderPage()
    await screen.findAllByText('SYN-DUP')
    const rows = dataRows()
    expect(rows).toHaveLength(3)
    const [first, second, third] = rows
    expect(within(first).getByText('9 มี.ค. 2569')).toBeInTheDocument()
    expect(within(first).getByText('หมดอายุก่อนวันนี้')).toBeInTheDocument()
    expect(within(first).getByText('หมดอายุ')).toBeInTheDocument()
    expect(within(first).getByText('บันทึกไว้: ยังใช้งานได้')).toBeInTheDocument()
    expect(within(first).getByText('บันทึกว่ายังใช้งานได้ แต่วันหมดอายุผ่านไปแล้ว')).toBeInTheDocument()
    expect(within(first).getByText(/ในข้อมูลมีใบรับรองประเภทเดียวกันของรถคันนี้ที่ยังใช้งานได้/)).toBeInTheDocument()
    expect(within(first).getByText('รหัสใบรับรองนี้ซ้ำกับรายการอื่นในข้อมูล')).toBeInTheDocument()
    expect(within(first).getByText('000123')).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: 'ดูรายละเอียดรถ' })).toHaveAttribute('href', '/vehicle/SYN-VEH-1')
    expect(within(first).getByRole('link', { name: 'ดูใบรับรองของรถคันนี้' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-1/certificates',
    )
    expect(within(second).getByText('29 ก.พ. 2571')).toBeInTheDocument()
    expect(within(third).getByText('(ไม่มีรหัสใบรับรอง)')).toBeInTheDocument()
    expect(within(third).getByText('(ไม่มีรหัสรถ)')).toBeInTheDocument()
    expect(within(third).queryByRole('link')).toBeNull()
    expect(screen.getByText('แสดงรายการที่ 1–3 จาก 3 รายการใบรับรอง')).toBeInTheDocument()
  })

  it('suppresses links for ids with trailing newline, Unicode, spaces or reserved characters and shows them as stored', async () => {
    const ids = ['SYN-VEH-1\n', 'รถ-1', 'SYN VEH', 'SYN/VEH', 'SYN%20VEH', '..', 'SYN?x=1']
    installFetch([jsonResponse(report({ items: ids.map((vehicle_id, i) => item(`SYN-C-${i}`, { vehicle_id })) }))])
    renderPage()
    await screen.findByText('SYN-C-0')
    const rows = dataRows()
    expect(rows).toHaveLength(ids.length)
    rows.forEach((row, index) => {
      expect(within(row).queryByRole('link')).toBeNull()
      expect(within(row).getByText(SUPPRESSED)).toBeInTheDocument()
      const idText = within(row).getAllByText((_, el) => el?.textContent === ids[index] && el.classList.contains('certificate-expiry-report__text'))
      expect(idText).toHaveLength(1)
    })
  })

  it('keeps editing local: no request until submit, which applies drafts and resets to page 1', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([
      jsonResponse(report({ items: items(1, 50), total_items: 120 })),
      jsonResponse(report({ items: items(51, 50), total_items: 120, page: 2 })),
      jsonResponse(report({ items: items(1, 1) })),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('SYN-C-51')
    expect(calls[1].params.page).toBe('2')

    await user.type(fromInput(), '2026-01-01')
    await user.type(toInput(), '2026-12-31')
    await user.selectOptions(statusSelect(), 'EXPIRED')
    await user.click(modeRadio('ใบรับรองที่ไม่มีวันหมดอายุในระบบ'))
    await user.click(modeRadio('ตามช่วงวันหมดอายุ'))
    expect(calls).toHaveLength(2)

    await user.click(submitButton())
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[2].params).toEqual({
      mode: 'RANGE',
      expiry_from: '2026-01-01',
      expiry_to: '2026-12-31',
      effective_status: 'EXPIRED',
      page: '1',
      page_size: '50',
    })
  })

  it('refresh and paging resend the APPLIED filters and ignore unsubmitted drafts', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([
      jsonResponse(report({ items: items(1, 50), total_items: 120 })),
      jsonResponse(report({ items: items(1, 50), total_items: 120 })),
      jsonResponse(report({ items: items(51, 50), total_items: 120, page: 2 })),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.type(fromInput(), '2026-01-01')
    await user.selectOptions(statusSelect(), 'ACTIVE')
    await user.click(refreshButton())
    await screen.findByText('SYN-C-1')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('SYN-C-51')
    expect(calls.map((c) => c.params)).toEqual([
      INITIAL_PARAMS,
      INITIAL_PARAMS,
      { ...INITIAL_PARAMS, page: '2' },
    ])
    expect(fromInput().value).toBe('2026-01-01') // the draft is kept, just not applied
  })

  it('keeps a blank end date dynamic across refresh, paging and a Bangkok midnight change', async () => {
    const user = userEvent.setup()
    const nextDay = {
      ...report().filter,
      expiry_to_resolved: '2026-03-11',
    }
    const { calls } = installFetch([
      jsonResponse(report({ items: items(1, 50), total_items: 60 })),
      jsonResponse(report({ items: items(1, 50), total_items: 61, as_of_date: '2026-03-11', filter: nextDay })),
      jsonResponse(report({ items: items(51, 11), total_items: 61, page: 2, as_of_date: '2026-03-11', filter: nextDay })),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.click(refreshButton())
    await screen.findByText('ข้อมูล ณ วันที่ 11 มี.ค. 2569 (เวลาประเทศไทย)')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('SYN-C-51')
    for (const call of calls) {
      expect(call.params).not.toHaveProperty('expiry_to')
      expect(call.params).not.toHaveProperty('expiry_from')
    }
    expect(toInput().value).toBe('')
    expect(screen.getByText(/ถึง 11 มี.ค. 2569 \(วันนี้ตามเวลาประเทศไทย\)/)).toBeInTheDocument()
  })

  it('keeps an explicit end date explicit, and "ใช้วันนี้อัตโนมัติ" only clears the draft', async () => {
    const user = userEvent.setup()
    const explicit = {
      ...report().filter,
      expiry_to_requested: '2026-06-30',
      expiry_to_resolved: '2026-06-30',
      expiry_to_is_default: false,
    }
    const { calls } = installFetch([
      jsonResponse(report()),
      jsonResponse(report({ filter: explicit })),
      jsonResponse(report({ filter: explicit, as_of_date: '2026-03-11' })),
      jsonResponse(report()),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.type(toInput(), '2026-06-30')
    await user.click(submitButton())
    await screen.findByText(/ถึง 30 มิ.ย. 2569 · สถานะที่คำนวณ/)
    await user.click(refreshButton())
    await screen.findByText('ข้อมูล ณ วันที่ 11 มี.ค. 2569 (เวลาประเทศไทย)')
    expect(calls[1].params.expiry_to).toBe('2026-06-30')
    expect(calls[2].params.expiry_to).toBe('2026-06-30')

    const dynamic = screen.getByRole('button', { name: 'ใช้วันนี้อัตโนมัติ' })
    expect(dynamic).toBeEnabled()
    await user.click(dynamic)
    expect(toInput().value).toBe('')
    expect(calls).toHaveLength(3)
    await user.click(submitButton())
    await waitFor(() => expect(calls).toHaveLength(4))
    expect(calls[3].params).not.toHaveProperty('expiry_to')
  })

  it('switching mode edits drafts only; MISSING submissions omit dates and keep date drafts for RANGE', async () => {
    const user = userEvent.setup()
    const missingFilter = {
      mode: 'MISSING_EXPIRY_DATE' as const,
      expiry_from: null,
      expiry_to_requested: null,
      expiry_to_resolved: null,
      expiry_to_is_default: false,
      effective_status: null,
    }
    const { calls } = installFetch([
      jsonResponse(report()),
      jsonResponse(report({ filter: missingFilter, items: [item('SYN-NOEXP', { expiry_date: null, expiry_position: 'NO_EXPIRY_DATE' })] })),
      jsonResponse(report()),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.type(fromInput(), '2026-01-01')
    await user.type(toInput(), '2026-02-01')
    await user.click(modeRadio('ใบรับรองที่ไม่มีวันหมดอายุในระบบ'))
    expect(fromInput()).toBeDisabled()
    expect(calls).toHaveLength(1)
    await user.click(submitButton())
    await screen.findByText('SYN-NOEXP')
    expect(calls[1].params).toEqual({ mode: 'MISSING_EXPIRY_DATE', page: '1', page_size: '50' })
    expect(screen.getByText('เงื่อนไข: ใบรับรองที่ไม่มีวันหมดอายุในระบบ · สถานะที่คำนวณ: ทั้งหมด')).toBeInTheDocument()
    expect(within(dataRows()[0]).getByText('ไม่มีวันหมดอายุในระบบ')).toBeInTheDocument()

    await user.click(modeRadio('ตามช่วงวันหมดอายุ'))
    expect(fromInput().value).toBe('2026-01-01')
    expect(toInput().value).toBe('2026-02-01')
    await user.click(submitButton())
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[2].params).toMatchObject({ mode: 'RANGE', expiry_from: '2026-01-01', expiry_to: '2026-02-01' })
  })

  it('shows the partial banner, occurrence-counted defects and samples alongside readable rows', async () => {
    installFetch([jsonResponse(partial())])
    renderPage()
    await screen.findByText('SYN-C-1')
    expect(screen.getByText(PARTIAL(3))).toBeInTheDocument()
    expect(screen.getByText('ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)')).toBeInTheDocument()
    expect(screen.getByText('สถานะใบรับรองอ่านไม่ได้หรือไม่ใช่ค่าที่ระบบรู้จัก: 2')).toBeInTheDocument()
    expect(screen.getByText('วันหมดอายุอ่านไม่ได้: 2')).toBeInTheDocument()
    expect(screen.getByText('ตัวอย่างรหัสใบรับรองที่อ่านไม่ได้: SYN-BAD-1, SYN-BAD-2')).toBeInTheDocument()
    expect(screen.getByText('รายการที่อ่านไม่ได้และไม่มีรหัสใบรับรอง: 1')).toBeInTheDocument()
    expect(dataRows()).toHaveLength(1)
  })

  it('distinguishes all-invalid partial empty, complete empty per mode/status, and out-of-range', async () => {
    const user = userEvent.setup()
    const statusFilter = { ...report().filter, effective_status: 'EXPIRED' as const }
    const missingActive = {
      mode: 'MISSING_EXPIRY_DATE' as const,
      expiry_from: null,
      expiry_to_requested: null,
      expiry_to_resolved: null,
      expiry_to_is_default: false,
      effective_status: 'ACTIVE' as const,
    }
    installFetch([
      jsonResponse(partial({ items: [], total_items: 0 }, 5)),
      jsonResponse(report({ items: [], total_items: 0 })),
      jsonResponse(report({ items: [], total_items: 0, filter: statusFilter })),
      jsonResponse(report({ items: [], total_items: 0, filter: missingActive })),
      jsonResponse(report({ items: [], total_items: 7, page: 9 })),
      jsonResponse(report()),
    ])
    renderPage()
    expect(await screen.findByText(PARTIAL_EMPTY(5))).toBeInTheDocument()
    expect(screen.getByText(PARTIAL(5))).toBeInTheDocument()
    expect(screen.queryByText(/^ไม่มีใบรับรองที่/)).toBeNull()

    await user.click(refreshButton())
    expect(await screen.findByText('ไม่มีใบรับรองที่วันหมดอายุอยู่ในช่วงที่เลือก')).toBeInTheDocument()
    expect(screen.queryByText(/รายงานอาจไม่ครบ/)).toBeNull()

    await user.click(refreshButton())
    expect(
      await screen.findByText('ไม่มีใบรับรองที่วันหมดอายุอยู่ในช่วงที่เลือก และมีสถานะที่คำนวณเป็น “หมดอายุ”'),
    ).toBeInTheDocument()

    await user.click(refreshButton())
    expect(
      await screen.findByText('ไม่มีใบรับรองที่ไม่มีวันหมดอายุในระบบ และมีสถานะที่คำนวณเป็น “ยังใช้งานได้”'),
    ).toBeInTheDocument()

    await user.click(refreshButton())
    expect(await screen.findByText('ไม่มีรายการในหน้านี้')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'กลับไปหน้าแรก' }))
    await screen.findByText('SYN-C-1')
  })

  it('shows a notice when a page answers with a different as_of date and offers page 1', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([
      jsonResponse(report({ items: items(1, 50), total_items: 60 })),
      jsonResponse(report({ items: items(51, 10), total_items: 60, page: 2, as_of_date: '2026-03-11' })),
      jsonResponse(report({ items: items(1, 50), total_items: 60, as_of_date: '2026-03-11' })),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('SYN-C-51')
    expect(screen.getByText('วันที่อ้างอิงของรายงานเปลี่ยนระหว่างเปลี่ยนหน้า')).toBeInTheDocument()
    expect(
      screen.getByText('หน้าก่อนหน้าอ้างอิงวันที่ 10 มี.ค. 2569 แต่หน้านี้อ้างอิงวันที่ 11 มี.ค. 2569 รายการอาจเลื่อน ซ้ำ หรือหายไประหว่างหน้า'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'กลับไปหน้าแรก' }))
    await screen.findByText('SYN-C-1')
    expect(calls[2].params.page).toBe('1')
    expect(screen.queryByText('วันที่อ้างอิงของรายงานเปลี่ยนระหว่างเปลี่ยนหน้า')).toBeNull()
  })

  it('ignores a stale success: an older response never overwrites rows, totals, echo or as_of', async () => {
    const user = userEvent.setup()
    const slow = deferred<Response>()
    installFetch([
      jsonResponse(report()),
      slow.promise,
      jsonResponse(report({ items: [item('SYN-NEW')], as_of_date: '2026-03-12', total_items: 1 })),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.click(refreshButton()) // older request (slow)
    expect(screen.queryByText('SYN-C-1')).toBeNull() // old response hidden while loading
    expect(screen.getByText('กำลังโหลดรายงานใบรับรอง...')).toBeInTheDocument()
    expect(refreshButton()).toBeEnabled()
    await user.click(refreshButton()) // newer request
    await screen.findByText('SYN-NEW')
    await act(async () => {
      slow.resolve(
        jsonResponse(partial({ items: [item('SYN-STALE')], as_of_date: '2020-01-01', total_items: 1 }, 9)),
      )
      await slow.promise
    })
    expect(screen.getByText('SYN-NEW')).toBeInTheDocument()
    expect(screen.queryByText('SYN-STALE')).toBeNull()
    expect(screen.queryByText(PARTIAL(9))).toBeNull()
    expect(screen.getByText('ข้อมูล ณ วันที่ 12 มี.ค. 2569 (เวลาประเทศไทย)')).toBeInTheDocument()
  })

  it('ignores a stale error and a stale success after a newer error', async () => {
    const user = userEvent.setup()
    const slowError = deferred<Response>()
    const slowSuccess = deferred<Response>()
    installFetch([
      jsonResponse(report()),
      slowError.promise,
      jsonResponse(report({ items: [item('SYN-NEW')] })),
      slowSuccess.promise,
      errorResponse('VEHICLE_CERTIFICATE_READ_FAILED', 503),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.click(refreshButton())
    await user.click(refreshButton())
    await screen.findByText('SYN-NEW')
    await act(async () => {
      slowError.resolve(errorResponse('VEHICLE_CERTIFICATE_SCHEMA_INVALID', 500))
      await slowError.promise
    })
    expect(screen.getByText('SYN-NEW')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()

    await user.click(refreshButton())
    await user.click(refreshButton())
    expect(await screen.findByText('ไม่สามารถอ่านข้อมูลใบรับรองได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()
    await act(async () => {
      slowSuccess.resolve(jsonResponse(report({ items: [item('SYN-STALE')] })))
      await slowSuccess.promise
    })
    expect(screen.queryByText('SYN-STALE')).toBeNull()
    expect(screen.getByText('ไม่สามารถอ่านข้อมูลใบรับรองได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()
  })

  it('shows the denied state for 403 and hides all report data', async () => {
    installFetch([errorResponse('HTTP_ERROR', 403)])
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์ดูรายงานนี้')).toBeInTheDocument()
    expect(dataRows()).toHaveLength(0)
    expect(screen.queryByText(/ข้อมูล ณ วันที่/)).toBeNull()
  })

  it('shows schema and read errors with retry and request id, and hides old data on error', async () => {
    const user = userEvent.setup()
    const { calls } = installFetch([
      jsonResponse(report()),
      errorResponse('VEHICLE_CERTIFICATE_SCHEMA_INVALID', 500, { tab: 'vehicle_certificate', problem: 'MISSING_HEADERS', headers: [] }, 'req-schema'),
      errorResponse('VEHICLE_CERTIFICATE_READ_FAILED', 503, null, 'req-read'),
      jsonResponse(report()),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.click(refreshButton())
    expect(
      await screen.findByText('โครงสร้างข้อมูลใบรับรองไม่ถูกต้อง จึงไม่แสดงรายงานเพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลระบบ'),
    ).toBeInTheDocument()
    expect(screen.getByText('ไม่แสดงรายงานใบรับรอง')).toBeInTheDocument()
    expect(screen.getByText('รหัสอ้างอิง: req-schema')).toBeInTheDocument()
    expect(screen.queryByText('SYN-C-1')).toBeNull()
    expect(screen.queryByText(/ข้อมูล ณ วันที่/)).toBeNull()
    expect(screen.queryByText(/จำนวนที่ใช้ประกอบรายงาน/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(await screen.findByText('ไม่สามารถอ่านข้อมูลใบรับรองได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()
    expect(screen.getByText('โหลดรายงานใบรับรองไม่สำเร็จ')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    await screen.findByText('SYN-C-1')
    expect(calls).toHaveLength(4)
    expect(calls.every((c) => c.method === 'GET' && c.path === REPORT_PATH)).toBe(true)
  })

  it('explains an AFTER_EXPIRY_TO validation error using the backend-resolved end date', async () => {
    const user = userEvent.setup()
    installFetch([
      jsonResponse(report()),
      errorResponse('VALIDATION_ERROR', 422, {
        errors: [{ loc: ['query', 'expiry_from'], field: 'expiry_from', reason: 'AFTER_EXPIRY_TO', resolved_expiry_to: '2026-03-10', expiry_to_is_default: true }],
      }),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    await user.type(fromInput(), '2026-12-01')
    await user.click(submitButton())
    expect(
      await screen.findByText('วันหมดอายุเริ่มต้นต้องไม่อยู่หลังวันสิ้นสุด (วันสิ้นสุดที่ใช้: 10 มี.ค. 2569 ซึ่งเป็นวันนี้ตามเวลาประเทศไทย)'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ลองใหม่อีกครั้ง' })).toBeNull()
    expect(toInput().value).toBe('')
  })

  it('shows population disclosures as report counts, not KPIs', async () => {
    installFetch([
      jsonResponse(
        report({
          population: {
            read_record_count: 11,
            in_scope_count: 1,
            in_scope_with_expiry_date_count: 1,
            in_scope_without_expiry_date_count: 0,
            excluded_replaced_count: 4,
            excluded_status_blank_count: 6,
            issue_row_count: 0,
            excluded_rows_with_other_defects: 2,
            replaced_link_observations: 3,
          },
        }),
      ),
    ])
    renderPage()
    await screen.findByText('SYN-C-1')
    expect(screen.getByText('จำนวนที่ใช้ประกอบรายงาน (ข้อมูลทั้งหมดที่อ่าน ไม่ขึ้นกับตัวกรอง และไม่ใช่ตัวชี้วัด)')).toBeInTheDocument()
    const row = (label: string) => screen.getByText(label).closest('div') as HTMLElement
    expect(within(row('ไม่รวม: บันทึกว่าถูกแทนที่แล้ว')).getByText('4')).toBeInTheDocument()
    expect(within(row('ไม่รวม: ไม่ได้ระบุสถานะ')).getByText('6')).toBeInTheDocument()
    expect(within(row('รายการใบรับรองที่อ่านได้จากระบบทั้งหมด')).getByText('11')).toBeInTheDocument()
  })

  it('uses page-position row keys, so repeated certificate ids never collide', async () => {
    const errors: unknown[] = []
    vi.spyOn(console, 'error').mockImplementation((...args) => errors.push(args))
    installFetch([jsonResponse(report({ items: [item('SYN-SAME'), item('SYN-SAME'), item('SYN-SAME')] }))])
    renderPage()
    await screen.findAllByText('SYN-SAME')
    expect(dataRows()).toHaveLength(3)
    expect(errors.filter((e) => String(e).includes('same key'))).toEqual([])
  })

  it('makes no per-row requests and, under StrictMode, applies only the latest initial response', async () => {
    const { calls } = installFetch([
      jsonResponse(report({ items: [item('SYN-FIRST')] })),
      jsonResponse(report({ items: items(1, 20), total_items: 20 })),
    ])
    renderPage(true)
    await screen.findByText('SYN-C-20')
    expect(screen.queryByText('SYN-FIRST')).toBeNull()
    expect(calls.every((c) => c.path === REPORT_PATH)).toBe(true)
    expect(calls.length).toBeLessThanOrEqual(2)
  })
})
