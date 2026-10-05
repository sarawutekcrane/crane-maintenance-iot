import { useState } from 'react'
import { type ReferenceLoad, resolveOptionalCode } from '../lib/referenceResolution'
import type { RegistrationHistory } from '../lib/types'
import { FormField } from './FormField'

/**
 * Phase 7 Batch 7O2b — registration reconciliation (contract Final Rev2
 * §4.6): bring the vehicle record and the registration history back into
 * agreement, deliberately and with a reason.
 *
 * - APPLY_RECORDED: write the latest recorded registration to the vehicle
 *   record (the normal duplicate and province rules apply).
 * - ACCEPT_MASTER: keep the vehicle record as it is and record that it was
 *   accepted (history only).
 * `related_request_id` is an audit link only: it never settles anything.
 */
export type ReconcileMode = 'APPLY_RECORDED' | 'ACCEPT_MASTER'

interface Props {
  open: boolean
  history: RegistrationHistory
  masterNo: string | null
  masterProvince: string | null
  provinces: ReferenceLoad
  initialRelatedRequestId: string
  submitting: boolean
  onCancel: () => void
  onSubmit: (mode: ReconcileMode, reason: string, relatedRequestId: string) => void
}

function pairText(no: string | null, province: string | null, provinces: ReferenceLoad): string {
  if (no === null) return 'ไม่มีทะเบียน'
  return province === null ? `${no} (ยังไม่ระบุจังหวัด)` : `${no} · ${resolveOptionalCode(province, provinces)}`
}

export function RegistrationReconcileDialog({
  open,
  history,
  masterNo,
  masterProvince,
  provinces,
  initialRelatedRequestId,
  submitting,
  onCancel,
  onSubmit,
}: Props) {
  const [mode, setMode] = useState<ReconcileMode | null>(null)
  const [reason, setReason] = useState('')
  const [related, setRelated] = useState(initialRelatedRequestId)
  const [error, setError] = useState<string | null>(null)
  if (!open) return null
  const latest = history.items[history.items.length - 1]

  const submit = () => {
    if (mode === null) {
      setError('กรุณาเลือกวิธีปรับข้อมูลให้ตรงกัน')
      return
    }
    if (reason.trim() === '') {
      setError('กรุณาระบุเหตุผล')
      return
    }
    setError(null)
    onSubmit(mode, reason, related)
  }

  return (
    <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="registration-reconcile-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="registration-reconcile-title">ปรับข้อมูลทะเบียนให้ตรงกับประวัติ</h2>
        <div className="status-card__row">
          <span>ข้อมูลทะเบียนรถตอนนี้</span>
          <span>{pairText(masterNo, masterProvince, provinces)}</span>
        </div>
        <div className="status-card__row">
          <span>ประวัติล่าสุด</span>
          <span>
            {latest ? pairText(latest.new_registration_no, latest.new_registration_province_code, provinces) : '-'}
          </span>
        </div>
        <fieldset className="form-grid">
          <legend>วิธีปรับข้อมูล</legend>
          <label>
            <input
              type="radio"
              name="reconcile-mode"
              checked={mode === 'APPLY_RECORDED'}
              onChange={() => setMode('APPLY_RECORDED')}
              disabled={submitting}
            />{' '}
            ใช้ค่าตามประวัติล่าสุด (แก้ข้อมูลทะเบียนรถให้ตรงกับประวัติ)
          </label>
          <label>
            <input
              type="radio"
              name="reconcile-mode"
              checked={mode === 'ACCEPT_MASTER'}
              onChange={() => setMode('ACCEPT_MASTER')}
              disabled={submitting}
            />{' '}
            ยอมรับค่าปัจจุบันในข้อมูลทะเบียนรถ (บันทึกเพิ่มในประวัติเท่านั้น)
          </label>
        </fieldset>
        <div className="form-grid">
          <FormField label="เหตุผล (บังคับ)" htmlFor="registration-reconcile-reason" error={error ?? undefined}>
            <textarea
              id="registration-reconcile-reason"
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              disabled={submitting}
            />
          </FormField>
          <FormField
            label="รหัสคำขอที่เกี่ยวข้อง (ไม่บังคับ)"
            htmlFor="registration-reconcile-related"
            hint="ใช้อ้างอิงในประวัติเท่านั้น ไม่ได้ยืนยันผลของคำขอนั้น"
          >
            <input
              id="registration-reconcile-related"
              type="text"
              value={related}
              onChange={(event) => setRelated(event.target.value)}
              disabled={submitting}
            />
          </FormField>
        </div>
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>
            ยกเลิก
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : 'ยืนยันการปรับข้อมูล'}
          </button>
        </div>
      </div>
    </div>
  )
}
