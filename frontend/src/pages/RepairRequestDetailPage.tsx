import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime, repairSourceTypeLabel } from '../lib/labels'
import type { RepairRequest } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; request: RepairRequest }

const REQUEST_STATUS_LABEL: Record<string, string> = {
  PENDING: 'รอตรวจรับ',
  CONVERTED: 'เปิดใบงานซ่อมแล้ว',
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
            tone={request.request_status === 'CONVERTED' ? 'success' : 'warning'}
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
    </section>
  )
}
