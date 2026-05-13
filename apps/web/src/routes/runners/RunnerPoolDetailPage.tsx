import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../features/auth/context/useAuth'
import { fetchRunnerPools, fetchRunners, drainPool, disablePool } from '../../features/runners/api'
import { getApiErrorMessage } from '../../shared/api/client'

function getStatusPillClass(status: string) {
  if (status === 'active') return 'pill pill--success'
  if (status === 'draining') return 'pill pill--warn'
  if (status === 'offline' || status === 'disabled' || status === 'revoked') return 'pill pill--danger'
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner-pools'] }),
  })

  const disableMutation = useMutation({
    mutationFn: disablePool,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner-pools'] }),
  })

  const pool = poolsQuery.data?.results?.find((p) => p.id === poolId)
  const poolRunners = (runnersQuery.data?.results ?? []).filter((r) => r.pool_id === poolId)

  if (poolsQuery.isLoading) return <p className="muted">Loading…</p>
  if (poolsQuery.error) return <p className="banner banner--error">{getApiErrorMessage(poolsQuery.error)}</p>
  if (!pool) return <p className="banner banner--error">Pool not found.</p>

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>{pool.name}</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
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
        </div>
      </div>

      <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.25rem 1rem' }}>
        <dt className="muted">Key</dt>
        <dd><code>{pool.key}</code></dd>
        <dt className="muted">Environment</dt>
        <dd>{pool.environment}</dd>
        <dt className="muted">Network Zone</dt>
        <dd>{pool.network_zone || '—'}</dd>
        <dt className="muted">Status</dt>
        <dd><span className={getStatusPillClass(pool.status)}>{pool.status}</span></dd>
        <dt className="muted">Max Concurrent</dt>
        <dd>{pool.max_concurrent_executions}</dd>
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
              </tr>
            </thead>
            <tbody>
              {poolRunners.map((runner) => (
                <tr key={runner.id}>
                  <td>{runner.display_name}</td>
                  <td><span className={getStatusPillClass(runner.status)}>{runner.status}</span></td>
                  <td>{runner.runner_version || '—'}</td>
                  <td>{runner.hostname || '—'}</td>
                  <td>{formatHeartbeatAge(runner.last_heartbeat_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  )
}
