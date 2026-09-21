import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  dailySummaryDataStatusLabel,
  dailySummaryDataStatusTone,
  dailySummaryMetricTypeLabel,
  describeErrorCode,
  formatThaiDate,
  formatThaiDateTime,
} from '../lib/labels'
import type { DailySummary } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; summaries: DailySummary[] }

const UNPROVABLE_DURATION_TH = 'ไม่สามารถคำนวณระยะเวลาได้จากข้อมูลที่มี'

function formatDurationSeconds(value: number | null): string {
  if (value === null) return UNPROVABLE_DURATION_TH
  return `${value} วินาที`
}

/**
 * Thai read-only Vehicle Daily Summary (Web/API Phase 6 Batch 6B). Consumes
 * only `GET /vehicles/{vehicleId}/daily-summaries` — this page never writes
 * to `daily_summary`, never sorts/re-sorts the returned array, never
 * recomputes/reconciles durations itself, and never treats `value: null`
 * (no provable duration) the same as a genuine `0` (a proven zero-duration
 * interval). Ordering is entirely owned by the backend
 * (`app.domain.daily_summary_service.DailySummaryService.list_for_vehicle`);
 * the array is rendered exactly as received.
 */
export function VehicleDailySummaryPage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<DailySummary[]>(`/vehicles/${vehicleId}/daily-summaries`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', summaries: result.data })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>สรุปการทำงานรายวัน</h1>
      <p>รหัสยานพาหนะ: {vehicleId}</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดสรุปการทำงานรายวัน..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <Card>
          <ResponsiveTable
            columns={[
              {
                key: 'summary_date',
                header: 'วันที่',
                render: (summary) => formatThaiDate(summary.summary_date),
              },
              {
                key: 'component_id',
                header: 'ส่วนประกอบ',
                render: (summary) => summary.component_id,
              },
              {
                key: 'metric_type',
                header: 'ประเภทการทำงาน',
                render: (summary) =>
                  dailySummaryMetricTypeLabel[summary.metric_type] ?? summary.metric_type,
              },
              {
                key: 'value',
                header: 'ระยะเวลา',
                render: (summary) => formatDurationSeconds(summary.value),
              },
              {
                key: 'data_status',
                header: 'สถานะข้อมูล',
                render: (summary) => (
                  <StatusBadge
                    label={dailySummaryDataStatusLabel[summary.data_status] ?? summary.data_status}
                    tone={dailySummaryDataStatusTone[summary.data_status]}
                  />
                ),
              },
              {
                key: 'created_at',
                header: 'เวลาที่ระบบสร้างข้อมูล',
                render: (summary) => formatThaiDateTime(summary.created_at),
              },
            ]}
            rows={state.summaries}
            getRowKey={(summary) => summary.daily_summary_id}
            emptyTitle="ไม่มีข้อมูลสรุปการทำงานรายวัน"
            emptyDescription="ยังไม่มีข้อมูลสรุปการทำงานรายวันสำหรับยานพาหนะนี้"
          />
        </Card>
      )}
    </section>
  )
}
