import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'

import { useAuth } from '../../features/auth/context/useAuth'
import { useAuditorAccessGrants } from '../../features/auditor/hooks/useAuditorAccessGrants'
import { useCreateAuditorAccessGrant } from '../../features/auditor/hooks/useCreateAuditorAccessGrant'
import { useRevokeAuditorAccessGrant } from '../../features/auditor/hooks/useRevokeAuditorAccessGrant'
import { getApiErrorMessage } from '../../shared/api/client'

const defaultScope = '{\n  "all": true\n}'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

export function AuditorAccessAdminPage() {
  const { user, activeOrganizationId } = useAuth()
  const activeMembership = user?.memberships.find((m) => m.organization.id === activeOrganizationId)
  const canManage = activeMembership?.role === 'owner' || activeMembership?.role === 'admin'
  const grantsQuery = useAuditorAccessGrants()
  const createGrant = useCreateAuditorAccessGrant()
  const revokeGrant = useRevokeAuditorAccessGrant()
  const [userId, setUserId] = useState('')
  const [reason, setReason] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [scopeJson, setScopeJson] = useState(defaultScope)
  const [localError, setLocalError] = useState<string | null>(null)
  const grants = grantsQuery.data ?? []

  const createError = useMemo(() => {
    if (localError) return localError
    if (createGrant.error) return getApiErrorMessage(createGrant.error)
    return null
  }, [createGrant.error, localError])

  function submit(event: FormEvent) {
    event.preventDefault()
    setLocalError(null)

    let scope: Record<string, unknown>
    try {
      scope = JSON.parse(scopeJson) as Record<string, unknown>
    } catch {
      setLocalError('Scope must be valid JSON.')
      return
    }

    createGrant.mutate({
      user_id: userId,
      scope,
      reason,
      starts_at: startsAt || undefined,
      expires_at: expiresAt || undefined,
    })
  }

  return (
    <div className="stack-lg">
      <section className="panel stack-md">
        <div className="panel__header">
          <h2>Auditor Access Grants</h2>
          <p className="muted">Scoped read-only access to audit change evidence.</p>
        </div>

        {!canManage && (
          <p className="banner banner--warning">
            Grant changes are available only to organization owners and admins.
          </p>
        )}

        {canManage && (
          <form className="stack-md" onSubmit={submit}>
            <div className="filter-row">
              <label className="field">
                <span className="field__label">User ID</span>
                <input
                  className="field__input"
                  required
                  value={userId}
                  onChange={(event) => setUserId(event.target.value)}
                />
              </label>
              <label className="field">
                <span className="field__label">Reason</span>
                <input
                  className="field__input"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <label className="field">
                <span className="field__label">Starts at</span>
                <input
                  className="field__input"
                  type="datetime-local"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                />
              </label>
              <label className="field">
                <span className="field__label">Expires at</span>
                <input
                  className="field__input"
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(event) => setExpiresAt(event.target.value)}
                />
              </label>
            </div>
            <label className="field">
              <span className="field__label">Scope JSON</span>
              <textarea
                className="field__input input--textarea"
                value={scopeJson}
                onChange={(event) => setScopeJson(event.target.value)}
              />
            </label>
            {createError && <p className="banner banner--error">{createError}</p>}
            <button className="btn btn--primary" disabled={createGrant.isPending} type="submit">
              Create Grant
            </button>
          </form>
        )}
      </section>

      <section className="panel stack-md">
        <h3>Current Grants</h3>
        {grantsQuery.isLoading && <p>Loading access grants...</p>}
        {grantsQuery.error && <p className="banner banner--error">Failed to load access grants.</p>}
        {!grantsQuery.isLoading && !grantsQuery.error && grants.length === 0 && (
          <p className="muted">No auditor access grants exist.</p>
        )}
        {grants.length > 0 && (
          <ul className="step-list">
            {grants.map((grant) => (
              <li className="step-list__item" key={grant.id}>
                <div className="stack-md">
                  <div>
                    <strong>{grant.user_id}</strong>
                    <div className="muted">{grant.reason || 'No reason provided.'}</div>
                  </div>
                  <pre className="code-block">{JSON.stringify(grant.scope, null, 2)}</pre>
                  <div className="muted">
                    Starts {formatDateTime(grant.starts_at)}; expires{' '}
                    {formatDateTime(grant.expires_at)}
                  </div>
                </div>
                <div className="step-list__meta">
                  <span className={grant.status === 'active' ? 'pill pill--success' : 'pill'}>
                    {grant.status}
                  </span>
                  {canManage && grant.status === 'active' && (
                    <button
                      className="btn"
                      disabled={revokeGrant.isPending}
                      onClick={() => revokeGrant.mutate(grant.id)}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
