import { useAuth } from '../../features/auth/context/useAuth'

export function SettingsPage() {
  const { user, activeOrganizationId } = useAuth()

  const activeMembership = user?.memberships.find(
    (m) => m.organization.id === activeOrganizationId
  )

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>Settings</h2>
      </div>

      <div className="stack-md">
        <h3>Session</h3>
        <div className="detail-grid">
          <div>
            <p className="detail-grid__label">Name</p>
            <p>{user?.full_name ?? '—'}</p>
          </div>
          <div>
            <p className="detail-grid__label">Email</p>
            <p>{user?.email ?? '—'}</p>
          </div>
          <div>
            <p className="detail-grid__label">Staff</p>
            <p>{user?.is_staff ? 'Yes' : 'No'}</p>
          </div>
        </div>
      </div>

      <div className="stack-md">
        <h3>Active organization</h3>
        {activeMembership ? (
          <div className="detail-grid">
            <div>
              <p className="detail-grid__label">Name</p>
              <p>{activeMembership.organization.name}</p>
            </div>
            <div>
              <p className="detail-grid__label">Slug</p>
              <p>
                <code>{activeMembership.organization.slug}</code>
              </p>
            </div>
            <div>
              <p className="detail-grid__label">Your role</p>
              <p>{activeMembership.role}</p>
            </div>
          </div>
        ) : (
          <p className="muted">No active organization.</p>
        )}
      </div>

      {user?.memberships && user.memberships.length > 1 ? (
        <div className="stack-md">
          <h3>All memberships</h3>
          <ul className="list">
            {user.memberships.map((membership) => (
              <li className="list__item" key={membership.id}>
                <div>
                  <strong>{membership.organization.name}</strong>
                  <p className="muted">
                    <code>{membership.organization.slug}</code>
                  </p>
                </div>
                <span className="pill">{membership.role}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
