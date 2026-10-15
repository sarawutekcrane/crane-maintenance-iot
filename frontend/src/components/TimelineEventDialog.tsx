import { useMemo, useState } from 'react'
import { bangkokDateTimeToIso, bangkokWallClock } from '../lib/branchEffectiveTime'
import { formatRegistryInstant, timelineOperationLabel } from '../lib/labels'
import { sortPeriods, type TimelinePeriod } from '../lib/r2History'
import { CONFLICT_ESCALATION, type R2Intent, type R2Message } from '../lib/r2HistoryWrites'
import { FormField } from './FormField'

/**
 * R2 Batch R2-C2a — one dialog for the five effective-dated operations of the
 * R2f-d equipment caretaker and the R2f-f permanent responsible driver:
 * TRANSFER (the first assignment is also a TRANSFER), INSERTION (backdated),
 * END, CORRECTION and CANCELLATION. The body follows the backend schema
 * exactly; the expected current id (and, for revisions, the expected revision
 * number) come from the timeline the panel last read, and the server re-checks
 * them (stale → reload). The target id is always chosen or typed by the user:
 * nothing is pre-selected or inferred (never the signed-in user).
 *
 * Effective time: "ตอนนี้" only for TRANSFER / END; a Bangkok date (00:00);
 * or a Bangkok date and time sent with the explicit +07:00 offset.
 */
export type TimelineOperation = 'TRANSFER' | 'INSERTION' | 'END' | 'CORRECTION' | 'CANCELLATION'
type EffectiveMode = 'NOW' | 'DATE' | 'DATETIME'

export interface TargetOption {
  id: string
  label: string
}

interface Props {
  operation: TimelineOperation
  /** technician_id / driver_id */
  targetField: 'technician_id' | 'driver_id'
  /** "ช่าง" / "คนขับ/ผู้ควบคุม" */
  targetName: string
  /** The current id of the last successful read (the expected current value). */
  currentId: string | null
  events: readonly TimelinePeriod[]
  /** Choices for the target; null = not loaded, so the id is typed instead. */
  options: readonly TargetOption[] | null
  submitting: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (body: Record<string, unknown>) => void
}

const ALLOW_NOW: readonly TimelineOperation[] = ['TRANSFER', 'END']
const REASON_REQUIRED: readonly TimelineOperation[] = ['INSERTION', 'CORRECTION', 'CANCELLATION']

export function TimelineEventDialog({
  operation, targetField, targetName, currentId, events, options, submitting, error, onCancel, onSubmit,
}: Props) {
  const revisable = useMemo(() => sortPeriods(events.filter((e) => e.in_force)), [events])
  const needsEvent = operation === 'CORRECTION' || operation === 'CANCELLATION'
  const allowNow = ALLOW_NOW.includes(operation)
  const needsReason = REASON_REQUIRED.includes(operation)

  const [eventId, setEventId] = useState('')
  const [target, setTarget] = useState('')
  const [mode, setMode] = useState<EffectiveMode>(allowNow ? 'NOW' : 'DATE')
  const [date, setDate] = useState('')
  const [dateTime, setDateTime] = useState('')
  const [reason, setReason] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const selected = revisable.find((e) => e.event_id === eventId) ?? null
  // A correction of an END event keeps it an END: no target may be sent.
  const needsTarget = operation === 'TRANSFER' || operation === 'INSERTION'
    || (operation === 'CORRECTION' && selected !== null && selected.target_id !== null)
  const needsEffective = operation !== 'CANCELLATION'

  const chooseEvent = (id: string) => {
    setEventId(id)
    const event = revisable.find((e) => e.event_id === id)
    if (operation !== 'CORRECTION' || !event) return
    // Prefill the correction with the event as it is now.
    setTarget(event.target_id ?? '')
    const wall = bangkokWallClock(event.effective_at)
    if (event.effective_precision === 'DATE') {
      setMode('DATE')
      setDate(wall.slice(0, 10))
    } else {
      setMode('DATETIME')
      setDateTime(wall)
    }
  }

  const effective = (): Record<string, string> | null => {
    if (mode === 'NOW') return allowNow ? { mode: 'NOW' } : null
    if (mode === 'DATE') return date ? { mode: 'DATE', date } : null
    // Whole seconds only (the backend refuses fractions): a zero fraction some
    // browsers report (".000") is dropped; any other fraction is sent and refused.
    return dateTime ? { mode: 'DATETIME', at: bangkokDateTimeToIso(dateTime.replace(/\.0+$/, '')) } : null
  }

  const submit = () => {
    if (needsEvent && !selected) return setLocalError('กรุณาเลือกรายการในประวัติ')
    if (needsTarget && target.trim() === '') return setLocalError(`กรุณาเลือกหรือระบุรหัส${targetName}`)
    const when = needsEffective ? effective() : null
    if (needsEffective && when === null) return setLocalError('กรุณาระบุเวลาที่มีผล')
    if (needsReason && reason.trim() === '') return setLocalError('กรุณาระบุเหตุผล')
    setLocalError(null)
    const expected = { [`expected_current_${targetField}`]: currentId }
    const body: Record<string, unknown> = { operation }
    if (needsEvent && selected) {
      body.event_id = selected.event_id
      body.expected_revision_no = selected.revision_no
    }
    if (needsTarget) body[targetField] = target
    if (needsEffective) body.effective = when
    Object.assign(body, expected)
    if (reason !== '') body.reason_th = reason
    onSubmit(body)
  }

  const titleId = `timeline-${operation}-title`
  return (
    <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="timeline-event-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{timelineOperationLabel[operation]}</h2>
        <div className="status-card__row">
          <span>{targetName}ปัจจุบันตามประวัติ</span>
          <span>{currentId === null ? 'ไม่มี' : <code>{currentId}</code>}</span>
        </div>
        {operation === 'CANCELLATION' && (
          <p className="form-field__error" role="note">
            การยกเลิกจะถูกบันทึกเป็นรายการใหม่ในประวัติ รายการเดิมยังคงอยู่และแสดงว่า "ยกเลิกแล้ว"
          </p>
        )}
        <div className="form-grid">
          {needsEvent && (
            <FormField label="รายการในประวัติ" htmlFor="timeline-event-select">
              <select id="timeline-event-select" value={eventId} onChange={(e) => chooseEvent(e.target.value)} disabled={submitting}>
                <option value="">เลือกรายการ</option>
                {revisable.map((e) => (
                  <option key={e.event_id} value={e.event_id}>
                    {formatRegistryInstant(e.effective_at, e.effective_precision)} → {e.target_id ?? 'สิ้นสุด'} (ฉบับ {e.revision_no})
                  </option>
                ))}
              </select>
            </FormField>
          )}
          {needsTarget && (
            <FormField
              label={`รหัส${targetName}`}
              htmlFor="timeline-target"
              hint="ต้องเลือกหรือระบุเอง ระบบไม่เลือกให้ และระบบหลังบ้านจะตรวจสอบสถานะและขอบเขตข้อมูลอีกครั้ง"
            >
              {options !== null ? (
                <select id="timeline-target" value={target} onChange={(e) => setTarget(e.target.value)} disabled={submitting}>
                  <option value="">{`เลือก${targetName}`}</option>
                  {options.map((o) => (
                    <option key={o.id} value={o.id}>{o.label}</option>
                  ))}
                </select>
              ) : (
                <input id="timeline-target" type="text" value={target} onChange={(e) => setTarget(e.target.value)} disabled={submitting} />
              )}
            </FormField>
          )}
          {needsEffective && (
            <fieldset className="form-grid">
              <legend>มีผลตั้งแต่ (เวลาประเทศไทย)</legend>
              {allowNow && (
                <label>
                  <input type="radio" name="timeline-effective-mode" checked={mode === 'NOW'} onChange={() => setMode('NOW')} disabled={submitting} />{' '}
                  ตอนนี้
                </label>
              )}
              <label>
                <input type="radio" name="timeline-effective-mode" checked={mode === 'DATE'} onChange={() => setMode('DATE')} disabled={submitting} />{' '}
                ระบุวันที่
              </label>
              <label>
                <input type="radio" name="timeline-effective-mode" checked={mode === 'DATETIME'} onChange={() => setMode('DATETIME')} disabled={submitting} />{' '}
                ระบุวันที่และเวลา
              </label>
              {mode === 'DATE' && (
                <FormField label="วันที่มีผล" htmlFor="timeline-effective-date">
                  <input id="timeline-effective-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} disabled={submitting} />
                </FormField>
              )}
              {mode === 'DATETIME' && (
                <FormField label="วันที่และเวลาที่มีผล" htmlFor="timeline-effective-datetime">
                  <input
                    id="timeline-effective-datetime"
                    type="datetime-local"
                    step={1}
                    value={dateTime}
                    onChange={(e) => setDateTime(e.target.value)}
                    disabled={submitting}
                  />
                </FormField>
              )}
            </fieldset>
          )}
          <FormField
            label={needsReason ? 'เหตุผล (บังคับ)' : 'เหตุผล (ไม่บังคับ)'}
            htmlFor="timeline-reason"
            error={localError ?? error ?? undefined}
          >
            <textarea id="timeline-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} disabled={submitting} />
          </FormField>
        </div>
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>
            ปิด
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : `ยืนยัน${timelineOperationLabel[operation]}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared write-outcome UI of the R2 history panels
// ---------------------------------------------------------------------------

const STATE_TEXT: Record<string, string> = {
  SUBMITTING: 'กำลังส่งคำขอ',
  UNKNOWN: 'ยังไม่ทราบผล',
  CONFLICT: 'รหัสคำขอขัดแย้ง',
  RECORDED: 'บันทึกประวัติแล้ว รอตรวจสอบข้อมูลปัจจุบัน',
}

/** The message line and the pending-intent banner of a write panel. */
export function R2WriteNotice({
  message, intent, inFlight, onResend, onReload,
}: {
  message: R2Message | null
  intent: R2Intent | 'corrupt' | null
  inFlight: boolean
  onResend: () => void
  onReload: () => void
}) {
  return (
    <>
      {message && (
        <div className={message.tone === 'success' ? 'form-field__hint' : 'form-field__error'} role="alert" data-testid="r2-write-message">
          <p>{message.text}</p>
          {message.requestId && <p className="state-panel__meta">รหัสคำขอ: {message.requestId}</p>}
          {message.reload && (
            <button type="button" className="button button--secondary" onClick={onReload}>
              โหลดข้อมูลล่าสุด
            </button>
          )}
        </div>
      )}
      {intent === 'corrupt' && (
        <div className="form-field__error" role="status" data-testid="r2-pending-intent">
          <p>พบรายการคำขอค้างที่อ่านไม่ได้ในเบราว์เซอร์นี้ จึงยังไม่บันทึกรายการใหม่ กรุณาติดต่อผู้ดูแลระบบ</p>
        </div>
      )}
      {intent !== null && intent !== 'corrupt' && (
        <div className="form-field__error" role="status" data-testid="r2-pending-intent">
          <p>
            มีคำขอที่ค้างอยู่ ({intent.operation}) — {inFlight ? STATE_TEXT.SUBMITTING : STATE_TEXT[intent.state]}
          </p>
          <p className="state-panel__meta">รหัสคำขอ: {intent.request_id}</p>
          {intent.state === 'CONFLICT' && <p data-testid="r2-conflict-escalation">{CONFLICT_ESCALATION}</p>}
          <div className="dialog__actions">
            {intent.state === 'UNKNOWN' && !inFlight && (
              <button type="button" className="button button--secondary" onClick={onResend}>
                ส่งคำขอเดิมอีกครั้ง
              </button>
            )}
            <button type="button" className="button button--secondary" onClick={onReload} disabled={inFlight}>
              โหลดข้อมูลล่าสุดเพื่อตรวจสอบ
            </button>
          </div>
        </div>
      )}
    </>
  )
}
