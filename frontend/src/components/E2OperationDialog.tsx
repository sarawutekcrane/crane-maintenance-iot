import { useState } from 'react'
import {
  E2_MAX_REASON_LENGTH,
  E2_MODES,
  E2_SHIFT_MODES,
  formatE2Date,
  formatE2Shift,
  formatE2Span,
  isIsoDate,
  type E2AssignmentState,
  type E2Mode,
  type E2Operation,
} from '../lib/e2Assignments'
import {
  buildE2Body,
  E2_CONFLICT_ESCALATION,
  emptyE2Form,
  formFromState,
  type E2Form,
  type E2Intent,
  type E2Message,
  type E2OverlapDetails,
} from '../lib/e2Writes'
import { e2ModeLabel, e2OperationLabel, e2ReviseVariantLabel, e2WarningLabel } from '../lib/labels'
import { FormField } from './FormField'

/**
 * R2 Batch R2-C2b — the dialog of the five E2 operations and every variant the
 * backend contract accepts (`operational_driver_assignment_schemas.py`):
 * - CREATE: explicit driver, mode, inclusive dates, explicit applied shift
 *   times for a shift mode (no defaults), optional H2 / H3 handover from an
 *   existing assignment, a reason for a past start;
 * - REVISE: full-state correction / extension, shift-time split from a date,
 *   removal of erroneous units (`exclude_dates`) or `void_elapsed`;
 * - SUBSTITUTE: whole days / whole shifts, by labelled date, to another driver;
 * - CANCEL (before the start) and EARLY_END (now / after a date).
 * The backend stays authoritative for every rule (eligibility, conflicts on
 * both axes, start / end restrictions, handover conditions); the dialog checks
 * only that the required inputs are present and well-formed.
 */

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

const isShift = (mode: E2Mode | '') => mode !== '' && E2_SHIFT_MODES.includes(mode)
const uniqueSorted = (dates: readonly string[]) => [...new Set(dates)].sort()

interface Option { id: string; label: string }

interface Props {
  operation: E2Operation
  target: E2AssignmentState | null
  /** The vehicle's assignments (CREATE handover: an ACTIVE predecessor). */
  assignments: readonly E2AssignmentState[]
  driverOptions: readonly Option[] | null
  today: string
  submitting: boolean
  error: { text: string; overlap: E2OverlapDetails | null } | null
  onCancel: () => void
  onSubmit: (body: Record<string, unknown>) => void
}

function DateList({ id, label, values, onChange, disabled }: {
  id: string; label: string; values: string[]; onChange: (next: string[]) => void; disabled: boolean
}) {
  const [draft, setDraft] = useState('')
  return (
    <FormField label={label} htmlFor={id} hint="เพิ่มทีละวัน (วันที่ตามปฏิทินไทย กะกลางคืนใช้วันที่เริ่มกะ)">
      <div className="e2-date-list">
        <input id={id} type="date" value={draft} onChange={(e) => setDraft(e.target.value)} disabled={disabled} />
        <button
          type="button"
          className="button button--secondary"
          disabled={disabled || !isIsoDate(draft) || values.includes(draft)}
          onClick={() => {
            onChange(uniqueSorted([...values, draft]))
            setDraft('')
          }}
        >
          เพิ่มวันที่
        </button>
      </div>
      {values.length > 0 && (
        <ul className="e2-date-chips" data-testid={`${id}-values`}>
          {values.map((d) => (
            <li key={d}>
              {formatE2Date(d)}{' '}
              <button type="button" className="button button--secondary" disabled={disabled} aria-label={`ลบ ${d}`}
                onClick={() => onChange(values.filter((v) => v !== d))}>
                ลบ
              </button>
            </li>
          ))}
        </ul>
      )}
    </FormField>
  )
}

function DriverField({ id, label, value, onChange, options, disabled }: {
  id: string; label: string; value: string; onChange: (v: string) => void; options: readonly Option[] | null; disabled: boolean
}) {
  return (
    <FormField label={label} htmlFor={id} hint="ต้องเลือกหรือระบุเอง ระบบไม่เลือกให้ และระบบหลังบ้านจะตรวจสอบสถานะและขอบเขตข้อมูลอีกครั้ง">
      {options !== null ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          <option value="">เลือกผู้ขับ</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      ) : (
        <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} />
      )}
    </FormField>
  )
}

function ShiftFields({ form, set, disabled, legend }: {
  form: E2Form; set: (patch: Partial<E2Form>) => void; disabled: boolean; legend: string
}) {
  return (
    <fieldset className="form-grid">
      <legend>{legend}</legend>
      <FormField label="เวลาเริ่มกะ" htmlFor="e2-shift-start">
        <input id="e2-shift-start" type="time" value={form.shiftStart} onChange={(e) => set({ shiftStart: e.target.value })} disabled={disabled} />
      </FormField>
      <FormField label="เวลาสิ้นสุดกะ" htmlFor="e2-shift-end">
        <input id="e2-shift-end" type="time" value={form.shiftEnd} onChange={(e) => set({ shiftEnd: e.target.value })} disabled={disabled} />
      </FormField>
      <FormField label="กะสิ้นสุด" htmlFor="e2-shift-offset" hint="เวลาเริ่มและสิ้นสุดเท่ากันได้เฉพาะเมื่อสิ้นสุดวันถัดไป (24 ชั่วโมง)">
        <select id="e2-shift-offset" value={form.shiftOffset} onChange={(e) => set({ shiftOffset: e.target.value as E2Form['shiftOffset'] })} disabled={disabled}>
          <option value="">เลือก</option>
          <option value="0">วันเดียวกัน</option>
          <option value="1">วันถัดไป (+1 วัน)</option>
        </select>
      </FormField>
    </fieldset>
  )
}

function TargetSummary({ target }: { target: E2AssignmentState }) {
  const s = target.state
  return (
    <div className="e2-target" data-testid="e2-dialog-target">
      <div className="status-card__row"><span>รายการมอบหมาย</span><span><code>{target.event.event_id}</code> (ฉบับ {target.event.revision_no})</span></div>
      {s && (
        <>
          <div className="status-card__row"><span>ผู้ขับปัจจุบัน</span><span><code>{s.assigned_driver_id}</code></span></div>
          <div className="status-card__row"><span>รูปแบบ</span><span>{e2ModeLabel[s.mode ?? ''] ?? s.mode}</span></div>
          <div className="status-card__row"><span>วันที่</span><span>{formatE2Date(s.start_date)} – {formatE2Date(s.end_date)}</span></div>
          {formatE2Shift(s.shift_start_time, s.shift_end_time, s.shift_end_day_offset) !== null && (
            <div className="status-card__row"><span>เวลากะ</span><span>{formatE2Shift(s.shift_start_time, s.shift_end_time, s.shift_end_day_offset)}</span></div>
          )}
          {s.excluded_dates.length > 0 && (
            <div className="status-card__row"><span>วันที่ตัดออกแล้ว</span><span>{s.excluded_dates.map(formatE2Date).join(', ')}</span></div>
          )}
        </>
      )}
    </div>
  )
}

/** The overlap details of a 409 E2_VEHICLE_CONFLICT / E2_DRIVER_CONFLICT. */
export function E2OverlapView({ overlap }: { overlap: E2OverlapDetails }) {
  const items = [overlap.first, overlap.second].filter((i) => i !== null)
  return (
    <div data-testid="e2-overlap">
      <p>
        แกนที่ทับกัน: {overlap.axis === 'VEHICLE' ? 'รถ' : overlap.axis === 'DRIVER' ? 'ผู้ขับ' : overlap.axis}
        {overlap.conflicting_event_id && <> — รายการที่ทับ <code>{overlap.conflicting_event_id}</code></>}
      </p>
      <ul>
        {items.map((i) => (
          <li key={`${i.event_id}-${i.start}`}>
            <code>{i.event_id}</code> รถ <code>{i.vehicle_id}</code> ผู้ขับ <code>{i.assigned_driver_id}</code>{' '}
            {formatE2Date(i.label_date)} {formatE2Span(i.start, i.end, i.label_date)}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function E2OperationDialog({
  operation, target, assignments, driverOptions, today, submitting, error, onCancel, onSubmit,
}: Props) {
  const [form, setForm] = useState<E2Form>(() => (operation === 'REVISE' ? formFromState(target) : emptyE2Form()))
  const [localError, setLocalError] = useState<string | null>(null)
  const set = (patch: Partial<E2Form>) => setForm((f) => ({ ...f, ...patch }))
  const targetMode = (target?.state?.mode ?? '') as E2Mode | ''
  const predecessors = assignments.filter((a) => a.event.lifecycle === 'ACTIVE' && a.state !== null)
  const reasonRequired = operation !== 'CREATE' || (isIsoDate(form.startDate) && form.startDate < today)

  const submit = () => {
    const built = buildE2Body(operation, form, target, assignments, today)
    if ('error' in built) return setLocalError(built.error)
    setLocalError(null)
    onSubmit(built.body)
  }

  const titleId = `e2-${operation}-title`
  return (
    <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="e2-operation-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{e2OperationLabel[operation]}</h2>
        <p className="form-field__hint">วันที่และเวลาทั้งหมดเป็นเวลาประเทศไทย (Asia/Bangkok)</p>
        {target && <TargetSummary target={target} />}
        {operation === 'CANCEL' && (
          <p className="form-field__error" role="note">
            ยกเลิกได้เฉพาะก่อนเริ่มการมอบหมาย การยกเลิกจะถูกบันทึกเป็นรายการใหม่ รายการเดิมยังคงอยู่ในประวัติ
          </p>
        )}
        <div className="form-grid">
          {operation === 'CREATE' && (
            <>
              <DriverField id="e2-driver" label="ผู้ขับที่ได้รับมอบหมาย" value={form.driverId} onChange={(v) => set({ driverId: v })}
                options={driverOptions} disabled={submitting} />
              <FormField label="รูปแบบการมอบหมาย" htmlFor="e2-mode">
                <select id="e2-mode" value={form.mode} onChange={(e) => set({ mode: e.target.value as E2Mode | '' })} disabled={submitting}>
                  <option value="">เลือกรูปแบบ</option>
                  {E2_MODES.map((m) => <option key={m} value={m}>{e2ModeLabel[m]}</option>)}
                </select>
              </FormField>
              <FormField label="วันที่เริ่มต้น" htmlFor="e2-start" hint="กะกลางคืนใช้วันที่เริ่มกะเป็นวันที่ของกะ">
                <input id="e2-start" type="date" value={form.startDate} onChange={(e) => set({ startDate: e.target.value })} disabled={submitting} />
              </FormField>
              <FormField label="วันที่สิ้นสุด (รวมวันนี้)" htmlFor="e2-end" hint="ทั้งวัน: มีผลถึง 24:00 ของวันสุดท้าย">
                <input id="e2-end" type="date" value={form.endDate} onChange={(e) => set({ endDate: e.target.value })} disabled={submitting} />
              </FormField>
              {isShift(form.mode) && <ShiftFields form={form} set={set} disabled={submitting} legend="เวลากะที่ใช้ (ต้องระบุเอง)" />}
              <label>
                <input type="checkbox" checked={form.handover} onChange={(e) => set({ handover: e.target.checked })} disabled={submitting} />{' '}
                ส่งต่อจากการมอบหมายก่อนหน้า (H2 / H3)
              </label>
              {form.handover && (
                <FormField label="การมอบหมายก่อนหน้า" htmlFor="e2-predecessor"
                  hint="H2: ทั้งวันวันสุดท้าย → กะกลางคืนที่เริ่มวันเดียวกัน, H3: กะกลางคืนข้ามคืน → ทั้งวันของวันถัดไป (ระบบหลังบ้านตรวจเงื่อนไข)">
                  <select id="e2-predecessor" value={form.predecessorId} onChange={(e) => set({ predecessorId: e.target.value })} disabled={submitting}>
                    <option value="">เลือกการมอบหมาย</option>
                    {predecessors.map((a) => (
                      <option key={a.event.event_id} value={a.event.event_id}>
                        {a.state?.assigned_driver_id} — {e2ModeLabel[a.state?.mode ?? ''] ?? a.state?.mode} {a.state?.start_date} ถึง {a.state?.end_date} (ฉบับ {a.event.revision_no})
                      </option>
                    ))}
                  </select>
                </FormField>
              )}
            </>
          )}

          {operation === 'REVISE' && (
            <>
              <fieldset className="form-grid">
                <legend>ประเภทการแก้ไข</legend>
                {(['STATE', 'SPLIT', 'EXCLUDE', 'VOID'] as const)
                  .filter((v) => v !== 'SPLIT' || isShift(targetMode))
                  .map((v) => (
                    <label key={v}>
                      <input type="radio" name="e2-revise-variant" checked={form.reviseVariant === v}
                        onChange={() => setForm({ ...formFromState(target), reviseVariant: v, reason: form.reason })} disabled={submitting} />{' '}
                      {e2ReviseVariantLabel[v]}
                    </label>
                  ))}
              </fieldset>
              {form.reviseVariant === 'STATE' && (
                <>
                  <DriverField id="e2-driver" label="ผู้ขับที่ได้รับมอบหมาย" value={form.driverId} onChange={(v) => set({ driverId: v })}
                    options={driverOptions} disabled={submitting} />
                  <FormField label="วันที่เริ่มต้น" htmlFor="e2-start">
                    <input id="e2-start" type="date" value={form.startDate} onChange={(e) => set({ startDate: e.target.value })} disabled={submitting} />
                  </FormField>
                  <FormField label="วันที่สิ้นสุด (รวมวันนี้)" htmlFor="e2-end">
                    <input id="e2-end" type="date" value={form.endDate} onChange={(e) => set({ endDate: e.target.value })} disabled={submitting} />
                  </FormField>
                  {isShift(targetMode) && <ShiftFields form={form} set={set} disabled={submitting} legend="เวลากะที่ใช้" />}
                </>
              )}
              {form.reviseVariant === 'SPLIT' && (
                <>
                  <FormField label="เริ่มใช้เวลากะใหม่ตั้งแต่วันที่" htmlFor="e2-split-from" hint="ช่วงก่อนวันนี้คงเวลากะเดิม">
                    <input id="e2-split-from" type="date" value={form.splitFrom} onChange={(e) => set({ splitFrom: e.target.value })} disabled={submitting} />
                  </FormField>
                  <ShiftFields form={form} set={set} disabled={submitting} legend="เวลากะใหม่" />
                </>
              )}
              {form.reviseVariant === 'EXCLUDE' && (
                <DateList id="e2-exclude" label="วันที่ที่ต้องการตัดออก" values={form.excludeDates}
                  onChange={(v) => set({ excludeDates: v })} disabled={submitting} />
              )}
              {form.reviseVariant === 'VOID' && (
                <p className="form-field__error" role="note">
                  ใช้เฉพาะการมอบหมายที่เริ่มแล้วและบันทึกผิดทั้งรายการ รายการเดิมยังอยู่ในประวัติ และจะไม่มีช่วงเวลาที่มีผล
                </p>
              )}
            </>
          )}

          {operation === 'SUBSTITUTE' && (
            <>
              <DateList id="e2-sub-dates" label="วัน/กะที่ให้ผู้ขับแทน (ทั้งวันหรือทั้งกะเท่านั้น)" values={form.dates}
                onChange={(v) => set({ dates: v })} disabled={submitting} />
              <DriverField id="e2-driver" label="ผู้ขับแทน" value={form.driverId} onChange={(v) => set({ driverId: v })}
                options={driverOptions} disabled={submitting} />
            </>
          )}

          {operation === 'EARLY_END' && (
            <fieldset className="form-grid">
              <legend>สิ้นสุดเมื่อ</legend>
              <label>
                <input type="radio" name="e2-early-mode" checked={form.earlyMode === 'NOW'} onChange={() => set({ earlyMode: 'NOW' })} disabled={submitting} />{' '}
                ตอนนี้
              </label>
              <label>
                <input type="radio" name="e2-early-mode" checked={form.earlyMode === 'AFTER_DATE'} onChange={() => set({ earlyMode: 'AFTER_DATE' })} disabled={submitting} />{' '}
                หลังวันที่ที่กำหนด (วันนั้นเป็นวันสุดท้าย)
              </label>
              {form.earlyMode === 'AFTER_DATE' && (
                <FormField label="วันสุดท้ายของการมอบหมาย" htmlFor="e2-early-date">
                  <input id="e2-early-date" type="date" value={form.earlyDate} onChange={(e) => set({ earlyDate: e.target.value })} disabled={submitting} />
                </FormField>
              )}
            </fieldset>
          )}

          <FormField
            label={reasonRequired ? 'เหตุผล (บังคับ)' : 'เหตุผล (ไม่บังคับ — บังคับเมื่อวันที่เริ่มอยู่ก่อนวันนี้)'}
            htmlFor="e2-reason"
            error={localError ?? error?.text ?? undefined}
          >
            <textarea id="e2-reason" value={form.reason} maxLength={E2_MAX_REASON_LENGTH} onChange={(e) => set({ reason: e.target.value })} disabled={submitting} />
          </FormField>
          {error?.overlap && <E2OverlapView overlap={error.overlap} />}
        </div>
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>ปิด</button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : `ยืนยัน${e2OperationLabel[operation]}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// The panel's message and pending-intent banner
// ---------------------------------------------------------------------------

const STATE_TEXT: Record<string, string> = {
  SUBMITTING: 'กำลังส่งคำขอ',
  UNKNOWN: 'ยังไม่ทราบผล',
  CONFLICT: 'รหัสคำขอขัดแย้ง',
}

export function E2WriteNotice({ message, intent, inFlight, onResend, onReload }: {
  message: E2Message | null
  intent: E2Intent | 'corrupt' | null
  inFlight: boolean
  onResend: () => void
  onReload: () => void
}) {
  return (
    <>
      {message && (
        <div className={message.tone === 'success' ? 'form-field__hint' : 'form-field__error'} role="alert" data-testid="e2-write-message">
          <p>{message.text}</p>
          {message.warnings && message.warnings.length > 0 && (
            <ul data-testid="e2-write-warnings">
              {message.warnings.map((w, i) => <li key={`${w.code}-${i}`}>{e2WarningLabel[w.code] ?? w.code}</li>)}
            </ul>
          )}
          {message.requestId && <p className="state-panel__meta">รหัสคำขอ: {message.requestId}</p>}
          {message.reload && (
            <button type="button" className="button button--secondary" onClick={onReload}>โหลดข้อมูลล่าสุด</button>
          )}
        </div>
      )}
      {intent === 'corrupt' && (
        <div className="form-field__error" role="status" data-testid="e2-pending-intent">
          <p>พบรายการคำขอค้างที่อ่านไม่ได้ในเบราว์เซอร์นี้ จึงยังไม่บันทึกรายการใหม่ กรุณาติดต่อผู้ดูแลระบบ</p>
        </div>
      )}
      {intent !== null && intent !== 'corrupt' && (
        <div className="form-field__error" role="status" data-testid="e2-pending-intent">
          <p>มีคำขอที่ค้างอยู่ ({e2OperationLabel[intent.operation] ?? intent.operation}) — {inFlight ? STATE_TEXT.SUBMITTING : STATE_TEXT[intent.state]}</p>
          <p className="state-panel__meta">รหัสคำขอ: {intent.request_id}</p>
          {intent.state === 'CONFLICT' && <p data-testid="e2-conflict-escalation">{E2_CONFLICT_ESCALATION}</p>}
          <div className="dialog__actions">
            {intent.state === 'UNKNOWN' && !inFlight && (
              <button type="button" className="button button--secondary" onClick={onResend}>ส่งคำขอเดิมอีกครั้ง</button>
            )}
            <button type="button" className="button button--secondary" onClick={onReload} disabled={inFlight}>
              โหลดประวัติล่าสุดเพื่อตรวจสอบ
            </button>
          </div>
        </div>
      )}
    </>
  )
}
