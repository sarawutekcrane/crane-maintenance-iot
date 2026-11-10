import { useState } from 'react'
import type { WorkBreakPeriod, WorkTimeClass, WorkTimeEntry } from '../lib/types'
import { FormField } from './FormField'

/** Values the dialog submits (ISO instants with the Asia/Bangkok offset). */
export interface WorkTimeEntryInput {
  started_at: string
  ended_at: string
  time_class: WorkTimeClass
  description: string
  /** Always present: `[]` means the technician explicitly declared "no break". */
  breaks: WorkBreakPeriod[]
  reason: string | null
}

interface WorkTimeEntryDialogProps {
  open: boolean
  /** CREATE = the technician's own new period; CORRECT = a new revision of `entry`. */
  mode: 'CREATE' | 'CORRECT'
  entry?: WorkTimeEntry | null
  submitting: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (input: WorkTimeEntryInput) => void
}

interface BreakRow {
  start: string
  end: string
}

const BANGKOK_OFFSET = '+07:00'

/** `YYYY-MM-DDTHH:mm` typed as Asia/Bangkok wall-clock time → ISO with offset. */
function toInstant(local: string): string {
  return `${local}:00${BANGKOK_OFFSET}`
}

/** ISO instant → `YYYY-MM-DDTHH:mm` in Asia/Bangkok for a datetime-local input. */
function toLocalInput(iso: string): string {
  const shifted = new Date(new Date(iso).getTime() + 7 * 3600 * 1000)
  return shifted.toISOString().slice(0, 16)
}

/**
 * R5 — record or correct ONE technician work period (Roadmap RM-6, RM-10).
 * The break declaration is explicit and has no default: the technician must
 * choose "ไม่มีพัก" or "มีพัก" (and then list each break). Times are entered in
 * Asia/Bangkok; a period may cross midnight and has no maximum length. A
 * correction always needs a reason. The server re-validates everything.
 */
export function WorkTimeEntryDialog({ open, mode, entry, submitting, error, onCancel, onSubmit }: WorkTimeEntryDialogProps) {
  const [start, setStart] = useState(entry ? toLocalInput(entry.started_at) : '')
  const [end, setEnd] = useState(entry ? toLocalInput(entry.ended_at) : '')
  const [timeClass, setTimeClass] = useState<WorkTimeClass>(entry?.time_class ?? 'REGULAR')
  const [description, setDescription] = useState(entry?.description ?? '')
  const [breakChoice, setBreakChoice] = useState<'NONE' | 'SOME' | null>(
    entry ? (entry.breaks.length ? 'SOME' : 'NONE') : null,
  )
  const [breaks, setBreaks] = useState<BreakRow[]>(
    entry ? entry.breaks.map((b) => ({ start: toLocalInput(b.started_at), end: toLocalInput(b.ended_at) })) : [],
  )
  const [reason, setReason] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  if (!open) return null

  const crossesMidnight = start !== '' && end !== '' && start.slice(0, 10) !== end.slice(0, 10)

  const submit = () => {
    if (!start || !end) return setLocalError('กรุณาระบุเวลาเริ่มและเวลาสิ้นสุด')
    if (end <= start) return setLocalError('เวลาสิ้นสุดต้องหลังเวลาเริ่ม')
    if (!description.trim()) return setLocalError('กรุณาระบุรายละเอียดงานที่ทำ')
    if (breakChoice === null) return setLocalError('กรุณาเลือกว่ามีช่วงพักหรือไม่')
    if (breakChoice === 'SOME' && (breaks.length === 0 || breaks.some((b) => !b.start || !b.end || b.end <= b.start)))
      return setLocalError('กรุณาระบุช่วงพักให้ครบและถูกต้อง')
    if (mode === 'CORRECT' && !reason.trim()) return setLocalError('การแก้ไขต้องระบุเหตุผล')
    setLocalError(null)
    onSubmit({
      started_at: toInstant(start),
      ended_at: toInstant(end),
      time_class: timeClass,
      description: description.trim(),
      breaks: breakChoice === 'SOME' ? breaks.map((b) => ({ started_at: toInstant(b.start), ended_at: toInstant(b.end) })) : [],
      reason: mode === 'CORRECT' ? reason.trim() : null,
    })
  }

  const shownError = localError ?? error

  return (
    <div className="dialog-overlay" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="work-time-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="work-time-dialog-title">{mode === 'CREATE' ? 'บันทึกเวลาทำงานของฉัน' : 'แก้ไขเวลาทำงาน'}</h2>
        <p className="form-field__hint">เวลาเป็นเวลาประเทศไทย บันทึกเฉพาะเวลาที่ทำงานจริง ระบบไม่คิดเวลา 8 ชั่วโมงหรือล่วงเวลาให้อัตโนมัติ</p>
        <div className="form-grid">
          <FormField label="เริ่มทำงาน" htmlFor="wt-start">
            <input id="wt-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          </FormField>
          <FormField label="สิ้นสุด" htmlFor="wt-end">
            <input id="wt-end" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
          </FormField>
          {crossesMidnight && (
            <p className="form-field__hint" data-testid="wt-crosses-midnight">ช่วงเวลานี้ข้ามเที่ยงคืน (นับวันทำงานทั้งสองวัน)</p>
          )}
          <FormField label="ประเภทเวลา" htmlFor="wt-class">
            <select id="wt-class" value={timeClass} onChange={(e) => setTimeClass(e.target.value as WorkTimeClass)}>
              <option value="REGULAR">เวลาปกติ</option>
              <option value="OVERTIME">ล่วงเวลา (OT)</option>
            </select>
          </FormField>
          <FormField label="รายละเอียดงานที่ทำ" htmlFor="wt-description">
            <textarea id="wt-description" value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)} />
          </FormField>
          <fieldset className="form-field">
            <legend>ช่วงพัก</legend>
            <label>
              <input type="radio" name="wt-breaks" checked={breakChoice === 'NONE'} onChange={() => setBreakChoice('NONE')} />
              ไม่มีพัก
            </label>
            <label>
              <input
                type="radio"
                name="wt-breaks"
                checked={breakChoice === 'SOME'}
                onChange={() => {
                  setBreakChoice('SOME')
                  if (breaks.length === 0) setBreaks([{ start: '', end: '' }])
                }}
              />
              มีพัก
            </label>
            {breakChoice === 'SOME' &&
              breaks.map((row, index) => (
                <div key={index} className="form-grid" data-testid="wt-break-row">
                  <FormField label={`พักครั้งที่ ${index + 1} เริ่ม`} htmlFor={`wt-break-start-${index}`}>
                    <input
                      id={`wt-break-start-${index}`}
                      type="datetime-local"
                      value={row.start}
                      onChange={(e) => setBreaks((all) => all.map((b, i) => (i === index ? { ...b, start: e.target.value } : b)))}
                    />
                  </FormField>
                  <FormField label={`พักครั้งที่ ${index + 1} สิ้นสุด`} htmlFor={`wt-break-end-${index}`}>
                    <input
                      id={`wt-break-end-${index}`}
                      type="datetime-local"
                      value={row.end}
                      onChange={(e) => setBreaks((all) => all.map((b, i) => (i === index ? { ...b, end: e.target.value } : b)))}
                    />
                  </FormField>
                  <button type="button" className="button button--secondary" onClick={() => setBreaks((all) => all.filter((_, i) => i !== index))}>
                    ลบช่วงพักนี้
                  </button>
                </div>
              ))}
            {breakChoice === 'SOME' && (
              <button type="button" className="button button--secondary" onClick={() => setBreaks((all) => [...all, { start: '', end: '' }])}>
                เพิ่มช่วงพัก
              </button>
            )}
          </fieldset>
          {mode === 'CORRECT' && (
            <FormField label="เหตุผลการแก้ไข" htmlFor="wt-reason">
              <textarea id="wt-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
            </FormField>
          )}
        </div>
        {shownError && (
          <p className="form-field__error" role="alert">
            {shownError}
          </p>
        )}
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>
            ยกเลิก
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : 'บันทึก'}
          </button>
        </div>
      </div>
    </div>
  )
}
