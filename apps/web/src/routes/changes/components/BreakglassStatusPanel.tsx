import { useEffect, useState } from 'react'

import type { BreakglassSession } from '../../../features/changes/types'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function formatCountdown(expiresAt: string): string {
  const now = Date.now()
  const expiry = new Date(expiresAt).getTime()
  const diffMs = expiry - now
  if (diffMs <= 0) return 'Expired'
  const diffSeconds = Math.floor(diffMs / 1000)
  const h = Math.floor(diffSeconds / 3600)
  const m = Math.floor((diffSeconds % 3600) / 60)
  const s = diffSeconds % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function getReviewStatusClass(status: string) {
  if (status === 'overdue' || status === 'blocked') return 'pill pill--danger'
  if (status === 'pending') return 'pill pill--warn'
  if (status === 'accepted' || status === 'submitted') return 'pill pill--success'
  return 'pill'
}

interface BreakglassStatusPanelProps {
  session: BreakglassSession
}

export function BreakglassStatusPanel({ session }: BreakglassStatusPanelProps) {
  const [countdown, setCountdown] = useState(() =>
    session.status === 'active' ? formatCountdown(session.expires_at) : null
  )

  useEffect(() => {
    if (session.status !== 'active') return
    const interval = setInterval(() => {
      setCountdown(formatCountdown(session.expires_at))
    }, 1000)
    return () => clearInterval(interval)
  }, [session.status, session.expires_at])

  const isActive = session.status === 'active'

  return (
    <div
      style={{
        border: `2px solid ${isActive ? 'var(--color-danger, #d00)' : 'var(--color-border, #ccc)'}`,
        borderRadius: '4px',
        padding: '1rem',
      }}
      data-testid="breakglass-status-panel"
      aria-label="Breakglass session status"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <strong>Breakglass Session</strong>
        <span
          className={isActive ? 'pill pill--danger' : 'pill'}
          data-testid="breakglass-status-badge"
        >
          {session.status}
        </span>
        {isActive && countdown && (
          <span
            className={countdown === 'Expired' ? 'pill pill--danger' : 'pill pill--warn'}
            data-testid="breakglass-countdown"
            aria-label={`Expires in ${countdown}`}
          >
            Expires in {countdown}
          </span>
        )}
      </div>

      <dl style={{ display: 'grid', gridTemplateColumns: '180px 1fr', rowGap: '0.25rem', marginTop: '0.75rem' }}>
        <dt className="muted">Started</dt>
        <dd data-testid="breakglass-started-at">{formatDateTime(session.started_at)}</dd>
        <dt className="muted">Expires</dt>
        <dd data-testid="breakglass-expires-at">{formatDateTime(session.expires_at)}</dd>
        {session.ended_at && (
          <>
            <dt className="muted">Ended</dt>
            <dd>{formatDateTime(session.ended_at)}</dd>
            {session.end_reason && (
              <>
                <dt className="muted">End reason</dt>
                <dd>{session.end_reason.replace(/_/g, ' ')}</dd>
              </>
            )}
          </>
        )}
        <dt className="muted">Review due</dt>
        <dd data-testid="breakglass-review-due-at">{formatDateTime(session.review_due_at)}</dd>
        <dt className="muted">Review status</dt>
        <dd>
          <span className={getReviewStatusClass(session.review_status)} data-testid="breakglass-review-status">
            {session.review_status}
          </span>
        </dd>
        {session.reason && (
          <>
            <dt className="muted">Reason</dt>
            <dd style={{ wordBreak: 'break-word' }}>{session.reason}</dd>
          </>
        )}
        <dt className="muted">Scope hash</dt>
        <dd>
          <code>{session.scope_sha256.slice(0, 16)}…</code>
        </dd>
      </dl>
    </div>
  )
}
