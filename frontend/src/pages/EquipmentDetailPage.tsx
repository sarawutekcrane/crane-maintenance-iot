import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ChangeEquipmentStatusDialog } from '../components/ChangeEquipmentStatusDialog'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import {
  describeErrorCode,
  equipmentCategoryLabel,
  equipmentStatusLabel,
  equipmentStatusTone,
  formatThaiDateTime,
} from '../lib/labels'
import type { Equipment, EquipmentOperationalStatus, EquipmentStatusHistoryEntry } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; equipment: Equipment; history: EquipmentStatusHistoryEntry[] }

export function EquipmentDetailPage() {
  const { equipmentId = '' } = useParams<{ equipmentId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [statusDialogOpen, setStatusDialogOpen] = useState(false)
  const [statusSubmitting, setStatusSubmitting] = useState(false)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const [equipmentResult, historyResult] = await Promise.all([
      apiGet<Equipment>(`/equipment/${equipmentId}`),
      apiGet<EquipmentStatusHistoryEntry[]>(`/equipment/${equipmentId}/status-history`),
    ])
    if (!equipmentResult.ok) {
      const err = equipmentResult.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({
      kind: 'ready',
      equipment: equipmentResult.data,
      history: historyResult.ok ? historyResult.data : [],
    })
  }, [equipmentId])

  useEffect(() => {
    void load()
  }, [load])

  const submitStatusChange = useCallback(
    async (status: EquipmentOperationalStatus, reason: string) => {
      setStatusSubmitting(true)
      const result = await apiPost<Equipment>(`/equipment/${equipmentId}/status`, {
        status,
        reason: reason || null,
      })
      setStatusSubmitting(false)
      if (result.ok) {
        setStatusDialogOpen(false)
        void load()
      }
    },
    [equipmentId, load],
  )

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

  const { equipment, history } = state
  const isRetired = equipment.operational_status === 'RETIRED'

  return (
    <section className="page">
      <h1>{equipment.name}</h1>
      <p>รหัสเครื่องมือ: {equipment.equipment_id}</p>

      {isRetired && (
        <Card className="state-panel state-panel--denied">
          <p className="state-panel__title">เครื่องมือนี้ถูกปลดระวางแล้ว</p>
          <p>ไม่สามารถเริ่มงานตรวจเช็ค PM หรือแจ้งซ่อมใหม่สำหรับเครื่องมือนี้ได้ (ประวัติเดิมยังคงอยู่ครบถ้วน)</p>
        </Card>
      )}

      <Card>
        <div className="status-card__actions">
          <Link
            to={`/equipment/${equipment.equipment_id}/inspect`}
            className="button button--primary button--full-width"
            aria-disabled={isRetired}
            onClick={(event) => isRetired && event.preventDefault()}
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
            aria-disabled={isRetired}
            onClick={(event) => isRetired && event.preventDefault()}
          >
            PM
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/repairs/new`}
            className="button button--primary button--full-width"
            aria-disabled={isRetired}
            onClick={(event) => isRetired && event.preventDefault()}
          >
            แจ้งซ่อม
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/repairs`}
            className="button button--secondary button--full-width"
          >
            ประวัติการซ่อม
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/parts`}
            className="button button--secondary button--full-width"
          >
            อะไหล่/อายุการใช้งาน
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
        <button
          type="button"
          className="button button--secondary button--full-width"
          onClick={() => setStatusDialogOpen(true)}
        >
          เปลี่ยนสถานะการใช้งาน
        </button>
        {history.length > 0 && (
          <details className="disclosure">
            <summary>ประวัติการเปลี่ยนสถานะ ({history.length})</summary>
            <ul>
              {[...history].reverse().map((entry) => (
                <li key={entry.history_id}>
                  {equipmentStatusLabel[entry.status] ?? entry.status} —{' '}
                  {formatThaiDateTime(entry.changed_at)}
                  {entry.changed_by ? ` โดย ${entry.changed_by}` : ''}
                  {entry.reason ? ` (${entry.reason})` : ''}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      <ChangeEquipmentStatusDialog
        open={statusDialogOpen}
        currentStatus={equipment.operational_status}
        submitting={statusSubmitting}
        onCancel={() => setStatusDialogOpen(false)}
        onSubmit={(status, reason) => void submitStatusChange(status, reason)}
      />
    </section>
  )
}
