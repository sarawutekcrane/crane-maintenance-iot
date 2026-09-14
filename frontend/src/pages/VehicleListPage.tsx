import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, operationalStatusLabel, operationalStatusTone } from '../lib/labels'
import type {
  InspectionFinding,
  OperationalStatus,
  Page,
  PmWorkOrderSummary,
  RepairSummary,
  Vehicle,
  VehicleModel,
} from '../lib/types'

const STATUS_FILTERS: OperationalStatus[] = [
  'WORKING',
  'READY',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'LONG_TERM_PARKING',
]

interface VehicleIndicators {
  openRepairCount: number
  openPmCount: number
  unresolvedFindingCount: number
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | {
      kind: 'ready'
      vehicles: Vehicle[]
      modelNameById: Map<string, string>
      indicatorsByVehicleId: Map<string, VehicleIndicators>
    }

function countByAssetId<T extends { asset_id: string }>(items: T[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const item of items) {
    counts.set(item.asset_id, (counts.get(item.asset_id) ?? 0) + 1)
  }
  return counts
}

export function VehicleListPage() {
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState<OperationalStatus | ''>('')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async (query: string, status: OperationalStatus | '') => {
    setState({ kind: 'loading' })

    const params = new URLSearchParams({ page_size: '50' })
    if (query.trim()) params.set('q', query.trim())
    if (status) params.set('status', status)

    // Core Demo Fixes, VEHICLE LIST / CORE STATUS SUMMARY: one list call
    // per indicator (never one call per vehicle row), using only data
    // already available from Phases 1-5.
    const [vehiclesResult, modelsResult, repairsResult, pmResult, findingsResult] =
      await Promise.all([
        apiGet<Page<Vehicle>>(`/vehicles?${params.toString()}`),
        apiGet<Page<VehicleModel>>('/models?page_size=200'),
        apiGet<Page<RepairSummary>>('/repairs?asset_type=VEHICLE&status=OPEN&page_size=200'),
        apiGet<Page<PmWorkOrderSummary>>(
          '/pm/work-orders?asset_type=VEHICLE&status=OPEN&page_size=200',
        ),
        apiGet<InspectionFinding[]>('/findings?asset_type=VEHICLE&status=OPEN'),
      ])

    if (!vehiclesResult.ok) {
      const err = vehiclesResult.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }

    const modelNameById = new Map<string, string>()
    if (modelsResult.ok) {
      for (const model of modelsResult.data.items) {
        modelNameById.set(model.model_id, model.model_name)
      }
    }

    const repairCounts = countByAssetId(repairsResult.ok ? repairsResult.data.items : [])
    const pmCounts = countByAssetId(pmResult.ok ? pmResult.data.items : [])
    const findingCounts = countByAssetId(findingsResult.ok ? findingsResult.data : [])

    const indicatorsByVehicleId = new Map<string, VehicleIndicators>()
    for (const vehicle of vehiclesResult.data.items) {
      indicatorsByVehicleId.set(vehicle.vehicle_id, {
        openRepairCount: repairCounts.get(vehicle.vehicle_id) ?? 0,
        openPmCount: pmCounts.get(vehicle.vehicle_id) ?? 0,
        unresolvedFindingCount: findingCounts.get(vehicle.vehicle_id) ?? 0,
      })
    }

    setState({
      kind: 'ready',
      vehicles: vehiclesResult.data.items,
      modelNameById,
      indicatorsByVehicleId,
    })
  }, [])

  useEffect(() => {
    void load(q, statusFilter)
    // Only re-run on explicit search submit / filter change, not per keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="page">
      <h1>ยานพาหนะ</h1>
      <p>ค้นหาและดูรายการรถเครนในระบบ แตะรายการเพื่อดูรายละเอียด</p>

      <Card>
        <form
          className="form-grid form-grid--two-column"
          onSubmit={(event) => {
            event.preventDefault()
            void load(q, statusFilter)
          }}
        >
          <FormField label="ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)" htmlFor="vehicle-search-q">
            <input
              id="vehicle-search-q"
              type="text"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="เช่น TC-12"
            />
          </FormField>
          <FormField label="สถานะ" htmlFor="vehicle-search-status">
            <select
              id="vehicle-search-status"
              value={statusFilter}
              onChange={(event) => {
                const next = event.target.value as OperationalStatus | ''
                setStatusFilter(next)
                void load(q, next)
              }}
            >
              <option value="">ทั้งหมด</option>
              {STATUS_FILTERS.map((status) => (
                <option key={status} value={status}>
                  {operationalStatusLabel[status]}
                </option>
              ))}
            </select>
          </FormField>
          <button type="submit" className="button button--primary button--full-width">
            ค้นหา
          </button>
        </form>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการยานพาหนะ..." />}

      {state.kind === 'error' && (
        <ErrorState
          message={state.message}
          requestId={state.requestId}
          onRetry={() => void load(q, statusFilter)}
        />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'vehicle_id',
              header: 'รหัสยานพาหนะ',
              render: (vehicle) => (
                <Link to={`/vehicle/${vehicle.vehicle_id}`}>{vehicle.vehicle_id}</Link>
              ),
            },
            { key: 'machine_no', header: 'เลขเครื่องจักร', render: (v) => v.machine_no },
            {
              key: 'model',
              header: 'รุ่น',
              render: (v) => state.modelNameById.get(v.model_id) ?? v.model_id,
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: (v) => (
                <StatusBadge
                  label={operationalStatusLabel[v.operational_status] ?? v.operational_status}
                  tone={operationalStatusTone[v.operational_status]}
                />
              ),
            },
            {
              key: 'indicators',
              header: 'สรุปสถานะงาน',
              render: (v) => {
                const indicators = state.indicatorsByVehicleId.get(v.vehicle_id)
                if (
                  !indicators ||
                  (indicators.openRepairCount === 0 &&
                    indicators.openPmCount === 0 &&
                    indicators.unresolvedFindingCount === 0)
                ) {
                  return <span className="vehicle-indicators__none">ไม่มีงานค้าง</span>
                }
                return (
                  <div className="vehicle-indicators">
                    {indicators.openRepairCount > 0 && (
                      <Link
                        to={`/vehicle/${v.vehicle_id}/repairs`}
                        className="vehicle-indicators__badge vehicle-indicators__badge--repair"
                      >
                        ซ่อม {indicators.openRepairCount}
                      </Link>
                    )}
                    {indicators.openPmCount > 0 && (
                      <Link
                        to={`/vehicle/${v.vehicle_id}/pm`}
                        className="vehicle-indicators__badge vehicle-indicators__badge--pm"
                      >
                        PM {indicators.openPmCount}
                      </Link>
                    )}
                    {indicators.unresolvedFindingCount > 0 && (
                      <Link
                        to={`/vehicle/${v.vehicle_id}/inspections`}
                        className="vehicle-indicators__badge vehicle-indicators__badge--finding"
                      >
                        ข้อบกพร่อง {indicators.unresolvedFindingCount}
                      </Link>
                    )}
                  </div>
                )
              },
            },
          ]}
          rows={state.vehicles}
          getRowKey={(v) => v.vehicle_id}
          emptyTitle="ไม่พบยานพาหนะ"
          emptyDescription="ลองเปลี่ยนคำค้นหาหรือตัวกรองสถานะ"
        />
      )}
    </section>
  )
}
