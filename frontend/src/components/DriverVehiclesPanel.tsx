import { Link } from 'react-router-dom'
import { formatRegistryInstant, R2_PANEL_TITLES, RESPONSIBLE_DRIVER_NOTE } from '../lib/labels'
import { parseDriverVehicles, useR2Read, type DriverVehicles } from '../lib/r2History'
import { Card } from './Card'
import { LoadingState } from './LoadingState'
import { ResponsiveTable } from './ResponsiveTable'
import { R2ReadFailureView } from './TimelineHistoryTable'

type Item = DriverVehicles['items'][number]

/**
 * R2 Batch R2-C2a — the vehicles this driver is CURRENTLY the permanent
 * responsible driver of (R2f-f, `GET /drivers/{id}/vehicles`). The endpoint
 * returns current responsibilities only; past periods are on each vehicle's
 * page, never invented here. Permanent responsibility is not proof of driving
 * and is not the R2-C2b day / shift assignment.
 */
export function DriverVehiclesPanel({ driverId }: { driverId: string }) {
  const [state, reload] = useR2Read(`/drivers/${encodeURIComponent(driverId)}/vehicles`, parseDriverVehicles)
  return (
    <Card className="r2-panel">
      <h2>{R2_PANEL_TITLES.driverVehicles}</h2>
      <p className="form-field__hint" data-testid="responsible-driver-note">{RESPONSIBLE_DRIVER_NOTE}</p>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรถที่รับผิดชอบประจำ..." />}
      {state.kind === 'error' && (
        <R2ReadFailureView failure={state.failure} title="โหลดรถที่รับผิดชอบประจำไม่สำเร็จ" onRetry={reload} />
      )}
      {state.kind === 'ready' && (
        <div data-testid="driver-vehicles">
          <ResponsiveTable
            columns={[
              {
                key: 'vehicle',
                header: 'รถ',
                render: (item: Item) => <Link to={`/vehicle/${encodeURIComponent(item.vehicle_id)}`}>{item.vehicle_id}</Link>,
              },
              { key: 'since', header: 'รับผิดชอบตั้งแต่ (เวลาไทย)', render: (item: Item) => formatRegistryInstant(item.since) },
            ]}
            rows={state.data.items}
            getRowKey={(item) => item.vehicle_id}
            emptyTitle="ไม่มีรถที่รับผิดชอบประจำในปัจจุบัน"
            emptyDescription="แสดงเฉพาะความรับผิดชอบที่มีผลอยู่ในขณะนี้ ประวัติย้อนหลังดูได้ที่หน้ารถแต่ละคัน"
          />
        </div>
      )}
    </Card>
  )
}
