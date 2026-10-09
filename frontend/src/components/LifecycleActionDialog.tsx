import { useState } from 'react'
import { FormField } from './FormField'

export type LifecycleDialogMode = 'deactivate' | 'reactivate' | 'reconcile'

const TITLES: Record<LifecycleDialogMode, string> = {
  deactivate: 'ปิดใช้งาน',
  reactivate: 'เปิดใช้งานอีกครั้ง',
  reconcile: 'ซิงก์สถานะให้ตรงกับประวัติล่าสุด',
}

interface LifecycleActionDialogProps {
  open: boolean
  mode: LifecycleDialogMode
  /** e.g. "บุคลากร" / "แผนก" */
  entityLabel: string
  entityId: string
  displayName: string
  currentStateLabel: string
  targetStateLabel: string
  /** Extra consequence note (e.g. that a personnel record is not a login account). */
  note?: string
  submitting: boolean
  error?: { message: string; requestId?: string | null } | null
  onCancel: () => void
  onConfirm: (reason: string) => void
}

/**
 * R2 Batch R2e — confirmation of a lifecycle action (the project's
 * alertdialog pattern, never `window.confirm`). Shows the stable id, the
 * name, the current and the target state, that nothing is deleted, and
 * requires a reason in BOTH directions (and for a reconciliation). The reason
 * lives only in this dialog, so there is no page-level unsaved warning.
 */
export function LifecycleActionDialog({
  open,
  mode,
  entityLabel,
  entityId,
  displayName,
  currentStateLabel,
  targetStateLabel,
  note,
  submitting,
  error = null,
  onCancel,
  onConfirm,
}: LifecycleActionDialogProps) {
  const [reason, setReason] = useState('')
  if (!open) return null
  const titleId = 'lifecycle-action-dialog-title'
  const reasonMissing = !reason.trim()

  return (
    <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>
          {TITLES[mode]}: {entityLabel}
        </h2>
        <dl className="lifecycle-dialog__facts">
          <dt>รหัส</dt>
          <dd>
            <code>{entityId}</code>
          </dd>
          <dt>ชื่อ</dt>
          <dd>{displayName}</dd>
          <dt>สถานะปัจจุบัน</dt>
          <dd>{currentStateLabel}</dd>
          <dt>สถานะหลังดำเนินการ</dt>
          <dd>{targetStateLabel}</dd>
        </dl>
        <p className="lifecycle-dialog__note">
          ข้อมูลและประวัติทั้งหมดยังคงอยู่ ไม่มีการลบข้อมูล และรหัสเดิมยังใช้อ้างอิงได้
        </p>
        {note && <p className="lifecycle-dialog__note">{note}</p>}
        <div className="form-grid">
          <FormField label="เหตุผล (จำเป็น)" htmlFor="lifecycle-action-reason">
            <textarea
              id="lifecycle-action-reason"
              value={reason}
              maxLength={500}
              required
              onChange={(event) => setReason(event.target.value)}
            />
          </FormField>
        </div>
        {error && (
          <div className="form-field__error" role="alert">
            <p>{error.message}</p>
            {error.requestId && <p className="state-panel__meta">รหัสอ้างอิง: {error.requestId}</p>}
          </div>
        )}
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>
            ยกเลิก
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => onConfirm(reason)}
            disabled={submitting || reasonMissing}
          >
            {submitting ? 'กำลังบันทึก...' : `ยืนยัน${TITLES[mode]}`}
          </button>
        </div>
      </div>
    </div>
  )
}
