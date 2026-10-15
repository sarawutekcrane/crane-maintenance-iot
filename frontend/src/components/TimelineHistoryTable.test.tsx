import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ReadFailure, TimelinePeriod } from '../lib/r2History'
import { R2ReadFailureView, TimelineHistoryTable } from './TimelineHistoryTable'

/** R2 Batch R2-C2a — the shared read-only timeline history and read-failure view. */

const period = (over: Partial<TimelinePeriod>): TimelinePeriod => ({
  event_id: 'E-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: 'E-1',
  target_id: 'DRV-TEST-901', effective_at: '2026-01-04T17:00:00+00:00', effective_precision: 'DATE',
  derived_end_at: null, recorded_at: '2026-10-15T05:28:53.694420+00:00', recorded_by: 'dev-user', notes: [], ...over,
})

describe('TimelineHistoryTable', () => {
  it('shows newest effective first, date-only for DATE precision, and separate recorded time / revision / actor', () => {
    render(
      <TimelineHistoryTable
        targetHeader="คนขับ"
        emptyTitle="ว่าง"
        events={[
          period({ event_id: 'old' }),
          period({ event_id: 'new', entry_operation: 'END', target_id: null, effective_at: '2026-03-01T03:15:00+00:00',
            effective_precision: 'DATETIME', revision_no: '2' }),
        ]}
      />,
    )
    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('สิ้นสุด')).toBeInTheDocument()
    expect(within(rows[0]).getByText('— (สิ้นสุด)')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/10:15/)).toBeInTheDocument() // 03:15 UTC = 10:15 Bangkok
    expect(within(rows[1]).getByText('DRV-TEST-901')).toBeInTheDocument()
    // DATE precision: 2026-01-04T17:00Z is 5 Jan 2026 00:00 in Bangkok, shown without a clock time.
    const effectiveCell = within(rows[1]).getAllByRole('cell')[2]
    expect(effectiveCell.textContent).toMatch(/5/)
    expect(effectiveCell.textContent).not.toMatch(/00:00/)
    expect(effectiveCell.textContent).toContain('ระดับวัน')
    expect(within(rows[1]).getByText('dev-user')).toBeInTheDocument()
    // No reason column: the reads do not return one.
    expect(screen.queryByRole('columnheader', { name: 'เหตุผล' })).not.toBeInTheDocument()
  })

  it('marks cancelled and superseded periods and translates system notes', () => {
    render(
      <TimelineHistoryTable
        targetHeader="ช่าง"
        emptyTitle="ว่าง"
        events={[period({ event_id: 'c', in_force: false, notes: ['CANCELLED'] }), period({ event_id: 's', in_force: false,
          effective_at: '2026-02-01T00:00:00+00:00', notes: ['SAME_INSTANT'] })]}
      />,
    )
    expect(screen.getAllByText('ยกเลิกแล้ว').length).toBeGreaterThan(0)
    expect(screen.getByText('ไม่มีผล')).toBeInTheDocument()
    expect(screen.getByText('เวลาเดียวกับรายการอื่น')).toBeInTheDocument()
  })

  it('an empty timeline shows the empty state', () => {
    render(<TimelineHistoryTable targetHeader="ช่าง" events={[]} emptyTitle="ยังไม่มีประวัติ" emptyDescription="คำอธิบาย" />)
    expect(screen.getByText('ยังไม่มีประวัติ')).toBeInTheDocument()
  })
})

describe('R2ReadFailureView', () => {
  const failure = (over: Partial<ReadFailure>): ReadFailure =>
    ({ kind: 'error', status: 503, code: 'X_READ_FAILED', message: 'อ่านไม่สำเร็จ', requestId: 'rid-1', ...over })

  it('403 is a permission state, not an error with retry', () => {
    render(<R2ReadFailureView failure={failure({ kind: 'forbidden', status: 403 })} title="t" onRetry={() => {}} />)
    expect(screen.getByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('an out-of-scope id gets its own explanation', () => {
    render(<R2ReadFailureView failure={failure({ kind: 'scope', status: 422, code: 'VEHICLE_SCOPE_UNPROVEN', message: 'นอกขอบเขต' })} title="t" onRetry={() => {}} />)
    expect(screen.getByTestId('r2-scope-unproven')).toHaveTextContent('นอกขอบเขต')
    expect(screen.getByTestId('r2-scope-unproven')).toHaveTextContent('TEST/REAL')
  })

  it('other failures show the code, request id and a retry', async () => {
    const retry = vi.fn()
    render(<R2ReadFailureView failure={failure({})} title="โหลดไม่สำเร็จ" onRetry={retry} />)
    expect(screen.getByText('โหลดไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.getByText(/X_READ_FAILED/)).toBeInTheDocument()
    expect(screen.getByText(/rid-1/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    expect(retry).toHaveBeenCalledOnce()
  })
})
