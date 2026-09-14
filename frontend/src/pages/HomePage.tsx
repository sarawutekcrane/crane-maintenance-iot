import { StatusBadge } from '../components/StatusBadge'

export function HomePage() {
  return (
    <section className="page">
      <h1>ยินดีต้อนรับ</h1>
      <p>
        ระบบจัดการยานพาหนะ เครื่องมือ การตรวจเช็ค บำรุงรักษาเชิงป้องกัน (PM) ใบแจ้งซ่อม
        และอะไหล่ <StatusBadge label="โหมดพัฒนา" tone="info" />
      </p>
      <p>
        เลือกเมนูด้านบนเพื่อดูรายการยานพาหนะ/เครื่องมือ เริ่มการตรวจเช็ค เปิดงาน PM
        แจ้งซ่อม หรือค้นหาอะไหล่
      </p>
    </section>
  )
}
