import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useCreateIntegration } from '../../features/integrations/hooks/useCreateIntegration'
import { useDeactivateIntegration } from '../../features/integrations/hooks/useDeactivateIntegration'
import { useIntegrations } from '../../features/integrations/hooks/useIntegrations'
import type { IntegrationConnection, IntegrationType } from '../../features/integrations/types'
import { getApiErrorMessage } from '../../shared/api/client'

const TYPE_LABELS: Record<IntegrationType, string> = {
  slack_webhook: 'Slack webhook',
  generic_webhook: 'Generic webhook',
}

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Never'
}

function parseEventTypes(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

interface IntegrationRowProps {
  integration: IntegrationConnection
  organizationId: string
  onChanged: () => void
}

function IntegrationRow({ integration, organizationId, onChanged }: IntegrationRowProps) {
  const navigate = useNavigate()
  const deactivateMutation = useDeactivateIntegration(integration.id, organizationId)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleDeactivate() {
    setErrorMsg(null)
    deactivateMutation.mutate(undefined, {
      onSuccess: onChanged,
      onError: (err) => setErrorMsg(getApiErrorMessage(err)),
    })
  }

  return (
    <li className="step-list__item" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
        <div className="stack-md">
          <div>
            <strong>{integration.name}</strong>
            <p className="muted">{TYPE_LABELS[integration.type]}</p>
          </div>
          <p className="muted">
            Credentials {integration.credentials_configured ? 'configured' : 'not configured'} -
            masked in API responses
          </p>
          <p className="muted">
            Events:{' '}
            {integration.event_types.length > 0 ? integration.event_types.join(', ') : 'all'}
          </p>
        </div>
        <div className="step-list__meta">
          <span className={integration.is_active ? 'pill pill--success' : 'pill'}>
            {integration.is_active ? 'active' : 'inactive'}
          </span>
          {integration.last_delivery_status ? (
            <span
              className={
                integration.last_delivery_status === 'success'
                  ? 'pill pill--success'
                  : 'pill pill--danger'
              }
            >
              last {integration.last_delivery_status}
            </span>
          ) : null}
          <span className="muted">
            Last delivery: {formatDateTime(integration.last_delivery_at)}
          </span>
          <button
            className="button button--secondary"
            onClick={() =>
              navigate(`/integrations/${integration.id}?organization_id=${organizationId}`)
            }
          >
            View history
          </button>
          <button
            className="button button--secondary"
            disabled={!integration.is_active || deactivateMutation.isPending}
            onClick={handleDeactivate}
          >
            {deactivateMutation.isPending ? 'Deactivating...' : 'Deactivate'}
          </button>
        </div>
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
    </li>
  )
}

interface CreateIntegrationFormProps {
  organizationId: string
  onCreated: () => void
  onCancel: () => void
}

function CreateIntegrationForm({
  organizationId,
  onCreated,
  onCancel,
}: CreateIntegrationFormProps) {
  const [name, setName] = useState('')
  const [type, setType] = useState<IntegrationType>('slack_webhook')
  const [webhookUrl, setWebhookUrl] = useState('')
  const [eventTypes, setEventTypes] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const createMutation = useCreateIntegration(organizationId)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    createMutation.mutate(
      {
        organization_id: organizationId,
        type,
        name,
        credentials: { url: webhookUrl },
        config: {},
        event_types: parseEventTypes(eventTypes),
      },
      {
        onSuccess: () => {
          setWebhookUrl('')
          setName('')
          setEventTypes('')
          onCreated()
        },
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <form className="stack-md" onSubmit={handleSubmit}>
      <div className="field">
        <label className="field__label" htmlFor="integration-name">
          Name
        </label>
        <input
          id="integration-name"
          className="input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Production alerts"
          required
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="integration-type">
          Type
        </label>
        <select
          id="integration-type"
          className="input"
          value={type}
          onChange={(e) => setType(e.target.value as IntegrationType)}
        >
          <option value="slack_webhook">Slack webhook</option>
          <option value="generic_webhook">Generic webhook</option>
        </select>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="integration-webhook-url">
          Webhook URL
        </label>
        <input
          id="integration-webhook-url"
          className="input"
          type="url"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://hooks.example.com/services/..."
          autoComplete="off"
          required
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="integration-event-types">
          Event types (optional)
        </label>
        <input
          id="integration-event-types"
          className="input"
          type="text"
          value={eventTypes}
          onChange={(e) => setEventTypes(e.target.value)}
          placeholder="execution.failed, approval.requested"
        />
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
      <div className="actions-row">
        <button className="button" type="submit" disabled={createMutation.isPending}>
          {createMutation.isPending ? 'Creating...' : 'Create integration'}
        </button>
        <button className="button button--secondary" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export function IntegrationsPage() {
  const [orgId, setOrgId] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const query = useIntegrations(orgId || null)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Phase 10.5</p>
        <h2>Integrations</h2>
        <p className="muted">
          Manage outbound notification connections controlled by the Django API.
        </p>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="org-id">
          Organization ID
        </label>
        <input
          id="org-id"
          className="input"
          type="text"
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          placeholder="Paste an organization UUID"
        />
      </div>

      {!orgId ? <p className="muted">Enter an organization ID to load integrations.</p> : null}

      {orgId && !showCreateForm ? (
        <button
          className="button"
          style={{ justifySelf: 'start' }}
          onClick={() => setShowCreateForm(true)}
        >
          Create integration
        </button>
      ) : null}

      {showCreateForm ? (
        <CreateIntegrationForm
          organizationId={orgId}
          onCreated={() => {
            setShowCreateForm(false)
            query.refetch()
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      ) : null}

      {query.isLoading ? <p className="muted">Loading integrations...</p> : null}

      {query.error ? (
        <p className="banner banner--error">{getApiErrorMessage(query.error)}</p>
      ) : null}

      {query.data && query.data.length === 0 ? (
        <p className="muted">No integrations configured.</p>
      ) : null}

      {query.data && query.data.length > 0 ? (
        <ol className="step-list">
          {query.data.map((integration) => (
            <IntegrationRow
              key={integration.id}
              integration={integration}
              organizationId={orgId}
              onChanged={() => query.refetch()}
            />
          ))}
        </ol>
      ) : null}
    </section>
  )
}
