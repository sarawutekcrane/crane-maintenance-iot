import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ChangeVehicleStatusDialog } from '../components/ChangeVehicleStatusDialog'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPatch } from '../lib/apiClient'
import {
  componentRoleLabel,
  describeErrorCode,
  formatThaiDateTime,
  operationalStatusLabel,
  operationalStatusTone,
} from '../lib/labels'
import type {
  ChangeVehicleStatusResult,
  OperationalStatus,
  Vehicle,
  VehicleDetail,
  VehicleStatusHistoryEntry,
} from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; detail: VehicleDetail; history: VehicleStatusHistoryEntry[] }

export function VehicleDetailPage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [statusDialogOpen, setStatusDialogOpen] = useState(false)
  const [statusSubmitting, setStatusSubmitting] = useState(false)
  const [editingMachineNo, setEditingMachineNo] = useState(false)
  const [machineNoInput, setMachineNoInput] = useState('')
  const [machineNoSubmitting, setMachineNoSubmitting] = useState(false)
  const [machineNoError, setMachineNoError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })

    const [detailResult, historyResult] = await Promise.all([
      apiGet<VehicleDetail>(`/vehicles/${vehicleId}`),
      apiGet<VehicleStatusHistoryEntry[]>(`/vehicles/${vehicleId}/status-history`),
    ])

    if (!detailResult.ok) {
      const err = detailResult.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }

    setState({
      kind: 'ready',
      detail: detailResult.data,
      history: historyResult.ok ? historyResult.data : [],
    })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  const submitStatusChange = useCallback(
    async (status: OperationalStatus, note: string) => {
      setStatusSubmitting(true)
      const result = await apiPatch<ChangeVehicleStatusResult>(`/vehicles/${vehicleId}/status`, {
        status,
        note: note || null,
      })
      setStatusSubmitting(false)
      if (result.ok) {
        setStatusDialogOpen(false)
        void load()
      }
    },
    [vehicleId, load],
  )

  const submitMachineNoChange = useCallback(async () => {
    if (machineNoInput.trim() === '') {
      setMachineNoError('กรุณากรอกเลขเครื่องจักร')
      return
    }
    setMachineNoSubmitting(true)
    setMachineNoError(null)
    const result = await apiPatch<Vehicle>(`/vehicles/${vehicleId}`, {
      machine_no: machineNoInput.trim(),
    })
    setMachineNoSubmitting(false)
    if (result.ok) {
      setEditingMachineNo(false)
      void load()
    } else {
      const err = result.error
      setMachineNoError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [vehicleId, machineNoInput, load])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลยานพาหนะ..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายละเอียดยานพาหนะ</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { vehicle, model, components } = state.detail

  return (
    <section className="page">
      <h1>{vehicle.machine_no}</h1>
      <p>รหัสยานพาหนะ: {vehicle.vehicle_id}</p>

      <Card>
        <div className="status-card__actions">
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/inspect`}
            className="button button--primary button--full-width"
          >
            ตรวจเช็ค
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/inspections`}
            className="button button--secondary button--full-width"
          >
            ประวัติการตรวจเช็ค
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/pm`}
            className="button button--primary button--full-width"
          >
            PM
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/repairs/new`}
            className="button button--primary button--full-width"
          >
            แจ้งซ่อม
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/repairs`}
            className="button button--secondary button--full-width"
          >
            ประวัติการซ่อม
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/parts`}
            className="button button--secondary button--full-width"
          >
            อะไหล่/อายุการใช้งาน
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/drivers`}
            className="button button--secondary button--full-width"
          >
            คนขับ/ผู้ควบคุม
          </Link>
          <Link
            to={`/vehicle/${vehicle.vehicle_id}/certificates`}
            className="button button--secondary button--full-width"
          >
            ใบรับรองยานพาหนะ
          </Link>
          {model && (
            <Link
              to={`/models/${model.model_id}/documents`}
              className="button button--secondary button--full-width"
            >
              เอกสารประจำรุ่นเครื่องจักร
            </Link>
          )}
        </div>
      </Card>

      <Card>
        <div className="status-card__row">
          <span>เลขเครื่องจักร (Machine No.)</span>
          {!editingMachineNo && (
            <span>
              {vehicle.machine_no}{' '}
              <button
                type="button"
                className="button button--secondary"
                onClick={() => {
                  setMachineNoInput(vehicle.machine_no)
                  setMachineNoError(null)
                  setEditingMachineNo(true)
                }}
              >
                แก้ไข
              </button>
            </span>
          )}
        </div>

        {editingMachineNo && (
          <div className="form-grid">
            <FormField
              label="เลขเครื่องจักรใหม่"
              htmlFor="edit-machine-no"
              error={machineNoError ?? undefined}
              hint="การเปลี่ยนเลขเครื่องจักรไม่มีผลต่อรหัสยานพาหนะ (vehicle_id)"
            >
              <input
                id="edit-machine-no"
                type="text"
                value={machineNoInput}
                onChange={(event) => setMachineNoInput(event.target.value)}
              />
            </FormField>
            <div>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setEditingMachineNo(false)}
                disabled={machineNoSubmitting}
              >
                ยกเลิก
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void submitMachineNoChange()}
                disabled={machineNoSubmitting}
              >
                {machineNoSubmitting ? 'กำลังบันทึก...' : 'บันทึก'}
              </button>
            </div>
          </div>
        )}

        <div className="status-card__row">
          <span>รุ่น/ยี่ห้อ</span>
          <span>{model ? `${model.model_name}${model.brand ? ` (${model.brand})` : ''}` : 'ไม่พบข้อมูลรุ่น'}</span>
        </div>

        <div className="status-card__row">
          <span>หมายเลขซีเรียล</span>
          <span>{vehicle.serial_number ?? 'ไม่มีข้อมูล'}</span>
        </div>

        <div className="status-card__row">
          <span>สถานะการใช้งาน</span>
          <StatusBadge
            label={operationalStatusLabel[vehicle.operational_status] ?? vehicle.operational_status}
            tone={operationalStatusTone[vehicle.operational_status]}
          />
        </div>

        <div className="status-card__actions">
          <button
            type="button"
            className="button button--primary button--full-width"
            onClick={() => setStatusDialogOpen(true)}
          >
            เปลี่ยนสถานะ
          </button>
        </div>
      </Card>

      <Card>
        <h2>ส่วนประกอบ (Component)</h2>
        <ResponsiveTable
          columns={[
            {
              key: 'role',
              header: 'ส่วนประกอบ',
              render: (c) => componentRoleLabel[c.component_role] ?? c.component_role,
            },
            { key: 'id', header: 'รหัส', render: (c) => c.component_id },
          ]}
          rows={components}
          getRowKey={(c) => c.component_id}
          emptyTitle="ไม่มีข้อมูลส่วนประกอบ"
          emptyDescription="ยังไม่มีการกำหนดส่วนประกอบสำหรับยานพาหนะนี้"
        />
      </Card>

      <Card>
        <h2>ประวัติการเปลี่ยนสถานะ</h2>
        <ResponsiveTable
          columns={[
            {
              key: 'changed_at',
              header: 'วันที่เปลี่ยน',
              render: (entry) => formatThaiDateTime(entry.changed_at),
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: (entry) => (
                <StatusBadge
                  label={operationalStatusLabel[entry.status] ?? entry.status}
                  tone={operationalStatusTone[entry.status]}
                />
              ),
            },
            {
              key: 'changed_by',
              header: 'ผู้เปลี่ยน',
              render: (entry) => entry.changed_by ?? 'ระบบ',
            },
            { key: 'note', header: 'หมายเหตุ', render: (entry) => entry.note ?? '-' },
          ]}
          rows={state.history}
          getRowKey={(entry) => entry.history_id}
          emptyTitle="ไม่มีประวัติ"
          emptyDescription="ยังไม่มีการเปลี่ยนสถานะสำหรับยานพาหนะนี้"
        />
      </Card>

      <ChangeVehicleStatusDialog
        open={statusDialogOpen}
        currentStatus={vehicle.operational_status}
        submitting={statusSubmitting}
        onCancel={() => setStatusDialogOpen(false)}
        onSubmit={(status, note) => void submitStatusChange(status, note)}
      />
    </section>
  )
}
