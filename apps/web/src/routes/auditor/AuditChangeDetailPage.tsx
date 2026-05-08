import { Link, useParams } from 'react-router-dom'

import { useAuditChangeDetail } from '../../features/auditor/hooks/useAuditChangeDetail'
import type { AuditChangeDetail, ChangeControlCoverage } from '../../features/auditor/types'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function CoverageStatus({ status }: { status: string }) {
  const className =
    status === 'covered'
      ? 'pill pill--success'
      : status === 'not_covered'
        ? 'pill pill--danger'
        : status === 'partially_covered'
          ? 'pill pill--warn'
          : 'pill'
  return <span className={className}>{status.replace(/_/g, ' ')}</span>
}

function SummaryPanel({ change }: { change: AuditChangeDetail }) {
  return (
    <section className="panel stack-md">
      <div className="panel__header">
        <Link className="muted" to="/audit/changes">
          Back to audit search
        </Link>
        <h2>{change.title}</h2>
        <div className="actions-row">
          <span className="pill">{change.status.replace(/_/g, ' ')}</span>
          <span className="pill">{change.risk}</span>
          <span className="pill">{change.change_type}</span>
        </div>
      </div>
      <p>{change.summary || 'No summary provided.'}</p>
      <dl className="detail-grid">
        <div>
          <dt className="detail-grid__label">Justification</dt>
          <dd>{change.justification || '-'}</dd>
        </div>
        <div>
          <dt className="detail-grid__label">Audit date</dt>
          <dd>
            {formatDateTime(change.audit_date)}
            <div className="muted">{change.audit_date_basis.replace(/_/g, ' ')}</div>
          </dd>
        </div>
        <div>
          <dt className="detail-grid__label">Submitted</dt>
          <dd>{formatDateTime(change.submitted_at)}</dd>
        </div>
        <div>
          <dt className="detail-grid__label">Approved</dt>
          <dd>{formatDateTime(change.approved_at)}</dd>
        </div>
        <div>
          <dt className="detail-grid__label">Closed</dt>
          <dd>{formatDateTime(change.closed_at)}</dd>
        </div>
        <div>
          <dt className="detail-grid__label">Evidence bundle</dt>
          <dd>{change.bundle ? change.bundle.status : 'No sealed bundle snapshot'}</dd>
        </div>
      </dl>
    </section>
  )
}

function TargetsPanel({ change }: { change: AuditChangeDetail }) {
  return (
    <section className="panel stack-md">
      <h3>Targets and Service Context</h3>
      {change.targets.length === 0 ? (
        <p className="muted">No target context is available.</p>
      ) : (
        <ul className="step-list">
          {change.targets.map((target) => (
            <li className="step-list__item" key={target.id}>
              <div>
                <strong>{target.label}</strong>
                <div className="muted">
                  {target.type}: {target.identifier}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function CoverageSummaryPanel({ change }: { change: AuditChangeDetail }) {
  const rows = Object.entries(change.coverage_summary).flatMap(([standard, statuses]) =>
    Object.entries(statuses).map(([status, count]) => ({ standard, status, count }))
  )

  return (
    <section className="panel stack-md">
      <h3>Control Coverage Summary</h3>
      {rows.length === 0 ? (
        <p className="muted">No control coverage has been computed for this change.</p>
      ) : (
        <ul className="step-list">
          {rows.map((row) => (
            <li className="step-list__item" key={`${row.standard}-${row.status}`}>
              <div>
                <strong>{row.standard}</strong>
                <div className="muted">{row.count} controls</div>
              </div>
              <CoverageStatus status={row.status} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function CoverageDetail({ coverage }: { coverage: ChangeControlCoverage }) {
  return (
    <li className="step-list__item">
      <div className="stack-md" style={{ width: '100%' }}>
        <div className="actions-row">
          <strong>
            {coverage.control_id}
            {coverage.control_title ? ` - ${coverage.control_title}` : ''}
          </strong>
          <CoverageStatus status={coverage.coverage_status} />
        </div>
        <div className="detail-grid">
          <div>
            <p className="detail-grid__label">Matched sections</p>
            <p>{coverage.matched_sections.join(', ') || '-'}</p>
          </div>
          <div>
            <p className="detail-grid__label">Missing sections</p>
            <p>{coverage.missing_sections.join(', ') || '-'}</p>
          </div>
          <div>
            <p className="detail-grid__label">Evidence paths</p>
            <p>{coverage.evidence_paths.join(', ') || '-'}</p>
          </div>
          <div>
            <p className="detail-grid__label">Computed</p>
            <p>{formatDateTime(coverage.computed_at)}</p>
          </div>
        </div>
      </div>
    </li>
  )
}

function CoverageDetailsPanel({ change }: { change: AuditChangeDetail }) {
  return (
    <section className="panel stack-md">
      <h3>Control Coverage Details</h3>
      {change.control_coverage.length === 0 ? (
        <p className="muted">No control coverage details are available.</p>
      ) : (
        <ul className="step-list">
          {change.control_coverage.map((coverage) => (
            <CoverageDetail coverage={coverage} key={coverage.id} />
          ))}
        </ul>
      )}
    </section>
  )
}

function ExternalReferencesPanel({ change }: { change: AuditChangeDetail }) {
  return (
    <section className="panel stack-md">
      <h3>External Reference Snapshots</h3>
      {change.external_references.length === 0 ? (
        <p className="muted">No external reference snapshots are linked.</p>
      ) : (
        <ul className="step-list">
          {change.external_references.map((reference) => (
            <li className="step-list__item" key={reference.id}>
              <div className="stack-md" style={{ width: '100%' }}>
                <div className="actions-row">
                  <strong>
                    {reference.display_label || reference.external_key || reference.external_id}
                  </strong>
                  <span className="pill">{reference.system}</span>
                  <span className="pill">{reference.snapshot_status}</span>
                </div>
                <dl className="detail-grid">
                  <div>
                    <dt className="detail-grid__label">Reference type</dt>
                    <dd>{reference.reference_type}</dd>
                  </div>
                  <div>
                    <dt className="detail-grid__label">Snapshot source</dt>
                    <dd>{reference.snapshot_source}</dd>
                  </div>
                  <div>
                    <dt className="detail-grid__label">Snapshot taken</dt>
                    <dd>{formatDateTime(reference.snapshot_taken_at)}</dd>
                  </div>
                  <div>
                    <dt className="detail-grid__label">Snapshot hash</dt>
                    <dd>
                      <code>{reference.snapshot_sha256 || '-'}</code>
                    </dd>
                  </div>
                </dl>
                <pre className="code-block">{JSON.stringify(reference.snapshot, null, 2)}</pre>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function EvidenceMetadataPanel({ change }: { change: AuditChangeDetail }) {
  return (
    <section className="panel stack-md">
      <h3>Audit Metadata</h3>
      <dl className="detail-grid">
        <div>
          <dt className="detail-grid__label">Change ID</dt>
          <dd>
            <code>{change.id}</code>
          </dd>
        </div>
        <div>
          <dt className="detail-grid__label">Created</dt>
          <dd>{formatDateTime(change.created_at)}</dd>
        </div>
        <div>
          <dt className="detail-grid__label">Updated</dt>
          <dd>{formatDateTime(change.updated_at)}</dd>
        </div>
        <div>
          <dt className="detail-grid__label">Bundle manifest</dt>
          <dd>
            <code>{change.bundle?.manifest_sha256 || '-'}</code>
          </dd>
        </div>
        <div>
          <dt className="detail-grid__label">Bundle content</dt>
          <dd>
            <code>{change.bundle?.content_sha256 || '-'}</code>
          </dd>
        </div>
      </dl>
    </section>
  )
}

export function AuditChangeDetailPage() {
  const { changeId } = useParams()
  const { data: change, isLoading, error } = useAuditChangeDetail(changeId)

  if (isLoading) {
    return <p>Loading audit change...</p>
  }

  if (error || !change) {
    return <p className="banner banner--error">Failed to load audit change.</p>
  }

  return (
    <div className="stack-lg">
      <SummaryPanel change={change} />
      <TargetsPanel change={change} />
      <CoverageSummaryPanel change={change} />
      <CoverageDetailsPanel change={change} />
      <ExternalReferencesPanel change={change} />
      <EvidenceMetadataPanel change={change} />
    </div>
  )
}
