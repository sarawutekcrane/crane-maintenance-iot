import { formatRegistryInstant, R2_PANEL_TITLES, timelineStatusLabel } from '../lib/labels'
import { parseDepartmentHistory, useR2Read } from '../lib/r2History'
import { Card } from './Card'
import { LoadingState } from './LoadingState'
import { R2ReadFailureView, TimelineHistoryTable } from './TimelineHistoryTable'

const CURRENT_LABEL: Record<string, string> = {
  EVENT: 'มีข้อมูลการสังกัด',
  NONE: 'ยังไม่มีประวัติการสังกัดแผนก',
  UNDETERMINED: 'ระบุแผนกปัจจุบันไม่ได้ (มีรายการเวลาเดียวกัน)',
}

/**
 * R2 Batch R2-C2a — the R2f-g personnel department history, READ-ONLY.
 * Department ids are shown exactly as returned: the department master is
 * operational-only, so no department detail is read and no name or link is
 * invented for an id (a TEST id has no department page). No move / transfer
 * control exists here (no role holds the department-move capability).
 */
export function DepartmentHistoryPanel({ personnelId }: { personnelId: string }) {
  const [state, reload] = useR2Read(`/personnel/${encodeURIComponent(personnelId)}/department-history`, parseDepartmentHistory)
  return (
    <Card className="r2-panel">
      <h2>{R2_PANEL_TITLES.departmentHistory}</h2>
      <p className="form-field__hint">แสดงรหัสแผนกตามที่บันทึกในประวัติ (อ่านอย่างเดียว)</p>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติการสังกัดแผนก..." />}
      {state.kind === 'error' && (
        <R2ReadFailureView failure={state.failure} title="โหลดประวัติการสังกัดแผนกไม่สำเร็จ" onRetry={reload} />
      )}
      {state.kind === 'ready' && (
        <div data-testid="department-history">
          <div className="status-card__row">
            <span>แผนกปัจจุบัน</span>
            <span>
              {state.data.current_department_id !== null
                ? <code>{state.data.current_department_id}</code>
                : CURRENT_LABEL[state.data.current_status]}
            </span>
          </div>
          {state.data.current_since !== null && (
            <div className="status-card__row">
              <span>ตั้งแต่</span>
              <span>{formatRegistryInstant(state.data.current_since)}</span>
            </div>
          )}
          {state.data.timeline_status !== 'VALID' && (
            <p className="form-field__error" role="alert">{timelineStatusLabel[state.data.timeline_status]}</p>
          )}
          <TimelineHistoryTable
            events={state.data.events}
            targetHeader="รหัสแผนก"
            emptyTitle="ยังไม่มีประวัติการสังกัดแผนก"
            emptyDescription="ยังไม่มีการบันทึกการสังกัดแผนกของบุคลากรนี้"
          />
        </div>
      )}
    </Card>
  )
}
