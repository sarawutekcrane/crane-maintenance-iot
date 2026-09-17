import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPatch } from '../lib/apiClient'
import { describeErrorCode, formatThaiDate } from '../lib/labels'
import type { Driver } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; driver: Driver }

export function DriverDetailPage() {
  const { driverId = '' } = useParams<{ driverId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    driver_name_th: '',
    phone: '',
    license_no: '',
    license_expiry_date: '',
    active_status: '',
    note_th: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Driver>(`/drivers/${driverId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', driver: result.data })
  }, [driverId])

  useEffect(() => {
    void load()
  }, [load])

  const startEditing = (driver: Driver) => {
    setForm({
      driver_name_th: driver.driver_name_th,
      phone: driver.phone ?? '',
      license_no: driver.license_no ?? '',
      license_expiry_date: driver.license_expiry_date ?? '',
      active_status: driver.active_status ?? '',
      note_th: driver.note_th ?? '',
    })
    setFormError(null)
    setEditing(true)
  }

  const submit = async () => {
    if (!form.driver_name_th.trim()) {
      setFormError('กรุณาระบุชื่อพนักงานขับ/ผู้ควบคุม')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPatch<Driver>(`/drivers/${driverId}`, {
      driver_name_th: form.driver_name_th.trim(),
      phone: form.phone.trim() || null,
      license_no: form.license_no.trim() || null,
      license_expiry_date: form.license_expiry_date || null,
      active_status: form.active_status.trim() || null,
      note_th: form.note_th.trim() || null,
    })
    setSubmitting(false)
    if (result.ok) {
      setEditing(false)
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลคนขับ/ผู้ควบคุม..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายละเอียดคนขับ/ผู้ควบคุม</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { driver } = state

  return (
    <section className="page">
      <h1>{driver.driver_name_th}</h1>
      <p>รหัสคนขับ/ผู้ควบคุม: {driver.driver_id}</p>

      <Card>
        {!editing && (
          <>
            <div className="status-card__row">
              <span>เบอร์โทร</span>
              <span>{driver.phone ?? 'ไม่มีข้อมูล'}</span>
            </div>
            <div className="status-card__row">
              <span>เลขใบขับขี่ (License No.)</span>
              <span>{driver.license_no ?? 'ไม่มีข้อมูล'}</span>
            </div>
            <div className="status-card__row">
              <span>วันหมดอายุใบขับขี่</span>
              <span>
                {driver.license_expiry_date ? formatThaiDate(driver.license_expiry_date) : 'ไม่มีข้อมูล'}
              </span>
            </div>
            <div className="status-card__row">
              <span>สถานะ (active_status)</span>
              <span>{driver.active_status ?? 'ไม่มีข้อมูล'}</span>
            </div>
            <div className="status-card__row">
              <span>หมายเหตุ</span>
              <span>{driver.note_th ?? 'ไม่มีข้อมูล'}</span>
            </div>
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={() => startEditing(driver)}
            >
              แก้ไขข้อมูล
            </button>
          </>
        )}

        {editing && (
          <div className="form-grid">
            <FormField label="ชื่อ" htmlFor="driver-edit-name">
              <input
                id="driver-edit-name"
                type="text"
                value={form.driver_name_th}
                onChange={(event) => setForm({ ...form, driver_name_th: event.target.value })}
              />
            </FormField>
            <FormField label="เบอร์โทร" htmlFor="driver-edit-phone">
              <input
                id="driver-edit-phone"
                type="text"
                value={form.phone}
                onChange={(event) => setForm({ ...form, phone: event.target.value })}
              />
            </FormField>
            <FormField label="เลขใบขับขี่ (License No.)" htmlFor="driver-edit-license-no">
              <input
                id="driver-edit-license-no"
                type="text"
                value={form.license_no}
                onChange={(event) => setForm({ ...form, license_no: event.target.value })}
              />
            </FormField>
            <FormField label="วันหมดอายุใบขับขี่" htmlFor="driver-edit-license-expiry">
              <input
                id="driver-edit-license-expiry"
                type="date"
                value={form.license_expiry_date}
                onChange={(event) => setForm({ ...form, license_expiry_date: event.target.value })}
              />
            </FormField>
            <FormField
              label="สถานะ (active_status)"
              htmlFor="driver-edit-active-status"
              hint="ยังไม่มีคำศัพท์สถานะที่ได้รับการอนุมัติจากบริษัท กรอกได้อย่างอิสระหรือเว้นว่างไว้"
            >
              <input
                id="driver-edit-active-status"
                type="text"
                value={form.active_status}
                onChange={(event) => setForm({ ...form, active_status: event.target.value })}
              />
            </FormField>
            <FormField label="หมายเหตุ" htmlFor="driver-edit-note">
              <textarea
                id="driver-edit-note"
                value={form.note_th}
                onChange={(event) => setForm({ ...form, note_th: event.target.value })}
              />
            </FormField>
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <div>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setEditing(false)}
                disabled={submitting}
              >
                ยกเลิก
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void submit()}
                disabled={submitting}
              >
                {submitting ? 'กำลังบันทึก...' : 'บันทึก'}
              </button>
            </div>
          </div>
        )}
      </Card>
    </section>
  )
}
