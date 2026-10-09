import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LifecyclePanel } from '../components/LifecyclePanel'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import { departmentLifecycleAdapter, departmentStatusLabel } from '../lib/lifecycleAdapters'
import type { Department } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; department: Department }

async function fetchRecord(id: string): Promise<LoadState> {
  const result = await apiGet<Department>(`/departments/${encodeURIComponent(id)}`)
  if (!result.ok) {
    const err = result.error
    return {
      kind: 'error',
      message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      requestId: err instanceof ApiError ? err.requestId : null,
    }
  }
  return { kind: 'ready', department: result.data }
}

/**
 * R2 Batch R2e — one department record: identity, name, status and lifecycle.
 * No create, rename or delete; a department lifecycle change never rewrites
 * any personnel record.
 */
export function DepartmentDetailPage() {
  const { departmentId = '' } = useParams()
  const location = useLocation()
  const backTo = (location.state as { from?: string } | null)?.from ?? '/departments'
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const reload = useCallback(() => {
    void fetchRecord(departmentId).then(setState)
  }, [departmentId])

  useEffect(() => {
    let cancelled = false
    void fetchRecord(departmentId).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [departmentId])

  return (
    <section className="page">
      <p>
        <Link to={backTo}>← กลับไปหน้ารายชื่อแผนก</Link>
      </p>
      <h1>ข้อมูลแผนก</h1>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูลแผนก..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={reload} />
      )}
      {state.kind === 'ready' && (
        <>
          <Card>
            <dl>
              <dt>รหัสแผนก</dt>
              <dd><code>{state.department.department_id}</code></dd>
              <dt>ชื่อแผนก</dt>
              <dd>{state.department.department_name_th}</dd>
              <dt>สถานะ</dt>
              <dd>{departmentStatusLabel(state.department.is_active)}</dd>
            </dl>
          </Card>
          <LifecyclePanel
            adapter={departmentLifecycleAdapter}
            entityId={state.department.department_id}
            displayName={state.department.department_name_th}
            onChanged={reload}
          />
        </>
      )}
    </section>
  )
}
