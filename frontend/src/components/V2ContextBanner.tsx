import { useCapabilities } from '../lib/capabilities'
import { Card } from './Card'
import { StatusBadge } from './StatusBadge'

export const V2_DISABLED_MESSAGE = 'การมอบหมายช่างยังไม่เปิดใช้งาน'

/**
 * R2 Batch R2f-h4 B4 (A1-§25, D-H4-6) — the server's data context and V2
 * cutover state, shown on every V2 page. Informational only: TEST is labelled
 * TEST; REAL is shown only when the server says exactly REAL; anything else is
 * unknown / unconfigured, never REAL. The flag is never a local toggle.
 */
export function V2ContextBanner() {
  const { loading, signals } = useCapabilities()
  if (loading) return null
  const { dataContext, v2Enabled, ok } = signals
  return (
    <Card className="v2-context-banner">
      <div className="status-card__row" data-testid="v2-data-context">
        <span>ขอบเขตข้อมูล</span>
        {dataContext === 'TEST' && <StatusBadge label="TEST — ข้อมูลทดสอบ" tone="warning" />}
        {dataContext === 'REAL' && <StatusBadge label="REAL — ข้อมูลจริง" tone="info" />}
        {dataContext === 'UNCONFIGURED' && <StatusBadge label="ยังไม่ได้กำหนดขอบเขตข้อมูล" tone="danger" />}
        {dataContext === 'UNKNOWN' && <StatusBadge label="ไม่ทราบขอบเขตข้อมูล" tone="danger" />}
      </div>
      <div className="status-card__row" data-testid="v2-cutover-state">
        <span>การมอบหมายช่าง V2</span>
        {v2Enabled ? (
          <StatusBadge label="เปิดใช้งาน" tone="success" />
        ) : (
          <StatusBadge label={V2_DISABLED_MESSAGE} tone="neutral" />
        )}
      </div>
      {!ok && (
        <p className="form-field__error" role="alert">
          อ่านสถานะของระบบไม่สำเร็จหรือข้อมูลไม่สมบูรณ์ ระบบจึงถือว่ายังไม่เปิดใช้งาน
        </p>
      )}
    </Card>
  )
}

/** The explicit cutover-OFF state of a V2 create page (no form, no request). */
export function V2CreationDisabled() {
  return (
    <Card className="state-panel state-panel--denied">
      <div role="alert" data-testid="v2-creation-disabled">
        <p className="state-panel__title">{V2_DISABLED_MESSAGE}</p>
        <p>ยังเปิดใบงานซ่อมหรือใบสั่งงาน PM ในรูปแบบ V2 ไม่ได้ จนกว่าระบบจะเปิดใช้งานการมอบหมายช่าง V2</p>
      </div>
    </Card>
  )
}
