import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../features/auth/context/useAuth'
import {
  fetchRunnerPool,
  fetchRunners,
  drainPool,
  disablePool,
  reactivatePool,
} from '../../features/runners/api'
import { getApiErrorMessage } from '../../shared/api/client'

function getPoolStatusPillClass(status: string) {
  if (status === 'active') return 'pill pill--success'
  if (status === 'draining') return 'pill pill--warn'
  if (status === 'disabled') return 'pill pill--danger'
  return 'pill'
}

function getRunnerStatusPillClass(status: string) {
  if (status === 'active') return 'pill pill--success'
  if (status === 'draining') return 'pill pill--warn'
  if (status === 'offline' || status === 'disabled' || status === 'revoked')
    return 'pill pill--danger'
  return 'pill'
}

function formatHeartbeatAge(ts: string | null): string {
  if (!ts) return 'Never'
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

export function RunnerPoolDetailPage() {
  const { poolId } = useParams<{ poolId: string }>()
  const { activeOrganizationId } = useAuth()
  const queryClient = useQueryClient()

  const poolQuery = useQuery({
    queryKey: ['runner-pool', poolId],
    queryFn: () => fetchRunnerPool(poolId ?? ''),
    enabled: !!poolId,
  })

  const runnersQuery = useQuery({
    queryKey: ['runners', activeOrganizationId],
    queryFn: () => fetchRunners(activeOrganizationId ?? ''),
    enabled: !!activeOrganizationId,
  })

  const drainMutation = useMutation({
    mutationFn: drainPool,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner-pool', poolId] }),
  })

  const disableMutation = useMutation({
    mutationFn: disablePool,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner-pool', poolId] }),
  })

  const reactivateMutation = useMutation({
    mutationFn: reactivatePool,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner-pool', poolId] }),
  })

  if (poolQuery.isLoading) return <p className="muted">Loading…</p>
  if (poolQuery.error)
    return <p className="banner banner--error">{getApiErrorMessage(poolQuery.error)}</p>

  const pool = poolQuery.data
  if (!pool) return null

  const poolRunners = (runnersQuery.data?.results ?? []).filter((r) => r.pool_id === poolId)
  const capacity = pool.capacity_summary

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <div>
          <Link to="/runners" className="muted" style={{ fontSize: '0.875em' }}>
            ← Runner Pools
          </Link>
          <h2 style={{ marginTop: '0.25rem' }}>{pool.name}</h2>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button
            className="button button--sm"
            type="button"
            disabled={pool.status === 'draining' || pool.status === 'disabled'}
            onClick={() => drainMutation.mutate(pool.id)}
          >
            Drain Pool
          </button>
          <button
            className="button button--sm button--ghost"
            type="button"
            disabled={pool.status === 'disabled'}
            onClick={() => disableMutation.mutate(pool.id)}
          >
            Disable Pool
          </button>
          {pool.status === 'draining' || pool.status === 'disabled' ? (
            <button
              className="button button--sm button--ghost"
              type="button"
              onClick={() => reactivateMutation.mutate(pool.id)}
            >
              Reactivate
            </button>
          ) : null}
        </div>
      </div>

      {drainMutation.error ? (
        <p className="banner banner--error">{getApiErrorMessage(drainMutation.error)}</p>
      ) : null}
      {disableMutation.error ? (
        <p className="banner banner--error">{getApiErrorMessage(disableMutation.error)}</p>
      ) : null}
      {reactivateMutation.error ? (
        <p className="banner banner--error">{getApiErrorMessage(reactivateMutation.error)}</p>
      ) : null}

      <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.25rem 1rem' }}>
        <dt className="muted">Key</dt>
        <dd>
          <code>{pool.key}</code>
        </dd>
        <dt className="muted">Environment</dt>
        <dd>{pool.environment}</dd>
        <dt className="muted">Network Zone</dt>
        <dd>{pool.network_zone || '—'}</dd>
        <dt className="muted">Status</dt>
        <dd>
          <span className={getPoolStatusPillClass(pool.status)}>{pool.status}</span>
          {pool.status === 'draining' && pool.drain_requested_at ? (
            <span className="muted" style={{ fontSize: '0.875em', marginLeft: '0.5rem' }}>
              since {new Date(pool.drain_requested_at).toLocaleString()}
            </span>
          ) : null}
          {pool.status === 'disabled' && pool.disabled_at ? (
            <span className="muted" style={{ fontSize: '0.875em', marginLeft: '0.5rem' }}>
              since {new Date(pool.disabled_at).toLocaleString()}
            </span>
          ) : null}
        </dd>
        <dt className="muted">Max Concurrent</dt>
        <dd>{pool.max_concurrent_executions}</dd>
        <dt className="muted">Active Runners</dt>
        <dd>{pool.active_runner_count}</dd>
        <dt className="muted">Active Executions</dt>
        <dd>{pool.active_execution_count}</dd>
        <dt className="muted">Capacity</dt>
        <dd>
          {capacity ? (
            <span
              className={
                capacity.available_capacity === 0 ? 'pill pill--danger' : 'pill pill--success'
              }
            >
              {capacity.active_executions}/{capacity.max_concurrent_executions} (
              {capacity.available_capacity} available)
            </span>
          ) : (
            '—'
          )}
        </dd>
        <dt className="muted">Capabilities</dt>
        <dd>{pool.capabilities.length ? pool.capabilities.join(', ') : '—'}</dd>
      </dl>

      <div>
        <h3>Runners in this pool</h3>
        {runnersQuery.isLoading ? <p className="muted">Loading runners…</p> : null}
        {poolRunners.length === 0 && !runnersQuery.isLoading ? (
          <p className="muted">No runners registered in this pool.</p>
        ) : null}
        {poolRunners.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Version</th>
                <th>Hostname</th>
                <th>Last Heartbeat</th>
                <th>Active Executions</th>
              </tr>
            </thead>
            <tbody>
              {poolRunners.map((runner) => (
                <tr key={runner.id}>
                  <td>
                    <Link to={`/runners/runners/${runner.id}`}>{runner.display_name}</Link>
                  </td>
                  <td>
                    <span className={getRunnerStatusPillClass(runner.status)}>{runner.status}</span>
                  </td>
                  <td>{runner.runner_version || '—'}</td>
                  <td>{runner.hostname || '—'}</td>
                  <td>{formatHeartbeatAge(runner.last_heartbeat_at)}</td>
                  <td>{runner.active_execution_count ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  )
}
