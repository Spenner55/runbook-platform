import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { useAuditChangeSearch } from '../../features/auditor/hooks/useAuditChangeSearch'
import type { AuditChangeSearchFilters } from '../../features/auditor/types'

const initialFilters: AuditChangeSearchFilters = {
  ordering: '-submitted_at',
  limit: '50',
  offset: '0',
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function cleanFilters(filters: AuditChangeSearchFilters) {
  return Object.fromEntries(
    Object.entries(filters).filter(
      ([, value]) => value !== undefined && String(value).trim() !== ''
    )
  ) as AuditChangeSearchFilters
}

function updateField(
  filters: AuditChangeSearchFilters,
  name: keyof AuditChangeSearchFilters,
  value: string
) {
  return cleanFilters({ ...filters, [name]: value, offset: '0' })
}

export function AuditorSearchPage() {
  const [draftFilters, setDraftFilters] = useState<AuditChangeSearchFilters>(initialFilters)
  const [activeFilters, setActiveFilters] = useState<AuditChangeSearchFilters>(initialFilters)
  const { data, isLoading, error } = useAuditChangeSearch(activeFilters)
  const changes = data?.results ?? []
  const limit = Number(activeFilters.limit ?? 50)
  const offset = Number(activeFilters.offset ?? 0)

  function submit(event: FormEvent) {
    event.preventDefault()
    setActiveFilters(cleanFilters({ ...draftFilters, offset: '0' }))
  }

  function setPage(nextOffset: number) {
    const next = { ...activeFilters, offset: String(Math.max(nextOffset, 0)) }
    setActiveFilters(next)
    setDraftFilters(next)
  }

  return (
    <div className="stack-lg">
      <section className="panel stack-md">
        <div className="panel__header">
          <h2>Audit Changes</h2>
          <p className="muted">Read-only search across persisted change evidence.</p>
        </div>

        <form className="stack-md" onSubmit={submit}>
          <div className="filter-row">
            {[
              ['service', 'Service'],
              ['target', 'Target'],
              ['risk', 'Risk'],
              ['status', 'Status'],
              ['change_type', 'Change type'],
              ['bundle_status', 'Bundle status'],
              ['control_id', 'Control ID'],
              ['coverage_status', 'Coverage status'],
              ['external_system', 'External system'],
              ['approver', 'Approver'],
              ['executor', 'Executor'],
            ].map(([name, label]) => (
              <label className="field" key={name}>
                <span className="field__label">{label}</span>
                <input
                  className="field__input"
                  name={name}
                  value={String(draftFilters[name as keyof AuditChangeSearchFilters] ?? '')}
                  onChange={(event) =>
                    setDraftFilters(
                      updateField(
                        draftFilters,
                        name as keyof AuditChangeSearchFilters,
                        event.target.value
                      )
                    )
                  }
                />
              </label>
            ))}
            <label className="field">
              <span className="field__label">Exception</span>
              <select
                className="field__input"
                name="has_exception"
                value={draftFilters.has_exception ?? ''}
                onChange={(event) =>
                  setDraftFilters(updateField(draftFilters, 'has_exception', event.target.value))
                }
              >
                <option value="">Any</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
            <label className="field">
              <span className="field__label">Start date</span>
              <input
                className="field__input"
                name="start_date"
                type="datetime-local"
                value={draftFilters.start_date ?? ''}
                onChange={(event) =>
                  setDraftFilters(updateField(draftFilters, 'start_date', event.target.value))
                }
              />
            </label>
            <label className="field">
              <span className="field__label">End date</span>
              <input
                className="field__input"
                name="end_date"
                type="datetime-local"
                value={draftFilters.end_date ?? ''}
                onChange={(event) =>
                  setDraftFilters(updateField(draftFilters, 'end_date', event.target.value))
                }
              />
            </label>
            <label className="field">
              <span className="field__label">Ordering</span>
              <select
                className="field__input"
                name="ordering"
                value={draftFilters.ordering ?? '-submitted_at'}
                onChange={(event) =>
                  setDraftFilters(updateField(draftFilters, 'ordering', event.target.value))
                }
              >
                <option value="-submitted_at">Newest submitted</option>
                <option value="submitted_at">Oldest submitted</option>
                <option value="-closed_at">Newest closed</option>
                <option value="closed_at">Oldest closed</option>
                <option value="-created_at">Newest created</option>
                <option value="created_at">Oldest created</option>
                <option value="-risk">Risk descending</option>
                <option value="risk">Risk ascending</option>
              </select>
            </label>
            <label className="field">
              <span className="field__label">Limit</span>
              <input
                className="field__input"
                name="limit"
                type="number"
                min="1"
                max="200"
                value={draftFilters.limit ?? '50'}
                onChange={(event) =>
                  setDraftFilters(updateField(draftFilters, 'limit', event.target.value))
                }
              />
            </label>
          </div>
          <div className="actions-row">
            <button className="btn btn--primary" type="submit">
              Apply filters
            </button>
            <Link className="btn" to="/audit/access">
              Access Grants
            </Link>
          </div>
        </form>
      </section>

      <section className="panel stack-md">
        <div className="panel__header">
          <h3>Results</h3>
          {data?.meta?.date_basis ? (
            <p className="muted">Date filters use submitted time with created time fallback.</p>
          ) : null}
        </div>
        {isLoading && <p>Loading audit changes...</p>}
        {error && <p className="banner banner--error">Failed to load audit changes.</p>}
        {!isLoading && !error && changes.length === 0 && (
          <p className="muted">No audit changes match the current filters.</p>
        )}
        {changes.length > 0 && (
          <>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Change</th>
                  <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Status</th>
                  <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Risk</th>
                  <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Bundle</th>
                  <th style={{ textAlign: 'left', paddingBottom: '0.5rem' }}>Audit date</th>
                </tr>
              </thead>
              <tbody>
                {changes.map((change) => (
                  <tr key={change.id}>
                    <td style={{ padding: '0.45rem 0' }}>
                      <Link to={`/audit/changes/${change.id}`}>{change.title}</Link>
                      <div className="muted">
                        {change.targets.map((target) => target.label).join(', ') || '-'}
                      </div>
                    </td>
                    <td style={{ padding: '0.45rem' }}>
                      <span className="pill">{change.status.replace(/_/g, ' ')}</span>
                    </td>
                    <td style={{ padding: '0.45rem' }}>{change.risk}</td>
                    <td style={{ padding: '0.45rem' }}>{change.bundle?.status ?? 'None'}</td>
                    <td style={{ padding: '0.45rem' }}>
                      {formatDateTime(change.audit_date)}
                      <div className="muted">{change.audit_date_basis.replace(/_/g, ' ')}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="actions-row">
              <button
                className="btn"
                disabled={offset === 0}
                onClick={() => setPage(offset - limit)}
              >
                Previous
              </button>
              <button
                className="btn"
                disabled={!data?.next}
                onClick={() => setPage(offset + limit)}
              >
                Next
              </button>
              <span className="muted">{data?.count ?? 0} total</span>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
