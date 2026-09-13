import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, trackingModeLabel } from '../lib/labels'
import type { Page, PartMaster, TrackingMode } from '../lib/types'

const TRACKING_MODE_FILTERS: TrackingMode[] = [
  'NONE',
  'CONSUMABLE',
  'POSITION_LIFETIME',
  'INSTANCE_TRACKED',
]

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; parts: PartMaster[] }

export function PartListPage() {
  const [q, setQ] = useState('')
  const [trackingMode, setTrackingMode] = useState<TrackingMode | ''>('')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async (query: string, mode: TrackingMode | '') => {
    setState({ kind: 'loading' })
    const params = new URLSearchParams({ page_size: '50' })
    if (query.trim()) params.set('q', query.trim())
    if (mode) params.set('tracking_mode', mode)

    const result = await apiGet<Page<PartMaster>>(`/parts?${params.toString()}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', parts: result.data.items })
  }, [])

  useEffect(() => {
    void load(q, trackingMode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="page">
      <h1>อะไหล่ (Part Master)</h1>
      <p>ค้นหาข้อมูลอะไหล่/วัสดุในระบบ แตะรายการเพื่อดูรายละเอียดและโหมดการติดตามอายุการใช้งาน</p>

      <Card>
        <form
          className="form-grid form-grid--two-column"
          onSubmit={(event) => {
            event.preventDefault()
            void load(q, trackingMode)
          }}
        >
          <FormField label="ค้นหา (ชื่อ/รหัสอะไหล่)" htmlFor="part-search-q">
            <input
              id="part-search-q"
              type="text"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="เช่น ไส้กรองน้ำมันเครื่อง"
            />
          </FormField>
          <FormField label="โหมดการติดตาม" htmlFor="part-search-mode">
            <select
              id="part-search-mode"
              value={trackingMode}
              onChange={(event) => {
                const next = event.target.value as TrackingMode | ''
                setTrackingMode(next)
                void load(q, next)
              }}
            >
              <option value="">ทั้งหมด</option>
              {TRACKING_MODE_FILTERS.map((mode) => (
                <option key={mode} value={mode}>
                  {trackingModeLabel[mode]}
                </option>
              ))}
            </select>
          </FormField>
          <button type="submit" className="button button--primary button--full-width">
            ค้นหา
          </button>
        </form>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการอะไหล่..." />}

      {state.kind === 'error' && (
        <ErrorState
          message={state.message}
          requestId={state.requestId}
          onRetry={() => void load(q, trackingMode)}
        />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'part_id',
              header: 'รหัสอะไหล่',
              render: (part) => <Link to={`/parts/${part.part_id}`}>{part.part_code}</Link>,
            },
            { key: 'name', header: 'ชื่ออะไหล่', render: (part) => part.name },
            {
              key: 'specification',
              header: 'สเปค',
              render: (part) => part.specification ?? '-',
            },
            {
              key: 'tracking_mode',
              header: 'โหมดการติดตาม',
              render: (part) => (
                <StatusBadge label={trackingModeLabel[part.tracking_mode] ?? part.tracking_mode} tone="info" />
              ),
            },
          ]}
          rows={state.parts}
          getRowKey={(part) => part.part_id}
          emptyTitle="ไม่พบอะไหล่"
          emptyDescription="ลองเปลี่ยนคำค้นหาหรือตัวกรองโหมดการติดตาม"
        />
      )}
    </section>
  )
}
