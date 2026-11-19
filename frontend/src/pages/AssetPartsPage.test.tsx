import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AssetPartsPage } from './AssetPartsPage'

// PG-5 P-A: the parts controls follow useTestGrantControlVisible (tested in MasterRecordForm.test.tsx);
// here it is controlled directly (true = legacy development mode / a grant holder in Access Management).
const visibility = vi.hoisted(() => ({ value: true }))
vi.mock('../lib/masterRecords', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/masterRecords')>()),
  useTestGrantControlVisible: () => visibility.value,
}))


function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/parts']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/parts" element={<AssetPartsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssetPartsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows an empty state and never displays an UNKNOWN prior-usage value as 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse([
          {
            position_lifetime_id: 'POSLT-0001',
            asset_type: 'VEHICLE',
            asset_id: 'VEH-1046',
            position_code: 'BOOM-CYL-1',
            part_id: 'PART-0004',
            lifetime_rule_id: null,
            baseline_meter_snapshot_id: null,
            prior_usage: { quality: 'UNKNOWN', value: null, note: null },
            started_at: '2026-02-01T00:00:00Z',
            started_by: 'dev-user',
            note: null,
          },
        ]),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ตำแหน่ง: BOOM-CYL-1')).toBeInTheDocument())
    expect(screen.getAllByText('ไม่ทราบค่า').length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('creates a new position-lifetime enrollment', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({
          method,
          url,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        })
        if (method === 'GET') return jsonResponse([])
        if (method === 'POST' && url.includes('/position-lifetime')) {
          return jsonResponse({
            position_lifetime_id: 'POSLT-0002',
            asset_type: 'VEHICLE',
            asset_id: 'VEH-1046',
            position_code: 'BOOM-CYL-2',
            part_id: null,
            lifetime_rule_id: null,
            baseline_meter_snapshot_id: null,
            prior_usage: { quality: 'UNKNOWN', value: null, note: null },
            started_at: '2026-02-01T00:00:00Z',
            started_by: 'dev-user',
            note: null,
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง')).toBeInTheDocument(),
    )
    await user.click(screen.getByText('+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง'))
    await user.type(screen.getByLabelText('ตำแหน่ง (position code)'), 'BOOM-CYL-2')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/position-lifetime'))).toBe(
        true,
      ),
    )
    const createCall = calls.find((c) => c.method === 'POST' && c.url.includes('/position-lifetime'))
    expect(createCall?.body).toMatchObject({
      asset_type: 'VEHICLE',
      asset_id: 'VEH-1046',
      position_code: 'BOOM-CYL-2',
    })
  })

  it('R6: lists installed instances with nested hosted seals from the single summary endpoint', async () => {
    const q = (value: number | null) => ({ value, quality: value === null ? 'UNKNOWN' : 'KNOWN', policy_state: null,
      reasons: value === null ? ['METER_EVIDENCE_MISSING'] : [] })
    const counters = (value: number | null) => [{ basis: { counter_type: 'ENGINE_HOUR', component_role: 'CARRIER_ENGINE' },
      verified_lifetime_total: q(value), verified_current_cycle: q(value), tracked_since_enrollment: q(value),
      tracked_in_current_cycle: q(value) }]
    const view = (id: string, extra: object) => ({ target_type: 'PART_INSTANCE', target_id: id, part_id: 'PART-0005',
      status: 'INSTALLED', policy_context: 'TEST', evaluated_at: '2026-11-10T00:00:00Z',
      host: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', position_code: 'BOOM-1', model_id: 'MODEL-0001', installed: true },
      lifecycle: { lifecycle_id: 'L', cycle_number: 1, start_reason: 'ENROLLMENT', start_trigger_event_id: null },
      approval: null, declarations: { prior_usage: null, prior_cycle_usage: null }, counters: counters(null),
      rules: [], inactive_rules: [], ...extra })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/part-lifetime')) {
        return jsonResponse({ asset_type: 'VEHICLE', asset_id: 'VEH-1046', policy_context: 'TEST', positions: [],
          instances: [view('PINST-0007', { hosted_positions: [view('POSLT-0009', {
            target_type: 'POSITION_LIFETIME', part_id: 'PART-0004',
            host: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', position_code: 'ROD-SEAL', model_id: 'MODEL-0001',
              installed: true, host_part_instance_id: 'PINST-0007' }, counters: counters(80) })] })] })
      }
      return jsonResponse([])
    }))
    renderPage()
    await waitFor(() => expect(screen.getByTestId('installed-instance')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'PINST-0007' })).toBeInTheDocument()
    expect(screen.getByTestId('hosted-position')).toHaveTextContent('ROD-SEAL')
    expect(screen.getByTestId('hosted-position')).toHaveTextContent('80')
    // The instance itself has no verified reading: shown as unknown, never 0.
    expect(screen.getAllByTestId('asset-status-summary')[0]).toHaveTextContent('ไม่ทราบ')
  })

  it('R6: a summary load failure is shown as such, not as "nothing installed"', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/part-lifetime')
      ? jsonResponse({ error: { code: 'VEHICLE_NOT_FOUND', message: 'x' } }, 404)
      : jsonResponse([])))
    renderPage()
    await waitFor(() => expect(screen.getByText(/โหลดสถานะชิ้นงานที่ติดตั้งไม่สำเร็จ/)).toBeInTheDocument())
    expect(screen.queryByText('ไม่มีชิ้นงานรายชิ้นติดตั้งอยู่บนสินทรัพย์นี้')).not.toBeInTheDocument()
  })
})

// R8 PRE-UAT (workstream F): position maintenance events (inspect / repair in place, no reset).
// The backend requires one INSPECT / REPAIR rule (or condition group) of the position's part.
describe('AssetPartsPage — R8 PRE-UAT position maintenance', () => {
  afterEach(() => vi.unstubAllGlobals())

  const record = { position_lifetime_id: 'POSLT-0001', asset_type: 'VEHICLE', asset_id: 'VEH-1046',
    position_code: 'BOOM-CYL-1', part_id: 'PART-0004', lifetime_rule_id: null, baseline_meter_snapshot_id: null,
    prior_usage: { quality: 'UNKNOWN', value: null, note: null }, started_at: '2026-02-01T00:00:00Z',
    started_by: 'dev-user', note: null }

  function stub(rules: unknown[], posts: { url: string; body: unknown; requestId: string | null }[]) {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input)
      if (init.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)), requestId: new Headers(init.headers).get('X-Request-Id') })
        return jsonResponse({ event_id: 'E' })
      }
      if (url.includes('/lifetime-rules?part_id=PART-0004')) return jsonResponse(rules)
      return jsonResponse([record])
    }))
  }

  it('records an inspection against the chosen INSPECT rule and an in-place repair against a REPAIR group', async () => {
    const posts: { url: string; body: unknown; requestId: string | null }[] = []
    stub([{ lifetime_rule_id: 'LTR-I', part_id: 'PART-0004', due_action: 'INSPECT', condition_group_key: null, note: 'ตรวจทุก 250 ชม.' },
      { lifetime_rule_id: 'LTR-R1', part_id: 'PART-0004', due_action: 'REPAIR', condition_group_key: 'GRP-1', note: null },
      { lifetime_rule_id: 'LTR-R2', part_id: 'PART-0004', due_action: 'REPAIR', condition_group_key: 'GRP-1', note: null },
      { lifetime_rule_id: 'LTR-X', part_id: 'PART-0004', due_action: 'REPLACE', condition_group_key: null, note: null }], posts)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'ตรวจที่ตำแหน่งนี้ (ไม่รีเซ็ตอายุ)' }))
    const select = await screen.findByLabelText('การตรวจตามกฎ')
    await screen.findByRole('option', { name: 'LTR-I — ตรวจทุก 250 ชม.' })
    expect(screen.queryByRole('option', { name: /LTR-X/ })).not.toBeInTheDocument() // REPLACE is never a maintenance target
    expect(screen.getByRole('button', { name: 'ยืนยันการตรวจ/ซ่อม' })).toBeDisabled()
    await userEvent.selectOptions(select, 'rule:LTR-I')
    await userEvent.click(screen.getByRole('button', { name: 'ยืนยันการตรวจ/ซ่อม' }))
    expect(await screen.findByText('บันทึกการตรวจแล้ว')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'ซ่อมในที่ที่ตำแหน่งนี้ (ไม่รีเซ็ตอายุ)' }))
    await screen.findByRole('option', { name: 'กลุ่มเงื่อนไข GRP-1' })
    expect(screen.getAllByRole('option', { name: 'กลุ่มเงื่อนไข GRP-1' })).toHaveLength(1)
    await userEvent.selectOptions(screen.getByLabelText('การซ่อมในที่ตามกฎ'), 'group:GRP-1')
    await userEvent.click(screen.getByRole('button', { name: 'ยืนยันการตรวจ/ซ่อม' }))
    expect(await screen.findByText('บันทึกการซ่อมในที่แล้ว')).toBeInTheDocument()
    expect(posts.map((p) => [p.url.replace(/.*\/api\/v1/, ''), p.body])).toEqual([
      ['/position-lifetime/POSLT-0001/maintenance-events', { action: 'INSPECTED', lifetime_rule_id: 'LTR-I' }],
      ['/position-lifetime/POSLT-0001/maintenance-events', { action: 'REPAIRED_IN_PLACE', condition_group_key: 'GRP-1' }]])
    expect(posts[0].requestId).not.toBe(posts[1].requestId)
  })

  it('without an INSPECT rule nothing can be recorded and the user is told why', async () => {
    const posts: { url: string; body: unknown; requestId: string | null }[] = []
    stub([], posts)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'ตรวจที่ตำแหน่งนี้ (ไม่รีเซ็ตอายุ)' }))
    expect(await screen.findByText(/ยังไม่มีกฎการตรวจ \(INSPECT\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ยืนยันการตรวจ/ซ่อม' })).toBeDisabled()
    expect(posts).toHaveLength(0)
  })
})

describe('AssetPartsPage — PG-5 visibility', () => {
  afterEach(() => { visibility.value = true; vi.unstubAllGlobals() })

  it('hides the position maintenance controls without can_test_manage_parts in Access Management', async () => {
    visibility.value = false
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([{ position_lifetime_id: 'POSLT-0001', asset_type: 'VEHICLE',
      asset_id: 'VEH-1046', position_code: 'BOOM-CYL-1', part_id: 'PART-0004', lifetime_rule_id: null,
      baseline_meter_snapshot_id: null, prior_usage: { quality: 'UNKNOWN', value: null, note: null },
      started_at: '2026-02-01T00:00:00Z', started_by: 'dev-user', note: null }])))
    renderPage()
    await screen.findByText('ตำแหน่ง: BOOM-CYL-1')
    expect(screen.queryByRole('button', { name: 'ตรวจที่ตำแหน่งนี้ (ไม่รีเซ็ตอายุ)' })).not.toBeInTheDocument()
  })
})
