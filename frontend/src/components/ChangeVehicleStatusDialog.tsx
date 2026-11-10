import { useState } from 'react'
import type { OperationalStatus } from '../lib/types'
import { operationalStatusLabel } from '../lib/labels'
import { FormField } from './FormField'

const STATUS_OPTIONS: OperationalStatus[] = [
  'WORKING',
  'READY',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'LONG_TERM_PARKING',
]

interface ChangeVehicleStatusDialogProps {
  open: boolean
  currentStatus: OperationalStatus
  submitting: boolean
  /** R5: the server's refusal (403 / scope / unconfigured context), shown in the dialog. */
  error?: string | null
  onCancel: () => void
  /** `effectiveAt` (R5 OD-3): null = the change takes effect now (the existing current-status change);
   * an ISO instant = an effective-dated status event. */
  onSubmit: (status: OperationalStatus, note: string, effectiveAt: string | null) => void
}

/**
 * Vehicle status change is a deliberate action, not a one-tap control
 * (baseline mobile-first principle 18: destructive/status-changing
 * actions must not be easy to trigger accidentally) — reuses the frozen
 * `.dialog`/`.dialog-overlay` bottom-sheet-on-phone pattern from
 * `ConfirmDialog`, extended with the fields this action needs.
 *
 * R5 (OD-3): an optional "effective time" records when the status actually took
 * effect (Asia/Bangkok, never in the future). Left blank, the change is recorded as
 * taking effect now, exactly as before. Who may change a status is decided by the
 * server (AMB-1); this dialog is only opened from a capability-gated control.
 */
export function ChangeVehicleStatusDialog({
  open,
  currentStatus,
  submitting,
  error = null,
  onCancel,
  onSubmit,
}: ChangeVehicleStatusDialogProps) {
  const [status, setStatus] = useState<OperationalStatus>(currentStatus)
  const [note, setNote] = useState('')
  const [effectiveLocal, setEffectiveLocal] = useState('')

  if (!open) return null

  return (
    <div className="dialog-overlay" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="change-status-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="change-status-dialog-title">เปลี่ยนสถานะการใช้งาน</h2>

        <div className="form-grid">
          <FormField label="สถานะใหม่" htmlFor="change-status-select">
            <select
              id="change-status-select"
              value={status}
              onChange={(event) => setStatus(event.target.value as OperationalStatus)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {operationalStatusLabel[option] ?? option}
                </option>
              ))}
            </select>
          </FormField>

          <FormField label="หมายเหตุ (ไม่บังคับ)" htmlFor="change-status-note">
            <textarea
              id="change-status-note"
              value={note}
              maxLength={500}
              onChange={(event) => setNote(event.target.value)}
              placeholder="เช่น เหตุผลของการเปลี่ยนสถานะ"
            />
          </FormField>

          <FormField label="เวลาที่มีผลจริง (ไม่บังคับ — เว้นว่าง = ตอนนี้)" htmlFor="change-status-effective">
            <input
              id="change-status-effective"
              type="datetime-local"
              value={effectiveLocal}
              onChange={(event) => setEffectiveLocal(event.target.value)}
            />
          </FormField>
        </div>

        {error && (
          <p className="form-field__error" role="alert">
            {error}
          </p>
        )}

        <div className="dialog__actions">
          <button
            type="button"
            className="button button--secondary"
            onClick={onCancel}
            disabled={submitting}
          >
            ยกเลิก
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() =>
              onSubmit(status, note.trim() === '' ? '' : note.trim(), effectiveLocal ? `${effectiveLocal}:00+07:00` : null)
            }
            disabled={submitting}
          >
            {submitting ? 'กำลังบันทึก...' : 'ยืนยันเปลี่ยนสถานะ'}
          </button>
        </div>
      </div>
    </div>
  )
}
