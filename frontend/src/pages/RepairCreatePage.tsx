import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { MeterSnapshotFields } from '../components/MeterSnapshotFields'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { describeErrorCode, repairSourceTypeLabel } from '../lib/labels'
import type {
  AssetType,
  MeterReadingInput,
  MeterSnapshot,
  RepairDetail,
  RepairSourceType,
  VehicleComponent,
  VehicleDetail,
} from '../lib/types'

const KNOWN_SOURCE_TYPES: RepairSourceType[] = [
  'MANUAL',
  'INSPECTION_RESULT',
  'FINDING',
  'PM_RESULT',
  'ALERT',
]

/** Repair reporting/creation (Phase 4, "แจ้งซ่อม"). When reached with
 * `source_type`/`source_id` query params (e.g. from a Finding on the
 * inspection detail page), the source is pre-filled and locked — this
 * page never invents which findings must convert to a repair (F02). */
export function RepairCreatePage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const queryType = searchParams.get('source_type')
  const sourceType: RepairSourceType =
    queryType && (KNOWN_SOURCE_TYPES as string[]).includes(queryType)
      ? (queryType as RepairSourceType)
      : 'MANUAL'
  const sourceId = searchParams.get('source_id')
  const sourceLocked = sourceType !== 'MANUAL' && !!sourceId

  const [category, setCategory] = useState('')
  const [symptom, setSymptom] = useState('')
  const [readings, setReadings] = useState<MeterReadingInput[]>([])
  const [vehicleComponents, setVehicleComponents] = useState<VehicleComponent[]>([])
  const [loadingComponents, setLoadingComponents] = useState(assetType === 'VEHICLE')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (assetType !== 'VEHICLE') return
    let cancelled = false
    void apiGet<VehicleDetail>(`/vehicles/${assetId}`).then((result) => {
      if (cancelled) return
      if (result.ok) setVehicleComponents(result.data.components)
      setLoadingComponents(false)
    })
    return () => {
      cancelled = true
    }
  }, [assetType, assetId])

  const submit = useCallback(async () => {
    setSubmitting(true)
    setError(null)

    let meterSnapshotId: string | null = null
    if (readings.length > 0) {
      const snapshotResult = await apiPost<MeterSnapshot>('/meter-snapshots', {
        asset_type: assetType,
        asset_id: assetId,
        readings,
      })
      if (!snapshotResult.ok) {
        setSubmitting(false)
        const err = snapshotResult.error
        setError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
        return
      }
      meterSnapshotId = snapshotResult.data.meter_snapshot_id
    }

    const result = await apiPost<RepairDetail>('/repairs', {
      asset_type: assetType,
      asset_id: assetId,
      source_type: sourceType,
      source_id: sourceId,
      category: category.trim() || null,
      symptom: symptom.trim() || null,
      meter_snapshot_id: meterSnapshotId,
    })
    setSubmitting(false)
    if (result.ok) {
      navigate(`/repairs/${result.data.repair.repair_id}`)
    } else {
      const err = result.error
      setError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [assetType, assetId, sourceType, sourceId, category, symptom, readings, navigate])

  return (
    <section className="page">
      <h1>แจ้งซ่อม</h1>
      <p>รหัสอ้างอิง: {assetId}</p>

      <Card>
        <div className="status-card__row">
          <span>แหล่งที่มา</span>
          <span>{repairSourceTypeLabel[sourceType] ?? sourceType}</span>
        </div>
        {sourceLocked && (
          <p className="form-field__hint">
            รายการนี้เชื่อมโยงมาจาก {repairSourceTypeLabel[sourceType]} รหัส {sourceId}
          </p>
        )}
      </Card>

      <Card>
        <div className="form-grid">
          <FormField label="หมวดหมู่ (ถ้ามี)" htmlFor="repair-category">
            <input
              id="repair-category"
              type="text"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="เช่น ระบบไฮดรอลิก, ระบบไฟฟ้า"
            />
          </FormField>
          <FormField label="อาการ/ปัญหาที่พบ" htmlFor="repair-symptom">
            <textarea
              id="repair-symptom"
              value={symptom}
              onChange={(event) => setSymptom(event.target.value)}
              placeholder="อธิบายอาการที่พบโดยละเอียด"
            />
          </FormField>
        </div>

        {assetType === 'VEHICLE' && (
          <div>
            <p className="form-field__hint">บันทึกค่ามาตรวัด (ถ้ามี)</p>
            {loadingComponents ? (
              <LoadingState message="กำลังโหลดข้อมูลส่วนประกอบ..." />
            ) : (
              <MeterSnapshotFields components={vehicleComponents} onChange={setReadings} />
            )}
          </div>
        )}

        {error && <ErrorState message={error} onRetry={() => setError(null)} />}

        <div className="sticky-actions">
          <button
            type="button"
            className="button button--primary button--full-width"
            disabled={submitting}
            onClick={() => void submit()}
          >
            {submitting ? 'กำลังบันทึก...' : 'ส่งแจ้งซ่อม'}
          </button>
        </div>
      </Card>
    </section>
  )
}
