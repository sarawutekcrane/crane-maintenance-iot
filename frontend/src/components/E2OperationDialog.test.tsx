import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { E2AssignmentState, E2HistoryRecord } from '../lib/e2Assignments'
import { buildE2Body, emptyE2Form, formFromState, type E2Form, type E2Intent } from '../lib/e2Writes'
import { E2OperationDialog, E2WriteNotice } from './E2OperationDialog'

/** R2 Batch R2-C2b — the five E2 operations and every backend variant: exact bodies, no defaults. */

const TODAY = '2026-10-16'
const stateRow = (over: Partial<E2HistoryRecord> = {}): E2HistoryRecord => ({
  record_id: 'ODA-1', operation_id: 'ODO-1', record_kind: 'ASSIGNMENT', entry_operation: 'CREATE', event_id: 'ODA-1',
  revision_no: '1', supersedes_record_id: null, assigned_driver_id: 'DRV-TEST-901', mode: 'FULL_DAY',
  start_date: '2026-10-20', end_date: '2026-10-22', shift_start_time: null, shift_end_time: null, shift_end_day_offset: null,
  excluded_dates: [], related_event_id: null, relation: null, early_end_at: null, voided: false, handover_kind: null,
  predecessor_event_id: null, predecessor_revision_no: null, successor_event_id: null, successor_revision_no: null,
  handover_at: null, unknown_start_at: null, unknown_end_at: null, reason_th: null, recorded_at: '2026-10-16T00:00:00+00:00',
  recorded_by: 'dev-user', request_id: 'r', ...over,
})
const assignment = (over: Partial<E2HistoryRecord> = {}, revision = '2'): E2AssignmentState => ({
  event: { event_id: over.event_id ?? 'ODA-1', kind: 'ASSIGNMENT', lifecycle: 'ACTIVE', revision_no: revision, head_record_id: 'h' },
  state: stateRow(over),
})
const FULL = assignment()
const NIGHT = assignment({ event_id: 'ODA-N', mode: 'NIGHT_SHIFT', shift_start_time: '20:00', shift_end_time: '06:00', shift_end_day_offset: '1' }, '1')
const form = (over: Partial<E2Form>): E2Form => ({ ...emptyE2Form(), ...over })
const body = (r: ReturnType<typeof buildE2Body>) => ('body' in r ? r.body : r)

describe('buildE2Body — CREATE', () => {
  it('FULL_DAY sends no shift and no reason for a same-day or future start', () => {
    expect(body(buildE2Body('CREATE', form({ driverId: 'DRV-TEST-901', mode: 'FULL_DAY', startDate: TODAY, endDate: '2026-10-18' }), null, [], TODAY)))
      .toEqual({ operation: 'CREATE', driver_id: 'DRV-TEST-901', mode: 'FULL_DAY', start_date: TODAY, end_date: '2026-10-18' })
  })

  it('a shift mode needs explicit applied times and the day offset as a number', () => {
    const base = form({ driverId: 'DRV-TEST-902', mode: 'NIGHT_SHIFT', startDate: '2026-10-22', endDate: '2026-10-23' })
    expect(buildE2Body('CREATE', base, null, [], TODAY)).toEqual({ error: expect.stringContaining('HH:MM') })
    expect(buildE2Body('CREATE', { ...base, shiftStart: '20:00', shiftEnd: '06:00' }, null, [], TODAY))
      .toEqual({ error: expect.stringContaining('วันถัดไป') })
    expect(body(buildE2Body('CREATE', { ...base, shiftStart: '20:00', shiftEnd: '06:00', shiftOffset: '1' }, null, [], TODAY))).toEqual({
      operation: 'CREATE', driver_id: 'DRV-TEST-902', mode: 'NIGHT_SHIFT', start_date: '2026-10-22', end_date: '2026-10-23',
      shift: { start_time: '20:00', end_time: '06:00', end_day_offset: 1 },
    })
  })

  it('a handover names the predecessor and its current revision', () => {
    const f = form({ driverId: 'DRV-TEST-902', mode: 'NIGHT_SHIFT', startDate: '2026-10-22', endDate: '2026-10-23',
      shiftStart: '20:00', shiftEnd: '06:00', shiftOffset: '1', handover: true, predecessorId: 'ODA-1' })
    expect(body(buildE2Body('CREATE', f, null, [FULL], TODAY))).toMatchObject({
      handover: { predecessor_event_id: 'ODA-1', expected_revision_no: '2' },
    })
    expect(buildE2Body('CREATE', { ...f, predecessorId: '' }, null, [FULL], TODAY)).toHaveProperty('error')
  })

  it('a back-dated start needs a reason; no driver or mode is ever chosen automatically', () => {
    const past = form({ driverId: 'DRV-TEST-901', mode: 'FULL_DAY', startDate: '2026-10-10', endDate: '2026-10-11' })
    expect(buildE2Body('CREATE', past, null, [], TODAY)).toEqual({ error: 'กรุณาระบุเหตุผล' })
    expect(body(buildE2Body('CREATE', { ...past, reason: 'บันทึกย้อนหลัง' }, null, [], TODAY))).toMatchObject({ reason_th: 'บันทึกย้อนหลัง' })
    expect(buildE2Body('CREATE', { ...past, driverId: '' }, null, [], TODAY)).toHaveProperty('error')
    expect(buildE2Body('CREATE', { ...past, mode: '' }, null, [], TODAY)).toHaveProperty('error')
  })
})

describe('buildE2Body — REVISE variants', () => {
  const reason = 'แก้ไข'
  it('STATE: the full new state (driver, dates; shift for a shift mode), never the mode', () => {
    expect(body(buildE2Body('REVISE', { ...formFromState(FULL), endDate: '2026-10-25', reason }, FULL, [], TODAY))).toEqual({
      operation: 'REVISE', event_id: 'ODA-1', expected_revision_no: '2', reason_th: reason,
      driver_id: 'DRV-TEST-901', start_date: '2026-10-20', end_date: '2026-10-25',
    })
    expect(body(buildE2Body('REVISE', { ...formFromState(NIGHT), shiftEnd: '07:00', reason }, NIGHT, [], TODAY))).toMatchObject({
      shift: { start_time: '20:00', end_time: '07:00', end_day_offset: 1 },
    })
  })

  it('SPLIT: the current driver and dates unchanged, the NEW shift times and split_from_date', () => {
    const f = { ...formFromState(NIGHT), reviseVariant: 'SPLIT' as const, driverId: 'ignored', startDate: '2000-01-01',
      shiftStart: '21:00', shiftEnd: '07:00', shiftOffset: '1' as const, splitFrom: '2026-10-23', reason }
    expect(body(buildE2Body('REVISE', f, NIGHT, [], TODAY))).toEqual({
      operation: 'REVISE', event_id: 'ODA-N', expected_revision_no: '1', reason_th: reason,
      driver_id: 'DRV-TEST-901', start_date: '2026-10-20', end_date: '2026-10-22',
      shift: { start_time: '21:00', end_time: '07:00', end_day_offset: 1 }, split_from_date: '2026-10-23',
    })
    expect(buildE2Body('REVISE', { ...f, splitFrom: '' }, NIGHT, [], TODAY)).toHaveProperty('error')
  })

  it('EXCLUDE: the current state plus the sorted, unique exclude_dates', () => {
    const f = { ...formFromState(FULL), reviseVariant: 'EXCLUDE' as const, excludeDates: ['2026-10-22', '2026-10-21', '2026-10-22'], reason }
    expect(body(buildE2Body('REVISE', f, FULL, [], TODAY))).toEqual({
      operation: 'REVISE', event_id: 'ODA-1', expected_revision_no: '2', reason_th: reason,
      driver_id: 'DRV-TEST-901', start_date: '2026-10-20', end_date: '2026-10-22', exclude_dates: ['2026-10-21', '2026-10-22'],
    })
    expect(buildE2Body('REVISE', { ...f, excludeDates: [] }, FULL, [], TODAY)).toHaveProperty('error')
  })

  it('VOID: void_elapsed true and no state fields', () => {
    expect(body(buildE2Body('REVISE', form({ reviseVariant: 'VOID', reason }), FULL, [], TODAY))).toEqual({
      operation: 'REVISE', event_id: 'ODA-1', expected_revision_no: '2', reason_th: reason, void_elapsed: true,
    })
  })

  it('every REVISE needs a reason', () => {
    expect(buildE2Body('REVISE', form({ reviseVariant: 'VOID' }), FULL, [], TODAY)).toEqual({ error: 'กรุณาระบุเหตุผล' })
  })
})

describe('buildE2Body — SUBSTITUTE, CANCEL, EARLY_END', () => {
  it('SUBSTITUTE: whole days / shifts by labelled date, another explicit driver, a reason', () => {
    expect(body(buildE2Body('SUBSTITUTE', form({ dates: ['2026-10-21'], driverId: 'DRV-TEST-902', reason: 'แทน' }), FULL, [], TODAY))).toEqual({
      operation: 'SUBSTITUTE', event_id: 'ODA-1', expected_revision_no: '2', dates: ['2026-10-21'], driver_id: 'DRV-TEST-902', reason_th: 'แทน',
    })
    expect(buildE2Body('SUBSTITUTE', form({ driverId: 'DRV-TEST-902', reason: 'แทน' }), FULL, [], TODAY)).toHaveProperty('error')
    expect(buildE2Body('SUBSTITUTE', form({ dates: ['2026-10-21'], reason: 'แทน' }), FULL, [], TODAY)).toHaveProperty('error')
  })

  it('CANCEL: the event, its revision and a reason only', () => {
    expect(body(buildE2Body('CANCEL', form({ reason: 'ยกเลิก' }), FULL, [], TODAY)))
      .toEqual({ operation: 'CANCEL', event_id: 'ODA-1', expected_revision_no: '2', reason_th: 'ยกเลิก' })
  })

  it('EARLY_END: NOW or AFTER_DATE with its date', () => {
    expect(body(buildE2Body('EARLY_END', form({ earlyMode: 'NOW', reason: 'x' }), FULL, [], TODAY)))
      .toEqual({ operation: 'EARLY_END', event_id: 'ODA-1', expected_revision_no: '2', end: { mode: 'NOW' }, reason_th: 'x' })
    expect(body(buildE2Body('EARLY_END', form({ earlyMode: 'AFTER_DATE', earlyDate: '2026-10-21', reason: 'x' }), FULL, [], TODAY)))
      .toMatchObject({ end: { mode: 'AFTER_DATE', date: '2026-10-21' } })
    expect(buildE2Body('EARLY_END', form({ reason: 'x' }), FULL, [], TODAY)).toHaveProperty('error')
  })

  it('an operation on an assignment needs a target', () => {
    expect(buildE2Body('CANCEL', form({ reason: 'x' }), null, [], TODAY)).toHaveProperty('error')
  })
})

// ---------------------------------------------------------------------------
// The dialog UI
// ---------------------------------------------------------------------------

const OPTIONS = [{ id: 'DRV-TEST-901', label: 'ผู้ขับทดสอบ หนึ่ง (DRV-TEST-901)' }, { id: 'DRV-TEST-902', label: 'ผู้ขับทดสอบ สอง (DRV-TEST-902)' }]

function renderDialog(props: Partial<Parameters<typeof E2OperationDialog>[0]> = {}) {
  const onSubmit = vi.fn()
  render(<E2OperationDialog operation="CREATE" target={null} assignments={[FULL]} driverOptions={OPTIONS} today={TODAY}
    submitting={false} error={null} onCancel={vi.fn()} onSubmit={onSubmit} {...props} />)
  return { onSubmit, dialog: screen.getByTestId('e2-operation-dialog') }
}

describe('E2OperationDialog', () => {
  it('CREATE: no driver or mode preselected; shift inputs appear only for a shift mode; exact body sent', async () => {
    const user = userEvent.setup()
    const { onSubmit, dialog } = renderDialog()
    expect(within(dialog).getByLabelText('ผู้ขับที่ได้รับมอบหมาย')).toHaveValue('')
    expect(within(dialog).getByLabelText('รูปแบบการมอบหมาย')).toHaveValue('')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(within(dialog).getByRole('alert')).toHaveTextContent('ระบบไม่เลือกให้')
    await user.selectOptions(within(dialog).getByLabelText('ผู้ขับที่ได้รับมอบหมาย'), 'DRV-TEST-902')
    await user.selectOptions(within(dialog).getByLabelText('รูปแบบการมอบหมาย'), 'DAY_SHIFT')
    expect(within(dialog).getByLabelText('เวลาเริ่มกะ')).toHaveValue('')
    await user.type(within(dialog).getByLabelText('วันที่เริ่มต้น'), '2026-10-21')
    await user.type(within(dialog).getByLabelText('วันที่สิ้นสุด (รวมวันนี้)'), '2026-10-21')
    await user.type(within(dialog).getByLabelText('เวลาเริ่มกะ'), '08:00')
    await user.type(within(dialog).getByLabelText('เวลาสิ้นสุดกะ'), '17:00')
    await user.selectOptions(within(dialog).getByLabelText('กะสิ้นสุด'), '0')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(onSubmit).toHaveBeenCalledWith({ operation: 'CREATE', driver_id: 'DRV-TEST-902', mode: 'DAY_SHIFT', start_date: '2026-10-21',
      end_date: '2026-10-21', shift: { start_time: '08:00', end_time: '17:00', end_day_offset: 0 } })
    await user.selectOptions(within(dialog).getByLabelText('รูปแบบการมอบหมาย'), 'FULL_DAY')
    expect(within(dialog).queryByLabelText('เวลาเริ่มกะ')).not.toBeInTheDocument()
  })

  it('CREATE handover lists only ACTIVE assignments with a state', async () => {
    const user = userEvent.setup()
    const cancelled = { ...assignment({ event_id: 'ODA-X' }), event: { ...assignment({ event_id: 'ODA-X' }).event, lifecycle: 'CANCELLED' as const } }
    const { dialog } = renderDialog({ assignments: [FULL, cancelled] })
    await user.click(within(dialog).getByLabelText(/ส่งต่อจากการมอบหมายก่อนหน้า/))
    const options = within(within(dialog).getByLabelText('การมอบหมายก่อนหน้า')).getAllByRole('option').map((o) => o.getAttribute('value'))
    expect(options).toEqual(['', 'ODA-1'])
  })

  it('REVISE offers the split variant only for a shift assignment and prefills the current state', async () => {
    const user = userEvent.setup()
    const { dialog } = renderDialog({ operation: 'REVISE', target: FULL })
    expect(within(dialog).queryByLabelText(/เปลี่ยนเวลากะ/)).not.toBeInTheDocument()
    expect(within(dialog).getByLabelText('วันที่สิ้นสุด (รวมวันนี้)')).toHaveValue('2026-10-22')
    expect(within(dialog).getByTestId('e2-dialog-target')).toHaveTextContent('ODA-1')
    await user.click(within(dialog).getByLabelText(/ตัดวัน\/กะ/))
    expect(within(dialog).getByLabelText('วันที่ที่ต้องการตัดออก')).toBeInTheDocument()
  })

  it('REVISE split on a night shift sends the new times from the chosen date', async () => {
    const user = userEvent.setup()
    const { dialog, onSubmit } = renderDialog({ operation: 'REVISE', target: NIGHT })
    await user.click(within(dialog).getByLabelText(/เปลี่ยนเวลากะ/))
    await user.type(within(dialog).getByLabelText('เริ่มใช้เวลากะใหม่ตั้งแต่วันที่'), '2026-10-21')
    await user.clear(within(dialog).getByLabelText('เวลาเริ่มกะ'))
    await user.type(within(dialog).getByLabelText('เวลาเริ่มกะ'), '21:00')
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'เปลี่ยนเวลา')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      split_from_date: '2026-10-21', shift: { start_time: '21:00', end_time: '06:00', end_day_offset: 1 }, driver_id: 'DRV-TEST-901',
    }))
  })

  it('SUBSTITUTE builds the date list (add / remove) and needs another driver', async () => {
    const user = userEvent.setup()
    const { dialog, onSubmit } = renderDialog({ operation: 'SUBSTITUTE', target: FULL })
    const input = within(dialog).getByLabelText(/วัน\/กะที่ให้ผู้ขับแทน/)
    await user.type(input, '2026-10-22')
    await user.click(within(dialog).getByRole('button', { name: 'เพิ่มวันที่' }))
    await user.type(input, '2026-10-21')
    await user.click(within(dialog).getByRole('button', { name: 'เพิ่มวันที่' }))
    await user.click(within(dialog).getByRole('button', { name: 'ลบ 2026-10-22' }))
    await user.selectOptions(within(dialog).getByLabelText('ผู้ขับแทน'), 'DRV-TEST-902')
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'ลา')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(onSubmit).toHaveBeenCalledWith({ operation: 'SUBSTITUTE', event_id: 'ODA-1', expected_revision_no: '2',
      dates: ['2026-10-21'], driver_id: 'DRV-TEST-902', reason_th: 'ลา' })
  })

  it('a backend refusal is shown in the dialog with the overlap details; a submitting dialog cannot submit twice', () => {
    renderDialog({
      operation: 'CANCEL', target: FULL, submitting: true,
      error: { text: 'ช่วงเวลานี้ทับกับการมอบหมายอื่นของรถคันนี้', overlap: {
        axis: 'VEHICLE', conflicting_event_id: 'ODA-9',
        first: { event_id: 'ODA-9', vehicle_id: 'VEH-1048', assigned_driver_id: 'DRV-TEST-901', label_date: '2026-10-21',
          start: '2026-10-20T17:00:00+00:00', end: '2026-10-21T17:00:00+00:00' },
        second: null,
      } },
    })
    expect(screen.getByRole('alert')).toHaveTextContent('ทับกับการมอบหมายอื่น')
    expect(screen.getByTestId('e2-overlap')).toHaveTextContent('ODA-9')
    expect(screen.getByTestId('e2-overlap')).toHaveTextContent('00:00 – 24:00')
    expect(screen.getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled()
  })
})

describe('E2WriteNotice', () => {
  const intent = (state: E2Intent['state']): E2Intent => ({
    v: 1, vehicle_id: 'VEH-1048', request_id: '11111111-2222-4333-8444-555555555555', path: '/x', body: {}, body_json: '{}',
    operation: 'CREATE', created_at: 'x', state, prior_uncertain: true, record_ids: [],
  })

  it('an UNKNOWN intent offers the explicit same-id resend; a CONFLICT offers none and escalates', async () => {
    const onResend = vi.fn()
    const { rerender } = render(<E2WriteNotice message={null} intent={intent('UNKNOWN')} inFlight={false} onResend={onResend} onReload={vi.fn()} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    expect(onResend).toHaveBeenCalledTimes(1)
    rerender(<E2WriteNotice message={null} intent={intent('CONFLICT')} inFlight={false} onResend={onResend} onReload={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).not.toBeInTheDocument()
    expect(screen.getByTestId('e2-conflict-escalation')).toHaveTextContent('กรุณาแจ้งผู้ดูแลระบบ')
  })

  it('shows the success warnings by their Thai label', () => {
    render(<E2WriteNotice inFlight={false} intent={null} onResend={vi.fn()} onReload={vi.fn()} message={{ tone: 'success', text: 'บันทึกเรียบร้อยแล้ว',
      warnings: [{ code: 'ADJACENT_ASSIGNMENT_REST_WARNING', event_id: 'e', driver_id: 'd', vehicle_id: 'v', related_event_id: 'r' }] }} />)
    expect(screen.getByTestId('e2-write-warnings')).toHaveTextContent('ไม่ใช่การรับรองความปลอดภัย')
  })
})
