import { useQuery } from '@tanstack/react-query'
import { fetchRunnerEligibility } from '../../../features/runners/api'
import { getApiErrorMessage } from '../../../shared/api/client'

const REASON_LABELS: Record<string, string> = {
  ok: 'Runner available',
  no_targets: 'No targets defined on this change',
  no_routes_configured: 'No eligible runner pool — no active connectivity routes are configured',
  route_miss: 'Route miss — no connectivity route matches the change target',
  missing_required_capability:
    'Missing capabilities — the matched pool lacks required runner capabilities',
  multi_pool_unsupported:
    'Cross-pool target mismatch — change targets resolve to different pools',
  pool_draining: 'Pool is draining — not accepting new executions',
  pool_disabled: 'Pool is disabled',
  no_online_runner:
    'No online runner — the pool has no active runner with a recent heartbeat',
}

function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason.replace(/_/g, ' ')
}

interface Props {
  changeId: string
  enabled: boolean
}

export function RunnerEligibilityPanel({ changeId, enabled }: Props) {
  const eligibilityQuery = useQuery({
    queryKey: ['runner-eligibility', changeId],
    queryFn: () => fetchRunnerEligibility(changeId),
    enabled,
    refetchInterval: enabled ? 30000 : false,
  })

  if (!enabled) return null
  if (eligibilityQuery.isLoading) return <p className="muted">Checking runner availability…</p>
  if (eligibilityQuery.error) {
    return (
      <p className="banner banner--error">
        Runner eligibility check failed: {getApiErrorMessage(eligibilityQuery.error)}
      </p>
    )
  }

  const result = eligibilityQuery.data
  if (!result) return null

  const isEligible = result.eligible

  return (
    <div
      className={isEligible ? 'banner banner--info' : 'banner banner--warn'}
      data-testid="runner-eligibility-panel"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
        <strong>Runner Availability</strong>
        <span className={isEligible ? 'pill pill--success' : 'pill pill--danger'}>
          {isEligible ? 'eligible' : 'ineligible'}
        </span>
      </div>

      {!isEligible && result.reason !== 'ok' && (
        <p style={{ margin: '0.25rem 0 0' }}>{reasonLabel(result.reason)}</p>
      )}

      {isEligible && result.pool_key && (
        <dl
          style={{
            display: 'grid',
            gridTemplateColumns: 'max-content 1fr',
            gap: '0.125rem 0.75rem',
            margin: '0.25rem 0 0',
            fontSize: '0.875em',
          }}
        >
          <dt className="muted">Pool</dt>
          <dd>
            <code>{result.pool_key}</code>
          </dd>
          <dt className="muted">Pool status</dt>
          <dd>{result.pool_status ?? '—'}</dd>
          <dt className="muted">Online runners</dt>
          <dd>{result.online_runners_count}</dd>
        </dl>
      )}
    </div>
  )
}
