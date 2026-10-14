import { useCapabilities } from '../lib/capabilities'
import { Card } from './Card'
import { StatusBadge } from './StatusBadge'

/**
 * R2 Batch R2f-h4 B4 (A1-§25, D-H4-6) — the server's data context, shown on
 * every V2 page. Informational only: TEST is labelled TEST; REAL is shown only
 * when the server says exactly REAL; anything else is unknown / unconfigured,
 * never REAL. R2 Batch R2f-h4 B6 Rev2: Technician V2 is the only assignment
 * model, so there is no V2 ON/OFF state to show and nothing here blocks a page.
 */
export function V2ContextBanner() {
  const { loading, signals } = useCapabilities()
  if (loading) return null
  const { dataContext, ok } = signals
  return (
    <Card className="v2-context-banner">
      <div className="status-card__row" data-testid="v2-data-context">
        <span>ขอบเขตข้อมูล</span>
        {dataContext === 'TEST' && <StatusBadge label="TEST — ข้อมูลทดสอบ" tone="warning" />}
        {dataContext === 'REAL' && <StatusBadge label="REAL — ข้อมูลจริง" tone="info" />}
        {dataContext === 'UNCONFIGURED' && <StatusBadge label="ยังไม่ได้กำหนดขอบเขตข้อมูล" tone="danger" />}
        {dataContext === 'UNKNOWN' && <StatusBadge label="ไม่ทราบขอบเขตข้อมูล" tone="danger" />}
      </div>
      {!ok && (
        <p className="form-field__error" role="alert">
          อ่านขอบเขตข้อมูลของระบบไม่สำเร็จหรือข้อมูลไม่สมบูรณ์ (ระบบหลังบ้านยังคงตรวจสอบสิทธิ์และขอบเขตข้อมูลทุกครั้ง)
        </p>
      )}
    </Card>
  )
}
