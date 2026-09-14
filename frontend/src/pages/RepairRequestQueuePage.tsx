import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import type { Page, RepairDetail, RepairRequest } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: RepairRequest[] }

/**
 * "รายการแจ้งซ่อมรอตรวจรับ" (Core Demo Fixes Delta REV05 section 5A) —
 * pending Repair Requests, Maintenance-only. Converting one opens a real
 * Repair Work Order (RPR-xxxx); an authorized Maintenance actor may also
 * open an RPR directly without a Repair Request (see `/vehicle/:id/repairs/new`).
 */
export function RepairRequestQueuePage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [convertingId, setConvertingId] = useState<string | null>(null)
  const [convertError, setConvertError] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<RepairRequest>>('/repair-requests/pending?page_size=100')
    if (!result.ok) {
      const err = result.error
      if (err instanceof ApiError && err.status === 403) {
        setState({ kind: 'denied' })
        return
      }
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', items: result.data.items })
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const convert = useCallback(
    async (repairRequestId: string) => {
      setConvertingId(repairRequestId)
      setConvertError(null)
      const result = await apiPost<RepairDetail>(
        `/repair-requests/${repairRequestId}/convert`,
        {},
      )
      setConvertingId(null)
      if (result.ok) {
        navigate(`/repairs/${result.data.repair.repair_id}`)
      } else {
        const err = result.error
        setConvertError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
      }
    },
    [navigate],
  )

  return (
    <section className="page">
      <h1>รายการแจ้งซ่อมรอตรวจรับ</h1>
      <p>ปัญหาที่มีการแจ้งเข้ามาและยังไม่ได้เปิดเป็นใบงานซ่อม สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุง</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการแจ้งซ่อม..." />}
      {state.kind === 'denied' && (
        <PermissionDeniedState message="หน้านี้สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุงเท่านั้น" />
      )}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.items.length === 0 && (
        <Card>
          <p>ไม่มีรายการแจ้งซ่อมรอตรวจรับในขณะนี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.items.map((item) => (
          <Card key={item.repair_request_id}>
            <div className="status-card__row">
              <span>ยานพาหนะ</span>
              <span>{item.vehicle_id}</span>
            </div>
            <div className="status-card__row">
              <span>แจ้งเมื่อ</span>
              <span>{formatThaiDateTime(item.reported_at)}</span>
            </div>
            {item.priority && (
              <div className="status-card__row">
                <span>ความสำคัญ</span>
                <span>{item.priority}</span>
              </div>
            )}
            {item.report_channel && (
              <div className="status-card__row">
                <span>ช่องทางแจ้ง</span>
                <span>{item.report_channel}</span>
              </div>
            )}
            <p>{item.symptom_th ?? '-'}</p>
            {item.note_th && <p className="form-field__hint">{item.note_th}</p>}

            {convertError && convertingId === null && (
              <ErrorState message={convertError} onRetry={() => setConvertError(null)} />
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={convertingId === item.repair_request_id}
              onClick={() => void convert(item.repair_request_id)}
            >
              {convertingId === item.repair_request_id ? 'กำลังเปิดใบงาน...' : 'เปิดใบงานซ่อม'}
            </button>
          </Card>
        ))}
    </section>
  )
}
