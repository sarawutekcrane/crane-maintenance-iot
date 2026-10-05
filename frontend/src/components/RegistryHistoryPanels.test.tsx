import { act, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReferenceLoad } from '../lib/referenceResolution'
import { RegistryHistoryPanels } from './RegistryHistoryPanels'

// Phase 7 Batch 7O2a — read-only history panels (contract Final Rev2 §5.4,
// §7.4, §10.2). Synthetic data only.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const BRANCHES: ReferenceLoad = {
  kind: 'ready',
  byCode: new Map([
    ['BR-SYN-A', { name: 'สาขาเอ', isActive: true }],
    ['BR-SYN-B', { name: 'สาขาบี', isActive: false }],
  ]),
}

function event(id: string, overrides: Record<string, unknown> = {}) {
  return {
    event_id: id, in_force: true, head_record_id: id, revision_no: 1, to_branch_id: 'BR-SYN-A',
    effective_at: '2026-08-31T17:00:00+00:00', effective_precision: 'DATE', derived_from_branch_id: 'BR-SYN-B',
    original_entry_from_branch_id: 'BR-SYN-B', original_entry_from_source: 'BASELINE',
    head_entry_from_branch_id: 'BR-SYN-B', head_entry_from_source: 'BASELINE', derived_end_at: null, notes: [],
    ...overrides,
  }
}

function record(id: string, kind = 'ASSIGNMENT', op = 'TRANSFER') {
  return {
    record_id: id, record_kind: kind, entry_operation: op, event_id: id, revision_no: 1, supersedes_record_id: null,
    branch_id: 'BR-SYN-A', effective_at: '2026-08-31T17:00:00+00:00', recorded_from_branch_id: 'BR-SYN-B',
    recorded_from_source: 'BASELINE', recorded_at: '2026-09-01T03:00:00+00:00', recorded_by: 'SYN-USER',
    request_id: `req-${id}`, related_request_id: null, reason_th: 'เหตุผลทดสอบ', reconciled_old_master_branch_id: null,
  }
}

function history(overrides: Record<string, unknown> = {}) {
  return {
    asset_type: 'VEHICLE', asset_id: 'SYN-V1', timeline_status: 'VALID',
    current: { branch_id: 'BR-SYN-A', source: 'EVENT' }, master: { state: 'RECORDED', value: 'BR-SYN-A' },
    consistency: 'CONSISTENT', history_revision: 'BHR1-x', baseline: { branch_id: 'BR-SYN-B', source: 'IMPORTED_MASTER' },
    events: [event('E1')], records: [record('E1')], excluded_test_rows: 0, issues: {}, ...overrides,
  }
}

const EMPTY_REGISTRATION = {
  vehicle_id: 'SYN-V1',
  current: { registration_no: { state: 'NOT_RECORDED', value: null }, registration_province: { state: 'NOT_RECORDED', value: null } },
  consistency: 'NO_HISTORY', history_revision: 'RHR1-x', items: [], excluded_test_rows: 0, issues: {},
}

function install(branch: () => Response | Promise<Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path.endsWith('/branch-history')) return branch()
      if (path.endsWith('/registration-history')) return json(EMPTY_REGISTRATION)
      throw new Error(`Unexpected fetch: ${path}`)
    }),
  )
}

describe('RegistryHistoryPanels', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the timeline with resolved names, notes, baseline and records', async () => {
    install(() =>
      json(history({
        events: [event('E1', { notes: ['RECORDED_SOURCE_DIFFERS'] }), event('E2', { in_force: false, notes: ['CANCELLED'] })],
        records: [record('E1'), record('E2'), record('C1', 'CANCELLATION', 'CANCELLATION')],
      })),
    )
    render(<RegistryHistoryPanels vehicleId="SYN-V1" branches={BRANCHES} provinces={{ kind: 'unavailable' }} />)
    const panel = await screen.findByTestId('branch-history-panel')
    expect(await within(panel).findByText('สาขาต้นทางที่บันทึกไว้ต่างจากที่คำนวณได้ตามลำดับปัจจุบัน')).toBeInTheDocument()
    expect(within(panel).getByText('ยกเลิกแล้ว')).toBeInTheDocument()
    // The inactive branch appears as the baseline and as the first event's derived source.
    expect(within(panel).getAllByText('สาขาบี (ไม่ใช้งาน)').length).toBeGreaterThanOrEqual(2)
    expect(within(panel).getByText('สาขาเดิมก่อนมีประวัติ')).toBeInTheDocument()
    expect(within(panel).getByText('รายการที่บันทึกทั้งหมด (3 รายการ)')).toBeInTheDocument()
    expect(within(panel).getByText('ยกเลิกการย้าย (ยกเลิก)')).toBeInTheDocument()
    expect(within(panel).getByText('req-E1')).toBeInTheDocument()
  })

  it('warns on same-instant ambiguity and shows the current branch as undetermined', async () => {
    install(() =>
      json(history({
        timeline_status: 'AMBIGUOUS_ORDER', current: { branch_id: null, source: 'UNDETERMINED' }, consistency: 'UNDETERMINED',
        events: [event('E1', { notes: ['SAME_INSTANT'], derived_from_branch_id: null })],
      })),
    )
    render(<RegistryHistoryPanels vehicleId="SYN-V1" branches={BRANCHES} provinces={BRANCHES} />)
    const panel = await screen.findByTestId('branch-history-panel')
    expect(await within(panel).findByText(/ระบุลำดับและสาขาปัจจุบันไม่ได้/)).toBeInTheDocument()
    expect(within(panel).getByText(/ยังระบุไม่ได้/)).toBeInTheDocument()
    expect(within(panel).getByText('ตรวจสอบความตรงกันไม่ได้')).toBeInTheDocument()
  })

  it('a slower response for a previous path never overwrites the current one', async () => {
    let releaseOld!: (r: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'http://localhost').pathname
        if (path.endsWith('/registration-history')) return json(EMPTY_REGISTRATION)
        if (path.includes('/SYN-OLD/')) return new Promise<Response>((res) => (releaseOld = res))
        return json(history({ records: [], events: [], consistency: 'NO_HISTORY', baseline: null }))
      }),
    )
    const { rerender } = render(<RegistryHistoryPanels vehicleId="SYN-OLD" branches={BRANCHES} provinces={BRANCHES} />)
    await screen.findByTestId('branch-history-panel')
    rerender(<RegistryHistoryPanels vehicleId="SYN-NEW" branches={BRANCHES} provinces={BRANCHES} />)
    // Panels are keyed by vehicle id: the new id gets a fresh panel.
    const panel = screen.getByTestId('branch-history-panel')
    expect(await within(panel).findByText('ยังไม่มีประวัติ')).toBeInTheDocument()
    await act(async () => releaseOld(json(history())))
    expect(within(panel).getByText('ยังไม่มีประวัติ')).toBeInTheDocument()
    expect(within(panel).queryByText('req-E1')).not.toBeInTheDocument()
  })

  it('unmount before the response arrives applies nothing', async () => {
    let release!: (r: Response) => void
    install(() => new Promise<Response>((res) => (release = res)))
    const { unmount } = render(<RegistryHistoryPanels vehicleId="SYN-V1" branches={BRANCHES} provinces={BRANCHES} />)
    await screen.findByTestId('branch-history-panel')
    unmount()
    const errors: unknown[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...args) => void errors.push(args))
    await act(async () => release(json(history())))
    expect(errors).toEqual([])
    spy.mockRestore()
  })
})

// 7O2a review fix: every nested element and finite vocabulary is validated; a
// malformed 200 body is the malformed-data error, never valid or empty history.
describe('RegistryHistoryPanels — malformed response shapes', () => {
  afterEach(() => vi.unstubAllGlobals())

  const MALFORMED = /รูปแบบไม่ถูกต้อง/

  function installBoth(branch: unknown, registration: unknown) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'http://localhost').pathname
        if (path.endsWith('/branch-history')) return json(branch)
        if (path.endsWith('/registration-history')) return json(registration)
        throw new Error(`Unexpected fetch: ${path}`)
      }),
    )
  }

  async function expectMalformed(testId: string) {
    const panel = await screen.findByTestId(testId)
    expect(await within(panel).findByText(MALFORMED)).toBeInTheDocument()
    expect(within(panel).queryByText('ยังไม่มีประวัติ')).not.toBeInTheDocument()
    return panel
  }

  const branchCases: [string, unknown][] = [
    ['events: [{}]', history({ events: [{}] })],
    ['records: [{}]', history({ records: [{}] })],
    ['record with unknown record_kind', history({ records: [{ ...record('E1'), record_kind: 'MOVE' }] })],
    ['record with string revision_no', history({ records: [{ ...record('E1'), revision_no: '1' }] })],
    ['record missing request_id', history({ records: [{ ...record('E1'), request_id: undefined }] })],
    ['event with unknown note', history({ events: [event('E1', { notes: ['MADE_UP'] })] })],
    ['event with null revision_no', history({ events: [event('E1', { revision_no: null })] })],
    ['current missing', history({ current: undefined })],
    ['current with unknown source', history({ current: { branch_id: 'BR-SYN-A', source: 'GUESS' } })],
    ['current branch_id number', history({ current: { branch_id: 7, source: 'EVENT' } })],
    ['master with unknown state', history({ master: { state: 'MAYBE', value: null } })],
    ['baseline with unknown source', history({ baseline: { branch_id: null, source: 'SOMETIME' } })],
    ['unknown timeline_status', history({ timeline_status: 'INVALID' })],
    ['unknown consistency', history({ consistency: 'MISMATCH' })],
  ]

  for (const [label, body] of branchCases) {
    it(`branch history: ${label} -> malformed error`, async () => {
      installBoth(body, EMPTY_REGISTRATION)
      render(<RegistryHistoryPanels vehicleId="SYN-V1" branches={BRANCHES} provinces={BRANCHES} />)
      await expectMalformed('branch-history-panel')
      // The other panel is unaffected.
      const other = screen.getByTestId('registration-history-panel')
      expect(await within(other).findByText('ยังไม่มีประวัติ')).toBeInTheDocument()
    })
  }

  const registrationCases: [string, unknown][] = [
    ['items: [{}]', { ...EMPTY_REGISTRATION, items: [{}] }],
    ['item with unknown change_kind', { ...EMPTY_REGISTRATION, items: [{ ...validItem(), change_kind: 'EDIT' }] }],
    ['item with numeric new_registration_no', { ...EMPTY_REGISTRATION, items: [{ ...validItem(), new_registration_no: 12 }] }],
    ['item with unknown accepted exception', { ...EMPTY_REGISTRATION, items: [{ ...validItem(), accepted_exceptions: ['X'] }] }],
    ['current missing', { ...EMPTY_REGISTRATION, current: undefined }],
    ['current field with bad state', { ...EMPTY_REGISTRATION, current: { registration_no: { state: 'X', value: null }, registration_province: { state: 'NOT_RECORDED', value: null } } }],
    ['unknown consistency', { ...EMPTY_REGISTRATION, consistency: 'PROJECTION_MISMATCH' }],
    ['consistency missing', { ...EMPTY_REGISTRATION, consistency: undefined }],
  ]

  for (const [label, body] of registrationCases) {
    it(`registration history: ${label} -> malformed error`, async () => {
      installBoth(history(), body)
      render(<RegistryHistoryPanels vehicleId="SYN-V1" branches={BRANCHES} provinces={BRANCHES} />)
      await expectMalformed('registration-history-panel')
      const other = screen.getByTestId('branch-history-panel')
      expect(await within(other).findByText('req-E1')).toBeInTheDocument()
    })
  }

  it('fully valid responses still render unchanged', async () => {
    installBoth(history(), { ...EMPTY_REGISTRATION, consistency: 'CONSISTENT', items: [validItem()] })
    render(<RegistryHistoryPanels vehicleId="SYN-V1" branches={BRANCHES} provinces={BRANCHES} />)
    const branchPanel = await screen.findByTestId('branch-history-panel')
    expect(await within(branchPanel).findByText('req-E1')).toBeInTheDocument()
    expect(within(branchPanel).queryByText(MALFORMED)).not.toBeInTheDocument()
    const registrationPanel = screen.getByTestId('registration-history-panel')
    expect(await within(registrationPanel).findByText(/กข 1234/)).toBeInTheDocument()
    expect(within(registrationPanel).queryByText(MALFORMED)).not.toBeInTheDocument()
  })
})

function validItem() {
  return {
    change_id: 'VRH-1', change_kind: 'CHANGE', old_registration_no: null, old_registration_province_code: null,
    new_registration_no: 'กข 1234', new_registration_province_code: null, recorded_at: '2026-09-02T03:00:00+00:00',
    recorded_by: 'SYN-USER', request_id: 'rreq-1', related_request_id: null, accepted_exceptions: [], note_th: null,
  }
}
