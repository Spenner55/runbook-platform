import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuditChangeDetailPage } from './AuditChangeDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const detail = {
  id: 'change-1',
  title: 'Rotate production credentials',
  summary: 'Credential rotation for production database.',
  justification: 'Quarterly control requirement',
  status: 'closed',
  risk: 'high',
  change_type: 'standard',
  targets: [
    { id: 'target-1', label: 'payments-prod', type: 'service', identifier: 'payments-prod' },
  ],
  submitted_at: '2026-05-02T10:00:00Z',
  audit_date: '2026-05-02T10:00:00Z',
  audit_date_basis: 'submitted_at',
  approved_at: '2026-05-02T10:05:00Z',
  closed_at: '2026-05-02T11:00:00Z',
  has_exception: false,
  bundle: {
    id: 'bundle-1',
    status: 'sealed',
    completeness_status: 'complete',
    version: 1,
    manifest_sha256: 'manifest-hash',
    content_sha256: 'content-hash',
  },
  external_references: [
    {
      id: 'ref-1',
      change_record_id: 'change-1',
      system: 'jira',
      reference_type: 'ticket',
      external_id: '10001',
      external_key: 'PROJ-123',
      display_label: 'PROJ-123',
      external_url: 'https://jira.example.test/browse/PROJ-123',
      snapshot: { title: 'Change ticket', state: 'Done' },
      snapshot_sha256: 'snapshot-hash',
      snapshot_source: 'manual',
      snapshot_status: 'current',
      snapshot_taken_at: '2026-05-02T10:30:00Z',
      last_refresh_attempted_at: null,
      last_refresh_error_code: '',
      linked_by_id: null,
      notes: '',
      created_at: '2026-05-02T10:30:00Z',
      updated_at: '2026-05-02T10:30:00Z',
    },
  ],
  control_coverage: [
    {
      id: 'coverage-1',
      evidence_bundle_id: 'bundle-1',
      mapping_profile_id: 'profile-1',
      standard: 'soc2',
      control_id: 'CC8.1',
      control_title: 'Change management',
      coverage_status: 'covered',
      matched_sections: ['request'],
      missing_sections: [],
      evidence_paths: ['request/change_record.json'],
      coverage_fingerprint_sha256: 'coverage-hash',
      computed_at: '2026-05-02T11:30:00Z',
      computed_by_id: null,
    },
  ],
  coverage_summary: { soc2: { covered: 1 } },
  created_at: '2026-05-02T09:00:00Z',
  updated_at: '2026-05-02T11:30:00Z',
}

const emptyDetail = {
  ...detail,
  external_references: [],
  control_coverage: [],
  coverage_summary: {},
  targets: [],
  bundle: null,
}

describe('AuditChangeDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderPage() {
    return renderRoute(<AuditChangeDetailPage />, {
      path: '/audit/changes/:changeId',
      route: '/audit/changes/change-1',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('renders read-only change detail with external snapshots and coverage', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(detail))
    renderPage()

    await screen.findByText('Rotate production credentials')
    expect(screen.getByText('Control Coverage Summary')).toBeInTheDocument()
    expect(screen.getByText('CC8.1 - Change management')).toBeInTheDocument()
    expect(screen.getByText('External Reference Snapshots')).toBeInTheDocument()
    expect(screen.getByText('PROJ-123')).toBeInTheDocument()
    expect(screen.getByText(/Change ticket/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText(/submit for approval/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/dispatch/i)).not.toBeInTheDocument()
  })

  it('renders empty states when audit sections are absent', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(emptyDetail))
    renderPage()

    await screen.findByText('No target context is available.')
    expect(
      screen.getByText('No control coverage has been computed for this change.')
    ).toBeInTheDocument()
    expect(screen.getByText('No control coverage details are available.')).toBeInTheDocument()
    expect(screen.getByText('No external reference snapshots are linked.')).toBeInTheDocument()
  })
})
