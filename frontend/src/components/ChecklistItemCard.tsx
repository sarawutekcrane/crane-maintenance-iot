import { Card } from './Card'
import { PhotoAttachmentField } from './PhotoAttachmentField'
import {
  ABNORMAL_INSPECTION_RESULTS,
  inspectionDueReasonLabel,
  inspectionResultLabel,
  NEW_INSPECTION_RESULTS,
  NOT_INSTALLED_NOTE,
} from '../lib/labels'
import type { AttachmentInfo, ChecklistItem, InspectionResultValue } from '../lib/types'

const RESULT_OPTIONS: readonly InspectionResultValue[] = NEW_INSPECTION_RESULTS

export interface ChecklistItemAnswer {
  result: InspectionResultValue | null
  remark: string
  evidence: AttachmentInfo[]
}

interface ChecklistItemCardProps {
  item: ChecklistItem
  answer: ChecklistItemAnswer
  uploading: boolean
  error?: string
  onResultChange: (result: InspectionResultValue) => void
  onRemarkChange: (remark: string) => void
  onAddEvidence: (file: File) => void
  onRemoveEvidence: (attachmentId: string) => void
  /** R3: why this item is shown today (DAILY / FIRST_WEEKLY / WEEKLY_DUE). */
  dueReason?: string
}

/**
 * One touch-friendly inspection item card (baseline "MOBILE INSPECTION"
 * requirement): title/point/method/standard/instruction, the reference
 * image (master guidance — separate from evidence below), large result
 * buttons, and — only shown once an abnormal result is selected — the remark
 * and evidence-photo controls, so the user does not need to navigate away.
 *
 * R3 (contract §4): four results — ปกติ / ผิดปกติ / ใช้งานได้รอการแก้ไข /
 * ไม่มีอุปกรณ์ติดตั้ง. Both abnormal results need a remark; photos are always
 * optional (the per-item photo/remark flags no longer apply to new entries).
 */
export function ChecklistItemCard({
  item,
  answer,
  uploading,
  error,
  onResultChange,
  onRemarkChange,
  onAddEvidence,
  onRemoveEvidence,
  dueReason,
}: ChecklistItemCardProps) {
  const isAbnormal = answer.result !== null && ABNORMAL_INSPECTION_RESULTS.includes(answer.result)

  return (
    <Card className="checklist-item-card">
      <div className="checklist-item-card__header">
        <span className="checklist-item-card__sequence">{item.sequence}</span>
        <h3>{item.title}</h3>
      </div>
      {dueReason && (
        <p className="form-field__hint" data-testid="inspection-due-reason">
          {inspectionDueReasonLabel[dueReason] ?? dueReason}
        </p>
      )}

      {item.inspection_point && <p>จุดตรวจ: {item.inspection_point}</p>}
      {item.method && <p>วิธีตรวจ: {item.method}</p>}
      {item.standard && <p>เกณฑ์ยอมรับ: {item.standard}</p>}
      {item.instruction && <p>คำแนะนำ: {item.instruction}</p>}

      {item.reference_image && (
        <div className="checklist-item-card__reference">
          <p className="form-field__hint">ภาพอ้างอิง (ตัวอย่างจุดตรวจ)</p>
          <img
            src={item.reference_image.url}
            alt={`ภาพอ้างอิงสำหรับ ${item.title}`}
            loading="lazy"
          />
        </div>
      )}

      <div
        className="checklist-item-card__result-group"
        role="radiogroup"
        aria-label={`ผลการตรวจสำหรับ ${item.title}`}
      >
        {RESULT_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={answer.result === option}
            className={
              answer.result === option
                ? `button result-button result-button--${option.toLowerCase()} result-button--selected`
                : `button button--secondary result-button result-button--${option.toLowerCase()}`
            }
            onClick={() => onResultChange(option)}
          >
            {inspectionResultLabel[option]}
          </button>
        ))}
      </div>

      {answer.result === 'NOT_INSTALLED' && (
        <p className="form-field__hint" data-testid="not-installed-note">
          {NOT_INSTALLED_NOTE}
        </p>
      )}

      {isAbnormal && (
        <div className="checklist-item-card__fail-details">
          <div className="form-field">
            <label htmlFor={`remark-${item.item_id}`}>หมายเหตุ (จำเป็น)</label>
            <textarea
              id={`remark-${item.item_id}`}
              value={answer.remark}
              onChange={(event) => onRemarkChange(event.target.value)}
              placeholder="อธิบายลักษณะความผิดปกติที่พบ"
            />
          </div>

          <PhotoAttachmentField
            id={`evidence-${item.item_id}`}
            label="รูปถ่ายหลักฐาน (ถ้ามี)"
            attachments={answer.evidence}
            uploading={uploading}
            onAddFile={onAddEvidence}
            onRemove={onRemoveEvidence}
            altPrefix={`หลักฐานสำหรับ ${item.title}`}
          />
        </div>
      )}

      {error && (
        <p className="form-field__error" role="alert">
          {error}
        </p>
      )}
    </Card>
  )
}
