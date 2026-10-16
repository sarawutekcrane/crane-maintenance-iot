import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { E2HistoryRecord } from '../lib/e2Assignments'
import { E2HistoryTable } from './E2HistoryTable'

/** R2 Batch R2-C2b — the immutable E2 history rows (shapes from the R2-C1 mock). */

const row = (over: Partial<E2HistoryRecord>): E2HistoryRecord => ({
  record_id: 'ODA-1', operation_id: 'ODO-1', record_kind: 'ASSIGNMENT', entry_operation: 'CREATE', event_id: 'ODA-1',
  revision_no: '1', supersedes_record_id: null, assigned_driver_id: 'DRV-TEST-901', mode: 'FULL_DAY',
  start_date: '2026-10-20', end_date: '2026-10-22', shift_start_time: null, shift_end_time: null, shift_end_day_offset: null,
  excluded_dates: [], related_event_id: null, relation: null, early_end_at: null, voided: false, handover_kind: null,
  predecessor_event_id: null, predecessor_revision_no: null, successor_event_id: null, successor_revision_no: null,
  handover_at: null, unknown_start_at: null, unknown_end_at: null, reason_th: null,
  recorded_at: '2026-10-16T00:24:28.000000+00:00', recorded_by: 'dev-user', request_id: 'req-1', ...over,
})

const RECORDS: E2HistoryRecord[] = [
  row({}),
  row({ record_id: 'ODA-H', record_kind: 'HANDOVER', event_id: 'ODA-H', assigned_driver_id: null, mode: null, start_date: null,
    end_date: null, handover_kind: 'H2', predecessor_event_id: 'ODA-1', predecessor_revision_no: '1', successor_event_id: 'ODA-2',
    successor_revision_no: '1', handover_at: '2026-10-22T13:00:00+00:00', unknown_start_at: '2026-10-22T13:00:00+00:00',
    unknown_end_at: '2026-10-22T14:00:00+00:00', recorded_at: '2026-10-16T00:25:00+00:00', request_id: 'req-2' }),
  row({ record_id: 'ODA-R', record_kind: 'REVISION', entry_operation: 'SUBSTITUTE', revision_no: '2', excluded_dates: ['2026-10-21'],
    reason_th: 'ผู้ขับลา', recorded_at: '2026-10-16T00:26:00+00:00', request_id: 'req-3' }),
  row({ record_id: 'ODA-S', record_kind: 'ASSIGNMENT', entry_operation: 'REVISE', event_id: 'ODA-S', mode: 'NIGHT_SHIFT',
    shift_start_time: '20:00', shift_end_time: '06:00', shift_end_day_offset: '1', relation: 'SPLIT', related_event_id: 'ODA-N',
    recorded_at: '2026-10-16T00:27:00+00:00', request_id: 'req-4' }),
  row({ record_id: 'ODA-E', record_kind: 'REVISION', entry_operation: 'EARLY_END', revision_no: '3',
    early_end_at: '2026-10-16T00:24:54+00:00', voided: true, recorded_at: '2026-10-16T00:28:00+00:00', request_id: 'req-5' }),
  row({ record_id: 'ODA-C', record_kind: 'CANCELLATION', entry_operation: 'CANCEL', revision_no: '4', assigned_driver_id: null,
    mode: null, start_date: null, end_date: null, reason_th: 'ยกเลิก', recorded_at: '2026-10-16T00:29:00+00:00', request_id: 'req-6' }),
]

describe('E2HistoryTable', () => {
  it('shows every stored row newest first, with reason, actor and request id', () => {
    render(<MemoryRouter><E2HistoryTable records={RECORDS} /></MemoryRouter>)
    const table = screen.getByTestId('e2-history')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(6)
    expect(rows[0]).toHaveTextContent('การยกเลิก')
    expect(rows[0]).toHaveTextContent('ยกเลิกการมอบหมายก่อนเริ่ม')
    expect(rows[0]).toHaveTextContent('req-6')
    expect(rows[5]).toHaveTextContent('บันทึกการมอบหมาย')
    expect(table).toHaveTextContent('ผู้ขับลา')
    expect(table).toHaveTextContent('dev-user')
  })

  it('renders handovers, splits, substitutions, early ends and voids from the stored fields only', () => {
    render(<MemoryRouter><E2HistoryTable records={RECORDS} /></MemoryRouter>)
    const table = screen.getByTestId('e2-history')
    expect(table).toHaveTextContent('H2 — ทั้งวันวันสุดท้าย → กะกลางคืนที่เริ่มวันเดียวกัน')
    expect(table).toHaveTextContent('ช่วงที่ไม่แน่ชัด')
    expect(table).toHaveTextContent('20:00 – 06:00 (+1 วัน)')
    expect(table).toHaveTextContent('แยกช่วงจาก ODA-N')
    expect(table).toHaveTextContent('วันที่ตัดออก')
    expect(table).toHaveTextContent('สิ้นสุดก่อนกำหนดเมื่อ')
    expect(table).toHaveTextContent('ยกเลิกเพราะบันทึกผิด')
    expect(within(table).getAllByRole('link', { name: 'DRV-TEST-901' })[0]).toHaveAttribute('href', '/drivers/DRV-TEST-901')
  })

  it('an empty history says so (it is not an error)', () => {
    render(<MemoryRouter><E2HistoryTable records={[]} /></MemoryRouter>)
    expect(screen.getByText('ยังไม่มีประวัติการมอบหมายตามวัน/กะ')).toBeInTheDocument()
  })
})
