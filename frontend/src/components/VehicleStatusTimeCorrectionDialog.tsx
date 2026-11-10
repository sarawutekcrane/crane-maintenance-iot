import { useState } from 'react'
import { operationalStatusLabel } from '../lib/labels'
import type { VehicleStatusEvent } from '../lib/types'
import { FormField } from './FormField'

interface VehicleStatusTimeCorrectionDialogProps {
  event: VehicleStatusEvent | null
  submitting: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (newEffectiveAt: string, reason: string) => void
}

function bangkok(iso: string): string {
  return new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Bangkok' }).format(
    new Date(iso),
  )
}

/**
 * R5 (OD-3) — correct WHEN a recorded vehicle status took effect. The status value is
 * never changed here, and a reason is mandatory; the original event and every earlier
 * correction are kept. The server keeps the new time strictly between the neighbouring
 * events and never in the future (AMB-1 authorization is server-side).
 */
export function VehicleStatusTimeCorrectionDialog({ event, submitting, error, onCancel, onSubmit }: VehicleStatusTimeCorrectionDialogProps) {
  const [local, setLocal] = useState('')
  const [reason, setReason] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  if (!event) return null

  const submit = () => {
    if (!local) return setLocalError('กรุณาระบุเวลาที่มีผลใหม่')
    if (!reason.trim()) return setLocalError('กรุณาระบุเหตุผลการแก้ไข')
    setLocalError(null)
    onSubmit(`${local}:00+07:00`, reason.trim())
  }
  const shown = localError ?? error

  return (
    <div className="dialog-overlay" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="status-time-correction-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="status-time-correction-title">แก้เวลาที่มีผลของสถานะ</h2>
        <p>
          สถานะ {operationalStatusLabel[event.status] ?? event.status} · เวลาที่มีผลปัจจุบัน {bangkok(event.effective_at)} · บันทึกเมื่อ{' '}
          {bangkok(event.recorded_at)}
        </p>
        <div className="form-grid">
          <FormField label="เวลาที่มีผลใหม่ (เวลาประเทศไทย)" htmlFor="status-time-new">
            <input id="status-time-new" type="datetime-local" value={local} onChange={(e) => setLocal(e.target.value)} />
          </FormField>
          <FormField label="เหตุผลการแก้ไข" htmlFor="status-time-reason">
            <textarea id="status-time-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </FormField>
        </div>
        {shown && (
          <p className="form-field__error" role="alert">
            {shown}
          </p>
        )}
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>
            ยกเลิก
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : 'บันทึกการแก้ไข'}
          </button>
        </div>
      </div>
    </div>
  )
}
