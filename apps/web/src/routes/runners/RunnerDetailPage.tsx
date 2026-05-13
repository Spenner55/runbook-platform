import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { fetchRunner, drainRunner, revokeRunner } from '../../features/runners/api'
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

  const revokeMutation = useMutation({
    mutationFn: revokeRunner,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runner', runnerId] }),
  })

  if (runnerQuery.isLoading) return <p className="muted">Loading…</p>
  if (runnerQuery.error) return <p className="banner banner--error">{getApiErrorMessage(runnerQuery.error)}</p>

  const runner = runnerQuery.data
  if (!runner) return null

  const heartbeatLabel = getHeartbeatLabel(runner.last_heartbeat_at)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>{runner.display_name}</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="button button--sm"
            type="button"
            disabled={runner.status === 'draining' || runner.status === 'revoked'}
            onClick={() => drainMutation.mutate(runner.id)}
          >
            Drain
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

      <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.25rem 1rem' }}>
        <dt className="muted">Status</dt>
        <dd><span className={getStatusPillClass(runner.status)}>{runner.status}</span></dd>
        <dt className="muted">Last Heartbeat</dt>
        <dd>
          <span className={heartbeatLabel === 'OFFLINE' || heartbeatLabel === 'STALE' ? 'pill pill--danger' : ''}>
            {heartbeatLabel}
          </span>
        </dd>
        <dt className="muted">Version</dt>
        <dd>{runner.runner_version || '—'}</dd>
        <dt className="muted">Hostname</dt>
        <dd>{runner.hostname || '—'}</dd>
        <dt className="muted">Pool</dt>
        <dd>{runner.pool_id}</dd>
        <dt className="muted">ID</dt>
        <dd><code style={{ fontSize: '0.875em' }}>{runner.id}</code></dd>
      </dl>
    </section>
  )
}
