import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  formatE2Date,
  formatE2Instant,
  formatE2Range,
  formatE2Shift,
  sortRecords,
  type E2HistoryRecord,
} from '../lib/e2Assignments'
import {
  e2HandoverKindLabel,
  e2ModeLabel,
  e2OperationLabel,
  e2RecordKindLabel,
  e2RelationLabel,
} from '../lib/labels'
import { ResponsiveTable } from './ResponsiveTable'

/**
 * R2 Batch R2-C2b — every stored E2 row of one vehicle (originals, revisions,
 * handovers, cancellations), newest first. Rows are immutable: a correction
 * is a new revision, a cancellation a terminal row; nothing is ever hidden or
 * rewritten here. Dates and instants are shown in Asia/Bangkok.
 */
export function E2HistoryTable({ records }: { records: readonly E2HistoryRecord[] }) {
  return (
    <div data-testid="e2-history">
      <ResponsiveTable
        columns={[
          { key: 'recorded_at', header: 'บันทึกเมื่อ', render: (r: E2HistoryRecord) => formatE2Instant(r.recorded_at) },
          {
            key: 'kind',
            header: 'รายการ',
            render: (r: E2HistoryRecord) => (
              <span>
                {e2RecordKindLabel[r.record_kind] ?? r.record_kind}
                <br />
                <small>{e2OperationLabel[r.entry_operation] ?? r.entry_operation}</small>
              </span>
            ),
          },
          {
            key: 'event',
            header: 'รายการมอบหมาย / ฉบับ',
            render: (r: E2HistoryRecord) => (
              <span>
                <code>{r.event_id}</code> <small>ฉบับที่ {r.revision_no}</small>
              </span>
            ),
          },
          { key: 'details', header: 'รายละเอียด', render: (r: E2HistoryRecord) => <RecordDetails record={r} /> },
          { key: 'reason', header: 'เหตุผล', render: (r: E2HistoryRecord) => r.reason_th ?? '-' },
          { key: 'recorded_by', header: 'ผู้บันทึก', render: (r: E2HistoryRecord) => r.recorded_by },
          { key: 'request_id', header: 'รหัสคำขอ', render: (r: E2HistoryRecord) => <code>{r.request_id}</code> },
        ]}
        rows={sortRecords(records)}
        getRowKey={(r) => r.record_id}
        emptyTitle="ยังไม่มีประวัติการมอบหมายตามวัน/กะ"
        emptyDescription="ยังไม่เคยบันทึกการมอบหมายผู้ขับตามวัน/กะของรถคันนี้"
      />
    </div>
  )
}

function RecordDetails({ record: r }: { record: E2HistoryRecord }) {
  const lines: ReactNode[] = []
  if (r.record_kind === 'HANDOVER') {
    lines.push(e2HandoverKindLabel[r.handover_kind ?? ''] ?? r.handover_kind ?? '-')
    lines.push(<>จาก <code>{r.predecessor_event_id}</code> (ฉบับ {r.predecessor_revision_no}) → <code>{r.successor_event_id}</code> (ฉบับ {r.successor_revision_no})</>)
    lines.push(`เวลาส่งต่อตามกำหนด: ${formatE2Instant(r.handover_at)}`)
    if (r.unknown_start_at !== null && r.unknown_end_at !== null) {
      lines.push(`ช่วงที่ไม่แน่ชัด: ${formatE2Range(r.unknown_start_at, r.unknown_end_at)}`)
    }
  } else if (r.record_kind === 'CANCELLATION') {
    lines.push('ยกเลิกรายการ (รายการเดิมยังเก็บไว้ในประวัติ)')
  } else {
    if (r.assigned_driver_id !== null) {
      lines.push(<>ผู้ขับที่ได้รับมอบหมาย: <Link to={`/drivers/${encodeURIComponent(r.assigned_driver_id)}`}>{r.assigned_driver_id}</Link></>)
    }
    if (r.mode !== null) lines.push(`รูปแบบ: ${e2ModeLabel[r.mode] ?? r.mode}`)
    if (r.start_date !== null) lines.push(`วันที่: ${formatE2Date(r.start_date)} – ${formatE2Date(r.end_date)}`)
    const shift = formatE2Shift(r.shift_start_time, r.shift_end_time, r.shift_end_day_offset)
    if (shift !== null) lines.push(`เวลากะ: ${shift}`)
    if (r.excluded_dates.length > 0) lines.push(`วันที่ตัดออก: ${r.excluded_dates.map(formatE2Date).join(', ')}`)
    if (r.relation !== null) {
      lines.push(<>{e2RelationLabel[r.relation] ?? r.relation} <code>{r.related_event_id}</code></>)
    }
    if (r.early_end_at !== null) lines.push(`สิ้นสุดก่อนกำหนดเมื่อ: ${formatE2Instant(r.early_end_at)}`)
    if (r.voided) lines.push('ยกเลิกเพราะบันทึกผิด (ไม่มีช่วงเวลาที่มีผล)')
  }
  return (
    <ul className="e2-record-details">
      {lines.map((line, i) => <li key={i}>{line}</li>)}
    </ul>
  )
}
