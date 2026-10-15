import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCapabilities } from '../lib/capabilities'
import { CAN_ASSIGN_CRANE_DRIVER } from '../lib/capabilityNames'
import {
  formatRegistryInstant,
  R2_PANEL_TITLES,
  RESPONSIBLE_DRIVER_NOTE,
  timelineCurrentStatusLabel,
  timelineOperationLabel,
  timelineStatusLabel,
} from '../lib/labels'
import { parseDriverPage, parseResponsibleDrivers, useR2Read, type ResponsibilityTimeline } from '../lib/r2History'
import { useR2Writes } from '../lib/r2HistoryWrites'
import { Card } from './Card'
import { LoadingState } from './LoadingState'
import { TimelineEventDialog, R2WriteNotice, type TimelineOperation } from './TimelineEventDialog'
import { R2ReadFailureView, TimelineHistoryTable } from './TimelineHistoryTable'
import { V2ContextBanner } from './V2ContextBanner'

/**
 * R2 Batch R2-C2a — the R2f-f PERMANENT responsible driver of a vehicle: at
 * most one at a time, with its effective-dated history and — with
 * can_assign_crane_driver — the five operations. The driver is always chosen
 * or typed by the user (DQ-C2); the backend proves it (scope, ACTIVE, linked
 * personnel ACTIVE). Permanent responsibility is not proof of who drove the
 * vehicle and is not the R2-C2b day / shift assignment (DQ-C3): no E2 data is
 * read or shown here. The legacy Phase 6 driver page stays as it is.
 */
export function ResponsibleDriverPanel({ vehicleId }: { vehicleId: string }) {
  const { hasCapability, userId } = useCapabilities()
  const canWrite = hasCapability(CAN_ASSIGN_CRANE_DRIVER)
  const writes = useR2Writes(userId, 'responsibility', vehicleId)
  const { settle } = writes
  const onData = useCallback((data: ResponsibilityTimeline) => settle({ kind: 'timeline', events: data.events }), [settle])
  const [state, reload] = useR2Read(`/vehicles/${encodeURIComponent(vehicleId)}/responsible-drivers`, parseResponsibleDrivers, onData)
  const [drivers] = useR2Read('/drivers?page_size=200', parseDriverPage)
  const [dialog, setDialog] = useState<TimelineOperation | null>(null)

  const names = useMemo(() => {
    const map = new Map<string, string>()
    if (drivers.kind === 'ready') for (const d of drivers.data) map.set(d.driver_id, d.driver_name_th)
    return map
  }, [drivers])
  const options = drivers.kind === 'ready'
    ? drivers.data.map((d) => ({
      id: d.driver_id,
      label: `${d.driver_name_th} (${d.driver_id})${d.active_status === null ? '' : ` — ${d.active_status}`}`,
    }))
    : null

  const open = (operation: TimelineOperation) => {
    writes.setMessage(null)
    writes.setDialogError(null)
    setDialog(operation)
  }

  const submit = async (body: Record<string, unknown>) => {
    const result = await writes.submit(
      `/vehicles/${encodeURIComponent(vehicleId)}/responsible-driver-events`, String(body.operation), body, reload)
    if (result && result.kind !== 'refused' && result.kind !== 'blocked') setDialog(null)
  }

  const renderTarget = (id: string) => (
    <span>
      <Link to={`/drivers/${encodeURIComponent(id)}`}>{id}</Link>
      {names.get(id) ? ` ${names.get(id)}` : ''}
    </span>
  )

  const data = state.kind === 'ready' ? state.data : null
  const hasEvents = !!data && data.events.some((e) => e.in_force)
  const blocked = writes.intent !== null || writes.inFlight

  return (
    <Card className="r2-panel">
      <h2>{R2_PANEL_TITLES.responsibleDriver}</h2>
      <p className="form-field__hint" data-testid="responsible-driver-note">{RESPONSIBLE_DRIVER_NOTE}</p>
      <V2ContextBanner />
      <R2WriteNotice
        message={writes.message}
        intent={writes.intent}
        inFlight={writes.inFlight}
        onResend={() => void writes.resend(reload)}
        onReload={reload}
      />
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดผู้รับผิดชอบรถประจำ..." />}
      {state.kind === 'error' && (
        <R2ReadFailureView failure={state.failure} title="โหลดผู้รับผิดชอบรถประจำไม่สำเร็จ" onRetry={reload} />
      )}
      {data && (
        <div data-testid="responsible-driver-panel">
          <div className="status-card__row">
            <span>ผู้รับผิดชอบรถประจำปัจจุบัน</span>
            <span data-testid="responsible-driver-current">
              {data.current_id !== null ? renderTarget(data.current_id) : timelineCurrentStatusLabel[data.current_status]}
            </span>
          </div>
          {data.current_since !== null && (
            <div className="status-card__row">
              <span>ตั้งแต่</span>
              <span>{formatRegistryInstant(data.current_since)}</span>
            </div>
          )}
          {data.timeline_status !== 'VALID' && (
            <p className="form-field__error" role="alert">{timelineStatusLabel[data.timeline_status]}</p>
          )}
          {canWrite && !blocked && (
            <div className="dialog__actions" data-testid="responsible-driver-actions">
              <button type="button" className="button button--primary" onClick={() => open('TRANSFER')}>
                {data.current_id === null ? 'กำหนดผู้รับผิดชอบ' : 'เปลี่ยนผู้รับผิดชอบ'}
              </button>
              {data.current_id !== null && (
                <button type="button" className="button button--secondary" onClick={() => open('END')}>สิ้นสุดความรับผิดชอบ</button>
              )}
              {hasEvents && (
                <>
                  <button type="button" className="button button--secondary" onClick={() => open('INSERTION')}>
                    {timelineOperationLabel.INSERTION}
                  </button>
                  <button type="button" className="button button--secondary" onClick={() => open('CORRECTION')}>
                    {timelineOperationLabel.CORRECTION}
                  </button>
                  <button type="button" className="button button--secondary" onClick={() => open('CANCELLATION')}>
                    {timelineOperationLabel.CANCELLATION}
                  </button>
                </>
              )}
            </div>
          )}
          <TimelineHistoryTable
            events={data.events}
            targetHeader="คนขับ/ผู้ควบคุม"
            renderTarget={renderTarget}
            emptyTitle="ยังไม่มีประวัติผู้รับผิดชอบรถประจำ"
            emptyDescription="ยังไม่เคยกำหนดผู้รับผิดชอบรถประจำของรถคันนี้ผ่านระบบ"
          />
          {dialog && (
            <TimelineEventDialog
              operation={dialog}
              targetField="driver_id"
              targetName="คนขับ/ผู้ควบคุม"
              currentId={data.current_id}
              events={data.events}
              options={options}
              submitting={writes.inFlight}
              error={writes.dialogError}
              onCancel={() => setDialog(null)}
              onSubmit={(body) => void submit(body)}
            />
          )}
        </div>
      )}
    </Card>
  )
}
