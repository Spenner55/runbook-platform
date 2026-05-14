import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../features/auth/context/useAuth'
import { fetchTargetConnectivityRoutes, deactivateRoute, reactivateRoute } from '../../features/runners/api'
import { getApiErrorMessage } from '../../shared/api/client'

export function TargetConnectivityRoutesPage() {
  const { activeOrganizationId } = useAuth()
  const queryClient = useQueryClient()
  const [confirmAction, setConfirmAction] = useState<{
    routeId: string
    action: 'deactivate' | 'reactivate'
  } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const routesQuery = useQuery({
    queryKey: ['target-connectivity-routes', activeOrganizationId],
    queryFn: () => fetchTargetConnectivityRoutes(activeOrganizationId ?? ''),
    enabled: !!activeOrganizationId,
  })

  const deactivateMutation = useMutation({
    mutationFn: deactivateRoute,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['target-connectivity-routes'] })
      setConfirmAction(null)
      setActionError(null)
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  })

  const reactivateMutation = useMutation({
    mutationFn: reactivateRoute,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['target-connectivity-routes'] })
      setConfirmAction(null)
      setActionError(null)
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  })

  const routes = routesQuery.data?.results ?? []

  function handleConfirm() {
    if (!confirmAction) return
    if (confirmAction.action === 'deactivate') deactivateMutation.mutate(confirmAction.routeId)
    else reactivateMutation.mutate(confirmAction.routeId)
  }

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <div>
          <Link to="/runners" className="muted" style={{ fontSize: '0.875em' }}>
            ← Runner Pools
          </Link>
          <h2 style={{ marginTop: '0.25rem' }}>Target Connectivity Routes</h2>
        </div>
      </div>

      <p className="muted" style={{ fontSize: '0.875em' }}>
        Routes map change targets to runner pools. All targets on a change must resolve to the same
        pool for dispatch.
      </p>

      {routesQuery.isLoading ? <p className="muted">Loading routes…</p> : null}
      {routesQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(routesQuery.error)}</p>
      ) : null}

      {!routesQuery.isLoading && !routesQuery.error && routes.length === 0 ? (
        <p className="muted">No connectivity routes configured for this organization.</p>
      ) : null}

      {routes.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Environment</th>
              <th>Target Type</th>
              <th>Pattern</th>
              <th>Pool</th>
              <th>Priority</th>
              <th>Required Capabilities</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((route) => (
              <tr key={route.id}>
                <td>{route.environment}</td>
                <td>
                  <code>{route.target_type}</code>
                </td>
                <td>
                  <code>{route.normalized_identifier_pattern}</code>
                </td>
                <td>
                  <Link to={`/runners/pools/${route.pool_id}`}>
                    <code>{route.pool_id}</code>
                  </Link>
                </td>
                <td>{route.priority}</td>
                <td>
                  {route.required_capabilities.length
                    ? route.required_capabilities.join(', ')
                    : '—'}
                </td>
                <td>
                  <span className={route.is_active ? 'pill pill--success' : 'pill pill--danger'}>
                    {route.is_active ? 'active' : 'inactive'}
                  </span>
                </td>
                <td>
                  {route.is_active ? (
                    <button
                      className="button button--sm button--ghost"
                      type="button"
                      onClick={() =>
                        setConfirmAction({ routeId: route.id, action: 'deactivate' })
                      }
                    >
                      Deactivate
                    </button>
                  ) : (
                    <button
                      className="button button--sm"
                      type="button"
                      onClick={() =>
                        setConfirmAction({ routeId: route.id, action: 'reactivate' })
                      }
                    >
                      Reactivate
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {confirmAction ? (
        <div className="banner banner--warn">
          <p>
            Are you sure you want to <strong>{confirmAction.action}</strong> this route?
            {confirmAction.action === 'deactivate' ? (
              <span> Changes targeting this route will no longer be dispatchable.</span>
            ) : null}
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button className="button button--sm" type="button" onClick={handleConfirm}>
              Confirm
            </button>
            <button
              className="button button--sm button--ghost"
              type="button"
              onClick={() => {
                setConfirmAction(null)
                setActionError(null)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {actionError ? <p className="banner banner--error">{actionError}</p> : null}
    </section>
  )
}
