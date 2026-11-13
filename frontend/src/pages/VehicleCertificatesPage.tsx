import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { certificateStatusLabel, certificateStatusTone, describeErrorCode, formatThaiDate } from '../lib/labels'
import type { AttachmentInfo, CertificateStatus, VehicleCertificate } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; certificates: VehicleCertificate[] }

const CERTIFICATE_STATUS_OPTIONS: CertificateStatus[] = ['ACTIVE', 'REPLACED', 'EXPIRED']

/** R7-A: the document source types and the one purpose each may carry. */
export type DocumentFileSourceType = 'VEHICLE_CERTIFICATE' | 'MODEL_DOCUMENT'

const DOCUMENT_FILE_PURPOSE: Record<DocumentFileSourceType, string> = {
  VEHICLE_CERTIFICATE: 'VEHICLE_CERTIFICATE_DOCUMENT',
  MODEL_DOCUMENT: 'MODEL_DOCUMENT_FILE',
}

/** Only the server's own authorized download route is ever linked — never a
 * stored `storage_ref` and never any other URL the response might carry. */
const AUTHORIZED_FILE_URL = /^\/api\/v1\/attachments\/[A-Za-z0-9_-]+\/file$/

/** No file picker is rendered at all: attaching a document file has no approved
 * permission policy, and the server refuses it for every actor. */
const DOCUMENT_FILE_ATTACH_UNAVAILABLE = 'ยังไม่เปิดใช้งาน (รอการอนุมัตินโยบายสิทธิ์การแนบไฟล์เอกสาร)'

type FileCheckState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; files: AttachmentInfo[] }

function describeFileCheckError(error: ApiError | Error): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return 'คุณไม่มีสิทธิ์ดูไฟล์ของเอกสารนี้ หรือข้อมูลเอกสารตรวจสอบไม่ผ่าน'
    if (error.status === 404) return 'ไม่พบเอกสารต้นทางของไฟล์นี้'
    return describeErrorCode(error.code)
  }
  return error.message
}

/**
 * R7-A (bounded Mock/TEST): the PDF file bound to one certificate / model
 * document, checked on demand through the authorized list-by-source route
 * (GET only; nothing is loaded until asked, so the page makes no extra call by
 * itself). Shows honestly: a server-verified file (opened only through
 * `/api/v1/attachments/{id}/file`, authorized on the server), no verified file,
 * or a historical `storage_ref` that is unverified text and cannot be opened
 * here. Attaching a file is shown as unavailable and no picker is rendered: no
 * permission policy for attaching a document file is approved yet (the server
 * refuses it for every actor as well).
 */
export function DocumentFilePanel({
  sourceType,
  sourceId,
  hasLegacyRef,
}: {
  sourceType: DocumentFileSourceType
  sourceId: string
  hasLegacyRef: boolean
}) {
  const [check, setCheck] = useState<FileCheckState>({ kind: 'idle' })

  const runCheck = async () => {
    setCheck({ kind: 'loading' })
    const result = await apiGet<AttachmentInfo[]>(
      `/attachments/by-source/${sourceType}/${encodeURIComponent(sourceId)}`,
    )
    if (!result.ok) {
      setCheck({ kind: 'error', message: describeFileCheckError(result.error) })
      return
    }
    const files = (Array.isArray(result.data) ? result.data : []).filter(
      (file) =>
        file.purpose === DOCUMENT_FILE_PURPOSE[sourceType] &&
        file.content_type === 'application/pdf' &&
        AUTHORIZED_FILE_URL.test(file.url),
    )
    setCheck({ kind: 'ready', files })
  }

  return (
    <div className="form-grid" data-testid={`document-file-panel-${sourceId}`}>
      <div className="status-card__row">
        <span>ไฟล์ PDF ในระบบ</span>
        <button
          type="button"
          className="button button--secondary"
          disabled={check.kind === 'loading'}
          onClick={() => void runCheck()}
        >
          {check.kind === 'loading' ? 'กำลังตรวจสอบ...' : 'ตรวจสอบไฟล์ PDF'}
        </button>
      </div>
      {check.kind === 'error' && (
        <p className="form-field__error" role="alert">
          {check.message}
        </p>
      )}
      {check.kind === 'ready' && check.files.length === 0 && <p>ยังไม่มีไฟล์ PDF ที่ตรวจสอบแล้วในระบบ</p>}
      {check.kind === 'ready' &&
        check.files.map((file) => (
          <div className="status-card__row" key={file.attachment_id}>
            <span>{file.filename}</span>
            <a href={file.url} target="_blank" rel="noopener noreferrer">
              เปิดไฟล์ PDF
            </a>
          </div>
        ))}
      {hasLegacyRef && (
        <p>มีข้อมูลอ้างอิงไฟล์เดิม (storage_ref) ซึ่งยังไม่ได้ตรวจสอบว่าเป็นไฟล์ในระบบ จึงเปิดจากหน้านี้ไม่ได้</p>
      )}
      <div className="status-card__row">
        <span>การแนบไฟล์ PDF</span>
        <span>{DOCUMENT_FILE_ATTACH_UNAVAILABLE}</span>
      </div>
    </div>
  )
}

/**
 * Vehicle Certificate create/list/history (Web/API Phase 6 Batch 2A) +
 * renewal (Batch 2B). Every certificate ever created for this vehicle
 * remains listed here — nothing is ever deleted from this view. Renewing
 * an ACTIVE certificate creates a brand new row and marks the old one
 * REPLACED (linked via replaced_by_certificate_id); no manual "mark
 * expired"/"mark replaced" control exists — those transitions are always
 * backend-driven.
 */
export function VehicleCertificatesPage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [formOpen, setFormOpen] = useState(false)
  const [certificateTypeCode, setCertificateTypeCode] = useState('')
  const [certificateTypeNameTh, setCertificateTypeNameTh] = useState('')
  const [documentNo, setDocumentNo] = useState('')
  const [issueDate, setIssueDate] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [alertLeadDays, setAlertLeadDays] = useState('')
  const [certificateStatus, setCertificateStatus] = useState('')
  const [noteTh, setNoteTh] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const [renewingCertificate, setRenewingCertificate] = useState<VehicleCertificate | null>(null)
  const [renewTypeNameTh, setRenewTypeNameTh] = useState('')
  const [renewDocumentNo, setRenewDocumentNo] = useState('')
  const [renewIssueDate, setRenewIssueDate] = useState('')
  const [renewExpiryDate, setRenewExpiryDate] = useState('')
  const [renewAlertLeadDays, setRenewAlertLeadDays] = useState('')
  const [renewStorageRef, setRenewStorageRef] = useState('')
  const [renewNoteTh, setRenewNoteTh] = useState('')
  const [renewSubmitting, setRenewSubmitting] = useState(false)
  const [renewError, setRenewError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<VehicleCertificate[]>(`/vehicles/${vehicleId}/certificates`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', certificates: result.data })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  const resetForm = () => {
    setCertificateTypeCode('')
    setCertificateTypeNameTh('')
    setDocumentNo('')
    setIssueDate('')
    setExpiryDate('')
    setAlertLeadDays('')
    setCertificateStatus('')
    setNoteTh('')
  }

  const submit = async () => {
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<VehicleCertificate>(`/vehicles/${vehicleId}/certificates`, {
      certificate_type_code: certificateTypeCode.trim() || null,
      certificate_type_name_th: certificateTypeNameTh.trim() || null,
      document_no: documentNo.trim() || null,
      issue_date: issueDate || null,
      expiry_date: expiryDate || null,
      alert_lead_days: alertLeadDays.trim() === '' ? null : Number(alertLeadDays),
      certificate_status: certificateStatus || null,
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

  const openRenewForm = (certificate: VehicleCertificate) => {
    setRenewingCertificate(certificate)
    // Pre-fill only certificate_type_name_th / alert_lead_days (the two
    // inherit-if-omitted fields) — everything else starts blank, since
    // document/date/storage/note are never auto-carried forward.
    setRenewTypeNameTh(certificate.certificate_type_name_th ?? '')
    setRenewDocumentNo('')
    setRenewIssueDate('')
    setRenewExpiryDate('')
    setRenewAlertLeadDays(
      certificate.alert_lead_days !== null ? String(certificate.alert_lead_days) : '',
    )
    setRenewStorageRef('')
    setRenewNoteTh('')
    setRenewError(null)
  }

  const closeRenewForm = () => {
    setRenewingCertificate(null)
    setRenewError(null)
  }

  const submitRenew = async () => {
    if (!renewingCertificate) return
    setRenewSubmitting(true)
    setRenewError(null)
    const result = await apiPost<VehicleCertificate>(
      `/certificates/${renewingCertificate.certificate_id}/renew`,
      {
        certificate_type_name_th: renewTypeNameTh.trim() || null,
        document_no: renewDocumentNo.trim() || null,
        issue_date: renewIssueDate || null,
        expiry_date: renewExpiryDate || null,
        alert_lead_days: renewAlertLeadDays.trim() === '' ? null : Number(renewAlertLeadDays),
        storage_ref: renewStorageRef.trim() || null,
        note_th: renewNoteTh.trim() || null,
      },
    )
    setRenewSubmitting(false)
    if (result.ok) {
      setRenewingCertificate(null)
      void load()
    } else {
      const err = result.error
      setRenewError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  return (
    <section className="page">
      <h1>เอกสาร/ใบรับรองยานพาหนะ</h1>
      <p>รหัสยานพาหนะ: {vehicleId}</p>

      <Card>
        <button
          type="button"
          className="button button--primary button--full-width"
          onClick={() => setFormOpen((open) => !open)}
        >
          + เพิ่มเอกสาร/ใบรับรอง
        </button>
      </Card>

      {formOpen && (
        <Card>
          <h2>เพิ่มเอกสาร/ใบรับรอง</h2>
          <div className="form-grid">
            <FormField label="ประเภทเอกสาร (รหัส)" htmlFor="cert-type-code">
              <input
                id="cert-type-code"
                type="text"
                value={certificateTypeCode}
                onChange={(event) => setCertificateTypeCode(event.target.value)}
                placeholder="เช่น INSURANCE"
              />
            </FormField>
            <FormField label="ประเภทเอกสาร (ชื่อภาษาไทย)" htmlFor="cert-type-name">
              <input
                id="cert-type-name"
                type="text"
                value={certificateTypeNameTh}
                onChange={(event) => setCertificateTypeNameTh(event.target.value)}
                placeholder="เช่น ประกันภัย"
              />
            </FormField>
            <FormField label="เลขที่เอกสาร" htmlFor="cert-document-no">
              <input
                id="cert-document-no"
                type="text"
                value={documentNo}
                onChange={(event) => setDocumentNo(event.target.value)}
              />
            </FormField>
            <FormField label="วันที่ออกเอกสาร" htmlFor="cert-issue-date">
              <input
                id="cert-issue-date"
                type="date"
                value={issueDate}
                onChange={(event) => setIssueDate(event.target.value)}
              />
            </FormField>
            <FormField label="วันหมดอายุ" htmlFor="cert-expiry-date">
              <input
                id="cert-expiry-date"
                type="date"
                value={expiryDate}
                onChange={(event) => setExpiryDate(event.target.value)}
              />
            </FormField>
            <FormField
              label="แจ้งเตือนล่วงหน้า (วัน)"
              htmlFor="cert-alert-lead-days"
              hint="เว้นว่างไว้หากไม่ต้องการกำหนดค่า"
            >
              <input
                id="cert-alert-lead-days"
                type="number"
                value={alertLeadDays}
                onChange={(event) => setAlertLeadDays(event.target.value)}
              />
            </FormField>
            <FormField label="สถานะ" htmlFor="cert-status" hint="เว้นว่างไว้หากยังไม่ทราบสถานะ">
              <select
                id="cert-status"
                value={certificateStatus}
                onChange={(event) => setCertificateStatus(event.target.value)}
              >
                <option value="">ไม่ระบุ</option>
                {CERTIFICATE_STATUS_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {certificateStatusLabel[value] ?? value}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField label="หมายเหตุ" htmlFor="cert-note">
              <textarea id="cert-note" value={noteTh} onChange={(event) => setNoteTh(event.target.value)} />
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

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดเอกสาร/ใบรับรอง..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.certificates.length === 0 && (
        <Card>
          <p>ยังไม่มีเอกสาร/ใบรับรองสำหรับยานพาหนะนี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.certificates.map((certificate) => (
          <Card key={certificate.certificate_id}>
            <div className="status-card__row">
              <span>ประเภทเอกสาร</span>
              <span>
                {certificate.certificate_type_name_th ??
                  certificate.certificate_type_code ??
                  'ไม่ระบุ'}
              </span>
            </div>
            <div className="status-card__row">
              <span>เลขที่เอกสาร</span>
              <span>{certificate.document_no ?? 'ไม่มีข้อมูล'}</span>
            </div>
            <div className="status-card__row">
              <span>วันที่ออกเอกสาร</span>
              <span>{certificate.issue_date ? formatThaiDate(certificate.issue_date) : 'ไม่มีข้อมูล'}</span>
            </div>
            <div className="status-card__row">
              <span>วันหมดอายุ</span>
              <span>{certificate.expiry_date ? formatThaiDate(certificate.expiry_date) : 'ไม่มีข้อมูล'}</span>
            </div>
            {certificate.certificate_status && (
              <div className="status-card__row">
                <span>สถานะ</span>
                <StatusBadge
                  label={certificateStatusLabel[certificate.certificate_status] ?? certificate.certificate_status}
                  tone={certificateStatusTone[certificate.certificate_status]}
                />
              </div>
            )}
            {certificate.certificate_status === 'REPLACED' && certificate.replaced_by_certificate_id && (
              <div className="status-card__row">
                <span>ถูกแทนที่โดย</span>
                <span>{certificate.replaced_by_certificate_id}</span>
              </div>
            )}
            {certificate.note_th && (
              <div className="status-card__row">
                <span>หมายเหตุ</span>
                <span>{certificate.note_th}</span>
              </div>
            )}
            <DocumentFilePanel
              sourceType="VEHICLE_CERTIFICATE"
              sourceId={certificate.certificate_id}
              hasLegacyRef={Boolean(certificate.storage_ref)}
            />
            {certificate.certificate_status === 'ACTIVE' && (
              <button
                type="button"
                className="button button--secondary button--full-width"
                onClick={() => openRenewForm(certificate)}
              >
                ต่ออายุ/ออกใหม่
              </button>
            )}

            {renewingCertificate?.certificate_id === certificate.certificate_id && (
              <div className="form-grid">
                <h3>ต่ออายุ/ออกใหม่</h3>
                <FormField label="ประเภทเอกสาร (ชื่อภาษาไทย)" htmlFor="renew-type-name">
                  <input
                    id="renew-type-name"
                    type="text"
                    value={renewTypeNameTh}
                    onChange={(event) => setRenewTypeNameTh(event.target.value)}
                  />
                </FormField>
                <FormField label="เลขที่เอกสารใหม่" htmlFor="renew-document-no">
                  <input
                    id="renew-document-no"
                    type="text"
                    value={renewDocumentNo}
                    onChange={(event) => setRenewDocumentNo(event.target.value)}
                  />
                </FormField>
                <FormField label="วันที่ออกเอกสารใหม่" htmlFor="renew-issue-date">
                  <input
                    id="renew-issue-date"
                    type="date"
                    value={renewIssueDate}
                    onChange={(event) => setRenewIssueDate(event.target.value)}
                  />
                </FormField>
                <FormField label="วันหมดอายุใหม่" htmlFor="renew-expiry-date">
                  <input
                    id="renew-expiry-date"
                    type="date"
                    value={renewExpiryDate}
                    onChange={(event) => setRenewExpiryDate(event.target.value)}
                  />
                </FormField>
                <FormField
                  label="แจ้งเตือนล่วงหน้า (วัน)"
                  htmlFor="renew-alert-lead-days"
                  hint="เว้นว่างไว้หากไม่ต้องการกำหนดค่า"
                >
                  <input
                    id="renew-alert-lead-days"
                    type="number"
                    value={renewAlertLeadDays}
                    onChange={(event) => setRenewAlertLeadDays(event.target.value)}
                  />
                </FormField>
                <FormField label="ไฟล์แนบใหม่ (storage_ref)" htmlFor="renew-storage-ref">
                  <input
                    id="renew-storage-ref"
                    type="text"
                    value={renewStorageRef}
                    onChange={(event) => setRenewStorageRef(event.target.value)}
                  />
                </FormField>
                <FormField label="หมายเหตุ" htmlFor="renew-note">
                  <textarea
                    id="renew-note"
                    value={renewNoteTh}
                    onChange={(event) => setRenewNoteTh(event.target.value)}
                  />
                </FormField>
                {renewError && (
                  <p className="form-field__error" role="alert">
                    {renewError}
                  </p>
                )}
                <button
                  type="button"
                  className="button button--secondary button--full-width"
                  onClick={closeRenewForm}
                  disabled={renewSubmitting}
                >
                  ยกเลิก
                </button>
                <button
                  type="button"
                  className="button button--primary button--full-width"
                  disabled={renewSubmitting}
                  onClick={() => void submitRenew()}
                >
                  {renewSubmitting ? 'กำลังบันทึก...' : 'ยืนยันต่ออายุ/ออกใหม่'}
                </button>
              </div>
            )}
          </Card>
        ))}
    </section>
  )
}
