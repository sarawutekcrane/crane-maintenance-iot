import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  describeErrorCode,
  formatThaiDateTime,
  timeQualityLabel,
  timeQualityTone,
  vehicleEventTypeLabel,
} from '../lib/labels'
import type { VehicleEvent } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; events: VehicleEvent[] }

const UNKNOWN_EVENT_TIME_TH = 'ไม่ทราบเวลาที่เกิดเหตุการณ์'

/**
 * Thai read-only Vehicle Work History (Web/API Phase 6 Batch 6A). Consumes
 * only `GET /vehicles/{vehicleId}/events` — this page never writes to
 * `vehicle_event`, never sorts/re-sorts the returned array, and never
 * substitutes `received_at` for a missing `event_time`. History ordering
 * is entirely owned by the backend
 * (`app.domain.vehicle_event_service.order_for_history`); the array is
 * rendered exactly as received.
 */
export function VehicleWorkHistoryPage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<VehicleEvent[]>(`/vehicles/${vehicleId}/events`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', events: result.data })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>ประวัติการทำงาน</h1>
      <p>รหัสยานพาหนะ: {vehicleId}</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติการทำงาน..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <Card>
          <ResponsiveTable
            columns={[
              {
                key: 'event_time',
                header: 'เวลาที่เกิดเหตุการณ์',
                render: (event) =>
                  event.event_time ? formatThaiDateTime(event.event_time) : UNKNOWN_EVENT_TIME_TH,
              },
              {
                key: 'event_type',
                header: 'เหตุการณ์',
                render: (event) => vehicleEventTypeLabel[event.event_type] ?? event.event_type,
              },
              {
                key: 'component_id',
                header: 'ส่วนประกอบ',
                render: (event) => event.component_id,
              },
              {
                key: 'device_id',
                header: 'อุปกรณ์ IoT',
                render: (event) => event.device_id,
              },
              {
                key: 'sequence',
                header: 'ลำดับจากอุปกรณ์',
                render: (event) => String(event.sequence),
              },
              {
                key: 'time_quality',
                header: 'สถานะเวลา',
                render: (event) => (
                  <StatusBadge
                    label={timeQualityLabel[event.time_quality] ?? event.time_quality}
                    tone={timeQualityTone[event.time_quality]}
                  />
                ),
              },
              {
                key: 'created_offline',
                header: 'อัปโหลดหลังออฟไลน์หรือไม่',
                render: (event) => (event.created_offline ? 'ใช่' : 'ไม่ใช่'),
              },
              {
                key: 'received_at',
                header: 'เวลาที่ระบบได้รับ',
                render: (event) => formatThaiDateTime(event.received_at),
              },
              {
                key: 'note_th',
                header: 'หมายเหตุ',
                render: (event) => event.note_th ?? '-',
              },
            ]}
            rows={state.events}
            getRowKey={(event) => event.event_id}
            emptyTitle="ไม่มีประวัติการทำงาน"
            emptyDescription="ยังไม่มีข้อมูลเหตุการณ์สำหรับยานพาหนะนี้"
          />
        </Card>
      )}
    </section>
  )
}
