import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ChecklistItemCard, type ChecklistItemAnswer } from '../components/ChecklistItemCard'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPostWithRequestId, apiUpload } from '../lib/apiClient'
import {
  ABNORMAL_INSPECTION_RESULTS,
  describeErrorCode,
  formatThaiDate,
  INSPECTION_OBSERVATION_NOTE,
} from '../lib/labels'
import { newRequestId } from '../lib/registryPending'
import type {
  AssetType,
  AttachmentInfo,
  Equipment,
  InspectionDetail,
  InspectionForm,
  SubmitInspectionRequest,
  Vehicle,
} from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; form: InspectionForm; assetLabel: string }

/**
 * Shared inspection form for both `/vehicle/:vehicleId/inspect` and
 * `/equipment/:equipmentId/inspect` (Phase 3 scope: "same engine supports
 * workshop equipment"). The frozen `/vehicle/{id}` / `/equipment/{id}` QR
 * routes themselves are untouched — this is a separate nested route.
 *
 * R3 (docs/project-governance/r3-implementation-contract.md §4–§6): the
 * backend resolves the asset's checklist and shows only today's due items
 * (every DAILY item, plus EVERY_7_DAYS items that are due). Both abnormal
 * results need a remark; photos are optional. One inspection per asset per
 * Bangkok date. Each submission intent carries one X-Request-Id: a retry
 * after a timeout reuses it (the server returns the original), and any edit
 * of the answers starts a new intent.
 */
export function InspectionFormPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const navigate = useNavigate()

  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''

  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [answers, setAnswers] = useState<Record<string, ChecklistItemAnswer>>({})
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({})
  const [uploadingItemId, setUploadingItemId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [existingInspectionId, setExistingInspectionId] = useState<string | null>(null)
  const intentId = useRef<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    setSubmitError(null)

    const [formResult, assetResult] = await Promise.all([
      apiGet<InspectionForm>(
        `/inspections/form?asset_type=${assetType}&asset_id=${encodeURIComponent(assetId)}`,
      ),
      assetType === 'VEHICLE'
        ? apiGet<{ vehicle: Vehicle }>(`/vehicles/${assetId}`)
        : apiGet<Equipment>(`/equipment/${assetId}`),
    ])

    // CORRECTION (post-Phase-3 verification): validate the asset exists
    // before allowing inspection entry — do not wait until final
    // submission to discover an invalid/mismatched asset ID.
    for (const result of [assetResult, formResult]) {
      if (!result.ok) {
        const err = result.error
        setState({
          kind: 'error',
          message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
          requestId: err instanceof ApiError ? err.requestId : null,
        })
        return
      }
    }
    if (!formResult.ok || !assetResult.ok) return

    const assetLabel =
      assetType === 'VEHICLE'
        ? (assetResult.data as { vehicle: Vehicle }).vehicle.machine_no
        : (assetResult.data as Equipment).name

    const initialAnswers: Record<string, ChecklistItemAnswer> = {}
    for (const entry of formResult.data.items) {
      initialAnswers[entry.item.item_id] = { result: null, remark: '', evidence: [] }
    }
    intentId.current = null
    setAnswers(initialAnswers)
    setItemErrors({})
    setExistingInspectionId(formResult.data.submitted_inspection_id)
    setState({ kind: 'ready', form: formResult.data, assetLabel })
  }, [assetType, assetId])

  useEffect(() => {
    void load()
  }, [load])

  const clearItemError = useCallback((itemId: string) => {
    setItemErrors((prev) => {
      if (!(itemId in prev)) return prev
      const next = { ...prev }
      delete next[itemId]
      return next
    })
  }, [])

  const updateAnswer = useCallback(
    (itemId: string, patch: Partial<ChecklistItemAnswer>) => {
      intentId.current = null // an edited answer is a new submission intent
      setAnswers((prev) => ({ ...prev, [itemId]: { ...prev[itemId], ...patch } }))
      clearItemError(itemId)
    },
    [clearItemError],
  )

  const handleAddEvidence = useCallback(
    async (itemId: string, file: File) => {
      setUploadingItemId(itemId)
      const formData = new FormData()
      formData.append('purpose', 'INSPECTION_EVIDENCE')
      formData.append(
        'source_type',
        assetType === 'VEHICLE' ? 'INSPECTION_VEHICLE' : 'INSPECTION_EQUIPMENT',
      )
      formData.append('source_id', assetId)
      formData.append('file', file)
      const result = await apiUpload<AttachmentInfo>('/attachments', formData)
      setUploadingItemId(null)
      if (result.ok) {
        updateAnswer(itemId, {})
        setAnswers((prev) => ({
          ...prev,
          [itemId]: { ...prev[itemId], evidence: [...prev[itemId].evidence, result.data] },
        }))
        return
      }
      // The upload boundary can reject a disallowed type or an oversized
      // file, so a failed upload surfaces a Thai message.
      const err = result.error
      setItemErrors((prev) => ({
        ...prev,
        [itemId]: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      }))
    },
    [assetType, assetId, updateAnswer],
  )

  const handleRemoveEvidence = useCallback(
    (itemId: string, attachmentId: string) => {
      intentId.current = null
      setAnswers((prev) => ({
        ...prev,
        [itemId]: {
          ...prev[itemId],
          evidence: prev[itemId].evidence.filter((e) => e.attachment_id !== attachmentId),
        },
      }))
    },
    [],
  )

  const entries = state.kind === 'ready' ? state.form.items : []
  const canSubmit =
    entries.length > 0 &&
    existingInspectionId === null &&
    entries.every((entry) => answers[entry.item.item_id]?.result !== null)

  const handleSubmit = useCallback(async () => {
    if (state.kind !== 'ready') return

    const errors: Record<string, string> = {}
    for (const { item } of state.form.items) {
      const answer = answers[item.item_id]
      if (!answer?.result) {
        errors[item.item_id] = 'กรุณาเลือกผลการตรวจ'
      } else if (ABNORMAL_INSPECTION_RESULTS.includes(answer.result) && !answer.remark.trim()) {
        // R3-15: both abnormal results need a descriptive remark (photo optional).
        errors[item.item_id] = 'กรุณาระบุหมายเหตุเมื่อผลตรวจผิดปกติหรือใช้งานได้รอการแก้ไข'
      }
    }
    if (Object.keys(errors).length > 0) {
      setItemErrors(errors)
      setSubmitError('กรุณาตรวจสอบรายการที่ยังไม่ครบถ้วน')
      return
    }

    setSubmitting(true)
    setSubmitError(null)

    const body: SubmitInspectionRequest = {
      asset_type: assetType,
      asset_id: assetId,
      items: state.form.items.map(({ item }) => {
        const answer = answers[item.item_id]
        return {
          item_id: item.item_id,
          result: answer.result!,
          remark: answer.remark.trim() ? answer.remark.trim() : null,
          evidence_attachment_ids: answer.evidence.map((e) => e.attachment_id),
        }
      }),
    }

    intentId.current ??= newRequestId()
    const result = await apiPostWithRequestId<InspectionDetail>('/inspections', body, intentId.current)
    setSubmitting(false)
    if (result.ok) {
      intentId.current = null
      navigate(`/inspections/${result.data.header.inspection_id}`)
      return
    }
    const err = result.error
    if (err instanceof ApiError) {
      intentId.current = err.code === 'REQUEST_ID_REUSED' ? null : intentId.current
      if (err.code === 'INSPECTION_ALREADY_SUBMITTED_TODAY') {
        const existing = err.details?.inspection_id
        setExistingInspectionId(typeof existing === 'string' ? existing : null)
      }
      setSubmitError(describeErrorCode(err.code))
      return
    }
    // Transport failure / timeout: keep the same request id so a retry is
    // recognised by the server as the same submission.
    setSubmitError('ส่งผลการตรวจไม่สำเร็จหรือไม่ทราบผล กรุณากดส่งอีกครั้ง ระบบจะไม่บันทึกซ้ำ')
  }, [state, answers, assetType, assetId, navigate])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดรายการตรวจเช็ค..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>ตรวจเช็ค</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  return (
    <section className="page inspection-form-page">
      <h1>ตรวจเช็ค: {state.assetLabel}</h1>
      <p>{state.form.checklist.name}</p>
      <p className="form-field__hint" data-testid="inspection-date">
        วันที่ตรวจ {formatThaiDate(state.form.inspection_date)} · รุ่นรายการตรวจที่ {state.form.revision.revision_number}
      </p>
      <p className="form-field__hint" data-testid="inspection-observation-note">
        {INSPECTION_OBSERVATION_NOTE}
      </p>

      {existingInspectionId !== null ? (
        <Card>
          <div role="status" data-testid="inspection-already-submitted">
            <p>วันนี้ส่งผลตรวจของเครื่องนี้แล้ว (บันทึกได้วันละหนึ่งครั้ง) ผลที่ส่งแล้วแก้ไขไม่ได้</p>
            <Link to={`/inspections/${existingInspectionId}`}>ดูผลการตรวจของวันนี้</Link>
          </div>
        </Card>
      ) : (
        state.form.items.map(({ item, due_reason }) => (
          <ChecklistItemCard
            key={item.item_id}
            item={item}
            dueReason={due_reason}
            answer={answers[item.item_id] ?? { result: null, remark: '', evidence: [] }}
            uploading={uploadingItemId === item.item_id}
            error={itemErrors[item.item_id]}
            onResultChange={(result) => updateAnswer(item.item_id, { result })}
            onRemarkChange={(remark) => updateAnswer(item.item_id, { remark })}
            onAddEvidence={(file) => void handleAddEvidence(item.item_id, file)}
            onRemoveEvidence={(attachmentId) => handleRemoveEvidence(item.item_id, attachmentId)}
          />
        ))
      )}

      <div className="sticky-actions">
        {submitError && (
          <p className="form-field__error" role="alert">
            {submitError}
          </p>
        )}
        <button
          type="button"
          className="button button--primary button--full-width"
          disabled={!canSubmit || submitting}
          onClick={() => void handleSubmit()}
        >
          {submitting ? 'กำลังส่งผลการตรวจ...' : 'ส่งผลการตรวจ'}
        </button>
      </div>
    </section>
  )
}
