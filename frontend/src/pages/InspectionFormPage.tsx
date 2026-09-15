import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChecklistItemCard, type ChecklistItemAnswer } from '../components/ChecklistItemCard'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPost, apiUpload } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import type {
  AssetType,
  AttachmentInfo,
  ChecklistRevisionDetail,
  Equipment,
  InspectionDetail,
  SubmitInspectionRequest,
  Vehicle,
} from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; checklist: ChecklistRevisionDetail; assetLabel: string }

/**
 * Shared inspection form for both `/vehicle/:vehicleId/inspect` and
 * `/equipment/:equipmentId/inspect` (Phase 3 scope: "same engine supports
 * workshop equipment"). The frozen `/vehicle/{id}` / `/equipment/{id}` QR
 * routes themselves are untouched — this is a separate nested route.
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

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    setSubmitError(null)

    const [checklistResult, assetResult] = await Promise.all([
      apiGet<ChecklistRevisionDetail>(`/checklists/active?asset_type=${assetType}`),
      assetType === 'VEHICLE'
        ? apiGet<{ vehicle: Vehicle }>(`/vehicles/${assetId}`)
        : apiGet<Equipment>(`/equipment/${assetId}`),
    ])

    // CORRECTION (post-Phase-3 verification): validate the asset exists
    // before allowing inspection entry — do not wait until final
    // submission to discover an invalid/mismatched asset ID. The frozen
    // `/vehicle/{vehicle_id}` and `/equipment/{equipment_id}` QR routes
    // themselves are untouched; this only affects the nested
    // `/inspect` entry point's own loading state.
    if (!assetResult.ok) {
      const err = assetResult.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }

    if (!checklistResult.ok) {
      const err = checklistResult.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }

    const assetLabel =
      assetType === 'VEHICLE'
        ? (assetResult.data as { vehicle: Vehicle }).vehicle.machine_no
        : (assetResult.data as Equipment).name

    const initialAnswers: Record<string, ChecklistItemAnswer> = {}
    for (const item of checklistResult.data.items) {
      initialAnswers[item.item_id] = { result: null, remark: '', evidence: [] }
    }
    setAnswers(initialAnswers)
    setItemErrors({})
    setState({ kind: 'ready', checklist: checklistResult.data, assetLabel })
  }, [assetType, assetId])

  useEffect(() => {
    void load()
  }, [load])

  const updateAnswer = useCallback(
    (itemId: string, patch: Partial<ChecklistItemAnswer>) => {
      setAnswers((prev) => ({ ...prev, [itemId]: { ...prev[itemId], ...patch } }))
      setItemErrors((prev) => {
        if (!(itemId in prev)) return prev
        const next = { ...prev }
        delete next[itemId]
        return next
      })
    },
    [setAnswers],
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
        setAnswers((prev) => ({
          ...prev,
          [itemId]: { ...prev[itemId], evidence: [...prev[itemId].evidence, result.data] },
        }))
        setItemErrors((prev) => {
          if (!(itemId in prev)) return prev
          const next = { ...prev }
          delete next[itemId]
          return next
        })
        return
      }
      // CORRECTION (post-Phase-3 verification): the upload boundary can
      // now reject a disallowed type or an oversized file, so a failed
      // upload must surface a Thai message rather than silently doing
      // nothing.
      const err = result.error
      setItemErrors((prev) => ({
        ...prev,
        [itemId]: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      }))
    },
    [setAnswers, assetType, assetId],
  )

  const handleRemoveEvidence = useCallback(
    (itemId: string, attachmentId: string) => {
      setAnswers((prev) => ({
        ...prev,
        [itemId]: {
          ...prev[itemId],
          evidence: prev[itemId].evidence.filter((e) => e.attachment_id !== attachmentId),
        },
      }))
    },
    [setAnswers],
  )

  const items = state.kind === 'ready' ? state.checklist.items : []
  const canSubmit =
    items.length > 0 && items.every((item) => answers[item.item_id]?.result !== null)

  const handleSubmit = useCallback(async () => {
    if (state.kind !== 'ready') return

    const errors: Record<string, string> = {}
    for (const item of state.checklist.items) {
      const answer = answers[item.item_id]
      if (!answer?.result) {
        errors[item.item_id] = 'กรุณาเลือกผลการตรวจ'
        continue
      }
      if (answer.result === 'FAIL') {
        // CORRECTION (post-Phase-3 verification): remark and photo are
        // both per-item, source-data-driven requirements (mirroring the
        // backend's InspectionService.submit_inspection) — neither is a
        // global, unconditional rule.
        const missingRemark = item.required_remark_on_fail && !answer.remark.trim()
        const missingPhoto = item.required_photo_on_fail && answer.evidence.length === 0
        if (missingRemark && missingPhoto) {
          errors[item.item_id] = 'กรุณาระบุหมายเหตุและแนบรูปถ่ายหลักฐานเมื่อผลตรวจไม่ผ่าน'
        } else if (missingRemark) {
          errors[item.item_id] = 'กรุณาระบุหมายเหตุเมื่อผลตรวจไม่ผ่าน'
        } else if (missingPhoto) {
          errors[item.item_id] = 'กรุณาแนบรูปถ่ายหลักฐานเมื่อผลตรวจไม่ผ่าน'
        }
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
      items: state.checklist.items.map((item) => {
        const answer = answers[item.item_id]
        return {
          item_id: item.item_id,
          result: answer.result!,
          remark: answer.remark.trim() ? answer.remark.trim() : null,
          evidence_attachment_ids: answer.evidence.map((e) => e.attachment_id),
        }
      }),
    }

    const result = await apiPost<InspectionDetail>('/inspections', body)
    setSubmitting(false)
    if (result.ok) {
      navigate(`/inspections/${result.data.header.inspection_id}`)
      return
    }
    const err = result.error
    setSubmitError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
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
      <p>{state.checklist.checklist.name}</p>

      {state.checklist.items.map((item) => (
        <ChecklistItemCard
          key={item.item_id}
          item={item}
          answer={answers[item.item_id] ?? { result: null, remark: '', evidence: [] }}
          uploading={uploadingItemId === item.item_id}
          error={itemErrors[item.item_id]}
          onResultChange={(result) => updateAnswer(item.item_id, { result })}
          onRemarkChange={(remark) => updateAnswer(item.item_id, { remark })}
          onAddEvidence={(file) => void handleAddEvidence(item.item_id, file)}
          onRemoveEvidence={(attachmentId) => handleRemoveEvidence(item.item_id, attachmentId)}
        />
      ))}

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
