import { useState } from 'react'

import { useCreateEvidenceBundle } from '../../../features/evidence/hooks/useCreateEvidenceBundle'
import { useCreateEvidenceExport } from '../../../features/evidence/hooks/useCreateEvidenceExport'
import { useCreateLegalHold } from '../../../features/evidence/hooks/useCreateLegalHold'
import { useEvidenceExportDownload } from '../../../features/evidence/hooks/useEvidenceExportDownload'
import { useLatestEvidenceBundle } from '../../../features/evidence/hooks/useLatestEvidenceBundle'
import { useSealEvidenceBundle } from '../../../features/evidence/hooks/useSealEvidenceBundle'
import type {
  CompletenessItemEntry,
  CompletenessReport,
  CompletenessSection,
  EvidenceBundle,
  EvidenceExport,
} from '../../../features/evidence/types'
import { getApiErrorMessage } from '../../../shared/api/client'

function truncateHash(hash: string | null | undefined, len = 16) {
  if (!hash) return null
  return hash.length > len ? `${hash.slice(0, len)}…` : hash
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function formatBytes(bytes: number | null | undefined) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function getBundleStatusPillClass(status: string) {
  if (status === 'sealed') return 'pill pill--success'
  if (status === 'compiling') return 'pill pill--info'
  if (status === 'invalidated') return 'pill pill--danger'
  return 'pill'
}

function getCompletenessStatusPillClass(status: string) {
  if (status === 'complete') return 'pill pill--success'
  if (status === 'incomplete') return 'pill pill--warn'
  if (status === 'invalid') return 'pill pill--danger'
  return 'pill'
}

function normalizeCompletenessReport(
  report: CompletenessReport | Record<string, unknown>
): CompletenessReport {
  const rawSections = Array.isArray((report as { sections?: unknown[] }).sections)
    ? ((report as { sections: unknown[] }).sections as Array<Record<string, unknown>>)
    : []

  if (rawSections.length > 0 && typeof rawSections[0].section === 'string') {
    return report as CompletenessReport
  }

  const groups = new Map<string, CompletenessItemEntry[]>()
  for (const item of rawSections) {
    const entry: CompletenessItemEntry = {
      item_type: String(item.item_type ?? 'unknown'),
      item_key: String(item.item_key ?? ''),
      canonical_path: String(item.canonical_path ?? ''),
      required: Boolean(item.required),
      present: Boolean(item.present),
      valid: item.valid !== false,
      missing_reason: String(item.missing_reason ?? ''),
      validation_errors: Array.isArray(item.validation_errors) ? item.validation_errors : [],
    }
    const section = entry.item_type
    groups.set(section, [...(groups.get(section) ?? []), entry])
  }

  const sections: CompletenessSection[] = Array.from(groups.entries()).map(([section, items]) => {
    const requiredItems = items.filter((item) => item.required)
    const required_count = requiredItems.length
    const present_count = requiredItems.filter((item) => item.present).length
    const invalid_count = items.filter((item) => !item.valid).length
    const status: CompletenessSection['status'] =
      invalid_count > 0 ? 'invalid' : present_count < required_count ? 'incomplete' : 'complete'

    return {
      section,
      status,
      items,
      required_count,
      present_count,
      invalid_count,
    }
  })

  const summary = (report as { summary?: Record<string, unknown> }).summary ?? {}
  const required_total = sections.reduce((count, section) => count + section.required_count, 0)
  const present_total = sections.reduce((count, section) => count + section.present_count, 0)
  const invalid_total =
    typeof summary.invalid_count === 'number'
      ? summary.invalid_count
      : sections.reduce((count, section) => count + section.invalid_count, 0)
  const missing_total =
    typeof summary.missing_required_count === 'number'
      ? summary.missing_required_count
      : required_total - present_total

  return {
    sections,
    required_total,
    present_total,
    invalid_total,
    missing_total,
  }
}

// ─── Completeness Checklist ───────────────────────────────────────────────────

function SectionRow({ section }: { section: CompletenessSection }) {
  const [expanded, setExpanded] = useState(false)
  const hasIssues = section.invalid_count > 0 || section.present_count < section.required_count

  return (
    <li className="step-list__item">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <span className={getCompletenessStatusPillClass(section.status)}>{section.status}</span>
        <strong>{section.section.replace(/_/g, ' ')}</strong>
        <span className="muted" style={{ fontSize: '0.85em' }}>
          {section.present_count}/{section.required_count} required
          {section.invalid_count > 0 && ` · ${section.invalid_count} invalid`}
        </span>
        {hasIssues && (
          <button
            className="btn"
            style={{ marginLeft: 'auto', fontSize: '0.8em' }}
            type="button"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Hide' : 'Show'} items
          </button>
        )}
      </div>
      {expanded && section.items.length > 0 && (
        <ul style={{ margin: '0.5rem 0 0 1rem', padding: 0, listStyle: 'none' }}>
          {section.items
            .filter((item) => !item.present || !item.valid)
            .map((item, i) => (
              <li key={`${item.item_type}-${item.item_key}-${i}`} style={{ fontSize: '0.85em' }}>
                <span className={item.valid ? 'pill' : 'pill pill--danger'}>
                  {item.valid ? (item.present ? 'ok' : 'missing') : 'invalid'}
                </span>{' '}
                <code>{item.canonical_path || item.item_key}</code>
                {!item.present && item.missing_reason && (
                  <span className="muted"> — {item.missing_reason}</span>
                )}
              </li>
            ))}
        </ul>
      )}
    </li>
  )
}

function CompletenessChecklist({ report }: { report: CompletenessReport }) {
  const sections: CompletenessSection[] = report.sections ?? []

  if (sections.length === 0) {
    return <p className="muted">No completeness data available.</p>
  }

  return (
    <div className="stack-md">
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.85em' }}>
        <span>
          {report.present_total ?? 0}/{report.required_total ?? 0} required present
        </span>
        {(report.invalid_total ?? 0) > 0 && (
          <span style={{ color: 'var(--color-danger, #d00)' }}>{report.invalid_total} invalid</span>
        )}
        {(report.missing_total ?? 0) > 0 && (
          <span className="muted">{report.missing_total} missing</span>
        )}
      </div>
      <ul className="step-list">
        {sections.map((sec) => (
          <SectionRow key={sec.section} section={sec} />
        ))}
      </ul>
    </div>
  )
}

// ─── Manifest Viewer ──────────────────────────────────────────────────────────

function ManifestViewer({ bundle }: { bundle: EvidenceBundle }) {
  const [expanded, setExpanded] = useState(false)
  const manifest = bundle.manifest_sha256

  if (!manifest) return null

  const rawManifest = (bundle as unknown as Record<string, unknown>).manifest as
    | Record<string, unknown>
    | undefined
  const entries = Array.isArray((rawManifest as Record<string, unknown> | undefined)?.entries)
    ? ((rawManifest as Record<string, unknown>).entries as unknown[])
    : []

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <span className="muted">Manifest SHA-256</span>
        <code title={bundle.manifest_sha256} style={{ fontSize: '0.85em' }}>
          {truncateHash(bundle.manifest_sha256)}
        </code>
        <button
          className="btn"
          type="button"
          style={{ fontSize: '0.8em', marginLeft: 'auto' }}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? 'Hide' : 'View'} manifest
        </button>
      </div>
      {expanded && (
        <div
          style={{
            marginTop: '0.75rem',
            border: '1px solid var(--color-border, #ccc)',
            borderRadius: '4px',
            padding: '0.75rem',
            background: 'var(--color-surface-secondary, #f8f8f8)',
          }}
        >
          <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '0.25rem' }}>
            <dt className="muted">Package type</dt>
            <dd>sealed bundle</dd>
            <dt className="muted">Bundle version</dt>
            <dd>v{bundle.version}</dd>
            <dt className="muted">Compiled</dt>
            <dd>{formatDateTime(bundle.compiled_at)}</dd>
            <dt className="muted">Sealed</dt>
            <dd>{formatDateTime(bundle.sealed_at)}</dd>
            <dt className="muted">Content hash</dt>
            <dd>
              <code title={bundle.content_sha256} style={{ fontSize: '0.85em' }}>
                {truncateHash(bundle.content_sha256)}
              </code>
            </dd>
            <dt className="muted">Package size</dt>
            <dd>{formatBytes(bundle.content_size_bytes)}</dd>
          </dl>

          {entries.length > 0 && (
            <>
              <h6 style={{ margin: '0.75rem 0 0.25rem' }}>Entries ({entries.length})</h6>
              <ul style={{ margin: 0, padding: 0, listStyle: 'none', fontSize: '0.82em' }}>
                {(entries as Array<Record<string, unknown>>).map((e, i) => (
                  <li
                    key={i}
                    style={{
                      display: 'flex',
                      gap: '0.5rem',
                      padding: '0.15rem 0',
                      borderBottom: '1px solid var(--color-border, #eee)',
                      alignItems: 'baseline',
                    }}
                  >
                    <code
                      style={{
                        flex: '1 1 auto',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {String(e.path ?? '')}
                    </code>
                    <span className="muted">{formatBytes(Number(e.size_bytes ?? 0))}</span>
                    <code title={String(e.sha256 ?? '')} style={{ fontSize: '0.9em' }}>
                      {truncateHash(String(e.sha256 ?? ''), 12)}
                    </code>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Seal Action ──────────────────────────────────────────────────────────────

function SealAction({ bundle, changeId }: { bundle: EvidenceBundle; changeId: string }) {
  const sealMutation = useSealEvidenceBundle(changeId)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const canSeal = bundle.status === 'compiling' && bundle.completeness_status === 'complete'

  if (bundle.status !== 'compiling') return null

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
      <button
        className="btn btn--primary"
        disabled={!canSeal || sealMutation.isPending}
        title={
          !canSeal
            ? `Bundle completeness is "${bundle.completeness_status}" — all required evidence must be present and valid before sealing`
            : 'Seal this evidence bundle to make it immutable'
        }
        onClick={() => {
          setErrorMsg(null)
          sealMutation.mutate(bundle.id, {
            onError: (err) => setErrorMsg(getApiErrorMessage(err)),
          })
        }}
      >
        {sealMutation.isPending ? 'Sealing…' : 'Seal bundle'}
      </button>
      {!canSeal && (
        <span className="muted" style={{ fontSize: '0.85em' }}>
          Complete all required evidence before sealing.
        </span>
      )}
      {errorMsg && <span className="banner banner--error">{errorMsg}</span>}
    </div>
  )
}

// ─── Export Dialog ────────────────────────────────────────────────────────────

interface ExportDialogProps {
  bundle: EvidenceBundle
  onClose: () => void
}

function ExportDialog({ bundle, onClose }: ExportDialogProps) {
  const createExportMutation = useCreateEvidenceExport(bundle.id)
  const downloadMutation = useEvidenceExportDownload()
  const [redactionPolicyId, setRedactionPolicyId] = useState<string>('')
  const [createdExport, setCreatedExport] = useState<EvidenceExport | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    createExportMutation.mutate(
      { redaction_policy_id: redactionPolicyId || null },
      {
        onSuccess: (exp) => setCreatedExport(exp),
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Create evidence export"
      style={{
        border: '1px solid var(--color-border, #ccc)',
        borderRadius: '4px',
        padding: '1rem',
        background: 'var(--color-surface, #fff)',
        marginTop: '0.75rem',
      }}
    >
      <h5 style={{ margin: '0 0 0.75rem' }}>Create Evidence Export</h5>

      {!createdExport ? (
        <form className="stack-md" onSubmit={handleCreate}>
          <p className="muted" style={{ margin: 0 }}>
            Export is derived from the sealed bundle (v{bundle.version}). Canonical evidence is not
            modified.
          </p>
          <div className="field">
            <label className="field__label" htmlFor="redaction-policy-id">
              Redaction policy ID (optional)
            </label>
            <input
              id="redaction-policy-id"
              className="field__input"
              type="text"
              value={redactionPolicyId}
              onChange={(e) => setRedactionPolicyId(e.target.value)}
              placeholder="Leave blank for unredacted export"
            />
          </div>
          {errorMsg && <p className="banner banner--error">{errorMsg}</p>}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="btn btn--primary"
              type="submit"
              disabled={createExportMutation.isPending}
            >
              {createExportMutation.isPending ? 'Creating…' : 'Create export'}
            </button>
            <button className="btn" type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="stack-md">
          <p>
            Export created.{' '}
            <span className={createdExport.status === 'ready' ? 'pill pill--success' : 'pill'}>
              {createdExport.status}
            </span>
          </p>
          <dl style={{ display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: '0.25rem' }}>
            <dt className="muted">Export hash</dt>
            <dd>
              <code title={createdExport.content_sha256} style={{ fontSize: '0.85em' }}>
                {truncateHash(createdExport.content_sha256)}
              </code>
            </dd>
            <dt className="muted">Receipt hash</dt>
            <dd>
              <code title={createdExport.receipt_sha256} style={{ fontSize: '0.85em' }}>
                {truncateHash(createdExport.receipt_sha256)}
              </code>
            </dd>
            {createdExport.expires_at && (
              <>
                <dt className="muted">Expires</dt>
                <dd>{formatDateTime(createdExport.expires_at)}</dd>
              </>
            )}
            {createdExport.redaction_policy_id && (
              <>
                <dt className="muted">Redaction policy</dt>
                <dd>
                  <code style={{ fontSize: '0.85em' }}>{createdExport.redaction_policy_id}</code>
                </dd>
              </>
            )}
            {!createdExport.redaction_policy_id && (
              <>
                <dt className="muted">Redaction</dt>
                <dd className="muted">None (unredacted)</dd>
              </>
            )}
          </dl>
          {downloadMutation.isError && (
            <p className="banner banner--error">{getApiErrorMessage(downloadMutation.error)}</p>
          )}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {createdExport.status === 'ready' && (
              <button
                className="btn btn--primary"
                disabled={downloadMutation.isPending}
                onClick={() =>
                  downloadMutation.mutate({
                    exportId: createdExport.id,
                    filename: `evidence-export-v${bundle.version}.zip`,
                  })
                }
              >
                {downloadMutation.isPending ? 'Downloading…' : 'Download ZIP'}
              </button>
            )}
            <button className="btn" type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Legal Hold Indicator / Control ──────────────────────────────────────────

interface LegalHoldControlProps {
  bundle: EvidenceBundle
  changeId: string
}

function LegalHoldControl({ bundle, changeId }: LegalHoldControlProps) {
  const [showForm, setShowForm] = useState(false)
  const [reason, setReason] = useState('')
  const [externalRef, setExternalRef] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const holdMutation = useCreateLegalHold(bundle.id, changeId)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    holdMutation.mutate(
      { reason, external_reference: externalRef || undefined },
      {
        onSuccess: () => {
          setShowForm(false)
          setReason('')
          setExternalRef('')
        },
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <section className="stack-md">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <h5 style={{ margin: 0 }}>Legal Hold</h5>
        {bundle.legal_hold_active ? (
          <span className="pill pill--danger" aria-label="Legal hold active">
            HOLD ACTIVE
          </span>
        ) : (
          <>
            <span className="pill" aria-label="No legal hold">
              No hold
            </span>
            {!showForm && (
              <button
                className="btn"
                style={{ marginLeft: 'auto' }}
                type="button"
                onClick={() => setShowForm(true)}
              >
                Place hold
              </button>
            )}
          </>
        )}
      </div>

      {bundle.legal_hold_active && (
        <p className="muted" style={{ fontSize: '0.85em' }}>
          An active legal hold is in effect. Retention cleanup of this bundle and its exports is
          blocked until the hold is released.
        </p>
      )}

      {bundle.retention_expires_at && !bundle.storage_deleted_at && (
        <p className="muted" style={{ fontSize: '0.85em' }}>
          Retention expires: <strong>{formatDateTime(bundle.retention_expires_at)}</strong>
          {bundle.legal_hold_active && <span> (hold overrides cleanup until released)</span>}
        </p>
      )}

      {bundle.storage_deleted_at && (
        <p className="banner banner--warning" style={{ fontSize: '0.85em' }}>
          Bundle storage was deleted on {formatDateTime(bundle.storage_deleted_at)}. Metadata and
          hashes are preserved.
        </p>
      )}

      {showForm && (
        <form
          className="stack-md"
          onSubmit={handleSubmit}
          style={{
            border: '1px solid var(--color-border, #ccc)',
            borderRadius: '4px',
            padding: '0.75rem',
          }}
        >
          <div className="field">
            <label className="field__label" htmlFor="hold-reason">
              Reason (required)
            </label>
            <textarea
              id="hold-reason"
              className="field__input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              required
              placeholder="Legal or business reason for this hold…"
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="hold-external-ref">
              External reference (optional)
            </label>
            <input
              id="hold-external-ref"
              className="field__input"
              type="text"
              value={externalRef}
              onChange={(e) => setExternalRef(e.target.value)}
              placeholder="Ticket ID, matter reference, etc."
            />
          </div>
          {errorMsg && <p className="banner banner--error">{errorMsg}</p>}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="btn btn--primary"
              type="submit"
              disabled={holdMutation.isPending || !reason}
            >
              {holdMutation.isPending ? 'Placing hold…' : 'Place legal hold'}
            </button>
            <button className="btn" type="button" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

// ─── Bundle Card ──────────────────────────────────────────────────────────────

function BundleCard({ bundle, changeId }: { bundle: EvidenceBundle; changeId: string }) {
  const [showExportDialog, setShowExportDialog] = useState(false)
  const report =
    bundle.completeness_report && Object.keys(bundle.completeness_report).length > 0
      ? normalizeCompletenessReport(bundle.completeness_report)
      : null

  const canExport = bundle.status === 'sealed' && !bundle.storage_deleted_at

  return (
    <div className="stack-md">
      {/* Bundle header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <span className={getBundleStatusPillClass(bundle.status)}>{bundle.status}</span>
        <span className={getCompletenessStatusPillClass(bundle.completeness_status)}>
          {bundle.completeness_status}
        </span>
        <span className="muted">v{bundle.version}</span>
        {!bundle.is_current && <span className="pill pill--warn">not current</span>}
      </div>

      {/* Core metadata */}
      <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '0.25rem' }}>
        <dt className="muted">Source snapshot</dt>
        <dd>
          <code title={bundle.source_snapshot_sha256} style={{ fontSize: '0.85em' }}>
            {truncateHash(bundle.source_snapshot_sha256)}
          </code>
        </dd>
        {bundle.sealed_at && (
          <>
            <dt className="muted">Sealed</dt>
            <dd>{formatDateTime(bundle.sealed_at)}</dd>
          </>
        )}
        {bundle.invalidated_at && (
          <>
            <dt className="muted">Invalidated</dt>
            <dd>
              {formatDateTime(bundle.invalidated_at)}
              {bundle.invalidation_reason && (
                <span className="muted"> — {bundle.invalidation_reason}</span>
              )}
            </dd>
          </>
        )}
      </dl>

      {/* Completeness checklist */}
      {report && (
        <section>
          <h5 style={{ margin: '0 0 0.5rem' }}>Completeness Checklist</h5>
          <CompletenessChecklist report={report} />
        </section>
      )}

      {/* Seal action (compiling bundles only) */}
      <SealAction bundle={bundle} changeId={changeId} />

      {/* Manifest viewer (sealed bundles only) */}
      {bundle.status === 'sealed' && <ManifestViewer bundle={bundle} />}

      {/* Export dialog */}
      {canExport && (
        <div>
          {!showExportDialog ? (
            <button className="btn" type="button" onClick={() => setShowExportDialog(true)}>
              Create export
            </button>
          ) : (
            <ExportDialog bundle={bundle} onClose={() => setShowExportDialog(false)} />
          )}
        </div>
      )}

      {/* Legal hold */}
      <LegalHoldControl bundle={bundle} changeId={changeId} />
    </div>
  )
}

// ─── Evidence Panel ───────────────────────────────────────────────────────────

interface EvidencePanelProps {
  changeId: string
  changeStatus: string
}

export function EvidencePanel({ changeId, changeStatus }: EvidencePanelProps) {
  const isClosed = changeStatus === 'closed'
  const bundleQuery = useLatestEvidenceBundle(changeId, isClosed)
  const createBundleMutation = useCreateEvidenceBundle(changeId)
  const [createError, setCreateError] = useState<string | null>(null)

  if (!isClosed) return null

  return (
    <section className="stack-md" aria-label="Evidence bundle">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <h4 style={{ margin: 0 }}>Evidence Bundle</h4>
        {bundleQuery.data?.status === 'sealed' && (
          <span className="pill pill--success">sealed</span>
        )}
        {!bundleQuery.isLoading && !bundleQuery.data && (
          <button
            className="btn btn--primary"
            disabled={createBundleMutation.isPending}
            onClick={() => {
              setCreateError(null)
              createBundleMutation.mutate(
                {},
                { onError: (err) => setCreateError(getApiErrorMessage(err)) }
              )
            }}
          >
            {createBundleMutation.isPending ? 'Creating…' : 'Create evidence bundle'}
          </button>
        )}
        {bundleQuery.data && bundleQuery.data.status !== 'sealed' && (
          <button
            className="btn"
            disabled={createBundleMutation.isPending}
            style={{ marginLeft: 'auto' }}
            onClick={() => {
              setCreateError(null)
              createBundleMutation.mutate(
                { force_new_version: true },
                { onError: (err) => setCreateError(getApiErrorMessage(err)) }
              )
            }}
          >
            {createBundleMutation.isPending ? 'Creating…' : 'New version'}
          </button>
        )}
      </div>

      {bundleQuery.isLoading && <p className="muted">Loading evidence bundle…</p>}
      {bundleQuery.error && <p className="banner banner--error">Could not load evidence bundle.</p>}
      {createError && <p className="banner banner--error">{createError}</p>}

      {!bundleQuery.isLoading && !bundleQuery.error && !bundleQuery.data && (
        <p className="muted">
          No evidence bundle yet. Create one to compile and seal the evidence record for this closed
          change.
        </p>
      )}

      {bundleQuery.data && <BundleCard bundle={bundleQuery.data} changeId={changeId} />}
    </section>
  )
}
