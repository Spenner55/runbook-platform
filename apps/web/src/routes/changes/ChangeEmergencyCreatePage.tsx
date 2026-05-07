import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../../features/auth/context/useAuth'
import { useCreateChange } from '../../features/changes/hooks/useCreateChange'
import { useOperationProfiles } from '../../features/changes/hooks/useOperationProfiles'
import { getApiErrorMessage } from '../../shared/api/client'

interface TargetDraft {
  target_type: string
  target_identifier: string
  display_name: string
}

export function ChangeEmergencyCreatePage() {
  const navigate = useNavigate()
  const { activeOrganizationId } = useAuth()
  const { data: profiles, isLoading: profilesLoading } = useOperationProfiles()
  const createMutation = useCreateChange()

  const [profileKey, setProfileKey] = useState('')
  const [workflowId, setWorkflowId] = useState('')
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [justification, setJustification] = useState('')
  const [emergencyReason, setEmergencyReason] = useState('')
  const [requestedInputsJson, setRequestedInputsJson] = useState('{}')
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
          setInputsError('Requested inputs must be a JSON object.')
          return
        }
        requestedInputs = parsed as Record<string, unknown>
      } catch {
        setInputsError('Invalid JSON in requested inputs.')
        return
      }
    }

    createMutation.mutate(
      {
        operation_profile_key: profileKey,
        workflow_id: workflowId,
        title,
        summary,
        justification,
        requested_inputs: requestedInputs,
        targets: targets.map((t) => ({
          target_type: t.target_type,
          target_identifier: t.target_identifier,
          display_name: t.display_name || undefined,
          environment: 'production',
        })),
        is_emergency: true,
        emergency_reason: emergencyReason,
      },
      {
        onSuccess: (change) => navigate(`/changes/${change.id}`),
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  if (!activeOrganizationId) return <p>No organization selected.</p>

  const allowedTypes = selectedProfile?.allowed_target_types ?? []

  return (
    <div className="stack-md">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <h2>Emergency Change Request</h2>
          <Link to="/changes/new" className="muted">
            Standard change instead
          </Link>
        </div>
        <div className="banner banner--warning" role="alert">
          <strong>Emergency mode:</strong> This change will be flagged as emergency and will
          require a mandatory retro-review after completion. Ensure the emergency reason is
          accurate and specific.
        </div>
      </div>

      <form className="stack-md" onSubmit={handleSubmit}>
        <div className="field">
          <label className="field__label" htmlFor="emergency-reason">
            Emergency Reason <span className="muted">(required)</span>
          </label>
          <textarea
            id="emergency-reason"
            className="field__input"
            value={emergencyReason}
            onChange={(e) => setEmergencyReason(e.target.value)}
            rows={3}
            required
            placeholder="Describe the emergency that requires this change to bypass normal scheduling…"
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="emergency-change-profile">
            Operation Profile
          </label>
          {profilesLoading ? (
            <p className="muted">Loading profiles…</p>
          ) : (
            <select
              id="emergency-change-profile"
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

        {selectedProfile && (
          <div className="field">
            <label className="field__label" htmlFor="emergency-change-workflow">
              Workflow
            </label>
            <select
              id="emergency-change-workflow"
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

        <div className="field">
          <label className="field__label" htmlFor="emergency-change-title">
            Title
          </label>
          <input
            id="emergency-change-title"
            className="field__input"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Emergency credential rotation due to incident"
            required
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="emergency-change-summary">
            Summary
          </label>
          <textarea
            id="emergency-change-summary"
            className="field__input"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={2}
            placeholder="Brief description"
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="emergency-change-justification">
            Justification
          </label>
          <textarea
            id="emergency-change-justification"
            className="field__input"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            rows={3}
            placeholder="Why is this change required?"
            required
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="emergency-requested-inputs">
            Requested Inputs
          </label>
          <textarea
            id="emergency-requested-inputs"
            className="field__input"
            value={requestedInputsJson}
            onChange={(e) => {
              setRequestedInputsJson(e.target.value)
              setInputsError(null)
            }}
            rows={4}
            placeholder='{"key": "value"}'
            spellCheck={false}
          />
          {inputsError && <p className="banner banner--error">{inputsError}</p>}
        </div>

        <fieldset>
          <legend className="field__label">Production Targets</legend>
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
                <div className="field" style={{ margin: 0 }}>
                  <label className="field__label" htmlFor={`emergency-target-type-${idx}`}>
                    Type
                  </label>
                  {allowedTypes.length > 0 ? (
                    <select
                      id={`emergency-target-type-${idx}`}
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
                      id={`emergency-target-type-${idx}`}
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

                <div className="field" style={{ margin: 0 }}>
                  <label className="field__label" htmlFor={`emergency-target-identifier-${idx}`}>
                    Identifier
                  </label>
                  <input
                    id={`emergency-target-identifier-${idx}`}
                    className="field__input"
                    type="text"
                    value={target.target_identifier}
                    onChange={(e) => updateTarget(idx, 'target_identifier', e.target.value)}
                    placeholder="e.g. prod-web-01"
                    required
                    aria-label={`Target ${idx + 1} identifier`}
                  />
                </div>

                <div className="field" style={{ margin: 0 }}>
                  <label className="field__label" htmlFor={`emergency-target-display-name-${idx}`}>
                    Display name
                  </label>
                  <input
                    id={`emergency-target-display-name-${idx}`}
                    className="field__input"
                    type="text"
                    value={target.display_name}
                    onChange={(e) => updateTarget(idx, 'display_name', e.target.value)}
                    placeholder="Optional label"
                    aria-label={`Target ${idx + 1} display name`}
                  />
                </div>

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
          <button
            className="btn btn--primary"
            type="submit"
            disabled={createMutation.isPending}
            style={{ background: 'var(--color-danger, #d00)', borderColor: 'var(--color-danger, #d00)' }}
          >
            {createMutation.isPending ? 'Creating…' : 'Create Emergency Change'}
          </button>
          <button className="btn" type="button" onClick={() => navigate(-1)}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
