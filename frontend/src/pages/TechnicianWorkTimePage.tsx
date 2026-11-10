import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import type { TechnicianWorkTimeResponse } from '../lib/types'

type State =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: TechnicianWorkTimeResponse }

function hours(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return m ? `${h} ชม. ${m} นาที` : `${h} ชม.`
}

function bangkok(iso: string): string {
  return new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Bangkok' }).format(
    new Date(iso),
  )
}

/** Today's Asia/Bangkok date, shifted by `days`, as YYYY-MM-DD. */
function bangkokDate(days: number): string {
  return new Date(Date.now() + 7 * 3600 * 1000 + days * 86400 * 1000).toISOString().slice(0, 10)
}

/**
 * R5 — one technician's actual work across Work Orders (RM-9, RM-11): every recorded
 * period inside the chosen Asia/Bangkok date range, regular / overtime totals and the
 * actual dates worked. Readable by a manager or by the technician themself (server-checked).
 */
export function TechnicianWorkTimePage() {
  const { assigneeId = '' } = useParams<{ assigneeId: string }>()
  const [from, setFrom] = useState(bangkokDate(-6))
  const [to, setTo] = useState(bangkokDate(0))
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    const query = new URLSearchParams({ from: `${from}T00:00:00+07:00`, to: `${to}T23:59:59+07:00` })
    void apiGet<TechnicianWorkTimeResponse>(`/work-time/assignees/${encodeURIComponent(assigneeId)}?${query}`).then((result) => {
      if (cancelled) return
      if (result.ok) setState({ kind: 'ready', data: result.data })
      else if (result.error instanceof ApiError && result.error.status === 403) setState({ kind: 'denied' })
      else
        setState({
          kind: 'error',
          message: result.error instanceof ApiError ? describeErrorCode(result.error.code) : 'โหลดข้อมูลไม่สำเร็จ',
        })
    })
    return () => {
      cancelled = true
    }
  }, [assigneeId, from, to, reload])

  const load = () => {
    setState({ kind: 'loading' })
    setReload((n) => n + 1)
  }

  return (
    <section className="page">
      <h1>เวลาทำงานของช่าง</h1>
      <p>รหัสช่าง: {assigneeId}</p>
      <Card>
        <div className="form-grid">
          <label htmlFor="wt-from">ตั้งแต่วันที่</label>
          <input id="wt-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <label htmlFor="wt-to">ถึงวันที่</label>
          <input id="wt-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </Card>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดเวลาทำงาน..." />}
      {state.kind === 'denied' && <PermissionDeniedState message="คุณดูเวลาทำงานของช่างคนอื่นไม่ได้ (เฉพาะผู้จัดการหรือช่างเจ้าของข้อมูล)" />}
      {state.kind === 'error' && <ErrorState message={state.message} onRetry={load} />}
      {state.kind === 'ready' && (
        <>
          <Card>
            <h2>สรุป</h2>
            <div className="status-card__row">
              <span>เวลาปกติ</span>
              <span data-testid="twt-regular">{hours(state.data.totals.regular_seconds)}</span>
            </div>
            <div className="status-card__row">
              <span>ล่วงเวลา (OT)</span>
              <span data-testid="twt-overtime">{hours(state.data.totals.overtime_seconds)}</span>
            </div>
            <div className="status-card__row">
              <span>รวมชั่วโมงทำงานจริง</span>
              <span data-testid="twt-total">{hours(state.data.totals.total_seconds)}</span>
            </div>
            <div className="status-card__row">
              <span>จำนวนวันที่ทำงานจริง</span>
              <span data-testid="twt-workdays">{state.data.totals.workdays.length} วัน</span>
            </div>
          </Card>
          <Card>
            <h2>ช่วงเวลาทำงาน</h2>
            {state.data.entries.length === 0 && <p>ไม่มีการบันทึกเวลาทำงานในช่วงวันที่นี้</p>}
            <ul>
              {state.data.entries.map((entry) => (
                <li key={entry.entry_id} data-testid="twt-entry">
                  {bangkok(entry.started_at)} – {bangkok(entry.ended_at)} ·{' '}
                  {entry.time_class === 'OVERTIME' ? 'ล่วงเวลา (OT)' : 'เวลาปกติ'} ·{' '}
                  <Link to={entry.work_kind === 'REPAIR' ? `/repairs/${entry.job_id}` : `/pm/work-orders/${entry.job_id}`}>
                    {entry.work_kind === 'REPAIR' ? 'งานซ่อม' : 'งาน PM'} {entry.job_id}
                  </Link>{' '}
                  · {entry.description}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </section>
  )
}
