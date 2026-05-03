import { Link } from 'react-router-dom'

import { useChangesList } from '../../features/changes/hooks/useChangesList'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function getStatusPillClass(status: string) {
  if (status === 'draft') return 'pill'
  if (status === 'pending_approval') return 'pill pill--warn'
  if (status === 'approved' || status === 'dispatchable' || status === 'scheduled')
    return 'pill pill--info'
  if (status === 'running') return 'pill pill--info'
  if (status === 'verification_pending') return 'pill pill--warn'
  if (status === 'verified' || status === 'closed') return 'pill pill--success'
  if (status === 'rejected' || status === 'expired' || status === 'canceled')
    return 'pill pill--danger'
  return 'pill'
}

export function ChangesPage() {
  const { data, isLoading, error } = useChangesList()
  const changes = data?.results ?? []

  return (
    <div className="stack-md">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2>Changes</h2>
          <p className="muted">Production operation dossiers.</p>
        </div>
        <Link to="/changes/new" className="btn btn--primary">
          New Change Request
        </Link>
      </div>

      {isLoading && <p>Loading changes…</p>}
      {error && <p className="banner banner--error">Failed to load changes.</p>}

      {!isLoading && !error && changes.length === 0 && (
        <p className="muted">No changes yet. Create your first change request above.</p>
      )}

      {changes.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Title</th>
              <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Status</th>
              <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Profile</th>
              <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Created</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((change) => (
              <tr key={change.id}>
                <td style={{ padding: '0.4rem 0' }}>
                  <Link to={`/changes/${change.id}`}>{change.title}</Link>
                </td>
                <td style={{ padding: '0.4rem 0.5rem' }}>
                  <span className={getStatusPillClass(change.status)}>
                    {change.status.replace(/_/g, ' ')}
                  </span>
                </td>
                <td style={{ padding: '0.4rem 0.5rem' }} className="muted">
                  {change.operation_profile?.key ?? '—'}
                </td>
                <td style={{ padding: '0.4rem 0.5rem' }} className="muted">
                  {formatDateTime(change.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
