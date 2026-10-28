import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { JobAssignmentSection } from '../components/JobAssignmentSection'
import { MachineStateReadOnly } from '../components/MachineStateReadOnly'
import { PmTaskCard, type PmTaskDraft } from '../components/PmTaskCard'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost, apiPostWithRequestId, apiUpload } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_PM, CAN_REPORT_REPAIR } from '../lib/capabilityNames'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  pmTransitionActionLabel,
  pmWorkOrderStatusLabel,
  pmWorkOrderStatusTone,
} from '../lib/labels'
import type { TechnicianAssignments } from '../lib/technicianV2'
import type {
  AttachmentInfo,
  PmItemOutcome,
  PmItemSaveResponse,
  PmOutstandingItem,
  PmTask,
  PmTaskRevisionDetail,
  PmWorkOrderDetail,
  PmWorkOrderTransition,
  RepairRequest,
  SubmitRepairRequestResponse,
} from '../lib/types'

/** R4 PM Workflow: one client intent id per lifecycle click (the server
 * treats a re-send of the same id + body as the same change). */
function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `${Date.now().toString(16)}-0000-4000-8000-${Math.random().toString(16).slice(2, 14).padEnd(12, '0')}`
}

function errorText(err: unknown): string {
  return err instanceof ApiError ? describeErrorCode(err.code) : err instanceof Error ? err.message : String(err)
}

/** R4 PM Workflow: the V2 lifecycle data (journal, Outcomes, effective Outstanding). */
interface WorkflowData {
  outcomes: Record<string, PmItemOutcome>
  history: PmWorkOrderTransition[]
  outstanding: PmOutstandingItem[]
}

const emptyWorkflow: WorkflowData = { outcomes: {}, history: [], outstanding: [] }

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
  const { hasCapability } = useCapabilities()
  const canManagePm = hasCapability(CAN_MANAGE_PM)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [drafts, setDrafts] = useState<Record<string, PmTaskDraft>>({})
  const [evidenceByTask, setEvidenceByTask] = useState<Record<string, AttachmentInfo[]>>({})
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [uploadingTask, setUploadingTask] = useState<string | null>(null)
  const [submittingTask, setSubmittingTask] = useState<string | null>(null)
  const [taskErrors, setTaskErrors] = useState<Record<string, string>>({})
  // Core Demo Fixes Delta REV06 section 16 — smallest safe addition
  // letting a technician report a PM defect via Repair Request (never a
  // direct RPR) from this same screen, preserving PM provenance
  // (source_type=PM_RESULT, source_id=<pm_work_result_id>).
  const [defectFormOpenFor, setDefectFormOpenFor] = useState<string | null>(null)
  const [defectSymptom, setDefectSymptom] = useState('')
  const [defectSubmitting, setDefectSubmitting] = useState(false)
  const [defectError, setDefectError] = useState<string | null>(null)
  // Web UAT Defect Fix UAT-F3: "already reported" derived from persisted
  // Repair Request data (GET /repair-requests/by-source/PM_RESULT/<id>)
  // instead of only client-side React state — previously this reset on
  // every reload even though the Repair Request still existed
  // server-side, inviting a duplicate report.
  const [existingDefectRequestsByResult, setExistingDefectRequestsByResult] = useState<
    Record<string, RepairRequest[]>
  >({})
  const [closing, setClosing] = useState(false)
  const [closeNote, setCloseNote] = useState('')
  const [closeError, setCloseError] = useState<string | null>(null)
  const [approvingScope, setApprovingScope] = useState(false)
  const [scopeError, setScopeError] = useState<string | null>(null)
  const [addTaskId, setAddTaskId] = useState('')
  const [addReason, setAddReason] = useState('')
  const [addingScopeTask, setAddingScopeTask] = useState(false)
  const [workflow, setWorkflow] = useState<WorkflowData>(emptyWorkflow)
  const [lifecycleBusy, setLifecycleBusy] = useState(false)
  const [lifecycleError, setLifecycleError] = useState<string | null>(null)
  const [returnReason, setReturnReason] = useState('')
  const [cancelReason, setCancelReason] = useState('')

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

    // F2 cross-phase integration fix: resolve this work order's own
    // PM_EVIDENCE attachments (uploaded with source_type=PM_WORK_ORDER,
    // source_id=workOrderId — see addEvidence below) so previously-
    // submitted task-result evidence remains visible after navigation/
    // reload, not just during the same in-memory session. Reuses the
    // existing, already-authorized by-source attachment endpoint. Honest
    // about Sheets-mode support: if the by-source fetch fails (e.g. this
    // is a still-stubbed repository path), the page shows that error
    // rather than silently pretending there is no evidence.
    const evidenceResult = await apiGet<AttachmentInfo[]>(
      `/attachments/by-source/PM_WORK_ORDER/${workOrderId}`,
    )
    if (evidenceResult.ok) {
      const byId = Object.fromEntries(evidenceResult.data.map((a) => [a.attachment_id, a]))
      setEvidenceError(null)
      setEvidenceByTask((prev) => {
        const next = { ...prev }
        for (const result of woResult.data.results) {
          next[result.pm_task_id] = result.evidence_attachment_ids
            .map((id) => byId[id])
            .filter((a): a is AttachmentInfo => a != null)
        }
        return next
      })
    } else {
      const err = evidenceResult.error
      setEvidenceError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }

    // Web UAT Defect Fix UAT-F3: re-derive "already reported" from
    // persisted data on every load (initial mount, reload, and after
    // reportPmDefect below), rather than only in-memory state — one
    // by-source lookup per recorded task result.
    const defectLookups = await Promise.all(
      woResult.data.results.map(async (result) => {
        const lookup = await apiGet<RepairRequest[]>(
          `/repair-requests/by-source/PM_RESULT/${result.pm_work_result_id}`,
        )
        return [result.pm_work_result_id, lookup.ok ? lookup.data : []] as const
      }),
    )
    setExistingDefectRequestsByResult(Object.fromEntries(defectLookups))

    // R4 PM Workflow: V2 work orders also load their Outcomes, lifecycle history and effective
    // Outstanding items (an actor without access simply sees none — the server decides).
    if (work_order.assignment_model === 'TECHNICIAN_V2') {
      const [outcomes, history, outstanding] = await Promise.all([
        apiGet<PmItemOutcome[]>(`/pm/work-orders/${workOrderId}/outcomes`),
        apiGet<PmWorkOrderTransition[]>(`/pm/work-orders/${workOrderId}/history`),
        apiGet<PmOutstandingItem[]>(`/pm/work-orders/${workOrderId}/outstanding`),
      ])
      // Anything but a list is treated as nothing recorded (fail closed: no actions unlocked).
      setWorkflow({
        outcomes:
          outcomes.ok && Array.isArray(outcomes.data)
            ? Object.fromEntries(outcomes.data.map((o) => [o.pm_task_id, o]))
            : {},
        history: history.ok && Array.isArray(history.data) ? history.data : [],
        outstanding: outstanding.ok && Array.isArray(outstanding.data) ? outstanding.data : [],
      })
    } else {
      setWorkflow(emptyWorkflow)
    }

    setState({ kind: 'ready', detail: woResult.data, tasks })
  }, [workOrderId])

  useEffect(() => {
    void load()
  }, [load])

  const getDraft = (taskId: string): PmTaskDraft => drafts[taskId] ?? emptyDraft

  const addEvidence = useCallback(async (taskId: string, file: File) => {
    setUploadingTask(taskId)
    setTaskErrors((prev) => ({ ...prev, [taskId]: '' }))
    const formData = new FormData()
    formData.append('purpose', 'PM_EVIDENCE')
    formData.append('source_type', 'PM_WORK_ORDER')
    formData.append('source_id', workOrderId)
    formData.append('file', file)
    const result = await apiUpload<AttachmentInfo>('/attachments', formData)
    setUploadingTask(null)
    if (result.ok) {
      setEvidenceByTask((prev) => ({
        ...prev,
        [taskId]: [...(prev[taskId] ?? []), result.data],
      }))
    } else {
      const err = result.error
      setTaskErrors((prev) => ({
        ...prev,
        [taskId]: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      }))
    }
  }, [workOrderId])

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
      const workOrderPath = `/pm/work-orders/${state.detail.work_order.pm_work_order_id}`
      const common = {
        remark: draft.remark.trim() || null,
        used_parts: draft.parts.filter((p) => p.part_description.trim() !== ''),
        evidence_attachment_ids: (evidenceByTask[task.pm_task_id] ?? []).map((a) => a.attachment_id),
      }
      // R4 PM Workflow: a V2 item is saved as a truthful Performed / Not Performed outcome.
      const result =
        state.detail.work_order.assignment_model === 'TECHNICIAN_V2'
          ? await apiPost<PmItemSaveResponse>(`${workOrderPath}/items/${task.pm_task_id}/outcome`, {
              ...common,
              disposition: draft.disposition,
              performed_actions: draft.disposition === 'PERFORMED' ? draft.actions ?? [] : [],
              reason_code: draft.disposition === 'NOT_PERFORMED' ? draft.reasonCode || null : null,
              other_text: draft.disposition === 'NOT_PERFORMED' ? draft.otherText?.trim() || null : null,
            })
          : await apiPost<PmWorkOrderDetail>(`${workOrderPath}/results`, {
              ...common,
              pm_task_id: task.pm_task_id,
              completed: draft.completed,
            })
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

  /** R4 PM Workflow: one E01 lifecycle change (START / SUBMIT / RETURN / CLOSE / CANCEL). */
  const runTransition = useCallback(
    async (action: 'start' | 'submit' | 'return' | 'close' | 'cancel', body: Record<string, unknown>) => {
      if (state.kind !== 'ready') return
      setLifecycleBusy(true)
      setLifecycleError(null)
      const jobPath = `/pm/work-orders/${state.detail.work_order.pm_work_order_id}`
      let payload = body
      if (action === 'submit') {
        const assignments = await apiGet<TechnicianAssignments>(`${jobPath}/technician-assignments`)
        if (!assignments.ok || !assignments.data.current) {
          setLifecycleBusy(false)
          setLifecycleError(assignments.ok ? 'ยังไม่มีทีมช่างปัจจุบันของงานนี้' : errorText(assignments.error))
          return
        }
        payload = { expected_set_id: assignments.data.current.assignment_set_id }
      }
      const result = await apiPostWithRequestId<PmWorkOrderDetail>(`${jobPath}/${action}`, payload, newRequestId())
      setLifecycleBusy(false)
      if (result.ok) {
        setReturnReason('')
        setCancelReason('')
        setCloseNote('')
        void load()
      } else {
        setLifecycleError(errorText(result.error))
      }
    },
    [state, load],
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

  const reportPmDefect = useCallback(
    async (pmWorkResultId: string) => {
      if (state.kind !== 'ready' || !defectSymptom.trim()) return
      setDefectSubmitting(true)
      setDefectError(null)
      const result = await apiPost<SubmitRepairRequestResponse>('/repair-requests', {
        vehicle_id: state.detail.work_order.asset_id,
        symptom_th: defectSymptom.trim(),
        source_type: 'PM_RESULT',
        source_id: pmWorkResultId,
      })
      setDefectSubmitting(false)
      if (result.ok) {
        setDefectFormOpenFor(null)
        setDefectSymptom('')
        // Web UAT Defect Fix UAT-F3: re-derive "already reported" from the
        // server (see load() above) rather than trusting this one
        // response in local state — keeps this screen and a reload
        // showing exactly the same, persisted truth.
        void load()
      } else {
        const err = result.error
        setDefectError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
      }
    },
    [state, defectSymptom, load],
  )

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
  // R4 PM Workflow: V2 work orders follow the Owner E01 lifecycle; legacy ones keep their original flow.
  const isV2 = work_order.assignment_model === 'TECHNICIAN_V2'
  const status = work_order.status
  const scopeEditable = isV2 ? status === 'OPEN' || status === 'IN_PROGRESS' : isOpen
  const performedSaved = Object.values(workflow.outcomes).some((o) => o.disposition === 'PERFORMED')
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

      {evidenceError && (
        <p className="form-field__error" role="alert">
          ไม่สามารถโหลดรูปแนบหลักฐานได้: {evidenceError}
        </p>
      )}

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
        {isV2 && status === 'CLOSED' && workflow.outstanding.length > 0 && (
          <p className="form-field__hint" role="note">
            ปิดงานแล้ว แต่ยังมีรายการค้าง {workflow.outstanding.filter((o) => !o.resolved).length} รายการ
            (ไม่ใช่การทำ PM ครบทุกรายการ)
          </p>
        )}
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

      {/* R2 Batch R2f-h4 B5: the technician team, by the persisted assignment_model. */}
      <JobAssignmentSection
        kind="PM"
        jobId={work_order.pm_work_order_id}
        jobStatus={work_order.status}
        assignmentModel={work_order.assignment_model}
        legacyPrimary={work_order.primary_technician}
        legacyCollaborators={work_order.collaborators}
      />

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
        {canManagePm && scopeEditable && !scopeApproved && outOfScopeTasks.length > 0 && (
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
        {canManagePm && scopeEditable && !scopeApproved && (
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

      {scopeTasks.map((task) => {
        const result = resultsByTask.get(task.pm_task_id) ?? null
        // Repair Request only covers VEHICLE (the live repair_request
        // sheet has no equipment column — same constraint RepairCreatePage
        // already follows for the ordinary reporting flow).
        const canReportDefect =
          result != null &&
          work_order.asset_type === 'VEHICLE' &&
          hasCapability(CAN_REPORT_REPAIR)
        const existingDefectRequests = result
          ? existingDefectRequestsByResult[result.pm_work_result_id] ?? []
          : []

        return (
          <div key={task.pm_task_id}>
            <PmTaskCard
              task={task}
              result={result}
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
              mode={isV2 ? 'V2' : 'LEGACY'}
              outcome={workflow.outcomes[task.pm_task_id] ?? null}
              editable={isV2 ? status === 'IN_PROGRESS' && !workflow.outcomes[task.pm_task_id] : true}
              notPerformedAllowed={performedSaved}
            />
            {canReportDefect && result && (
              <Card>
                {existingDefectRequests.length > 0 ? (
                  <p className="form-field__hint">
                    แจ้งซ่อมแล้ว (รหัส{' '}
                    <Link to={`/repair-requests/${existingDefectRequests[0].repair_request_id}`}>
                      {existingDefectRequests[0].repair_request_id}
                    </Link>
                    ) — ทีมซ่อมบำรุงจะตรวจสอบและเปิดใบงานซ่อมต่อไป
                  </p>
                ) : defectFormOpenFor === result.pm_work_result_id ? (
                  <div className="form-grid">
                    <div className="form-field">
                      <label htmlFor={`pm-defect-symptom-${result.pm_work_result_id}`}>
                        อาการ/ข้อบกพร่องที่พบระหว่าง PM
                      </label>
                      <textarea
                        id={`pm-defect-symptom-${result.pm_work_result_id}`}
                        value={defectSymptom}
                        onChange={(event) => setDefectSymptom(event.target.value)}
                        placeholder="อธิบายข้อบกพร่องที่พบ"
                      />
                    </div>
                    {defectError && (
                      <p className="form-field__error" role="alert">
                        {defectError}
                      </p>
                    )}
                    <div className="status-card__actions">
                      <button
                        type="button"
                        className="button button--primary button--full-width"
                        disabled={defectSubmitting || !defectSymptom.trim()}
                        onClick={() => void reportPmDefect(result.pm_work_result_id)}
                      >
                        {defectSubmitting ? 'กำลังส่ง...' : 'ส่งแจ้งซ่อม'}
                      </button>
                      <button
                        type="button"
                        className="button button--secondary button--full-width"
                        disabled={defectSubmitting}
                        onClick={() => {
                          setDefectFormOpenFor(null)
                          setDefectError(null)
                        }}
                      >
                        ยกเลิก
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="button button--secondary button--full-width"
                    onClick={() => {
                      setDefectFormOpenFor(result.pm_work_result_id)
                      setDefectSymptom('')
                      setDefectError(null)
                    }}
                  >
                    แจ้งซ่อม (พบข้อบกพร่องระหว่าง PM)
                  </button>
                )}
              </Card>
            )}
          </div>
        )
      })}

      {isV2 && (
        <Card>
          <h2>ขั้นตอนงาน PM</h2>
          {status === 'OPEN' && (
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={lifecycleBusy}
              onClick={() => void runTransition('start', {})}
            >
              เริ่มงาน
            </button>
          )}
          {status === 'IN_PROGRESS' && (
            <>
              <p className="form-field__hint">
                บันทึกทุกรายการในขอบเขตงาน (ต้องมีรายการที่ดำเนินการแล้วอย่างน้อย 1 รายการ) แล้วให้ช่างหลักส่งตรวจสอบ
              </p>
              <button
                type="button"
                className="button button--primary button--full-width"
                disabled={lifecycleBusy}
                onClick={() => void runTransition('submit', {})}
              >
                ส่งตรวจสอบ
              </button>
            </>
          )}
          {status === 'PENDING_REVIEW' && !canManagePm && <p>รอผู้มีสิทธิ์ตรวจสอบและปิดงาน</p>}
          {status === 'PENDING_REVIEW' && canManagePm && (
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="pm-return-reason">เหตุผลที่ส่งกลับ</label>
                <textarea
                  id="pm-return-reason"
                  value={returnReason}
                  onChange={(event) => setReturnReason(event.target.value)}
                />
              </div>
              <button
                type="button"
                className="button button--secondary button--full-width"
                disabled={lifecycleBusy || !returnReason.trim()}
                onClick={() => void runTransition('return', { reason: returnReason.trim() })}
              >
                ส่งกลับให้แก้ไข
              </button>
              <div className="form-field">
                <label htmlFor="pm-close-note">หมายเหตุการปิดงาน (ถ้ามี)</label>
                <textarea
                  id="pm-close-note"
                  value={closeNote}
                  onChange={(event) => setCloseNote(event.target.value)}
                />
              </div>
              <button
                type="button"
                className="button button--primary button--full-width"
                disabled={lifecycleBusy}
                onClick={() => void runTransition('close', { note: closeNote.trim() || null })}
              >
                อนุมัติและปิดงาน
              </button>
            </div>
          )}
          {(status === 'OPEN' || status === 'IN_PROGRESS') && canManagePm && (
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="pm-cancel-reason">เหตุผลการยกเลิก (ยกเลิกได้เฉพาะงานที่ยังไม่มีการบันทึกผล)</label>
                <textarea
                  id="pm-cancel-reason"
                  value={cancelReason}
                  onChange={(event) => setCancelReason(event.target.value)}
                />
              </div>
              <button
                type="button"
                className="button button--secondary button--full-width"
                disabled={lifecycleBusy || !cancelReason.trim()}
                onClick={() => void runTransition('cancel', { reason: cancelReason.trim() })}
              >
                ยกเลิกใบสั่งงาน
              </button>
            </div>
          )}
          {lifecycleError && (
            <p className="form-field__error" role="alert">
              {lifecycleError}
            </p>
          )}
        </Card>
      )}

      {isV2 && workflow.history.length > 0 && (
        <Card>
          <h2>ประวัติสถานะงาน</h2>
          <ul>
            {workflow.history.map((event) => (
              <li key={event.event_id}>
                {pmTransitionActionLabel[event.action] ?? event.action} —{' '}
                {formatThaiDateTime(event.occurred_at)} โดย {event.actor}
                {event.reason ? ` (${event.reason})` : ''}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {isV2 && status === 'CLOSED' && workflow.outstanding.length > 0 && (
        <Card>
          <h2>รายการค้างจาก PM นี้</h2>
          <ul>
            {workflow.outstanding.map((item) => (
              <li key={item.outstanding_id}>
                {state.tasks.find((t) => t.pm_task_id === item.pm_task_id)?.description ?? item.pm_task_id} —{' '}
                {item.origin_reason_code}
                {item.origin_other_text ? ` (${item.origin_other_text})` : ''} —{' '}
                {item.resolved ? 'ปิดรายการค้างแล้ว' : 'ยังค้างอยู่'}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!isV2 && isOpen && canManagePm && (
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
