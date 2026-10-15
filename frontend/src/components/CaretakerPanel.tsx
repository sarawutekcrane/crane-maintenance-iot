import { useCallback, useMemo, useState } from 'react'
import { useCapabilities } from '../lib/capabilities'
import { CAN_ASSIGN_EQUIPMENT_CARETAKER } from '../lib/capabilityNames'
import { formatRegistryInstant, R2_PANEL_TITLES, timelineCurrentStatusLabel, timelineOperationLabel, timelineStatusLabel } from '../lib/labels'
import {
  parseCaretakers,
  parseTechnicianPage,
  technicianName,
  useR2Read,
  type CaretakerTimeline,
} from '../lib/r2History'
import { useR2Writes } from '../lib/r2HistoryWrites'
import { Card } from './Card'
import { LoadingState } from './LoadingState'
import { TimelineEventDialog, R2WriteNotice, type TimelineOperation } from './TimelineEventDialog'
import { R2ReadFailureView, TimelineHistoryTable } from './TimelineHistoryTable'
import { V2ContextBanner } from './V2ContextBanner'

/**
 * R2 Batch R2-C2a — the R2f-d equipment caretaker: the current caretaker
 * (technician), its effective-dated history, and — with
 * can_assign_equipment_caretaker — TRANSFER (also the first assignment),
 * backdated INSERTION, END, CORRECTION and CANCELLATION. The caretaker is
 * always chosen by the user, never taken from the signed-in user; the
 * equipment master is never written. Outside the server's data scope the
 * read answers EQUIPMENT_SCOPE_UNPROVEN and nothing can be recorded.
 */
export function CaretakerPanel({ equipmentId }: { equipmentId: string }) {
  const { hasCapability, userId } = useCapabilities()
  const canWrite = hasCapability(CAN_ASSIGN_EQUIPMENT_CARETAKER)
  const writes = useR2Writes(userId, 'caretaker', equipmentId)
  const { settle } = writes
  const onData = useCallback((data: CaretakerTimeline) => settle({ kind: 'timeline', events: data.events }), [settle])
  const [state, reload] = useR2Read(`/equipment/${encodeURIComponent(equipmentId)}/caretakers`, parseCaretakers, onData)
  const [technicians] = useR2Read('/technicians?page_size=200', parseTechnicianPage)
  const [dialog, setDialog] = useState<TimelineOperation | null>(null)

  const names = useMemo(() => {
    const map = new Map<string, string>()
    if (technicians.kind === 'ready') for (const t of technicians.data) map.set(t.technician_id, technicianName(t) ?? t.technician_id)
    return map
  }, [technicians])
  const options = technicians.kind === 'ready'
    ? technicians.data.map((t) => ({
      id: t.technician_id,
      label: `${technicianName(t) ?? '(ไม่มีชื่อ)'} (${t.technician_id})${t.active_status === 'ACTIVE' ? '' : ' (ไม่อยู่ในสถานะใช้งาน)'}`,
    }))
    : null

  const open = (operation: TimelineOperation) => {
    writes.setMessage(null)
    writes.setDialogError(null)
    setDialog(operation)
  }

  const submit = async (body: Record<string, unknown>) => {
    const result = await writes.submit(
      `/equipment/${encodeURIComponent(equipmentId)}/caretaker-events`, String(body.operation), body, reload)
    if (result && result.kind !== 'refused' && result.kind !== 'blocked') setDialog(null)
  }

  const renderTarget = (id: string) => (
    <span>
      <code>{id}</code>
      {names.get(id) ? ` ${names.get(id)}` : ''}
    </span>
  )

  const data = state.kind === 'ready' ? state.data : null
  const hasEvents = !!data && data.events.some((e) => e.in_force)
  const blocked = writes.intent !== null || writes.inFlight

  return (
    <Card className="r2-panel">
      <h2>{R2_PANEL_TITLES.caretaker}</h2>
      <V2ContextBanner />
      <R2WriteNotice
        message={writes.message}
        intent={writes.intent}
        inFlight={writes.inFlight}
        onResend={() => void writes.resend(reload)}
        onReload={reload}
      />
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูลผู้ดูแลอุปกรณ์..." />}
      {state.kind === 'error' && (
        <R2ReadFailureView failure={state.failure} title="โหลดข้อมูลผู้ดูแลอุปกรณ์ไม่สำเร็จ" onRetry={reload} />
      )}
      {data && (
        <div data-testid="caretaker-panel">
          <div className="status-card__row">
            <span>ผู้ดูแลปัจจุบัน</span>
            <span data-testid="caretaker-current">
              {data.current_id !== null ? (
                <span>
                  <code>{data.current_id}</code> {technicianName(data.current_technician) ?? names.get(data.current_id) ?? ''}
                </span>
              ) : (
                timelineCurrentStatusLabel[data.current_status]
              )}
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
            <div className="dialog__actions" data-testid="caretaker-actions">
              <button type="button" className="button button--primary" onClick={() => open('TRANSFER')}>
                {data.current_id === null ? 'กำหนดผู้ดูแล' : 'เปลี่ยนผู้ดูแล'}
              </button>
              {data.current_id !== null && (
                <button type="button" className="button button--secondary" onClick={() => open('END')}>สิ้นสุดการดูแล</button>
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
            targetHeader="ช่างผู้ดูแล"
            renderTarget={renderTarget}
            emptyTitle="ยังไม่มีประวัติผู้ดูแลอุปกรณ์"
            emptyDescription="ยังไม่เคยกำหนดผู้ดูแลอุปกรณ์นี้ผ่านระบบ"
          />
          {dialog && (
            <TimelineEventDialog
              operation={dialog}
              targetField="technician_id"
              targetName="ช่าง"
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
