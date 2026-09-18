import { useCallback, useEffect, useState } from 'react'
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

/**
 * Model Document create/list/history (Web/API Phase 6 Batch 3A). Model
 * documents (Load Chart / Operation Manual / Service Manual, etc.) are
 * model-level data — every vehicle sharing this model_id sees the exact
 * same records here, never duplicated per vehicle. Every document ever
 * created for this model remains listed — nothing is ever deleted from
 * this view. Revision/replacement (marking a document REPLACED and
 * linking to its successor) is NOT part of this batch — deferred to
 * Batch 3B; no such control exists on this page. `document_type`/
 * `version`/`file_status`/`active_status` have no approved vocabulary,
 * so they are always rendered as plain text, never a colored status
 * badge (which would visually imply a known/fixed set of values).
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
        state.documents.map((document) => (
          <Card key={document.model_document_id}>
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
          </Card>
        ))}
    </section>
  )
}
