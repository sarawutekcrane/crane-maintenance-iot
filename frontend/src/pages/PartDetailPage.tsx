import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, trackingModeLabel } from '../lib/labels'
import type { PartMaster } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; part: PartMaster }

export function PartDetailPage() {
  const { partId = '' } = useParams<{ partId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<PartMaster>(`/parts/${partId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', part: result.data })
  }, [partId])

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลอะไหล่..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายละเอียดอะไหล่</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { part } = state

  return (
    <section className="page">
      <h1>{part.name}</h1>
      <p>รหัสอะไหล่: {part.part_id} ({part.part_code})</p>

      <Card>
        <div className="status-card__row">
          <span>โหมดการติดตามอายุการใช้งาน</span>
          <StatusBadge label={trackingModeLabel[part.tracking_mode] ?? part.tracking_mode} tone="info" />
        </div>
        <div className="status-card__row">
          <span>สเปค</span>
          <span>{part.specification ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>ผู้ผลิต</span>
          <span>{part.manufacturer ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>หมายเลขอะไหล่ (Part No.)</span>
          <span>{part.part_number ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>หมวดหมู่</span>
          <span>{part.category ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>สถานะ</span>
          <StatusBadge
            label={part.is_active ? 'ใช้งาน' : 'เลิกใช้งาน/เก็บถาวร'}
            tone={part.is_active ? 'success' : 'neutral'}
          />
        </div>
      </Card>

      {part.tracking_mode === 'INSTANCE_TRACKED' && (
        <Card>
          <h2>ติดตามรายชิ้น</h2>
          <p>
            อะไหล่นี้ติดตามเป็นรายชิ้น (มีรหัสชิ้นงานเฉพาะ) ประวัติการติดตั้ง/ถอด/โยกย้ายจะติดตามไปกับตัวชิ้นงานจริง
            ไม่ใช่กับอะไหล่นี้โดยตรง
          </p>
          <Link
            to={`/parts/${part.part_id}/instances/new`}
            className="button button--primary button--full-width"
          >
            + ลงทะเบียนชิ้นงานใหม่
          </Link>
        </Card>
      )}

      {part.tracking_mode === 'POSITION_LIFETIME' && (
        <Card>
          <h2>อายุการใช้งานตามตำแหน่ง</h2>
          <p>
            อะไหล่นี้ติดตามอายุการใช้งานตามตำแหน่งบนยานพาหนะ/อุปกรณ์ ไม่จำเป็นต้องมีรหัสชิ้นงานเฉพาะ
            ดูและลงทะเบียนอายุการใช้งานตามตำแหน่งได้จากหน้ารายละเอียดยานพาหนะ/อุปกรณ์ (เมนู &quot;อะไหล่/อายุการใช้งาน&quot;)
          </p>
        </Card>
      )}
    </section>
  )
}
