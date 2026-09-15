import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PartMasterSearchSelect } from '../components/PartMasterSearchSelect'
import { PhotoAttachmentField } from '../components/PhotoAttachmentField'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost, apiUpload } from '../lib/apiClient'
import {
  assetTypeLabel,
  counterTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  partActionTypeLabel,
  repairSourceTypeLabel,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { AttachmentInfo, MeterSnapshot, PartMaster, RepairDetail } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | {
      kind: 'ready'
      detail: RepairDetail
      meterSnapshot: MeterSnapshot | null
      closedSnapshot: MeterSnapshot | null
    }

export function RepairDetailPage() {
  const { repairId = '' } = useParams<{ repairId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const [actionText, setActionText] = useState('')
  const [actionAttachments, setActionAttachments] = useState<AttachmentInfo[]>([])
  const [uploadingAction, setUploadingAction] = useState(false)
  const [submittingAction, setSubmittingAction] = useState(false)

  const [selectedPart, setSelectedPart] = useState<PartMaster | null>(null)
  const [partFreeText, setPartFreeText] = useState('')
  const [partQuantity, setPartQuantity] = useState('')
  const [partUnit, setPartUnit] = useState('')
  const [partInstanceId, setPartInstanceId] = useState('')
  const [submittingPart, setSubmittingPart] = useState(false)

  const [primaryTechnician, setPrimaryTechnician] = useState('')
  const [collaboratorsText, setCollaboratorsText] = useState('')
  const [savingAssignment, setSavingAssignment] = useState(false)

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
    let closedSnapshot: MeterSnapshot | null = null
    if (result.data.repair.closed_snapshot_id) {
      const snapshotResult = await apiGet<MeterSnapshot>(
        `/meter-snapshots/${result.data.repair.closed_snapshot_id}`,
      )
      if (snapshotResult.ok) closedSnapshot = snapshotResult.data
    }
    setState({ kind: 'ready', detail: result.data, meterSnapshot, closedSnapshot })
    setPrimaryTechnician(result.data.repair.primary_technician ?? '')
    setCollaboratorsText((result.data.repair.collaborators ?? []).join(', '))
  }, [repairId])

  useEffect(() => {
    void load()
  }, [load])

  const addEvidence = useCallback(async (file: File) => {
    setUploadingAction(true)
    const formData = new FormData()
    formData.append('purpose', 'REPAIR_EVIDENCE')
    formData.append('source_type', 'REPAIR')
    formData.append('source_id', repairId)
    formData.append('file', file)
    const result = await apiUpload<AttachmentInfo>('/attachments', formData)
    setUploadingAction(false)
    if (result.ok) setActionAttachments((prev) => [...prev, result.data])
  }, [repairId])

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
    const description = selectedPart
      ? `${selectedPart.name}${selectedPart.specification ? ` (${selectedPart.specification})` : ''}`
      : partFreeText.trim()
    if (!description) {
      setFormError('กรุณาเลือกอะไหล่จาก Part Master หรือระบุชื่ออะไหล่')
      return
    }
    setSubmittingPart(true)
    setFormError(null)
    const result = await apiPost<RepairDetail>(`/repairs/${repairId}/parts`, {
      part_description: description,
      part_id: selectedPart?.part_id ?? null,
      quantity: partQuantity === '' ? null : Number(partQuantity),
      unit: partUnit.trim() || null,
      part_instance_id: partInstanceId.trim() || null,
    })
    setSubmittingPart(false)
    if (result.ok) {
      setSelectedPart(null)
      setPartFreeText('')
      setPartQuantity('')
      setPartUnit('')
      setPartInstanceId('')
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [repairId, selectedPart, partFreeText, partQuantity, partUnit, partInstanceId, load])

  const saveAssignment = useCallback(async () => {
    setSavingAssignment(true)
    setFormError(null)
    const collaborators = collaboratorsText
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean)
    const result = await apiPost<RepairDetail>(`/repairs/${repairId}/assign`, {
      primary_technician: primaryTechnician.trim() || null,
      collaborators,
    })
    setSavingAssignment(false)
    if (result.ok) {
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }, [repairId, primaryTechnician, collaboratorsText, load])

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
  const sortedActions = [...actions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )
  const latestAction = sortedActions[0] ?? null
  const olderActions = sortedActions.slice(1)

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

      <Card>
        <h2>การมอบหมายงาน</h2>
        <div className="form-grid">
          <div className="form-field">
            <label htmlFor="primary-technician">ช่างผู้รับผิดชอบหลัก</label>
            <input
              id="primary-technician"
              type="text"
              value={primaryTechnician}
              onChange={(event) => setPrimaryTechnician(event.target.value)}
              disabled={!isOpen}
            />
          </div>
          <div className="form-field">
            <label htmlFor="collaborators">ผู้ร่วมงาน (คั่นด้วยจุลภาค)</label>
            <input
              id="collaborators"
              type="text"
              value={collaboratorsText}
              onChange={(event) => setCollaboratorsText(event.target.value)}
              disabled={!isOpen}
            />
          </div>
          {isOpen && (
            <button
              type="button"
              className="button button--secondary button--full-width"
              disabled={savingAssignment}
              onClick={() => void saveAssignment()}
            >
              {savingAssignment ? 'กำลังบันทึก...' : 'บันทึกการมอบหมาย'}
            </button>
          )}
        </div>
      </Card>

      {state.meterSnapshot && (
        <Card>
          <h2>ค่ามาตรวัดขณะแจ้งซ่อม</h2>
          <p className="form-field__hint">
            {state.meterSnapshot.is_automatic
              ? 'บันทึกโดยระบบอัตโนมัติจากข้อมูลล่าสุดที่ทราบ'
              : 'บันทึกโดยผู้ใช้งาน'}
          </p>
          {state.meterSnapshot.readings.length === 0 && <p>ไม่มีข้อมูล</p>}
          {state.meterSnapshot.readings.map((reading, index) => (
            <div className="status-card__row" key={index}>
              <span>{counterTypeLabel[reading.counter_type] ?? reading.counter_type}</span>
              <span>{reading.value == null ? 'ไม่ทราบค่า' : reading.value}</span>
            </div>
          ))}
        </Card>
      )}

      {state.closedSnapshot && (
        <Card>
          <h2>ค่ามาตรวัดขณะปิดงาน</h2>
          {state.closedSnapshot.readings.map((reading, index) => (
            <div className="status-card__row" key={index}>
              <span>{counterTypeLabel[reading.counter_type] ?? reading.counter_type}</span>
              <span>{reading.value == null ? 'ไม่ทราบค่า' : reading.value}</span>
            </div>
          ))}
        </Card>
      )}

      <Card>
        <h2>ความคืบหน้าล่าสุด</h2>
        {latestAction ? (
          <div>
            <p>{latestAction.action_text}</p>
            <p className="form-field__hint">
              {formatThaiDateTime(latestAction.created_at)} — {latestAction.actor ?? 'ไม่ทราบ'}
            </p>
          </div>
        ) : (
          <p>ยังไม่มีประวัติการดำเนินการ</p>
        )}

        {olderActions.length > 0 && (
          <details className="disclosure">
            <summary>ดูประวัติการดำเนินการทั้งหมด ({actions.length} รายการ)</summary>
            <ul>
              {olderActions.map((action) => (
                <li key={action.repair_action_id}>
                  <p>{action.action_text}</p>
                  <p className="form-field__hint">
                    {formatThaiDateTime(action.created_at)} — {action.actor ?? 'ไม่ทราบ'}
                  </p>
                </li>
              ))}
            </ul>
          </details>
        )}

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
            <PhotoAttachmentField
              id="action-photo"
              label="แนบรูปถ่าย (ถ้ามี)"
              attachments={actionAttachments}
              uploading={uploadingAction}
              onAddFile={(file) => void addEvidence(file)}
              onRemove={(attachmentId) =>
                setActionAttachments((prev) => prev.filter((a) => a.attachment_id !== attachmentId))
              }
              altPrefix="รูปแนบการดำเนินการ"
            />
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
              {part.action && ` — ${partActionTypeLabel[part.action]}`}
              {part.part_instance_id && (
                <>
                  {' '}
                  (<Link to={`/part-instances/${part.part_instance_id}`}>{part.part_instance_id}</Link>)
                </>
              )}
            </li>
          ))}
        </ul>

        {isOpen && (
          <div className="form-grid">
            <PartMasterSearchSelect
              selectedPart={selectedPart}
              onSelectPart={setSelectedPart}
              freeTextDescription={partFreeText}
              onFreeTextDescriptionChange={setPartFreeText}
            />
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
            <div className="form-field">
              <label htmlFor="part-instance-id">รหัสชิ้นงาน (Part Instance) — ถ้ามี</label>
              <input
                id="part-instance-id"
                type="text"
                value={partInstanceId}
                onChange={(event) => setPartInstanceId(event.target.value)}
                placeholder="เช่น PINST-0001"
              />
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
