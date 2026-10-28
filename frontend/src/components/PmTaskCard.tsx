import { Link } from 'react-router-dom'
import { Card } from './Card'
import { PartRowsEditor } from './PartRowsEditor'
import { PhotoAttachmentField } from './PhotoAttachmentField'
import {
  PM_NOT_PERFORMED_REASONS,
  PM_OTHER_REASON,
  PM_PERFORMED_ACTIONS,
  partActionTypeLabel,
  pmItemDispositionLabel,
  pmTriggerTypeLabel,
} from '../lib/labels'
import type {
  AttachmentInfo,
  PmItemDisposition,
  PmItemOutcome,
  PmTask,
  PmUsedPartInput,
  PmWorkResult,
} from '../lib/types'

export interface PmTaskDraft {
  completed: boolean
  remark: string
  parts: PmUsedPartInput[]
  /** R4 PM Workflow (V2 work orders): the truthful item outcome. */
  disposition?: PmItemDisposition
  actions?: string[]
  reasonCode?: string
  otherText?: string
}

/** R4 PM Workflow: whether a V2 draft is complete enough to save (the server
 * validates the same rules again; this only keeps the button honest). */
function isPmOutcomeDraftValid(draft: PmTaskDraft): boolean {
  if (draft.disposition === 'PERFORMED') {
    const actions = draft.actions ?? []
    return actions.length >= 1 && actions.length <= 2
  }
  if (draft.disposition === 'NOT_PERFORMED') {
    if (!draft.reasonCode) return false
    return draft.reasonCode !== PM_OTHER_REASON || (draft.otherText ?? '').trim() !== ''
  }
  return false
}

interface PmTaskCardProps {
  task: PmTask
  result: PmWorkResult | null
  draft: PmTaskDraft
  onDraftChange: (draft: PmTaskDraft) => void
  onSubmit: () => void
  submitting: boolean
  error?: string
  evidence: AttachmentInfo[]
  uploadingEvidence: boolean
  onAddEvidence: (file: File) => void
  onRemoveEvidence: (attachmentId: string) => void
  /** R4 PM Workflow: V2 work orders record a truthful Performed / Not
   * Performed outcome instead of the legacy completed flag. */
  mode?: 'LEGACY' | 'V2'
  outcome?: PmItemOutcome | null
  /** V2 only: the work order is IN_PROGRESS and this item is not saved yet. */
  editable?: boolean
  /** V2 only: a Not Performed item may be saved only after a Performed one. */
  notPerformedAllowed?: boolean
}

/** One touch-friendly PM task card — mirrors `ChecklistItemCard`'s layout
 * pattern. A completed task shows its immutable historical result;
 * an incomplete one shows the entry form.
 *
 * Core Demo Fixes, PM WORKFLOW REDESIGN section E: the card visually
 * separates "มาตรฐานงาน" (what the task master/standard tells the
 * technician to do — group, trigger/interval, standard parts) from
 * "บันทึกผลการปฏิบัติงาน" (the execution/result state). Manual counter/GPS
 * entry is not part of this card — the work order's own machine-state
 * snapshot is captured automatically by the backend (see
 * MachineStateReadOnly on the work-order page). */
export function PmTaskCard({
  task,
  result,
  draft,
  onDraftChange,
  onSubmit,
  submitting,
  error,
  evidence,
  uploadingEvidence,
  onAddEvidence,
  onRemoveEvidence,
  mode = 'LEGACY',
  outcome = null,
  editable = true,
  notPerformedAllowed = true,
}: PmTaskCardProps) {
  const v2 = mode === 'V2'
  // V2: read-only unless the work order is IN_PROGRESS and the item has no Outcome yet (an item whose
  // factual result was saved without its Outcome stays editable so an identical retry completes it).
  const readOnly = v2 ? !editable : result != null
  if (readOnly) {
    return (
      <Card className="pm-task-card">
        <div className="pm-task-card__header">
          <span className="pm-task-card__sequence">{task.sequence}</span>
          <h3>{task.description}</h3>
        </div>
        {v2 ? (
          outcome ? (
            <div>
              <p>ผลงาน: {pmItemDispositionLabel[outcome.disposition] ?? outcome.disposition}</p>
              {outcome.disposition === 'PERFORMED' ? (
                <p>สิ่งที่ทำ: {outcome.performed_actions.join(', ')}</p>
              ) : (
                <p>
                  เหตุผลที่ไม่ได้ดำเนินการ: {outcome.reason_code}
                  {outcome.other_text ? ` — ${outcome.other_text}` : ''}
                </p>
              )}
            </div>
          ) : (
            <p className="form-field__hint">{result ? 'บันทึกไม่ครบ — บันทึกรายการนี้อีกครั้ง' : 'ยังไม่ได้บันทึก'}</p>
          )
        ) : (
          result && <p>ผลงาน: {result.completed ? 'เสร็จสิ้น' : 'ยังไม่เสร็จสิ้น / พบปัญหา'}</p>
        )}
        {result?.remark && <p>หมายเหตุ: {result.remark}</p>}
        {result && result.used_parts.length > 0 && (
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
        {result?.meter_snapshot_id && (
          <p className="form-field__hint">บันทึกค่ามาตรวัดแล้ว ({result.meter_snapshot_id})</p>
        )}
        {evidence.length > 0 && (
          <div className="checklist-item-card__reference">
            <p className="form-field__hint">รูปถ่ายหลักฐาน</p>
            <ul className="checklist-item-card__evidence-list">
              {evidence.map((attachment) => (
                <li key={attachment.attachment_id}>
                  <img src={attachment.url} alt={`หลักฐานสำหรับ ${task.description}`} />
                </li>
              ))}
            </ul>
          </div>
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

      <div className="pm-task-card__standard">
        <p className="form-field__hint">มาตรฐานงาน</p>
        {task.group && <p>กลุ่มงาน: {task.group}</p>}
        {task.trigger_type && <p>เงื่อนไขครบกำหนด: {pmTriggerTypeLabel[task.trigger_type]}</p>}
        {task.interval_value != null && (
          <p>
            รอบ: ทุก {task.interval_value} {task.interval_unit ?? ''}
          </p>
        )}
        {task.standard_parts.length > 0 && (
          <div>
            <p className="form-field__hint">อะไหล่มาตรฐานตามแผน (ไม่สามารถแก้ไขได้จากหน้านี้)</p>
            <ul>
              {task.standard_parts.map((part) => (
                <li key={part.pm_task_part_id}>
                  {part.part_description}
                  {part.quantity != null ? ` x${part.quantity}${part.unit ?? ''}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <p className="form-field__hint">บันทึกผลการปฏิบัติงาน</p>
      {v2 ? (
        <V2OutcomeFields
          task={task}
          draft={draft}
          onDraftChange={onDraftChange}
          notPerformedAllowed={notPerformedAllowed}
        />
      ) : (
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
      )}

      <div className="form-field">
        <label htmlFor={`pm-remark-${task.pm_task_id}`}>หมายเหตุ (ถ้ามี)</label>
        <textarea
          id={`pm-remark-${task.pm_task_id}`}
          value={draft.remark}
          onChange={(event) => onDraftChange({ ...draft, remark: event.target.value })}
        />
      </div>

      <div className="form-field">
        <label>อะไหล่ที่ใช้จริง (ถ้ามี)</label>
        <PartRowsEditor
          parts={draft.parts}
          onChange={(parts) => onDraftChange({ ...draft, parts })}
        />
      </div>

      <PhotoAttachmentField
        id={`pm-evidence-${task.pm_task_id}`}
        label="รูปถ่ายหลักฐาน (ถ้ามี)"
        attachments={evidence}
        uploading={uploadingEvidence}
        onAddFile={onAddEvidence}
        onRemove={onRemoveEvidence}
        altPrefix={`หลักฐานสำหรับ ${task.description}`}
      />

      {error && (
        <p className="form-field__error" role="alert">
          {error}
        </p>
      )}

      <div className="status-card__actions">
        <button
          type="button"
          className="button button--primary button--full-width"
          disabled={
            submitting ||
            (v2 &&
              (!isPmOutcomeDraftValid(draft) || (draft.disposition === 'NOT_PERFORMED' && !notPerformedAllowed)))
          }
          onClick={onSubmit}
        >
          {submitting ? 'กำลังบันทึก...' : 'บันทึกผลงาน'}
        </button>
      </div>
    </Card>
  )
}

/** R4 PM Workflow (Q-R4-03): Performed with one or two approved actions, or
 * Not Performed with exactly one approved reason (Other needs a written
 * explanation). A Not Performed choice stays an unsaved draft until a
 * Performed item has been saved. */
function V2OutcomeFields({
  task,
  draft,
  onDraftChange,
  notPerformedAllowed,
}: {
  task: PmTask
  draft: PmTaskDraft
  onDraftChange: (draft: PmTaskDraft) => void
  notPerformedAllowed: boolean
}) {
  const actions = draft.actions ?? []
  const toggleAction = (action: string) => {
    const next = actions.includes(action) ? actions.filter((a) => a !== action) : [...actions, action]
    onDraftChange({ ...draft, actions: next })
  }
  return (
    <div>
      <div className="checklist-item-card__result-group" role="radiogroup" aria-label={`ผลงานสำหรับ ${task.description}`}>
        <button
          type="button"
          role="radio"
          aria-checked={draft.disposition === 'PERFORMED'}
          className={
            draft.disposition === 'PERFORMED'
              ? 'button result-button result-button--pass result-button--selected'
              : 'button button--secondary result-button result-button--pass'
          }
          onClick={() => onDraftChange({ ...draft, disposition: 'PERFORMED', reasonCode: '', otherText: '' })}
        >
          ดำเนินการแล้ว
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={draft.disposition === 'NOT_PERFORMED'}
          className={
            draft.disposition === 'NOT_PERFORMED'
              ? 'button result-button result-button--fail result-button--selected'
              : 'button button--secondary result-button result-button--fail'
          }
          onClick={() => onDraftChange({ ...draft, disposition: 'NOT_PERFORMED', actions: [] })}
        >
          ไม่ได้ดำเนินการ
        </button>
      </div>
      {draft.disposition === 'PERFORMED' && (
        <fieldset className="form-field">
          <legend>สิ่งที่ทำจริง (เลือก 1–2 รายการ)</legend>
          {PM_PERFORMED_ACTIONS.map((action) => (
            <label key={action} className="checkbox-row">
              <input
                type="checkbox"
                checked={actions.includes(action)}
                disabled={!actions.includes(action) && actions.length >= 2}
                onChange={() => toggleAction(action)}
              />{' '}
              {action}
            </label>
          ))}
        </fieldset>
      )}
      {draft.disposition === 'NOT_PERFORMED' && (
        <div className="form-field">
          <label htmlFor={`pm-reason-${task.pm_task_id}`}>เหตุผลที่ไม่ได้ดำเนินการ (เลือก 1 เหตุผล)</label>
          <select
            id={`pm-reason-${task.pm_task_id}`}
            value={draft.reasonCode ?? ''}
            onChange={(event) => onDraftChange({ ...draft, reasonCode: event.target.value })}
          >
            <option value="">-- เลือกเหตุผล --</option>
            {PM_NOT_PERFORMED_REASONS.map((reason) => (
              <option key={reason} value={reason}>
                {reason}
              </option>
            ))}
          </select>
          {draft.reasonCode === PM_OTHER_REASON && (
            <textarea
              aria-label="ระบุเหตุผลอื่น"
              value={draft.otherText ?? ''}
              onChange={(event) => onDraftChange({ ...draft, otherText: event.target.value })}
              placeholder="ระบุเหตุผล"
            />
          )}
          {!notPerformedAllowed && (
            <p className="form-field__hint" role="note">
              ต้องบันทึกรายการที่ &quot;ดำเนินการแล้ว&quot; อย่างน้อย 1 รายการก่อน จึงจะบันทึกรายการที่ไม่ได้ดำเนินการได้
            </p>
          )}
        </div>
      )}
    </div>
  )
}
