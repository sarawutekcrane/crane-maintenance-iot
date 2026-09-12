import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
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
  MeterSnapshot,
  PmTask,
  PmTaskRevisionDetail,
  PmWorkOrderDetail,
  VehicleComponent,
  VehicleDetail,
} from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | {
      kind: 'ready'
      detail: PmWorkOrderDetail
      tasks: PmTask[]
      vehicleComponents: VehicleComponent[]
    }

const emptyDraft: PmTaskDraft = { completed: true, remark: '', readings: [], parts: [] }

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

    let vehicleComponents: VehicleComponent[] = []
    if (work_order.asset_type === 'VEHICLE') {
      const vehicleResult = await apiGet<VehicleDetail>(`/vehicles/${work_order.asset_id}`)
      if (vehicleResult.ok) vehicleComponents = vehicleResult.data.components
    }

    setState({ kind: 'ready', detail: woResult.data, tasks, vehicleComponents })
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

      let meterSnapshotId: string | null = null
      if (draft.readings.length > 0) {
        const snapshotResult = await apiPost<MeterSnapshot>('/meter-snapshots', {
          asset_type: state.detail.work_order.asset_type,
          asset_id: state.detail.work_order.asset_id,
          readings: draft.readings,
        })
        if (!snapshotResult.ok) {
          setSubmittingTask(null)
          const err = snapshotResult.error
          setTaskErrors((prev) => ({
            ...prev,
            [task.pm_task_id]: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
          }))
          return
        }
        meterSnapshotId = snapshotResult.data.meter_snapshot_id
      }

      const result = await apiPost<PmWorkOrderDetail>(
        `/pm/work-orders/${state.detail.work_order.pm_work_order_id}/results`,
        {
          pm_task_id: task.pm_task_id,
          completed: draft.completed,
          meter_snapshot_id: meterSnapshotId,
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
    await apiPost(`/pm/work-orders/${state.detail.work_order.pm_work_order_id}/close`, {
      note: closeNote.trim() || null,
    })
    setClosing(false)
    void load()
  }, [state, closeNote, load])

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
  const resultsByTask = new Map(results.map((r) => [r.pm_task_id, r]))
  const isOpen = work_order.status === 'OPEN'

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

      {state.tasks.map((task) => (
        <PmTaskCard
          key={task.pm_task_id}
          task={task}
          result={resultsByTask.get(task.pm_task_id) ?? null}
          vehicleComponents={state.vehicleComponents}
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
