import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { LoadingState } from '../../components/LoadingState'
import { TechnicianAssignmentV2Panel } from '../../components/TechnicianAssignmentV2Panel'
import { V2ContextBanner } from '../../components/V2ContextBanner'
import { apiGet } from '../../lib/apiClient'
import { formatThaiDateTime } from '../../lib/labels'
import { assignmentModelOf, jobApiPath, readFailure, type AssignmentModelSignal, type ReadFailure, type WorkKind } from '../../lib/technicianV2'

interface JobSummary {
  jobId: string
  assetType: string
  assetId: string
  status: string
  openedAt: string
  description: string | null
  model: AssignmentModelSignal
  /** The legacy header mirror, raw (shown read-only for LEGACY jobs only). */
  legacyPrimary: unknown
  legacyCollaborators: unknown
}

type LoadState = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; job: JobSummary }

function summaryOf(kind: WorkKind, json: unknown): JobSummary | null {
  const root = (typeof json === 'object' && json !== null ? json : {}) as Record<string, unknown>
  const record = root[kind === 'REPAIR' ? 'repair' : 'work_order']
  if (typeof record !== 'object' || record === null) return null
  const r = record as Record<string, unknown>
  const id = r[kind === 'REPAIR' ? 'repair_id' : 'pm_work_order_id']
  if (typeof id !== 'string') return null
  return {
    jobId: id,
    assetType: String(r.asset_type ?? ''),
    assetId: String(r.asset_id ?? ''),
    status: String(r.status ?? ''),
    openedAt: String(r.opened_at ?? ''),
    description: kind === 'REPAIR' ? ((r.symptom as string | null) ?? null) : `แผน ${String(r.pm_plan_id ?? '')}`,
    model: assignmentModelOf(r.assignment_model),
    legacyPrimary: r.primary_technician,
    legacyCollaborators: r.collaborators,
  }
}

async function fetchJob(kind: WorkKind, jobId: string): Promise<LoadState> {
  const result = await apiGet<unknown>(jobApiPath(kind, jobId))
  if (!result.ok) return { kind: 'error', failure: readFailure(result.error) }
  const job = summaryOf(kind, result.data)
  return job
    ? { kind: 'ready', job }
    : { kind: 'error', failure: { message: 'ข้อมูลงานที่ได้รับไม่อยู่ในรูปแบบที่รู้จัก', code: null, requestId: null, status: null } }
}

function rawText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '(ว่าง)'
  return typeof value === 'string' ? value : JSON.stringify(value)
}

/** LEGACY job: the legacy user-id mirror, raw and read-only; no assignment control. */
function LegacyAssignmentReadOnly({ job }: { job: JobSummary }) {
  const collaborators = Array.isArray(job.legacyCollaborators) ? job.legacyCollaborators : []
  return (
    <Card>
      <h2>ผู้รับผิดชอบ (รูปแบบเดิม — อ่านอย่างเดียว)</h2>
      <p className="form-field__hint" data-testid="v2-legacy-readonly">
        งานนี้สร้างด้วยรูปแบบการมอบหมายเดิม (LEGACY) ค่าด้านล่างเป็นรหัสผู้ใช้เดิม (LEGACY_USER_ID) ตามที่บันทึกไว้
        ไม่ใช่รหัสช่าง และไม่สามารถมอบหมายช่าง V2 กับงานนี้ได้
      </p>
      <div className="status-card__row">
        <span>LEGACY_USER_ID (หลัก)</span>
        <code>{rawText(job.legacyPrimary)}</code>
      </div>
      <div className="status-card__row">
        <span>LEGACY_USER_ID (ร่วม)</span>
        <code>{collaborators.length ? collaborators.map(rawText).join(', ') : '(ว่าง)'}</code>
      </div>
    </Card>
  )
}

/**
 * R2 Batch R2f-h4 B4 — the V2 job detail (parallel route, Option 1). The
 * assignment area branches strictly on the job's persisted `assignment_model`:
 * TECHNICIAN_V2 → the V2 panel; LEGACY → read-only legacy display; anything
 * else → an explicit error with no control.
 */
export function V2JobDetailPage({ kind }: { kind: WorkKind }) {
  const { repairId, workOrderId } = useParams<{ repairId?: string; workOrderId?: string }>()
  const jobId = (kind === 'REPAIR' ? repairId : workOrderId) ?? ''
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchJob(kind, jobId).then(setState)
  }, [kind, jobId])

  useEffect(() => {
    let cancelled = false
    void fetchJob(kind, jobId).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [kind, jobId])

  const title = kind === 'REPAIR' ? 'ใบงานซ่อม (V2)' : 'ใบสั่งงาน PM (V2)'
  return (
    <section className="page">
      <h1>{title}</h1>
      <V2ContextBanner />
      {state.kind === 'loading' && <LoadingState />}
      {state.kind === 'error' && (
        <ErrorState
          message={state.failure.message}
          code={state.failure.code}
          requestId={state.failure.requestId}
          onRetry={() => load()}
        />
      )}
      {state.kind === 'ready' && (
        <>
          <Card>
            <div className="status-card__row">
              <span>รหัสงาน</span>
              <strong data-testid="v2-job-id">{state.job.jobId}</strong>
            </div>
            <div className="status-card__row">
              <span>สินทรัพย์</span>
              <span>
                {state.job.assetType} {state.job.assetId}
              </span>
            </div>
            <div className="status-card__row">
              <span>สถานะ</span>
              <span data-testid="v2-job-status">{state.job.status}</span>
            </div>
            <div className="status-card__row">
              <span>เปิดเมื่อ</span>
              <span>{state.job.openedAt ? formatThaiDateTime(state.job.openedAt) : '-'}</span>
            </div>
            {state.job.description && <p>{state.job.description}</p>}
            <div className="status-card__row">
              <span>รูปแบบการมอบหมาย</span>
              <code data-testid="v2-assignment-model">{state.job.model}</code>
            </div>
          </Card>
          {state.job.model === 'TECHNICIAN_V2' && (
            <TechnicianAssignmentV2Panel kind={kind} jobId={state.job.jobId} jobStatus={state.job.status} />
          )}
          {state.job.model === 'LEGACY' && <LegacyAssignmentReadOnly job={state.job} />}
          {state.job.model === 'INVALID' && (
            <ErrorState
              title="รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง"
              message="ข้อมูลรูปแบบการมอบหมายที่บันทึกไว้ไม่ใช่ค่าที่ระบบรู้จัก ระบบจึงไม่แสดงและไม่อนุญาตการมอบหมายช่าง กรุณาแจ้งผู้ดูแลข้อมูล"
              code="ASSIGNMENT_MODEL_INVALID"
            />
          )}
        </>
      )}
    </section>
  )
}
