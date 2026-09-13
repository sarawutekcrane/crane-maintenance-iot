import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime, priorUsageQualityLabel } from '../lib/labels'
import type { AssetType, PositionLifetimeRecord, PriorUsageQuality } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; records: PositionLifetimeRecord[] }

const QUALITY_OPTIONS: PriorUsageQuality[] = ['KNOWN', 'PARTIAL', 'UNKNOWN']

/**
 * Asset-scoped "อะไหล่/อายุการใช้งาน" page (Phase 5). Shows/creates
 * POSITION_LIFETIME enrollments for this asset. INSTANCE_TRACKED
 * components installed on this asset are tracked and viewed from their
 * own Part Instance detail page (reached via the Part Master catalog),
 * since their identity/history follows the physical component, not the
 * asset.
 */
export function AssetPartsPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''

  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [formOpen, setFormOpen] = useState(false)
  const [positionCode, setPositionCode] = useState('')
  const [partId, setPartId] = useState('')
  const [quality, setQuality] = useState<PriorUsageQuality>('UNKNOWN')
  const [value, setValue] = useState('')
  const [usageNote, setUsageNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<PositionLifetimeRecord[]>(
      `/position-lifetime?asset_type=${assetType}&asset_id=${assetId}`,
    )
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', records: result.data })
  }, [assetType, assetId])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    if (!positionCode.trim()) {
      setFormError('กรุณาระบุตำแหน่ง (position code)')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<PositionLifetimeRecord>('/position-lifetime', {
      asset_type: assetType,
      asset_id: assetId,
      position_code: positionCode.trim(),
      part_id: partId.trim() || null,
      prior_usage: {
        quality,
        value: quality === 'UNKNOWN' || value === '' ? null : Number(value),
        note: usageNote.trim() || null,
      },
    })
    setSubmitting(false)
    if (result.ok) {
      setFormOpen(false)
      setPositionCode('')
      setPartId('')
      setQuality('UNKNOWN')
      setValue('')
      setUsageNote('')
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  return (
    <section className="page">
      <h1>อะไหล่/อายุการใช้งาน</h1>
      <p>รหัสอ้างอิง: {assetId}</p>
      <p className="form-field__hint">
        รหัสตำแหน่ง (position code) ด้านล่างเป็นข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบเท่านั้น
        ยังไม่มีรหัสตำแหน่งมาตรฐานที่ได้รับการอนุมัติจากบริษัท
      </p>

      <Card>
        <Link to="/parts" className="button button--secondary button--full-width">
          ดูรายการอะไหล่ทั้งหมด (Part Master)
        </Link>
        <button
          type="button"
          className="button button--primary button--full-width"
          onClick={() => setFormOpen((open) => !open)}
        >
          + ลงทะเบียนอายุการใช้งานตามตำแหน่ง
        </button>
      </Card>

      {formOpen && (
        <Card>
          <h2>ลงทะเบียนอายุการใช้งานตามตำแหน่ง</h2>
          <div className="form-grid">
            <FormField label="ตำแหน่ง (position code)" htmlFor="position-code">
              <input
                id="position-code"
                type="text"
                value={positionCode}
                onChange={(event) => setPositionCode(event.target.value)}
                placeholder="เช่น BOOM-CYL-1 (ตัวอย่าง)"
              />
            </FormField>
            <FormField label="รหัสอะไหล่ (ถ้ามี)" htmlFor="position-part-id">
              <input
                id="position-part-id"
                type="text"
                value={partId}
                onChange={(event) => setPartId(event.target.value)}
                placeholder="เช่น PART-0004"
              />
            </FormField>
            <FormField label="ประวัติการใช้งานก่อนเริ่มติดตาม" htmlFor="position-quality">
              <select
                id="position-quality"
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
              <FormField label="ค่าที่ทราบ" htmlFor="position-value">
                <input
                  id="position-value"
                  type="number"
                  inputMode="decimal"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                />
              </FormField>
            )}
            {quality !== 'KNOWN' && (
              <FormField label="หมายเหตุประวัติการใช้งาน" htmlFor="position-note">
                <textarea
                  id="position-note"
                  value={usageNote}
                  onChange={(event) => setUsageNote(event.target.value)}
                />
              </FormField>
            )}
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submitting}
              onClick={() => void submit()}
            >
              {submitting ? 'กำลังบันทึก...' : 'บันทึก'}
            </button>
          </div>
        </Card>
      )}

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูลอายุการใช้งานตามตำแหน่ง..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.records.length === 0 && (
        <Card>
          <p>ยังไม่มีข้อมูลอายุการใช้งานตามตำแหน่งสำหรับสินทรัพย์นี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.records.map((record) => (
          <Card key={record.position_lifetime_id}>
            <h2>ตำแหน่ง: {record.position_code}</h2>
            {record.part_id && <p className="form-field__hint">รหัสอะไหล่: {record.part_id}</p>}
            <div className="status-card__row">
              <span>ประวัติการใช้งานก่อนเริ่มติดตาม</span>
              <span>{priorUsageQualityLabel[record.prior_usage.quality]}</span>
            </div>
            <div className="status-card__row">
              <span>ค่าที่ทราบ</span>
              <span>
                {record.prior_usage.quality === 'UNKNOWN' || record.prior_usage.value === null
                  ? 'ไม่ทราบค่า'
                  : record.prior_usage.value}
              </span>
            </div>
            <div className="status-card__row">
              <span>สถานะกำหนดถึงรอบ (Due)</span>
              <span>ไม่สามารถคำนวณได้ในขณะนี้</span>
            </div>
            <p className="form-field__hint">
              การคำนวณอายุการใช้งานคงเหลือต้องรอกฎอายุการใช้งานและช่วงเตือนที่ได้รับอนุมัติ (G01/G02)
            </p>
            <p className="form-field__hint">เริ่มติดตามเมื่อ {formatThaiDateTime(record.started_at)}</p>
          </Card>
        ))}
    </section>
  )
}
