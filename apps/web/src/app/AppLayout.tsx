import { NavLink, Outlet } from 'react-router-dom'

function getNavClassName({ isActive }: { isActive: boolean }) {
  return isActive ? 'app-nav__link app-nav__link--active' : 'app-nav__link'
}

export function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <div className="app-shell__branding">
          <p className="eyebrow">Phase 1 Vertical Slice</p>
          <h1>Runbook Platform</h1>
          <p className="lede">
            Create organizations and runbooks, generate workflows through Django, and inspect live
            execution progress from the browser.
          </p>
        </div>

        <nav className="app-nav" aria-label="Primary">
          <NavLink className={getNavClassName} to="/organizations">
            Organizations
          </NavLink>
          <NavLink className={getNavClassName} to="/runbooks">
            Runbooks
          </NavLink>
          <NavLink className={getNavClassName} to="/approvals">
            Approvals
          </NavLink>
          <NavLink className={getNavClassName} to="/policies">
            Policies
          </NavLink>
          <NavLink className={getNavClassName} to="/integrations">
            Integrations
          </NavLink>
        </nav>
      </header>

      <main className="app-shell__main">
        <Outlet />
      </main>
    </div>
  )
}
