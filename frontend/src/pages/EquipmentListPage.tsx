import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  describeErrorCode,
  equipmentCategoryLabel,
  equipmentStatusLabel,
  equipmentStatusTone,
} from '../lib/labels'
import type { Equipment, EquipmentCategory, Page } from '../lib/types'

const CATEGORY_OPTIONS: EquipmentCategory[] = [
  'LATHE',
  'MILLING',
  'AIR_COMPRESSOR',
  'WELDING',
  'PRESS',
  'DRILL_PRESS',
  'GRINDER',
  'FORKLIFT',
  'OTHER',
]

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: Equipment[] }

export function EquipmentListPage() {
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<EquipmentCategory | ''>('')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async (query: string, cat: EquipmentCategory | '') => {
    setState({ kind: 'loading' })

    const params = new URLSearchParams({ page_size: '50' })
    if (query.trim()) params.set('q', query.trim())
    if (cat) params.set('category', cat)

    const result = await apiGet<Page<Equipment>>(`/equipment?${params.toString()}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', items: result.data.items })
  }, [])

  useEffect(() => {
    void load(q, category)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="page">
      <h1>เครื่องมือ/อุปกรณ์ซ่อมบำรุง</h1>
      <p>ค้นหาและดูรายการเครื่องมือในโรงซ่อม แตะรายการเพื่อดูรายละเอียด</p>

      <Card>
        <form
          className="form-grid form-grid--two-column"
          onSubmit={(event) => {
            event.preventDefault()
            void load(q, category)
          }}
        >
          <FormField label="ค้นหา (ชื่อ หรือ รหัส)" htmlFor="equipment-search-q">
            <input
              id="equipment-search-q"
              type="text"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="เช่น เครื่องกลึง"
            />
          </FormField>
          <FormField label="ประเภท" htmlFor="equipment-search-category">
            <select
              id="equipment-search-category"
              value={category}
              onChange={(event) => {
                const next = event.target.value as EquipmentCategory | ''
                setCategory(next)
                void load(q, next)
              }}
            >
              <option value="">ทั้งหมด</option>
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {equipmentCategoryLabel[option]}
                </option>
              ))}
            </select>
          </FormField>
          <button type="submit" className="button button--primary button--full-width">
            ค้นหา
          </button>
        </form>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการเครื่องมือ..." />}

      {state.kind === 'error' && (
        <ErrorState
          message={state.message}
          requestId={state.requestId}
          onRetry={() => void load(q, category)}
        />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'equipment_id',
              header: 'รหัส',
              render: (item) => (
                <Link to={`/equipment/${item.equipment_id}`}>{item.equipment_id}</Link>
              ),
            },
            { key: 'name', header: 'ชื่อ', render: (item) => item.name },
            {
              key: 'category',
              header: 'ประเภท',
              render: (item) => equipmentCategoryLabel[item.category] ?? item.category,
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: (item) => (
                <StatusBadge
                  label={equipmentStatusLabel[item.operational_status] ?? item.operational_status}
                  tone={equipmentStatusTone[item.operational_status]}
                />
              ),
            },
          ]}
          rows={state.items}
          getRowKey={(item) => item.equipment_id}
          emptyTitle="ไม่พบเครื่องมือ"
          emptyDescription="ลองเปลี่ยนคำค้นหาหรือประเภท"
        />
      )}
    </section>
  )
}
