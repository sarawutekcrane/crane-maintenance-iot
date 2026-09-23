import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FleetStatusPage } from './FleetStatusPage'

// Synthetic payloads only; the page renders server integers verbatim.

const SUMMARY_PATH = '/api/v1/dashboard/fleet-status'

function summary(counts: Partial<Record<string, number>> = {}, total?: number) {
  const status_counts = {
    WORKING: 2,
    READY: 1,
    MAINTENANCE: 1,
    OUT_OF_SERVICE: 1,
    LONG_TERM_PARKING: 1,
    ...counts,
  }
  return {
    population: 'VEHICLE_MASTER_VALIDATED_RECORDS',
    vehicle_total: total ?? Object.values(status_counts).reduce((a, b) => a + b, 0),
    status_counts,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(code: string, status: number, requestId = 'req-7b2') {
  return jsonResponse({ error: { code, message: 'synthetic', details: null, request_id: requestId } }, status)
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

/** Each call to fetch takes the next queued response (or promise). */
function installFetch(queue: Array<Response | Promise<Response> | Error>) {
  const calls: { path: string; method: string }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push({ path: url.pathname, method: (init?.method ?? 'GET').toUpperCase() })
    const next = queue.shift()
    if (next === undefined) throw new Error(`Unexpected fetch: ${url.toString()}`)
    if (next instanceof Error) throw next
    return next
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

function renderPage(strict = false) {
  const tree = (
    <BrowserRouter>
      <FleetStatusPage />
    </BrowserRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

function countTexts() {
  return screen.queryAllByText(/\d+ คัน$/)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FleetStatusPage', () => {
  it('shows no numbers while loading and keeps the refresh button available', async () => {
    const pending = deferred<Response>()
    installFetch([pending.promise])
    renderPage()

    expect(screen.getByRole('heading', { name: 'ภาพรวมกองรถ' })).toBeInTheDocument()
    expect(screen.getByText('กำลังโหลดภาพรวมกองรถ...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' })).toBeEnabled()
    expect(countTexts()).toHaveLength(0)
    expect(screen.queryByText('0 คัน')).not.toBeInTheDocument()

    await act(async () => pending.resolve(jsonResponse(summary())))
    expect(await screen.findByText('6 คัน')).toBeInTheDocument()
  })

  it('renders Thai labels and the server integers verbatim, without arithmetic', async () => {
    // Deliberately inconsistent payload: the page must not re-add numbers.
    installFetch([jsonResponse(summary({ WORKING: 7 }, 99))])
    renderPage()

    const total = (await screen.findByText('รถในทะเบียนทั้งหมด')).closest('.card') as HTMLElement
    expect(within(total).getByText('99 คัน')).toBeInTheDocument()
    const expected: [string, string][] = [
      ['ใช้งานอยู่', '7 คัน'],
      ['พร้อมใช้งาน', '1 คัน'],
      ['ซ่อมบำรุง', '1 คัน'],
      ['หยุดใช้งาน', '1 คัน'],
      ['จอดระยะยาว', '1 คัน'],
    ]
    for (const [label, count] of expected) {
      const card = screen.getByText(label).closest('.card') as HTMLElement
      expect(within(card).getByText(count)).toBeInTheDocument()
    }
    expect(screen.getByText(/หน้านี้แสดงเฉพาะจำนวนรถตามสถานะที่บันทึกไว้ในทะเบียนรถ/)).toBeInTheDocument()
    expect(screen.getByText('ต้องการดูรถตามสถานะ ให้เปิดรายการรถแล้วเลือกตัวกรอง “สถานะ”')).toBeInTheDocument()
    expect(screen.queryByText('ยังไม่มีรายการรถในทะเบียน')).not.toBeInTheDocument()
  })

  it('shows genuine zeros and the empty-fleet message only on a successful empty result', async () => {
    installFetch([
      jsonResponse(summary({ WORKING: 0, READY: 0, MAINTENANCE: 0, OUT_OF_SERVICE: 0, LONG_TERM_PARKING: 0 })),
    ])
    renderPage()

    expect(await screen.findByText('ยังไม่มีรายการรถในทะเบียน')).toBeInTheDocument()
    expect(screen.getAllByText('0 คัน')).toHaveLength(6)
  })

  it.each([
    [
      'VEHICLE_MASTER_DATA_INVALID',
      500,
      'ไม่แสดงตัวเลขสรุป',
      /ข้อมูลทะเบียนรถบางรายการไม่ครบหรือไม่ถูกต้อง/,
    ],
    [
      'VEHICLE_MASTER_SCHEMA_INVALID',
      500,
      'ไม่แสดงตัวเลขสรุป',
      /โครงสร้างตารางทะเบียนรถไม่ตรงกับที่ระบบรองรับ/,
    ],
    [
      'VEHICLE_MASTER_READ_FAILED',
      503,
      'โหลดภาพรวมกองรถไม่สำเร็จ',
      /ไม่สามารถอ่านข้อมูลทะเบียนรถได้ในขณะนี้/,
    ],
    ['INTERNAL_ERROR', 500, 'โหลดภาพรวมกองรถไม่สำเร็จ', /เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ/],
  ])('shows the Thai message for %s with request id, retry and no numbers', async (code, status, title, message) => {
    installFetch([errorResponse(code, status)])
    renderPage()

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(title)).toBeInTheDocument()
    expect(within(alert).getByText(message)).toBeInTheDocument()
    expect(within(alert).getByText('รหัสอ้างอิง: req-7b2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' })).toBeInTheDocument()
    expect(countTexts()).toHaveLength(0)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('shows a Thai generic error for a network failure, never raw English text', async () => {
    installFetch([new TypeError('Failed to fetch')])
    renderPage()

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('โหลดภาพรวมกองรถไม่สำเร็จ')).toBeInTheDocument()
    expect(within(alert).getByText(/เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ/)).toBeInTheDocument()
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument()
    expect(countTexts()).toHaveLength(0)
  })

  it('shows the permission-denied state on 403 with no numbers', async () => {
    installFetch([errorResponse('HTTP_ERROR', 403)])
    renderPage()

    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(countTexts()).toHaveLength(0)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('recovers through the retry button after a failure', async () => {
    const user = userEvent.setup()
    const calls = installFetch([errorResponse('VEHICLE_MASTER_READ_FAILED', 503), jsonResponse(summary())])
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(await screen.findByText('6 คัน')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(calls).toHaveLength(2)
  })

  it('hides previous numbers while a refresh is loading', async () => {
    const user = userEvent.setup()
    const second = deferred<Response>()
    installFetch([jsonResponse(summary()), second.promise])
    renderPage()
    expect(await screen.findByText('6 คัน')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    expect(screen.getByText('กำลังโหลดภาพรวมกองรถ...')).toBeInTheDocument()
    expect(countTexts()).toHaveLength(0)

    await act(async () => second.resolve(jsonResponse(summary({ READY: 4 }))))
    expect(await screen.findByText('9 คัน')).toBeInTheDocument()
  })

  it('ignores a slow older success that arrives after a newer refresh succeeded', async () => {
    const user = userEvent.setup()
    const first = deferred<Response>()
    const second = deferred<Response>()
    installFetch([first.promise, second.promise])
    renderPage()

    // The refresh button is usable while the mount request is pending.
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    await act(async () => second.resolve(jsonResponse(summary({ WORKING: 10 }))))
    expect(await screen.findByText('14 คัน')).toBeInTheDocument()

    await act(async () => first.resolve(jsonResponse(summary({ WORKING: 50 }))))
    await waitFor(() => expect(screen.getByText('14 คัน')).toBeInTheDocument())
    expect(screen.queryByText('54 คัน')).not.toBeInTheDocument()
  })

  it('ignores a slow older error that arrives after a newer refresh succeeded', async () => {
    const user = userEvent.setup()
    const first = deferred<Response>()
    const second = deferred<Response>()
    installFetch([first.promise, second.promise])
    renderPage()

    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    await act(async () => second.resolve(jsonResponse(summary())))
    expect(await screen.findByText('6 คัน')).toBeInTheDocument()

    await act(async () => first.resolve(errorResponse('VEHICLE_MASTER_DATA_INVALID', 500)))
    await waitFor(() => expect(screen.getByText('6 คัน')).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ignores a slow older success that arrives after a newer refresh failed', async () => {
    const user = userEvent.setup()
    const first = deferred<Response>()
    const second = deferred<Response>()
    installFetch([first.promise, second.promise])
    renderPage()

    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลใหม่' }))
    await act(async () => second.resolve(errorResponse('VEHICLE_MASTER_SCHEMA_INVALID', 500)))
    expect(await screen.findByRole('alert')).toBeInTheDocument()

    await act(async () => first.resolve(jsonResponse(summary())))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(countTexts()).toHaveLength(0)
  })

  it('makes only summary GETs under StrictMode and applies exactly one result', async () => {
    const calls = installFetch([jsonResponse(summary({ WORKING: 3 })), jsonResponse(summary({ WORKING: 3 }))])
    renderPage(true)

    const total = (await screen.findByText('รถในทะเบียนทั้งหมด')).closest('.card') as HTMLElement
    expect(within(total).getByText('7 คัน')).toBeInTheDocument()
    expect(calls.length).toBeGreaterThanOrEqual(1)
    expect(calls.length).toBeLessThanOrEqual(2)
    expect(calls.every((c) => c.path === SUMMARY_PATH && c.method === 'GET')).toBe(true)
    expect(screen.getAllByText('รถในทะเบียนทั้งหมด')).toHaveLength(1)
  })

  it('has exactly one plain unfiltered link and status cards are not links', async () => {
    installFetch([jsonResponse(summary())])
    renderPage()
    await screen.findByText('6 คัน')

    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveTextContent('ดูรายการรถทั้งหมด (ไม่กรองสถานะ)')
    expect(links[0]).toHaveAttribute('href', '/vehicles')
    for (const label of ['ใช้งานอยู่', 'พร้อมใช้งาน', 'ซ่อมบำรุง', 'หยุดใช้งาน', 'จอดระยะยาว']) {
      expect(screen.getByText(label).closest('a')).toBeNull()
    }
  })
})
