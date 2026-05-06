import { useState } from 'react'

import { useAuth } from '../../features/auth/context/useAuth'
import { useCreateFreezeRule } from '../../features/freeze-rules/hooks/useCreateFreezeRule'
import { useDeactivateFreezeRule } from '../../features/freeze-rules/hooks/useDeactivateFreezeRule'
import { useFreezeRules } from '../../features/freeze-rules/hooks/useFreezeRules'
import type {
  CreateFreezeRuleInput,
  FreezeRule,
  FreezeRuleBehavior,
  FreezeRuleScopeType,
} from '../../features/freeze-rules/types'
import { getApiErrorMessage } from '../../shared/api/client'

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}

function scopeLabel(rule: FreezeRule): string {
  if (rule.scope_type === 'all_production') return 'All production'
  if (rule.scope_type === 'target_type') return rule.target_type || 'Target type'
  if (rule.scope_type === 'target_identifier') return rule.target_identifier || 'Target identifier'
  return rule.scope_type
}

function behaviorLabel(behavior: FreezeRuleBehavior): string {
  return behavior === 'block' ? 'Block' : 'Allow with exception'
}

interface FreezeRuleRowProps {
  rule: FreezeRule
  isAdmin: boolean
  onUpdated: () => void
}

function FreezeRuleRow({ rule, isAdmin, onUpdated }: FreezeRuleRowProps) {
  const { activeOrganizationId } = useAuth()
  const deactivateMutation = useDeactivateFreezeRule(activeOrganizationId ?? '')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleDeactivate() {
    setErrorMsg(null)
    deactivateMutation.mutate(rule.id, {
      onSuccess: onUpdated,
      onError: (err) => setErrorMsg(getApiErrorMessage(err)),
    })
  }

  return (
    <li className="step-list__item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
        <div>
          <strong>{rule.name}</strong>
          {rule.description ? <p className="muted">{rule.description}</p> : null}
          <p className="muted">
            {behaviorLabel(rule.behavior)} · {scopeLabel(rule)} · {formatDateTime(rule.starts_at)} –{' '}
            {formatDateTime(rule.ends_at)}
          </p>
          {rule.requires_exception_reference ? (
            <p className="muted">Exception reference required</p>
          ) : null}
        </div>
        <div className="step-list__meta">
          <span className={rule.is_active ? 'pill pill--success' : 'pill'}>
            {rule.is_active ? 'active' : 'inactive'}
          </span>
          {isAdmin && rule.is_active ? (
            <button
              className="btn"
              disabled={deactivateMutation.isPending}
              onClick={handleDeactivate}
            >
              Deactivate
            </button>
          ) : null}
        </div>
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
    </li>
  )
}

interface CreateFreezeRuleFormProps {
  organizationId: string
  onCreated: () => void
  onCancel: () => void
}

function CreateFreezeRuleForm({ organizationId, onCreated, onCancel }: CreateFreezeRuleFormProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [behavior, setBehavior] = useState<FreezeRuleBehavior>('block')
  const [scopeType, setScopeType] = useState<FreezeRuleScopeType>('all_production')
  const [targetType, setTargetType] = useState('')
  const [targetIdentifier, setTargetIdentifier] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [requiresExceptionRef, setRequiresExceptionRef] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const createMutation = useCreateFreezeRule(organizationId)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)

    const input: CreateFreezeRuleInput = {
      organization_id: organizationId,
      name,
      description,
      behavior,
      starts_at: startsAt,
      ends_at: endsAt,
      scope_type: scopeType,
      target_type: targetType,
      target_identifier: targetIdentifier,
      requires_exception_reference: requiresExceptionRef,
    }

    createMutation.mutate(input, {
      onSuccess: onCreated,
      onError: (err) => setErrorMsg(getApiErrorMessage(err)),
    })
  }

  return (
    <form className="stack-md" onSubmit={handleSubmit}>
      <div className="field">
        <label className="field__label" htmlFor="rule-name">
          Name
        </label>
        <input
          id="rule-name"
          className="field__input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Holiday freeze"
          required
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="rule-description">
          Description (optional)
        </label>
        <textarea
          id="rule-description"
          className="field__input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="rule-behavior">
          Behavior
        </label>
        <select
          id="rule-behavior"
          className="field__input"
          value={behavior}
          onChange={(e) => setBehavior(e.target.value as FreezeRuleBehavior)}
        >
          <option value="block">Block</option>
          <option value="allow_with_exception">Allow with exception</option>
        </select>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="rule-scope-type">
          Scope
        </label>
        <select
          id="rule-scope-type"
          className="field__input"
          value={scopeType}
          onChange={(e) => setScopeType(e.target.value as FreezeRuleScopeType)}
        >
          <option value="all_production">All production</option>
          <option value="target_type">Target type</option>
          <option value="target_identifier">Target identifier</option>
        </select>
      </div>
      {scopeType === 'target_type' ? (
        <div className="field">
          <label className="field__label" htmlFor="rule-target-type">
            Target type
          </label>
          <input
            id="rule-target-type"
            className="field__input"
            type="text"
            value={targetType}
            onChange={(e) => setTargetType(e.target.value)}
            placeholder="e.g. database"
          />
        </div>
      ) : null}
      {scopeType === 'target_identifier' ? (
        <div className="field">
          <label className="field__label" htmlFor="rule-target-identifier">
            Target identifier
          </label>
          <input
            id="rule-target-identifier"
            className="field__input"
            type="text"
            value={targetIdentifier}
            onChange={(e) => setTargetIdentifier(e.target.value)}
            placeholder="e.g. prod-db-primary"
          />
        </div>
      ) : null}
      <div className="field">
        <label className="field__label" htmlFor="rule-starts-at">
          Starts at
        </label>
        <input
          id="rule-starts-at"
          className="field__input"
          type="datetime-local"
          value={startsAt}
          onChange={(e) => setStartsAt(e.target.value)}
          required
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="rule-ends-at">
          Ends at
        </label>
        <input
          id="rule-ends-at"
          className="field__input"
          type="datetime-local"
          value={endsAt}
          onChange={(e) => setEndsAt(e.target.value)}
          required
        />
      </div>
      <div className="field">
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            type="checkbox"
            checked={requiresExceptionRef}
            onChange={(e) => setRequiresExceptionRef(e.target.checked)}
          />
          Require exception reference
        </label>
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button type="submit" className="btn btn--primary" disabled={createMutation.isPending}>
          {createMutation.isPending ? 'Creating…' : 'Create freeze rule'}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export function FreezeRulesPage() {
  const { user, activeOrganizationId } = useAuth()
  const [isActiveFilter, setIsActiveFilter] = useState<'true' | 'false' | 'all'>('all')
  const [showCreateForm, setShowCreateForm] = useState(false)

  const activeMembership = user?.memberships.find((m) => m.organization.id === activeOrganizationId)
  const isAdmin = activeMembership?.role === 'owner' || activeMembership?.role === 'admin'

  const query = useFreezeRules(activeOrganizationId, isActiveFilter)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>Freeze Rules</h2>
        <p className="muted">
          Freeze rules block or restrict change dispatches during defined time windows.
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
            <option value="all">All rules</option>
            <option value="true">Active only</option>
            <option value="false">Inactive only</option>
          </select>
        </div>
      </div>

      {!activeOrganizationId ? <p className="muted">No active organization selected.</p> : null}

      {activeOrganizationId && isAdmin && !showCreateForm ? (
        <button
          className="btn btn--primary"
          style={{ alignSelf: 'flex-start' }}
          onClick={() => setShowCreateForm(true)}
        >
          Create freeze rule
        </button>
      ) : null}

      {showCreateForm ? (
        <CreateFreezeRuleForm
          organizationId={activeOrganizationId ?? ''}
          onCreated={() => {
            setShowCreateForm(false)
            query.refetch()
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      ) : null}

      {query.isLoading ? <p className="muted">Loading freeze rules…</p> : null}

      {query.error ? (
        <p className="banner banner--error">{getApiErrorMessage(query.error)}</p>
      ) : null}

      {query.data && (query.data.results?.length ?? 0) === 0 ? (
        <p className="muted">No freeze rules found.</p>
      ) : null}

      {query.data && (query.data.results?.length ?? 0) > 0 ? (
        <ol className="step-list">
          {query.data.results.map((rule) => (
            <FreezeRuleRow
              key={rule.id}
              rule={rule}
              isAdmin={isAdmin ?? false}
              onUpdated={() => query.refetch()}
            />
          ))}
        </ol>
      ) : null}
    </section>
  )
}
