import { useEffect, useState } from 'react'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  approvalStateLabel,
  describeErrorCode,
  dueActionLabel,
  dueStatusLabel,
  dueStatusTone,
  lifetimeTriggerTypeLabel,
  priorUsageQualityLabel,
  verificationLevelLabel,
} from '../lib/labels'
import { COUNTER_ROWS, basisText, formatNumber, policyText, quantityText, reasonText } from '../lib/partLifetime'
import type { DeclarationView, LifetimeStatus, RuleResultView } from '../lib/types'
import { Card } from './Card'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'
import { StatusBadge } from './StatusBadge'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; status: LifetimeStatus }

/** R6 FINAL §9 / §19: renders the ONE lifetime-status read contract. A load
 * failure is never shown as "nothing tracked". `reloadKey` changes after a
 * write so the panel re-reads; a stale response never overwrites a newer one. */
export function PartLifetimeStatusPanel({ path, reloadKey = 0 }: { path: string; reloadKey?: number }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let cancelled = false
    // The previous view stays until the new one arrives; a response for an
    // older path / reload is discarded (never overwrites a newer one).
    void apiGet<LifetimeStatus>(path).then((result) => {
      if (cancelled) return
      if (!result.ok) {
        const err = result.error
        setState({ kind: 'error', message: err instanceof ApiError ? describeErrorCode(err.code) : err.message })
        return
      }
      if (!result.data || !Array.isArray(result.data.counters) || !Array.isArray(result.data.rules)) {
        setState({ kind: 'error', message: 'ข้อมูลอายุการใช้งานไม่อยู่ในรูปแบบที่คาดไว้' })
        return
      }
      setState({ kind: 'ready', status: result.data })
    })
    return () => {
      cancelled = true
    }
  }, [path, reloadKey, retry])
  const load = () => setRetry((n) => n + 1)

  if (state.kind === 'loading') return <LoadingState message="กำลังคำนวณอายุการใช้งาน..." />
  if (state.kind === 'error') return <ErrorState message={state.message} onRetry={load} />
  const { status } = state
  return (
    <section aria-label="อายุการใช้งาน" data-testid="part-lifetime-status">
      <Card>
        <h2>อายุการใช้งาน</h2>
        {status.policy_context === 'TEST' && (
          <p className="form-field__hint">ข้อมูลทดสอบ (TEST) — ค่าตามนโยบายที่ยังไม่อนุมัติจะแสดงว่า "ค่าทดสอบตามข้อเสนอ"</p>
        )}
        {status.approval && (
          <p data-testid="approval-state">การอนุมัติหลังซ่อม: {approvalStateLabel[status.approval.state]}</p>
        )}
        {status.lifecycle.cycle_number !== null && <p>รอบการใช้งานที่ {status.lifecycle.cycle_number}</p>}
        {status.counters.length === 0 && <p>ยังไม่มีฐานการนับสำหรับชิ้นงานนี้</p>}
        {status.counters.map((counters) => (
          <div key={basisText(counters)} className="part-counters" data-testid="part-counters">
            <h3>{basisText(counters)}</h3>
            {COUNTER_ROWS.map((row) => {
              const q = counters[row.key]
              const policy = policyText(q.policy_state)
              return (
                <div key={row.key} className="status-card__row" data-testid={`counter-${row.key}`}>
                  <span>{row.label}</span>
                  <span>
                    <strong data-testid={`counter-value-${row.key}`}>{quantityText(q)}</strong>
                    {policy && <span className="form-field__hint"> ({policy})</span>}
                    {q.quality !== 'KNOWN' && q.reasons.length > 0 && (
                      <span className="form-field__hint"> — {reasonText(q.reasons)}</span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </Card>
      <Card>
        <h2>กำหนดตรวจ/ซ่อม/เปลี่ยน</h2>
        {status.rules.length === 0 && <p>ยังไม่มีกฎอายุการใช้งานสำหรับรุ่นนี้ (รอข้อมูลจริง)</p>}
        <ul>
          {status.rules.map((rule) => (
            <RuleRow key={rule.due_key} rule={rule} />
          ))}
        </ul>
        {status.inactive_rules.length > 0 && (
          <p className="form-field__hint">มีกฎเฉพาะยานพาหนะ {status.inactive_rules.length} รายการที่ยังไม่เปิดใช้</p>
        )}
      </Card>
      <Card>
        <h2>ประวัติการใช้งานที่แจ้งไว้</h2>
        <Declaration title="ก่อนเริ่มติดตาม (ตลอดอายุ)" view={status.declarations.prior_usage} />
        {status.declarations.prior_cycle_usage && (
          <Declaration title="ก่อนเริ่มติดตาม (รอบปัจจุบัน)" view={status.declarations.prior_cycle_usage} />
        )}
      </Card>
    </section>
  )
}

function RuleRow({ rule }: { rule: RuleResultView }) {
  const policy = policyText(rule.policy_state)
  return (
    <li data-testid="due-rule">
      <p>
        {rule.due_action ? dueActionLabel[rule.due_action] : 'ไม่ระบุการดำเนินการ'} —{' '}
        {rule.trigger_type === 'MULTI_CONDITION'
          ? `หลายเงื่อนไข (ถึงอย่างใดก่อน) ${rule.condition_group_key ?? ''}`
          : (lifetimeTriggerTypeLabel[rule.trigger_type ?? ''] ?? rule.trigger_type)}{' '}
        <StatusBadge label={dueStatusLabel[rule.status]} tone={dueStatusTone[rule.status]} />
      </p>
      {rule.next_due_value !== null && rule.current_value !== null && (
        <p className="form-field__hint">
          ใช้แล้ว {formatNumber(rule.current_value)} / กำหนด {formatNumber(rule.next_due_value)}
        </p>
      )}
      {rule.next_due_date && <p className="form-field__hint">ครบกำหนดวันที่ {rule.next_due_date}</p>}
      {policy && <p className="form-field__hint">{policy}</p>}
      {rule.reasons.length > 0 && <p className="form-field__hint">{reasonText(rule.reasons)}</p>}
    </li>
  )
}

function Declaration({ title, view }: { title: string; view: DeclarationView | null }) {
  if (!view) return null
  return (
    <div className="status-card__row" data-testid="declaration">
      <span>{title}</span>
      <span>
        {priorUsageQualityLabel[view.quality]}
        {view.declared_value !== null && view.quality !== 'UNKNOWN' ? ` — แจ้งไว้ ${formatNumber(view.declared_value)}` : ''}
        {view.verification_level && (
          <span className="form-field__hint"> ({verificationLevelLabel[view.verification_level]})</span>
        )}
      </span>
    </div>
  )
}
