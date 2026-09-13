import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  installationSegmentStatusLabel,
  lifecycleStartReasonLabel,
  partInstanceStatusLabel,
  partInstanceStatusTone,
  priorUsageQualityLabel,
} from '../lib/labels'
import type { AssetType, PartInstanceDetail, PartInstanceStatus } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; detail: PartInstanceDetail }

type ActionPanel = 'none' | 'install' | 'remove' | 'transfer' | 'overhaul'

const REMOVAL_NEXT_STATUSES: PartInstanceStatus[] = ['REMOVED', 'IN_REPAIR', 'STOCK', 'SCRAPPED']

export function PartInstanceDetailPage() {
  const { instanceId = '' } = useParams<{ instanceId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [panel, setPanel] = useState<ActionPanel>('none')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // install
  const [assetType, setAssetType] = useState<AssetType>('VEHICLE')
  const [assetId, setAssetId] = useState('')
  const [positionCode, setPositionCode] = useState('')

  // remove
  const [nextStatus, setNextStatus] = useState<PartInstanceStatus>('IN_REPAIR')
  const [removalReason, setRemovalReason] = useState('')

  // transfer
  const [targetAssetType, setTargetAssetType] = useState<AssetType>('VEHICLE')
  const [targetAssetId, setTargetAssetId] = useState('')
  const [transferPositionCode, setTransferPositionCode] = useState('')

  // overhaul
  const [approvedReason, setApprovedReason] = useState('')

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<PartInstanceDetail>(`/part-instances/${instanceId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', detail: result.data })
  }, [instanceId])

  useEffect(() => {
    void load()
  }, [load])

  const closePanel = () => {
    setPanel('none')
    setFormError(null)
  }

  const submitInstall = async () => {
    if (!assetId.trim()) {
      setFormError('กรุณาระบุรหัสยานพาหนะ/อุปกรณ์')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<PartInstanceDetail>(`/part-instances/${instanceId}/install`, {
      asset_type: assetType,
      asset_id: assetId.trim(),
      position_code: positionCode.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      closePanel()
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  const submitRemove = async () => {
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<PartInstanceDetail>(`/part-instances/${instanceId}/remove`, {
      next_status: nextStatus,
      removal_reason: removalReason.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      closePanel()
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  const submitTransfer = async () => {
    if (!targetAssetId.trim()) {
      setFormError('กรุณาระบุรหัสยานพาหนะ/อุปกรณ์ปลายทาง')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<PartInstanceDetail>(`/part-instances/${instanceId}/transfer`, {
      target_asset_type: targetAssetType,
      target_asset_id: targetAssetId.trim(),
      position_code: transferPositionCode.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      closePanel()
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  const submitOverhaul = async () => {
    if (!approvedReason.trim()) {
      setFormError('กรุณาระบุเหตุผล/การอนุมัติสำหรับการเริ่มรอบการใช้งานใหม่ (Overhaul)')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<PartInstanceDetail>(
      `/part-instances/${instanceId}/start-new-lifecycle`,
      { approved_reason: approvedReason.trim() },
    )
    setSubmitting(false)
    if (result.ok) {
      closePanel()
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลชิ้นงาน..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายละเอียดชิ้นงาน</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { instance, lifecycles, segments } = state.detail
  const isInstalled = instance.status === 'INSTALLED'
  const activeSegment = segments.find((s) => s.status === 'ACTIVE')

  return (
    <section className="page">
      <h1>ชิ้นงาน {instance.part_instance_id}</h1>
      <p>รหัสอะไหล่: <Link to={`/parts/${instance.part_id}`}>{instance.part_id}</Link></p>

      <Card>
        <div className="status-card__row">
          <span>สถานะ</span>
          <StatusBadge
            label={partInstanceStatusLabel[instance.status] ?? instance.status}
            tone={partInstanceStatusTone[instance.status]}
          />
        </div>
        <div className="status-card__row">
          <span>หมายเลขซีเรียล</span>
          <span>{instance.serial_number ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>ประวัติการใช้งานก่อนเริ่มติดตาม</span>
          <span>{priorUsageQualityLabel[instance.prior_usage.quality]}</span>
        </div>
        <div className="status-card__row">
          <span>ค่าที่ทราบ</span>
          <span>
            {instance.prior_usage.quality === 'UNKNOWN' || instance.prior_usage.value === null
              ? 'ไม่ทราบค่า'
              : instance.prior_usage.value}
          </span>
        </div>
        {instance.prior_usage.note && <p>หมายเหตุประวัติการใช้งาน: {instance.prior_usage.note}</p>}
        {activeSegment && (
          <p>
            ติดตั้งอยู่บน: {assetTypeLabel[activeSegment.asset_type] ?? activeSegment.asset_type} —{' '}
            {activeSegment.asset_id}
            {activeSegment.position_code ? ` (ตำแหน่ง ${activeSegment.position_code})` : ''}
          </p>
        )}

        <div className="status-card__actions">
          {!isInstalled && instance.status !== 'SCRAPPED' && (
            <button
              type="button"
              className="button button--primary button--full-width"
              onClick={() => setPanel(panel === 'install' ? 'none' : 'install')}
            >
              ติดตั้ง
            </button>
          )}
          {isInstalled && (
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={() => setPanel(panel === 'remove' ? 'none' : 'remove')}
            >
              ถอดออก
            </button>
          )}
          {isInstalled && (
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={() => setPanel(panel === 'transfer' ? 'none' : 'transfer')}
            >
              โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น
            </button>
          )}
          {!isInstalled && (
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={() => setPanel(panel === 'overhaul' ? 'none' : 'overhaul')}
            >
              เริ่มรอบการใช้งานใหม่ (Overhaul)
            </button>
          )}
        </div>
      </Card>

      {panel === 'install' && (
        <Card>
          <h2>ติดตั้งชิ้นงาน</h2>
          <div className="form-grid">
            <FormField label="ประเภทสินทรัพย์" htmlFor="install-asset-type">
              <select
                id="install-asset-type"
                value={assetType}
                onChange={(event) => setAssetType(event.target.value as AssetType)}
              >
                <option value="VEHICLE">ยานพาหนะ</option>
                <option value="EQUIPMENT">เครื่องมือ/อุปกรณ์</option>
              </select>
            </FormField>
            <FormField label="รหัสยานพาหนะ/อุปกรณ์" htmlFor="install-asset-id">
              <input id="install-asset-id" type="text" value={assetId} onChange={(e) => setAssetId(e.target.value)} />
            </FormField>
            <FormField label="ตำแหน่งติดตั้ง (ถ้ามี)" htmlFor="install-position">
              <input
                id="install-position"
                type="text"
                value={positionCode}
                onChange={(e) => setPositionCode(e.target.value)}
              />
            </FormField>
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submitting}
              onClick={() => void submitInstall()}
            >
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันการติดตั้ง'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'remove' && (
        <Card>
          <h2>ถอดชิ้นงานออก</h2>
          <div className="form-grid">
            <FormField label="สถานะหลังถอดออก" htmlFor="remove-next-status">
              <select
                id="remove-next-status"
                value={nextStatus}
                onChange={(event) => setNextStatus(event.target.value as PartInstanceStatus)}
              >
                {REMOVAL_NEXT_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {partInstanceStatusLabel[status]}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField label="เหตุผล (ถ้ามี)" htmlFor="remove-reason">
              <textarea
                id="remove-reason"
                value={removalReason}
                onChange={(event) => setRemovalReason(event.target.value)}
              />
            </FormField>
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submitting}
              onClick={() => void submitRemove()}
            >
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันการถอดออก'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'transfer' && (
        <Card>
          <h2>โยกย้ายชิ้นงาน</h2>
          <div className="form-grid">
            <FormField label="ประเภทสินทรัพย์ปลายทาง" htmlFor="transfer-asset-type">
              <select
                id="transfer-asset-type"
                value={targetAssetType}
                onChange={(event) => setTargetAssetType(event.target.value as AssetType)}
              >
                <option value="VEHICLE">ยานพาหนะ</option>
                <option value="EQUIPMENT">เครื่องมือ/อุปกรณ์</option>
              </select>
            </FormField>
            <FormField label="รหัสยานพาหนะ/อุปกรณ์ปลายทาง" htmlFor="transfer-asset-id">
              <input
                id="transfer-asset-id"
                type="text"
                value={targetAssetId}
                onChange={(event) => setTargetAssetId(event.target.value)}
              />
            </FormField>
            <FormField label="ตำแหน่งติดตั้งใหม่ (ถ้ามี)" htmlFor="transfer-position">
              <input
                id="transfer-position"
                type="text"
                value={transferPositionCode}
                onChange={(event) => setTransferPositionCode(event.target.value)}
              />
            </FormField>
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submitting}
              onClick={() => void submitTransfer()}
            >
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันการโยกย้าย'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'overhaul' && (
        <Card>
          <h2>เริ่มรอบการใช้งานใหม่ (Overhaul)</h2>
          <p className="form-field__hint">
            ต้องระบุเหตุผล/การอนุมัติที่ชัดเจน ระบบจะไม่ตัดสินเองว่าการซ่อมครั้งใดถือเป็น Overhaul —
            ประวัติรอบการใช้งานเดิมจะยังคงเก็บไว้และดูได้ตามปกติ
          </p>
          <div className="form-grid">
            <FormField label="เหตุผล/การอนุมัติ" htmlFor="overhaul-reason">
              <textarea
                id="overhaul-reason"
                value={approvedReason}
                onChange={(event) => setApprovedReason(event.target.value)}
              />
            </FormField>
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submitting}
              onClick={() => void submitOverhaul()}
            >
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันเริ่มรอบการใช้งานใหม่'}
            </button>
          </div>
        </Card>
      )}

      <Card>
        <h2>รอบการใช้งาน (Lifecycle)</h2>
        <ul>
          {lifecycles.map((lc) => (
            <li key={lc.lifecycle_id}>
              <p>
                รอบที่ {lc.cycle_number} — {lifecycleStartReasonLabel[lc.start_reason]}
                {lc.lifecycle_id === instance.current_lifecycle_id ? ' (ปัจจุบัน)' : ''}
              </p>
              <p className="form-field__hint">
                เริ่ม {formatThaiDateTime(lc.started_at)}
                {lc.ended_at ? ` — สิ้นสุด ${formatThaiDateTime(lc.ended_at)}` : ''}
              </p>
              {lc.started_note && <p className="form-field__hint">{lc.started_note}</p>}
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h2>ประวัติการติดตั้ง/ถอด/โยกย้าย</h2>
        {segments.length === 0 && <p>ยังไม่มีประวัติการติดตั้ง</p>}
        <ul>
          {segments.map((segment) => (
            <li key={segment.segment_id}>
              <p>
                {assetTypeLabel[segment.asset_type] ?? segment.asset_type} — {segment.asset_id}
                {segment.position_code ? ` (ตำแหน่ง ${segment.position_code})` : ''}{' '}
                <StatusBadge
                  label={installationSegmentStatusLabel[segment.status]}
                  tone={segment.status === 'ACTIVE' ? 'success' : 'neutral'}
                />
              </p>
              <p className="form-field__hint">
                ติดตั้งเมื่อ {formatThaiDateTime(segment.installed_at)}
                {segment.removed_at ? ` — ถอดเมื่อ ${formatThaiDateTime(segment.removed_at)}` : ''}
              </p>
              {segment.removal_reason && (
                <p className="form-field__hint">เหตุผล: {segment.removal_reason}</p>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </section>
  )
}
