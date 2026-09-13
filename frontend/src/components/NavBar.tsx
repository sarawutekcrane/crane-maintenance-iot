import { useState } from 'react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'หน้าหลัก' },
  { to: '/vehicles', label: 'ยานพาหนะ' },
  { to: '/equipment', label: 'เครื่องมือ' },
  { to: '/parts', label: 'อะไหล่' },
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
