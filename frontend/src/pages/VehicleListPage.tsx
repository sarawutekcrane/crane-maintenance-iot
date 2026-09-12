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
import type { OperationalStatus, Page, Vehicle, VehicleModel } from '../lib/types'

const STATUS_FILTERS: OperationalStatus[] = [
  'WORKING',
  'READY',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'LONG_TERM_PARKING',
]

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; vehicles: Vehicle[]; modelNameById: Map<string, string> }

export function VehicleListPage() {
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState<OperationalStatus | ''>('')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async (query: string, status: OperationalStatus | '') => {
    setState({ kind: 'loading' })

    const params = new URLSearchParams({ page_size: '50' })
    if (query.trim()) params.set('q', query.trim())
    if (status) params.set('status', status)

    const [vehiclesResult, modelsResult] = await Promise.all([
      apiGet<Page<Vehicle>>(`/vehicles?${params.toString()}`),
      apiGet<Page<VehicleModel>>('/models?page_size=200'),
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

    setState({ kind: 'ready', vehicles: vehiclesResult.data.items, modelNameById })
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
