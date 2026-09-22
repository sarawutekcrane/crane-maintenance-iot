import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import type { LatestLocation } from '../lib/types'
import { Card } from './Card'
import { LoadingState } from './LoadingState'

interface VehicleLatestLocationCardProps {
  vehicleId: string
}

type CardState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; location: LatestLocation | null }

/**
 * Web/API Phase 6 Batch 6D — read-only Thai GPS card for Vehicle Detail.
 * Fetches `GET /vehicles/{vehicleId}/latest-location` and manages its own
 * loading/error/no-location/location-present states so a GPS API failure
 * never hides or fails the rest of the Vehicle Detail page.
 *
 * Never shows a map/route/history — current-location display only (H02
 * GPS History remains deferred, H03 Location Privacy/Access remains
 * TBD-BLOCKING before production RBAC).
 */
export function VehicleLatestLocationCard({ vehicleId }: VehicleLatestLocationCardProps) {
  const [state, setState] = useState<CardState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<LatestLocation | null>(`/vehicles/${vehicleId}/latest-location`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', location: result.data })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <Card>
      <h2>ตำแหน่ง GPS ล่าสุด</h2>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดตำแหน่ง GPS..." />}
      {state.kind === 'error' && (
        <div role="alert">
          <p>{state.message}</p>
          {state.requestId && <p className="state-panel__meta">รหัสอ้างอิง: {state.requestId}</p>}
          <button
            type="button"
            className="button button--secondary button--full-width"
            onClick={() => void load()}
          >
            ลองใหม่อีกครั้ง
          </button>
        </div>
      )}
      {state.kind === 'ready' && <LatestLocationBody location={state.location} />}
    </Card>
  )
}

function LatestLocationBody({ location }: { location: LatestLocation | null }) {
  if (location === null) {
    return <p>ยังไม่มีข้อมูลตำแหน่ง GPS</p>
  }

  // Partial/legacy coordinate safety: only a genuine (lat, long) pair is
  // ever presented as a usable position — a single stray coordinate (or a
  // legacy row with neither) must never be shown as if it were valid.
  const hasFullCoordinates = location.latitude !== null && location.longitude !== null

  return (
    <>
      {hasFullCoordinates ? (
        <>
          <div className="status-card__row">
            <span>ละติจูด</span>
            <span>{location.latitude}</span>
          </div>
          <div className="status-card__row">
            <span>ลองจิจูด</span>
            <span>{location.longitude}</span>
          </div>
        </>
      ) : (
        <p>ข้อมูลตำแหน่ง GPS ไม่สมบูรณ์</p>
      )}

      <div className="status-card__row">
        <span>เวลา GPS</span>
        <span>{location.gps_time ? formatThaiDateTime(location.gps_time) : 'ไม่ทราบเวลา GPS'}</span>
      </div>
      <div className="status-card__row">
        <span>เวลาที่ระบบได้รับ</span>
        <span>
          {location.received_at
            ? formatThaiDateTime(location.received_at)
            : 'ไม่ทราบเวลาที่ระบบได้รับ'}
        </span>
      </div>
      <div className="status-card__row">
        <span>อุปกรณ์ IoT ต้นทาง</span>
        <span>{location.source_device_id ?? '-'}</span>
      </div>
      <div className="status-card__row">
        <span>ส่วนประกอบต้นทาง</span>
        <span>{location.source_component_id ?? '-'}</span>
      </div>
    </>
  )
}
