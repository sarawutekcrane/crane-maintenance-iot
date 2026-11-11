import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { FormField } from '../components/FormField'
import { ApiError, apiGet, apiPostWithRequestId } from '../lib/apiClient'
import {
  describeErrorCode,
  dueActionLabel,
  lifetimeRuleScopeLabel,
  lifetimeTriggerTypeLabel,
  trackingModeLabel,
} from '../lib/labels'
import { formatNumber, isUncertain, newRequestId } from '../lib/partLifetime'
import type { LifetimeRule, PartMaster } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; part: PartMaster; rules: LifetimeRule[] | null }

export function PartDetailPage() {
  const { partId = '' } = useParams<{ partId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [reason, setReason] = useState('')
  const [activeError, setActiveError] = useState<string | null>(null)
  const [activeIntent, setActiveIntent] = useState(newRequestId)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const [result, rules] = await Promise.all([
      apiGet<PartMaster>(`/parts/${partId}`),
      apiGet<LifetimeRule[]>(`/lifetime-rules?part_id=${partId}`),
    ])
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', part: result.data, rules: rules.ok && Array.isArray(rules.data) ? rules.data : null })
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

  const { part, rules } = state

  const toggleActive = async () => {
    if (!reason.trim()) {
      setActiveError('กรุณาระบุเหตุผล')
      return
    }
    setActiveError(null)
    const result = await apiPostWithRequestId<PartMaster>(
      `/parts/${part.part_id}/${part.is_active ? 'deactivate' : 'reactivate'}`, { reason: reason.trim() }, activeIntent)
    if (result.ok) {
      setActiveIntent(newRequestId())
      setReason('')
      void load()
      return
    }
    const err = result.error
    if (err instanceof ApiError && !isUncertain(err.status)) {
      setActiveIntent(newRequestId())
      setActiveError(describeErrorCode(err.code))
    } else {
      setActiveError('ไม่ทราบผลการบันทึก — กดอีกครั้งเพื่อส่งคำขอเดิมซ้ำอย่างปลอดภัย')
    }
  }

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

      <Card>
        <h2>กฎอายุการใช้งาน</h2>
        {rules === null && <p className="form-field__error">โหลดกฎอายุการใช้งานไม่สำเร็จ</p>}
        {rules !== null && rules.length === 0 && <p>ยังไม่มีกฎอายุการใช้งาน (ค่ากำหนดจริงรอข้อมูลที่อนุมัติ)</p>}
        <ul>
          {(rules ?? []).map((rule) => (
            <li key={rule.lifetime_rule_id} data-testid="part-rule">
              <p>
                {rule.due_action ? dueActionLabel[rule.due_action] : 'ยังไม่ระบุการดำเนินการ'} —{' '}
                {lifetimeTriggerTypeLabel[rule.trigger_type] ?? rule.trigger_type}
                {rule.interval_value !== null ? ` ทุก ${formatNumber(rule.interval_value)} ${rule.interval_unit ?? ''}` : ''}
              </p>
              <p className="form-field__hint">
                {lifetimeRuleScopeLabel[rule.scope]} {rule.model_id ?? rule.vehicle_id}
                {rule.condition_group_key ? ` · กลุ่มเงื่อนไข ${rule.condition_group_key} (ถึงอย่างใดก่อน)` : ''}
                {rule.trigger_type === 'CYCLE' ? ' · ยังไม่รองรับการคำนวณ' : ''}
              </p>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h2>{part.is_active ? 'เลิกใช้อะไหล่รายการนี้' : 'นำอะไหล่รายการนี้กลับมาใช้'}</h2>
        <p className="form-field__hint">ประวัติเดิมทั้งหมดยังคงอยู่ — ไม่มีการลบ</p>
        <div className="form-grid">
          <FormField label="เหตุผล" htmlFor="part-active-reason">
            <input id="part-active-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          </FormField>
          {activeError && <p className="form-field__error" role="alert">{activeError}</p>}
          <button type="button" className="button button--secondary button--full-width"
            onClick={() => void toggleActive()}>
            {part.is_active ? 'เลิกใช้' : 'นำกลับมาใช้'}
          </button>
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
