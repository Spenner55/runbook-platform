import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../features/auth/context/useAuth'
import { fetchRunnerPools, fetchRunners, drainPool, disablePool } from '../../features/runners/api'
import { getApiErrorMessage } from '../../shared/api/client'

function getStatusPillClass(status: string) {
  if (status === 'active') return 'pill pill--success'
  if (status === 'draining') return 'pill pill--warn'
  if (status === 'disabled') return 'pill pill--danger'
  return 'pill'
}

export function RunnerPoolsPage() {
  const { activeOrganizationId } = useAuth()
  const queryClient = useQueryClient()
  const [confirmAction, setConfirmAction] = useState<{ poolId: string; action: 'drain' | 'disable' } | null>(null)

  const poolsQuery = useQuery({
    queryKey: ['runner-pools', activeOrganizationId],
    queryFn: () => fetchRunnerPools(activeOrganizationId ?? ''),
    enabled: !!activeOrganizationId,
  })

  const runnersQuery = useQuery({
    queryKey: ['runners', activeOrganizationId],
    queryFn: () => fetchRunners(activeOrganizationId ?? ''),
    enabled: !!activeOrganizationId,
  })

  const drainMutation = useMutation({
    mutationFn: drainPool,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runner-pools'] })
      setConfirmAction(null)
    },
  })

  const disableMutation = useMutation({
    mutationFn: disablePool,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runner-pools'] })
      setConfirmAction(null)
    },
  })

  const pools = poolsQuery.data?.results ?? []
  const runners = runnersQuery.data?.results ?? []

  function getActiveRunnerCount(poolId: string) {
    return runners.filter((r) => r.pool_id === poolId && r.status === 'active').length
  }

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>Runner Pools</h2>
      </div>

      {poolsQuery.isLoading ? <p className="muted">Loading runner pools…</p> : null}
      {poolsQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(poolsQuery.error)}</p>
      ) : null}

      {!poolsQuery.isLoading && !poolsQuery.error && pools.length === 0 ? (
        <p className="muted">No runner pools configured for this organization.</p>
      ) : null}

      {pools.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Key</th>
              <th>Environment</th>
              <th>Network Zone</th>
              <th>Status</th>
              <th>Max Concurrent</th>
              <th>Active Runners</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pools.map((pool) => (
              <tr key={pool.id}>
                <td>
                  <Link to={`/runners/pools/${pool.id}`}>{pool.name}</Link>
                </td>
                <td>
                  <code>{pool.key}</code>
                </td>
                <td>{pool.environment}</td>
                <td>{pool.network_zone || '—'}</td>
                <td>
                  <span className={getStatusPillClass(pool.status)}>{pool.status}</span>
                </td>
                <td>{pool.max_concurrent_executions}</td>
                <td>{getActiveRunnerCount(pool.id)}</td>
                <td>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      className="button button--sm"
                      type="button"
                      disabled={pool.status === 'draining' || pool.status === 'disabled'}
                      onClick={() => setConfirmAction({ poolId: pool.id, action: 'drain' })}
                    >
                      Drain
                    </button>
                    <button
                      className="button button--sm button--ghost"
                      type="button"
                      disabled={pool.status === 'disabled'}
                      onClick={() => setConfirmAction({ poolId: pool.id, action: 'disable' })}
                    >
                      Disable
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {confirmAction ? (
        <div className="banner banner--warn">
          <p>
            Are you sure you want to <strong>{confirmAction.action}</strong> this pool?
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button
              className="button button--sm"
              type="button"
              onClick={() => {
                if (confirmAction.action === 'drain') {
                  drainMutation.mutate(confirmAction.poolId)
                } else {
                  disableMutation.mutate(confirmAction.poolId)
                }
              }}
            >
              Confirm
            </button>
            <button
              className="button button--sm button--ghost"
              type="button"
              onClick={() => setConfirmAction(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </section>
  )
}
