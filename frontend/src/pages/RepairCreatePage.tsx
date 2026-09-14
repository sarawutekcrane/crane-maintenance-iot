import { useCallback, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { MachineStateReadOnly } from '../components/MachineStateReadOnly'
import { ApiError, apiPost } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_REPAIR } from '../lib/capabilityNames'
import { describeErrorCode, repairSourceTypeLabel } from '../lib/labels'
import type {
  AssetType,
  RepairDetail,
  RepairSourceType,
  SubmitRepairRequestResponse,
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

  const { loading: capabilitiesLoading, hasCapability } = useCapabilities()
  // Core Demo Fixes Delta REV05 section 2A: only an authorized
  // Maintenance actor may open a Repair Work Order directly. Everyone
  // else reports the problem instead (แจ้งปัญหา/แจ้งซ่อม) via
  // `POST /repair-requests`, which a Maintenance actor later reviews and
  // converts. Repair Request only covers VEHICLE (the live sheet's own
  // `repair_request` schema has no equipment column) — equipment
  // reporting stays on the direct path, Maintenance-only in practice.
  const canManageRepair = hasCapability(CAN_MANAGE_REPAIR)
  const useRepairRequestFlow = assetType === 'VEHICLE' && !canManageRepair

  const [category, setCategory] = useState('')
  const [symptom, setSymptom] = useState('')
  const [primaryTechnician, setPrimaryTechnician] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submittedRequestId, setSubmittedRequestId] = useState<string | null>(null)

  const submit = useCallback(async () => {
    setSubmitting(true)
    setError(null)

    if (useRepairRequestFlow) {
      const result = await apiPost<SubmitRepairRequestResponse>('/repair-requests', {
        vehicle_id: assetId,
        symptom_th: symptom.trim(),
      })
      setSubmitting(false)
      if (result.ok) {
        setSubmittedRequestId(result.data.request.repair_request_id)
      } else {
        const err = result.error
        setError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
      }
      return
    }

    // Normal path: no manual counter/GPS entry here — the backend
    // automatically captures current machine state on creation (Core
    // Demo Fixes prompt, APPROVED CORE RULE).
    const result = await apiPost<RepairDetail>('/repairs', {
      asset_type: assetType,
      asset_id: assetId,
      source_type: sourceType,
      source_id: sourceId,
      category: category.trim() || null,
      symptom: symptom.trim() || null,
      primary_technician: primaryTechnician.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      navigate(`/repairs/${result.data.repair.repair_id}`)
    } else {
      const err = result.error
      setError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [
    useRepairRequestFlow,
    assetType,
    assetId,
    sourceType,
    sourceId,
    category,
    symptom,
    primaryTechnician,
    navigate,
  ])

  if (submittedRequestId) {
    return (
      <section className="page">
        <h1>แจ้งปัญหา/แจ้งซ่อมแล้ว</h1>
        <Card>
          <p>
            บันทึกการแจ้งปัญหาแล้ว (รหัส {submittedRequestId}) — ทีมซ่อมบำรุงจะตรวจสอบและเปิดใบงานซ่อมต่อไป
          </p>
        </Card>
      </section>
    )
  }

  return (
    <section className="page">
      <h1>{capabilitiesLoading ? 'แจ้งซ่อม' : useRepairRequestFlow ? 'แจ้งปัญหา/แจ้งซ่อม' : 'แจ้งซ่อม'}</h1>
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
          {!useRepairRequestFlow && (
            <FormField label="หมวดหมู่ (ถ้ามี)" htmlFor="repair-category">
              <input
                id="repair-category"
                type="text"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                placeholder="เช่น ระบบไฮดรอลิก, ระบบไฟฟ้า"
              />
            </FormField>
          )}
          <FormField label="อาการ/ปัญหาที่พบ" htmlFor="repair-symptom">
            <textarea
              id="repair-symptom"
              value={symptom}
              onChange={(event) => setSymptom(event.target.value)}
              placeholder="อธิบายอาการที่พบโดยละเอียด"
            />
          </FormField>
          {!useRepairRequestFlow && (
            <FormField label="ช่างผู้รับผิดชอบหลัก (ถ้าทราบ)" htmlFor="repair-primary-technician">
              <input
                id="repair-primary-technician"
                type="text"
                value={primaryTechnician}
                onChange={(event) => setPrimaryTechnician(event.target.value)}
                placeholder="สามารถมอบหมาย/แก้ไขภายหลังได้ที่หน้าใบแจ้งซ่อม"
              />
            </FormField>
          )}
        </div>

        <MachineStateReadOnly assetType={assetType} assetId={assetId} />

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
