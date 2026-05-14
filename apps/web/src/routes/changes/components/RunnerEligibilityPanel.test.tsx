import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunnerEligibilityPanel } from './RunnerEligibilityPanel'
import { createJsonResponse } from '../../../test/fetchResponse'
import { renderRoute } from '../../../test/renderRoute'

function renderPanel(changeId: string, enabled = true) {
  return renderRoute(<RunnerEligibilityPanel changeId={changeId} enabled={enabled} />, {
    path: '/changes/:changeId',
    route: `/changes/${changeId}`,
  })
}

describe('RunnerEligibilityPanel', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders nothing when disabled', () => {
    renderPanel('change-1', false)
    expect(screen.queryByTestId('runner-eligibility-panel')).not.toBeInTheDocument()
  })

  it('shows eligible state with pool info', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: true,
        pool_key: 'prod-us-east',
        pool_id: 'pool-1',
        pool_status: 'active',
        reason: 'ok',
        online_runners_count: 3,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByTestId('runner-eligibility-panel')).toBeInTheDocument()
    })

    expect(screen.getByText('eligible')).toBeInTheDocument()
    expect(screen.getByText('prod-us-east')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows ineligible state with route miss reason', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: null,
        pool_id: null,
        pool_status: null,
        reason: 'route_miss',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText('ineligible')).toBeInTheDocument()
    })

    expect(
      screen.getByText(/Route miss — no connectivity route matches the change target/i)
    ).toBeInTheDocument()
  })

  it('shows no eligible runner pool reason', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: null,
        pool_id: null,
        pool_status: null,
        reason: 'no_routes_configured',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText(/No eligible runner pool/i)).toBeInTheDocument()
    })
  })

  it('shows missing capabilities reason', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: null,
        pool_id: null,
        pool_status: null,
        reason: 'missing_required_capability',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText(/Missing capabilities/i)).toBeInTheDocument()
    })
  })

  it('shows no online runner reason', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: 'prod-us-east',
        pool_id: 'pool-1',
        pool_status: 'active',
        reason: 'no_online_runner',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText(/No online runner/i)).toBeInTheDocument()
    })
  })

  it('shows cross-pool target mismatch reason', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: null,
        pool_id: null,
        pool_status: null,
        reason: 'multi_pool_unsupported',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText(/Cross-pool target mismatch/i)).toBeInTheDocument()
    })
  })

  it('shows pool draining reason', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: 'prod-us-east',
        pool_id: 'pool-1',
        pool_status: 'draining',
        reason: 'pool_draining',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText(/Pool is draining/i)).toBeInTheDocument()
    })
  })

  it('calls public runner-eligibility endpoint only (not internal)', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      urls.push(String(input))
      return createJsonResponse({
        eligible: true,
        pool_key: 'prod',
        pool_id: 'pool-1',
        pool_status: 'active',
        reason: 'ok',
        online_runners_count: 1,
      })
    })

    renderPanel('change-abc')

    await waitFor(() => {
      expect(urls.some((u) => u.includes('/runner-eligibility/'))).toBe(true)
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
    expect(urls.every((u) => u.startsWith('http://localhost:8000/api/v1/'))).toBe(true)
  })

  it('does not display tokens, credentials, or raw secret names', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: true,
        pool_key: 'prod',
        pool_id: 'pool-1',
        pool_status: 'active',
        reason: 'ok',
        online_runners_count: 2,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByTestId('runner-eligibility-panel')).toBeInTheDocument()
    })

    expect(screen.queryByText(/token/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/credential/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/RUNNER_REGISTRATION_TOKEN/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/fingerprint/i)).not.toBeInTheDocument()
  })

  it('shows runner eligibility failures from change preflight context', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({
        eligible: false,
        pool_key: null,
        pool_id: null,
        pool_status: null,
        reason: 'no_online_runner',
        online_runners_count: 0,
      })
    )

    renderPanel('change-1')

    await waitFor(() => {
      expect(screen.getByText('ineligible')).toBeInTheDocument()
    })

    expect(screen.getByText(/No online runner/i)).toBeInTheDocument()
  })
})
