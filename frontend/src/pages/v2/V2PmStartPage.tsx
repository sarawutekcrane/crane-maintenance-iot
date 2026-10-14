import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { LoadingState } from '../../components/LoadingState'
import { V2ContextBanner } from '../../components/V2ContextBanner'
import { apiGet, apiPost } from '../../lib/apiClient'
import { CAN_MANAGE_PM } from '../../lib/capabilityNames'
import { readFailure, v2DetailRoute, type ReadFailure } from '../../lib/technicianV2'
import type { AssetType, PmPlanStatus, PmWorkOrderDetail } from '../../lib/types'
import { V2CreateGate } from './V2CreateGate'

type LoadState = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; plans: PmPlanStatus[] }

async function fetchPlans(assetType: AssetType, assetId: string): Promise<LoadState> {
  const result = await apiGet<PmPlanStatus[]>(
    `/pm/plans/status?asset_type=${assetType}&asset_id=${encodeURIComponent(assetId)}`,
  )
  return result.ok ? { kind: 'ready', plans: result.data } : { kind: 'error', failure: readFailure(result.error) }
}

function PlanList({ assetType, assetId }: { assetType: AssetType; assetId: string }) {
  const navigate = useNavigate()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [openingPlanId, setOpeningPlanId] = useState<string | null>(null)
  const [openFailure, setOpenFailure] = useState<ReadFailure | null>(null)
  const inFlight = useRef(false)

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchPlans(assetType, assetId).then(setState)
  }, [assetType, assetId])

  useEffect(() => {
    let cancelled = false
    void fetchPlans(assetType, assetId).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [assetType, assetId])

  const start = async (pmPlanId: string) => {
    if (inFlight.current) return
    inFlight.current = true
    setOpeningPlanId(pmPlanId)
    setOpenFailure(null)
    // Existing POST /pm/work-orders; it carries no technician field at all.
    const result = await apiPost<PmWorkOrderDetail>('/pm/work-orders', {
      asset_type: assetType,
      asset_id: assetId,
      pm_plan_id: pmPlanId,
    })
    inFlight.current = false
    setOpeningPlanId(null)
    if (result.ok) navigate(v2DetailRoute('PM', result.data.work_order.pm_work_order_id))
    else setOpenFailure(readFailure(result.error))
  }

  if (state.kind === 'loading') return <LoadingState message="กำลังโหลดแผน PM..." />
  if (state.kind === 'error') {
    return (
      <ErrorState
        message={state.failure.message}
        code={state.failure.code}
        requestId={state.failure.requestId}
        onRetry={() => load()}
      />
    )
  }
  if (state.plans.length === 0) return <EmptyState title="ไม่มีแผน PM" description="ยังไม่มีแผนบำรุงรักษาที่ใช้งานสำหรับสินทรัพย์นี้" />
  return (
    <>
      {openFailure && (
        <ErrorState
          title="เปิดใบสั่งงาน PM ไม่สำเร็จ"
          message={openFailure.message}
          code={openFailure.code}
          requestId={openFailure.requestId}
        />
      )}
      {state.plans.map((planStatus) => (
        <Card key={planStatus.plan.pm_plan_id}>
          <h2>{planStatus.plan.name}</h2>
          <p className="form-field__hint">รหัสแผน: {planStatus.plan.plan_code}</p>
          {planStatus.active_revision ? (
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={openingPlanId !== null}
              onClick={() => void start(planStatus.plan.pm_plan_id)}
            >
              {openingPlanId === planStatus.plan.pm_plan_id ? 'กำลังเปิดใบสั่งงาน...' : 'เริ่มทำ PM (V2)'}
            </button>
          ) : (
            <p>ยังไม่มีรุ่นรายการงานที่ใช้งานอยู่สำหรับแผนนี้</p>
          )}
        </Card>
      ))}
    </>
  )
}

/**
 * R2 Batch R2f-h4 B4 — V2 PM work-order creation (parallel route, Option 1).
 * The plan list and the existing `POST /pm/work-orders` are reached only behind
 * the creation gate: with the cutover OFF, no request other than GET /me is made.
 */
export function V2PmStartPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''
  return (
    <section className="page">
      <h1>PM (V2)</h1>
      <p>รหัสอ้างอิง: {assetId}</p>
      <V2ContextBanner />
      <V2CreateGate capability={CAN_MANAGE_PM}>
        <PlanList assetType={assetType} assetId={assetId} />
      </V2CreateGate>
    </section>
  )
}
