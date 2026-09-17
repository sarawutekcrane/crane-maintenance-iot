import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import type { VehicleDriverAssignment } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; entries: VehicleDriverAssignment[] }

/**
 * Vehicle<->Driver assignment history (Web/API Phase 6 Batch 1). Every
 * assignment ever created for this vehicle remains listed here, active or
 * ended — nothing is ever deleted from this view.
 */
export function VehicleDriverAssignmentsPage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [formOpen, setFormOpen] = useState(false)
  const [driverId, setDriverId] = useState('')
  const [isPrimary, setIsPrimary] = useState(true)
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [endingId, setEndingId] = useState<string | null>(null)
  const [endError, setEndError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<VehicleDriverAssignment[]>(
      `/vehicles/${vehicleId}/driver-assignments`,
    )
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', entries: result.data })
  }, [vehicleId])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    if (!driverId.trim()) {
      setFormError('กรุณาระบุรหัสคนขับ/ผู้ควบคุม (driver_id)')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPost<VehicleDriverAssignment>(
      `/vehicles/${vehicleId}/driver-assignments`,
      {
        driver_id: driverId.trim(),
        is_primary: isPrimary,
        note_th: note.trim() || null,
      },
    )
    setSubmitting(false)
    if (result.ok) {
      setFormOpen(false)
      setDriverId('')
      setIsPrimary(true)
      setNote('')
      void load()
    } else {
      const err = result.error
      setFormError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  const endAssignment = async (assignmentId: string) => {
    setEndingId(assignmentId)
    setEndError(null)
    const result = await apiPost<VehicleDriverAssignment>(
      `/vehicle-driver-assignments/${assignmentId}/end`,
      {},
    )
    setEndingId(null)
    if (result.ok) {
      void load()
    } else {
      const err = result.error
      setEndError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  return (
    <section className="page">
      <h1>คนขับ/ผู้ควบคุม</h1>
      <p>รหัสยานพาหนะ: {vehicleId}</p>

      <Card>
        <Link to="/drivers" className="button button--secondary button--full-width">
          ดูรายชื่อคนขับ/ผู้ควบคุมทั้งหมด
        </Link>
        <button
          type="button"
          className="button button--primary button--full-width"
          onClick={() => setFormOpen((open) => !open)}
        >
          + มอบหมายคนขับ/ผู้ควบคุม
        </button>
      </Card>

      {formOpen && (
        <Card>
          <h2>มอบหมายคนขับ/ผู้ควบคุม</h2>
          <div className="form-grid">
            <FormField
              label="รหัสคนขับ/ผู้ควบคุม (driver_id)"
              htmlFor="assign-driver-id"
              hint="ค้นหารหัสได้จากรายชื่อคนขับ/ผู้ควบคุมทั้งหมด"
            >
              <input
                id="assign-driver-id"
                type="text"
                value={driverId}
                onChange={(event) => setDriverId(event.target.value)}
                placeholder="เช่น DRV-0001"
              />
            </FormField>
            <FormField label="เป็นผู้ขับ/ผู้ควบคุมหลัก (PRIMARY)" htmlFor="assign-is-primary">
              <input
                id="assign-is-primary"
                type="checkbox"
                checked={isPrimary}
                onChange={(event) => setIsPrimary(event.target.checked)}
              />
            </FormField>
            <FormField label="หมายเหตุ" htmlFor="assign-note">
              <textarea id="assign-note" value={note} onChange={(event) => setNote(event.target.value)} />
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

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติการมอบหมายคนขับ/ผู้ควบคุม..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {endError && (
        <p className="form-field__error" role="alert">
          {endError}
        </p>
      )}

      {state.kind === 'ready' && state.entries.length === 0 && (
        <Card>
          <p>ยังไม่มีประวัติการมอบหมายคนขับ/ผู้ควบคุมสำหรับยานพาหนะนี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.entries.map((entry) => (
          <Card key={entry.assignment_id}>
            <div className="status-card__row">
              <span>รหัสคนขับ/ผู้ควบคุม</span>
              <Link to={`/drivers/${entry.driver_id}`}>{entry.driver_id}</Link>
            </div>
            <div className="status-card__row">
              <span>บทบาท</span>
              <span>{entry.is_primary ? 'ผู้ขับ/ผู้ควบคุมหลัก (PRIMARY)' : 'ไม่ใช่ผู้ขับหลัก'}</span>
            </div>
            <div className="status-card__row">
              <span>เริ่มต้น</span>
              <span>{formatThaiDateTime(entry.start_at)}</span>
            </div>
            <div className="status-card__row">
              <span>สิ้นสุด</span>
              <span>{entry.end_at ? formatThaiDateTime(entry.end_at) : 'ยังคงมอบหมายอยู่'}</span>
            </div>
            {entry.note_th && (
              <div className="status-card__row">
                <span>หมายเหตุ</span>
                <span>{entry.note_th}</span>
              </div>
            )}
            {entry.end_at === null && (
              <button
                type="button"
                className="button button--secondary button--full-width"
                disabled={endingId === entry.assignment_id}
                onClick={() => void endAssignment(entry.assignment_id)}
              >
                {endingId === entry.assignment_id ? 'กำลังบันทึก...' : 'สิ้นสุดการมอบหมาย'}
              </button>
            )}
          </Card>
        ))}
    </section>
  )
}
