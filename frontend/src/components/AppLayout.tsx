import type { ReactNode } from 'react'
import { NavBar } from './NavBar'

interface AppLayoutProps {
  children: ReactNode
}

/** Responsive base layout shared by every page: nav bar + main content area. */
export function AppLayout({ children }: AppLayoutProps) {
  return (
    <div className="app-shell">
      <NavBar />
      <main className="app-shell__content">{children}</main>
      <footer className="app-shell__footer">
        <span>Crane Fleet Maintenance Platform — โหมดพัฒนา (Local Development)</span>
      </footer>
    </div>
  )
}
