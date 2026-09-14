import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { MachineStateReadOnly } from '../components/MachineStateReadOnly'
import { PmTaskCard, type PmTaskDraft } from '../components/PmTaskCard'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost, apiUpload } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  pmWorkOrderStatusLabel,
  pmWorkOrderStatusTone,
} from '../lib/labels'
import type {
  AttachmentInfo,
  PmTask,
  PmTaskRevisionDetail,
  PmWorkOrderDetail,
} from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | {
      kind: 'ready'
      detail: PmWorkOrderDetail
      tasks: PmTask[]
    }

const emptyDraft: PmTaskDraft = { completed: true, remark: '', parts: [] }

export function PmWorkOrderDetailPage() {
  const { workOrderId = '' } = useParams<{ workOrderId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [drafts, setDrafts] = useState<Record<string, PmTaskDraft>>({})
  const [evidenceByTask, setEvidenceByTask] = useState<Record<string, AttachmentInfo[]>>({})
  const [uploadingTask, setUploadingTask] = useState<string | null>(null)
  const [submittingTask, setSubmittingTask] = useState<string | null>(null)
  const [taskErrors, setTaskErrors] = useState<Record<string, string>>({})
  const [closing, setClosing] = useState(false)
  const [closeNote, setCloseNote] = useState('')
  const [closeError, setCloseError] = useState<string | null>(null)
  const [approvingScope, setApprovingScope] = useState(false)
  const [scopeError, setScopeError] = useState<string | null>(null)
  const [addTaskId, setAddTaskId] = useState('')
  const [addReason, setAddReason] = useState('')
  const [addingScopeTask, setAddingScopeTask] = useState(false)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const woResult = await apiGet<PmWorkOrderDetail>(`/pm/work-orders/${workOrderId}`)
    if (!woResult.ok) {
      const err = woResult.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    const { work_order } = woResult.data
    const revisionResult = await apiGet<PmTaskRevisionDetail>(
      `/pm/plans/${work_order.pm_plan_id}/revisions/${work_order.revision_id}`,
    )
    const tasks = revisionResult.ok ? [...revisionResult.data.tasks].sort((a, b) => a.sequence - b.sequence) : []

    setState({ kind: 'ready', detail: woResult.data, tasks })
  }, [workOrderId])

  useEffect(() => {
    void load()
  }, [load])

  const getDraft = (taskId: string): PmTaskDraft => drafts[taskId] ?? emptyDraft

  const addEvidence = useCallback(async (taskId: string, file: File) => {
    setUploadingTask(taskId)
    const formData = new FormData()
    formData.append('purpose', 'PM_EVIDENCE')
    formData.append('file', file)
    const result = await apiUpload<AttachmentInfo>('/attachments', formData)
    setUploadingTask(null)
    if (result.ok) {
      setEvidenceByTask((prev) => ({
        ...prev,
        [taskId]: [...(prev[taskId] ?? []), result.data],
      }))
    }
  }, [])

  const removeEvidence = useCallback((taskId: string, attachmentId: string) => {
    setEvidenceByTask((prev) => ({
      ...prev,
      [taskId]: (prev[taskId] ?? []).filter((item) => item.attachment_id !== attachmentId),
    }))
  }, [])

  const submitTask = useCallback(
    async (task: PmTask) => {
      if (state.kind !== 'ready') return
      const draft = drafts[task.pm_task_id] ?? emptyDraft
      setSubmittingTask(task.pm_task_id)
      setTaskErrors((prev) => ({ ...prev, [task.pm_task_id]: '' }))

      // Normal path: no manual counter/GPS entry — the backend
      // automatically captures current machine state for this result.
      const result = await apiPost<PmWorkOrderDetail>(
        `/pm/work-orders/${state.detail.work_order.pm_work_order_id}/results`,
        {
          pm_task_id: task.pm_task_id,
          completed: draft.completed,
          remark: draft.remark.trim() || null,
          used_parts: draft.parts.filter((p) => p.part_description.trim() !== ''),
          evidence_attachment_ids: (evidenceByTask[task.pm_task_id] ?? []).map((a) => a.attachment_id),
        },
      )
      setSubmittingTask(null)
      if (result.ok) {
        setDrafts((prev) => {
          const next = { ...prev }
          delete next[task.pm_task_id]
          return next
        })
        void load()
      } else {
        const err = result.error
        setTaskErrors((prev) => ({
          ...prev,
          [task.pm_task_id]: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        }))
      }
    },
    [state, drafts, evidenceByTask, load],
  )

  const closeWorkOrder = useCallback(async () => {
    if (state.kind !== 'ready') return
    setClosing(true)
    setCloseError(null)
    const result = await apiPost(`/pm/work-orders/${state.detail.work_order.pm_work_order_id}/close`, {
      note: closeNote.trim() || null,
    })
    setClosing(false)
    if (result.ok) {
      void load()
    } else {
      const err = result.error
      setCloseError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [state, closeNote, load])

  const approveScope = useCallback(async () => {
    if (state.kind !== 'ready') return
    setApprovingScope(true)
    setScopeError(null)
    const result = await apiPost<PmWorkOrderDetail>(
      `/pm/work-orders/${state.detail.work_order.pm_work_order_id}/scope/approve`,
      {},
    )
    setApprovingScope(false)
    if (result.ok) {
      void load()
    } else {
      const err = result.error
      setScopeError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [state, load])

  const addScopeTask = useCallback(async () => {
    if (state.kind !== 'ready' || !addTaskId || !addReason.trim()) return
    setAddingScopeTask(true)
    setScopeError(null)
    const result = await apiPost<PmWorkOrderDetail>(
      `/pm/work-orders/${state.detail.work_order.pm_work_order_id}/scope/add`,
      { pm_task_id: addTaskId, reason: addReason.trim() },
    )
    setAddingScopeTask(false)
    if (result.ok) {
      setAddTaskId('')
      setAddReason('')
      void load()
    } else {
      const err = result.error
      setScopeError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [state, addTaskId, addReason, load])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดใบสั่งงาน PM..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>ใบสั่งงาน PM</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { work_order, results } = state.detail
  const scope_additions = state.detail.scope_additions ?? []
  const scopeTaskIds = work_order.scope_task_ids ?? []
  const resultsByTask = new Map(results.map((r) => [r.pm_task_id, r]))
  const isOpen = work_order.status === 'OPEN'
  const scopeApproved = work_order.scope_approved_at != null
  const scopeTasks =
    scopeTaskIds.length > 0
      ? state.tasks.filter((t) => scopeTaskIds.includes(t.pm_task_id))
      : state.tasks
  const outOfScopeTasks =
    scopeTaskIds.length > 0 ? state.tasks.filter((t) => !scopeTaskIds.includes(t.pm_task_id)) : []

  return (
    <section className="page">
      <h1>ใบสั่งงาน PM</h1>
      <p>รหัสใบสั่งงาน: {work_order.pm_work_order_id}</p>

      <Card>
        <div className="status-card__row">
          <span>สินทรัพย์</span>
          <span>
            {assetTypeLabel[work_order.asset_type] ?? work_order.asset_type} — {work_order.asset_id}
          </span>
        </div>
        <div className="status-card__row">
          <span>สถานะ</span>
          <StatusBadge
            label={pmWorkOrderStatusLabel[work_order.status] ?? work_order.status}
            tone={pmWorkOrderStatusTone[work_order.status]}
          />
        </div>
        <div className="status-card__row">
          <span>เปิดใบสั่งงานเมื่อ</span>
          <span>{formatThaiDateTime(work_order.opened_at)}</span>
        </div>
        {work_order.closed_at && (
          <div className="status-card__row">
            <span>ปิดใบสั่งงานเมื่อ</span>
            <span>{formatThaiDateTime(work_order.closed_at)}</span>
          </div>
        )}
      </Card>

      <MachineStateReadOnly assetType={work_order.asset_type} assetId={work_order.asset_id} />

      <Card>
        <h2>ขอบเขตงาน PM</h2>
        <p className="form-field__hint">
          {scopeApproved
            ? `ขอบเขตงานอนุมัติแล้วเมื่อ ${formatThaiDateTime(work_order.scope_approved_at ?? '')} โดย ${
                work_order.scope_approved_by ?? 'ไม่ทราบ'
              } — ล็อกไม่สามารถเพิ่มกลุ่มงานได้อีก`
            : 'ยังไม่ได้อนุมัติขอบเขตงาน — สามารถเพิ่มกลุ่มงานที่ยังไม่ครบกำหนดล่วงหน้าได้ก่อนอนุมัติ'}
        </p>
        {scope_additions.length > 0 && (
          <details className="disclosure">
            <summary>รายการที่เพิ่มล่วงหน้า ({scope_additions.length})</summary>
            <ul>
              {scope_additions.map((addition) => (
                <li key={`${addition.pm_task_id}-${addition.added_at}`}>
                  {state.tasks.find((t) => t.pm_task_id === addition.pm_task_id)?.description ??
                    addition.pm_task_id}{' '}
                  — {addition.reason} ({formatThaiDateTime(addition.added_at)} โดย{' '}
                  {addition.added_by ?? 'ไม่ทราบ'})
                </li>
              ))}
            </ul>
          </details>
        )}
        {isOpen && !scopeApproved && outOfScopeTasks.length > 0 && (
          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="pm-scope-add-task">เพิ่มกลุ่มงานล่วงหน้า (จากแผนเดียวกันเท่านั้น)</label>
              <select
                id="pm-scope-add-task"
                value={addTaskId}
                onChange={(event) => setAddTaskId(event.target.value)}
              >
                <option value="">-- เลือกงาน --</option>
                {outOfScopeTasks.map((task) => (
                  <option key={task.pm_task_id} value={task.pm_task_id}>
                    {task.group ? `[${task.group}] ` : ''}
                    {task.description}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="pm-scope-add-reason">เหตุผลที่ทำก่อนกำหนด</label>
              <input
                id="pm-scope-add-reason"
                type="text"
                value={addReason}
                onChange={(event) => setAddReason(event.target.value)}
                placeholder="เช่น ใกล้ครบกำหนด/ตามความเห็นหัวหน้างาน"
              />
            </div>
            <button
              type="button"
              className="button button--secondary button--full-width"
              disabled={addingScopeTask || !addTaskId || !addReason.trim()}
              onClick={() => void addScopeTask()}
            >
              {addingScopeTask ? 'กำลังเพิ่ม...' : '+ เพิ่มเข้าขอบเขตงาน'}
            </button>
          </div>
        )}
        {isOpen && !scopeApproved && (
          <button
            type="button"
            className="button button--secondary button--full-width"
            disabled={approvingScope}
            onClick={() => void approveScope()}
          >
            {approvingScope ? 'กำลังอนุมัติ...' : 'อนุมัติขอบเขตงาน (ล็อกและสร้างใบเบิกอะไหล่)'}
          </button>
        )}
        {scopeError && (
          <p className="form-field__error" role="alert">
            {scopeError}
          </p>
        )}
      </Card>

      {scopeTasks.map((task) => (
        <PmTaskCard
          key={task.pm_task_id}
          task={task}
          result={resultsByTask.get(task.pm_task_id) ?? null}
          draft={getDraft(task.pm_task_id)}
          onDraftChange={(draft) =>
            setDrafts((prev) => ({ ...prev, [task.pm_task_id]: draft }))
          }
          onSubmit={() => void submitTask(task)}
          submitting={submittingTask === task.pm_task_id}
          error={taskErrors[task.pm_task_id]}
          evidence={evidenceByTask[task.pm_task_id] ?? []}
          uploadingEvidence={uploadingTask === task.pm_task_id}
          onAddEvidence={(file) => void addEvidence(task.pm_task_id, file)}
          onRemoveEvidence={(attachmentId) => removeEvidence(task.pm_task_id, attachmentId)}
        />
      ))}

      {isOpen && (
        <Card>
          <h2>ปิดใบสั่งงาน PM</h2>
          <div className="form-field">
            <label htmlFor="pm-close-note">หมายเหตุการปิดงาน (ถ้ามี)</label>
            <textarea
              id="pm-close-note"
              value={closeNote}
              onChange={(event) => setCloseNote(event.target.value)}
            />
          </div>
          {closeError && (
            <p className="form-field__error" role="alert">
              {closeError}
            </p>
          )}
          <div className="status-card__actions">
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={closing}
              onClick={() => void closeWorkOrder()}
            >
              {closing ? 'กำลังปิดงาน...' : 'ปิดใบสั่งงาน PM'}
            </button>
          </div>
        </Card>
      )}
    </section>
  )
}
