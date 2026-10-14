import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { TechnicianAssignments } from '../lib/technicianV2'
import { TechnicianAssignmentV2Panel } from './TechnicianAssignmentV2Panel'

/**
 * R2 Batch R2f-h4 B6 — the whole-assignment withdrawal control (owner D2) and the
 * CLOSED refusal (owner D1) on the V2 panel. Every response is a synthetic stub.
 */

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const SET = {
  assignment_set_id: 'SET-SYN-1',
  assigned_at: '2026-01-02T08:00:00Z',
  assigned_by_user_id: 'SYN-MGR',
  primary_technician_id: 'TEC-SYN-1',
  collaborator_technician_ids: ['TEC-SYN-2'],
  reason_th: null,
  record_ids: ['R1', 'R2'],
}
const VALID: TechnicianAssignments = { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'VALID', current: SET, sets: [SET], withdrawals: [] }
const WITHDRAWN: TechnicianAssignments = {
  ...VALID,
  status: 'NONE',
  current: null,
  withdrawals: [{ withdrawal_id: 'W-SYN-1', withdrawn_at: '2026-01-03T08:00:00Z', withdrawn_by_user_id: 'SYN-MGR', reason_th: 'ยกเลิกงาน', record_ids: ['W'] }],
}
const TECHS = {
  items: [
    { technician_id: 'TEC-SYN-1', first_name: 'ช่าง', last_name: 'หนึ่ง', active_status: 'ACTIVE' },
    { technician_id: 'TEC-SYN-2', first_name: 'ช่าง', last_name: 'สอง', active_status: 'ACTIVE' },
  ],
  page: 1,
  page_size: 200,
  total_items: 2,
}

interface Call {
  url: string
  method: string
  body: unknown
  requestId: string | undefined
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function setup({
  kind = 'REPAIR',
  jobStatus = 'OPEN',
  capabilities = ['can_view', 'can_manage_repair', 'can_manage_pm'],
  reads = [VALID],
  write = () => jsonResponse({ request_id: 'x', changed: true, withdrawn: true, record_ids: ['W'] }),
}: {
  kind?: 'REPAIR' | 'PM'
  jobStatus?: string
  capabilities?: string[]
  reads?: TechnicianAssignments[]
  write?: () => Response | Promise<Response>
} = {}) {
  const calls: Call[] = []
  const base = kind === 'REPAIR' ? '/api/v1/repairs/RPR-SYN-1' : '/api/v1/pm/work-orders/RPR-SYN-1'
  let readIndex = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const headers = (init?.headers ?? {}) as Record<string, string>
      calls.push({ url: input, method, body: init?.body ? JSON.parse(String(init.body)) : undefined, requestId: headers['X-Request-Id'] })
      if (input === '/api/v1/me') {
        return jsonResponse({ user_id: 'SYN-MGR', roles: [], capabilities, data_context: 'TEST' })
      }
      if (input === `${base}/technician-assignments` && method === 'GET') {
        const data = reads[Math.min(readIndex, reads.length - 1)]
        readIndex += 1
        return jsonResponse(data)
      }
      if (input.startsWith('/api/v1/technicians?')) return jsonResponse(TECHS)
      if (method === 'POST') return write()
      throw new Error(`unexpected ${method} ${input}`)
    }),
  )
  const onChanged = vi.fn()
  render(
    <MemoryRouter>
      <CapabilitiesProvider>
        <TechnicianAssignmentV2Panel kind={kind} jobId="RPR-SYN-1" jobStatus={jobStatus} onChanged={onChanged} />
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
  return { calls, base, onChanged, posts: () => calls.filter((c) => c.method === 'POST') }
}

const WITHDRAW = 'ถอนการมอบหมายช่างทั้งหมด'

describe('R2f-h4 B6 — withdraw the whole assignment (D2)', () => {
  it.each(['REPAIR', 'PM'] as const)('%s: confirm → one POST to the withdrawal route with the exact expected_current → NONE + history → picker for reassignment', async (kind) => {
    const user = userEvent.setup()
    const { base, posts, onChanged } = setup({ kind, reads: [VALID, WITHDRAWN] })
    await user.click(await screen.findByRole('button', { name: WITHDRAW }))
    expect(posts()).toHaveLength(0) // nothing is sent before the confirmation
    const dialog = screen.getByTestId('v2-withdraw-dialog')
    expect(dialog).toHaveTextContent('TEC-SYN-1')
    expect(dialog).toHaveTextContent('TEC-SYN-2')
    await user.type(screen.getByLabelText('เหตุผล (ถ้ามี)', { selector: `#v2-withdraw-reason-${kind}-RPR-SYN-1` }), 'ยกเลิกงาน')
    await user.click(screen.getByTestId('v2-withdraw-confirm'))
    expect(await screen.findByTestId('v2-assignment-message-success')).toHaveTextContent('ถอนการมอบหมายช่างทั้งหมดเรียบร้อยแล้ว')
    expect(posts()).toHaveLength(1)
    expect(posts()[0].url).toBe(`${base}/technician-assignment-withdrawals`)
    expect(posts()[0].body).toEqual({
      expected_current: { primary_technician_id: 'TEC-SYN-1', collaborator_technician_ids: ['TEC-SYN-2'] },
      reason_th: 'ยกเลิกงาน',
    })
    expect(posts()[0].requestId).toBeTruthy()
    expect(onChanged).toHaveBeenCalled()
    // Reloaded through the normal read: no current set, the withdrawal kept in history, the old set kept too.
    expect(await screen.findByText('ยังไม่ได้มอบหมายช่าง')).toBeInTheDocument()
    expect(screen.getByTestId('v2-withdrawal-history')).toHaveTextContent('SYN-MGR')
    expect(screen.getByTestId('v2-withdrawal-history')).toHaveTextContent('ยกเลิกงาน')
    expect(screen.getByTestId('v2-assignment-history')).toHaveTextContent('TEC-SYN-1')
    expect(screen.queryByRole('button', { name: WITHDRAW })).toBeNull() // nothing left to withdraw
    expect(screen.getByRole('heading', { name: 'มอบหมายช่าง' })).toBeInTheDocument() // reassignment via the picker
    expect(screen.getByLabelText(/ช่างหลัก \(PRIMARY\)/)).toHaveValue('')
  })

  it('cancel sends nothing', async () => {
    const user = userEvent.setup()
    const { posts } = setup()
    await user.click(await screen.findByRole('button', { name: WITHDRAW }))
    await user.click(screen.getByRole('button', { name: 'ยกเลิก' }))
    expect(screen.queryByTestId('v2-withdraw-dialog')).toBeNull()
    expect(posts()).toHaveLength(0)
  })

  it('the confirm button cannot double-submit', async () => {
    const user = userEvent.setup()
    let release: (r: Response) => void = () => {}
    const { posts } = setup({ write: () => new Promise<Response>((resolve) => (release = resolve)) })
    await user.click(await screen.findByRole('button', { name: WITHDRAW }))
    const confirm = screen.getByTestId('v2-withdraw-confirm')
    await user.click(confirm)
    await waitFor(() => expect(confirm).toBeDisabled())
    await user.click(confirm)
    expect(posts()).toHaveLength(1)
    release(jsonResponse({ request_id: 'x', changed: true, withdrawn: true, record_ids: ['W'] }))
    expect(await screen.findByTestId('v2-assignment-message-success')).toBeInTheDocument()
  })

  it.each([
    ['no manage capability', { capabilities: ['can_view'] }],
    ['a CLOSED job', { jobStatus: 'CLOSED' }],
    ['an unknown job status', { jobStatus: 'open' }],
    ['no current set', { reads: [{ ...VALID, status: 'NONE' as const, current: null, sets: [] }] }],
    ['an AMBIGUOUS current set', { reads: [{ ...VALID, status: 'AMBIGUOUS' as const, current: null }] }],
  ])('not offered with %s', async (_name, options) => {
    setup(options)
    expect(await screen.findByTestId('v2-current-set')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('กำลังโหลดข้อมูลการมอบหมายช่าง...')).toBeNull())
    expect(screen.queryByRole('button', { name: WITHDRAW })).toBeNull()
  })

  it('not offered while a pending intent exists (resend goes to the withdrawal route with the same id)', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem(
      'crane.technicianAssignmentPending.v1:SYN-MGR:REPAIR:RPR-SYN-1',
      JSON.stringify({
        operation: 'withdraw',
        requestId: 'REQ-SYN-PENDING',
        body: { expected_current: { primary_technician_id: 'TEC-SYN-1', collaborator_technician_ids: ['TEC-SYN-2'] } },
        createdAt: 'now',
      }),
    )
    const { base, posts } = setup({ write: () => jsonResponse({ request_id: 'REQ-SYN-PENDING', replayed: true, record_ids: ['W'] }), reads: [VALID, WITHDRAWN] })
    expect(await screen.findByTestId('v2-assignment-pending')).toHaveTextContent('มีคำขอถอนการมอบหมายช่างที่ยังไม่ทราบผล')
    expect(screen.queryByRole('button', { name: WITHDRAW })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    expect(await screen.findByTestId('v2-assignment-message-success')).toHaveTextContent('ถอนการมอบหมายช่างทั้งหมดเรียบร้อยแล้ว')
    expect(posts()[0].url).toBe(`${base}/technician-assignment-withdrawals`)
    expect(posts()[0].requestId).toBe('REQ-SYN-PENDING')
  })

  it('a stale withdrawal is never success: reload offered, the control disabled', async () => {
    const user = userEvent.setup()
    setup({ write: () => jsonResponse({ error: { code: 'TECHNICIAN_ASSIGNMENT_STALE', message: 'x', details: {} } }, 409) })
    await user.click(await screen.findByRole('button', { name: WITHDRAW }))
    await user.click(screen.getByTestId('v2-withdraw-confirm'))
    expect(await screen.findByTestId('v2-assignment-message-stale')).toBeInTheDocument()
    expect(screen.queryByTestId('v2-assignment-message-success')).toBeNull()
    expect(screen.getByRole('button', { name: WITHDRAW })).toBeDisabled()
  })

  it('JOB_CLOSED (closed meanwhile) shows the Thai message, the code and the request id; nothing pending', async () => {
    const user = userEvent.setup()
    setup({
      write: () =>
        new Response(JSON.stringify({ error: { code: 'TECHNICIAN_ASSIGNMENT_JOB_CLOSED', message: 'x', details: { status: 'CLOSED' } } }), {
          status: 409,
          headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'REQ-SYN-CLOSED' },
        }),
    })
    await user.click(await screen.findByRole('button', { name: WITHDRAW }))
    await user.click(screen.getByTestId('v2-withdraw-confirm'))
    const error = await screen.findByTestId('v2-assignment-message-error')
    expect(error).toHaveTextContent('งานนี้ปิดแล้ว')
    expect(error).toHaveTextContent('TECHNICIAN_ASSIGNMENT_JOB_CLOSED')
    expect(error).toHaveTextContent('REQ-SYN-CLOSED')
    expect(screen.queryByTestId('v2-assignment-pending')).toBeNull()
  })

  it('a transport failure is UNKNOWN (never success) and keeps the withdraw intent for an explicit resend', async () => {
    const user = userEvent.setup()
    setup({ write: () => Promise.reject(new TypeError('network down')) })
    await user.click(await screen.findByRole('button', { name: WITHDRAW }))
    await user.click(screen.getByTestId('v2-withdraw-confirm'))
    expect(await screen.findByTestId('v2-assignment-message-unknown')).toBeInTheDocument()
    expect(screen.queryByTestId('v2-assignment-message-success')).toBeNull()
    expect(await screen.findByTestId('v2-assignment-pending')).toHaveTextContent('มีคำขอถอนการมอบหมายช่างที่ยังไม่ทราบผล')
  })
})
