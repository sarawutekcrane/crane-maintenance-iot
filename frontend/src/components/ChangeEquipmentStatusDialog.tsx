import { useState } from 'react'
import type { EquipmentOperationalStatus } from '../lib/types'
import { equipmentStatusLabel } from '../lib/labels'
import { FormField } from './FormField'

const STATUS_OPTIONS: EquipmentOperationalStatus[] = [
  'READY',
  'IN_USE',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'RETIRED',
]

interface ChangeEquipmentStatusDialogProps {
  open: boolean
  currentStatus: EquipmentOperationalStatus
  submitting: boolean
  onCancel: () => void
  onSubmit: (status: EquipmentOperationalStatus, reason: string) => void
}

/**
 * Core Demo Fixes, EQUIPMENT STATUS CHANGE — APPROVED: equipment status
 * change with reason/actor/timestamp, appended to an immutable history.
 * Mirrors `ChangeVehicleStatusDialog`'s deliberate-action bottom-sheet
 * pattern — a status change (especially RETIRED, which is permanent) must
 * never be a one-tap accidental control.
 */
export function ChangeEquipmentStatusDialog({
  open,
  currentStatus,
  submitting,
  onCancel,
  onSubmit,
}: ChangeEquipmentStatusDialogProps) {
  const [status, setStatus] = useState<EquipmentOperationalStatus>(currentStatus)
  const [reason, setReason] = useState('')

  if (!open) return null

  return (
    <div className="dialog-overlay" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="change-equipment-status-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="change-equipment-status-dialog-title">เปลี่ยนสถานะการใช้งาน</h2>

        <div className="form-grid">
          <FormField label="สถานะใหม่" htmlFor="change-equipment-status-select">
            <select
              id="change-equipment-status-select"
              value={status}
              onChange={(event) => setStatus(event.target.value as EquipmentOperationalStatus)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {equipmentStatusLabel[option] ?? option}
                </option>
              ))}
            </select>
          </FormField>

          {status === 'RETIRED' && (
            <p className="form-field__error" role="alert">
              การปลดระวางเป็นการดำเนินการถาวร เครื่องมือนี้จะไม่สามารถเลือกใช้งานใหม่ได้อีก
              (ประวัติทั้งหมดจะยังคงอยู่)
            </p>
          )}

          <FormField label="เหตุผล (ไม่บังคับ)" htmlFor="change-equipment-status-reason">
            <textarea
              id="change-equipment-status-reason"
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
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
            onClick={() => onSubmit(status, reason.trim())}
            disabled={submitting}
          >
            {submitting ? 'กำลังบันทึก...' : 'ยืนยันเปลี่ยนสถานะ'}
          </button>
        </div>
      </div>
    </div>
  )
}
