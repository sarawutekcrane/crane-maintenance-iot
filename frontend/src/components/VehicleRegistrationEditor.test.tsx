import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReferenceLoad } from '../lib/referenceResolution'
import { PendingStore, storageKey } from '../lib/registryPending'
import type { RegistrationHistory, VehicleRegistry } from '../lib/types'
import { VehicleRegistrationEditor } from './VehicleRegistrationEditor'

// Phase 7 Batch 7O2b — the registration editor (contract Final Rev2 §4.4,
// §4.6, §10.2-§10.4; Outcome Classification Addendum A.2; review
// clarifications C5, C6). Synthetic data only.

const VID = 'SYN-V1'
const UNKNOWN = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'

function reg(no: string | null, province: string | null, state: 'RECORDED' | 'NOT_IN_SCHEMA' = 'RECORDED'): VehicleRegistry {
  const field = (value: string | null) =>
    state === 'NOT_IN_SCHEMA' ? { state, value: null } : value === null ? { state: 'NOT_RECORDED' as const, value: null } : { state, value }
  return { registration_no: field(no), registration_province: field(province), responsible_branch: { state: 'NOT_RECORDED', value: null } }
}

const PROVINCES: ReferenceLoad = {
  kind: 'ready',
  byCode: new Map([
    ['TH-10', { name: 'กรุงเทพมหานคร', isActive: true }],
    ['TH-21', { name: 'ระยอง', isActive: true }],
    ['TH-76', { name: 'เพชรบุรี', isActive: false }],
  ]),
}

function hist(consistency = 'CONSISTENT', requestIds: string[] = ['seed-1']): RegistrationHistory {
  return {
    vehicle_id: VID,
    current: { registration_no: { state: 'RECORDED', value: '0099' }, registration_province: { state: 'RECORDED', value: 'TH-10' } },
    consistency, history_revision: 'RHR1-abc', excluded_test_rows: 0, issues: {},
    items: requestIds.map((rid, n) => ({
      change_id: `VRH-${n}`, change_kind: 'CHANGE', old_registration_no: null, old_registration_province_code: null,
      new_registration_no: '0012', new_registration_province_code: 'TH-21', recorded_at: '2026-09-01T00:00:00+00:00',
      recorded_by: 'u', request_id: rid, related_request_id: null, accepted_exceptions: [], note_th: null,
    })),
  }
}

interface Sent {
  url: string
  method: string
  requestId: string
  body: Record<string, unknown>
  storedBefore: string | null
}

type Reply = (sent: Sent) => Response | Promise<Response>

function respond(status: number, body: (rid: string) => unknown, header = true): Reply {
  return (sent) =>
    new Response(JSON.stringify(body(sent.requestId)), {
      status,
      headers: { 'Content-Type': 'application/json', ...(header ? { 'X-Request-Id': sent.requestId } : {}) },
    })
}
const ok = respond(200, (rid) => ({
  request_id: rid, changed: true, master_write: 'WRITTEN', warnings: [],
  change: { change_id: 'VRH-' + 'f'.repeat(32), recorded_at: '2026-10-05T00:00:00.000001+00:00', request_id: rid },
}))
const coded = (status: number, code: string, details: Record<string, unknown> | null = null) =>
  respond(status, (rid) => ({ error: { code, message: code, details, request_id: rid } }))

function installFetch(...replies: Reply[]) {
  const sent: Sent[] = []
  const queue = [...replies]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      const s: Sent = {
        url: String(url),
        method: String(init.method),
        requestId: new Headers(init.headers).get('X-Request-Id') ?? '',
        body: JSON.parse(String(init.body)) as Record<string, unknown>,
        storedBefore: window.localStorage.getItem(storageKey('u1', VID)),
      }
      sent.push(s)
      const reply = queue.shift()
      if (!reply) throw new Error(`unexpected request ${s.method} ${s.url}`)
      return reply(s)
    }),
  )
  return sent
}

let store: PendingStore
let onRefresh: ReturnType<typeof vi.fn<() => void>>

function renderEditor(props: Partial<Parameters<typeof VehicleRegistrationEditor>[0]> = {}) {
  return render(
    <MemoryRouter>
      <VehicleRegistrationEditor
        vehicleId={VID}
        registry={reg(' กข 1 ', 'TH-21')}
        provinces={PROVINCES}
        history={hist()}
        userId="u1"
        getRouteEpoch={() => 7}
        onRefresh={onRefresh}
        store={store}
        {...props}
      />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  window.localStorage.clear()
  store = new PendingStore(() => window.localStorage)
  onRefresh = vi.fn<() => void>()
})
afterEach(() => vi.unstubAllGlobals())

describe('editing', () => {
  it('prefills the stored text exactly and sends it untrimmed, persisting the intent before the request', async () => {
    const sent = installFetch(ok)
    const user = userEvent.setup()
    renderEditor()
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    const input = screen.getByLabelText('ทะเบียนรถ') as HTMLInputElement
    expect(input.value).toBe(' กข 1 ')
    await user.type(input, '2 ')
    await user.selectOptions(screen.getByLabelText('จังหวัดที่จดทะเบียน'), 'TH-10')
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    await screen.findByText('บันทึกทะเบียนเรียบร้อยแล้ว')
    expect(sent).toHaveLength(1)
    expect(sent[0]).toMatchObject({ url: `/api/v1/vehicles/${VID}/registration`, method: 'PATCH' })
    expect(sent[0].body).toEqual({
      registration_no: ' กข 1 2 ', registration_province_code: 'TH-10',
      expected_registration_no: ' กข 1 ', expected_registration_province_code: 'TH-21',
    })
    const stored = JSON.parse(sent[0].storedBefore as string)
    expect(stored[0]).toMatchObject({ request_id: sent[0].requestId, state: 'SUBMITTING', route_epoch: 7, body: sent[0].body })
    expect(store.list('u1', VID)).toEqual([]) // confirmed applied -> removed
    expect(onRefresh).toHaveBeenCalled()
  })

  it('clearing is explicit and sends null/null; an empty text is blocked without a request', async () => {
    const sent = installFetch(ok)
    const user = userEvent.setup()
    renderEditor()
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.clear(screen.getByLabelText('ทะเบียนรถ'))
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    expect(await screen.findByText(/กรุณากรอกทะเบียน/)).toBeInTheDocument()
    expect(sent).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'ล้างทะเบียน' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ registration_no: null, registration_province_code: null })
  })

  it('an inactive province cannot be newly chosen but the current one stays selectable', () => {
    const kept = renderEditor({ registry: reg('x', 'TH-76') })
    act(() => screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }).click())
    const select = screen.getByLabelText('จังหวัดที่จดทะเบียน') as HTMLSelectElement
    expect(select.value).toBe('TH-76')
    expect((within(select).getByRole('option', { name: /เพชรบุรี/ }) as HTMLOptionElement).disabled).toBe(false)
    kept.unmount()
    renderEditor({ registry: reg('x', 'TH-21') })
    act(() => screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }).click())
    const other = screen.getByLabelText('จังหวัดที่จดทะเบียน') as HTMLSelectElement
    expect((within(other).getByRole('option', { name: /เพชรบุรี/ }) as HTMLOptionElement).disabled).toBe(true)
  })

  it('C6: with /provinces unavailable only the recorded raw code stays and nothing new is offered', () => {
    renderEditor({ provinces: { kind: 'unavailable' }, registry: reg('x', 'TH-99') })
    act(() => screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }).click())
    const select = screen.getByLabelText('จังหวัดที่จดทะเบียน') as HTMLSelectElement
    expect(select.value).toBe('TH-99')
    expect([...select.options].map((o) => o.value)).toEqual(['', 'TH-99'])
    expect(screen.getByText(/โหลดรายชื่อจังหวัดไม่ได้/)).toBeInTheDocument()
  })

  it('NOT_IN_SCHEMA disables the editor and explains the source column is unavailable', () => {
    renderEditor({ registry: reg(null, null, 'NOT_IN_SCHEMA') })
    expect(screen.getByText('แหล่งข้อมูลยังไม่มีช่องนี้ จึงแก้ไขทะเบียนไม่ได้')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'เปลี่ยนทะเบียน' })).toBeNull()
    expect(screen.queryByText('ยังไม่ได้บันทึก')).toBeNull()
  })

  it('C5: without a user id the editor is disabled and no shared key is created', () => {
    window.localStorage.setItem('unrelated', '1')
    renderEditor({ userId: null })
    expect(screen.getByText('ไม่ทราบผู้ใช้ปัจจุบัน จึงแก้ไขทะเบียนไม่ได้ในขณะนี้')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'เปลี่ยนทะเบียน' })).toBeNull()
    expect(Object.keys(window.localStorage).filter((k) => k.startsWith('crane.registryPending'))).toEqual([])
  })
})

describe('proven refusals stay inline and keep the typed values', () => {
  async function saveWith(reply: Reply) {
    const sent = installFetch(reply)
    const user = userEvent.setup()
    renderEditor()
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.type(screen.getByLabelText('ทะเบียนรถ'), 'X')
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    return sent
  }

  it('stale: message, reload action, typed value kept, intent removed', async () => {
    await saveWith(coded(409, 'VEHICLE_REGISTRY_STALE', { current_matches_request: false }))
    expect(await screen.findByText(/มีผู้อื่นแก้ไขทะเบียน/)).toBeInTheDocument()
    expect((screen.getByLabelText('ทะเบียนรถ') as HTMLInputElement).value).toBe(' กข 1 X')
    expect(store.list('u1', VID)).toEqual([])
    await userEvent.setup().click(screen.getByRole('button', { name: 'โหลดใหม่' }))
    expect(onRefresh).toHaveBeenCalled()
  })

  it('duplicate: names the other vehicles, linking only safe ids', async () => {
    await saveWith(coded(409, 'REGISTRATION_DUPLICATE', { conflict_count: 3, conflict_vehicle_ids: ['VEH-2', 'a/b'] }))
    expect(await screen.findByText('ทะเบียนและจังหวัดนี้ถูกใช้กับรถคันอื่นอยู่แล้ว')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'VEH-2' })).toHaveAttribute('href', '/vehicle/VEH-2')
    expect(screen.queryByRole('link', { name: 'a/b' })).toBeNull()
    expect(screen.getByText(/a\/b/)).toBeInTheDocument()
  })

  it('projection mismatch offers reconciliation', async () => {
    await saveWith(coded(409, 'REGISTRATION_PROJECTION_MISMATCH'))
    expect(await screen.findByText(/ต้องปรับข้อมูลให้ตรงกันก่อน/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ปรับข้อมูลทะเบียนให้ตรงกับประวัติ' })).toBeInTheDocument()
  })
})

describe('uncertain outcomes (W-OC-02, W-OC-06)', () => {
  it('500 INTERNAL_ERROR keeps the intent with the UNKNOWN banner; never "not saved"; explicit resend reuses id and body', async () => {
    const sent = installFetch(coded(500, 'INTERNAL_ERROR'), coded(409, 'VEHICLE_REGISTRY_STALE'))
    const user = userEvent.setup()
    renderEditor()
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    const banner = await screen.findByTestId('registration-intent-banner')
    expect(within(banner).getByText(UNKNOWN)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('ไม่ได้บันทึก')
    expect(sent).toHaveLength(1)
    await user.click(within(banner).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    await waitFor(() => expect(sent).toHaveLength(2))
    expect(sent[1].requestId).toBe(sent[0].requestId)
    expect(sent[1].body).toEqual(sent[0].body)
    // the refused resend is shown AND the uncertainty banner stays
    expect(await screen.findByText(/คำขอที่ส่งซ้ำถูกปฏิเสธ/)).toBeInTheDocument()
    expect(screen.getByTestId('registration-intent-banner')).toBeInTheDocument()
    expect(store.list('u1', VID)).toHaveLength(1)
  })

  it('acknowledgement removes the local intent only and says what it does not establish', async () => {
    store.add('u1', {
      request_id: 'r-unknown', operation: 'registration', vehicle_id: VID, body: { registration_no: 'a' },
      submitted_at: new Date().toISOString(), state: 'UNKNOWN', page_instance: 'p', route_epoch: 0, prior_uncertain: true,
    })
    const sent = installFetch()
    renderEditor()
    expect(screen.getByText(/ไม่ได้ยืนยันว่าการบันทึกครั้งแรกสำเร็จหรือไม่/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'รับทราบ' }))
    expect(screen.queryByTestId('registration-intent-banner')).toBeNull()
    expect(store.list('u1', VID)).toEqual([])
    expect(sent).toHaveLength(0) // nothing is sent to the server
  })

  it('W2 failure: RECORDED_PROJECTION_PENDING and a reconcile dialog that sends the contract body', async () => {
    const sent = installFetch(
      coded(503, 'VEHICLE_MASTER_WRITE_FAILED', { history_recorded: true, change_id: 'VRH-1', master_write_outcome: 'rejected' }),
      respond(200, (rid) => ({
        request_id: rid, changed: true, master_write: 'WRITTEN', warnings: [],
        change: { change_id: 'VRH-2', recorded_at: 'x', request_id: rid },
      })),
    )
    const user = userEvent.setup()
    renderEditor({ history: hist('MISMATCH') })
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    const banner = await screen.findByTestId('registration-intent-banner')
    expect(within(banner).getByText(/บันทึกในประวัติแล้ว แต่ทะเบียนในข้อมูลทะเบียนรถยังไม่ตรงกับประวัติ/)).toBeInTheDocument()
    expect(within(banner).queryByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).toBeNull()
    await user.click(within(banner).getByRole('button', { name: 'ปรับข้อมูลให้ตรงกัน' }))
    const dialog = screen.getByRole('alertdialog')
    expect((within(dialog).getByLabelText(/รหัสคำขอที่เกี่ยวข้อง/) as HTMLInputElement).value).toBe(sent[0].requestId)
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการปรับข้อมูล' }))
    expect(within(dialog).getByText('กรุณาเลือกวิธีปรับข้อมูลให้ตรงกัน')).toBeInTheDocument()
    await user.click(within(dialog).getByLabelText(/ใช้ค่าตามประวัติล่าสุด/))
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'แก้ให้ตรง')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการปรับข้อมูล' }))
    await waitFor(() => expect(sent).toHaveLength(2))
    expect(sent[1]).toMatchObject({ url: `/api/v1/vehicles/${VID}/registration-history/reconciliations`, method: 'POST' })
    expect(sent[1].body).toEqual({
      mode: 'APPLY_RECORDED', expected_registration_no: ' กข 1 ', expected_registration_province_code: 'TH-21',
      expected_history_revision: 'RHR1-abc', reason_th: 'แก้ให้ตรง', related_request_id: sent[0].requestId,
    })
    expect(sent[1].requestId).not.toBe(sent[0].requestId)
    // the original intent is still pending: the reconciliation's audit link settles nothing
    expect(store.list('u1', VID).map((i) => i.state)).toEqual(['RECORDED_PROJECTION_PENDING'])
  })

  it('a blank related request id is omitted from the reconciliation body', async () => {
    const sent = installFetch(respond(200, (rid) => ({ request_id: rid, changed: false, warnings: [] })))
    const user = userEvent.setup()
    renderEditor({ history: hist('MISMATCH') })
    await user.click(screen.getByRole('button', { name: 'ปรับข้อมูลทะเบียนให้ตรงกับประวัติ' }))
    const dialog = screen.getByRole('alertdialog')
    await user.click(within(dialog).getByLabelText(/ยอมรับค่าปัจจุบัน/))
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'ค่าในทะเบียนรถถูกต้อง')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการปรับข้อมูล' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).not.toHaveProperty('related_request_id')
    expect(sent[0].body.mode).toBe('ACCEPT_MASTER')
  })

  it('CONFLICT shows its own banner and offers no resend', async () => {
    store.add('u1', {
      request_id: 'r-c', operation: 'registration', vehicle_id: VID, body: {}, submitted_at: new Date().toISOString(),
      state: 'CONFLICT', page_instance: 'p', route_epoch: 0, prior_uncertain: true,
    })
    renderEditor()
    expect(screen.getByText('รหัสคำขอนี้ถูกใช้กับข้อมูลอื่นแล้ว — ต้องตรวจสอบกับผู้ดูแลระบบ')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).toBeNull()
  })

  it('memory-only storage is disclosed on the banner', async () => {
    const memoryStore = new PendingStore(() => {
      throw new Error('blocked')
    })
    memoryStore.add('u1', {
      request_id: 'r-m', operation: 'registration', vehicle_id: VID, body: {}, submitted_at: new Date().toISOString(),
      state: 'UNKNOWN', page_instance: 'p', route_epoch: 0, prior_uncertain: true,
    })
    renderEditor({ store: memoryStore })
    expect(screen.getByText('คำเตือนนี้จะหายเมื่อออกจากหน้า')).toBeInTheDocument()
  })
})

describe('late responses (W-13)', () => {
  it('a response after the view is gone updates the store only', async () => {
    let release!: (r: Response) => void
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      requests.push(new Headers(init.headers).get('X-Request-Id') ?? '')
      return new Promise<Response>((resolve) => {
        release = resolve
      })
    }))
    const user = userEvent.setup()
    const view = renderEditor()
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    await waitFor(() => expect(requests).toHaveLength(1))
    view.unmount()
    const errors = vi.spyOn(console, 'error')
    await act(async () => {
      release(new Response(JSON.stringify({ request_id: requests[0], changed: false, warnings: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': requests[0] },
      }))
    })
    await waitFor(() => expect(store.list('u1', VID)).toEqual([]))
    expect(errors).not.toHaveBeenCalled()
    expect(onRefresh).not.toHaveBeenCalled()
    errors.mockRestore()
  })
})
