import { useState } from 'react'
import type { CrewInterval, CrewMode, CrewRole } from '../lib/types'
import { crewRoleLabel, e2ModeLabel } from '../lib/labels'
import { bangkokToday, isHhMm, isIsoDate } from '../lib/e2Assignments'
import { FormField } from './FormField'

/**
 * R8 early workstream — the crew write form (OD-4 = A: CREATE / REVISE / CANCEL /
 * EARLY_END; no SUBSTITUTE or handover). Client checks only help the user; the
 * backend validates everything again and is the only authority.
 */

export type CrewOperation = 'CREATE' | 'REVISE' | 'CANCEL' | 'EARLY_END'

export interface PersonnelOption {
  personnel_id: string
  name: string
}

interface Props {
  operation: CrewOperation
  target: CrewInterval | null
  personnel: PersonnelOption[]
  busy: boolean
  onSubmit: (body: Record<string, unknown>) => void
  onClose: () => void
}

const ROLES: CrewRole[] = ['RIGGER', 'SIGNALMAN', 'OTHER']
const MODES: CrewMode[] = ['FULL_DAY', 'DAY_SHIFT', 'NIGHT_SHIFT']

const TITLES: Record<CrewOperation, string> = {
  CREATE: 'เพิ่มทีมงานประจำเครน',
  REVISE: 'แก้ไขการมอบหมายทีมงาน',
  CANCEL: 'ยกเลิกการมอบหมาย (ก่อนเริ่มงาน)',
  EARLY_END: 'สิ้นสุดการมอบหมายก่อนกำหนด',
}

export function CrewOperationDialog({ operation, target, personnel, busy, onSubmit, onClose }: Props) {
  const today = bangkokToday()
  const [personnelId, setPersonnelId] = useState(target?.personnel_id ?? '')
  const [role, setRole] = useState<CrewRole>(target?.crew_role ?? 'RIGGER')
  const [note, setNote] = useState(target?.crew_role_note_th ?? '')
  const [mode, setMode] = useState<CrewMode>(target?.mode ?? 'FULL_DAY')
  const [startDate, setStartDate] = useState(target?.label_date ?? today)
  const [endDate, setEndDate] = useState(target?.label_date ?? today)
  const [startTime, setStartTime] = useState('08:00')
  const [endTime, setEndTime] = useState('17:00')
  const [nextDay, setNextDay] = useState(false)
  const [reason, setReason] = useState('')
  const [endMode, setEndMode] = useState<'NOW' | 'AFTER_DATE'>('NOW')
  const [endAfter, setEndAfter] = useState(today)
  const [error, setError] = useState<string | null>(null)

  const needsState = operation === 'CREATE' || operation === 'REVISE'
  const reasonRequired = operation !== 'CREATE' || startDate < today

  const submit = () => {
    if (needsState) {
      if (operation === 'CREATE' && !personnelId) return setError('กรุณาเลือกบุคลากร')
      if (!isIsoDate(startDate) || !isIsoDate(endDate) || endDate < startDate) {
        return setError('กรุณาระบุวันที่เริ่มและวันที่สิ้นสุดให้ถูกต้อง')
      }
      if (role === 'OTHER' && !note.trim()) return setError('บทบาท “อื่นๆ” ต้องระบุคำอธิบายบทบาท')
      if (mode !== 'FULL_DAY' && (!isHhMm(startTime) || !isHhMm(endTime))) {
        return setError('กรุณาระบุเวลาเริ่มและสิ้นสุดกะ (HH:MM)')
      }
    }
    if (reasonRequired && !reason.trim()) return setError('กรุณาระบุเหตุผล')
    setError(null)
    const shift = mode === 'FULL_DAY' ? undefined : { start_time: startTime, end_time: endTime, end_day_offset: nextDay ? 1 : 0 }
    if (operation === 'CREATE') {
      onSubmit({
        operation, personnel_id: personnelId, crew_role: role, mode, start_date: startDate, end_date: endDate,
        ...(role === 'OTHER' ? { crew_role_note_th: note } : {}),
        ...(shift ? { shift } : {}),
        ...(reason.trim() ? { reason_th: reason } : {}),
      })
    } else if (operation === 'REVISE' && target) {
      onSubmit({
        operation, event_id: target.event_id, expected_revision_no: target.revision_no, reason_th: reason,
        crew_role: role, mode, start_date: startDate, end_date: endDate,
        ...(role === 'OTHER' ? { crew_role_note_th: note } : {}),
        ...(shift ? { shift } : {}),
      })
    } else if (operation === 'CANCEL' && target) {
      onSubmit({ operation, event_id: target.event_id, expected_revision_no: target.revision_no, reason_th: reason })
    } else if (operation === 'EARLY_END' && target) {
      onSubmit({
        operation, event_id: target.event_id, expected_revision_no: target.revision_no, reason_th: reason,
        end: endMode === 'NOW' ? { mode: 'NOW' } : { mode: 'AFTER_DATE', date: endAfter },
      })
    }
  }

  return (
    <div className="crew-dialog" role="group" aria-label={TITLES[operation]}>
      <h3>{TITLES[operation]}</h3>
      {needsState && (
        <div className="form-grid form-grid--two-column">
          {operation === 'CREATE' ? (
            <FormField label="บุคลากร" htmlFor="crew-personnel">
              <select id="crew-personnel" value={personnelId} onChange={(e) => setPersonnelId(e.target.value)}>
                <option value="">— เลือกบุคลากร —</option>
                {personnel.map((p) => (
                  <option key={p.personnel_id} value={p.personnel_id}>
                    {p.name ? `${p.name} (${p.personnel_id})` : p.personnel_id}
                  </option>
                ))}
              </select>
            </FormField>
          ) : (
            <p>บุคลากร: {target?.personnel_name ?? target?.personnel_id} (เปลี่ยนคนให้ใช้สิ้นสุด/ยกเลิก แล้วเพิ่มใหม่)</p>
          )}
          <FormField label="บทบาท" htmlFor="crew-role">
            <select id="crew-role" value={role} onChange={(e) => setRole(e.target.value as CrewRole)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {crewRoleLabel[r]}
                </option>
              ))}
            </select>
          </FormField>
          {role === 'OTHER' && (
            <FormField label="คำอธิบายบทบาท" htmlFor="crew-role-note">
              <input id="crew-role-note" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
            </FormField>
          )}
          <FormField label="รูปแบบเวลา" htmlFor="crew-mode">
            <select id="crew-mode" value={mode} onChange={(e) => setMode(e.target.value as CrewMode)}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {e2ModeLabel[m] ?? m}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="วันที่เริ่ม" htmlFor="crew-start">
            <input id="crew-start" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </FormField>
          <FormField label="วันที่สิ้นสุด" htmlFor="crew-end">
            <input id="crew-end" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </FormField>
          {mode !== 'FULL_DAY' && (
            <>
              <FormField label="เวลาเริ่มกะ" htmlFor="crew-shift-start">
                <input id="crew-shift-start" type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
              </FormField>
              <FormField label="เวลาสิ้นสุดกะ" htmlFor="crew-shift-end">
                <input id="crew-shift-end" type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
              </FormField>
              <label className="vehicle-list__checkbox">
                <input type="checkbox" checked={nextDay} onChange={(e) => setNextDay(e.target.checked)} /> สิ้นสุดวันถัดไป
              </label>
            </>
          )}
        </div>
      )}
      {operation === 'EARLY_END' && (
        <FormField label="สิ้นสุดเมื่อ" htmlFor="crew-end-mode">
          <select id="crew-end-mode" value={endMode} onChange={(e) => setEndMode(e.target.value as 'NOW' | 'AFTER_DATE')}>
            <option value="NOW">ตอนนี้</option>
            <option value="AFTER_DATE">หลังวันที่ระบุ</option>
          </select>
        </FormField>
      )}
      {operation === 'EARLY_END' && endMode === 'AFTER_DATE' && (
        <FormField label="วันสุดท้ายที่ทำงาน" htmlFor="crew-end-after">
          <input id="crew-end-after" type="date" value={endAfter} onChange={(e) => setEndAfter(e.target.value)} />
        </FormField>
      )}
      <FormField label={reasonRequired ? 'เหตุผล (จำเป็น)' : 'เหตุผล'} htmlFor="crew-reason">
        <textarea id="crew-reason" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </FormField>
      <p className="vehicle-overview__muted">
        บันทึกเป็นการ “มอบหมาย” เท่านั้น ไม่ใช่การยืนยันการมาทำงานจริง ระบบตรวจไม่ให้บุคคลเดียวกันถูกมอบหมายซ้อนเวลา
      </p>
      {error && (
        <p className="form-field__error" role="alert">
          {error}
        </p>
      )}
      <div className="vehicle-list__form-actions">
        <button type="button" className="button button--primary button--full-width" disabled={busy} onClick={submit}>
          {busy ? 'กำลังบันทึก...' : 'บันทึก'}
        </button>
        <button type="button" className="button button--secondary button--full-width" disabled={busy} onClick={onClose}>
          ปิด
        </button>
      </div>
    </div>
  )
}
