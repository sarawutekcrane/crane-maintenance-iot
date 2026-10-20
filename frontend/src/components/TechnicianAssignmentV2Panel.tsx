import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_FINDING_REPAIR, CAN_MANAGE_PM, CAN_MANAGE_REPAIR } from '../lib/capabilityNames'
import { formatThaiDateTime } from '../lib/labels'
import {
  buildAssignmentBody,
  buildWithdrawalBody,
  fetchAllTechnicians,
  intentOperation,
  jobApiPath,
  pendingAssignmentIntent,
  readFailure,
  resendAssignment,
  selectionProblem,
  startAssignment,
  startWithdrawal,
  technicianName,
  type AssignmentOperation,
  type AssignmentResult,
  type AssignmentSet,
  type AssignmentWithdrawal,
  type ReadFailure,
  type TechnicianAssignments,
  type TechnicianSummary,
  type WorkKind,
} from '../lib/technicianV2'
import { Card } from './Card'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { FormField } from './FormField'
import { LoadingState } from './LoadingState'
import { ResponsiveTable } from './ResponsiveTable'
import { StatusBadge } from './StatusBadge'
import { TechnicianV2Picker } from './TechnicianV2Picker'

type Load<T> = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; data: T }

type Message =
  | { tone: 'success'; text: string }
  | { tone: 'stale'; text: string }
  | { tone: 'error'; text: string; code: string; requestId: string | null }
  | { tone: 'unknown'; text: string; requestId: string }
  | null

interface Loaded {
  assignments: Load<TechnicianAssignments>
  technicians: Load<TechnicianSummary[]>
}

/** Both reads; each failure is kept as its own error (never a partial picker). */
async function fetchPanel(kind: WorkKind, jobId: string): Promise<Loaded> {
  const [read, listed] = await Promise.all([
    apiGet<TechnicianAssignments>(`${jobApiPath(kind, jobId)}/technician-assignments`),
    fetchAllTechnicians(),
  ])
  return {
    assignments: read.ok ? { kind: 'ready', data: read.data } : { kind: 'error', failure: readFailure(read.error) },
    technicians: listed.ok ? { kind: 'ready', data: listed.data } : { kind: 'error', failure: readFailure(listed.error) },
  }
}

interface TechnicianAssignmentV2PanelProps {
  kind: WorkKind
  jobId: string
  /** The job's stored status; assignment is offered only while exactly OPEN. */
  jobStatus: string
  /** Called after a proven change so the page can reload its own record. */
  onChanged?: () => void
  /** An R3 Finding round (server-stored `finding_id`): assigning needs
   * `can_manage_finding_repair` alone (L11 source-scoped predicate, superseding
   * L8), and the lead is never withdrawn, only replaced by a new team (L9). The
   * backend enforces both; this only avoids offering a refused action. */
  r3FindingRound?: boolean
}

/** One assignee: the stable id, with the name shown separately (or the explicit unresolved state). */
function Assignee({ id, byId, techniciansLoaded }: { id: string; byId: Map<string, TechnicianSummary>; techniciansLoaded: boolean }) {
  const technician = byId.get(id)
  return (
    <span data-testid="v2-assignee">
      <strong>{id}</strong>{' '}
      {technician ? (
        <span>— {technicianName(technician) ?? 'ไม่มีชื่อในข้อมูลหลัก'}</span>
      ) : techniciansLoaded ? (
        <span className="form-field__error">— ไม่พบรหัสช่างนี้ในขอบเขตข้อมูลปัจจุบัน (ยืนยันชื่อ/ขอบเขตไม่ได้)</span>
      ) : (
        <span className="form-field__hint">— ไม่ทราบชื่อ (โหลดรายชื่อช่างไม่สำเร็จ)</span>
      )}
    </span>
  )
}

/**
 * R2 Batch R2f-h4 B4 (A1-§25) — the V2 technician assignment panel of a
 * `TECHNICIAN_V2` job: the current PRIMARY / COLLABORATORs (stable id + name),
 * the set history kept separate, and the save form. A save always sends the
 * exact `expected_current`, follows the R2e request-intent pattern, cannot be
 * double-submitted, never overwrites silently on a stale conflict (reload and
 * reconfirm), and is not offered on a job that is not exactly OPEN or whose
 * current set is AMBIGUOUS. The backend is authoritative for every rule.
 *
 * R2 Batch R2f-h4 B6 (owner D2): a manager may WITHDRAW the whole current set
 * of an OPEN job (never a partial empty set through the picker). The action is
 * explicit, needs a confirmation, sends the exact `expected_current`, and uses
 * the same request-intent safeguards; the withdrawal is kept as history and the
 * job can be reassigned afterwards through the normal picker. A CLOSED job is
 * refused by the backend (`TECHNICIAN_ASSIGNMENT_JOB_CLOSED`) and never offered.
 */
export function TechnicianAssignmentV2Panel({
  kind,
  jobId,
  jobStatus,
  onChanged,
  r3FindingRound = false,
}: TechnicianAssignmentV2PanelProps) {
  const { hasCapability, userId } = useCapabilities()
  // L11: an R3 round is managed under the Finding authority alone; every other job keeps its own capability.
  const canManageJob = hasCapability(kind === 'REPAIR' ? CAN_MANAGE_REPAIR : CAN_MANAGE_PM)
  const canManage = r3FindingRound ? kind === 'REPAIR' && hasCapability(CAN_MANAGE_FINDING_REPAIR) : canManageJob
  const findingAuthorityMissing = Boolean(r3FindingRound) && canManageJob && !canManage
  const [assignments, setAssignments] = useState<Load<TechnicianAssignments>>({ kind: 'loading' })
  const [technicians, setTechnicians] = useState<Load<TechnicianSummary[]>>({ kind: 'loading' })
  const [primary, setPrimary] = useState('')
  const [collaborators, setCollaborators] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [message, setMessage] = useState<Message>(null)
  const [stale, setStale] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [confirmingWithdrawal, setConfirmingWithdrawal] = useState(false)
  const [withdrawalReason, setWithdrawalReason] = useState('')
  const inFlight = useRef(false)
  // Re-read on every render (cheap): the user id arrives asynchronously from /me,
  // and every action may store or remove the intent.
  const [, setIntentVersion] = useState(0)
  const pending = pendingAssignmentIntent(userId, kind, jobId)

  const applyLoaded = useCallback((loaded: Loaded, keepSelection: boolean) => {
    setTechnicians(loaded.technicians)
    setAssignments(loaded.assignments)
    if (!keepSelection && loaded.assignments.kind === 'ready') {
      const current = loaded.assignments.data.current
      setPrimary(current?.primary_technician_id ?? '')
      setCollaborators(current ? [...current.collaborator_technician_ids] : [])
      setReason('')
    }
  }, [])

  const load = useCallback(
    (keepSelection: boolean) => {
      setAssignments({ kind: 'loading' })
      setTechnicians({ kind: 'loading' })
      void fetchPanel(kind, jobId).then((loaded) => applyLoaded(loaded, keepSelection))
    },
    [kind, jobId, applyLoaded],
  )

  useEffect(() => {
    let cancelled = false
    void fetchPanel(kind, jobId).then((loaded) => {
      if (!cancelled) applyLoaded(loaded, false)
    })
    return () => {
      cancelled = true
    }
  }, [kind, jobId, applyLoaded])

  const byId = useMemo(
    () => new Map((technicians.kind === 'ready' ? technicians.data : []).map((t) => [t.technician_id, t])),
    [technicians],
  )
  const listedIds = useMemo(() => new Set(byId.keys()), [byId])

  const apply = (result: AssignmentResult | null, operation: AssignmentOperation = 'assign') => {
    setIntentVersion((v) => v + 1)
    if (!result) return
    if (result.kind === 'changed' || result.kind === 'replayed' || result.kind === 'no-op' || result.kind === 'withdrawn') {
      setMessage({
        tone: 'success',
        text:
          result.kind === 'no-op'
            ? 'ทีมช่างเป็นชุดนี้อยู่แล้ว ไม่มีการเปลี่ยนแปลง'
            : result.kind === 'withdrawn' || operation === 'withdraw'
              ? 'ถอนการมอบหมายช่างทั้งหมดเรียบร้อยแล้ว งานนี้กลับไปรอมอบหมายช่าง'
              : 'บันทึกการมอบหมายช่างเรียบร้อยแล้ว',
      })
      void load(false)
      onChanged?.()
    } else if (result.kind === 'stale') {
      setStale(true)
      setMessage({ tone: 'stale', text: result.message })
    } else if (result.kind === 'refused') {
      setMessage({ tone: 'error', text: result.message, code: result.code, requestId: result.requestId })
    } else if (result.kind === 'unknown') {
      setMessage({ tone: 'unknown', text: result.message, requestId: result.requestId })
    }
  }

  const submit = async () => {
    if (inFlight.current || assignments.kind !== 'ready') return
    const problem = selectionProblem(primary, collaborators, listedIds)
    if (problem) {
      setFormError(problem.message)
      return
    }
    inFlight.current = true
    setSubmitting(true)
    setFormError(null)
    setMessage(null)
    const body = buildAssignmentBody(primary, collaborators, assignments.data.current, reason)
    const result = await startAssignment(userId, kind, jobId, body)
    inFlight.current = false
    setSubmitting(false)
    apply(result)
  }

  const withdraw = async () => {
    if (inFlight.current || assignments.kind !== 'ready' || !assignments.data.current) return
    inFlight.current = true
    setSubmitting(true)
    setFormError(null)
    setMessage(null)
    const body = buildWithdrawalBody(assignments.data.current, withdrawalReason)
    const result = await startWithdrawal(userId, kind, jobId, body)
    inFlight.current = false
    setSubmitting(false)
    setConfirmingWithdrawal(false)
    setWithdrawalReason('')
    apply(result, 'withdraw')
  }

  const resend = async () => {
    if (inFlight.current) return
    const stored = pendingAssignmentIntent(userId, kind, jobId)
    const operation = stored ? intentOperation(stored) : 'assign'
    inFlight.current = true
    setSubmitting(true)
    const result = await resendAssignment(userId, kind, jobId)
    inFlight.current = false
    setSubmitting(false)
    apply(result, operation)
  }

  const reloadAfterStale = () => {
    setStale(false)
    setMessage(null)
    load(true) // keep the selection; the user must confirm it again against the new current set
    onChanged?.()
  }

  const current: AssignmentSet | null = assignments.kind === 'ready' ? assignments.data.current : null
  const ambiguous = assignments.kind === 'ready' && assignments.data.status === 'AMBIGUOUS'
  const open = jobStatus === 'OPEN'
  const techniciansLoaded = technicians.kind === 'ready'
  const withdrawals: AssignmentWithdrawal[] = assignments.kind === 'ready' ? (assignments.data.withdrawals ?? []) : []
  const canWithdraw = canManage && !r3FindingRound && open && !ambiguous && current !== null && (!pending || submitting)

  return (
    <Card className="technician-v2-panel">
      <h2>ทีมช่าง (การมอบหมายช่าง V2)</h2>

      {assignments.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูลการมอบหมายช่าง..." />}
      {assignments.kind === 'error' && (
        <ErrorState
          title="โหลดข้อมูลการมอบหมายช่างไม่สำเร็จ"
          message={assignments.failure.message}
          code={assignments.failure.code}
          requestId={assignments.failure.requestId}
          onRetry={() => void load(false)}
        />
      )}

      {message && (
        <div
          className={message.tone === 'success' ? 'form-field__hint' : 'form-field__error'}
          role="alert"
          data-testid={`v2-assignment-message-${message.tone}`}
        >
          <p>{message.text}</p>
          {message.tone === 'error' && <p className="state-panel__meta">รหัสข้อผิดพลาด: {message.code}</p>}
          {(message.tone === 'error' || message.tone === 'unknown') && message.requestId && (
            <p className="state-panel__meta">รหัสอ้างอิง: {message.requestId}</p>
          )}
          {message.tone === 'stale' && (
            <button type="button" className="button button--secondary" onClick={reloadAfterStale}>
              โหลดข้อมูลล่าสุด
            </button>
          )}
        </div>
      )}

      {/* An intent left by an unknown outcome (not the request now in flight). */}
      {pending && !submitting && (
        <div className="form-field__error" role="status" data-testid="v2-assignment-pending">
          <p>
            {intentOperation(pending) === 'withdraw' ? 'มีคำขอถอนการมอบหมายช่างที่ยังไม่ทราบผล' : 'มีคำขอมอบหมายช่างที่ยังไม่ทราบผล'}{' '}
            (รหัสคำขอ {pending.requestId})
          </p>
          <button type="button" className="button button--secondary" disabled={submitting} onClick={() => void resend()}>
            ส่งคำขอเดิมอีกครั้ง
          </button>
          <button type="button" className="button button--secondary" disabled={submitting} onClick={() => void load(false)}>
            โหลดข้อมูลล่าสุด
          </button>
        </div>
      )}

      {assignments.kind === 'ready' && (
        <>
          <section aria-label="ทีมช่างปัจจุบัน" data-testid="v2-current-set">
            <h3>ทีมช่างปัจจุบัน</h3>
            {ambiguous && (
              <p className="form-field__error" role="alert">
                ระบุทีมช่างปัจจุบันไม่ได้ (มีชุดการมอบหมายที่บันทึกในเวลาเดียวกัน) จึงยังมอบหมายช่างไม่ได้ กรุณาแจ้งผู้ดูแลข้อมูล
              </p>
            )}
            {!ambiguous && !current && (
              <p>
                <StatusBadge label="ยังไม่ได้มอบหมายช่าง" tone="warning" />
              </p>
            )}
            {current && (
              <>
                <div className="status-card__row">
                  <span>ช่างหลัก (PRIMARY)</span>
                  <Assignee id={current.primary_technician_id} byId={byId} techniciansLoaded={techniciansLoaded} />
                </div>
                <div className="status-card__row">
                  <span>ช่างร่วม (COLLABORATOR)</span>
                  <span>
                    {current.collaborator_technician_ids.length === 0
                      ? 'ไม่มี'
                      : current.collaborator_technician_ids.map((id) => (
                          <span key={id} className="v2-assignee-line">
                            <Assignee id={id} byId={byId} techniciansLoaded={techniciansLoaded} />
                          </span>
                        ))}
                  </span>
                </div>
                <p className="form-field__hint">
                  เวลาที่บันทึก: {formatThaiDateTime(current.assigned_at)} โดย {current.assigned_by_user_id}
                </p>
              </>
            )}
            {canWithdraw && (
              <button
                type="button"
                className="button button--secondary"
                data-testid="v2-withdraw-assignment"
                disabled={submitting || stale}
                onClick={() => {
                  setWithdrawalReason('')
                  setConfirmingWithdrawal(true)
                }}
              >
                ถอนการมอบหมายช่างทั้งหมด
              </button>
            )}
          </section>

          {technicians.kind === 'error' && (
            <ErrorState
              title="โหลดรายชื่อช่างไม่สำเร็จ"
              message={technicians.failure.message}
              code={technicians.failure.code}
              requestId={technicians.failure.requestId}
              onRetry={() => load(true)}
            />
          )}

          {findingAuthorityMissing && open && (
            <p className="form-field__hint" data-testid="v2-assignment-finding-authority">
              งานซ่อมจากรายการผิดปกติ: ต้องมีสิทธิ์จัดการงานซ่อมจากรายการผิดปกติจึงจะมอบหมายช่างได้
            </p>
          )}

          {canManage && r3FindingRound && open && (
            <p className="form-field__hint" data-testid="v2-assignment-r3-lead-kept">
              ใบงานซ่อมจากรายการผิดปกติต้องมีช่างหลักตลอดการซ่อม: เปลี่ยนช่างหลักได้โดยมอบหมายทีมใหม่ (ระบบเก็บประวัติทีมเดิมไว้)
              ไม่สามารถถอนการมอบหมายโดยไม่มีผู้แทน
            </p>
          )}

          {!open && (
            <p className="form-field__hint" data-testid="v2-assignment-closed">
              งานนี้ไม่ได้อยู่ในสถานะเปิด (สถานะ: {jobStatus}) จึงไม่สามารถมอบหมายช่างได้
            </p>
          )}

          {canManage && open && !ambiguous && (!pending || submitting) && techniciansLoaded && technicians.data.length === 0 && (
            <EmptyState title="ไม่มีช่างในขอบเขตข้อมูลนี้" description="ยังไม่มีรายชื่อช่างที่ระบบส่งมาสำหรับขอบเขตข้อมูลปัจจุบัน" />
          )}

          {canManage && open && !ambiguous && (!pending || submitting) && techniciansLoaded && technicians.data.length > 0 && (
            <form
              className="technician-v2-form"
              onSubmit={(event) => {
                event.preventDefault()
                void submit()
              }}
            >
              <h3>{current ? 'เปลี่ยนทีมช่าง' : 'มอบหมายช่าง'}</h3>
              <TechnicianV2Picker
                technicians={technicians.data}
                primary={primary}
                collaborators={collaborators}
                disabled={submitting || stale}
                onChange={(p, c) => {
                  setPrimary(p)
                  setCollaborators(c)
                  setFormError(null)
                }}
              />
              <FormField label="เหตุผล (ถ้ามี)" htmlFor={`v2-reason-${kind}-${jobId}`}>
                <textarea
                  id={`v2-reason-${kind}-${jobId}`}
                  value={reason}
                  disabled={submitting || stale}
                  maxLength={500}
                  onChange={(event) => setReason(event.target.value)}
                />
              </FormField>
              {formError && (
                <p className="form-field__error" role="alert">
                  {formError}
                </p>
              )}
              <button type="submit" className="button button--primary button--full-width" disabled={submitting || stale}>
                {submitting ? 'กำลังบันทึก...' : 'บันทึกการมอบหมายช่าง'}
              </button>
            </form>
          )}

          {withdrawals.length > 0 && (
            <section aria-label="ประวัติการถอนการมอบหมายช่าง" data-testid="v2-withdrawal-history">
              <h3>ประวัติการถอนการมอบหมายช่าง</h3>
              <ResponsiveTable<AssignmentWithdrawal>
                rows={withdrawals}
                getRowKey={(w) => w.withdrawal_id}
                emptyTitle="ยังไม่มีประวัติการถอนการมอบหมายช่าง"
                columns={[
                  { key: 'at', header: 'เวลาที่ถอน', render: (w) => formatThaiDateTime(w.withdrawn_at) },
                  { key: 'by', header: 'ถอนโดย', render: (w) => w.withdrawn_by_user_id },
                  { key: 'reason', header: 'เหตุผล', render: (w) => w.reason_th ?? '-' },
                ]}
              />
            </section>
          )}

          <section aria-label="ประวัติการมอบหมายช่าง" data-testid="v2-assignment-history">
            <h3>ประวัติการมอบหมายช่าง</h3>
            <ResponsiveTable<AssignmentSet>
              rows={assignments.data.sets}
              getRowKey={(set) => set.assignment_set_id}
              emptyTitle="ยังไม่มีประวัติการมอบหมายช่าง"
              emptyDescription="งานนี้ยังไม่เคยถูกมอบหมายช่างในรูปแบบ V2"
              columns={[
                { key: 'at', header: 'เวลาที่บันทึก', render: (set) => formatThaiDateTime(set.assigned_at) },
                {
                  key: 'primary',
                  header: 'ช่างหลัก',
                  render: (set) => <Assignee id={set.primary_technician_id} byId={byId} techniciansLoaded={techniciansLoaded} />,
                },
                {
                  key: 'collaborators',
                  header: 'ช่างร่วม',
                  render: (set) =>
                    set.collaborator_technician_ids.length === 0
                      ? 'ไม่มี'
                      : set.collaborator_technician_ids.map((id) => (
                          <span key={id} className="v2-assignee-line">
                            <Assignee id={id} byId={byId} techniciansLoaded={techniciansLoaded} />
                          </span>
                        )),
                },
                { key: 'by', header: 'บันทึกโดย', render: (set) => set.assigned_by_user_id },
                { key: 'reason', header: 'เหตุผล', render: (set) => set.reason_th ?? '-' },
              ]}
            />
          </section>
        </>
      )}
      {confirmingWithdrawal && canWithdraw && current && (
        <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : () => setConfirmingWithdrawal(false)}>
          <div
            className="dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={`v2-withdraw-title-${kind}-${jobId}`}
            data-testid="v2-withdraw-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id={`v2-withdraw-title-${kind}-${jobId}`}>ยืนยันการถอนการมอบหมายช่างทั้งหมด</h2>
            <p>
              ช่างหลัก {current.primary_technician_id}
              {current.collaborator_technician_ids.length > 0 && <> และช่างร่วม {current.collaborator_technician_ids.join(', ')}</>}{' '}
              จะถูกถอนออกจากงานนี้ งานยังคงเปิดอยู่และกลับไปอยู่ในคิวรอมอบหมายช่าง ประวัติการมอบหมายเดิมยังถูกเก็บไว้
            </p>
            <FormField label="เหตุผล (ถ้ามี)" htmlFor={`v2-withdraw-reason-${kind}-${jobId}`}>
              <textarea
                id={`v2-withdraw-reason-${kind}-${jobId}`}
                value={withdrawalReason}
                disabled={submitting}
                maxLength={500}
                onChange={(event) => setWithdrawalReason(event.target.value)}
              />
            </FormField>
            <div className="dialog__actions">
              <button
                type="button"
                className="button button--secondary"
                disabled={submitting}
                onClick={() => setConfirmingWithdrawal(false)}
              >
                ยกเลิก
              </button>
              <button
                type="button"
                className="button button--primary"
                data-testid="v2-withdraw-confirm"
                disabled={submitting}
                onClick={() => void withdraw()}
              >
                {submitting ? 'กำลังบันทึก...' : 'ยืนยันการถอน'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}
