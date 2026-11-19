import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useCapabilities } from '../lib/capabilities'
import {
  CAN_ASSIGN_CRANE_CREW,
  CAN_TEST_PM_MASTER_ASSIGN,
  CAN_TEST_PM_MASTER_PUBLISH,
  CAN_ASSIGN_CRANE_DRIVER,
  CAN_MANAGE_FINDING_REPAIR,
  CAN_MANAGE_PM,
  CAN_MANAGE_REPAIR,
  CAN_VIEW,
} from '../lib/capabilityNames'

const leadingNavItems = [
  { to: '/', label: 'หน้าหลัก' },
  { to: '/dashboard', label: 'ภาพรวมกองรถ' },
]

// Phase 7 Batches 7D2/7E2: shown only to an actor with `can_view` (the
// backend requires the same capability on each report's GET) — a UX
// convenience, not the access control itself.
const viewReportNavItems = [
  { to: '/reports/certificate-expiry', label: 'ใบรับรองตามวันหมดอายุ' },
  // Deliberately NOT 'ข้อบกพร่องจากการตรวจเช็ค': that text is the existing
  // FINDING source label on the repair pages (labels.ts), so a menu link with
  // the same text would be ambiguous there.
  { to: '/reports/inspection-findings', label: 'ประวัติข้อบกพร่องที่บันทึกไว้' },
  // R4 / TASK-010 Fleet PM Due B1: read-only, `can_view` (the backend re-checks it).
  { to: '/pm/due', label: 'กำหนด PM ทั้งกองรถ' },
  // R7 Whole-Phase: the central read-only alert list, `can_view` (the backend re-checks it).
  { to: '/alerts', label: 'การแจ้งเตือนทั้งหมด' },
  // R8 (R8-09): the fleet part-lifetime-due report, `can_view` (the backend re-checks it).
  { to: '/reports/part-lifetime-due', label: 'อายุอะไหล่ถึงกำหนด' },
]

// R8 early workstream (OD-7 = A): the fleet-wide Resource Calendar shows personal schedules,
// so the item is shown to a holder of can_assign_crane_driver or can_assign_crane_crew — the
// same rule the backend enforces on every read (a UX convenience, not the control itself).
const resourceCalendarNavItem = { to: '/resource-calendar', label: 'ปฏิทินทรัพยากร' }
// R8 PRE-UAT SG-PM: the PM Master TEST profile page, for holders of its per-employee TEST grants only.
const pmMasterTestNavItem = { to: '/pm-master-test', label: 'แผน PM หลัก (ทดสอบ)' }

const baseNavItems = [
  { to: '/vehicles', label: 'ยานพาหนะ' },
  { to: '/equipment', label: 'เครื่องมือ' },
  { to: '/parts', label: 'อะไหล่' },
  // Distinct wording from VehicleDetailPage's own "คนขับ/ผู้ควบคุม" action
  // link (which is scoped to one vehicle) — avoids an ambiguous duplicate
  // accessible name on the same page.
  { to: '/drivers', label: 'คนขับทั้งหมด' },
  { to: '/my-work', label: 'งานของฉัน' },
]

// Core Demo Fixes Delta REV05 section 10: shown only to an actor with
// `can_manage_repair` — a UX convenience, not the access control itself
// (the backend re-checks the same capability on every request these
// pages make). This is deliberately the smallest reversible rule, not a
// final per-role navigation matrix.
const maintenanceNavItems = [
  { to: '/repair-request-queue', label: 'แจ้งซ่อมรอตรวจรับ' },
]
// R3-11: the Finding follow-up view sits with the repair queues (same audience);
// L11: a holder of the Finding authority alone sees it too.
const openRepairQueueNavItem = { to: '/open-repair-queue', label: 'งานซ่อมค้าง' }
const findingFollowupNavItem = { to: '/findings/follow-up', label: 'ติดตามผิดปกติ' }

// R2 Batch R2f-h4 B5: the Technician V2 waiting-assignment view holds a Repair
// queue (`can_manage_repair`) and a PM queue (`can_manage_pm`), so its menu item
// is shown to a holder of either — the page shows only the queues the actor
// may read, and the backend re-checks each one.
const waitingAssignmentNavItem = { to: '/waiting-assignment', label: 'รอมอบหมายช่าง' }

// R4 / TASK-010: the fleet PM Work Order queue for PM managers (`can_manage_pm`)
// — a UX convenience; the backend re-checks the capability on every read.
const pmManagerQueueNavItem = { to: '/pm/manager-queue', label: 'คิวใบงาน PM' }

// R2 Batch R2e: the organisation masters, shown to an actor with `can_view`
// (the backend requires the same capability on each read) — a UX convenience.
const orgMasterNavItems = [
  { to: '/personnel', label: 'บุคลากร' },
  { to: '/departments', label: 'แผนก' },
  // R8 PRE-UAT (workstream A): models / branches / technicians (read for can_view; TEST create/edit by grant).
  { to: '/master-data', label: 'ข้อมูลหลัก (รุ่น/สาขา/ช่าง)' },
]

// Access Management (Owner-approved Mock): authority there is a position or a
// delegation, not a capability, so the item is always listed; the page itself
// says when the feature is not enabled or the actor holds no authority.
const trailingNavItems = [
  { to: '/access-management', label: 'จัดการสิทธิ์' },
  { to: '/system-status', label: 'สถานะระบบ' },
]

/**
 * Reusable responsive nav pattern: below tablet width the link list is
 * collapsed behind a toggle button (mobile navigation); from tablet width
 * up, CSS always shows the list inline regardless of `open` (see
 * `.app-navbar__list` in index.css), so the toggle button itself is also
 * hidden there via CSS.
 */
export function NavBar() {
  const [open, setOpen] = useState(false)
  const { hasCapability } = useCapabilities()
  const navItems = [
    ...leadingNavItems,
    ...(hasCapability(CAN_VIEW) ? viewReportNavItems : []),
    ...baseNavItems,
    ...(hasCapability(CAN_MANAGE_REPAIR) ? maintenanceNavItems : []),
    ...(hasCapability(CAN_MANAGE_REPAIR) || hasCapability(CAN_MANAGE_PM) ? [waitingAssignmentNavItem] : []),
    ...(hasCapability(CAN_MANAGE_PM) ? [pmManagerQueueNavItem] : []),
    ...(hasCapability(CAN_MANAGE_REPAIR) ? [openRepairQueueNavItem] : []),
    ...(hasCapability(CAN_MANAGE_REPAIR) || hasCapability(CAN_MANAGE_FINDING_REPAIR) ? [findingFollowupNavItem] : []),
    ...(hasCapability(CAN_VIEW) ? orgMasterNavItems : []),
    ...(hasCapability(CAN_ASSIGN_CRANE_DRIVER) || hasCapability(CAN_ASSIGN_CRANE_CREW) ? [resourceCalendarNavItem] : []),
    ...(hasCapability(CAN_TEST_PM_MASTER_PUBLISH) || hasCapability(CAN_TEST_PM_MASTER_ASSIGN) ? [pmMasterTestNavItem] : []),
    ...trailingNavItems,
  ]

  return (
    <header className="app-navbar">
      <div className="app-navbar__bar">
        <div className="app-navbar__brand">ระบบบำรุงรักษาเครน</div>
        <button
          type="button"
          className="app-navbar__toggle"
          aria-expanded={open}
          aria-controls="app-navbar-menu"
          aria-label={open ? 'ปิดเมนู' : 'เปิดเมนู'}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? '✕' : '☰'}
        </button>
      </div>
      <nav aria-label="เมนูหลัก">
        <ul
          id="app-navbar-menu"
          className={open ? 'app-navbar__list is-open' : 'app-navbar__list'}
        >
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  isActive ? 'app-navbar__link app-navbar__link--active' : 'app-navbar__link'
                }
                onClick={() => setOpen(false)}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
