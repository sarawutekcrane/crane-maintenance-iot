import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { certificateStatusLabel, certificateStatusTone, describeErrorCode, formatThaiDate } from '../lib/labels'
import type { CertificateStatus, VehicleCertificate } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; certificates: VehicleCertificate[] }

const CERTIFICATE_STATUS_OPTIONS: CertificateStatus[] = ['ACTIVE', 'REPLACED', 'EXPIRED']

/**
 * Vehicle Certificate create/list/history (Web/API Phase 6 Batch 2A).
 * Every certificate ever created for this vehicle remains listed here —
 * nothing is ever deleted from this view. Renewal/replacement (marking a
 * certificate REPLACED and linking to its successor) is NOT part of this
 * batch — deferred to Batch 2B; no such control exists on this page.
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
            {certificate.note_th && (
              <div className="status-card__row">
                <span>หมายเหตุ</span>
                <span>{certificate.note_th}</span>
              </div>
            )}
          </Card>
        ))}
    </section>
  )
}
