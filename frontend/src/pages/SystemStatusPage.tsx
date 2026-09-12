import { useCallback, useEffect, useState } from 'react'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'

interface HealthResponse {
  status: string
  app_env: string
}

interface ReadinessCheck {
  name: string
  ready: boolean
  reason: string | null
}

interface ReadinessResponse {
  ready: boolean
  repository_mode: string
  checks: ReadinessCheck[]
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; health: HealthResponse; readiness: ReadinessResponse }

export function SystemStatusPage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [confirmOpen, setConfirmOpen] = useState(false)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })

    const healthResult = await apiGet<HealthResponse>('/health')
    if (!healthResult.ok) {
      const err = healthResult.error
      setState({
        kind: 'error',
        message: err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }

    const readinessResult = await apiGet<ReadinessResponse>('/readiness')
    if (!readinessResult.ok) {
      const err = readinessResult.error
      setState({
        kind: 'error',
        message: err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }

    setState({ kind: 'ready', health: healthResult.data, readiness: readinessResult.data })
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>สถานะระบบ</h1>
      <p>ตรวจสอบว่าหน้าเว็บสามารถเรียก API ของ Backend ได้สำเร็จหรือไม่ (สำหรับการพัฒนาเท่านั้น)</p>

      {state.kind === 'loading' && <LoadingState message="กำลังตรวจสอบสถานะระบบ..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <div className="status-card">
          <div className="status-card__row">
            <span>Backend Health</span>
            <StatusBadge
              label={state.health.status === 'ok' ? 'พร้อมใช้งาน' : state.health.status}
              tone={state.health.status === 'ok' ? 'success' : 'danger'}
            />
          </div>
          <div className="status-card__row">
            <span>โหมดข้อมูล (Repository)</span>
            <StatusBadge label={state.readiness.repository_mode} tone="neutral" />
          </div>
          <div className="status-card__row">
            <span>ความพร้อมใช้งานโดยรวม</span>
            <StatusBadge
              label={state.readiness.ready ? 'พร้อม' : 'ยังไม่พร้อม'}
              tone={state.readiness.ready ? 'success' : 'warning'}
            />
          </div>

          {state.readiness.checks.length === 0 ? (
            <EmptyState title="ไม่มีรายการตรวจสอบ" description="ยังไม่มีรายการตรวจสอบย่อยในขณะนี้" />
          ) : (
            <ul className="status-card__checks">
              {state.readiness.checks.map((check) => (
                <li key={check.name}>
                  <span>{check.name}</span>
                  <StatusBadge
                    label={check.ready ? 'ผ่าน' : check.reason ?? 'ไม่ผ่าน'}
                    tone={check.ready ? 'success' : 'warning'}
                  />
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            className="button button--secondary"
            onClick={() => setConfirmOpen(true)}
          >
            โหลดสถานะใหม่
          </button>
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title="ยืนยันการโหลดสถานะใหม่"
        description="ระบบจะเรียกข้อมูลสถานะจาก Backend อีกครั้ง"
        onConfirm={() => {
          setConfirmOpen(false)
          void load()
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </section>
  )
}
