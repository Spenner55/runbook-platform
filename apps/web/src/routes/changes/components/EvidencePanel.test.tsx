import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { EvidencePanel } from './EvidencePanel'
import { createJsonResponse } from '../../../test/fetchResponse'
import { renderRoute } from '../../../test/renderRoute'

const BASE_BUNDLE = {
  id: 'bundle-1',
  change_record_id: 'change-1',
  version: 1,
  status: 'compiling',
  completeness_status: 'incomplete',
  is_current: true,
  source_snapshot_sha256: 'abc'.padEnd(64, '0'),
  completeness_report: {
    sections: [
      {
        section: 'change_snapshot',
        status: 'complete',
        items: [],
        required_count: 1,
        present_count: 1,
        invalid_count: 0,
      },
      {
        section: 'closure',
        status: 'incomplete',
        items: [
          {
            item_type: 'closure',
            item_key: 'closure-main',
            canonical_path: 'change/closure.json',
            required: true,
            present: false,
            valid: true,
            missing_reason: 'closure_not_found',
            validation_errors: [],
          },
        ],
        required_count: 1,
        present_count: 0,
        invalid_count: 0,
      },
    ],
    required_total: 2,
    present_total: 1,
    invalid_total: 0,
    missing_total: 1,
  },
  manifest_sha256: '',
  payload_checksums_sha256: '',
  content_sha256: '',
  content_size_bytes: null,
  compiled_at: '2026-05-01T10:00:00Z',
  sealed_at: null,
  invalidated_at: null,
  invalidation_reason: '',
  retention_expires_at: null,
  legal_hold_active: false,
  storage_deleted_at: null,
  created_at: '2026-05-01T10:00:00Z',
  updated_at: '2026-05-01T10:00:00Z',
}

const COMPLETE_BUNDLE = {
  ...BASE_BUNDLE,
  completeness_status: 'complete',
  completeness_report: {
    sections: [
      {
        section: 'change_snapshot',
        status: 'complete',
        items: [],
        required_count: 1,
        present_count: 1,
        invalid_count: 0,
      },
      {
        section: 'closure',
        status: 'complete',
        items: [],
        required_count: 1,
        present_count: 1,
        invalid_count: 0,
      },
    ],
    required_total: 2,
    present_total: 2,
    invalid_total: 0,
    missing_total: 0,
  },
}

const INVALID_BUNDLE = {
  ...BASE_BUNDLE,
  completeness_status: 'invalid',
  completeness_report: {
    sections: [
      {
        section: 'artifacts',
        status: 'invalid',
        items: [
          {
            item_type: 'artifact',
            item_key: 'artifact-99',
            canonical_path: 'artifacts/files/artifact-99/diag.txt',
            required: true,
            present: true,
            valid: false,
            missing_reason: '',
            validation_errors: ['checksum_mismatch'],
          },
        ],
        required_count: 1,
        present_count: 1,
        invalid_count: 1,
      },
    ],
    required_total: 1,
    present_total: 1,
    invalid_total: 1,
    missing_total: 0,
  },
}

const BACKEND_SHAPE_BUNDLE = {
  ...BASE_BUNDLE,
  completeness_report: {
    schema_version: '1',
    status: 'incomplete',
    summary: {
      total_items: 2,
      missing_required_count: 1,
      invalid_count: 0,
    },
    missing_required: [],
    invalid: [],
    sections: [
      {
        item_type: 'change_snapshot',
        item_key: 'change_snapshot',
        canonical_path: 'change/change_record.json',
        required: true,
        present: true,
        valid: true,
        missing_reason: '',
        validation_errors: [],
      },
      {
        item_type: 'closure',
        item_key: 'closure',
        canonical_path: 'closure/closure.json',
        required: true,
        present: false,
        valid: true,
        missing_reason: 'missing_closure',
        validation_errors: [],
      },
    ],
  },
}

const SEALED_BUNDLE = {
  ...COMPLETE_BUNDLE,
  status: 'sealed',
  manifest_sha256: 'deadbeef'.padEnd(64, '0'),
  payload_checksums_sha256: 'cafe'.padEnd(64, '0'),
  content_sha256: 'f00d'.padEnd(64, '0'),
  content_size_bytes: 45678,
  sealed_at: '2026-05-01T11:00:00Z',
}

const SEALED_WITH_HOLD = {
  ...SEALED_BUNDLE,
  legal_hold_active: true,
  retention_expires_at: '2033-05-01T00:00:00Z',
}

describe('EvidencePanel', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderPanel(changeStatus = 'closed', changeId = 'change-1') {
    renderRoute(<EvidencePanel changeId={changeId} changeStatus={changeStatus} />, {
      path: '/changes/:changeId',
      route: `/changes/${changeId}`,
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  // ── Empty state ────────────────────────────────────────────────────────────

  it('renders empty state when no bundle exists (404)', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ detail: 'Not found.' }, { status: 404 }))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText(/no evidence bundle yet/i)).toBeInTheDocument()
    })
  })

  it('renders create bundle button when no bundle exists', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ detail: 'Not found.' }, { status: 404 }))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create evidence bundle/i })).toBeInTheDocument()
    })
  })

  it('does not render evidence panel for non-closed changes', () => {
    renderPanel('running')
    expect(screen.queryByText(/evidence bundle/i)).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  // ── Completeness checklist ─────────────────────────────────────────────────

  it('renders incomplete completeness status', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(BASE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getAllByText('incomplete').length).toBeGreaterThan(0)
    })
    expect(screen.getByText(/1\/2 required present/i)).toBeInTheDocument()
  })

  it('renders complete completeness status', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(COMPLETE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getAllByText('complete').length).toBeGreaterThan(0)
    })
    expect(screen.getByText(/2\/2 required present/i)).toBeInTheDocument()
  })

  it('renders invalid completeness status', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(INVALID_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getAllByText('invalid').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText(/invalid/i).length).toBeGreaterThan(0)
  })

  it('renders section rows with correct statuses', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(BASE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('change snapshot')).toBeInTheDocument()
    })
    expect(screen.getByText('closure')).toBeInTheDocument()
  })

  it('renders backend item-level completeness reports without crashing', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(BACKEND_SHAPE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText('change snapshot')).toBeInTheDocument()
    })
    expect(screen.getByText('closure')).toBeInTheDocument()
    expect(screen.getByText(/1\/2 required present/i)).toBeInTheDocument()
  })

  // ── Seal action ────────────────────────────────────────────────────────────

  it('renders seal button when bundle is compiling and complete', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(COMPLETE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /seal bundle/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /seal bundle/i })).not.toBeDisabled()
  })

  it('renders disabled seal button when bundle is compiling but incomplete', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(BASE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /seal bundle/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /seal bundle/i })).toBeDisabled()
  })

  it('does not render seal button for sealed bundles', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(SEALED_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getAllByText('sealed').length).toBeGreaterThan(0)
    })
    expect(screen.queryByRole('button', { name: /seal bundle/i })).not.toBeInTheDocument()
  })

  it('seal action calls the seal API and refreshes bundle query', async () => {
    const sealedResult = { ...COMPLETE_BUNDLE, status: 'sealed', sealed_at: '2026-05-01T11:00:00Z' }
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(COMPLETE_BUNDLE)) // initial bundle query
      .mockResolvedValueOnce(createJsonResponse(sealedResult, { status: 200 })) // seal POST
      .mockResolvedValueOnce(createJsonResponse(sealedResult)) // re-fetch after seal

    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /seal bundle/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /seal bundle/i }))

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(calls.some((url) => url.includes('/evidence-bundles/bundle-1/seal/'))).toBe(true)
    })
  })

  // ── Export dialog ──────────────────────────────────────────────────────────

  it('shows create export button for sealed bundles', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(SEALED_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create export/i })).toBeInTheDocument()
    })
  })

  it('does not show create export button for compiling bundles', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(COMPLETE_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /seal bundle/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /create export/i })).not.toBeInTheDocument()
  })

  it('export dialog creates export via API', async () => {
    const mockExport = {
      id: 'export-1',
      bundle_id: 'bundle-1',
      status: 'ready',
      redaction_policy_id: null,
      requested_by_id: 'user-1',
      requested_at: '2026-05-01T12:00:00Z',
      ready_at: '2026-05-01T12:00:05Z',
      expires_at: '2026-06-01T00:00:00Z',
      source_manifest_sha256: 'deadbeef'.padEnd(64, '0'),
      source_bundle_content_sha256: 'f00d'.padEnd(64, '0'),
      manifest_sha256: 'aa'.padEnd(64, '0'),
      content_sha256: 'bb'.padEnd(64, '0'),
      content_size_bytes: 12345,
      receipt_sha256: 'cc'.padEnd(64, '0'),
      redaction_summary: {},
      failure_code: '',
      storage_deleted_at: null,
      created_at: '2026-05-01T12:00:00Z',
      updated_at: '2026-05-01T12:00:05Z',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(SEALED_BUNDLE))
      .mockResolvedValueOnce(createJsonResponse(mockExport, { status: 201 }))

    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create export/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /create export/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /create evidence export/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /create export/i }))

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(calls.some((url) => url.includes('/evidence-bundles/bundle-1/exports/'))).toBe(true)
    })

    await waitFor(() => {
      expect(screen.getByText(/export created/i)).toBeInTheDocument()
    })
  })

  // ── Legal hold indicator ───────────────────────────────────────────────────

  it('displays legal hold active badge when hold is active', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(SEALED_WITH_HOLD))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByLabelText(/legal hold active/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/HOLD ACTIVE/)).toBeInTheDocument()
  })

  it('displays no-hold state and place hold button when no hold active', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(SEALED_BUNDLE))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByLabelText(/no legal hold/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /place hold/i })).toBeInTheDocument()
  })

  it('legal hold API is called with correct payload', async () => {
    const mockHold = {
      id: 'hold-1',
      status: 'active',
      change_record_id: 'change-1',
      evidence_bundle_id: 'bundle-1',
      reason: 'Required for audit matter MATTER-9999.',
      external_reference: 'MATTER-9999',
      placed_by_id: 'user-1',
      placed_at: '2026-05-01T12:00:00Z',
      released_at: null,
      release_reason: '',
      created_at: '2026-05-01T12:00:00Z',
      updated_at: '2026-05-01T12:00:00Z',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(SEALED_BUNDLE))
      .mockResolvedValueOnce(createJsonResponse(mockHold, { status: 201 }))
      .mockResolvedValueOnce(createJsonResponse({ ...SEALED_BUNDLE, legal_hold_active: true }))

    renderPanel()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /place hold/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /place hold/i }))
    await userEvent.type(screen.getByLabelText(/reason/i), 'Required for audit matter MATTER-9999.')

    await userEvent.click(screen.getByRole('button', { name: /place legal hold/i }))

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(calls.some((url) => url.includes('/evidence-bundles/bundle-1/legal-hold/'))).toBe(true)
    })

    const holdCall = fetchMock.mock.calls.find((c) => String(c[0]).includes('/legal-hold/'))
    expect(holdCall).toBeDefined()
    const body = JSON.parse(String((holdCall?.[1] as RequestInit)?.body)) as Record<string, unknown>
    expect(body.reason).toContain('MATTER-9999')
  })

  // ── No internal API calls ──────────────────────────────────────────────────

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ detail: 'Not found.' }, { status: 404 }))
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText(/no evidence bundle yet/i)).toBeInTheDocument()
    })

    const allCalls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allCalls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
