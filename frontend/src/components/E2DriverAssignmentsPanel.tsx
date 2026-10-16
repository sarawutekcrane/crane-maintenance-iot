import { useState } from 'react'
import { Link } from 'react-router-dom'
import { defaultE2Window, driverSchedulePath, parseDriverSchedule, validateE2Filter, type E2Filter } from '../lib/e2Assignments'
import { E2_NOTE, E2_PANEL_TITLES, e2TimelineStatusLabel } from '../lib/labels'
import { useR2Read } from '../lib/r2History'
import { Card } from './Card'
import { E2Conflicts, E2FilterBar, E2IntervalTable, E2ReadFailureView, E2UnavailableView, E2Warnings } from './E2VehicleAssignmentsPanel'
import { LoadingState } from './LoadingState'

/**
 * R2 Batch R2-C2b — READ ONLY: the E2 operational assignments of one driver
 * across vehicles in a date / mode window, with conflicts and warnings, and a
 * link to each vehicle (writes happen on Vehicle Detail only, the backend's
 * only write route). Separate from the R2f-f "vehicles under permanent
 * responsibility" panel and from the legacy Phase 6 data. An assignment is
 * not proof of actual driving.
 */
export function E2DriverAssignmentsPanel({ driverId }: { driverId: string }) {
  const [draft, setDraft] = useState<E2Filter>(() => ({ ...defaultE2Window(), mode: '' }))
  const [filter, setFilter] = useState<E2Filter>(draft)
  const [filterError, setFilterError] = useState<string | null>(null)
  const [state, reload] = useR2Read(driverSchedulePath(driverId, filter), parseDriverSchedule)

  const applyFilter = () => {
    const error = validateE2Filter(draft)
    setFilterError(error)
    if (error === null) setFilter({ ...draft })
  }

  const unavailable = state.kind === 'error' && state.failure.status === 501

  return (
    <Card className="r2-panel e2-panel">
      <h2>{E2_PANEL_TITLES.driver}</h2>
      <p className="form-field__hint" data-testid="e2-note">{E2_NOTE}</p>
      <p className="form-field__hint">แสดงอย่างเดียว บันทึกหรือแก้ไขได้ที่หน้ารายละเอียดรถแต่ละคัน</p>
      {unavailable ? (
        <E2UnavailableView />
      ) : (
        <>
          <E2FilterBar draft={draft} setDraft={setDraft} onApply={applyFilter} error={filterError} idPrefix="e2-driver" />
          {state.kind === 'loading' && <LoadingState message="กำลังโหลดการมอบหมายขับรถตามวัน/กะ..." />}
          {state.kind === 'error' && (
            <E2ReadFailureView failure={state.failure} title="โหลดการมอบหมายขับรถตามวัน/กะไม่สำเร็จ" onRetry={reload} />
          )}
          {state.kind === 'ready' && (
            <div data-testid="e2-driver-schedule">
              {state.data.timeline_status !== 'VALID' && (
                <p className="form-field__error" role="alert" data-testid="e2-timeline-conflicted">
                  {e2TimelineStatusLabel[state.data.timeline_status]} — ระบบไม่เดาให้ ต้องแก้ไขโดยผู้มีสิทธิ์ที่หน้ารถ
                </p>
              )}
              <E2Warnings warnings={state.data.warnings} />
              <E2Conflicts conflicts={state.data.conflicts} />
              <E2IntervalTable
                intervals={state.data.intervals}
                targetHeader="รถ"
                renderTarget={(i) => <Link to={`/vehicle/${encodeURIComponent(i.vehicle_id)}`}>{i.vehicle_id}</Link>}
                emptyTitle="ไม่มีการมอบหมายขับรถในช่วงที่เลือก"
              />
            </div>
          )}
        </>
      )}
    </Card>
  )
}
