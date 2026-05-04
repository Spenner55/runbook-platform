import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../features/auth/context/useAuth'
import { useCreateChange } from '../../features/changes/hooks/useCreateChange'
import { useOperationProfiles } from '../../features/changes/hooks/useOperationProfiles'
import { getApiErrorMessage } from '../../shared/api/client'

interface TargetDraft {
  target_type: string
  target_identifier: string
  display_name: string
}

function normalizeIdentifier(id: string) {
  return id.trim().toLowerCase()
}

function findDuplicateTarget(targets: TargetDraft[]): number | null {
  const seen = new Map<string, number>()
  for (let i = 0; i < targets.length; i++) {
    const key = `${targets[i].target_type}::${normalizeIdentifier(targets[i].target_identifier)}`
    if (seen.has(key)) return i
    seen.set(key, i)
  }
  return null
}

export function ChangeCreatePage() {
  const navigate = useNavigate()
  const { activeOrganizationId } = useAuth()
  const { data: profiles, isLoading: profilesLoading } = useOperationProfiles()
  const createMutation = useCreateChange()

  const [profileKey, setProfileKey] = useState('')
  const [workflowId, setWorkflowId] = useState('')
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [justification, setJustification] = useState('')
  const [requestedInputsJson, setRequestedInputsJson] = useState('{}')
  const [scheduledFor, setScheduledFor] = useState('')
  const [targets, setTargets] = useState<TargetDraft[]>([
    { target_type: '', target_identifier: '', display_name: '' },
  ])
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [inputsError, setInputsError] = useState<string | null>(null)

  const selectedProfile = profiles?.find((p) => p.key === profileKey)

  function handleProfileChange(key: string) {
    const newProfile = profiles?.find((p) => p.key === key)
    const firstType = newProfile?.allowed_target_types[0] ?? ''
    setProfileKey(key)
    setWorkflowId('')
    setTargets([{ target_type: firstType, target_identifier: '', display_name: '' }])
  }

  function updateTarget(index: number, field: keyof TargetDraft, value: string) {
    setTargets((prev) => prev.map((t, i) => (i === index ? { ...t, [field]: value } : t)))
  }

  function addTarget() {
    const firstType = selectedProfile?.allowed_target_types[0] ?? ''
    setTargets((prev) => [
      ...prev,
      { target_type: firstType, target_identifier: '', display_name: '' },
    ])
  }

  function removeTarget(index: number) {
    setTargets((prev) => prev.filter((_, i) => i !== index))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!activeOrganizationId) return
    setErrorMsg(null)
    setInputsError(null)

    let requestedInputs: Record<string, unknown> = {}
    const trimmed = requestedInputsJson.trim()
    if (trimmed && trimmed !== '{}') {
      try {
        const parsed = JSON.parse(trimmed) as unknown
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          setInputsError('Requested inputs must be a JSON object, e.g. {"key": "value"}.')
          return
        }
        requestedInputs = parsed as Record<string, unknown>
      } catch {
        setInputsError('Invalid JSON in requested inputs.')
        return
      }
    }

    const dupIdx = findDuplicateTarget(targets)
    if (dupIdx !== null) {
      setErrorMsg(`Duplicate target at row ${dupIdx + 1}: same type and identifier already exists.`)
      return
    }

    createMutation.mutate(
      {
        operation_profile_key: profileKey,
        workflow_id: workflowId,
        title,
        summary,
        justification,
        requested_inputs: requestedInputs,
        scheduled_for: scheduledFor ? new Date(scheduledFor).toISOString() : null,
        targets: targets.map((t) => ({
          target_type: t.target_type,
          target_identifier: t.target_identifier,
          display_name: t.display_name || undefined,
          environment: 'production',
        })),
      },
      {
        onSuccess: (change) => {
          navigate(`/changes/${change.id}`)
        },
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  if (!activeOrganizationId) return <p>No organization selected.</p>

  const allowedTypes = selectedProfile?.allowed_target_types ?? []

  return (
    <div className="stack-md">
      <div>
        <h2>New Change Request</h2>
        <p className="muted">Create a change dossier for a production operation.</p>
      </div>

      <form className="stack-md" onSubmit={handleSubmit}>
        {/* Operation Profile */}
        <div className="field">
          <label className="field__label" htmlFor="change-profile">
            Operation Profile
          </label>
          {profilesLoading ? (
            <p className="muted">Loading profiles…</p>
          ) : (
            <select
              id="change-profile"
              className="field__input"
              value={profileKey}
              onChange={(e) => handleProfileChange(e.target.value)}
              required
            >
              <option value="">Select a profile…</option>
              {profiles?.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name} ({p.risk_level})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Workflow — constrained to selected profile */}
        {selectedProfile && (
          <div className="field">
            <label className="field__label" htmlFor="change-workflow">
              Workflow
            </label>
            <select
              id="change-workflow"
              className="field__input"
              value={workflowId}
              onChange={(e) => setWorkflowId(e.target.value)}
              required
            >
              <option value="">Select a workflow…</option>
              {selectedProfile.allowed_workflows.map((wf) => (
                <option key={wf.id} value={wf.id}>
                  {wf.name} (v{wf.version})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Title */}
        <div className="field">
          <label className="field__label" htmlFor="change-title">
            Title
          </label>
          <input
            id="change-title"
            className="field__input"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Rotate production database credentials"
            required
          />
        </div>

        {/* Summary */}
        <div className="field">
          <label className="field__label" htmlFor="change-summary">
            Summary
          </label>
          <textarea
            id="change-summary"
            className="field__input"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={2}
            placeholder="Brief description of the operation (optional)"
          />
        </div>

        {/* Justification */}
        <div className="field">
          <label className="field__label" htmlFor="change-justification">
            Justification
          </label>
          <textarea
            id="change-justification"
            className="field__input"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            rows={3}
            placeholder="Why is this change required?"
            required
          />
        </div>

        {/* Requested Inputs */}
        <div className="field">
          <label className="field__label" htmlFor="change-requested-inputs">
            Requested Inputs
          </label>
          <textarea
            id="change-requested-inputs"
            className="field__input"
            value={requestedInputsJson}
            onChange={(e) => {
              setRequestedInputsJson(e.target.value)
              setInputsError(null)
            }}
            rows={4}
            placeholder='{"key": "value"}'
            spellCheck={false}
            aria-describedby={inputsError ? 'inputs-error' : undefined}
          />
          {inputsError && (
            <p id="inputs-error" className="banner banner--error" style={{ marginTop: '0.25rem' }}>
              {inputsError}
            </p>
          )}
        </div>

        {/* Schedule */}
        <div className="field">
          <label className="field__label" htmlFor="change-scheduled-for">
            Scheduled For (optional)
          </label>
          <input
            id="change-scheduled-for"
            className="field__input"
            type="datetime-local"
            value={scheduledFor}
            onChange={(e) => setScheduledFor(e.target.value)}
          />
        </div>

        {/* Production Targets */}
        <fieldset>
          <legend className="field__label">
            Production Targets <span className="muted">(environment is always production)</span>
          </legend>
          <div className="stack-md">
            {targets.map((target, idx) => (
              <div
                key={idx}
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'auto 1fr 1fr auto',
                  gap: '0.5rem',
                  alignItems: 'end',
                }}
                data-testid={`target-row-${idx}`}
              >
                {/* Target type — driven by profile */}
                <div className="field" style={{ margin: 0 }}>
                  <label className="field__label" htmlFor={`target-type-${idx}`}>
                    Type
                  </label>
                  {allowedTypes.length > 0 ? (
                    <select
                      id={`target-type-${idx}`}
                      className="field__input"
                      value={target.target_type}
                      onChange={(e) => updateTarget(idx, 'target_type', e.target.value)}
                      required
                      aria-label={`Target ${idx + 1} type`}
                    >
                      <option value="">Select type…</option>
                      {allowedTypes.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={`target-type-${idx}`}
                      className="field__input"
                      type="text"
                      value={target.target_type}
                      onChange={(e) => updateTarget(idx, 'target_type', e.target.value)}
                      placeholder="e.g. server"
                      required
                      aria-label={`Target ${idx + 1} type`}
                    />
                  )}
                </div>

                {/* Target identifier */}
                <div className="field" style={{ margin: 0 }}>
                  <label className="field__label" htmlFor={`target-identifier-${idx}`}>
                    Identifier
                  </label>
                  <input
                    id={`target-identifier-${idx}`}
                    className="field__input"
                    type="text"
                    value={target.target_identifier}
                    onChange={(e) => updateTarget(idx, 'target_identifier', e.target.value)}
                    placeholder="e.g. prod-web-01"
                    required
                    aria-label={`Target ${idx + 1} identifier`}
                  />
                </div>

                {/* Display name */}
                <div className="field" style={{ margin: 0 }}>
                  <label className="field__label" htmlFor={`target-display-name-${idx}`}>
                    Display name
                  </label>
                  <input
                    id={`target-display-name-${idx}`}
                    className="field__input"
                    type="text"
                    value={target.display_name}
                    onChange={(e) => updateTarget(idx, 'display_name', e.target.value)}
                    placeholder="Optional label"
                    aria-label={`Target ${idx + 1} display name`}
                  />
                </div>

                {/* Remove button — only when more than one target */}
                <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                  {targets.length > 1 && (
                    <button
                      type="button"
                      className="btn"
                      aria-label={`Remove target ${idx + 1}`}
                      onClick={() => removeTarget(idx)}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}

            <button type="button" className="btn" onClick={addTarget}>
              + Add Target
            </button>
          </div>
        </fieldset>

        {errorMsg && <p className="banner banner--error">{errorMsg}</p>}

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn--primary" type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Creating…' : 'Create Change'}
          </button>
          <button className="btn" type="button" onClick={() => navigate(-1)}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
