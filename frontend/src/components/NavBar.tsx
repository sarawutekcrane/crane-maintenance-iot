import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_REPAIR, CAN_VIEW } from '../lib/capabilityNames'

const leadingNavItems = [
  { to: '/', label: 'หน้าหลัก' },
  { to: '/dashboard', label: 'ภาพรวมกองรถ' },
]

// Phase 7 Batch 7D2: shown only to an actor with `can_view` (the backend
// requires the same capability on the report's GET) — a UX convenience,
// not the access control itself.
const viewReportNavItems = [{ to: '/reports/certificate-expiry', label: 'ใบรับรองตามวันหมดอายุ' }]

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
  { to: '/waiting-assignment', label: 'รอมอบหมายช่าง' },
  { to: '/open-repair-queue', label: 'งานซ่อมค้าง' },
]

const trailingNavItems = [{ to: '/system-status', label: 'สถานะระบบ' }]

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
