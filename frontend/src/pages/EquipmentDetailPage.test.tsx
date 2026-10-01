import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { describeErrorCode } from '../lib/labels'
import { EquipmentDetailPage } from './EquipmentDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/equipment/EQP-0001']}>
      <Routes>
        <Route path="/equipment/:equipmentId" element={<EquipmentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('EquipmentDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders equipment identity fields in Thai', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          equipment_id: 'EQP-0001',
          equipment_code: 'LATHE-01',
          name: 'เครื่องกลึงเบอร์ 1',
          category: 'LATHE',
          serial_number: 'LT-2019-0021',
          location: 'โรงซ่อมกลาง',
          operational_status: 'IN_USE',
          created_at: '2026-01-15T08:00:00Z',
          updated_at: '2026-01-15T08:00:00Z',
        }),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeInTheDocument(),
    )
    expect(screen.getByText('เครื่องกลึง')).toBeInTheDocument()
    expect(screen.getByText('โรงซ่อมกลาง')).toBeInTheDocument()
    // Equipment status renders via the equipment-specific label map
    // (decision C02), not the vehicle status label map.
    expect(screen.getByText('กำลังใช้งาน')).toBeInTheDocument()
  })

  it('shows a controlled Thai 404 message for missing equipment', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'EQUIPMENT_NOT_FOUND',
              message: "Equipment 'EQP-0001' was not found",
              details: null,
              request_id: 'req-1',
            },
          },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ไม่พบข้อมูลเครื่องมือ/อุปกรณ์นี้')).toBeInTheDocument(),
    )
  })
})

// ---------------------------------------------------------------------------
// Phase 7 Batch 7K2 — status-change outcome handling (KF01-KF06). The fetch
// stub routes by method and path and records every call, so tests can prove
// which follow-up reads happen and that the POST is never repeated.
// ---------------------------------------------------------------------------

const EQUIPMENT = {
  equipment_id: 'EQP-0001',
  equipment_code: 'LATHE-01',
  name: 'เครื่องกลึงเบอร์ 1',
  category: 'LATHE',
  serial_number: null,
  location: null,
  operational_status: 'READY',
  created_at: '2026-01-15T08:00:00Z',
  updated_at: '2026-01-15T08:00:00Z',
}
const HISTORY = [
  {
    history_id: 'ESTH-0001',
    equipment_id: 'EQP-0001',
    status: 'READY',
    changed_at: '2026-01-15T08:00:00Z',
    changed_by: 'u-1',
    reason: null,
  },
]

function envelope(code: string, details: Record<string, unknown> | null = null, requestId = 'req-7k2') {
  return { error: { code, message: code, details, request_id: requestId } }
}

type Route = (method: string, path: string, call: number) => Response | Promise<Response>

function stubFetch(route: Route) {
  const calls: { method: string; path: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const path = String(input).replace('/api/v1', '')
      calls.push({ method, path })
      return route(method, path, calls.length)
    }),
  )
  return calls
}

function readsAfterPost(calls: { method: string; path: string }[]) {
  const post = calls.findIndex((c) => c.method === 'POST')
  return calls.slice(post + 1)
}

async function openDialogAndSubmit(status = 'ซ่อมบำรุง', reason = '0007') {
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' }))
  await user.selectOptions(screen.getByLabelText('สถานะใหม่'), status)
  await user.type(screen.getByLabelText('เหตุผล (ไม่บังคับ)'), reason)
  await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
  return user
}

function defaultReads(method: string, path: string): Response | null {
  if (method === 'GET' && path === '/equipment/EQP-0001') return jsonResponse(EQUIPMENT)
  if (method === 'GET' && path === '/equipment/EQP-0001/status-history') return jsonResponse(HISTORY)
  return null
}

describe('EquipmentDetailPage — Phase 7 Batch 7K2 status outcomes', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each([
    ['EQUIPMENT_ID_AMBIGUOUS', 409, null, 'รหัสเครื่องมือนี้ซ้ำกันมากกว่าหนึ่งรายการ'],
    ['EQUIPMENT_MASTER_DATA_INVALID', 500, { issue_counts: { UNRECOGNIZED_STATUS: 1 } }, 'ข้อมูลทะเบียนเครื่องมือบางรายการไม่ถูกต้อง'],
    ['EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID', 500, { tab: 'equipment_status_history', problem: 'MISSING_HEADERS', headers: ['status_code'] }, 'โครงสร้างตารางประวัติสถานะเครื่องมือ'],
    ['EQUIPMENT_MASTER_READ_FAILED', 503, null, 'ไม่สามารถอ่านข้อมูลทะเบียนเครื่องมือได้'],
    ['EQUIPMENT_MASTER_WRITE_FAILED', 503, { equipment_write_outcome: 'rejected' }, 'Google Sheets ปฏิเสธคำขอเปลี่ยนสถานะ สถานะน่าจะยังไม่ถูกเปลี่ยน'],
  ])('KF01 P/R %s keeps the dialog open with its values and issues no refresh', async (code, status, details, text) => {
    const calls = stubFetch((method, path) => {
      const read = defaultReads(method, path)
      if (read) return read
      return jsonResponse(envelope(code, details as Record<string, unknown> | null), status)
    })
    renderPage()
    await openDialogAndSubmit()

    const dialog = await screen.findByRole('alertdialog')
    await waitFor(() => expect(within(dialog).getByRole('alert')).toHaveTextContent(text))
    expect(within(dialog).getByText('รหัสอ้างอิง: req-7k2')).toBeInTheDocument()
    expect(screen.getByLabelText('สถานะใหม่')).toHaveValue('MAINTENANCE')
    expect(screen.getByLabelText('เหตุผล (ไม่บังคับ)')).toHaveValue('0007')
    expect(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' })).toBeEnabled()
    expect(readsAfterPost(calls)).toEqual([])
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it.each([
    ['master unknown', () => jsonResponse(envelope('EQUIPMENT_MASTER_WRITE_FAILED', { equipment_write_outcome: 'unknown' }), 503),
      'ไม่ทราบผลการเปลี่ยนสถานะ (อาจเปลี่ยนแล้วหรือยังไม่เปลี่ยน) กรุณาตรวจสอบสถานะปัจจุบันก่อนลองใหม่'],
    ['history rejected', () => jsonResponse(envelope('EQUIPMENT_STATUS_HISTORY_WRITE_FAILED', { equipment_status_updated: true, history_write_outcome: 'rejected' }), 503),
      'ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว แต่คำขอบันทึกประวัติถูกปฏิเสธ'],
    ['history unknown', () => jsonResponse(envelope('EQUIPMENT_STATUS_HISTORY_WRITE_FAILED', { equipment_status_updated: true, history_write_outcome: 'unknown' }), 503),
      'ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว แต่ไม่ทราบผลการบันทึกประวัติ (อาจบันทึกแล้วหรือไม่ก็ได้)'],
    ['INTERNAL_ERROR', () => jsonResponse(envelope('INTERNAL_ERROR'), 500), 'ไม่ทราบผลการเปลี่ยนสถานะ'],
    ['no usable response', () => new Response('bad gateway', { status: 502 }), 'ไม่ทราบผลการเปลี่ยนสถานะ'],
    ['network failure', () => Promise.reject(new TypeError('Failed to fetch')), 'ไม่ทราบผลการเปลี่ยนสถานะ'],
  ])('KF02 U/H %s: dialog closes, page warning, exactly one refresh, no POST retry', async (_label, post, text) => {
    const calls = stubFetch((method, path) => defaultReads(method, path) ?? post())
    renderPage()
    await openDialogAndSubmit()

    const warning = await screen.findByText(text, { exact: false })
    expect(warning.closest('[role="alert"]')).not.toBeNull()
    await waitFor(() => expect(document.activeElement).toBe(warning.closest('[role="alert"]')))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() => expect(readsAfterPost(calls)).toHaveLength(2))
    expect(readsAfterPost(calls).map((c) => c.path).sort()).toEqual([
      '/equipment/EQP-0001',
      '/equipment/EQP-0001/status-history',
    ])
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' })).toBeEnabled()
  })

  it('KF03 a failed refresh keeps the shown data and the warning, and offers a manual reload only', async () => {
    let posted = false
    const calls = stubFetch((method, path) => {
      if (method === 'POST') {
        posted = true
        return jsonResponse(envelope('EQUIPMENT_STATUS_HISTORY_WRITE_FAILED', { equipment_status_updated: true, history_write_outcome: 'unknown' }), 503)
      }
      if (posted) return jsonResponse(envelope('EQUIPMENT_MASTER_READ_FAILED'), 503)
      return defaultReads(method, path) ?? jsonResponse({}, 404)
    })
    renderPage()
    const user = await openDialogAndSubmit()

    expect(await screen.findByText('โหลดข้อมูลล่าสุดไม่สำเร็จ ข้อมูลที่แสดงอาจไม่เป็นปัจจุบัน')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeInTheDocument()
    expect(screen.getByText('ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว', { exact: false })).toBeInTheDocument()
    expect(screen.queryByText('เกิดข้อผิดพลาด')).not.toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(readsAfterPost(calls)).toHaveLength(2) // no automatic re-request
    await user.click(screen.getByRole('button', { name: 'โหลดใหม่' }))
    await waitFor(() => expect(readsAfterPost(calls)).toHaveLength(4))
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
    expect(screen.getByText('ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว', { exact: false })).toBeInTheDocument()
  })

  it('KF04 the warning is cleared by dismissing it or by a new submission', async () => {
    let posts = 0
    stubFetch((method, path) => {
      if (method === 'POST') {
        posts += 1
        return posts === 1
          ? jsonResponse(envelope('EQUIPMENT_MASTER_WRITE_FAILED', { equipment_write_outcome: 'unknown' }), 503)
          : jsonResponse({ ...EQUIPMENT, operational_status: 'MAINTENANCE' })
      }
      return defaultReads(method, path) ?? jsonResponse({}, 404)
    })
    renderPage()
    const user = await openDialogAndSubmit()
    expect(await screen.findByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ปิดคำเตือน' }))
    expect(screen.queryByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).not.toBeInTheDocument()

    // Warning again, then a new (successful) submission clears it.
    posts = 0
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    expect(await screen.findByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    await waitFor(() => expect(screen.queryByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).not.toBeInTheDocument())
  })

  it('KF05 a failed history load is shown as a history error, not an empty history', async () => {
    stubFetch((method, path) => {
      if (path === '/equipment/EQP-0001/status-history') {
        return jsonResponse(envelope('EQUIPMENT_STATUS_HISTORY_DATA_INVALID', { issue_counts: { MIXED_TIMEZONE_TIMESTAMP: 2 } }), 500)
      }
      return defaultReads(method, path) ?? jsonResponse({}, 404)
    })
    renderPage()
    expect(
      await screen.findByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false }),
    ).toHaveTextContent('ข้อมูลประวัติการเปลี่ยนสถานะบางรายการไม่ถูกต้อง')
    expect(screen.queryByText(/ประวัติการเปลี่ยนสถานะ \(/)).not.toBeInTheDocument()
  })

  it('KF05 a successful history load still lists entries, including duplicate history ids', async () => {
    stubFetch((method, path) => {
      if (path === '/equipment/EQP-0001/status-history') return jsonResponse([...HISTORY, { ...HISTORY[0], status: 'IN_USE' }])
      return defaultReads(method, path) ?? jsonResponse({}, 404)
    })
    renderPage()
    expect(await screen.findByText('ประวัติการเปลี่ยนสถานะ (2)')).toBeInTheDocument()
  })

  it('success keeps the existing behaviour: the dialog closes and the page reloads', async () => {
    const calls = stubFetch((method, path) => defaultReads(method, path) ?? jsonResponse({ ...EQUIPMENT, operational_status: 'MAINTENANCE' }))
    renderPage()
    await openDialogAndSubmit()
    await waitFor(() => expect(readsAfterPost(calls)).toHaveLength(2))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('KF06 every new error code has its own Thai message', () => {
    const generic = describeErrorCode('SOMETHING_UNKNOWN')
    for (const code of [
      'EQUIPMENT_ID_AMBIGUOUS',
      'EQUIPMENT_MASTER_DATA_INVALID',
      'EQUIPMENT_MASTER_SCHEMA_INVALID',
      'EQUIPMENT_MASTER_READ_FAILED',
      'EQUIPMENT_STATUS_HISTORY_DATA_INVALID',
      'EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID',
      'EQUIPMENT_STATUS_HISTORY_READ_FAILED',
      'EQUIPMENT_MASTER_WRITE_FAILED',
      'EQUIPMENT_STATUS_HISTORY_WRITE_FAILED',
      'EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK',
    ]) {
      expect(describeErrorCode(code)).not.toBe(generic)
    }
  })
})

// ---------------------------------------------------------------------------
// Phase 7 Batch 7K2 correction — regression tests.
// Finding 1: a U/H refresh succeeds only when BOTH reads succeed; otherwise the
// previously shown equipment AND history are kept, the stale notice and manual
// reload appear, and a history failure is shown without discarding history.
// Finding 2: only the newest read may apply data, history errors, staleness or
// the refreshing state (deferred responses below control completion order).
// ---------------------------------------------------------------------------

const PREVIOUS_HISTORY = [{ ...HISTORY[0], reason: 'ประวัติเดิม' }]
const UNKNOWN_POST = () =>
  jsonResponse(envelope('EQUIPMENT_MASTER_WRITE_FAILED', { equipment_write_outcome: 'unknown' }), 503)
const HISTORY_FAIL = () =>
  jsonResponse(envelope('EQUIPMENT_STATUS_HISTORY_DATA_INVALID', { issue_counts: { BLANK_STATUS: 1 } }), 500)
const DETAIL_FAIL = () => jsonResponse(envelope('EQUIPMENT_MASTER_READ_FAILED'), 503)

describe('EquipmentDetailPage — 7K2 correction, Finding 1: combined refresh', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function refreshScenario(detail: () => Response, history: () => Response) {
    let posted = false
    let refreshPairs = 0
    let historyCalls = 0
    const calls = stubFetch((method, path) => {
      if (method === 'POST') {
        posted = true
        return UNKNOWN_POST()
      }
      if (path === '/equipment/EQP-0001/status-history') {
        historyCalls += 1
        if (!posted) return jsonResponse(PREVIOUS_HISTORY)
        if (refreshPairs >= 1 && historyCalls > 2) {
          return jsonResponse([...PREVIOUS_HISTORY, { ...HISTORY[0], history_id: 'ESTH-0002', reason: 'ประวัติใหม่' }])
        }
        return history()
      }
      if (!posted) return jsonResponse(EQUIPMENT)
      refreshPairs += 1
      if (refreshPairs > 1) return jsonResponse({ ...EQUIPMENT, name: 'ชื่อหลังโหลดใหม่' })
      return detail()
    })
    return calls
  }

  async function expectPreviousStateKept() {
    expect(await screen.findByText('โหลดข้อมูลล่าสุดไม่สำเร็จ ข้อมูลที่แสดงอาจไม่เป็นปัจจุบัน')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'โหลดใหม่' })).toBeEnabled()
    expect(screen.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'ชื่อที่ไม่ควรแสดง' })).not.toBeInTheDocument()
    expect(screen.getByText('ประวัติการเปลี่ยนสถานะ (1)')).toBeInTheDocument()
    expect(screen.getByText('ประวัติเดิม', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).toBeInTheDocument()
  }

  it('R1a detail succeeds but history fails: previous equipment and history kept, stale + history error shown', async () => {
    refreshScenario(() => jsonResponse({ ...EQUIPMENT, name: 'ชื่อที่ไม่ควรแสดง' }), HISTORY_FAIL)
    renderPage()
    await openDialogAndSubmit()
    await expectPreviousStateKept()
    expect(screen.getByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).toBeInTheDocument()
  })

  it('R1b detail fails but history succeeds: previous equipment and history kept, stale shown', async () => {
    refreshScenario(DETAIL_FAIL, () => jsonResponse([]))
    renderPage()
    await openDialogAndSubmit()
    await expectPreviousStateKept()
    expect(screen.queryByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).not.toBeInTheDocument()
  })

  it('R1c both fail: previous equipment and history kept, stale + history error shown', async () => {
    refreshScenario(DETAIL_FAIL, HISTORY_FAIL)
    renderPage()
    await openDialogAndSubmit()
    await expectPreviousStateKept()
    expect(screen.getByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).toBeInTheDocument()
  })

  it('R1d a later successful manual reload replaces the data and clears staleness and the history error', async () => {
    const calls = refreshScenario(() => jsonResponse({ ...EQUIPMENT, name: 'ชื่อที่ไม่ควรแสดง' }), HISTORY_FAIL)
    renderPage()
    const user = await openDialogAndSubmit()
    await expectPreviousStateKept()
    await user.click(screen.getByRole('button', { name: 'โหลดใหม่' }))
    expect(await screen.findByRole('heading', { name: 'ชื่อหลังโหลดใหม่' })).toBeInTheDocument()
    expect(screen.queryByText('โหลดข้อมูลล่าสุดไม่สำเร็จ', { exact: false })).not.toBeInTheDocument()
    expect(screen.queryByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).not.toBeInTheDocument()
    expect(screen.getByText('ประวัติการเปลี่ยนสถานะ (2)')).toBeInTheDocument()
    expect(screen.getByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })
})

type PendingCall = {
  method: string
  path: string
  resolve: (response: Response) => void
}

function deferredFetch() {
  const pending: PendingCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((resolve) => {
          pending.push({ method: init?.method ?? 'GET', path: String(input).replace('/api/v1', ''), resolve })
        }),
    ),
  )
  return pending
}

async function takeCall(pending: PendingCall[], method: string, path: string): Promise<PendingCall> {
  let found: PendingCall | undefined
  await waitFor(() => {
    found = pending.find((c) => c.method === method && c.path === path)
    expect(found).toBeDefined()
  })
  pending.splice(pending.indexOf(found!), 1)
  return found!
}

async function settle(call: PendingCall, response: Response) {
  await act(async () => {
    call.resolve(response)
  })
}

async function resolvePair(pending: PendingCall[], id: string, detail: Response, history: Response) {
  const d = await takeCall(pending, 'GET', `/equipment/${id}`)
  const h = await takeCall(pending, 'GET', `/equipment/${id}/status-history`)
  return { d, h, settle: async () => { await settle(d, detail); await settle(h, history) } }
}

async function submitFromPage(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' }))
  await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
}

describe('EquipmentDetailPage — 7K2 correction, Finding 2: read ordering', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function loadedPage() {
    const pending = deferredFetch()
    renderPage()
    const initial = await resolvePair(pending, 'EQP-0001', jsonResponse(EQUIPMENT), jsonResponse(PREVIOUS_HISTORY))
    await initial.settle()
    await screen.findByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })
    return { pending, user: userEvent.setup() }
  }

  async function unknownOutcomeWithPendingRefresh(pending: PendingCall[], user: ReturnType<typeof userEvent.setup>) {
    await submitFromPage(user)
    await settle(await takeCall(pending, 'POST', '/equipment/EQP-0001/status'), UNKNOWN_POST())
    await screen.findByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })
    const d = await takeCall(pending, 'GET', '/equipment/EQP-0001')
    const h = await takeCall(pending, 'GET', '/equipment/EQP-0001/status-history')
    return { d, h }
  }

  it('R2-1 an older U/H refresh cannot overwrite a newer successful submission and reload', async () => {
    const { pending, user } = await loadedPage()
    const older = await unknownOutcomeWithPendingRefresh(pending, user)
    await submitFromPage(user)
    await settle(await takeCall(pending, 'POST', '/equipment/EQP-0001/status'), jsonResponse({ ...EQUIPMENT, operational_status: 'MAINTENANCE' }))
    const reload = await resolvePair(pending, 'EQP-0001', jsonResponse({ ...EQUIPMENT, name: 'ข้อมูลใหม่ล่าสุด' }),
      jsonResponse([...PREVIOUS_HISTORY, { ...HISTORY[0], history_id: 'ESTH-0002', reason: 'ล่าสุด' }]))
    await reload.settle()
    expect(await screen.findByRole('heading', { name: 'ข้อมูลใหม่ล่าสุด' })).toBeInTheDocument()
    await settle(older.d, jsonResponse({ ...EQUIPMENT, name: 'ข้อมูลเก่าที่มาช้า' }))
    await settle(older.h, jsonResponse([]))
    expect(screen.getByRole('heading', { name: 'ข้อมูลใหม่ล่าสุด' })).toBeInTheDocument()
    expect(screen.getByText('ประวัติการเปลี่ยนสถานะ (2)')).toBeInTheDocument()
  })

  it('R2-2 an older refresh failure cannot mark newer successful data stale', async () => {
    const { pending, user } = await loadedPage()
    const older = await unknownOutcomeWithPendingRefresh(pending, user)
    await submitFromPage(user)
    await settle(await takeCall(pending, 'POST', '/equipment/EQP-0001/status'), jsonResponse(EQUIPMENT))
    const reload = await resolvePair(pending, 'EQP-0001', jsonResponse({ ...EQUIPMENT, name: 'ข้อมูลใหม่ล่าสุด' }), jsonResponse(PREVIOUS_HISTORY))
    await reload.settle()
    await screen.findByRole('heading', { name: 'ข้อมูลใหม่ล่าสุด' })
    await settle(older.d, DETAIL_FAIL())
    await settle(older.h, HISTORY_FAIL())
    expect(screen.queryByText('โหลดข้อมูลล่าสุดไม่สำเร็จ', { exact: false })).not.toBeInTheDocument()
    expect(screen.queryByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).not.toBeInTheDocument()
  })

  it('R2-3 responses for a previous equipment id cannot replace the current route data', async () => {
    const pending = deferredFetch()
    render(
      <MemoryRouter initialEntries={['/equipment/EQP-0001']}>
        <Routes>
          <Route
            path="/equipment/:equipmentId"
            element={
              <>
                <Link to="/equipment/EQP-0002">ไปเครื่องที่สอง</Link>
                <EquipmentDetailPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    )
    const first = await resolvePair(pending, 'EQP-0001', jsonResponse({ ...EQUIPMENT, name: 'เครื่องแรก' }), jsonResponse(PREVIOUS_HISTORY))
    await userEvent.setup().click(screen.getByRole('link', { name: 'ไปเครื่องที่สอง' }))
    const second = await resolvePair(pending, 'EQP-0002',
      jsonResponse({ ...EQUIPMENT, equipment_id: 'EQP-0002', name: 'เครื่องที่สอง' }), jsonResponse([]))
    await second.settle()
    expect(await screen.findByRole('heading', { name: 'เครื่องที่สอง' })).toBeInTheDocument()
    await first.settle()
    expect(screen.getByRole('heading', { name: 'เครื่องที่สอง' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'เครื่องแรก' })).not.toBeInTheDocument()
    expect(screen.getByText('รหัสเครื่องมือ: EQP-0002')).toBeInTheDocument()
  })

  it('R2-4 an older completion cannot clear the current request refreshing state', async () => {
    const { pending, user } = await loadedPage()
    const first = await unknownOutcomeWithPendingRefresh(pending, user)
    await settle(first.d, DETAIL_FAIL())
    await settle(first.h, jsonResponse(PREVIOUS_HISTORY))
    await user.click(await screen.findByRole('button', { name: 'โหลดใหม่' }))
    const manual = {
      d: await takeCall(pending, 'GET', '/equipment/EQP-0001'),
      h: await takeCall(pending, 'GET', '/equipment/EQP-0001/status-history'),
    }
    expect(screen.getByRole('button', { name: 'กำลังโหลด...' })).toBeDisabled()
    const current = await unknownOutcomeWithPendingRefresh(pending, user)
    expect(screen.getByRole('button', { name: 'กำลังโหลด...' })).toBeDisabled()
    await settle(manual.d, jsonResponse({ ...EQUIPMENT, name: 'ข้อมูลเก่าที่มาช้า' }))
    await settle(manual.h, jsonResponse(PREVIOUS_HISTORY))
    expect(screen.getByRole('button', { name: 'กำลังโหลด...' })).toBeDisabled()
    expect(screen.queryByRole('heading', { name: 'ข้อมูลเก่าที่มาช้า' })).not.toBeInTheDocument()
    await settle(current.d, jsonResponse({ ...EQUIPMENT, name: 'ข้อมูลปัจจุบัน' }))
    await settle(current.h, jsonResponse(PREVIOUS_HISTORY))
    expect(await screen.findByRole('heading', { name: 'ข้อมูลปัจจุบัน' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'กำลังโหลด...' })).not.toBeInTheDocument()
    expect(screen.queryByText('โหลดข้อมูลล่าสุดไม่สำเร็จ', { exact: false })).not.toBeInTheDocument()
  })

  it('R2-5 reads pending before a new submission cannot apply during that newer mutation', async () => {
    const { pending, user } = await loadedPage()
    const older = await unknownOutcomeWithPendingRefresh(pending, user)
    await submitFromPage(user)
    const post = await takeCall(pending, 'POST', '/equipment/EQP-0001/status')
    await settle(older.d, jsonResponse({ ...EQUIPMENT, name: 'ข้อมูลระหว่างบันทึก' }))
    await settle(older.h, HISTORY_FAIL())
    expect(screen.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeInTheDocument()
    expect(screen.queryByText('โหลดข้อมูลล่าสุดไม่สำเร็จ', { exact: false })).not.toBeInTheDocument()
    expect(screen.queryByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).not.toBeInTheDocument()
    await settle(post, jsonResponse(EQUIPMENT))
    const reload = await resolvePair(pending, 'EQP-0001', jsonResponse({ ...EQUIPMENT, name: 'หลังบันทึกสำเร็จ' }), jsonResponse(PREVIOUS_HISTORY))
    await reload.settle()
    expect(await screen.findByRole('heading', { name: 'หลังบันทึกสำเร็จ' })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Phase 7 Batch 7K2 final correction — route-specific state on equipment-id
// change. The same mounted route element switches from EQP-0001 (A) to
// EQP-0002 (B); A's POST may still be pending. B must start clean, and nothing
// that completes for A may change B's state or trigger B reads/warnings.
// ---------------------------------------------------------------------------

const EQUIPMENT_B = { ...EQUIPMENT, equipment_id: 'EQP-0002', name: 'เครื่องที่สอง' }

function renderSwitchablePage() {
  return render(
    <MemoryRouter initialEntries={['/equipment/EQP-0001']}>
      <Routes>
        <Route
          path="/equipment/:equipmentId"
          element={
            <>
              <Link to="/equipment/EQP-0002">ไปเครื่องที่สอง</Link>
              <EquipmentDetailPage />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

async function loadA(pending: PendingCall[]) {
  const a = await resolvePair(pending, 'EQP-0001', jsonResponse(EQUIPMENT), jsonResponse(PREVIOUS_HISTORY))
  await a.settle()
  await screen.findByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })
}

async function goToB(pending: PendingCall[], user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('link', { name: 'ไปเครื่องที่สอง' }))
  const b = await resolvePair(pending, 'EQP-0002', jsonResponse(EQUIPMENT_B), jsonResponse([]))
  await b.settle()
  await screen.findByRole('heading', { name: 'เครื่องที่สอง' })
}

function expectCleanPage() {
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText('โหลดข้อมูลล่าสุดไม่สำเร็จ', { exact: false })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'กำลังโหลด...' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' })).toBeEnabled()
}

describe('EquipmentDetailPage — 7K2 final correction: route-specific state', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('R3-1 a pending POST for A neither leaks into B nor changes B when it completes', async () => {
    const pending = deferredFetch()
    const user = userEvent.setup()
    renderSwitchablePage()
    await loadA(pending)

    // 1. A's status change stays pending while the route moves to B.
    await submitFromPage(user)
    const postA = await takeCall(pending, 'POST', '/equipment/EQP-0001/status')
    expect(screen.getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled()
    await goToB(pending, user)

    // 2. B inherits no dialog, error, warning, stale/refreshing or submitting state.
    expectCleanPage()

    // 3. B can open its dialog and submit.
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' }))
    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    const postB = await takeCall(pending, 'POST', '/equipment/EQP-0002/status')
    expect(screen.getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled()

    // 4. A's POST completes (an outcome that would warn and refresh A): B is untouched.
    await settle(postA, UNKNOWN_POST())
    expect(screen.getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(screen.queryByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).not.toBeInTheDocument()
    expect(pending.filter((c) => c.method === 'GET')).toEqual([])

    // 5. B's POST completes normally: dialog closes and B reloads.
    await settle(postB, jsonResponse({ ...EQUIPMENT_B, operational_status: 'MAINTENANCE' }))
    const reload = await resolvePair(pending, 'EQP-0002', jsonResponse({ ...EQUIPMENT_B, name: 'เครื่องที่สองหลังบันทึก' }), jsonResponse([]))
    await reload.settle()
    expect(await screen.findByRole('heading', { name: 'เครื่องที่สองหลังบันทึก' })).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(pending).toEqual([])
  })

  it('R3-2 a warning and stale notice from A do not carry into B', async () => {
    const pending = deferredFetch()
    const user = userEvent.setup()
    renderSwitchablePage()
    await loadA(pending)
    await submitFromPage(user)
    await settle(await takeCall(pending, 'POST', '/equipment/EQP-0001/status'), UNKNOWN_POST())
    const refresh = await resolvePair(pending, 'EQP-0001', DETAIL_FAIL(), HISTORY_FAIL())
    await refresh.settle()
    expect(await screen.findByText('โหลดข้อมูลล่าสุดไม่สำเร็จ', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('ไม่ทราบผลการเปลี่ยนสถานะ', { exact: false })).toBeInTheDocument()

    await goToB(pending, user)
    expectCleanPage()
  })

  it('R3-2 an open dialog with an inline error on A does not carry into B', async () => {
    const pending = deferredFetch()
    const user = userEvent.setup()
    renderSwitchablePage()
    await loadA(pending)
    await submitFromPage(user)
    await settle(await takeCall(pending, 'POST', '/equipment/EQP-0001/status'),
      jsonResponse(envelope('EQUIPMENT_ID_AMBIGUOUS', { match_count: 2 }), 409))
    expect(within(screen.getByRole('alertdialog')).getByRole('alert')).toHaveTextContent('รหัสเครื่องมือนี้ซ้ำกัน')

    await goToB(pending, user)
    expectCleanPage()
  })
})
