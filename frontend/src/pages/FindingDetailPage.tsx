import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost, type ApiResult } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_FINDING_REPAIR } from '../lib/capabilityNames'
import {
  assetTypeLabel,
  describeErrorCode,
  findingEndReasonLabel,
  findingFollowupGroupLabel,
  findingStatusLabel,
  formatThaiDate,
  formatThaiDateTime,
  inspectionResultLabel,
  inspectionResultTone,
  REPAIR_COMPLETION_SUBMITTED_LABEL,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { FindingDetail, RepairDetail } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; detail: FindingDetail }


function toLoadState(result: ApiResult<FindingDetail>): LoadState {
  if (result.ok) return { kind: 'ready', detail: result.data }
  const err = result.error
  return {
    kind: 'error',
    message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

/**
 * R3 Finding (contract §7–§9): one episode for one asset + checklist item,
 * its dated observations and its repair rounds. ENDED never means verified or
 * safe. Opening a round and manual termination are manager / delegate actions
 * (the backend re-checks the capabilities).
 */
export function FindingDetailPage() {
  const { findingId = '' } = useParams<{ findingId: string }>()
  const navigate = useNavigate()
  const { hasCapability } = useCapabilities()
  // L11: opening a round and terminating need the Finding authority alone (the backend re-checks it).
  const canManageFinding = hasCapability(CAN_MANAGE_FINDING_REPAIR)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setState(toLoadState(await apiGet<FindingDetail>(`/findings/${findingId}`)))
  }, [findingId])

  useEffect(() => {
    let cancelled = false
    void apiGet<FindingDetail>(`/findings/${findingId}`).then((result) => {
      if (!cancelled) setState(toLoadState(result))
    })
    return () => {
      cancelled = true
    }
  }, [findingId])

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchData()
  }, [fetchData])

  const openRound = useCallback(async () => {
    if (state.kind !== 'ready') return
    setBusy(true)
    setActionError(null)
    const { finding } = state.detail
    const result = await apiPost<RepairDetail>('/repairs', {
      asset_type: finding.asset_type,
      asset_id: finding.asset_id,
      source_type: 'FINDING',
      source_id: finding.finding_id,
      symptom: finding.observations?.at(-1)?.remark ?? null,
    })
    setBusy(false)
    if (result.ok) {
      navigate(`/repairs/${result.data.repair.repair_id}`)
      return
    }
    const err = result.error
    setActionError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
  }, [state, navigate])

  const terminate = useCallback(async () => {
    if (!reason.trim()) {
      setActionError('กรุณาระบุเหตุผลในการยุติการติดตาม')
      return
    }
    setBusy(true)
    setActionError(null)
    const result = await apiPost<FindingDetail>(`/findings/${findingId}/termination`, { reason: reason.trim() })
    setBusy(false)
    if (result.ok) {
      setReason('')
      setState({ kind: 'ready', detail: result.data })
      return
    }
    const err = result.error
    setActionError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
  }, [findingId, reason])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดรายการผิดปกติ..." />
      </section>
    )
  }
  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายการผิดปกติ</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { finding, repairs, followup_group } = state.detail
  const isOpen = finding.status === 'OPEN'
  const hasOpenRound = repairs.some((r) => r.status === 'OPEN' && !r.completion_submitted_at)

  return (
    <section className="page">
      <h1>รายการผิดปกติ {finding.finding_id}</h1>
      <Card>
        <div className="status-card__row">
          <span>สินทรัพย์</span>
          <span>
            {assetTypeLabel[finding.asset_type] ?? finding.asset_type} — {finding.asset_id}
          </span>
        </div>
        <div className="status-card__row">
          <span>รายการตรวจ</span>
          <span>{finding.item_title}</span>
        </div>
        <div className="status-card__row">
          <span>สถานะ</span>
          <span data-testid="finding-status">
            <StatusBadge
              label={findingStatusLabel[finding.status] ?? finding.status}
              tone={isOpen ? 'warning' : 'neutral'}
            />{' '}
            {followup_group && findingFollowupGroupLabel[followup_group]}
          </span>
        </div>
        {finding.end_reason && (
          <p data-testid="finding-end-reason">
            {findingEndReasonLabel[finding.end_reason]}
            {finding.ended_at ? ` · ${formatThaiDateTime(finding.ended_at)}` : ''}
            {finding.end_reason === 'MANUAL_TERMINATION' && finding.end_note ? ` · เหตุผล: ${finding.end_note}` : ''}
          </p>
        )}
        {!isOpen && (
          <p className="form-field__hint">
            การสิ้นสุดรอบติดตามไม่ใช่การยืนยันว่าแก้ไขสำเร็จ และไม่ใช่การรับรองความปลอดภัย
          </p>
        )}
        {finding.previous_finding_id && (
          <p>
            รอบติดตามก่อนหน้าของรายการเดียวกัน:{' '}
            <Link to={`/findings/${finding.previous_finding_id}`}>{finding.previous_finding_id}</Link>
          </p>
        )}
      </Card>

      <Card>
        <h2>ผลตรวจที่บันทึก ({finding.observations?.length ?? 0})</h2>
        <ul data-testid="finding-observations">
          {(finding.observations ?? []).map((o) => (
            <li key={o.result_id}>
              {formatThaiDate(o.inspection_date)}{' '}
              <StatusBadge label={inspectionResultLabel[o.result] ?? o.result} tone={inspectionResultTone[o.result]} />{' '}
              {o.remark ?? ''} <Link to={`/inspections/${o.inspection_id}`}>{o.inspection_id}</Link>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h2>ใบงานซ่อม ({repairs.length})</h2>
        {repairs.length === 0 ? (
          <p>ยังไม่มีใบงานซ่อมจากรายการนี้</p>
        ) : (
          <ul data-testid="finding-repairs">
            {repairs.map((r) => (
              <li key={r.repair_id}>
                <Link to={`/repairs/${r.repair_id}`}>{r.repair_id}</Link>{' '}
                <StatusBadge label={repairStatusLabel[r.status] ?? r.status} tone={repairStatusTone[r.status]} />
                {r.status === 'OPEN' && r.completion_submitted_at && ` ${REPAIR_COMPLETION_SUBMITTED_LABEL}`}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {isOpen && canManageFinding && (
        <Card>
          <h2>การจัดการ (ผู้จัดการแผนกซ่อมบำรุงหรือผู้ได้รับมอบหมาย)</h2>
          {!hasOpenRound && (
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={busy}
              onClick={() => void openRound()}
            >
              เปิดใบงานซ่อมจากรายการนี้
            </button>
          )}
          <div className="form-field">
            <label htmlFor="termination-reason">เหตุผลในการยุติการติดตาม (จำเป็น)</label>
            <textarea
              id="termination-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <button
            type="button"
            className="button button--secondary button--full-width"
            disabled={busy}
            onClick={() => void terminate()}
          >
            ยุติการติดตาม
          </button>
        </Card>
      )}
      {actionError && (
        <p className="form-field__error" role="alert">
          {actionError}
        </p>
      )}
    </section>
  )
}
