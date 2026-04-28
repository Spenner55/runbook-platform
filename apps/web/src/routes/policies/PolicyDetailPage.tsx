import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'

import {
  useCreateRule,
  useDeactivateRule,
  useUpdateRule,
} from '../../features/policies/hooks/usePolicyRules'
import { usePolicyDetail } from '../../features/policies/hooks/usePolicyDetail'
import { useUpdatePolicy } from '../../features/policies/hooks/useUpdatePolicy'
import type { PolicyConditionType, PolicyOutcome, PolicyRule } from '../../features/policies/types'
import { getApiErrorMessage } from '../../shared/api/client'

const OUTCOME_LABELS: Record<PolicyOutcome, string> = {
  approval_required: 'Approval Required',
  auto_approve: 'Auto Approve',
  block: 'Block',
}

const OUTCOME_CLASSES: Record<PolicyOutcome, string> = {
  approval_required: 'pill pill--warn',
  auto_approve: 'pill pill--success',
  block: 'pill pill--danger',
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}

// ---------------------------------------------------------------------------
// Condition param editors
// ---------------------------------------------------------------------------

interface EnumConditionEditorProps {
  params: Record<string, unknown>
  onChange: (params: Record<string, unknown>) => void
}

function EnumConditionEditor({ params, onChange }: EnumConditionEditorProps) {
  const operator = (params.operator as string) || 'in'
  const values = (params.values as string[]) || []
  const value = (params.value as string) || ''

  return (
    <div className="stack-md">
      <div className="field">
        <label className="field__label">Operator</label>
        <select
          className="field__input"
          value={operator}
          onChange={(e) => {
            const op = e.target.value
            if (op === 'in') {
              onChange({ operator: 'in', values: value ? [value] : [] })
            } else {
              onChange({ operator: 'equals', value: values[0] ?? '' })
            }
          }}
        >
          <option value="in">in (list)</option>
          <option value="equals">equals (single)</option>
        </select>
      </div>
      {operator === 'in' ? (
        <div className="field">
          <label className="field__label">Values (comma-separated)</label>
          <input
            className="field__input"
            type="text"
            value={values.join(', ')}
            onChange={(e) =>
              onChange({
                operator: 'in',
                values: e.target.value
                  .split(',')
                  .map((v) => v.trim())
                  .filter(Boolean),
              })
            }
            placeholder="e.g. high, critical"
          />
        </div>
      ) : (
        <div className="field">
          <label className="field__label">Value</label>
          <input
            className="field__input"
            type="text"
            value={value}
            onChange={(e) => onChange({ operator: 'equals', value: e.target.value })}
            placeholder="e.g. high"
          />
        </div>
      )}
    </div>
  )
}

interface TimeWindowEditorProps {
  params: Record<string, unknown>
  onChange: (params: Record<string, unknown>) => void
}

const ALL_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

function TimeWindowEditor({ params, onChange }: TimeWindowEditorProps) {
  const tz = (params.timezone as string) || 'UTC'
  const days = (params.days_of_week as string[]) || []
  const startTime = (params.start_time as string) || '09:00'
  const endTime = (params.end_time as string) || '17:00'
  const matchWhen = (params.match_when as string) || 'inside'

  function update(patch: Partial<Record<string, unknown>>) {
    onChange({
      timezone: tz,
      days_of_week: days,
      start_time: startTime,
      end_time: endTime,
      match_when: matchWhen,
      ...patch,
    })
  }

  return (
    <div className="stack-md">
      <div className="field">
        <label className="field__label">Timezone (IANA)</label>
        <input
          className="field__input"
          type="text"
          value={tz}
          onChange={(e) => update({ timezone: e.target.value })}
          placeholder="e.g. America/Edmonton"
        />
      </div>
      <div className="field">
        <label className="field__label">Days of week</label>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {ALL_DAYS.map((day) => (
            <label key={day} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <input
                type="checkbox"
                checked={days.includes(day)}
                onChange={(e) => {
                  const newDays = e.target.checked ? [...days, day] : days.filter((d) => d !== day)
                  update({ days_of_week: newDays })
                }}
              />
              {day}
            </label>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: '1rem' }}>
        <div className="field">
          <label className="field__label">Start time</label>
          <input
            className="field__input"
            type="time"
            value={startTime}
            onChange={(e) => update({ start_time: e.target.value })}
          />
        </div>
        <div className="field">
          <label className="field__label">End time</label>
          <input
            className="field__input"
            type="time"
            value={endTime}
            onChange={(e) => update({ end_time: e.target.value })}
          />
        </div>
      </div>
      <div className="field">
        <label className="field__label">Match when</label>
        <select
          className="field__input"
          value={matchWhen}
          onChange={(e) => update({ match_when: e.target.value })}
        >
          <option value="inside">Inside window</option>
          <option value="outside">Outside window</option>
        </select>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rule form
// ---------------------------------------------------------------------------

interface RuleFormProps {
  policyId: string
  organizationId: string
  initial?: Partial<PolicyRule>
  onSaved: () => void
  onCancel: () => void
}

function RuleForm({ policyId, organizationId, initial, onSaved, onCancel }: RuleFormProps) {
  const isEdit = Boolean(initial?.id)
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [priority, setPriority] = useState(String(initial?.priority ?? ''))
  const [conditionType, setConditionType] = useState<PolicyConditionType>(
    initial?.condition_type ?? 'risk_level'
  )
  const [conditionParams, setConditionParams] = useState<Record<string, unknown>>(
    initial?.condition_params ?? { operator: 'in', values: [] }
  )
  const [outcome, setOutcome] = useState<PolicyOutcome>(initial?.outcome ?? 'approval_required')
  const [reason, setReason] = useState(initial?.reason ?? '')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const createMutation = useCreateRule(policyId, organizationId)
  const updateMutation = useUpdateRule(policyId, organizationId, initial?.id ?? '')

  function handleConditionTypeChange(ct: PolicyConditionType) {
    setConditionType(ct)
    if (ct === 'time_window') {
      setConditionParams({
        timezone: 'UTC',
        days_of_week: ['mon', 'tue', 'wed', 'thu', 'fri'],
        start_time: '09:00',
        end_time: '17:00',
        match_when: 'inside',
      })
    } else {
      setConditionParams({ operator: 'in', values: [] })
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    const payload = {
      name,
      description,
      priority: Number(priority),
      condition_type: conditionType,
      condition_params: conditionParams,
      outcome,
      reason,
    }
    const mutation = isEdit ? updateMutation : createMutation
    mutation.mutate(payload as never, {
      onSuccess: () => onSaved(),
      onError: (err) => setErrorMsg(getApiErrorMessage(err)),
    })
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <form className="stack-md" onSubmit={handleSubmit}>
      <div className="field">
        <label className="field__label">Rule name</label>
        <input
          className="field__input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>
      <div className="field">
        <label className="field__label">Description</label>
        <textarea
          className="field__input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
        />
      </div>
      <div className="field">
        <label className="field__label">Priority (lower = evaluated first)</label>
        <input
          className="field__input"
          type="number"
          min="1"
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          required
        />
      </div>
      <div className="field">
        <label className="field__label">Condition type</label>
        <select
          className="field__input"
          value={conditionType}
          onChange={(e) => handleConditionTypeChange(e.target.value as PolicyConditionType)}
        >
          <option value="risk_level">Risk level</option>
          <option value="step_type">Step type</option>
          <option value="time_window">Time window</option>
        </select>
      </div>
      {conditionType === 'time_window' ? (
        <TimeWindowEditor params={conditionParams} onChange={setConditionParams} />
      ) : (
        <EnumConditionEditor params={conditionParams} onChange={setConditionParams} />
      )}
      <div className="field">
        <label className="field__label">Outcome</label>
        <select
          className="field__input"
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as PolicyOutcome)}
        >
          <option value="approval_required">Approval Required</option>
          <option value="auto_approve">Auto Approve</option>
          <option value="block">Block</option>
        </select>
      </div>
      <div className="field">
        <label className="field__label">Reason (shown in evaluation records)</label>
        <textarea
          className="field__input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
        />
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button type="submit" className="btn btn--primary" disabled={isPending}>
          {isPending ? 'Saving…' : isEdit ? 'Save rule' : 'Add rule'}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Rule row
// ---------------------------------------------------------------------------

interface RuleRowProps {
  rule: PolicyRule
  policyId: string
  organizationId: string
  onChanged: () => void
}

function RuleRow({ rule, policyId, organizationId, onChanged }: RuleRowProps) {
  const [editing, setEditing] = useState(false)
  const deactivateMutation = useDeactivateRule(policyId, organizationId, rule.id)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleDeactivate() {
    setErrorMsg(null)
    deactivateMutation.mutate(undefined, {
      onSuccess: onChanged,
      onError: (err) => setErrorMsg(getApiErrorMessage(err)),
    })
  }

  if (editing) {
    return (
      <li className="step-list__item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
        <RuleForm
          policyId={policyId}
          organizationId={organizationId}
          initial={rule}
          onSaved={() => {
            setEditing(false)
            onChanged()
          }}
          onCancel={() => setEditing(false)}
        />
      </li>
    )
  }

  return (
    <li className="step-list__item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
        <div>
          <strong>{rule.name}</strong>
          <p className="muted">
            Priority {rule.priority} · {rule.condition_type}
            {rule.reason ? ` · "${rule.reason}"` : ''}
          </p>
          {rule.description ? <p className="muted">{rule.description}</p> : null}
        </div>
        <div className="step-list__meta">
          <span className={OUTCOME_CLASSES[rule.outcome]}>{OUTCOME_LABELS[rule.outcome]}</span>
          <span className={rule.is_active ? 'pill pill--success' : 'pill'}>
            {rule.is_active ? 'active' : 'inactive'}
          </span>
          <button className="btn" onClick={() => setEditing(true)}>
            Edit
          </button>
          {rule.is_active ? (
            <button
              className="btn"
              onClick={handleDeactivate}
              disabled={deactivateMutation.isPending}
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

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function PolicyDetailPage() {
  const { policyId } = useParams()
  const [searchParams] = useSearchParams()
  const organizationId = searchParams.get('organization_id') ?? ''
  const query = usePolicyDetail(policyId ?? null, organizationId || null)
  const [showEditMeta, setShowEditMeta] = useState(false)
  const [showAddRule, setShowAddRule] = useState(false)
  const [metaName, setMetaName] = useState('')
  const [metaDescription, setMetaDescription] = useState('')
  const [metaError, setMetaError] = useState<string | null>(null)

  const updateMutation = useUpdatePolicy(policyId ?? '', organizationId)

  function openEditMeta() {
    setMetaName(query.data?.name ?? '')
    setMetaDescription(query.data?.description ?? '')
    setMetaError(null)
    setShowEditMeta(true)
  }

  function handleSaveMeta(e: React.FormEvent) {
    e.preventDefault()
    setMetaError(null)
    updateMutation.mutate(
      { name: metaName, description: metaDescription },
      {
        onSuccess: () => setShowEditMeta(false),
        onError: (err) => setMetaError(getApiErrorMessage(err)),
      }
    )
  }

  if (!organizationId) {
    return (
      <section className="panel">
        <p className="banner banner--error">
          organization_id is required to manage policy details.
        </p>
      </section>
    )
  }

  if (query.isLoading) {
    return (
      <section className="panel">
        <p className="muted">Loading policy…</p>
      </section>
    )
  }

  if (query.error) {
    return (
      <section className="panel">
        <p className="banner banner--error">{getApiErrorMessage(query.error)}</p>
      </section>
    )
  }

  const policy = query.data
  if (!policy) return null

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Phase 10.2 · Policy</p>
        <h2>{policy.name}</h2>
        {policy.description ? <p className="muted">{policy.description}</p> : null}
        <p className="muted">
          <span className={policy.is_active ? 'pill pill--success' : 'pill'}>
            {policy.is_active ? 'active' : 'inactive'}
          </span>{' '}
          · updated {formatDateTime(policy.updated_at)}
        </p>
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
          <button className="btn" onClick={openEditMeta}>
            Edit details
          </button>
          <button
            className="btn"
            onClick={() =>
              updateMutation.mutate({ is_active: !policy.is_active }, { onError: () => {} })
            }
          >
            {policy.is_active ? 'Deactivate policy' : 'Activate policy'}
          </button>
        </div>
      </div>

      {showEditMeta ? (
        <form className="stack-md" onSubmit={handleSaveMeta}>
          <div className="field">
            <label className="field__label" htmlFor="policy-detail-name">
              Name
            </label>
            <input
              id="policy-detail-name"
              className="field__input"
              type="text"
              value={metaName}
              onChange={(e) => setMetaName(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="policy-detail-description">
              Description
            </label>
            <textarea
              id="policy-detail-description"
              className="field__input"
              value={metaDescription}
              onChange={(e) => setMetaDescription(e.target.value)}
              rows={2}
            />
          </div>
          {metaError ? <p className="banner banner--error">{metaError}</p> : null}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button type="submit" className="btn btn--primary" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="btn" onClick={() => setShowEditMeta(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      <div className="stack-md">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>Rules ({policy.rules.length})</h3>
          {!showAddRule ? (
            <button className="btn btn--primary" onClick={() => setShowAddRule(true)}>
              Add rule
            </button>
          ) : null}
        </div>

        {showAddRule ? (
          <div className="step-list__item" style={{ flexDirection: 'column' }}>
            <RuleForm
              policyId={policy.id}
              organizationId={organizationId}
              onSaved={() => {
                setShowAddRule(false)
                query.refetch()
              }}
              onCancel={() => setShowAddRule(false)}
            />
          </div>
        ) : null}

        {policy.rules.length === 0 ? (
          <p className="muted">No rules yet. Add a rule to start enforcing policy decisions.</p>
        ) : (
          <ol className="step-list">
            {policy.rules.map((rule) => (
              <RuleRow
                key={rule.id}
                rule={rule}
                policyId={policy.id}
                organizationId={organizationId}
                onChanged={() => query.refetch()}
              />
            ))}
          </ol>
        )}
      </div>
    </section>
  )
}
