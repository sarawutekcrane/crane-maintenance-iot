import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'หน้าหลัก' },
  { to: '/system-status', label: 'สถานะระบบ' },
]

export function NavBar() {
  return (
    <header className="app-navbar">
      <div className="app-navbar__brand">ระบบบำรุงรักษาเครน</div>
      <nav aria-label="เมนูหลัก">
        <ul className="app-navbar__list">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  isActive ? 'app-navbar__link app-navbar__link--active' : 'app-navbar__link'
                }
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
