import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../features/auth/context/useAuth'
import { useCreatePolicy } from '../../features/policies/hooks/useCreatePolicy'
import { usePolicies } from '../../features/policies/hooks/usePolicies'
import { useUpdatePolicy } from '../../features/policies/hooks/useUpdatePolicy'
import type { Policy } from '../../features/policies/types'
import { getApiErrorMessage } from '../../shared/api/client'

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}

interface PolicyRowProps {
  policy: Policy
  organizationId: string
  onUpdated: () => void
}

function PolicyRow({ policy, organizationId, onUpdated }: PolicyRowProps) {
  const navigate = useNavigate()
  const updateMutation = useUpdatePolicy(policy.id, organizationId)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleToggleActive() {
    setErrorMsg(null)
    updateMutation.mutate(
      { is_active: !policy.is_active },
      {
        onSuccess: onUpdated,
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <li className="step-list__item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
        <div>
          <strong>{policy.name}</strong>
          {policy.description ? <p className="muted">{policy.description}</p> : null}
          <p className="muted">
            {policy.rule_count} rule{policy.rule_count !== 1 ? 's' : ''} · updated{' '}
            {formatDateTime(policy.updated_at)}
          </p>
        </div>
        <div className="step-list__meta">
          <span className={policy.is_active ? 'pill pill--success' : 'pill'}>
            {policy.is_active ? 'active' : 'inactive'}
          </span>
          <button className="btn" onClick={() => navigate(`/policies/${policy.id}`)}>
            Manage rules
          </button>
          <button className="btn" disabled={updateMutation.isPending} onClick={handleToggleActive}>
            {policy.is_active ? 'Deactivate' : 'Activate'}
          </button>
        </div>
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
    </li>
  )
}

interface CreatePolicyFormProps {
  organizationId: string
  onCreated: () => void
  onCancel: () => void
}

function CreatePolicyForm({ organizationId, onCreated, onCancel }: CreatePolicyFormProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const createMutation = useCreatePolicy(organizationId)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    createMutation.mutate(
      { organization_id: organizationId, name, description },
      {
        onSuccess: () => {
          onCreated()
        },
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <form className="stack-md" onSubmit={handleSubmit}>
      <div className="field">
        <label className="field__label" htmlFor="policy-name">
          Policy name
        </label>
        <input
          id="policy-name"
          className="field__input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Production safety policy"
          required
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="policy-description">
          Description (optional)
        </label>
        <textarea
          id="policy-description"
          className="field__input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          placeholder="What does this policy do?"
        />
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button type="submit" className="btn btn--primary" disabled={createMutation.isPending}>
          {createMutation.isPending ? 'Creating…' : 'Create policy'}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export function PoliciesPage() {
  const { activeOrganizationId } = useAuth()
  const [isActiveFilter, setIsActiveFilter] = useState<'true' | 'false' | 'all'>('all')
  const [showCreateForm, setShowCreateForm] = useState(false)

  const query = usePolicies(activeOrganizationId, isActiveFilter)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Phase 10.2</p>
        <h2>Policies</h2>
        <p className="muted">
          Manage execution policies that determine whether steps require approval, auto-proceed, or
          are blocked.
        </p>
      </div>

      <div className="filter-row">
        <div className="field">
          <label className="field__label" htmlFor="active-filter">
            Show
          </label>
          <select
            id="active-filter"
            className="field__input"
            value={isActiveFilter}
            onChange={(e) => setIsActiveFilter(e.target.value as 'true' | 'false' | 'all')}
          >
            <option value="all">All policies</option>
            <option value="true">Active only</option>
            <option value="false">Inactive only</option>
          </select>
        </div>
      </div>

      {!activeOrganizationId ? <p className="muted">No active organization selected.</p> : null}

      {activeOrganizationId && !showCreateForm ? (
        <button
          className="btn btn--primary"
          style={{ alignSelf: 'flex-start' }}
          onClick={() => setShowCreateForm(true)}
        >
          Create policy
        </button>
      ) : null}

      {showCreateForm ? (
        <CreatePolicyForm
          organizationId={activeOrganizationId ?? ''}
          onCreated={() => {
            setShowCreateForm(false)
            query.refetch()
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      ) : null}

      {query.isLoading ? <p className="muted">Loading policies…</p> : null}

      {query.error ? (
        <p className="banner banner--error">{getApiErrorMessage(query.error)}</p>
      ) : null}

      {query.data && (query.data.results?.length ?? 0) === 0 ? (
        <p className="muted">No policies found.</p>
      ) : null}

      {query.data && (query.data.results?.length ?? 0) > 0 ? (
        <ol className="step-list">
          {query.data.results.map((policy) => (
            <PolicyRow
              key={policy.id}
              policy={policy}
              organizationId={activeOrganizationId ?? ''}
              onUpdated={() => query.refetch()}
            />
          ))}
        </ol>
      ) : null}
    </section>
  )
}
