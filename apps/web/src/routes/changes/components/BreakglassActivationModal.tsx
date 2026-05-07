import { useState } from 'react'

import { useActivateBreakglass } from '../../../features/changes/hooks/useActivateBreakglass'
import type { BreakglassSession } from '../../../features/changes/types'
import { getApiErrorMessage } from '../../../shared/api/client'

interface BreakglassActivationModalProps {
  changeId: string
  onSuccess?: (session: BreakglassSession) => void
  onClose: () => void
}

export function BreakglassActivationModal({
  changeId,
  onSuccess,
  onClose,
}: BreakglassActivationModalProps) {
  const activateMutation = useActivateBreakglass(changeId)

  const [reason, setReason] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [allowedActions, setAllowedActions] = useState('')
  const [gateTypes, setGateTypes] = useState('')
  const [targetIds, setTargetIds] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function splitCsv(value: string): string[] {
    return value
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)

    if (!reason.trim()) {
      setErrorMsg('Reason is required.')
      return
    }

    const parsedActions = splitCsv(allowedActions)
    const parsedGates = splitCsv(gateTypes)
    const parsedTargets = splitCsv(targetIds)

    if (parsedActions.length === 0 || parsedGates.length === 0 || parsedTargets.length === 0) {
      setErrorMsg('Scope must include at least one allowed action, gate type, and target ID.')
      return
    }

    if (!expiresAt) {
      setErrorMsg('Expiry is required. Open-ended sessions are not permitted.')
      return
    }

    const expiryDate = new Date(expiresAt)
    if (isNaN(expiryDate.getTime()) || expiryDate <= new Date()) {
      setErrorMsg('Expiry must be a future datetime.')
      return
    }

    if (!confirmed) {
      setErrorMsg('You must confirm breakglass activation.')
      return
    }

    activateMutation.mutate(
      {
        reason: reason.trim(),
        scope_json: {
          allowed_actions: parsedActions,
          gate_types: parsedGates,
          target_ids: parsedTargets,
        },
        expires_at: expiryDate.toISOString(),
      },
      {
        onSuccess: (session) => onSuccess?.(session),
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Activate Breakglass"
      style={{
        border: '2px solid var(--color-danger, #d00)',
        borderRadius: '4px',
        padding: '1rem',
        background: 'var(--color-surface, #fff)',
      }}
    >
      <h4 style={{ margin: '0 0 0.75rem', color: 'var(--color-danger, #d00)' }}>
        Activate Breakglass
      </h4>
      <p className="muted" style={{ marginTop: 0 }}>
        Breakglass bypasses platform dispatch and continuation gates. Every activation requires a
        mandatory retro-review. The same actor cannot perform the review.
      </p>

      <form className="stack-md" onSubmit={handleSubmit}>
        <div className="field">
          <label className="field__label" htmlFor="bg-reason">
            Reason <span aria-hidden="true">*</span>
          </label>
          <textarea
            id="bg-reason"
            className="field__input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="Explain the emergency requiring breakglass activation…"
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="bg-expires-at">
            Expires At <span aria-hidden="true">*</span>
          </label>
          <input
            id="bg-expires-at"
            className="field__input"
            type="datetime-local"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
          />
          <p className="muted" style={{ fontSize: '0.85em', marginTop: '0.25rem' }}>
            Open-ended sessions are not permitted. Choose the shortest duration necessary.
          </p>
        </div>

        <fieldset>
          <legend className="field__label">Scope</legend>
          <div className="stack-md">
            <div className="field">
              <label className="field__label" htmlFor="bg-allowed-actions">
                Allowed Actions (comma-separated) <span aria-hidden="true">*</span>
              </label>
              <input
                id="bg-allowed-actions"
                className="field__input"
                type="text"
                value={allowedActions}
                onChange={(e) => setAllowedActions(e.target.value)}
                placeholder="e.g. dispatch, continue_running"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="bg-gate-types">
                Gate Types (comma-separated) <span aria-hidden="true">*</span>
              </label>
              <input
                id="bg-gate-types"
                className="field__input"
                type="text"
                value={gateTypes}
                onChange={(e) => setGateTypes(e.target.value)}
                placeholder="e.g. window_overrun, policy_override"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="bg-target-ids">
                Target IDs (comma-separated) <span aria-hidden="true">*</span>
              </label>
              <input
                id="bg-target-ids"
                className="field__input"
                type="text"
                value={targetIds}
                onChange={(e) => setTargetIds(e.target.value)}
                placeholder="e.g. target-uuid-1, target-uuid-2"
              />
            </div>
          </div>
        </fieldset>

        <div className="field">
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              aria-label="Confirm breakglass activation"
            />
            <span>
              I confirm that this emergency breakglass activation is justified and that a mandatory
              retro-review will be completed by an independent reviewer.
            </span>
          </label>
        </div>

        {errorMsg && <p className="banner banner--error">{errorMsg}</p>}

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn btn--primary"
            type="submit"
            disabled={activateMutation.isPending || !confirmed}
            style={{
              background: 'var(--color-danger, #d00)',
              borderColor: 'var(--color-danger, #d00)',
            }}
          >
            {activateMutation.isPending ? 'Activating…' : 'Activate Breakglass'}
          </button>
          <button className="btn" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
