import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost, apiUpload } from '../lib/apiClient'
import {
  assetTypeLabel,
  counterTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  repairSourceTypeLabel,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { AttachmentInfo, MeterSnapshot, RepairDetail } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; detail: RepairDetail; meterSnapshot: MeterSnapshot | null }

export function RepairDetailPage() {
  const { repairId = '' } = useParams<{ repairId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const [actionText, setActionText] = useState('')
  const [actionAttachments, setActionAttachments] = useState<AttachmentInfo[]>([])
  const [uploadingAction, setUploadingAction] = useState(false)
  const [submittingAction, setSubmittingAction] = useState(false)

  const [partDescription, setPartDescription] = useState('')
  const [partQuantity, setPartQuantity] = useState('')
  const [partUnit, setPartUnit] = useState('')
  const [submittingPart, setSubmittingPart] = useState(false)

  const [closeNote, setCloseNote] = useState('')
  const [closing, setClosing] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<RepairDetail>(`/repairs/${repairId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    let meterSnapshot: MeterSnapshot | null = null
    if (result.data.repair.meter_snapshot_id) {
      const snapshotResult = await apiGet<MeterSnapshot>(
        `/meter-snapshots/${result.data.repair.meter_snapshot_id}`,
      )
      if (snapshotResult.ok) meterSnapshot = snapshotResult.data
    }
    setState({ kind: 'ready', detail: result.data, meterSnapshot })
  }, [repairId])

  useEffect(() => {
    void load()
  }, [load])

  const addEvidence = useCallback(async (file: File) => {
    setUploadingAction(true)
    const formData = new FormData()
    formData.append('purpose', 'REPAIR_EVIDENCE')
    formData.append('file', file)
    const result = await apiUpload<AttachmentInfo>('/attachments', formData)
    setUploadingAction(false)
    if (result.ok) setActionAttachments((prev) => [...prev, result.data])
  }, [])

  const submitAction = useCallback(async () => {
    if (!actionText.trim()) {
      setFormError('กรุณาระบุรายละเอียดการดำเนินการ')
      return
    }
    setSubmittingAction(true)
    setFormError(null)
    const result = await apiPost<RepairDetail>(`/repairs/${repairId}/actions`, {
      action_text: actionText.trim(),
      attachment_ids: actionAttachments.map((a) => a.attachment_id),
    })
    setSubmittingAction(false)
    if (result.ok) {
      setActionText('')
      setActionAttachments([])
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [repairId, actionText, actionAttachments, load])

  const submitPart = useCallback(async () => {
    if (!partDescription.trim()) {
      setFormError('กรุณาระบุชื่ออะไหล่')
      return
    }
    setSubmittingPart(true)
    setFormError(null)
    const result = await apiPost<RepairDetail>(`/repairs/${repairId}/parts`, {
      part_description: partDescription.trim(),
      quantity: partQuantity === '' ? null : Number(partQuantity),
      unit: partUnit.trim() || null,
    })
    setSubmittingPart(false)
    if (result.ok) {
      setPartDescription('')
      setPartQuantity('')
      setPartUnit('')
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [repairId, partDescription, partQuantity, partUnit, load])

  const closeRepair = useCallback(async () => {
    setClosing(true)
    const result = await apiPost<RepairDetail>(`/repairs/${repairId}/close`, {
      close_note: closeNote.trim() || null,
    })
    setClosing(false)
    if (result.ok) void load()
  }, [repairId, closeNote, load])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลใบแจ้งซ่อม..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>ใบแจ้งซ่อม</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { repair, actions, parts } = state.detail
  const isOpen = repair.status === 'OPEN'

  return (
    <section className="page">
      <h1>ใบแจ้งซ่อม</h1>
      <p>รหัสใบแจ้งซ่อม: {repair.repair_id}</p>

      <Card>
        <div className="status-card__row">
          <span>สินทรัพย์</span>
          <span>
            {assetTypeLabel[repair.asset_type] ?? repair.asset_type} — {repair.asset_id}
          </span>
        </div>
        <div className="status-card__row">
          <span>สถานะ</span>
          <StatusBadge
            label={repairStatusLabel[repair.status] ?? repair.status}
            tone={repairStatusTone[repair.status]}
          />
        </div>
        <div className="status-card__row">
          <span>แหล่งที่มา</span>
          <span>
            {repairSourceTypeLabel[repair.source_type] ?? repair.source_type}
            {repair.source_id ? ` (${repair.source_id})` : ''}
          </span>
        </div>
        {repair.category && (
          <div className="status-card__row">
            <span>หมวดหมู่</span>
            <span>{repair.category}</span>
          </div>
        )}
        {repair.symptom && <p>อาการ/ปัญหา: {repair.symptom}</p>}
        <div className="status-card__row">
          <span>เปิดแจ้งซ่อมเมื่อ</span>
          <span>{formatThaiDateTime(repair.opened_at)}</span>
        </div>
        {repair.closed_at && (
          <div className="status-card__row">
            <span>ปิดงานเมื่อ</span>
            <span>{formatThaiDateTime(repair.closed_at)}</span>
          </div>
        )}
        {repair.close_note && <p>หมายเหตุปิดงาน: {repair.close_note}</p>}
      </Card>

      {state.meterSnapshot && (
        <Card>
          <h2>ค่ามาตรวัดขณะแจ้งซ่อม</h2>
          {state.meterSnapshot.readings.length === 0 && <p>ไม่มีข้อมูล</p>}
          {state.meterSnapshot.readings.map((reading, index) => (
            <div className="status-card__row" key={index}>
              <span>{counterTypeLabel[reading.counter_type] ?? reading.counter_type}</span>
              <span>{reading.value == null ? 'ไม่ทราบค่า' : reading.value}</span>
            </div>
          ))}
        </Card>
      )}

      <Card>
        <h2>ประวัติการดำเนินการ</h2>
        {actions.length === 0 && <p>ยังไม่มีประวัติการดำเนินการ</p>}
        <ul>
          {actions.map((action) => (
            <li key={action.repair_action_id}>
              <p>{action.action_text}</p>
              <p className="form-field__hint">
                {formatThaiDateTime(action.created_at)} — {action.actor ?? 'ไม่ทราบ'}
              </p>
            </li>
          ))}
        </ul>

        {isOpen && (
          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="action-text">เพิ่มการดำเนินการ</label>
              <textarea
                id="action-text"
                value={actionText}
                onChange={(event) => setActionText(event.target.value)}
                placeholder="อธิบายการตรวจสอบ/ซ่อมที่ทำ"
              />
            </div>
            <div className="form-field">
              <label htmlFor="action-photo">แนบรูปถ่าย (ถ้ามี)</label>
              <input
                id="action-photo"
                type="file"
                accept="image/*"
                capture="environment"
                disabled={uploadingAction}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void addEvidence(file)
                  event.target.value = ''
                }}
              />
              {uploadingAction && <p className="form-field__hint">กำลังอัปโหลดรูปภาพ...</p>}
            </div>
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submittingAction}
              onClick={() => void submitAction()}
            >
              {submittingAction ? 'กำลังบันทึก...' : 'บันทึกการดำเนินการ'}
            </button>
          </div>
        )}
      </Card>

      <Card>
        <h2>อะไหล่ที่ใช้จริง</h2>
        {parts.length === 0 && <p>ยังไม่มีการบันทึกอะไหล่</p>}
        <ul>
          {parts.map((part) => (
            <li key={part.repair_part_id}>
              {part.part_description}
              {part.quantity != null ? ` x${part.quantity}${part.unit ?? ''}` : ''}
            </li>
          ))}
        </ul>

        {isOpen && (
          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="part-description">ชื่ออะไหล่</label>
              <input
                id="part-description"
                type="text"
                value={partDescription}
                onChange={(event) => setPartDescription(event.target.value)}
              />
            </div>
            <div className="part-rows-editor__row-fields">
              <div className="form-field">
                <label htmlFor="part-quantity">จำนวน</label>
                <input
                  id="part-quantity"
                  type="number"
                  inputMode="decimal"
                  value={partQuantity}
                  onChange={(event) => setPartQuantity(event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="part-unit">หน่วย</label>
                <input
                  id="part-unit"
                  type="text"
                  value={partUnit}
                  onChange={(event) => setPartUnit(event.target.value)}
                />
              </div>
            </div>
            <button
              type="button"
              className="button button--secondary button--full-width"
              disabled={submittingPart}
              onClick={() => void submitPart()}
            >
              {submittingPart ? 'กำลังบันทึก...' : '+ เพิ่มอะไหล่'}
            </button>
          </div>
        )}
      </Card>

      {isOpen && (
        <Card>
          <h2>ปิดใบแจ้งซ่อม</h2>
          <div className="form-field">
            <label htmlFor="close-note">หมายเหตุปิดงาน (ถ้ามี)</label>
            <textarea
              id="close-note"
              value={closeNote}
              onChange={(event) => setCloseNote(event.target.value)}
            />
          </div>
          <button
            type="button"
            className="button button--primary button--full-width"
            disabled={closing}
            onClick={() => void closeRepair()}
          >
            {closing ? 'กำลังปิดงาน...' : 'ปิดใบแจ้งซ่อม'}
          </button>
        </Card>
      )}
    </section>
  )
}
