import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { TimelinePeriod } from '../lib/r2History'
import { TimelineEventDialog, type TimelineOperation } from './TimelineEventDialog'

/** R2 Batch R2-C2a — the five effective-dated operations: exact backend body shapes. */

const assignment: TimelinePeriod = {
  event_id: 'CDR-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '3', head_record_id: 'CDR-3',
  target_id: 'DRV-TEST-901', effective_at: '2026-01-04T17:00:00+00:00', effective_precision: 'DATE',
  derived_end_at: null, recorded_at: '2026-10-15T05:00:00+00:00', recorded_by: 'dev-user', notes: [],
}
const endEvent: TimelinePeriod = { ...assignment, event_id: 'CDR-9', head_record_id: 'CDR-9', revision_no: '1',
  entry_operation: 'END', target_id: null, effective_at: '2026-02-01T03:00:00+00:00', effective_precision: 'DATETIME' }

function setup(operation: TimelineOperation, over: Partial<Parameters<typeof TimelineEventDialog>[0]> = {}) {
  const onSubmit = vi.fn()
  render(
    <TimelineEventDialog
      operation={operation}
      targetField="driver_id"
      targetName="คนขับ/ผู้ควบคุม"
      currentId="DRV-TEST-901"
      events={[assignment, endEvent]}
      options={[{ id: 'DRV-TEST-901', label: 'หนึ่ง (DRV-TEST-901)' }, { id: 'DRV-TEST-902', label: 'สอง (DRV-TEST-902)' }]}
      submitting={false}
      error={null}
      onCancel={() => {}}
      onSubmit={onSubmit}
      {...over}
    />,
  )
  return { onSubmit, user: userEvent.setup() }
}

const confirm = (op: string) => screen.getByRole('button', { name: new RegExp(`^ยืนยัน${op}`) })

describe('TimelineEventDialog', () => {
  it('TRANSFER: nothing is pre-selected; an explicit target is required; NOW is allowed', async () => {
    const { onSubmit, user } = setup('TRANSFER')
    expect(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม')).toHaveValue('')
    await user.click(confirm('เปลี่ยน'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาเลือกหรือระบุรหัสคนขับ/ผู้ควบคุม')
    await user.selectOptions(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-902')
    await user.click(confirm('เปลี่ยน'))
    expect(onSubmit).toHaveBeenCalledWith({
      operation: 'TRANSFER', driver_id: 'DRV-TEST-902', effective: { mode: 'NOW' }, expected_current_driver_id: 'DRV-TEST-901',
    })
  })

  it('DATETIME is sent with the explicit +07:00 offset; an optional reason is sent only when typed', async () => {
    const { onSubmit, user } = setup('TRANSFER', { currentId: null })
    await user.selectOptions(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-901')
    await user.click(screen.getByLabelText('ระบุวันที่และเวลา'))
    await user.type(screen.getByLabelText('วันที่และเวลาที่มีผล'), '2026-03-01T10:15:30')
    await user.type(screen.getByLabelText('เหตุผล (ไม่บังคับ)'), 'รับมอบรถ')
    await user.click(confirm('เปลี่ยน'))
    expect(onSubmit).toHaveBeenCalledWith({
      operation: 'TRANSFER', driver_id: 'DRV-TEST-901', effective: { mode: 'DATETIME', at: '2026-03-01T10:15:30+07:00' },
      expected_current_driver_id: null, reason_th: 'รับมอบรถ',
    })
  })

  it('INSERTION has no NOW option and requires a reason', async () => {
    const { onSubmit, user } = setup('INSERTION')
    expect(screen.queryByLabelText('ตอนนี้')).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-902')
    await user.type(screen.getByLabelText('วันที่มีผล'), '2026-01-02')
    await user.click(confirm('เพิ่ม'))
    expect(onSubmit).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText('เหตุผล (บังคับ)'), 'บันทึกย้อนหลัง')
    await user.click(confirm('เพิ่ม'))
    expect(onSubmit).toHaveBeenCalledWith({
      operation: 'INSERTION', driver_id: 'DRV-TEST-902', effective: { mode: 'DATE', date: '2026-01-02' },
      expected_current_driver_id: 'DRV-TEST-901', reason_th: 'บันทึกย้อนหลัง',
    })
  })

  it('END sends no target', async () => {
    const { onSubmit, user } = setup('END')
    expect(screen.queryByLabelText('รหัสคนขับ/ผู้ควบคุม')).not.toBeInTheDocument()
    await user.click(confirm('สิ้นสุด'))
    expect(onSubmit).toHaveBeenCalledWith({ operation: 'END', effective: { mode: 'NOW' }, expected_current_driver_id: 'DRV-TEST-901' })
  })

  it('CORRECTION is prefilled from the chosen event and carries its event id and revision', async () => {
    const { onSubmit, user } = setup('CORRECTION')
    await user.selectOptions(screen.getByLabelText('รายการในประวัติ'), 'CDR-1')
    expect(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม')).toHaveValue('DRV-TEST-901')
    expect(screen.getByLabelText('วันที่มีผล')).toHaveValue('2026-01-05')
    await user.selectOptions(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-902')
    await user.type(screen.getByLabelText('เหตุผล (บังคับ)'), 'แก้ไขรหัส')
    await user.click(confirm('แก้ไข'))
    expect(onSubmit).toHaveBeenCalledWith({
      operation: 'CORRECTION', event_id: 'CDR-1', expected_revision_no: '3', driver_id: 'DRV-TEST-902',
      effective: { mode: 'DATE', date: '2026-01-05' }, expected_current_driver_id: 'DRV-TEST-901', reason_th: 'แก้ไขรหัส',
    })
  })

  it('a CORRECTION of an END event sends no target (it stays an END)', async () => {
    const { onSubmit, user } = setup('CORRECTION')
    await user.selectOptions(screen.getByLabelText('รายการในประวัติ'), 'CDR-9')
    expect(screen.queryByLabelText('รหัสคนขับ/ผู้ควบคุม')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('เหตุผล (บังคับ)'), 'แก้เวลา')
    await user.click(confirm('แก้ไข'))
    const body = onSubmit.mock.calls[0][0]
    expect(body).not.toHaveProperty('driver_id')
    expect(body).toMatchObject({ operation: 'CORRECTION', event_id: 'CDR-9', expected_revision_no: '1',
      effective: { mode: 'DATETIME', at: '2026-02-01T10:00:00+07:00' } })
  })

  it('CANCELLATION warns that history is kept, and needs an event and a reason', async () => {
    const { onSubmit, user } = setup('CANCELLATION')
    expect(screen.getByRole('note')).toHaveTextContent('รายการเดิมยังคงอยู่')
    await user.type(screen.getByLabelText('เหตุผล (บังคับ)'), 'ยกเลิก')
    await user.click(confirm('ยกเลิก'))
    expect(onSubmit).not.toHaveBeenCalled()
    await user.selectOptions(screen.getByLabelText('รายการในประวัติ'), 'CDR-1')
    await user.click(confirm('ยกเลิก'))
    expect(onSubmit).toHaveBeenCalledWith({
      operation: 'CANCELLATION', event_id: 'CDR-1', expected_revision_no: '3', expected_current_driver_id: 'DRV-TEST-901', reason_th: 'ยกเลิก',
    })
  })

  it('without a loaded list the id is typed; while submitting every control is disabled', async () => {
    const { onSubmit, user } = setup('TRANSFER', { options: null, targetField: 'technician_id', targetName: 'ช่าง', currentId: null })
    await user.type(screen.getByLabelText('รหัสช่าง'), 'TEC-TEST-911')
    await user.click(confirm('เปลี่ยน'))
    expect(onSubmit).toHaveBeenCalledWith({
      operation: 'TRANSFER', technician_id: 'TEC-TEST-911', effective: { mode: 'NOW' }, expected_current_technician_id: null,
    })
  })

  it('shows the server error and disables the form while submitting', () => {
    setup('END', { submitting: true, error: 'ข้อผิดพลาดจากระบบ' })
    expect(screen.getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'ปิด' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('ข้อผิดพลาดจากระบบ')
  })
})
