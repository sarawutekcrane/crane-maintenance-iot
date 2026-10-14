import { useId, useMemo, useState } from 'react'
import { technicianName, type TechnicianSummary } from '../lib/technicianV2'
import { FormField } from './FormField'

interface TechnicianV2PickerProps {
  /** Exactly what the server returned for its own scope (never filtered by scope here). */
  technicians: TechnicianSummary[]
  primary: string
  collaborators: string[]
  onChange: (primary: string, collaborators: string[]) => void
  disabled?: boolean
}

function optionLabel(technician: TechnicianSummary): string {
  const name = technicianName(technician) ?? 'ไม่มีชื่อในข้อมูลหลัก'
  return `${technician.technician_id} — ${name}`
}

/**
 * R2 Batch R2f-h4 B4 (A1-§25) — the stable-ID technician picker: exactly one
 * PRIMARY plus zero or more COLLABORATORs, chosen only from the ids the server
 * listed (never a name, a user id or free text). The PRIMARY can never also be a
 * COLLABORATOR, so a duplicate cannot be built. The filter box only narrows what
 * is displayed, locally; it sends no search parameter. Eligibility (the
 * BOTH-ACTIVE gate) is decided by the server on save.
 */
export function TechnicianV2Picker({ technicians, primary, collaborators, onChange, disabled }: TechnicianV2PickerProps) {
  const baseId = useId()
  const [filter, setFilter] = useState('')
  const needle = filter.trim().toLowerCase()
  const visible = useMemo(
    () =>
      technicians.filter(
        (t) =>
          !needle ||
          t.technician_id.toLowerCase().includes(needle) ||
          (technicianName(t) ?? '').toLowerCase().includes(needle) ||
          t.technician_id === primary ||
          collaborators.includes(t.technician_id),
      ),
    [technicians, needle, primary, collaborators],
  )

  const choosePrimary = (id: string) => onChange(id, collaborators.filter((c) => c !== id))
  const toggleCollaborator = (id: string, checked: boolean) =>
    onChange(primary, checked ? [...collaborators.filter((c) => c !== id), id] : collaborators.filter((c) => c !== id))

  return (
    <div className="form-grid" data-testid="technician-v2-picker">
      <FormField label="กรองรายชื่อช่าง (เฉพาะที่แสดงในหน้านี้)" htmlFor={`${baseId}-filter`}>
        <input
          id={`${baseId}-filter`}
          type="search"
          value={filter}
          disabled={disabled}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="รหัสช่างหรือชื่อ"
        />
      </FormField>
      <FormField
        label="ช่างหลัก (PRIMARY) — 1 คน"
        htmlFor={`${baseId}-primary`}
        hint="เลือกจากรหัสช่างในขอบเขตข้อมูลของระบบเท่านั้น"
      >
        <select
          id={`${baseId}-primary`}
          value={primary}
          disabled={disabled}
          onChange={(event) => choosePrimary(event.target.value)}
        >
          <option value="">— เลือกช่างหลัก —</option>
          {visible.map((t) => (
            <option key={t.technician_id} value={t.technician_id}>
              {optionLabel(t)}
              {t.active_status !== 'ACTIVE' ? ` (สถานะ: ${t.active_status ?? 'ไม่ระบุ'})` : ''}
            </option>
          ))}
        </select>
      </FormField>
      <fieldset className="form-field" disabled={disabled}>
        <legend>ช่างร่วม (COLLABORATOR) — ไม่บังคับ</legend>
        {visible.filter((t) => t.technician_id !== primary).length === 0 && (
          <p className="form-field__hint">ไม่มีช่างอื่นให้เลือก</p>
        )}
        {visible
          .filter((t) => t.technician_id !== primary)
          .map((t) => {
            const inputId = `${baseId}-collab-${t.technician_id}`
            return (
              <label key={t.technician_id} htmlFor={inputId} className="checkbox-row">
                <input
                  id={inputId}
                  type="checkbox"
                  value={t.technician_id}
                  checked={collaborators.includes(t.technician_id)}
                  onChange={(event) => toggleCollaborator(t.technician_id, event.target.checked)}
                />{' '}
                <span>
                  <strong>{t.technician_id}</strong> — {technicianName(t) ?? 'ไม่มีชื่อในข้อมูลหลัก'}
                  {t.active_status !== 'ACTIVE' && ` (สถานะ: ${t.active_status ?? 'ไม่ระบุ'})`}
                </span>
              </label>
            )
          })}
      </fieldset>
    </div>
  )
}
