import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { JobWorkTimeResponse, WorkTimeEntry } from '../lib/types'
import { WorkTimePanel } from './WorkTimePanel'

// R5 WorkTimePanel / WorkTimeEntryDialog — synthetic data only.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function entry(over: Partial<WorkTimeEntry> = {}): WorkTimeEntry {
  return {
    entry_id: 'WTE-1', revision: 1, record_kind: 'ENTRY', work_kind: 'REPAIR', job_id: 'RPR-1', technician_id: 'TEC-B',
    started_at: '2026-11-02T01:00:00Z', ended_at: '2026-11-02T09:00:00Z', time_class: 'REGULAR', description: 'ถอดปั๊ม',
    breaks: [], recorded_by: 'USR-B', recorded_at: '2026-11-02T10:00:00Z', reason: null, request_id: 'r', request_fingerprint: 'f',
    member_set_id: 'S', is_test_data: 'TRUE', test_batch_id: 'B', ...over,
  }
}

function view(entries: { entry: WorkTimeEntry; confirmed: boolean; revisions?: WorkTimeEntry[] }[], over: Partial<JobWorkTimeResponse> = {}): JobWorkTimeResponse {
  return {
    work_kind: 'REPAIR', job_id: 'RPR-1', status: 'OPEN',
    entries: entries.map((e) => ({ entry: e.entry, confirmed: e.confirmed, revisions: e.revisions ?? [e.entry] })),
    confirmations: [],
    technicians: { 'TEC-B': { regular_seconds: 16 * 3600, overtime_seconds: 5 * 3600, total_seconds: 21 * 3600, workdays: ['2026-11-02', '2026-11-03'] } },
    team: { regular_seconds: 16 * 3600, overtime_seconds: 5 * 3600, total_seconds: 21 * 3600, technician_count: 1 },
    elapsed_seconds: 15 * 86400,
    unconfirmed_count: entries.filter((e) => !e.confirmed).length,
    ...over,
  }
}

function install(body: JobWorkTimeResponse, userId = 'USR-MGR', post?: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, init })
      if (url.endsWith('/me')) return json({ user_id: userId, roles: ['SYN'], capabilities: [], is_dev_auth: true })
      if (init?.method === 'POST' && post) return post(url, init)
      if (url.endsWith('/work-time')) return json(body)
      throw new Error(`unexpected ${url}`)
    }),
  )
  return calls
}

function renderPanel(props: Partial<Parameters<typeof WorkTimePanel>[0]> = {}) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter>
        <WorkTimePanel kind="REPAIR" jobId="RPR-1" jobStatus="OPEN" canConfirm {...props} />
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('WorkTimePanel', () => {
  it('shows actual man-hours and the Work Order elapsed time separately (EX-3), never as 2.625 days', async () => {
    install(view([{ entry: entry(), confirmed: true }]))
    renderPanel()
    expect(await screen.findByTestId('wt-team-total')).toHaveTextContent('21 ชม. (ปกติ 16 ชม. / ล่วงเวลา 5 ชม.)')
    expect(screen.getByTestId('wt-elapsed')).toHaveTextContent('15 วัน 0 ชม. 0 นาที')
    expect(screen.getByTestId('wt-technicians')).toHaveTextContent('2 วัน')
    expect(document.body.textContent).not.toContain('2.625')
  })

  it('labels overtime as overtime and shows explicit "no break"', async () => {
    install(view([{ entry: entry({ time_class: 'OVERTIME' }), confirmed: false }]))
    renderPanel()
    expect(await screen.findByTestId('wt-entry-class')).toHaveTextContent('ล่วงเวลา (OT)')
    expect(screen.getByTestId('wt-entry')).toHaveTextContent('ไม่มีพัก')
    expect(screen.getByTestId('wt-unconfirmed')).toHaveTextContent('ต้องยืนยันทุกรายการก่อนปิดงาน')
  })

  it('offers confirmation only with the capability and never for the viewer\'s own entry', async () => {
    install(view([{ entry: entry(), confirmed: false }]), 'USR-B')
    const { unmount } = renderPanel()
    await screen.findByTestId('wt-entry')
    await waitFor(() => expect(screen.queryByRole('button', { name: 'ยืนยันเวลานี้' })).toBeNull())
    unmount()
    install(view([{ entry: entry(), confirmed: false }]), 'USR-MGR')
    renderPanel({ canConfirm: false })
    await screen.findByTestId('wt-entry')
    expect(screen.queryByRole('button', { name: 'ยืนยันเวลานี้' })).toBeNull()
  })

  it('AMB-2: a manager who corrected another technician\'s entry may still confirm it', async () => {
    const original = entry()
    const corrected = entry({ revision: 2, record_kind: 'CORRECTION', recorded_by: 'USR-MGR', reason: 'แก้เวลา' })
    install(view([{ entry: corrected, confirmed: false, revisions: [original, corrected] }]), 'USR-MGR')
    renderPanel()
    expect(await screen.findByRole('button', { name: 'ยืนยันเวลานี้' })).toBeInTheDocument()
    expect(screen.getByText(/ประวัติการแก้ไข \(2 ฉบับ\)/)).toBeInTheDocument()
  })

  it('confirms the exact current revision with a request id', async () => {
    const calls = install(view([{ entry: entry({ revision: 3, record_kind: 'CORRECTION' }), confirmed: false }]), 'USR-MGR', () =>
      json(view([{ entry: entry({ revision: 3, record_kind: 'CORRECTION' }), confirmed: true }])),
    )
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'ยืนยันเวลานี้' }))
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.init?.method === 'POST')!
    expect(post.url).toContain('/repairs/RPR-1/work-time/confirmations')
    expect(JSON.parse(String(post.init!.body))).toEqual({ entries: [{ entry_id: 'WTE-1', revision: 3 }] })
    expect(new Headers(post.init!.headers).get('X-Request-Id')).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('a transport failure is UNKNOWN (never success) and the resend reuses the same request id', async () => {
    const ids: string[] = []
    let attempt = 0
    install(view([{ entry: entry(), confirmed: false }]), 'USR-MGR', (_url, init) => {
      ids.push(new Headers(init.headers).get('X-Request-Id') ?? '')
      attempt += 1
      if (attempt === 1) throw new TypeError('network down')
      return json(view([{ entry: entry(), confirmed: true }]))
    })
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'ยืนยันเวลานี้' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ไม่ทราบผลการบันทึก')
    await user.click(screen.getByRole('button', { name: 'ยืนยันเวลานี้' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'ยืนยันเวลานี้' })).toBeNull())
    expect(ids).toHaveLength(2)
    expect(ids[1]).toBe(ids[0])
  })

  it('shows the server code in Thai, e.g. the cross-Work-Order overlap refusal', async () => {
    install(view([]), 'USR-B', () =>
      json({ error: { code: 'WORK_TIME_OVERLAP', message: 'x', details: { job_id: 'PMW-1' }, request_id: 'r' } }, 409),
    )
    const user = userEvent.setup()
    renderPanel({ canConfirm: false })
    await user.click(await screen.findByRole('button', { name: 'บันทึกเวลาทำงานของฉัน' }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('เริ่มทำงาน'), '2026-11-02T08:00')
    await user.type(within(dialog).getByLabelText('สิ้นสุด'), '2026-11-02T12:00')
    await user.type(within(dialog).getByLabelText('รายละเอียดงานที่ทำ'), 'งาน')
    await user.click(within(dialog).getByLabelText('ไม่มีพัก'))
    await user.click(within(dialog).getByRole('button', { name: 'บันทึก' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('มีเวลาทำงานที่บันทึกไว้ในช่วงเวลาเดียวกันแล้ว')
  })

  it('does not offer recording when the work order is closed, and explains post-close corrections', async () => {
    install(view([{ entry: entry(), confirmed: false }], { status: 'CLOSED' }))
    renderPanel({ jobStatus: 'CLOSED' })
    expect(await screen.findByTestId('wt-unconfirmed')).toHaveTextContent('แก้ไขหลังปิดงาน — ใบงานยังคงปิดอยู่')
    expect(screen.queryByRole('button', { name: 'บันทึกเวลาทำงานของฉัน' })).toBeNull()
  })

  it('PM: recording is offered only while IN_PROGRESS or PENDING_REVIEW', async () => {
    install(view([], { work_kind: 'PM' }))
    const { unmount } = renderPanel({ kind: 'PM', jobId: 'PMW-1', jobStatus: 'OPEN' })
    await screen.findByTestId('wt-team-total')
    expect(screen.queryByRole('button', { name: 'บันทึกเวลาทำงานของฉัน' })).toBeNull()
    unmount()
    renderPanel({ kind: 'PM', jobId: 'PMW-1', jobStatus: 'IN_PROGRESS' })
    expect(await screen.findByRole('button', { name: 'บันทึกเวลาทำงานของฉัน' })).toBeInTheDocument()
  })

  it('an unexpected response body fails closed instead of rendering a partial state', async () => {
    install({ unexpected: true } as unknown as JobWorkTimeResponse)
    renderPanel()
    expect(await screen.findByText('ข้อมูลเวลาทำงานที่ได้รับไม่ถูกต้อง จึงไม่แสดงผล')).toBeInTheDocument()
    expect(screen.queryByTestId('wt-team-total')).toBeNull()
  })
})

describe('WorkTimeEntryDialog (via the panel)', () => {
  async function openDialog() {
    const posts: unknown[] = []
    install(view([]), 'USR-B', (_url, init) => {
      posts.push(JSON.parse(String(init.body)))
      return json(view([{ entry: entry(), confirmed: false }]))
    })
    const user = userEvent.setup()
    renderPanel({ canConfirm: false })
    await user.click(await screen.findByRole('button', { name: 'บันทึกเวลาทำงานของฉัน' }))
    return { user, dialog: screen.getByRole('dialog'), posts }
  }

  it('requires an explicit break choice (no default) and sends [] for "no break"', async () => {
    const { user, dialog, posts } = await openDialog()
    await user.type(within(dialog).getByLabelText('เริ่มทำงาน'), '2026-11-02T08:00')
    await user.type(within(dialog).getByLabelText('สิ้นสุด'), '2026-11-02T17:00')
    await user.type(within(dialog).getByLabelText('รายละเอียดงานที่ทำ'), 'งานซ่อม')
    expect(within(dialog).getByLabelText('ไม่มีพัก')).not.toBeChecked()
    expect(within(dialog).getByLabelText('มีพัก')).not.toBeChecked()
    await user.click(within(dialog).getByRole('button', { name: 'บันทึก' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('กรุณาเลือกว่ามีช่วงพักหรือไม่')
    expect(posts).toHaveLength(0)
    await user.click(within(dialog).getByLabelText('ไม่มีพัก'))
    await user.click(within(dialog).getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toEqual({
      started_at: '2026-11-02T08:00:00+07:00', ended_at: '2026-11-02T17:00:00+07:00', time_class: 'REGULAR',
      description: 'งานซ่อม', breaks: [],
    })
  })

  it('sends explicit break periods and overtime, and flags work across midnight', async () => {
    const { user, dialog, posts } = await openDialog()
    await user.type(within(dialog).getByLabelText('เริ่มทำงาน'), '2026-11-02T20:00')
    await user.type(within(dialog).getByLabelText('สิ้นสุด'), '2026-11-03T02:00')
    expect(within(dialog).getByTestId('wt-crosses-midnight')).toBeInTheDocument()
    await user.selectOptions(within(dialog).getByLabelText('ประเภทเวลา'), 'OVERTIME')
    await user.type(within(dialog).getByLabelText('รายละเอียดงานที่ทำ'), 'งานกลางคืน')
    await user.click(within(dialog).getByLabelText('มีพัก'))
    await user.type(within(dialog).getByLabelText('พักครั้งที่ 1 เริ่ม'), '2026-11-02T23:00')
    await user.type(within(dialog).getByLabelText('พักครั้งที่ 1 สิ้นสุด'), '2026-11-02T23:30')
    await user.click(within(dialog).getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({
      time_class: 'OVERTIME',
      breaks: [{ started_at: '2026-11-02T23:00:00+07:00', ended_at: '2026-11-02T23:30:00+07:00' }],
    })
  })

  it('a correction requires a reason and sends the expected revision', async () => {
    const posts: { url: string; body: unknown }[] = []
    install(view([{ entry: entry({ revision: 2, record_kind: 'CORRECTION' }), confirmed: false }]), 'USR-MGR', (url, init) => {
      posts.push({ url, body: JSON.parse(String(init.body)) })
      return json(view([{ entry: entry({ revision: 3, record_kind: 'CORRECTION' }), confirmed: false }]))
    })
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'แก้ไข' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'บันทึก' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('การแก้ไขต้องระบุเหตุผล')
    await user.type(within(dialog).getByLabelText('เหตุผลการแก้ไข'), 'ผู้จัดการตรวจพบเวลาเกิน')
    await user.click(within(dialog).getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain('/work-time/WTE-1/revisions')
    expect(posts[0].body).toMatchObject({ action: 'CORRECT', expected_revision: 2, reason: 'ผู้จัดการตรวจพบเวลาเกิน' })
  })
})
