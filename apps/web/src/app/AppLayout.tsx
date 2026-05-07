import { NavLink, Outlet } from 'react-router-dom'

import { AuthStatus } from '../features/auth/AuthStatus'
import { useAuth } from '../features/auth/context/useAuth'

function getNavClassName({ isActive }: { isActive: boolean }) {
  return isActive ? 'app-nav__link app-nav__link--active' : 'app-nav__link'
}

export function AppLayout() {
  const { user, activeOrganizationId } = useAuth()

  const activeMembership = user?.memberships.find((m) => m.organization.id === activeOrganizationId)

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <div className="app-shell__branding">
          <h1>Runbook Platform</h1>
          {activeMembership ? <p className="muted">{activeMembership.organization.name}</p> : null}
        </div>

        <AuthStatus />

        <nav className="app-nav" aria-label="Primary">
          <NavLink className={getNavClassName} to="/runbooks">
            Runbooks
          </NavLink>
          <NavLink className={getNavClassName} to="/executions">
            Executions
          </NavLink>
          <NavLink className={getNavClassName} to="/approvals">
            Approvals
          </NavLink>
          <NavLink className={getNavClassName} to="/changes">
            Changes
          </NavLink>
          <NavLink className={getNavClassName} to="/retro-reviews">
            Retro Reviews
          </NavLink>
          <NavLink className={getNavClassName} to="/freeze-rules">
            Freeze Rules
          </NavLink>
          <NavLink className={getNavClassName} to="/policies">
            Policies
          </NavLink>
          <NavLink className={getNavClassName} to="/integrations">
            Integrations
          </NavLink>
          <NavLink className={getNavClassName} to="/settings">
            Settings
          </NavLink>
        </nav>
      </header>

      <main className="app-shell__main">
        <Outlet />
      </main>
    </div>
  )
}
