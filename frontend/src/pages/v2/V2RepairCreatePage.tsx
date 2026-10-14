import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { FormField } from '../../components/FormField'
import { MachineStateReadOnly } from '../../components/MachineStateReadOnly'
import { V2ContextBanner } from '../../components/V2ContextBanner'
import { apiPost } from '../../lib/apiClient'
import { CAN_MANAGE_REPAIR } from '../../lib/capabilityNames'
import { readFailure, v2DetailRoute, type ReadFailure } from '../../lib/technicianV2'
import type { AssetType, RepairDetail } from '../../lib/types'
import { V2CreateGate } from './V2CreateGate'

/**
 * R2 Batch R2f-h4 B4 — V2 Repair creation (parallel route, Option 1). Uses the
 * existing `POST /repairs` and never sends a technician field: with the V2
 * cutover ON the server marks the job TECHNICIAN_V2 and the team is assigned on
 * the V2 detail page. Manual source only (the legacy page keeps the
 * Finding / PM-defect and Repair-Request flows until B5).
 */
export function V2RepairCreatePage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''
  const navigate = useNavigate()
  const [category, setCategory] = useState('')
  const [symptom, setSymptom] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<ReadFailure | null>(null)
  const inFlight = useRef(false)

  const submit = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setSubmitting(true)
    setFailure(null)
    const result = await apiPost<RepairDetail>('/repairs', {
      asset_type: assetType,
      asset_id: assetId,
      source_type: 'MANUAL',
      source_id: null,
      category: category.trim() || null,
      symptom: symptom.trim() || null,
    })
    inFlight.current = false
    setSubmitting(false)
    if (result.ok) navigate(v2DetailRoute('REPAIR', result.data.repair.repair_id))
    else setFailure(readFailure(result.error))
  }

  return (
    <section className="page">
      <h1>แจ้งซ่อม (V2)</h1>
      <p>รหัสอ้างอิง: {assetId}</p>
      <V2ContextBanner />
      <V2CreateGate capability={CAN_MANAGE_REPAIR}>
        <Card>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            <div className="form-grid">
              <FormField label="หมวดหมู่ (ถ้ามี)" htmlFor="v2-repair-category">
                <input
                  id="v2-repair-category"
                  type="text"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  placeholder="เช่น ระบบไฮดรอลิก, ระบบไฟฟ้า"
                />
              </FormField>
              <FormField label="อาการ/ปัญหาที่พบ" htmlFor="v2-repair-symptom">
                <textarea
                  id="v2-repair-symptom"
                  value={symptom}
                  onChange={(event) => setSymptom(event.target.value)}
                  placeholder="อธิบายอาการที่พบโดยละเอียด"
                />
              </FormField>
            </div>
            <p className="form-field__hint">มอบหมายทีมช่างได้ที่หน้ารายละเอียดงานหลังเปิดใบงานแล้ว</p>
            <MachineStateReadOnly assetType={assetType} assetId={assetId} />
            {failure && (
              <ErrorState title="เปิดใบงานซ่อมไม่สำเร็จ" message={failure.message} code={failure.code} requestId={failure.requestId} />
            )}
            <button type="submit" className="button button--primary button--full-width" disabled={submitting}>
              {submitting ? 'กำลังบันทึก...' : 'เปิดใบงานซ่อม'}
            </button>
          </form>
        </Card>
      </V2CreateGate>
    </section>
  )
}
