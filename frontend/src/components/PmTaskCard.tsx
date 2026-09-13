import { Link } from 'react-router-dom'
import { Card } from './Card'
import { MeterSnapshotFields } from './MeterSnapshotFields'
import { PartRowsEditor } from './PartRowsEditor'
import { partActionTypeLabel, pmTriggerTypeLabel } from '../lib/labels'
import type {
  AttachmentInfo,
  MeterReadingInput,
  PmTask,
  PmUsedPartInput,
  PmWorkResult,
  VehicleComponent,
} from '../lib/types'

export interface PmTaskDraft {
  completed: boolean
  remark: string
  readings: MeterReadingInput[]
  parts: PmUsedPartInput[]
}

interface PmTaskCardProps {
  task: PmTask
  result: PmWorkResult | null
  vehicleComponents: VehicleComponent[]
  draft: PmTaskDraft
  onDraftChange: (draft: PmTaskDraft) => void
  onSubmit: () => void
  submitting: boolean
  error?: string
  evidence: AttachmentInfo[]
  uploadingEvidence: boolean
  onAddEvidence: (file: File) => void
  onRemoveEvidence: (attachmentId: string) => void
}

/** One touch-friendly PM task card — mirrors `ChecklistItemCard`'s layout
 * pattern. A completed task shows its immutable historical result;
 * an incomplete one shows the entry form. */
export function PmTaskCard({
  task,
  result,
  vehicleComponents,
  draft,
  onDraftChange,
  onSubmit,
  submitting,
  error,
  evidence,
  uploadingEvidence,
  onAddEvidence,
  onRemoveEvidence,
}: PmTaskCardProps) {
  if (result) {
    return (
      <Card className="pm-task-card">
        <div className="pm-task-card__header">
          <span className="pm-task-card__sequence">{task.sequence}</span>
          <h3>{task.description}</h3>
        </div>
        <p>ผลงาน: {result.completed ? 'เสร็จสิ้น' : 'ยังไม่เสร็จสิ้น / พบปัญหา'}</p>
        {result.remark && <p>หมายเหตุ: {result.remark}</p>}
        {result.used_parts.length > 0 && (
          <div>
            <p className="form-field__hint">อะไหล่ที่ใช้จริง</p>
            <ul>
              {result.used_parts.map((part) => (
                <li key={part.pm_used_part_id}>
                  {part.part_description}
                  {part.quantity != null ? ` x${part.quantity}${part.unit ?? ''}` : ''}
                  {part.action && ` — ${partActionTypeLabel[part.action]}`}
                  {part.part_instance_id && (
                    <>
                      {' '}
                      (<Link to={`/part-instances/${part.part_instance_id}`}>{part.part_instance_id}</Link>)
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {result.meter_snapshot_id && (
          <p className="form-field__hint">บันทึกค่ามาตรวัดแล้ว ({result.meter_snapshot_id})</p>
        )}
      </Card>
    )
  }

  return (
    <Card className="pm-task-card">
      <div className="pm-task-card__header">
        <span className="pm-task-card__sequence">{task.sequence}</span>
        <h3>{task.description}</h3>
      </div>
      {task.trigger_type && <p>เงื่อนไขครบกำหนด: {pmTriggerTypeLabel[task.trigger_type]}</p>}

      <div
        className="checklist-item-card__result-group"
        role="radiogroup"
        aria-label={`ผลงานสำหรับ ${task.description}`}
      >
        <button
          type="button"
          role="radio"
          aria-checked={draft.completed}
          className={
            draft.completed
              ? 'button result-button result-button--pass result-button--selected'
              : 'button button--secondary result-button result-button--pass'
          }
          onClick={() => onDraftChange({ ...draft, completed: true })}
        >
          เสร็จสิ้น
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={!draft.completed}
          className={
            !draft.completed
              ? 'button result-button result-button--fail result-button--selected'
              : 'button button--secondary result-button result-button--fail'
          }
          onClick={() => onDraftChange({ ...draft, completed: false })}
        >
          ยังไม่เสร็จสิ้น / พบปัญหา
        </button>
      </div>

      <div className="form-field">
        <label htmlFor={`pm-remark-${task.pm_task_id}`}>หมายเหตุ (ถ้ามี)</label>
        <textarea
          id={`pm-remark-${task.pm_task_id}`}
          value={draft.remark}
          onChange={(event) => onDraftChange({ ...draft, remark: event.target.value })}
        />
      </div>

      {vehicleComponents.length > 0 && (
        <div>
          <p className="form-field__hint">บันทึกค่ามาตรวัด (ถ้ามี)</p>
          <MeterSnapshotFields
            components={vehicleComponents}
            onChange={(readings) => onDraftChange({ ...draft, readings })}
          />
        </div>
      )}

      <div className="form-field">
        <label>อะไหล่ที่ใช้จริง (ถ้ามี)</label>
        <PartRowsEditor
          parts={draft.parts}
          onChange={(parts) => onDraftChange({ ...draft, parts })}
        />
      </div>

      <div className="form-field">
        <label htmlFor={`pm-evidence-${task.pm_task_id}`}>รูปถ่ายหลักฐาน (ถ้ามี)</label>
        <input
          id={`pm-evidence-${task.pm_task_id}`}
          type="file"
          accept="image/*"
          capture="environment"
          disabled={uploadingEvidence}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onAddEvidence(file)
            event.target.value = ''
          }}
        />
        {uploadingEvidence && <p className="form-field__hint">กำลังอัปโหลดรูปภาพ...</p>}
        {evidence.length > 0 && (
          <ul className="checklist-item-card__evidence-list">
            {evidence.map((item) => (
              <li key={item.attachment_id}>
                <img src={item.url} alt={`หลักฐานสำหรับ ${task.description}`} />
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => onRemoveEvidence(item.attachment_id)}
                >
                  ลบรูป
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && (
        <p className="form-field__error" role="alert">
          {error}
        </p>
      )}

      <div className="status-card__actions">
        <button
          type="button"
          className="button button--primary button--full-width"
          disabled={submitting}
          onClick={onSubmit}
        >
          {submitting ? 'กำลังบันทึก...' : 'บันทึกผลงาน'}
        </button>
      </div>
    </Card>
  )
}
