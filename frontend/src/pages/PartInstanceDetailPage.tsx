import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AssetSearchSelect } from '../components/AssetSearchSelect'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { PartLifetimeStatusPanel } from '../components/PartLifetimeStatusPanel'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPostWithRequestId } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  installationSegmentStatusLabel,
  lifecycleStartReasonLabel,
  partInstanceStatusLabel,
  partInstanceStatusTone,
  partOperationLabel,
  priorUsageQualityLabel,
} from '../lib/labels'
import { allowedActions, isUncertain, newRequestId } from '../lib/partLifetime'
import type { AssetType, PartInstanceDetail, PartInstanceStatus } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; detail: PartInstanceDetail }

type ActionPanel = 'none' | 'install' | 'remove' | 'transfer' | 'status' | 'return' | 'identifiers'

const REMOVAL_NEXT_STATUSES: PartInstanceStatus[] = ['REMOVED', 'IN_REPAIR', 'STOCK', 'SCRAPPED']
const APPROVER_CAPABILITIES = ['can_manage_repair', 'can_manage_pm']

export function PartInstanceDetailPage() {
  const { instanceId = '' } = useParams<{ instanceId: string }>()
  const { hasCapability } = useCapabilities()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [panel, setPanel] = useState<ActionPanel>('none')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [identityHint, setIdentityHint] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  // One client intent id per open panel; kept after an uncertain outcome so a
  // retry is the SAME intent (the server replays the committed result).
  const intentId = useRef<string>(newRequestId())
  const loadGeneration = useRef(0)

  // install / transfer
  const [assetType, setAssetType] = useState<AssetType>('VEHICLE')
  const [assetId, setAssetId] = useState('')
  const [positionCode, setPositionCode] = useState('')
  const [targetAssetType, setTargetAssetType] = useState<AssetType>('VEHICLE')
  const [targetAssetId, setTargetAssetId] = useState('')
  const [transferPositionCode, setTransferPositionCode] = useState('')
  // remove / status / return
  const [nextStatus, setNextStatus] = useState<PartInstanceStatus>('IN_REPAIR')
  const [removalReason, setRemovalReason] = useState('')
  const [storageLocation, setStorageLocation] = useState('')
  const [moveTo, setMoveTo] = useState<PartInstanceStatus | ''>('')
  const [returnOutcome, setReturnOutcome] = useState('')
  const [repairReference, setRepairReference] = useState('')
  const [approveNewCycle, setApproveNewCycle] = useState(false)
  const [approvalReasonCode, setApprovalReasonCode] = useState('')
  // identifiers
  const [serialNumber, setSerialNumber] = useState('')
  const [tagLabel, setTagLabel] = useState('')

  const load = useCallback(async () => {
    const mine = ++loadGeneration.current
    setState({ kind: 'loading' })
    const result = await apiGet<PartInstanceDetail>(`/part-instances/${instanceId}`)
    if (mine !== loadGeneration.current) return
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

  const openPanel = (next: ActionPanel) => {
    setPanel(panel === next ? 'none' : next)
    setFormError(null)
    intentId.current = newRequestId()
  }

  const submit = async (path: string, body: Record<string, unknown>) => {
    setSubmitting(true)
    setFormError(null)
    const result = await apiPostWithRequestId<PartInstanceDetail>(`/part-instances/${instanceId}/${path}`, body,
      intentId.current)
    setSubmitting(false)
    if (result.ok) {
      intentId.current = newRequestId()
      setPanel('none')
      setIdentityHint(false)
      setState({ kind: 'ready', detail: result.data })
      setReloadKey((k) => k + 1)
      return
    }
    const err = result.error
    if (err instanceof ApiError && !isUncertain(err.status)) {
      intentId.current = newRequestId() // a definitive refusal ends this intent
      if (err.code === 'PHYSICAL_IDENTITY_INSUFFICIENT') {
        setIdentityHint(true)
      }
      setFormError(describeErrorCode(err.code))
      return
    }
    // Uncertain outcome: keep the same request id so "ลองอีกครั้ง" is the same intent.
    setFormError('ไม่ทราบผลการบันทึก (การเชื่อมต่อขัดข้อง) — กดยืนยันอีกครั้งเพื่อส่งคำขอเดิมซ้ำอย่างปลอดภัย')
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
  const statusEvents = state.detail.status_events ?? []
  const actions = allowedActions(instance.status)
  const activeSegment = segments.find((s) => s.status === 'ACTIVE')
  const canApprove = APPROVER_CAPABILITIES.some((c) => hasCapability(c))
  const errorBlock = formError && (
    <p className="form-field__error" role="alert">
      {formError}
      {identityHint && (
        <>
          {' '}
          <button type="button" className="button button--secondary" onClick={() => openPanel('identifiers')}>
            เพิ่มหมายเลข/ป้ายระบุชิ้น
          </button>
        </>
      )}
    </p>
  )

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
          <span>รหัสชิ้นงานในระบบ</span>
          <span>{instance.part_instance_id}</span>
        </div>
        <div className="status-card__row">
          <span>หมายเลขซีเรียล</span>
          <span>{instance.serial_number ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>ป้ายระบุชิ้น</span>
          <span>{instance.tag_label ?? 'ไม่มีข้อมูล'}</span>
        </div>
        {instance.status !== 'INSTALLED' && (
          <div className="status-card__row">
            <span>ตำแหน่งจัดเก็บปัจจุบัน — ไม่ใช่รหัสชิ้น</span>
            <span>{instance.storage_location ?? 'ไม่ทราบตำแหน่งจัดเก็บ'}</span>
          </div>
        )}
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
        {instance.status === 'IN_REPAIR' && (
          <p className="form-field__hint">ชิ้นงานที่อยู่ระหว่างซ่อมต้องบันทึกรับกลับจากซ่อมก่อนติดตั้ง</p>
        )}

        <div className="status-card__actions">
          {actions.install && (
            <button type="button" className="button button--primary button--full-width"
              onClick={() => openPanel('install')}>
              ติดตั้ง
            </button>
          )}
          {actions.remove && (
            <button type="button" className="button button--secondary button--full-width"
              onClick={() => openPanel('remove')}>
              ถอดออก
            </button>
          )}
          {actions.transfer && (
            <button type="button" className="button button--secondary button--full-width"
              onClick={() => openPanel('transfer')}>
              โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น
            </button>
          )}
          {actions.returnFromRepair && (
            <button type="button" className="button button--primary button--full-width"
              onClick={() => openPanel('return')}>
              รับกลับจากซ่อม
            </button>
          )}
          {actions.statusMoves.length > 0 && (
            <button type="button" className="button button--secondary button--full-width"
              onClick={() => openPanel('status')}>
              เปลี่ยนสถานะ (คลัง/พร้อมติดตั้ง/ส่งซ่อม/ปลดระวาง)
            </button>
          )}
          {(!instance.serial_number || !instance.tag_label) && instance.status !== 'SCRAPPED' && (
            <button type="button" className="button button--secondary button--full-width"
              onClick={() => openPanel('identifiers')}>
              เพิ่มหมายเลข/ป้ายระบุชิ้น
            </button>
          )}
        </div>
        {panel === 'none' && errorBlock}
      </Card>

      {panel === 'install' && (
        <Card>
          <h2>ติดตั้งชิ้นงาน</h2>
          <div className="form-grid">
            <FormField label="ประเภทสินทรัพย์" htmlFor="install-asset-type">
              <select id="install-asset-type" value={assetType}
                onChange={(event) => setAssetType(event.target.value as AssetType)}>
                <option value="VEHICLE">ยานพาหนะ</option>
                <option value="EQUIPMENT">เครื่องมือ/อุปกรณ์</option>
              </select>
            </FormField>
            <AssetSearchSelect id="install-asset-id" assetType={assetType} assetId={assetId}
              onChangeAssetId={setAssetId} />
            <FormField label="ตำแหน่งติดตั้ง (ถ้ามี)" htmlFor="install-position">
              <input id="install-position" type="text" value={positionCode}
                onChange={(e) => setPositionCode(e.target.value)} />
            </FormField>
            {errorBlock}
            <button type="button" className="button button--primary button--full-width" disabled={submitting}
              onClick={() => {
                if (!assetId.trim()) {
                  setFormError('กรุณาระบุรหัสยานพาหนะ/อุปกรณ์')
                  return
                }
                void submit('install', { asset_type: assetType, asset_id: assetId.trim(),
                  position_code: positionCode.trim() || null })
              }}>
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
              <select id="remove-next-status" value={nextStatus}
                onChange={(event) => setNextStatus(event.target.value as PartInstanceStatus)}>
                {REMOVAL_NEXT_STATUSES.map((status) => (
                  <option key={status} value={status}>{partInstanceStatusLabel[status]}</option>
                ))}
              </select>
            </FormField>
            <FormField label="ตำแหน่งจัดเก็บ (ถ้ามี)" htmlFor="remove-location">
              <input id="remove-location" type="text" value={storageLocation}
                onChange={(e) => setStorageLocation(e.target.value)} />
            </FormField>
            <FormField label="เหตุผล (ถ้ามี)" htmlFor="remove-reason">
              <textarea id="remove-reason" value={removalReason}
                onChange={(event) => setRemovalReason(event.target.value)} />
            </FormField>
            {errorBlock}
            <button type="button" className="button button--primary button--full-width" disabled={submitting}
              onClick={() => void submit('remove', { next_status: nextStatus,
                removal_reason: removalReason.trim() || null, storage_location: storageLocation.trim() || null })}>
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันการถอดออก'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'transfer' && (
        <Card>
          <h2>โยกย้ายชิ้นงาน</h2>
          <p className="form-field__hint">การโยกย้ายไม่รีเซ็ตอายุรวมและรอบปัจจุบัน</p>
          <div className="form-grid">
            <FormField label="ประเภทสินทรัพย์ปลายทาง" htmlFor="transfer-asset-type">
              <select id="transfer-asset-type" value={targetAssetType}
                onChange={(event) => setTargetAssetType(event.target.value as AssetType)}>
                <option value="VEHICLE">ยานพาหนะ</option>
                <option value="EQUIPMENT">เครื่องมือ/อุปกรณ์</option>
              </select>
            </FormField>
            <AssetSearchSelect id="transfer-asset-id" assetType={targetAssetType} assetId={targetAssetId}
              onChangeAssetId={setTargetAssetId} />
            <FormField label="ตำแหน่งติดตั้งใหม่ (ถ้ามี)" htmlFor="transfer-position">
              <input id="transfer-position" type="text" value={transferPositionCode}
                onChange={(event) => setTransferPositionCode(event.target.value)} />
            </FormField>
            {errorBlock}
            <button type="button" className="button button--primary button--full-width" disabled={submitting}
              onClick={() => {
                if (!targetAssetId.trim()) {
                  setFormError('กรุณาระบุรหัสยานพาหนะ/อุปกรณ์ปลายทาง')
                  return
                }
                void submit('transfer', { target_asset_type: targetAssetType, target_asset_id: targetAssetId.trim(),
                  position_code: transferPositionCode.trim() || null })
              }}>
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันการโยกย้าย'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'status' && (
        <Card>
          <h2>เปลี่ยนสถานะชิ้นงาน</h2>
          <div className="form-grid">
            <FormField label="สถานะใหม่" htmlFor="status-move-to">
              <select id="status-move-to" value={moveTo}
                onChange={(event) => setMoveTo(event.target.value as PartInstanceStatus)}>
                <option value="">— เลือก —</option>
                {actions.statusMoves.map((status) => (
                  <option key={status} value={status}>{partInstanceStatusLabel[status]}</option>
                ))}
              </select>
            </FormField>
            <FormField label="ตำแหน่งจัดเก็บ/ผู้รับซ่อม (ถ้ามี)" htmlFor="status-location">
              <input id="status-location" type="text" value={storageLocation}
                onChange={(e) => setStorageLocation(e.target.value)} />
            </FormField>
            {errorBlock}
            <button type="button" className="button button--primary button--full-width"
              disabled={submitting || !moveTo}
              onClick={() => void submit('status', { to_status: moveTo,
                storage_location: storageLocation.trim() || null })}>
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันการเปลี่ยนสถานะ'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'return' && (
        <Card>
          <h2>รับกลับจากซ่อม</h2>
          <p className="form-field__hint">
            การซ่อมทั่วไปไม่เริ่มรอบใหม่ — รอบใหม่จะเริ่มเมื่อติดตั้งชิ้นงานที่ได้รับอนุมัติเท่านั้น อายุรวมไม่ถูกรีเซ็ต
          </p>
          <div className="form-grid">
            <FormField label="ผลการซ่อม" htmlFor="return-outcome">
              <input id="return-outcome" type="text" value={returnOutcome}
                onChange={(e) => setReturnOutcome(e.target.value)} />
            </FormField>
            <FormField label="เลขที่ใบงานซ่อม (ถ้ามี)" htmlFor="return-repair-reference">
              <input id="return-repair-reference" type="text" value={repairReference}
                onChange={(e) => setRepairReference(e.target.value)} />
            </FormField>
            <FormField label="ตำแหน่งจัดเก็บ (ถ้ามี)" htmlFor="return-location">
              <input id="return-location" type="text" value={storageLocation}
                onChange={(e) => setStorageLocation(e.target.value)} />
            </FormField>
            {canApprove && (
              <label className="form-field">
                <input type="checkbox" checked={approveNewCycle}
                  onChange={(e) => setApproveNewCycle(e.target.checked)} />{' '}
                อนุมัติให้เริ่มรอบการใช้งานใหม่เมื่อติดตั้ง
              </label>
            )}
            {canApprove && approveNewCycle && (
              <FormField label="รหัสเหตุผลการอนุมัติ (ข้อมูลทดสอบ: ขึ้นต้นด้วย TEST-)" htmlFor="return-reason-code">
                <input id="return-reason-code" type="text" value={approvalReasonCode}
                  onChange={(e) => setApprovalReasonCode(e.target.value)} />
              </FormField>
            )}
            {errorBlock}
            <button type="button" className="button button--primary button--full-width" disabled={submitting}
              onClick={() => void submit('return-from-repair', {
                outcome: returnOutcome.trim() || null,
                repair_reference: repairReference.trim() || null,
                storage_location: storageLocation.trim() || null,
                new_cycle_approved: canApprove && approveNewCycle,
                approval_reason_code: canApprove && approveNewCycle ? approvalReasonCode.trim() || null : null,
              })}>
              {submitting ? 'กำลังบันทึก...' : 'ยืนยันรับกลับจากซ่อม'}
            </button>
          </div>
        </Card>
      )}

      {panel === 'identifiers' && (
        <Card>
          <h2>เพิ่มหมายเลข/ป้ายระบุชิ้น</h2>
          <p className="form-field__hint">กำหนดได้ครั้งเดียว — แก้ไขภายหลังไม่ได้</p>
          <div className="form-grid">
            {!instance.serial_number && (
              <FormField label="หมายเลขซีเรียล" htmlFor="ident-serial">
                <input id="ident-serial" type="text" value={serialNumber}
                  onChange={(e) => setSerialNumber(e.target.value)} />
              </FormField>
            )}
            {!instance.tag_label && (
              <FormField label="ป้ายระบุชิ้น" htmlFor="ident-tag">
                <input id="ident-tag" type="text" value={tagLabel} onChange={(e) => setTagLabel(e.target.value)} />
              </FormField>
            )}
            {errorBlock}
            <button type="button" className="button button--primary button--full-width" disabled={submitting}
              onClick={() => void submit('identifiers', { serial_number: serialNumber.trim() || null,
                tag_label: tagLabel.trim() || null })}>
              {submitting ? 'กำลังบันทึก...' : 'บันทึกหมายเลข/ป้าย'}
            </button>
          </div>
        </Card>
      )}

      <PartLifetimeStatusPanel path={`/part-instances/${instanceId}/lifetime-status`} reloadKey={reloadKey} />

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
                ติดตั้งเมื่อ {formatThaiDateTime(segment.installed_effective_at ?? segment.installed_at)}
                {segment.removed_at
                  ? ` — ถอดเมื่อ ${formatThaiDateTime(segment.removed_effective_at ?? segment.removed_at)}`
                  : ''}
              </p>
              {segment.removal_reason && <p className="form-field__hint">เหตุผล: {segment.removal_reason}</p>}
            </li>
          ))}
        </ul>
      </Card>

      {statusEvents.length > 0 && (
        <Card>
          <h2>ประวัติสถานะ</h2>
          <ul>
            {statusEvents.map((event) => (
              <li key={event.event_id} data-testid="status-event">
                <p>
                  {partOperationLabel[event.operation] ?? event.operation} —{' '}
                  {partInstanceStatusLabel[event.to_status] ?? event.to_status}
                  {event.new_cycle_approved ? ' (อนุมัติเริ่มรอบใหม่เมื่อติดตั้ง)' : ''}
                </p>
                <p className="form-field__hint">
                  {formatThaiDateTime(event.effective_at)}
                  {event.storage_location ? ` · ${event.storage_location}` : ''}
                  {event.actor ? ` · ${event.actor}` : ''}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  )
}
