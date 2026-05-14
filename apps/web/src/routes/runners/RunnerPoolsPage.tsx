import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../features/auth/context/useAuth'
import {
  fetchRunnerPools,
  fetchRunners,
  drainPool,
  disablePool,
  reactivatePool,
} from '../../features/runners/api'
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
  const [confirmAction, setConfirmAction] = useState<{
    poolId: string
    action: 'drain' | 'disable' | 'reactivate'
  } | null>(null)

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

  const reactivateMutation = useMutation({
    mutationFn: reactivatePool,
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

  function handleConfirm() {
    if (!confirmAction) return
    if (confirmAction.action === 'drain') drainMutation.mutate(confirmAction.poolId)
    else if (confirmAction.action === 'disable') disableMutation.mutate(confirmAction.poolId)
    else if (confirmAction.action === 'reactivate') reactivateMutation.mutate(confirmAction.poolId)
  }

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>Runner Pools</h2>
        <Link to="/runners/routes" className="button button--sm button--ghost">
          Connectivity Routes
        </Link>
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
              <th>Active Executions</th>
              <th>Capacity</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pools.map((pool) => {
              const capacity = pool.capacity_summary
              const activeRunners = pool.active_runner_count ?? getActiveRunnerCount(pool.id)
              return (
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
                    {pool.status === 'draining' && pool.drain_requested_at ? (
                      <span className="muted" style={{ fontSize: '0.75em', marginLeft: '0.25rem' }}>
                        since {new Date(pool.drain_requested_at).toLocaleString()}
                      </span>
                    ) : null}
                    {pool.status === 'disabled' && pool.disabled_at ? (
                      <span className="muted" style={{ fontSize: '0.75em', marginLeft: '0.25rem' }}>
                        since {new Date(pool.disabled_at).toLocaleString()}
                      </span>
                    ) : null}
                  </td>
                  <td>{pool.max_concurrent_executions}</td>
                  <td>{activeRunners}</td>
                  <td>{pool.active_execution_count ?? '—'}</td>
                  <td>
                    {capacity ? (
                      <span
                        className={
                          capacity.available_capacity === 0
                            ? 'pill pill--danger'
                            : 'pill pill--success'
                        }
                      >
                        {capacity.active_executions}/{capacity.max_concurrent_executions}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
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
                      {pool.status === 'draining' || pool.status === 'disabled' ? (
                        <button
                          className="button button--sm button--ghost"
                          type="button"
                          onClick={() =>
                            setConfirmAction({ poolId: pool.id, action: 'reactivate' })
                          }
                        >
                          Reactivate
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : null}

      {confirmAction ? (
        <div className="banner banner--warn">
          <p>
            Are you sure you want to <strong>{confirmAction.action}</strong> this pool?
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button className="button button--sm" type="button" onClick={handleConfirm}>
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
