import { StatusBadge } from '../components/StatusBadge'

export function HomePage() {
  return (
    <section className="page">
      <h1>ยินดีต้อนรับ</h1>
      <p>
        นี่คือโครงหน้าเว็บเบื้องต้นของระบบบำรุงรักษาเครน (Phase 1) <StatusBadge label="โหมดพัฒนา" tone="info" />
      </p>
      <p>
        ฟังก์ชันด้านการตรวจเช็ค บำรุงรักษา ซ่อมบำรุง และการจัดการอะไหล่ จะถูกเพิ่มในเฟสถัดไป
      </p>
    </section>
  )
}
