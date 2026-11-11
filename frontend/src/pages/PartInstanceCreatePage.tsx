import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { FormField } from '../components/FormField'
import { ApiError, apiPostWithRequestId } from '../lib/apiClient'
import { describeErrorCode, priorUsageQualityLabel } from '../lib/labels'
import { isUncertain, newRequestId } from '../lib/partLifetime'
import type { HistoricalEvidenceType, PartInstanceDetail, PartInstanceStatus, PriorUsageQuality } from '../lib/types'

const QUALITY_OPTIONS: PriorUsageQuality[] = ['KNOWN', 'PARTIAL', 'UNKNOWN']

/**
 * On-demand PartInstance enrollment (guardrails §12: create only when
 * required — never a full-machine BOM pre-registration form). Reached
 * from a Part Master's detail page for an INSTANCE_TRACKED part.
 */
export function PartInstanceCreatePage() {
  const { partId = '' } = useParams<{ partId: string }>()
  const navigate = useNavigate()

  const [serialNumber, setSerialNumber] = useState('')
  const [tagLabel, setTagLabel] = useState('')
  const [storageLocation, setStorageLocation] = useState('')
  const [initialStatus, setInitialStatus] = useState<PartInstanceStatus>('READY_FOR_INSTALL')
  const [basis, setBasis] = useState('ENGINE_HOUR:CARRIER_ENGINE')
  const [asOf, setAsOf] = useState('')
  const [evidenceType, setEvidenceType] = useState<HistoricalEvidenceType>('DOCUMENT')
  const [evidenceReference, setEvidenceReference] = useState('')
  const [intentId, setIntentId] = useState(newRequestId)
  const [quality, setQuality] = useState<PriorUsageQuality>('UNKNOWN')
  const [value, setValue] = useState('')
  const [usageNote, setUsageNote] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    const [counterType, role] = basis.split(':')
    const known = quality !== 'UNKNOWN'
    const result = await apiPostWithRequestId<PartInstanceDetail>('/part-instances', {
      part_id: partId,
      serial_number: serialNumber.trim() || null,
      tag_label: tagLabel.trim() || null,
      storage_location: storageLocation.trim() || null,
      initial_status: initialStatus,
      prior_usage: {
        quality,
        value: !known || value === '' ? null : Number(value),
        note: usageNote.trim() || null,
        ...(known
          ? {
              basis: evidenceType === 'NEW_PART' ? null : counterType,
              component_role: evidenceType === 'NEW_PART' || !role ? null : role,
              as_of: asOf || null,
              evidence_type: evidenceType,
              evidence_reference: evidenceReference.trim() || null,
            }
          : {}),
      },
      note: note.trim() || null,
    }, intentId)
    setSubmitting(false)
    if (result.ok) {
      navigate(`/part-instances/${result.data.instance.part_instance_id}`)
    } else {
      const err = result.error
      if (err instanceof ApiError && !isUncertain(err.status)) {
        setIntentId(newRequestId())
        setError(describeErrorCode(err.code))
      } else {
        setError('ไม่ทราบผลการบันทึก — กดลงทะเบียนอีกครั้งเพื่อส่งคำขอเดิมซ้ำอย่างปลอดภัย')
      }
    }
  }

  return (
    <section className="page">
      <h1>ลงทะเบียนชิ้นงานใหม่</h1>
      <p>รหัสอะไหล่: {partId}</p>

      <Card>
        <div className="form-grid">
          <FormField
            label="หมายเลขซีเรียล (ถ้ามี)"
            htmlFor="instance-serial"
            hint="ปล่อยว่างได้หากยังไม่ทราบหมายเลขซีเรียลจริง"
          >
            <input
              id="instance-serial"
              type="text"
              value={serialNumber}
              onChange={(event) => setSerialNumber(event.target.value)}
            />
          </FormField>

          <FormField
            label="ป้ายระบุชิ้น (ถ้ามี)"
            htmlFor="instance-tag"
            hint="ไม่บังคับ — ใช้แยกชิ้นที่หน้าตาเหมือนกันในคลัง (ไม่บังคับ QR)"
          >
            <input id="instance-tag" type="text" value={tagLabel} onChange={(e) => setTagLabel(e.target.value)} />
          </FormField>

          <FormField label="สถานะเริ่มต้น" htmlFor="instance-initial-status">
            <select id="instance-initial-status" value={initialStatus}
              onChange={(e) => setInitialStatus(e.target.value as PartInstanceStatus)}>
              <option value="READY_FOR_INSTALL">พร้อมติดตั้ง</option>
              <option value="STOCK">อยู่ในคลัง</option>
            </select>
          </FormField>

          <FormField label="ตำแหน่งจัดเก็บ (ถ้ามี)" htmlFor="instance-location"
            hint="ตำแหน่งปัจจุบันเท่านั้น — ไม่ใช่รหัสประจำชิ้น">
            <input id="instance-location" type="text" value={storageLocation}
              onChange={(e) => setStorageLocation(e.target.value)} />
          </FormField>

          <FormField label="ประวัติการใช้งานก่อนเริ่มติดตาม" htmlFor="instance-prior-quality">
            <select
              id="instance-prior-quality"
              value={quality}
              onChange={(event) => setQuality(event.target.value as PriorUsageQuality)}
            >
              {QUALITY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {priorUsageQualityLabel[option]}
                </option>
              ))}
            </select>
          </FormField>

          {quality !== 'UNKNOWN' && (
            <FormField
              label="ค่าที่ทราบ (เช่น ชั่วโมงใช้งานเดิม)"
              htmlFor="instance-prior-value"
              hint={
                quality === 'PARTIAL'
                  ? 'ทราบค่าเพียงบางส่วน — โปรดระบุรายละเอียดที่ยังไม่ทราบในหมายเหตุด้านล่าง'
                  : undefined
              }
            >
              <input
                id="instance-prior-value"
                type="number"
                inputMode="decimal"
                value={value}
                onChange={(event) => setValue(event.target.value)}
              />
            </FormField>
          )}

          {quality !== 'UNKNOWN' && (
            <>
              <FormField label="ประเภทหลักฐาน" htmlFor="instance-evidence-type">
                <select id="instance-evidence-type" value={evidenceType}
                  onChange={(e) => setEvidenceType(e.target.value as HistoricalEvidenceType)}>
                  <option value="NEW_PART">ชิ้นใหม่ทั้งชิ้น (ค่า 0)</option>
                  <option value="DOCUMENT">เอกสาร</option>
                  <option value="WORK_ORDER">ใบงาน</option>
                  <option value="METER_RECORD">บันทึกมาตรวัด</option>
                </select>
              </FormField>
              {evidenceType !== 'NEW_PART' && (
                <FormField label="ฐานการนับ" htmlFor="instance-basis">
                  <select id="instance-basis" value={basis} onChange={(e) => setBasis(e.target.value)}>
                    <option value="ENGINE_HOUR:CARRIER_ENGINE">ชั่วโมงเครื่องยนต์ล่าง</option>
                    <option value="ENGINE_HOUR:CRANE_ENGINE">ชั่วโมงเครื่องยนต์บน</option>
                    <option value="ODOMETER:">เลขไมล์</option>
                  </select>
                </FormField>
              )}
              <FormField label="ค่า ณ วันที่" htmlFor="instance-as-of">
                <input id="instance-as-of" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
              </FormField>
              <FormField label="เลขอ้างอิงหลักฐาน" htmlFor="instance-evidence-reference"
                hint="เลขใบงาน/เอกสารแนบที่ระบบตรวจได้จะยกระดับความน่าเชื่อถือ ข้อความอิสระยังไม่ถือว่ายืนยัน">
                <input id="instance-evidence-reference" type="text" value={evidenceReference}
                  onChange={(e) => setEvidenceReference(e.target.value)} />
              </FormField>
            </>
          )}

          {quality !== 'KNOWN' && (
            <FormField
              label="หมายเหตุประวัติการใช้งาน"
              htmlFor="instance-prior-note"
              hint="อธิบายว่าทราบข้อมูลช่วงใด หรือเหตุผลที่ไม่ทราบค่า"
            >
              <textarea
                id="instance-prior-note"
                value={usageNote}
                onChange={(event) => setUsageNote(event.target.value)}
              />
            </FormField>
          )}

          <FormField label="หมายเหตุ (ถ้ามี)" htmlFor="instance-note">
            <textarea id="instance-note" value={note} onChange={(event) => setNote(event.target.value)} />
          </FormField>

          {error && (
            <p className="form-field__error" role="alert">
              {error}
            </p>
          )}

          <button
            type="button"
            className="button button--primary button--full-width"
            disabled={submitting}
            onClick={() => void submit()}
          >
            {submitting ? 'กำลังบันทึก...' : 'ลงทะเบียนชิ้นงาน'}
          </button>
        </div>
      </Card>
    </section>
  )
}
