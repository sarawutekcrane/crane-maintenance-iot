import { Card } from './Card'
import { inspectionResultLabel } from '../lib/labels'
import type { AttachmentInfo, ChecklistItem, InspectionResultValue } from '../lib/types'

const RESULT_OPTIONS: InspectionResultValue[] = ['PASS', 'FAIL', 'NA']

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
}

/**
 * One touch-friendly inspection item card (baseline "MOBILE INSPECTION"
 * requirement): title/point/method/standard/instruction, the reference
 * image (master guidance — separate from evidence below), large PASS/
 * FAIL/N/A buttons, and — only shown once FAIL is selected — the remark
 * and evidence-photo controls, so the user does not need to navigate away.
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
}: ChecklistItemCardProps) {
  const isFail = answer.result === 'FAIL'

  return (
    <Card className="checklist-item-card">
      <div className="checklist-item-card__header">
        <span className="checklist-item-card__sequence">{item.sequence}</span>
        <h3>{item.title}</h3>
      </div>

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

      {isFail && (
        <div className="checklist-item-card__fail-details">
          <div className="form-field">
            <label htmlFor={`remark-${item.item_id}`}>หมายเหตุ (จำเป็นเมื่อไม่ผ่าน)</label>
            <textarea
              id={`remark-${item.item_id}`}
              value={answer.remark}
              onChange={(event) => onRemarkChange(event.target.value)}
              placeholder="อธิบายลักษณะความผิดปกติที่พบ"
            />
          </div>

          <div className="form-field">
            <label htmlFor={`evidence-${item.item_id}`}>
              รูปถ่ายหลักฐาน{item.required_photo_on_fail ? ' (จำเป็น)' : ' (ถ้ามี)'}
            </label>
            <input
              id={`evidence-${item.item_id}`}
              type="file"
              accept="image/*"
              capture="environment"
              disabled={uploading}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) onAddEvidence(file)
                event.target.value = ''
              }}
            />
            {uploading && <p className="form-field__hint">กำลังอัปโหลดรูปภาพ...</p>}
            {answer.evidence.length > 0 && (
              <ul className="checklist-item-card__evidence-list">
                {answer.evidence.map((evidence) => (
                  <li key={evidence.attachment_id}>
                    <img src={evidence.url} alt={`หลักฐานสำหรับ ${item.title}`} />
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={() => onRemoveEvidence(evidence.attachment_id)}
                    >
                      ลบรูป
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
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
