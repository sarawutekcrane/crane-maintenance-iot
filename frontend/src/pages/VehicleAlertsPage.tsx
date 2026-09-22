import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  alertSeverityLabel,
  alertSeverityTone,
  alertStatusLabel,
  alertStatusTone,
  describeErrorCode,
  formatThaiDateTime,
  missingAlertMessageLabel,
  missingAlertSourceLabel,
  unknownAlertFieldLabel,
  unknownAlertTypeLabel,
} from '../lib/labels'
import type { Alert } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; alerts: Alert[] }

function renderSource(alert: Alert): string {
  if (alert.source_type && alert.source_id) return `${alert.source_type} / ${alert.source_id}`
  if (alert.source_type) return alert.source_type
  if (alert.source_id) return alert.source_id
  return missingAlertSourceLabel
}

/**
 * Thai read-only Vehicle Alerts (Web/API Phase 6 Batch 6C). Consumes only
 * `GET /vehicles/{vehicleId}/alerts` — this page never writes to `alert`,
 * never sorts/re-sorts the returned array, and never renders an
 * acknowledge/mute/resolve/reopen control (A07/M02 remain unresolved —
 * see `app.domain.alert`/`app.api.v1.alerts` docstrings). Ordering is
 * entirely owned by the backend
 * (`app.domain.alert_service.AlertService.list_for_vehicle`); the array
 * is rendered exactly as received.
 */
export function VehicleAlertsPage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Alert[]>(`/vehicles/${vehicleId}/alerts`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', alerts: result.data })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>การแจ้งเตือน</h1>
      <p>รหัสยานพาหนะ: {vehicleId}</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดการแจ้งเตือน..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <Card>
          <ResponsiveTable
            columns={[
              {
                key: 'created_at',
                header: 'วันที่/เวลาที่สร้าง',
                render: (alert) => formatThaiDateTime(alert.created_at),
              },
              {
                key: 'message_th',
                header: 'ข้อความแจ้งเตือน',
                render: (alert) => alert.message_th ?? missingAlertMessageLabel,
              },
              {
                key: 'alert_type',
                header: 'ประเภทการแจ้งเตือน',
                render: (alert) => alert.alert_type ?? unknownAlertTypeLabel,
              },
              {
                key: 'severity',
                header: 'ระดับ',
                render: (alert) =>
                  alert.severity ? (
                    <StatusBadge
                      label={alertSeverityLabel[alert.severity] ?? alert.severity}
                      tone={alertSeverityTone[alert.severity]}
                    />
                  ) : (
                    <StatusBadge label={unknownAlertFieldLabel} tone="neutral" />
                  ),
              },
              {
                key: 'alert_status',
                header: 'สถานะ',
                render: (alert) =>
                  alert.alert_status ? (
                    <StatusBadge
                      label={alertStatusLabel[alert.alert_status] ?? alert.alert_status}
                      tone={alertStatusTone[alert.alert_status]}
                    />
                  ) : (
                    <StatusBadge label={unknownAlertFieldLabel} tone="neutral" />
                  ),
              },
              {
                key: 'source',
                header: 'แหล่งที่มา',
                render: (alert) => renderSource(alert),
              },
              {
                key: 'muted_until',
                header: 'ระงับถึง',
                render: (alert) => (alert.muted_until ? formatThaiDateTime(alert.muted_until) : '-'),
              },
            ]}
            rows={state.alerts}
            getRowKey={(alert) => alert.alert_id}
            emptyTitle="ไม่มีการแจ้งเตือน"
            emptyDescription="ยังไม่มีการแจ้งเตือนสำหรับยานพาหนะนี้"
          />
        </Card>
      )}
    </section>
  )
}
