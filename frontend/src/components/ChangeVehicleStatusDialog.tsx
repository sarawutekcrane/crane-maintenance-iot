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
  onCancel: () => void
  onSubmit: (status: OperationalStatus, note: string) => void
}

/**
 * Vehicle status change is a deliberate action, not a one-tap control
 * (baseline mobile-first principle 18: destructive/status-changing
 * actions must not be easy to trigger accidentally) — reuses the frozen
 * `.dialog`/`.dialog-overlay` bottom-sheet-on-phone pattern from
 * `ConfirmDialog`, extended with the fields this action needs.
 */
export function ChangeVehicleStatusDialog({
  open,
  currentStatus,
  submitting,
  onCancel,
  onSubmit,
}: ChangeVehicleStatusDialogProps) {
  const [status, setStatus] = useState<OperationalStatus>(currentStatus)
  const [note, setNote] = useState('')

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
        </div>

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
            onClick={() => onSubmit(status, note.trim() === '' ? '' : note.trim())}
            disabled={submitting}
          >
            {submitting ? 'กำลังบันทึก...' : 'ยืนยันเปลี่ยนสถานะ'}
          </button>
        </div>
      </div>
    </div>
  )
}
