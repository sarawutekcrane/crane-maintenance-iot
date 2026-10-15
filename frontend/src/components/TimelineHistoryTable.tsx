import type { ReactNode } from 'react'
import {
  effectivePrecisionLabel,
  formatRegistryInstant,
  timelineEntryLabel,
  timelineNoteLabel,
} from '../lib/labels'
import { sortPeriods, type ReadFailure, type TimelinePeriod } from '../lib/r2History'
import { ErrorState } from './ErrorState'
import { PermissionDeniedState } from './PermissionDeniedState'
import { ResponsiveTable } from './ResponsiveTable'

/**
 * R2 Batch R2-C2a — the read-only history of an effective-dated R2f timeline
 * (department, equipment caretaker, permanent responsible driver). Effective
 * time and recorded time are separate columns; a DATE-precision effective
 * time is shown as a date only (Asia/Bangkok). The reads return no reason
 * text, so no reason column is shown. Newest effective first.
 */
interface Props {
  events: readonly TimelinePeriod[]
  /** Column header of the period's id (แผนก / ช่าง / คนขับ). */
  targetHeader: string
  /** How a period's id is shown (exact id, optionally with a known name / link). */
  renderTarget?: (id: string) => ReactNode
  emptyTitle: string
  emptyDescription?: string
}

function stateText(e: TimelinePeriod): string {
  if (e.in_force) return 'มีผล'
  return e.notes.includes('CANCELLED') ? 'ยกเลิกแล้ว' : 'ไม่มีผล'
}

export function TimelineHistoryTable({ events, targetHeader, renderTarget, emptyTitle, emptyDescription }: Props) {
  return (
    <ResponsiveTable
      columns={[
        { key: 'entry', header: 'รายการ', render: (e: TimelinePeriod) => timelineEntryLabel[e.entry_operation] ?? e.entry_operation },
        {
          key: 'target',
          header: targetHeader,
          render: (e: TimelinePeriod) =>
            e.target_id === null ? '— (สิ้นสุด)' : renderTarget ? renderTarget(e.target_id) : <code>{e.target_id}</code>,
        },
        {
          key: 'effective',
          header: 'มีผลตั้งแต่ (เวลาไทย)',
          render: (e: TimelinePeriod) => (
            <span>
              {formatRegistryInstant(e.effective_at, e.effective_precision)}{' '}
              <small>({effectivePrecisionLabel[e.effective_precision] ?? e.effective_precision})</small>
            </span>
          ),
        },
        {
          key: 'end',
          header: 'สิ้นสุดเมื่อ',
          render: (e: TimelinePeriod) => (e.derived_end_at === null ? '-' : formatRegistryInstant(e.derived_end_at)),
        },
        { key: 'state', header: 'สถานะรายการ', render: (e: TimelinePeriod) => stateText(e) },
        { key: 'revision', header: 'ฉบับแก้ไข', render: (e: TimelinePeriod) => e.revision_no },
        { key: 'recorded_at', header: 'บันทึกเมื่อ', render: (e: TimelinePeriod) => formatRegistryInstant(e.recorded_at) },
        { key: 'recorded_by', header: 'ผู้บันทึก', render: (e: TimelinePeriod) => e.recorded_by },
        {
          key: 'notes',
          header: 'หมายเหตุระบบ',
          render: (e: TimelinePeriod) => (e.notes.length === 0 ? '-' : e.notes.map((n) => timelineNoteLabel[n] ?? n).join(', ')),
        },
      ]}
      rows={sortPeriods(events)}
      getRowKey={(e) => e.event_id}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
    />
  )
}

/** A failed R2 read: never shown as "no data". An id outside the server's
 * data scope (TEST/REAL) gets its own explanation — an expected, informational
 * state (role="status"), not an urgent alert: e.g. every REAL-scoped record
 * shows it while the server runs in the TEST context. */
export function R2ReadFailureView({ failure, title, onRetry }: { failure: ReadFailure; title: string; onRetry: () => void }) {
  if (failure.kind === 'forbidden') return <PermissionDeniedState message={failure.message} />
  if (failure.kind === 'scope') {
    return (
      <div className="form-field__hint" role="status" data-testid="r2-scope-unproven">
        <p>{failure.message}</p>
        <p className="state-panel__meta">ระบบแสดงเฉพาะข้อมูลในขอบเขตข้อมูลของเซิร์ฟเวอร์ (TEST/REAL) ที่พิสูจน์ได้เท่านั้น</p>
      </div>
    )
  }
  return <ErrorState title={title} message={failure.message} code={failure.code} requestId={failure.requestId} onRetry={onRetry} />
}
