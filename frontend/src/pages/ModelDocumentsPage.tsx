import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { describeErrorCode, formatThaiDate } from '../lib/labels'
import type { ModelDocument } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; documents: ModelDocument[] }

/** The three-way inherit/set/clear semantics locked for `document_name_th`
 * and `active_status` on revision (Web/API Phase 6 Batch 3B, Locked Rules
 * 3/7): "inherit" omits the JSON key entirely, "set" sends the exact
 * entered string, "clear" sends explicit JSON `null`. There is no
 * combined "inherit-or-clear" option. */
type InheritFieldMode = 'inherit' | 'set' | 'clear'

function cardAnchorId(modelDocumentId: string): string {
  return `model-document-${modelDocumentId}`
}

/**
 * Model Document create/list/history (Web/API Phase 6 Batch 3A) + revision
 * (Batch 3B). Model documents (Load Chart / Operation Manual / Service
 * Manual, etc.) are model-level data — every vehicle sharing this model_id
 * sees the exact same records here, never duplicated per vehicle. Every
 * document ever created for this model remains listed — nothing is ever
 * deleted or hidden from this view, and a revision never edits a document
 * in place: it always creates a brand-new row and links the source to it
 * via `replaced_by_document_id` (POST `/model-documents/{id}/revise`).
 * Only one revision form is open at a time (per source document), fully
 * independent from the create-document form above. A source document can
 * only start a revision when it has an `effective_from` and is not
 * already replaced; both cases render an explanatory message instead of
 * the action. `document_type`/`version`/`file_status`/`active_status` have
 * no approved vocabulary, so they are always rendered as plain text, never
 * a colored status badge (which would visually imply a known/fixed set of
 * values).
 */
export function ModelDocumentsPage() {
  const { modelId = '' } = useParams<{ modelId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [formOpen, setFormOpen] = useState(false)
  const [documentType, setDocumentType] = useState('')
  const [documentNameTh, setDocumentNameTh] = useState('')
  const [version, setVersion] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [effectiveTo, setEffectiveTo] = useState('')
  const [storageRef, setStorageRef] = useState('')
  const [fileStatus, setFileStatus] = useState('')
  const [activeStatus, setActiveStatus] = useState('')
  const [noteTh, setNoteTh] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // ---- Revision form (Batch 3B) — one active source document at a time.
  const [revisingDocumentId, setRevisingDocumentId] = useState<string | null>(null)
  const [reviseVersion, setReviseVersion] = useState('')
  const [reviseEffectiveFrom, setReviseEffectiveFrom] = useState('')
  const [reviseNameMode, setReviseNameMode] = useState<InheritFieldMode>('inherit')
  const [reviseNameValue, setReviseNameValue] = useState('')
  const [reviseActiveStatusMode, setReviseActiveStatusMode] = useState<InheritFieldMode>('inherit')
  const [reviseActiveStatusValue, setReviseActiveStatusValue] = useState('')
  const [reviseStorageRef, setReviseStorageRef] = useState('')
  const [reviseFileStatus, setReviseFileStatus] = useState('')
  const [reviseNoteTh, setReviseNoteTh] = useState('')
  // The source model_document_id with an in-flight revise POST, or null.
  // This is intentionally page-wide (not per-card): while it is non-null,
  // every "สร้างเอกสารฉบับปรับปรุง" open action (on ANY document, not just
  // the one being submitted), the cancel action, and a second submit are
  // all blocked — a pending request's own document/form context can never
  // change out from under it before the response arrives.
  const [revisePendingId, setRevisePendingId] = useState<string | null>(null)
  // Client-side input validation (blank required field, blank "set" value).
  const [reviseFieldError, setReviseFieldError] = useState<string | null>(null)
  // Backend-confirmed rejection (validation/conflict) — inputs preserved.
  const [reviseServerError, setReviseServerError] = useState<string | null>(null)
  // Network/timeout/ambiguous-server failure — outcome unknown, never
  // "nothing was saved"; inputs preserved and a GET-only history refresh
  // is offered.
  const [reviseUncertain, setReviseUncertain] = useState(false)

  // Both refs below exist to answer "is this in-flight response still
  // relevant?" AFTER an `await`, using values read fresh at resolution
  // time rather than values captured in the async closure at call time
  // (which — since React re-renders create a brand new `submitRevise`
  // closure every time, and the one actually invoked is whichever closure
  // was current when the button was clicked — would otherwise always
  // reflect the OLD pre-await state/props, never a live "did anything
  // change while we were waiting?" answer).
  //
  // requestTokenRef: bumped once per submitRevise call; a resolved
  // response only applies if it is still the most recent request (this
  // project's own React Router setup does not remount ModelDocumentsPage
  // on a modelId-only navigation — see modelIdRef below — so without this,
  // a superseded request could still theoretically land after a fresher
  // one due to network reordering).
  const requestTokenRef = useRef(0)
  // modelIdRef: because `/models/:modelId/documents` reuses the same
  // mounted ModelDocumentsPage instance across a modelId-only navigation
  // (React Router does not remount on a param-only change), a revise POST
  // issued for one model_id could still resolve after the user has
  // navigated to a different model's documents page in the same tab. Its
  // stale closure's own `load()` is bound to the OLD modelId (via
  // useCallback's `[modelId]` dependency) and must never be allowed to
  // fetch/overwrite the NEW model's now-displayed list.
  const modelIdRef = useRef(modelId)
  useEffect(() => {
    modelIdRef.current = modelId
  }, [modelId])

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<ModelDocument[]>(`/models/${modelId}/documents`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', documents: result.data })
  }, [modelId])

  useEffect(() => {
    void load()
  }, [load])

  const resetForm = () => {
    setDocumentType('')
    setDocumentNameTh('')
    setVersion('')
    setEffectiveFrom('')
    setEffectiveTo('')
    setStorageRef('')
    setFileStatus('')
    setActiveStatus('')
    setNoteTh('')
  }

  const submit = async () => {
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<ModelDocument>(`/models/${modelId}/documents`, {
      document_type: documentType.trim() || null,
      document_name_th: documentNameTh.trim() || null,
      version: version.trim() || null,
      effective_from: effectiveFrom || null,
      effective_to: effectiveTo || null,
      storage_ref: storageRef.trim() || null,
      file_status: fileStatus.trim() || null,
      active_status: activeStatus.trim() || null,
      note_th: noteTh.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      setFormOpen(false)
      resetForm()
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  const closeReviseForm = () => {
    // Guard against the cancel button somehow firing while a revise POST
    // is in flight (the button is also `disabled` for this same reason —
    // this is defense in depth, not the only protection).
    if (revisePendingId !== null) return
    setRevisingDocumentId(null)
    setReviseVersion('')
    setReviseEffectiveFrom('')
    setReviseNameMode('inherit')
    setReviseNameValue('')
    setReviseActiveStatusMode('inherit')
    setReviseActiveStatusValue('')
    setReviseStorageRef('')
    setReviseFileStatus('')
    setReviseNoteTh('')
    setReviseFieldError(null)
    setReviseServerError(null)
    setReviseUncertain(false)
  }

  const openReviseForm = (document: ModelDocument) => {
    // Never allow switching to (or re-opening) a form while a revise POST
    // for another document is in flight — the "สร้างเอกสารฉบับปรับปรุง"
    // buttons are also `disabled` for this same reason; this is defense
    // in depth. This is what actually prevents document B's form from
    // ever opening while document A's request is pending, so a stale
    // response for A can never land on a form that has moved on to B.
    if (revisePendingId !== null) return
    // Switching to a different source document — or opening the form for
    // the first time — always starts from a fully blank slate. Nothing
    // from a previously-open revision form (values or errors) carries
    // over, and this is entirely independent of the create-document form.
    setRevisingDocumentId(document.model_document_id)
    setReviseVersion('')
    setReviseEffectiveFrom('')
    setReviseNameMode('inherit')
    setReviseNameValue('')
    setReviseActiveStatusMode('inherit')
    setReviseActiveStatusValue('')
    // storage_ref/file_status/note_th are NEVER inherited — always start
    // blank, never pre-filled from the source document.
    setReviseStorageRef('')
    setReviseFileStatus('')
    setReviseNoteTh('')
    setReviseFieldError(null)
    setReviseServerError(null)
    setReviseUncertain(false)
  }

  const submitRevise = async (source: ModelDocument) => {
    // Defense in depth alongside the button's own `disabled` attribute —
    // never start a second concurrent revise request.
    if (revisePendingId !== null) return
    if (revisingDocumentId !== source.model_document_id) return

    // Client-side checks catch obvious mistakes early; the backend remains
    // authoritative for effective_from/version validation (Locked Rules
    // 2/6) — these never invent or normalize a value on success.
    if (!reviseVersion.trim()) {
      setReviseFieldError('กรุณากรอกเวอร์ชัน/ฉบับที่ของเอกสารฉบับใหม่')
      return
    }
    if (reviseVersion === source.version) {
      setReviseFieldError('เวอร์ชัน/ฉบับที่ใหม่ต้องไม่ซ้ำกับเวอร์ชันเดิมของเอกสารต้นทาง')
      return
    }
    if (!reviseEffectiveFrom) {
      setReviseFieldError('กรุณาระบุวันที่เริ่มมีผลใช้ของเอกสารฉบับใหม่')
      return
    }
    if (source.effective_from && reviseEffectiveFrom <= source.effective_from) {
      setReviseFieldError('วันที่เริ่มมีผลใช้ของฉบับใหม่ต้องอยู่หลังวันที่เริ่มมีผลใช้ของเอกสารต้นทาง')
      return
    }
    if (reviseNameMode === 'set' && !reviseNameValue.trim()) {
      setReviseFieldError('กรุณากรอกชื่อเอกสารใหม่ หรือเลือก "คงค่าเดิม" / "ล้างค่า" แทน')
      return
    }
    if (reviseActiveStatusMode === 'set' && !reviseActiveStatusValue.trim()) {
      setReviseFieldError('กรุณากรอกสถานะการใช้งานใหม่ หรือเลือก "คงค่าเดิม" / "ล้างค่า" แทน')
      return
    }

    setReviseFieldError(null)
    setReviseServerError(null)
    setReviseUncertain(false)

    // Captured now (from the current render's live values), before the
    // request starts — used after the `await` to detect whether the page
    // has moved on in the meantime. See requestTokenRef/modelIdRef above
    // for why this must be a ref comparison, not a re-read of a variable
    // from this same (necessarily stale-after-await) closure.
    const requestModelId = modelId
    const token = ++requestTokenRef.current
    setRevisePendingId(source.model_document_id)

    // Exactly the seven allowed keys — never model_document_id, model_id,
    // document_type, effective_to, or replaced_by_document_id (frozen
    // contract, Batch 3B). Omission vs. explicit null vs. exact string is
    // built key-by-key here since a single typed object cannot express
    // "omit this key" as a value.
    const payload: Record<string, unknown> = {
      version: reviseVersion,
      effective_from: reviseEffectiveFrom,
    }
    if (reviseNameMode === 'set') payload.document_name_th = reviseNameValue
    else if (reviseNameMode === 'clear') payload.document_name_th = null
    if (reviseActiveStatusMode === 'set') payload.active_status = reviseActiveStatusValue
    else if (reviseActiveStatusMode === 'clear') payload.active_status = null
    // storage_ref/file_status/note_th are never inherited: an untouched
    // blank input is simply omitted; a non-blank input is sent unchanged,
    // including its exact spacing (never trimmed).
    if (reviseStorageRef.trim() !== '') payload.storage_ref = reviseStorageRef
    if (reviseFileStatus.trim() !== '') payload.file_status = reviseFileStatus
    if (reviseNoteTh.trim() !== '') payload.note_th = reviseNoteTh

    const result = await apiPost<ModelDocument>(
      `/model-documents/${source.model_document_id}/revise`,
      payload,
    )

    // The page has moved on (a newer request superseded this one, or —
    // since this route does not remount on a modelId-only navigation —
    // the user navigated to a different model's documents page while this
    // request was in flight). Drop the response entirely: never call the
    // stale `load()` (it is bound to the OLD modelId and would fetch/
    // overwrite the wrong model's list), never touch the form or error
    // state of whatever is now on screen. Still clear the pending flag —
    // it is page-wide, and leaving it set would permanently block every
    // revise action on the new context.
    if (requestTokenRef.current !== token || modelIdRef.current !== requestModelId) {
      setRevisePendingId(null)
      return
    }

    setRevisePendingId(null)

    if (result.ok) {
      closeReviseForm()
      // Authoritative refresh — the old and new records and their
      // replaced_by_document_id linkage come from the backend's own list,
      // never fabricated locally.
      void load()
      return
    }

    const err = result.error
    // Only a definite, sub-500 ApiError (an explicit domain/validation
    // rejection the backend fully processed and reported) is treated as
    // known-and-final. A 5xx ApiError (the request reached the backend,
    // but the backend itself failed or errored while handling it — the
    // response body happening to parse as the error envelope shape
    // doesn't mean the failure is any less ambiguous about what was
    // actually written) is treated the same as a network/timeout/
    // malformed-response failure below.
    if (err instanceof ApiError && err.status < 500) {
      // Explicit validation/conflict rejection — inputs are preserved.
      setReviseServerError(describeErrorCode(err.code))
    } else {
      // Network/timeout failure, OR a 5xx (server-side) failure, OR a
      // non-envelope malformed response: in every one of these cases the
      // request may or may not have been applied server-side. Never claim
      // "nothing was saved" and never imply the failure was specifically
      // a timeout (a 5xx or a connection-refused are not "the request
      // took too long," but they are exactly as ambiguous as one is about
      // whether a write happened) — inputs stay untouched and a GET-only
      // refresh is offered so the user can inspect current history before
      // deciding whether to retry. Refreshing does not by itself prove an
      // orphan row (a new document created by WRITE 1 with no successful
      // WRITE 2 linking the source to it) was avoided or reconciled.
      setReviseUncertain(true)
      setReviseServerError(
        'ไม่สามารถยืนยันผลการบันทึกได้ (เกิดปัญหาการเชื่อมต่อหรือเซิร์ฟเวอร์ขัดข้อง) ระบบอาจบันทึกฉบับใหม่ไว้แล้วหรือยังไม่ได้บันทึกก็ได้ กรุณากด "รีเฟรชประวัติ" ด้านล่างเพื่อตรวจสอบสถานะล่าสุดก่อนตัดสินใจส่งใหม่อีกครั้ง',
      )
    }
  }

  const documents = state.kind === 'ready' ? state.documents : []
  const findDocument = (id: string) => documents.find((d) => d.model_document_id === id)

  return (
    <section className="page">
      <h1>เอกสารประจำรุ่นเครื่องจักร</h1>
      <p>รหัสรุ่นเครื่องจักร: {modelId}</p>

      <Card>
        <button
          type="button"
          className="button button--primary button--full-width"
          onClick={() => setFormOpen((open) => !open)}
        >
          + เพิ่มเอกสาร
        </button>
      </Card>

      {formOpen && (
        <Card>
          <h2>เพิ่มเอกสาร</h2>
          <div className="form-grid">
            <FormField label="ประเภทเอกสาร" htmlFor="doc-type">
              <input
                id="doc-type"
                type="text"
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value)}
                placeholder="เช่น Load Chart, Operation Manual, Service Manual"
              />
            </FormField>
            <FormField label="ชื่อเอกสาร (ภาษาไทย)" htmlFor="doc-name">
              <input
                id="doc-name"
                type="text"
                value={documentNameTh}
                onChange={(event) => setDocumentNameTh(event.target.value)}
              />
            </FormField>
            <FormField label="เวอร์ชัน/ฉบับที่" htmlFor="doc-version">
              <input
                id="doc-version"
                type="text"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                placeholder="เช่น 1.0, Rev.A"
              />
            </FormField>
            <FormField label="มีผลใช้ตั้งแต่วันที่" htmlFor="doc-effective-from">
              <input
                id="doc-effective-from"
                type="date"
                value={effectiveFrom}
                onChange={(event) => setEffectiveFrom(event.target.value)}
              />
            </FormField>
            <FormField label="มีผลใช้ถึงวันที่" htmlFor="doc-effective-to">
              <input
                id="doc-effective-to"
                type="date"
                value={effectiveTo}
                onChange={(event) => setEffectiveTo(event.target.value)}
              />
            </FormField>
            <FormField label="ไฟล์แนบ (storage_ref)" htmlFor="doc-storage-ref">
              <input
                id="doc-storage-ref"
                type="text"
                value={storageRef}
                onChange={(event) => setStorageRef(event.target.value)}
              />
            </FormField>
            <FormField label="สถานะไฟล์" htmlFor="doc-file-status" hint="เว้นว่างไว้หากยังไม่ทราบสถานะ">
              <input
                id="doc-file-status"
                type="text"
                value={fileStatus}
                onChange={(event) => setFileStatus(event.target.value)}
              />
            </FormField>
            <FormField label="สถานะการใช้งาน" htmlFor="doc-active-status" hint="เว้นว่างไว้หากยังไม่ทราบสถานะ">
              <input
                id="doc-active-status"
                type="text"
                value={activeStatus}
                onChange={(event) => setActiveStatus(event.target.value)}
              />
            </FormField>
            <FormField label="หมายเหตุ" htmlFor="doc-note">
              <textarea id="doc-note" value={noteTh} onChange={(event) => setNoteTh(event.target.value)} />
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
              onClick={() => void submit()}
            >
              {submitting ? 'กำลังบันทึก...' : 'บันทึก'}
            </button>
          </div>
        </Card>
      )}

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดเอกสารประจำรุ่นเครื่องจักร..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.documents.length === 0 && (
        <Card>
          <p>ยังไม่มีเอกสารสำหรับรุ่นเครื่องจักรนี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.documents.map((document) => {
          const isRevising = revisingDocumentId === document.model_document_id
          const successor = document.replaced_by_document_id
            ? findDocument(document.replaced_by_document_id)
            : undefined

          return (
            <div id={cardAnchorId(document.model_document_id)} key={document.model_document_id}>
              <Card>
                <div className="status-card__row">
                  <span>รหัสเอกสาร</span>
                  <span>{document.model_document_id}</span>
                </div>
                <div className="status-card__row">
                  <span>ประเภทเอกสาร</span>
                  <span>{document.document_type ?? 'ไม่ระบุ'}</span>
                </div>
                <div className="status-card__row">
                  <span>ชื่อเอกสาร</span>
                  <span>{document.document_name_th ?? 'ไม่มีข้อมูล'}</span>
                </div>
                <div className="status-card__row">
                  <span>เวอร์ชัน/ฉบับที่</span>
                  <span>{document.version ?? 'ไม่มีข้อมูล'}</span>
                </div>
                <div className="status-card__row">
                  <span>มีผลใช้ตั้งแต่วันที่</span>
                  <span>
                    {document.effective_from ? formatThaiDate(document.effective_from) : 'ไม่มีข้อมูล'}
                  </span>
                </div>
                <div className="status-card__row">
                  <span>มีผลใช้ถึงวันที่</span>
                  <span>{document.effective_to ? formatThaiDate(document.effective_to) : 'ไม่มีข้อมูล'}</span>
                </div>
                <div className="status-card__row">
                  <span>ไฟล์แนบ</span>
                  <span>{document.storage_ref ?? 'ไม่มีข้อมูล'}</span>
                </div>
                <div className="status-card__row">
                  <span>สถานะไฟล์</span>
                  <span>{document.file_status ?? 'ไม่ระบุ'}</span>
                </div>
                <div className="status-card__row">
                  <span>สถานะการใช้งาน</span>
                  <span>{document.active_status ?? 'ไม่ระบุ'}</span>
                </div>
                {document.note_th && (
                  <div className="status-card__row">
                    <span>หมายเหตุ</span>
                    <span>{document.note_th}</span>
                  </div>
                )}

                {document.replaced_by_document_id && (
                  <div className="status-card__row">
                    <span>ถูกแทนที่ด้วยฉบับปรับปรุง</span>
                    <span>
                      {successor ? (
                        <a href={`#${cardAnchorId(document.replaced_by_document_id)}`}>
                          {document.replaced_by_document_id}
                        </a>
                      ) : (
                        document.replaced_by_document_id
                      )}
                    </span>
                  </div>
                )}

                {!document.replaced_by_document_id && document.effective_from === null && (
                  <p className="form-field__hint">
                    เอกสารนี้ยังไม่มีวันที่เริ่มมีผลใช้ จึงยังไม่สามารถสร้างฉบับปรับปรุงได้
                  </p>
                )}

                {!document.replaced_by_document_id && document.effective_from !== null && !isRevising && (
                  <button
                    type="button"
                    className="button button--secondary button--full-width"
                    disabled={revisePendingId !== null}
                    onClick={() => openReviseForm(document)}
                  >
                    สร้างเอกสารฉบับปรับปรุง
                  </button>
                )}

                {isRevising && (
                  <div className="form-grid">
                    <h3>สร้างเอกสารฉบับปรับปรุง</h3>
                    <p>
                      จากเอกสารต้นทาง: {document.document_name_th ?? document.document_type ?? 'ไม่ระบุชื่อ'}{' '}
                      (เวอร์ชันเดิม {document.version ?? 'ไม่มีข้อมูล'}, รหัส {document.model_document_id})
                    </p>
                    <p className="form-field__hint">
                      การสร้างฉบับปรับปรุงจะสร้างเอกสารใหม่แยกต่างหาก ไม่ใช่การแก้ไขประวัติเดิม
                    </p>

                    <FormField label="เวอร์ชัน/ฉบับที่ใหม่" htmlFor="revise-version">
                      <input
                        id="revise-version"
                        type="text"
                        maxLength={100}
                        value={reviseVersion}
                        onChange={(event) => setReviseVersion(event.target.value)}
                        placeholder="ต้องไม่ซ้ำกับเวอร์ชันเดิม"
                      />
                    </FormField>
                    <FormField
                      label="วันที่เริ่มมีผลใช้ฉบับใหม่"
                      htmlFor="revise-effective-from"
                      hint={
                        document.effective_from
                          ? `ต้องอยู่หลังวันที่ ${formatThaiDate(document.effective_from)}`
                          : undefined
                      }
                    >
                      <input
                        id="revise-effective-from"
                        type="date"
                        value={reviseEffectiveFrom}
                        onChange={(event) => setReviseEffectiveFrom(event.target.value)}
                      />
                    </FormField>

                    <FormField label="ชื่อเอกสาร (ภาษาไทย)" htmlFor="revise-name-mode">
                      <select
                        id="revise-name-mode"
                        value={reviseNameMode}
                        onChange={(event) => setReviseNameMode(event.target.value as InheritFieldMode)}
                      >
                        <option value="inherit">คงค่าเดิมจากเอกสารต้นทาง</option>
                        <option value="set">ระบุชื่อใหม่</option>
                        <option value="clear">ล้างค่า (ไม่ระบุ)</option>
                      </select>
                    </FormField>
                    {reviseNameMode === 'set' && (
                      <FormField label="ชื่อเอกสารใหม่" htmlFor="revise-name-value">
                        <input
                          id="revise-name-value"
                          type="text"
                          maxLength={200}
                          value={reviseNameValue}
                          onChange={(event) => setReviseNameValue(event.target.value)}
                        />
                      </FormField>
                    )}

                    <FormField label="สถานะการใช้งาน" htmlFor="revise-active-status-mode">
                      <select
                        id="revise-active-status-mode"
                        value={reviseActiveStatusMode}
                        onChange={(event) =>
                          setReviseActiveStatusMode(event.target.value as InheritFieldMode)
                        }
                      >
                        <option value="inherit">คงค่าเดิมจากเอกสารต้นทาง</option>
                        <option value="set">ระบุสถานะใหม่</option>
                        <option value="clear">ล้างค่า (ไม่ระบุ)</option>
                      </select>
                    </FormField>
                    {reviseActiveStatusMode === 'set' && (
                      <FormField label="สถานะการใช้งานใหม่" htmlFor="revise-active-status-value">
                        <input
                          id="revise-active-status-value"
                          type="text"
                          maxLength={50}
                          value={reviseActiveStatusValue}
                          onChange={(event) => setReviseActiveStatusValue(event.target.value)}
                        />
                      </FormField>
                    )}

                    <FormField
                      label="ไฟล์แนบใหม่ (storage_ref)"
                      htmlFor="revise-storage-ref"
                      hint="ไม่คงค่าเดิม — เว้นว่างไว้หากยังไม่มีไฟล์แนบใหม่"
                    >
                      <input
                        id="revise-storage-ref"
                        type="text"
                        maxLength={500}
                        value={reviseStorageRef}
                        onChange={(event) => setReviseStorageRef(event.target.value)}
                      />
                    </FormField>
                    <FormField
                      label="สถานะไฟล์ใหม่"
                      htmlFor="revise-file-status"
                      hint="ไม่คงค่าเดิม — เว้นว่างไว้หากยังไม่ทราบสถานะ"
                    >
                      <input
                        id="revise-file-status"
                        type="text"
                        maxLength={50}
                        value={reviseFileStatus}
                        onChange={(event) => setReviseFileStatus(event.target.value)}
                      />
                    </FormField>
                    <FormField
                      label="หมายเหตุใหม่"
                      htmlFor="revise-note"
                      hint="ไม่คงค่าเดิม — เว้นว่างไว้หากไม่มีหมายเหตุใหม่"
                    >
                      <textarea
                        id="revise-note"
                        maxLength={500}
                        value={reviseNoteTh}
                        onChange={(event) => setReviseNoteTh(event.target.value)}
                      />
                    </FormField>

                    {reviseFieldError && (
                      <p className="form-field__error" role="alert">
                        {reviseFieldError}
                      </p>
                    )}
                    {reviseServerError && (
                      <p className="form-field__error" role="alert">
                        {reviseServerError}
                      </p>
                    )}
                    {reviseUncertain && (
                      <button
                        type="button"
                        className="button button--secondary button--full-width"
                        onClick={() => void load()}
                      >
                        รีเฟรชประวัติ
                      </button>
                    )}

                    <button
                      type="button"
                      className="button button--secondary button--full-width"
                      onClick={closeReviseForm}
                      disabled={revisePendingId !== null}
                    >
                      ยกเลิก
                    </button>
                    <button
                      type="button"
                      className="button button--primary button--full-width"
                      disabled={revisePendingId !== null}
                      onClick={() => void submitRevise(document)}
                    >
                      {revisePendingId === document.model_document_id
                        ? 'กำลังบันทึก...'
                        : 'ยืนยันสร้างฉบับปรับปรุง'}
                    </button>
                  </div>
                )}
              </Card>
            </div>
          )
        })}
    </section>
  )
}
