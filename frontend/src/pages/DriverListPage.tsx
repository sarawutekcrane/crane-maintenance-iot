import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, formatThaiDate } from '../lib/labels'
import type { Driver, Page } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; drivers: Driver[] }

/**
 * Driver / Operator master catalog (Web/API Phase 6 Batch 1). `active_status`
 * is intentionally never rendered as a colored/known badge here — no
 * approved vocabulary for it exists yet (see app.domain.driver docstring),
 * so it is shown as plain text exactly as stored.
 */
export function DriverListPage() {
  const [q, setQ] = useState('')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async (query: string) => {
    setState({ kind: 'loading' })
    const params = new URLSearchParams({ page_size: '50' })
    if (query.trim()) params.set('q', query.trim())

    const result = await apiGet<Page<Driver>>(`/drivers?${params.toString()}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', drivers: result.data.items })
  }, [])

  useEffect(() => {
    void load(q)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="page">
      <h1>คนขับ/ผู้ควบคุม (Driver/Operator)</h1>
      <p>ค้นหาข้อมูลพนักงานขับ/ผู้ควบคุมในระบบ แตะรายการเพื่อดูรายละเอียด</p>

      <Card>
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault()
            void load(q)
          }}
        >
          <FormField label="ค้นหา (ชื่อ/เบอร์โทร/เลขใบขับขี่)" htmlFor="driver-search-q">
            <input
              id="driver-search-q"
              type="text"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="เช่น สมชาย"
            />
          </FormField>
          <button type="submit" className="button button--primary button--full-width">
            ค้นหา
          </button>
        </form>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการคนขับ/ผู้ควบคุม..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={() => void load(q)} />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'driver_name_th',
              header: 'ชื่อ',
              render: (driver) => <Link to={`/drivers/${driver.driver_id}`}>{driver.driver_name_th}</Link>,
            },
            { key: 'phone', header: 'เบอร์โทร', render: (driver) => driver.phone ?? '-' },
            { key: 'license_no', header: 'เลขใบขับขี่', render: (driver) => driver.license_no ?? '-' },
            {
              key: 'license_expiry_date',
              header: 'วันหมดอายุใบขับขี่',
              render: (driver) =>
                driver.license_expiry_date ? formatThaiDate(driver.license_expiry_date) : 'ไม่มีข้อมูล',
            },
          ]}
          rows={state.drivers}
          getRowKey={(driver) => driver.driver_id}
          emptyTitle="ไม่พบคนขับ/ผู้ควบคุม"
          emptyDescription="ลองเปลี่ยนคำค้นหา"
        />
      )}
    </section>
  )
}
