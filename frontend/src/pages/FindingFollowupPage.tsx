import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, type ApiResult } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  findingFollowupGroupLabel,
  formatThaiDate,
  inspectionResultLabel,
} from '../lib/labels'
import type { FindingDetail, FindingFollowupGroup } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: FindingDetail[] }

const GROUPS: FindingFollowupGroup[] = ['AWAITING_REPAIR_DECISION', 'IN_REPAIR']


function toLoadState(result: ApiResult<FindingDetail[]>): LoadState {
  if (result.ok) return { kind: 'ready', items: result.data }
  const err = result.error
  return {
    kind: 'error',
    message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

/**
 * R3-11 (contract §12): every active (OPEN) Finding, in two groups —
 * waiting for a repair decision, and with a repair round in progress. ENDED
 * Findings are history only. No priority, severity or due date (R3-10).
 */
export function FindingFollowupPage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const fetchData = useCallback(async () => {
    setState(toLoadState(await apiGet<FindingDetail[]>('/findings/follow-up')))
  }, [])

  useEffect(() => {
    let cancelled = false
    void apiGet<FindingDetail[]>('/findings/follow-up').then((result) => {
      if (!cancelled) setState(toLoadState(result))
    })
    return () => {
      cancelled = true
    }
  }, [])

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchData()
  }, [fetchData])

  return (
    <section className="page">
      <h1>ติดตามรายการผิดปกติ</h1>
      <p className="form-field__hint">
        รายการที่ยังอยู่ในรอบติดตาม แบ่งเป็นรอพิจารณาเปิดงานซ่อม และอยู่ระหว่างซ่อม ไม่มีการจัดลำดับความสำคัญหรือกำหนดเส้นตาย
      </p>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการผิดปกติ..." />}
      {state.kind === 'error' && <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />}
      {state.kind === 'ready' &&
        GROUPS.map((group) => {
          const rows = state.items.filter((d) => d.followup_group === group)
          return (
            <Card key={group}>
              <h2>
                {findingFollowupGroupLabel[group]} ({rows.length})
              </h2>
              {rows.length === 0 ? (
                <p>ไม่มีรายการ</p>
              ) : (
                <ul data-testid={`followup-${group}`}>
                  {rows.map(({ finding, repairs }) => {
                    const last = finding.observations?.at(-1)
                    const openRound = repairs.find((r) => r.status === 'OPEN')
                    return (
                      <li key={finding.finding_id}>
                        <Link to={`/findings/${finding.finding_id}`}>{finding.finding_id}</Link>{' '}
                        {assetTypeLabel[finding.asset_type] ?? finding.asset_type} {finding.asset_id} —{' '}
                        {finding.item_title}{' '}
                        {last && (
                          <StatusBadge
                            label={`${inspectionResultLabel[last.result] ?? last.result} ${formatThaiDate(last.inspection_date)}`}
                            tone="neutral"
                          />
                        )}{' '}
                        {openRound && <Link to={`/repairs/${openRound.repair_id}`}>{openRound.repair_id}</Link>}
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>
          )
        })}
    </section>
  )
}
