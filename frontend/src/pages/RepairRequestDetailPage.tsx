import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_CANCEL_REPAIR_REQUEST } from '../lib/capabilityNames'
import { describeErrorCode, formatThaiDateTime, repairSourceTypeLabel } from '../lib/labels'
import type { RepairRequest } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; request: RepairRequest }

const REQUEST_STATUS_LABEL: Record<string, string> = {
  PENDING: 'รอตรวจรับ',
  CONVERTED: 'เปิดใบงานซ่อมแล้ว',
  CANCELLED: 'ยกเลิกแล้ว',
}

/**
 * Read-only Repair Request detail (Web UAT Defect Fix UAT-F2) — lets a
 * reporter (or anyone else the backend's existing, unrestricted
 * `GET /repair-requests/{id}` already permits — M02 read-governance
 * remains open, see docs) find and re-open a Repair Request after
 * navigating away, instead of only a transient success message that
 * disappears on reload.
 */
export function RepairRequestDetailPage() {
  const { repairRequestId = '' } = useParams<{ repairRequestId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const { hasCapability } = useCapabilities()
  const canCancel = hasCapability(CAN_CANCEL_REPAIR_REQUEST)
  const [reason, setReason] = useState('')
  const [duplicateRepairId, setDuplicateRepairId] = useState('')
  const [busy, setBusy] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<RepairRequest>(`/repair-requests/${repairRequestId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', request: result.data })
  }, [repairRequestId])

  useEffect(() => {
    void load()
  }, [load])

  const cancel = useCallback(async () => {
    if (!reason.trim()) {
      setCancelError('กรุณาระบุเหตุผลในการยกเลิกคำขอแจ้งซ่อม')
      return
    }
    setBusy(true)
    setCancelError(null)
    const result = await apiPost<RepairRequest>(`/repair-requests/${repairRequestId}/cancellation`, {
      reason_th: reason.trim(),
      duplicate_of_repair_id: duplicateRepairId.trim() || null,
    })
    setBusy(false)
    if (result.ok) {
      setState({ kind: 'ready', request: result.data })
      return
    }
    const err = result.error
    setCancelError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
  }, [repairRequestId, reason, duplicateRepairId])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลคำขอแจ้งซ่อม..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>คำขอแจ้งซ่อม</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { request } = state

  return (
    <section className="page">
      <h1>คำขอแจ้งซ่อม</h1>
      <p>รหัสคำขอ: {request.repair_request_id}</p>

      <Card>
        <div className="status-card__row">
          <span>ยานพาหนะ</span>
          <span>{request.vehicle_id}</span>
        </div>
        <div className="status-card__row">
          <span>สถานะ</span>
          <StatusBadge
            label={REQUEST_STATUS_LABEL[request.request_status] ?? request.request_status}
            tone={request.request_status === 'CONVERTED' ? 'success' : request.request_status === 'CANCELLED' ? 'neutral' : 'warning'}
          />
        </div>
        <div className="status-card__row">
          <span>แจ้งเมื่อ</span>
          <span>{formatThaiDateTime(request.reported_at)}</span>
        </div>
        {request.priority && (
          <div className="status-card__row">
            <span>ความสำคัญ</span>
            <span>{request.priority}</span>
          </div>
        )}
        {request.report_channel && (
          <div className="status-card__row">
            <span>ช่องทางแจ้ง</span>
            <span>{request.report_channel}</span>
          </div>
        )}
        {request.source_type && (
          <div className="status-card__row">
            <span>แหล่งที่มา</span>
            <span>
              {repairSourceTypeLabel[request.source_type] ?? request.source_type}
              {request.source_id ? ` (${request.source_id})` : ''}
            </span>
          </div>
        )}
        <p>อาการ/ปัญหาที่พบ: {request.symptom_th ?? '-'}</p>
        {request.note_th && <p className="form-field__hint">{request.note_th}</p>}
      </Card>

      {request.request_status === 'CONVERTED' && request.repair_id && (
        <Card>
          <p>ทีมซ่อมบำรุงเปิดใบงานซ่อมจากคำขอนี้แล้ว</p>
          <Link
            to={`/repairs/${request.repair_id}`}
            className="button button--primary button--full-width"
          >
            ดูใบแจ้งซ่อม {request.repair_id}
          </Link>
        </Card>
      )}

      {request.request_status === 'PENDING' && (
        <Card>
          <p>คำขอนี้อยู่ระหว่างรอทีมซ่อมบำรุงตรวจสอบและเปิดใบงานซ่อม</p>
        </Card>
      )}

      {request.request_status === 'CANCELLED' && (
        <Card>
          <div role="status" data-testid="repair-request-cancelled">
            <p>
              ผู้จัดการแผนกซ่อมบำรุงยกเลิกคำขอนี้แล้ว
              {request.cancelled_at ? ` เมื่อ ${formatThaiDateTime(request.cancelled_at)}` : ''}
              {request.cancelled_by_user_id ? ` โดย ${request.cancelled_by_user_id}` : ''}
            </p>
            {request.cancel_reason_th && <p>เหตุผล: {request.cancel_reason_th}</p>}
            {request.duplicate_of_repair_id && (
              <p>
                ซ้ำกับงานซ่อม <Link to={`/repairs/${request.duplicate_of_repair_id}`}>{request.duplicate_of_repair_id}</Link>
              </p>
            )}
            {request.duplicate_of_repair_request_id && (
              <p>
                ซ้ำกับคำขอ{' '}
                <Link to={`/repair-requests/${request.duplicate_of_repair_request_id}`}>
                  {request.duplicate_of_repair_request_id}
                </Link>
              </p>
            )}
            <p className="form-field__hint">ข้อมูลเดิมของคำขอยังคงเก็บไว้ทั้งหมด และคำขอนี้จะไม่ถูกเปิดเป็นใบงานซ่อม</p>
          </div>
        </Card>
      )}

      {request.request_status === 'PENDING' && canCancel && (
        <Card>
          <h2>ยกเลิกคำขอที่ซ้ำซ้อน</h2>
          <p className="form-field__hint">
            สำหรับคำขอที่แจ้งซ้ำกับงานซ่อมที่ดำเนินการอยู่แล้ว ระบบไม่ยกเลิกให้อัตโนมัติ ผู้จัดการต้องตรวจสอบและยืนยันเอง
          </p>
          <div className="form-field">
            <label htmlFor="rrq-cancel-reason">เหตุผลในการยกเลิก (จำเป็น)</label>
            <textarea id="rrq-cancel-reason" value={reason} onChange={(event) => setReason(event.target.value)} />
          </div>
          <div className="form-field">
            <label htmlFor="rrq-duplicate-of">เลขใบงานซ่อมที่ดำเนินการกับข้อบกพร่องเดียวกัน (ถ้ามี)</label>
            <input
              id="rrq-duplicate-of"
              value={duplicateRepairId}
              onChange={(event) => setDuplicateRepairId(event.target.value)}
              placeholder="เช่น RPR-0001"
            />
          </div>
          {cancelError && (
            <p className="form-field__error" role="alert">
              {cancelError}
            </p>
          )}
          <button
            type="button"
            className="button button--secondary button--full-width"
            disabled={busy}
            onClick={() => void cancel()}
          >
            ยกเลิกคำขอแจ้งซ่อม
          </button>
        </Card>
      )}
    </section>
  )
}
