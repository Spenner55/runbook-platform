import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../features/auth/context/useAuth'
import { useCreateChange } from '../../features/changes/hooks/useCreateChange'
import { useOperationProfiles } from '../../features/changes/hooks/useOperationProfiles'
import { getApiErrorMessage } from '../../shared/api/client'

export function ChangeCreatePage() {
  const navigate = useNavigate()
  const { activeOrganizationId } = useAuth()
  const { data: profiles, isLoading: profilesLoading } = useOperationProfiles()
  const createMutation = useCreateChange()

  const [profileKey, setProfileKey] = useState('')
  const [workflowId, setWorkflowId] = useState('')
  const [title, setTitle] = useState('')
  const [justification, setJustification] = useState('')
  const [targetType, setTargetType] = useState('server')
  const [targetIdentifier, setTargetIdentifier] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const selectedProfile = profiles?.find((p) => p.key === profileKey)

  function handleProfileChange(key: string) {
    setProfileKey(key)
    setWorkflowId('')
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!activeOrganizationId) return
    setErrorMsg(null)

    createMutation.mutate(
      {
        operation_profile_key: profileKey,
        workflow_id: workflowId,
        title,
        justification,
        targets: [
          {
            target_type: targetType,
            target_identifier: targetIdentifier,
            environment: 'production',
          },
        ],
      },
      {
        onSuccess: (change) => {
          navigate(`/changes/${change.id}`)
        },
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      },
    )
  }

  if (!activeOrganizationId) return <p>No organization selected.</p>

  return (
    <div className="stack-md">
      <div>
        <h2>New Change Request</h2>
        <p className="muted">Create a change dossier for a production operation.</p>
      </div>

      <form className="stack-md" onSubmit={handleSubmit}>
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
            placeholder="e.g. Restart nginx on prod-01"
            required
          />
        </div>

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

        <fieldset>
          <legend className="field__label">Target</legend>
          <div className="stack-md">
            <div className="field">
              <label className="field__label" htmlFor="target-type">
                Target type
              </label>
              <select
                id="target-type"
                className="field__input"
                value={targetType}
                onChange={(e) => setTargetType(e.target.value)}
                required
              >
                {(selectedProfile?.allowed_target_types ?? ['server']).map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="target-identifier">
                Target identifier
              </label>
              <input
                id="target-identifier"
                className="field__input"
                type="text"
                value={targetIdentifier}
                onChange={(e) => setTargetIdentifier(e.target.value)}
                placeholder="e.g. prod-web-01"
                required
              />
            </div>
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
