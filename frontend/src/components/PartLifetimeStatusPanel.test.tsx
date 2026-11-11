import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PartLifetimeStatusPanel } from './PartLifetimeStatusPanel'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const unknownQ = { value: null, quality: 'UNKNOWN', policy_state: null, reasons: ['METER_EVIDENCE_MISSING'] }

function status(over: Record<string, unknown> = {}) {
  return {
    target_type: 'PART_INSTANCE', target_id: 'PINST-0001', part_id: 'PART-0005', status: 'INSTALLED',
    policy_context: 'TEST', evaluated_at: '2026-11-10T00:00:00Z',
    host: { asset_type: 'VEHICLE', asset_id: 'VEH-1048', position_code: null, model_id: 'MODEL-0003', installed: true },
    lifecycle: { lifecycle_id: 'PLC-0002', cycle_number: 2, start_reason: 'OVERHAUL', start_trigger_event_id: 'PSE-1' },
    approval: { state: 'CONSUMED', return_event_id: 'PSE-1' },
    declarations: { prior_usage: { declared_value: 0, quality: 'KNOWN', basis: null, component_role: null,
      as_of: '2026-01-01', evidence_type: 'NEW_PART', evidence_reference: 'RPR-1', reference_status: 'RESOLVED',
      verification_level: 'VERIFIED', note: null }, prior_cycle_usage: null },
    counters: [{
      basis: { counter_type: 'ENGINE_HOUR', component_role: 'CARRIER_ENGINE' },
      verified_lifetime_total: { value: 8200, quality: 'KNOWN', policy_state: 'APPROVED', reasons: [] },
      verified_current_cycle: { value: 5000, quality: 'KNOWN', policy_state: 'TEST_PROPOSED', reasons: [] },
      tracked_since_enrollment: { value: 8200, quality: 'KNOWN', policy_state: null, reasons: [] },
      tracked_in_current_cycle: { value: 5000, quality: 'KNOWN', policy_state: null, reasons: [] },
    }],
    rules: [{ lifetime_rule_id: 'LTR-1', condition_group_key: null, due_action: 'REPLACE', trigger_type: 'ENGINE_HOUR',
      status: 'DUE', current_value: 5000, next_due_value: 5000, next_due_date: null, remaining: 0, reasons: [],
      policy_state: 'TEST_PROPOSED', due_key: 'k1', members: [] }],
    inactive_rules: [],
    ...over,
  }
}

describe('PartLifetimeStatusPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows verified and tracked rows from the API, with the due status and policy label', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(status())))
    render(<PartLifetimeStatusPanel path="/part-instances/PINST-0001/lifetime-status" />)
    await waitFor(() => expect(screen.getByTestId('counter-value-verified_lifetime_total')).toHaveTextContent('8,200'))
    expect(screen.getByTestId('counter-value-verified_current_cycle')).toHaveTextContent('5,000')
    expect(screen.getByText('ถึงกำหนด')).toBeInTheDocument()
    expect(screen.getAllByText(/ค่าทดสอบตามข้อเสนอ/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/ยืนยันแล้ว\)/).length).toBeGreaterThan(1)
    expect(screen.getByTestId('approval-state')).toHaveTextContent('ใช้แล้ว (เริ่มรอบใหม่แล้ว)')
  })

  it('never renders UNKNOWN as 0 and never moves a tracked number into a verified row', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(status({
      counters: [{
        basis: { counter_type: 'ENGINE_HOUR', component_role: 'CARRIER_ENGINE' },
        verified_lifetime_total: { ...unknownQ, reasons: ['PRIOR_USAGE_UNKNOWN'] },
        verified_current_cycle: { ...unknownQ, reasons: ['PRIOR_CYCLE_USAGE_UNKNOWN'] },
        tracked_since_enrollment: { value: 1000, quality: 'KNOWN', policy_state: null, reasons: [] },
        tracked_in_current_cycle: { value: 1000, quality: 'KNOWN', policy_state: null, reasons: [] },
      }],
    }))))
    render(<PartLifetimeStatusPanel path="/x" />)
    await waitFor(() => expect(screen.getByTestId('counter-value-verified_lifetime_total')).toHaveTextContent('ไม่ทราบ'))
    expect(screen.getByTestId('counter-value-verified_current_cycle')).toHaveTextContent('ไม่ทราบ')
    expect(screen.getByTestId('counter-value-tracked_since_enrollment')).toHaveTextContent('1,000')
    expect(screen.getByText(/ไม่ทราบการใช้งานก่อนเริ่มติดตาม/)).toBeInTheDocument()
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument()
  })

  it('shows the due status exactly as the API returns it (never computed in the browser)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(status({
      rules: [
        { lifetime_rule_id: 'LTR-1', condition_group_key: null, due_action: 'REPLACE', trigger_type: 'ENGINE_HOUR',
          status: 'UNKNOWN', current_value: null, next_due_value: null, next_due_date: null, remaining: null,
          reasons: ['PRIOR_CYCLE_USAGE_UNKNOWN'], policy_state: 'PENDING', due_key: 'k1', members: [] },
        { lifetime_rule_id: 'LTR-2', condition_group_key: null, due_action: 'INSPECT', trigger_type: 'ENGINE_HOUR',
          status: 'DUE', current_value: 400, next_due_value: 500, next_due_date: null, remaining: 100,
          reasons: [], policy_state: 'TEST_PROPOSED', due_key: 'k2', members: [] },
      ],
    }))))
    render(<PartLifetimeStatusPanel path="/x" />)
    await waitFor(() => expect(screen.getAllByTestId('due-rule')).toHaveLength(2))
    const [unknownRule, dueRule] = screen.getAllByTestId('due-rule')
    expect(unknownRule).toHaveTextContent('ไม่ทราบ')
    expect(unknownRule).not.toHaveTextContent('ยังไม่ถึงกำหนด')
    expect(dueRule).toHaveTextContent('ถึงกำหนด')
    expect(dueRule).not.toHaveTextContent('ยังไม่ถึงกำหนด')
  })

  it('shows a load failure as an error, never as "nothing tracked"', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: { code: 'PART_INSTANCE_NOT_FOUND', message: 'x' } },
      404)))
    render(<PartLifetimeStatusPanel path="/x" />)
    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลชิ้นงานนี้')).toBeInTheDocument())
    expect(screen.queryByTestId('part-lifetime-status')).not.toBeInTheDocument()
  })

  it('discards a stale response after the path changed', async () => {
    let releaseFirst: (r: Response) => void = () => {}
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('/first')) return new Promise<Response>((resolve) => { releaseFirst = resolve })
      return Promise.resolve(jsonResponse(status({ target_id: 'SECOND' })))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { rerender } = render(<PartLifetimeStatusPanel path="/first" />)
    rerender(<PartLifetimeStatusPanel path="/second" />)
    await waitFor(() => expect(screen.getByTestId('counter-value-verified_lifetime_total')).toHaveTextContent('8,200'))
    releaseFirst(jsonResponse(status({ counters: [] })))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.getByTestId('counter-value-verified_lifetime_total')).toHaveTextContent('8,200')
  })
})
