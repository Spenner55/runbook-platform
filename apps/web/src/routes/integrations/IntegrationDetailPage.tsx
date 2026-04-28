import { useParams, useSearchParams } from 'react-router-dom'

import { useIntegrationDelivery } from '../../features/integrations/hooks/useIntegrationDelivery'
import { useIntegrationDetail } from '../../features/integrations/hooks/useIntegrationDetail'
import type { IntegrationDeliveryAttempt, IntegrationType } from '../../features/integrations/types'
import { getApiErrorMessage } from '../../shared/api/client'

const TYPE_LABELS: Record<IntegrationType, string> = {
  slack_webhook: 'Slack webhook',
  generic_webhook: 'Generic webhook',
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}

function statusLabel(attempt: IntegrationDeliveryAttempt) {
  if (attempt.success) return 'success'
  return 'failed'
}

function responseSummary(attempt: IntegrationDeliveryAttempt) {
  if (attempt.http_status) {
    return `HTTP ${attempt.http_status}`
  }
  return attempt.error_detail || 'No response status'
}

export function IntegrationDetailPage() {
  const { integrationId } = useParams()
  const [searchParams] = useSearchParams()
  const organizationId = searchParams.get('organization_id')
  const detailQuery = useIntegrationDetail(integrationId, organizationId)
  const deliveryQuery = useIntegrationDelivery(integrationId, organizationId)

  if (!organizationId) {
    return <p className="banner banner--error">organization_id is required.</p>
  }

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Integration detail</p>
        <h2>{detailQuery.data?.name ?? 'Integration'}</h2>
        <p className="muted">Delivery history and redacted connection metadata.</p>
      </div>

      {detailQuery.isLoading ? <p className="muted">Loading integration...</p> : null}
      {detailQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(detailQuery.error)}</p>
      ) : null}

      {detailQuery.data ? (
        <div className="detail-grid">
          <div>
            <p className="detail-grid__label">Type</p>
            <p>{TYPE_LABELS[detailQuery.data.type]}</p>
          </div>
          <div>
            <p className="detail-grid__label">Status</p>
            <p>{detailQuery.data.is_active ? 'active' : 'inactive'}</p>
          </div>
          <div>
            <p className="detail-grid__label">Credentials</p>
            <p>
              {detailQuery.data.credentials_configured ? 'configured (masked)' : 'not configured'}
            </p>
          </div>
          <div>
            <p className="detail-grid__label">Events</p>
            <p>
              {detailQuery.data.event_types.length > 0
                ? detailQuery.data.event_types.join(', ')
                : 'all'}
            </p>
          </div>
        </div>
      ) : null}

      <div className="stack-md">
        <h3>Delivery history</h3>
        {deliveryQuery.isLoading ? <p className="muted">Loading delivery attempts...</p> : null}
        {deliveryQuery.error ? (
          <p className="banner banner--error">{getApiErrorMessage(deliveryQuery.error)}</p>
        ) : null}
        {deliveryQuery.data && deliveryQuery.data.results.length === 0 ? (
          <p className="muted">No delivery attempts yet.</p>
        ) : null}
        {deliveryQuery.data && deliveryQuery.data.results.length > 0 ? (
          <ol className="step-list">
            {deliveryQuery.data.results.map((attempt) => (
              <li
                className="step-list__item"
                key={attempt.id}
                style={{ flexDirection: 'column', alignItems: 'stretch' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                  <div>
                    <strong>{attempt.event_type}</strong>
                    <p className="muted">Attempted {formatDateTime(attempt.attempted_at)}</p>
                  </div>
                  <div className="step-list__meta">
                    <span className={attempt.success ? 'pill pill--success' : 'pill pill--danger'}>
                      {statusLabel(attempt)}
                    </span>
                    <span>{responseSummary(attempt)}</span>
                    {attempt.latency_ms !== null ? (
                      <span className="muted">{attempt.latency_ms} ms</span>
                    ) : null}
                  </div>
                </div>
                {attempt.error_detail ? (
                  <p className="banner banner--error">{attempt.error_detail}</p>
                ) : null}
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </section>
  )
}
