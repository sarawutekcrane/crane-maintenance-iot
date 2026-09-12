import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  describeErrorCode,
  equipmentCategoryLabel,
  equipmentStatusLabel,
  equipmentStatusTone,
} from '../lib/labels'
import type { Equipment } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; equipment: Equipment }

export function EquipmentDetailPage() {
  const { equipmentId = '' } = useParams<{ equipmentId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Equipment>(`/equipment/${equipmentId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', equipment: result.data })
  }, [equipmentId])

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลเครื่องมือ..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายละเอียดเครื่องมือ</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { equipment } = state

  return (
    <section className="page">
      <h1>{equipment.name}</h1>
      <p>รหัสเครื่องมือ: {equipment.equipment_id}</p>

      <Card>
        <div className="status-card__actions">
          <Link
            to={`/equipment/${equipment.equipment_id}/inspect`}
            className="button button--primary button--full-width"
          >
            ตรวจเช็ค
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/inspections`}
            className="button button--secondary button--full-width"
          >
            ประวัติการตรวจเช็ค
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/pm`}
            className="button button--primary button--full-width"
          >
            PM
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/repairs/new`}
            className="button button--primary button--full-width"
          >
            แจ้งซ่อม
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/repairs`}
            className="button button--secondary button--full-width"
          >
            ประวัติการซ่อม
          </Link>
        </div>
      </Card>

      <Card>
        <div className="status-card__row">
          <span>รหัส</span>
          <span>{equipment.equipment_code}</span>
        </div>
        <div className="status-card__row">
          <span>ประเภท</span>
          <span>{equipmentCategoryLabel[equipment.category] ?? equipment.category}</span>
        </div>
        <div className="status-card__row">
          <span>หมายเลขซีเรียล</span>
          <span>{equipment.serial_number ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>ตำแหน่งที่ตั้ง</span>
          <span>{equipment.location ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>สถานะการใช้งาน</span>
          <StatusBadge
            label={equipmentStatusLabel[equipment.operational_status] ?? equipment.operational_status}
            tone={equipmentStatusTone[equipment.operational_status]}
          />
        </div>
      </Card>

      <p className="state-panel__meta">
        ข้อมูลอะไหล่/อายุการใช้งานและเอกสารของเครื่องมือจะเปิดให้ใช้งานในเฟสถัดไป
      </p>
    </section>
  )
}
