import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LifecyclePanel } from '../components/LifecyclePanel'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import { personnelLifecycleAdapter, personnelName, personnelStatusLabel } from '../lib/lifecycleAdapters'
import type { Personnel } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; personnel: Personnel }

async function fetchRecord(id: string): Promise<LoadState> {
  const result = await apiGet<Personnel>(`/personnel/${encodeURIComponent(id)}`)
  if (!result.ok) {
    const err = result.error
    return {
      kind: 'error',
      message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      requestId: err instanceof ApiError ? err.requestId : null,
    }
  }
  return { kind: 'ready', personnel: result.data }
}

/**
 * R2 Batch R2e — one personnel record: identity, name, status and lifecycle
 * (deactivate / reactivate / reconcile, with history). No department, branch,
 * account, technician or driver editing; no create or delete. Deactivating a
 * personnel record does not disable any login account.
 */
export function PersonnelDetailPage() {
  const { personnelId = '' } = useParams()
  const location = useLocation()
  const backTo = (location.state as { from?: string } | null)?.from ?? '/personnel'
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const reload = useCallback(() => {
    void fetchRecord(personnelId).then(setState)
  }, [personnelId])

  useEffect(() => {
    let cancelled = false
    void fetchRecord(personnelId).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [personnelId])

  return (
    <section className="page">
      <p>
        <Link to={backTo}>← กลับไปหน้ารายชื่อบุคลากร</Link>
      </p>
      <h1>ข้อมูลบุคลากร</h1>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูลบุคลากร..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={reload} />
      )}
      {state.kind === 'ready' && (
        <>
          <Card>
            <dl>
              <dt>รหัสบุคลากร</dt>
              <dd><code>{state.personnel.personnel_id}</code></dd>
              <dt>ชื่อ</dt>
              <dd>{personnelName(state.personnel)}</dd>
              <dt>สถานะ</dt>
              <dd>{personnelStatusLabel(state.personnel.active_status)}</dd>
            </dl>
          </Card>
          <LifecyclePanel
            adapter={personnelLifecycleAdapter}
            entityId={state.personnel.personnel_id}
            displayName={personnelName(state.personnel)}
            onChanged={reload}
          />
        </>
      )}
    </section>
  )
}
