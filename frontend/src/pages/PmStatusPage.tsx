import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import type { AssetType, PmPlanStatus, PmWorkOrderDetail } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; plans: PmPlanStatus[] }

/**
 * PM summary for one asset (Phase 4). Backend-authoritative
 * `due_status`/`due_status_note` are rendered as-is — this page never
 * computes its own due/remaining value (E02/E03/E04 unresolved).
 */
export function PmStatusPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''
  const historyPath = vehicleId ? `/vehicle/${vehicleId}/pm/history` : `/equipment/${equipmentId}/pm/history`

  const navigate = useNavigate()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [openingPlanId, setOpeningPlanId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<PmPlanStatus[]>(
      `/pm/plans/status?asset_type=${assetType}&asset_id=${assetId}`,
    )
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', plans: result.data })
  }, [assetType, assetId])

  useEffect(() => {
    void load()
  }, [load])

  const startWorkOrder = useCallback(
    async (pmPlanId: string) => {
      setOpeningPlanId(pmPlanId)
      const result = await apiPost<PmWorkOrderDetail>('/pm/work-orders', {
        asset_type: assetType,
        asset_id: assetId,
        pm_plan_id: pmPlanId,
      })
      setOpeningPlanId(null)
      if (result.ok) {
        navigate(`/pm/work-orders/${result.data.work_order.pm_work_order_id}`)
      }
    },
    [assetType, assetId, navigate],
  )

  return (
    <section className="page">
      <h1>PM (บำรุงรักษาเชิงป้องกัน)</h1>
      <p>รหัสอ้างอิง: {assetId}</p>

      <Card>
        <Link to={historyPath} className="button button--secondary button--full-width">
          ประวัติ PM
        </Link>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูล PM..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.plans.length === 0 && (
        <Card>
          <p>ยังไม่มีแผนบำรุงรักษาที่ใช้งานสำหรับสินทรัพย์นี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.plans.map((planStatus) => (
          <Card key={planStatus.plan.pm_plan_id}>
            <h2>{planStatus.plan.name}</h2>
            <p className="form-field__hint">รหัสแผน: {planStatus.plan.plan_code}</p>

            {planStatus.active_revision ? (
              <p>รุ่นรายการงานปัจจุบัน: รุ่นที่ {planStatus.active_revision.revision_number}</p>
            ) : (
              <p>ยังไม่มีรุ่นรายการงานที่ใช้งานอยู่สำหรับแผนนี้</p>
            )}

            <div className="status-card__row">
              <span>งานล่าสุดที่เสร็จสิ้น</span>
              <span>
                {planStatus.last_completed_at
                  ? formatThaiDateTime(planStatus.last_completed_at)
                  : 'ยังไม่มีประวัติ'}
              </span>
            </div>

            <div className="status-card__row">
              <span>สถานะกำหนดถึงรอบ (Due)</span>
              <span>ไม่สามารถคำนวณได้ในขณะนี้</span>
            </div>
            <p className="form-field__hint">{planStatus.due_status_note}</p>

            {planStatus.active_revision && (
              <div className="status-card__actions">
                <button
                  type="button"
                  className="button button--primary button--full-width"
                  disabled={openingPlanId === planStatus.plan.pm_plan_id}
                  onClick={() => void startWorkOrder(planStatus.plan.pm_plan_id)}
                >
                  {openingPlanId === planStatus.plan.pm_plan_id
                    ? 'กำลังเปิดใบสั่งงาน...'
                    : 'เริ่มทำ PM'}
                </button>
              </div>
            )}
          </Card>
        ))}
    </section>
  )
}
