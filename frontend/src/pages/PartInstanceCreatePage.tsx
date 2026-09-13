import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { FormField } from '../components/FormField'
import { ApiError, apiPost } from '../lib/apiClient'
import { describeErrorCode, priorUsageQualityLabel } from '../lib/labels'
import type { PartInstanceDetail, PriorUsageQuality } from '../lib/types'

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
  const [quality, setQuality] = useState<PriorUsageQuality>('UNKNOWN')
  const [value, setValue] = useState('')
  const [usageNote, setUsageNote] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    const result = await apiPost<PartInstanceDetail>('/part-instances', {
      part_id: partId,
      serial_number: serialNumber.trim() || null,
      prior_usage: {
        quality,
        value: quality === 'UNKNOWN' || value === '' ? null : Number(value),
        note: usageNote.trim() || null,
      },
      note: note.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      navigate(`/part-instances/${result.data.instance.part_instance_id}`)
    } else {
      const err = result.error
      setError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
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
