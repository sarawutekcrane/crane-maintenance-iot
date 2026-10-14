import { Link } from 'react-router-dom'
import { Card } from '../../components/Card'
import { V2ContextBanner } from '../../components/V2ContextBanner'

/**
 * R2 Batch R2f-h4 B4 — the index of the parallel V2 routes (Option 1, B4 only:
 * a development / test arrangement; navigation cutover is B5). Not linked from
 * the main navigation.
 */
export function V2HomePage() {
  return (
    <section className="page">
      <h1>การมอบหมายช่าง V2</h1>
      <V2ContextBanner />
      <Card>
        <p className="form-field__hint">
          หน้ากลุ่มนี้เป็นหน้าทดสอบการมอบหมายช่างแบบ V2 ระหว่างการพัฒนา (ยังไม่ใช่เมนูหลักของระบบ)
        </p>
        <Link to="/v2/waiting-assignment" className="button button--secondary button--full-width">
          งานที่รอมอบหมายช่าง
        </Link>
        <Link to="/v2/my-work" className="button button--secondary button--full-width">
          งานของฉัน
        </Link>
      </Card>
    </section>
  )
}
