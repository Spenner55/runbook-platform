import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { fetchRunner, drainRunner, disableRunner, revokeRunner } from '../../features/runners/api'
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
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return 'STALE'
}

function getHeartbeatLabel(ts: string | null): string {
  if (!ts) return 'OFFLINE'
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (diff > 120) return 'OFFLINE'
  if (diff > 30) return 'STALE'
  return formatHeartbeatAge(ts)
}

function getHeartbeatClass(label: string): string {
  if (label === 'OFFLINE' || label === 'STALE') return 'pill pill--danger'
  return 'pill pill--success'
}

export function RunnerDetailPage() {
  const { runnerId } = useParams<{ runnerId: string }>()
  const queryClient = useQueryClient()

  const runnerQuery = useQuery({
    queryKey: ['runner', runnerId],
    queryFn: () => fetchRunner(runnerId ?? ''),
    enabled: !!runnerId,
    refetchInterval: 15000,
  })

  const drainMutation = useMutation({
    mutationFn: drainRunner,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner', runnerId] }),
  })

  const disableMutation = useMutation({
    mutationFn: disableRunner,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner', runnerId] }),
  })

  const revokeMutation = useMutation({
    mutationFn: revokeRunner,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner', runnerId] }),
  })

  if (runnerQuery.isLoading) return <p className="muted">Loading…</p>
  if (runnerQuery.error)
    return <p className="banner banner--error">{getApiErrorMessage(runnerQuery.error)}</p>

  const runner = runnerQuery.data
  if (!runner) return null

  const heartbeatLabel = getHeartbeatLabel(runner.last_heartbeat_at)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <div>
          {runner.pool_id ? (
            <Link
              to={`/runners/pools/${runner.pool_id}`}
              className="muted"
              style={{ fontSize: '0.875em' }}
            >
              ← Pool
            </Link>
          ) : null}
          <h2 style={{ marginTop: '0.25rem' }}>{runner.display_name}</h2>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button
            className="button button--sm"
            type="button"
            disabled={
              runner.status === 'draining' ||
              runner.status === 'disabled' ||
              runner.status === 'revoked'
            }
            onClick={() => drainMutation.mutate(runner.id)}
          >
            Drain
          </button>
          <button
            className="button button--sm button--ghost"
            type="button"
            disabled={runner.status === 'disabled' || runner.status === 'revoked'}
            onClick={() => disableMutation.mutate(runner.id)}
          >
            Disable
          </button>
          <button
            className="button button--sm button--ghost"
            type="button"
            disabled={runner.status === 'revoked'}
            onClick={() => {
              if (window.confirm('Revoke this runner? It will no longer be able to authenticate.')) {
                revokeMutation.mutate(runner.id)
              }
            }}
          >
            Revoke
          </button>
        </div>
      </div>

      {drainMutation.error ? (
        <p className="banner banner--error">{getApiErrorMessage(drainMutation.error)}</p>
      ) : null}
      {disableMutation.error ? (
        <p className="banner banner--error">{getApiErrorMessage(disableMutation.error)}</p>
      ) : null}
      {revokeMutation.error ? (
        <p className="banner banner--error">{getApiErrorMessage(revokeMutation.error)}</p>
      ) : null}

      <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.25rem 1rem' }}>
        <dt className="muted">ID</dt>
        <dd>
          <code style={{ fontSize: '0.875em' }}>{runner.id}</code>
        </dd>
        <dt className="muted">Pool</dt>
        <dd>
          {runner.pool_id ? (
            <Link to={`/runners/pools/${runner.pool_id}`}>
              <code>{runner.pool_id}</code>
            </Link>
          ) : (
            '—'
          )}
        </dd>
        <dt className="muted">Status</dt>
        <dd>
          <span className={getStatusPillClass(runner.status)}>{runner.status}</span>
          {runner.status === 'draining' && runner.drain_requested_at ? (
            <span className="muted" style={{ fontSize: '0.875em', marginLeft: '0.5rem' }}>
              since {new Date(runner.drain_requested_at).toLocaleString()}
            </span>
          ) : null}
          {runner.status === 'disabled' && runner.disabled_at ? (
            <span className="muted" style={{ fontSize: '0.875em', marginLeft: '0.5rem' }}>
              since {new Date(runner.disabled_at).toLocaleString()}
            </span>
          ) : null}
          {runner.status === 'revoked' && runner.revoked_at ? (
            <span className="muted" style={{ fontSize: '0.875em', marginLeft: '0.5rem' }}>
              since {new Date(runner.revoked_at).toLocaleString()}
            </span>
          ) : null}
        </dd>
        <dt className="muted">Runner Version</dt>
        <dd>{runner.runner_version || '—'}</dd>
        <dt className="muted">Hostname</dt>
        <dd>{runner.hostname || '—'}</dd>
        <dt className="muted">Last Heartbeat</dt>
        <dd>
          <span className={getHeartbeatClass(heartbeatLabel)}>{heartbeatLabel}</span>
          {runner.last_heartbeat_at ? (
            <span className="muted" style={{ fontSize: '0.875em', marginLeft: '0.5rem' }}>
              {new Date(runner.last_heartbeat_at).toLocaleString()}
            </span>
          ) : null}
        </dd>
        <dt className="muted">Last Seen</dt>
        <dd>
          {runner.last_seen_at ? new Date(runner.last_seen_at).toLocaleString() : 'Never'}
        </dd>
        <dt className="muted">Active Executions</dt>
        <dd>{runner.active_execution_count ?? '—'}</dd>
        <dt className="muted">Registered</dt>
        <dd>{runner.created_at ? new Date(runner.created_at).toLocaleString() : '—'}</dd>
      </dl>
    </section>
  )
}
