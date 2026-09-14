import { useEffect, useState } from 'react'
import { apiGet } from '../lib/apiClient'
import { counterTypeLabel, formatThaiDateTime } from '../lib/labels'
import type { AssetType, CurrentMachineState } from '../lib/types'
import { Card } from './Card'
import { LoadingState } from './LoadingState'

interface MachineStateReadOnlyProps {
  assetType: AssetType
  assetId: string
}

/**
 * Core Demo Fixes, APPROVED CORE RULE: read-only display of the backend's
 * automatically-derived current machine state — never a manual counter/GPS
 * entry field. The value shown here is exactly what the backend will
 * capture automatically into this event's own snapshot; the user cannot
 * edit it here (see `MeterService.capture_current_state`/
 * `preview_current_state`).
 */
export function MachineStateReadOnly({ assetType, assetId }: MachineStateReadOnlyProps) {
  const [state, setState] = useState<CurrentMachineState | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void apiGet<CurrentMachineState>(
      `/machine-state/current?asset_type=${assetType}&asset_id=${assetId}`,
    ).then((result) => {
      if (cancelled) return
      if (result.ok) setState(result.data)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [assetType, assetId])

  if (loading) {
    return <LoadingState message="กำลังโหลดค่ามาตรวัดล่าสุด..." />
  }

  if (!state) return null

  return (
    <Card>
      <h2>ค่ามาตรวัดปัจจุบัน (อ่านอย่างเดียว)</h2>
      <p className="form-field__hint">
        ระบบบันทึกค่านี้ให้อัตโนมัติจากข้อมูลล่าสุดที่ระบบทราบ ไม่ต้องกรอกด้วยตนเอง
      </p>
      {state.readings.length === 0 && <p>ไม่มีข้อมูลส่วนประกอบสำหรับสินทรัพย์นี้</p>}
      {state.readings.map((reading, index) => (
        <div className="status-card__row" key={index}>
          <span>{counterTypeLabel[reading.counter_type] ?? reading.counter_type}</span>
          <span>
            {reading.value == null ? (
              'ไม่ทราบค่า'
            ) : (
              <>
                {reading.value}
                {reading.observed_at && (
                  <span className="form-field__hint"> (ณ {formatThaiDateTime(reading.observed_at)})</span>
                )}
              </>
            )}
          </span>
        </div>
      ))}
      <p className="form-field__hint">{state.note}</p>
    </Card>
  )
}
