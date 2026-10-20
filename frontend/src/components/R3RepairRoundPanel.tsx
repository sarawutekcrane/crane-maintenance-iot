import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiGet, apiPost, apiPostWithRequestId } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_FINDING_REPAIR, CAN_MANAGE_REPAIR } from '../lib/capabilityNames'
import { describeErrorCode, formatThaiDateTime, REPAIR_COMPLETION_SUBMITTED_LABEL } from '../lib/labels'
import { newRequestId } from '../lib/registryPending'
import type { TechnicianAssignments } from '../lib/technicianV2'
import type { Repair, RepairDetail } from '../lib/types'
import { Card } from './Card'

interface R3RepairRoundPanelProps {
  repair: Repair
  /** True when no repair action, part or evidence is recorded yet. */
  noRecordedWork: boolean
  onChanged: () => void
}

/**
 * R3 (docs/project-governance/r3-implementation-contract.md §10): the repair
 * round opened from a Finding.
 * - 'ส่งงานซ่อมเสร็จ' — only the current V2 lead technician (the backend
 *   proves it; this page cannot). It ends the Finding episode and leaves the
 *   order OPEN until the manager closes it. One X-Request-Id per intent.
 * - Cancellation — the manager / delegate only, with a reason, only before
 *   any recorded work. Never automatic.
 * Neither action is a repair acceptance or a safety clearance.
 */
export function R3RepairRoundPanel({ repair, noRecordedWork, onChanged }: R3RepairRoundPanelProps) {
  const { hasCapability } = useCapabilities()
  const canManageFinding = hasCapability(CAN_MANAGE_REPAIR) && hasCapability(CAN_MANAGE_FINDING_REPAIR)
  const [assignment, setAssignment] = useState<TechnicianAssignments | null>(null)
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const completionIntent = useRef<string | null>(null)

  const isOpen = repair.status === 'OPEN'
  const submitted = repair.completion_submitted_at != null

  useEffect(() => {
    if (!isOpen || submitted) return
    let cancelled = false
    void apiGet<TechnicianAssignments>(`/repairs/${repair.repair_id}/technician-assignments`).then((result) => {
      if (!cancelled && result.ok) setAssignment(result.data)
    })
    return () => {
      cancelled = true
    }
  }, [repair.repair_id, isOpen, submitted])

  const currentSetId = assignment?.current?.assignment_set_id ?? null

  const submitCompletion = useCallback(async () => {
    setBusy(true)
    setError(null)
    completionIntent.current ??= newRequestId()
    const result = await apiPostWithRequestId<RepairDetail>(
      `/repairs/${repair.repair_id}/completion`,
      { expected_set_id: currentSetId, note: note.trim() || null },
      completionIntent.current,
    )
    setBusy(false)
    if (result.ok) {
      completionIntent.current = null
      onChanged()
      return
    }
    const err = result.error
    if (err instanceof ApiError) {
      completionIntent.current = null
      setError(describeErrorCode(err.code))
    } else {
      // Unknown outcome: keep the same request id; a retry cannot submit twice.
      setError('ส่งงานไม่สำเร็จหรือไม่ทราบผล กรุณากดส่งอีกครั้ง ระบบจะไม่บันทึกซ้ำ')
    }
  }, [repair.repair_id, currentSetId, note, onChanged])

  const cancelRound = useCallback(async () => {
    if (!reason.trim()) {
      setError('กรุณาระบุเหตุผลในการยกเลิก')
      return
    }
    setBusy(true)
    setError(null)
    const result = await apiPost<RepairDetail>(`/repairs/${repair.repair_id}/cancellation`, { reason: reason.trim() })
    setBusy(false)
    if (result.ok) {
      onChanged()
      return
    }
    const err = result.error
    setError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
  }, [repair.repair_id, reason, onChanged])

  return (
    <Card>
      <h2>รอบการซ่อมจากรายการผิดปกติ</h2>
      <p>
        เปิดจากรายการผิดปกติ{' '}
        <Link to={`/findings/${repair.finding_id}`} data-testid="r3-round-finding-link">
          {repair.finding_id}
        </Link>{' '}
        ใบงานหนึ่งใบคือการซ่อมหนึ่งรอบ
      </p>

      {submitted && (
        <div role="status" data-testid="r3-completion-submitted">
          <p>
            <strong>{repair.status === 'OPEN' ? REPAIR_COMPLETION_SUBMITTED_LABEL : 'ช่างส่งงานซ่อมแล้ว'}</strong>{' '}
            เมื่อ {formatThaiDateTime(repair.completion_submitted_at!)}
            {repair.completion_technician_id ? ` โดยช่างหลัก ${repair.completion_technician_id}` : ''}
          </p>
          {repair.completion_note && <p>หมายเหตุการส่งงาน: {repair.completion_note}</p>}
          <p className="form-field__hint">
            การส่งงานไม่ใช่การยืนยันว่าแก้ไขสำเร็จ และไม่ใช่การรับรองความปลอดภัย ผู้จัดการเป็นผู้ปิดใบงาน
          </p>
        </div>
      )}

      {repair.status === 'CANCELLED' && (
        <div role="status" data-testid="r3-round-cancelled">
          <p>
            ยกเลิกใบงานเมื่อ {repair.cancelled_at ? formatThaiDateTime(repair.cancelled_at) : '-'}
            {repair.cancelled_by ? ` โดย ${repair.cancelled_by}` : ''}
          </p>
          {repair.cancel_reason && <p>เหตุผล: {repair.cancel_reason}</p>}
        </div>
      )}

      {isOpen && !submitted && assignment !== null && assignment.status !== 'VALID' && (
        <p className="form-field__hint" data-testid="r3-round-needs-lead">
          ยังไม่มีทีมช่างที่มีช่างหลัก: ต้องมอบหมายทีมช่างก่อนจึงจะบันทึกงานซ่อม อะไหล่ หรือรูปหลักฐานได้
        </p>
      )}

      {isOpen && !submitted && (
        <div className="form-field" data-testid="r3-completion-form">
          <label htmlFor="completion-note">หมายเหตุการส่งงาน (ถ้ามี)</label>
          <textarea id="completion-note" value={note} onChange={(event) => setNote(event.target.value)} />
          <p className="form-field__hint">เฉพาะช่างหลักที่ได้รับมอบหมายในปัจจุบันเท่านั้นที่ส่งงานซ่อมเสร็จได้</p>
          <button
            type="button"
            className="button button--primary button--full-width"
            disabled={busy || assignment?.status !== 'VALID'}
            onClick={() => void submitCompletion()}
          >
            ส่งงานซ่อมเสร็จ
          </button>
        </div>
      )}

      {isOpen && !submitted && canManageFinding && noRecordedWork && (
        <div className="form-field" data-testid="r3-cancel-form">
          <label htmlFor="cancel-reason">เหตุผลในการยกเลิกใบงาน (จำเป็น)</label>
          <textarea id="cancel-reason" value={reason} onChange={(event) => setReason(event.target.value)} />
          <p className="form-field__hint">ยกเลิกได้เฉพาะก่อนเริ่มงานซ่อม (ยังไม่มีการบันทึกงาน อะไหล่ หรือรูปหลักฐาน)</p>
          <button
            type="button"
            className="button button--secondary button--full-width"
            disabled={busy}
            onClick={() => void cancelRound()}
          >
            ยกเลิกใบงานซ่อม
          </button>
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
