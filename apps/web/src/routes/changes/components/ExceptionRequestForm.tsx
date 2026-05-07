import { useState } from 'react'

import { useCreateException } from '../../../features/changes/hooks/useCreateException'
import type { ChangeException, ExceptionType } from '../../../features/changes/types'
import { getApiErrorMessage } from '../../../shared/api/client'

const EXCEPTION_TYPES: { value: ExceptionType; label: string }[] = [
  { value: 'freeze_override', label: 'Freeze Override' },
  { value: 'window_overrun', label: 'Window Overrun' },
  { value: 'late_verification', label: 'Late Verification' },
  { value: 'policy_override', label: 'Policy Override' },
  { value: 'missing_artifact', label: 'Missing Artifact' },
]

const SCOPE_FIELDS: Record<
  ExceptionType,
  Array<{ key: string; label: string; required: boolean }>
> = {
  freeze_override: [
    { key: 'freeze_rule_id', label: 'Freeze Rule ID', required: true },
    { key: 'target_ids', label: 'Target IDs (comma-separated)', required: true },
  ],
  window_overrun: [
    { key: 'change_window_id', label: 'Change Window ID', required: true },
    { key: 'allowed_until', label: 'Allowed Until (ISO datetime)', required: true },
  ],
  late_verification: [
    { key: 'verification_plan_id', label: 'Verification Plan ID', required: true },
    {
      key: 'verification_check_ids',
      label: 'Verification Check IDs (comma-separated)',
      required: true,
    },
    { key: 'due_at', label: 'Due At (ISO datetime)', required: true },
  ],
  policy_override: [
    { key: 'policy_evaluation_id', label: 'Policy Evaluation ID', required: true },
    { key: 'policy_rule_ids', label: 'Policy Rule IDs (comma-separated)', required: true },
    { key: 'overridden_outcome', label: 'Overridden Outcome', required: true },
  ],
  missing_artifact: [
    { key: 'verification_check_id', label: 'Verification Check ID', required: true },
    { key: 'expected_artifact_kind', label: 'Expected Artifact Kind', required: true },
    { key: 'replacement_evidence', label: 'Replacement Evidence', required: true },
  ],
}

function buildScopeJson(
  exceptionType: ExceptionType,
  scopeValues: Record<string, string>
): Record<string, unknown> {
  const scope: Record<string, unknown> = {}
  for (const field of SCOPE_FIELDS[exceptionType]) {
    const value = scopeValues[field.key] ?? ''
    if (field.key.endsWith('_ids')) {
      scope[field.key] = value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    } else {
      scope[field.key] = value
    }
  }
  return scope
}

interface ExceptionRequestFormProps {
  changeId: string
  onSuccess?: (exception: ChangeException) => void
  onCancel?: () => void
}

export function ExceptionRequestForm({ changeId, onSuccess, onCancel }: ExceptionRequestFormProps) {
  const createMutation = useCreateException(changeId)

  const [exceptionType, setExceptionType] = useState<ExceptionType | ''>('')
  const [reason, setReason] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [scopeValues, setScopeValues] = useState<Record<string, string>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleTypeChange(type: ExceptionType | '') {
    setExceptionType(type)
    setScopeValues({})
  }

  function updateScopeValue(key: string, value: string) {
    setScopeValues((prev) => ({ ...prev, [key]: value }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!exceptionType) return
    setErrorMsg(null)

    const scopeJson = buildScopeJson(exceptionType, scopeValues)

    createMutation.mutate(
      {
        exception_type: exceptionType,
        reason,
        scope_json: scopeJson,
        expires_at: new Date(expiresAt).toISOString(),
      },
      {
        onSuccess: (exc) => onSuccess?.(exc),
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  const fields = exceptionType ? SCOPE_FIELDS[exceptionType] : []

  return (
    <form className="stack-md" onSubmit={handleSubmit} aria-label="Request exception">
      <div className="field">
        <label className="field__label" htmlFor="exception-type">
          Exception Type
        </label>
        <select
          id="exception-type"
          className="field__input"
          value={exceptionType}
          onChange={(e) => handleTypeChange(e.target.value as ExceptionType | '')}
          required
        >
          <option value="">Select type…</option>
          {EXCEPTION_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="exception-reason">
          Reason
        </label>
        <textarea
          id="exception-reason"
          className="field__input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          required
          placeholder="Explain why this exception is required…"
        />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="exception-expires-at">
          Expires At
        </label>
        <input
          id="exception-expires-at"
          className="field__input"
          type="datetime-local"
          value={expiresAt}
          onChange={(e) => setExpiresAt(e.target.value)}
          required
        />
      </div>

      {fields.length > 0 && (
        <fieldset>
          <legend className="field__label">Scope ({exceptionType?.replace(/_/g, ' ')})</legend>
          <div className="stack-md">
            {fields.map((f) => (
              <div className="field" key={f.key}>
                <label className="field__label" htmlFor={`scope-${f.key}`}>
                  {f.label}
                </label>
                <input
                  id={`scope-${f.key}`}
                  className="field__input"
                  type="text"
                  value={scopeValues[f.key] ?? ''}
                  onChange={(e) => updateScopeValue(f.key, e.target.value)}
                  required={f.required}
                  aria-label={f.label}
                />
              </div>
            ))}
          </div>
        </fieldset>
      )}

      {errorMsg && <p className="banner banner--error">{errorMsg}</p>}

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          className="btn btn--primary"
          type="submit"
          disabled={createMutation.isPending || !exceptionType}
        >
          {createMutation.isPending ? 'Requesting…' : 'Request Exception'}
        </button>
        {onCancel && (
          <button className="btn" type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}
