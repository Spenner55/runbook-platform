import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExecutionDetailPage } from './ExecutionDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const fetchEventSourceMock = vi.hoisted(() => vi.fn())

vi.mock('@microsoft/fetch-event-source', () => ({
  EventStreamContentType: 'text/event-stream',
  fetchEventSource: fetchEventSourceMock,
}))

const emptyArtifacts = { count: 0, next: null, previous: null, results: [] }

describe('ExecutionDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    fetchEventSourceMock.mockImplementation(async (_url, options) => {
      await options.onopen({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/event-stream' }),
      } as Response)
      return new Promise(() => {})
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
    fetchEventSourceMock.mockReset()
  })

  it('renders execution detail and shows the streaming banner while the execution is active', async () => {
    const runningExecution = {
      id: 'execution-1',
      status: 'running',
      workflow_id: 'workflow-1',
      organization_id: 'organization-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: '2026-04-15T10:00:01Z',
      last_heartbeat_at: '2026-04-15T10:00:10Z',
      started_at: '2026-04-15T10:00:00Z',
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'step-1',
          name: 'Verify prerequisites',
          step_type: 'manual',
          risk_level: 'low',
          command: '',
          requires_approval: false,
          status: 'running',
          started_at: '2026-04-15T10:00:05Z',
          finished_at: null,
          exit_code: null,
          error_message: '',
        },
      ],
    }

    const finishedExecution = {
      ...runningExecution,
      status: 'succeeded',
      finished_at: '2026-04-15T10:02:00Z',
      steps: [
        {
          ...runningExecution.steps[0],
          status: 'succeeded',
          finished_at: '2026-04-15T10:01:30Z',
          exit_code: 0,
        },
      ],
    }

    let executionFetchCount = 0
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/audit/')) {
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      }
      if (url.includes('/artifacts/')) {
        return createJsonResponse(emptyArtifacts)
      }
      executionFetchCount += 1
      return createJsonResponse(executionFetchCount === 1 ? runningExecution : finishedExecution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    expect(screen.getByText('Loading execution…')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('Receiving live updates.')).toBeInTheDocument()
    })

    expect(executionFetchCount).toBe(1)
  })

  it('refetches canonical execution detail when the stream closes', async () => {
    const runningExecution = {
      id: 'execution-1',
      status: 'running',
      workflow_id: 'workflow-1',
      organization_id: 'organization-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: '2026-04-15T10:00:01Z',
      last_heartbeat_at: '2026-04-15T10:00:10Z',
      started_at: '2026-04-15T10:00:00Z',
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'verify',
          name: 'Verify prerequisites',
          step_type: 'shell',
          risk_level: 'low',
          command: 'verify.sh',
          requires_approval: false,
          status: 'succeeded',
          started_at: '2026-04-15T10:00:05Z',
          finished_at: '2026-04-15T10:00:10Z',
          exit_code: 0,
          error_message: '',
        },
        {
          id: 'step-2',
          position: 2,
          step_key: 'deploy',
          name: 'Deploy service',
          step_type: 'shell',
          risk_level: 'high',
          command: 'deploy.sh',
          requires_approval: true,
          status: 'waiting_for_approval',
          started_at: null,
          finished_at: null,
          exit_code: null,
          error_message: '',
        },
      ],
    }
    const finishedExecution = {
      ...runningExecution,
      status: 'succeeded',
      finished_at: '2026-04-15T10:02:00Z',
      steps: runningExecution.steps.map((step) => ({
        ...step,
        status: 'succeeded',
        started_at: step.started_at ?? '2026-04-15T10:01:00Z',
        finished_at: step.finished_at ?? '2026-04-15T10:01:30Z',
        exit_code: step.exit_code ?? 0,
      })),
    }

    let streamOptions!: {
      onopen: (response: Response) => Promise<void>
      onmessage: (message: { event: string; data: string }) => void
    }
    fetchEventSourceMock.mockImplementation((_url, options) => {
      streamOptions = options
      return new Promise(() => {})
    })

    let executionFetchCount = 0
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/audit/')) {
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      }
      if (url.includes('/artifacts/')) {
        return createJsonResponse(emptyArtifacts)
      }
      executionFetchCount += 1
      return createJsonResponse(executionFetchCount === 1 ? runningExecution : finishedExecution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(streamOptions).toBeDefined()
    })
    await act(async () => {
      await streamOptions.onopen({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/event-stream' }),
      } as Response)
    })

    await waitFor(() => {
      expect(screen.getByText('Receiving live updates.')).toBeInTheDocument()
    })

    await act(async () => {
      streamOptions.onmessage({
        event: 'stream.closed',
        data: JSON.stringify({
          execution_id: 'execution-1',
          final_status: 'succeeded',
          reason: 'terminal_state',
        }),
      })
    })

    await waitFor(() => {
      expect(executionFetchCount).toBeGreaterThanOrEqual(2)
    })
    expect(screen.getAllByText('succeeded').length).toBeGreaterThan(0)
    expect(screen.getAllByText('exit 0').length).toBeGreaterThan(0)
  })

  it('shows the polling fallback banner when streaming is unavailable', async () => {
    const runningExecution = {
      id: 'execution-1',
      status: 'running',
      workflow_id: 'workflow-1',
      organization_id: 'organization-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: '2026-04-15T10:00:00Z',
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }

    fetchEventSourceMock.mockImplementation((_url, options) => {
      options.onerror(new Error('stream failed'))
      options.onerror(new Error('stream failed'))
      try {
        options.onerror(new Error('stream failed'))
      } catch {
        // The hook throws on the third failure to stop fetch-event-source retries.
      }
      return Promise.resolve()
    })

    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/audit/')) {
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      }
      if (url.includes('/artifacts/')) {
        return createJsonResponse(emptyArtifacts)
      }
      return createJsonResponse(runningExecution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Polling for updates (streaming unavailable).')).toBeInTheDocument()
    })
  })

  it('renders the Django error envelope when execution detail fails', async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(emptyArtifacts)
      return createJsonResponse({ detail: 'execution unavailable' }, { status: 503 })
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('execution unavailable')).toBeInTheDocument()
    })
  })

  it('renders policy evaluation badge with effective outcome and policy name', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: '2026-04-15T10:00:01Z',
      last_heartbeat_at: '2026-04-15T10:00:10Z',
      started_at: '2026-04-15T10:00:00Z',
      finished_at: '2026-04-15T10:02:00Z',
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:02:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'step-1',
          name: 'Deploy service',
          step_type: 'shell',
          risk_level: 'high',
          command: 'deploy.sh',
          requires_approval: true,
          status: 'succeeded',
          started_at: '2026-04-15T10:00:05Z',
          finished_at: '2026-04-15T10:01:30Z',
          exit_code: 0,
          error_message: '',
          policy_evaluation: {
            id: 'eval-1',
            outcome: 'approval_required',
            effective_outcome: 'approval_required',
            decision_source: 'policy_rule',
            matched: true,
            policy_id: 'policy-1',
            policy_name: 'Production Safety Policy',
            rule_id: 'rule-1',
            rule_name: 'High risk approval',
            reason: 'High risk requires sign-off',
            evaluated_at: '2026-04-15T10:00:04Z',
          },
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(emptyArtifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Approval Required')).toBeInTheDocument()
    })

    expect(screen.getByText(/Production Safety Policy/i)).toBeInTheDocument()
    expect(screen.getByText(/High risk approval/i)).toBeInTheDocument()
    expect(screen.getByText(/High risk requires sign-off/i)).toBeInTheDocument()
  })

  it('renders floor-applied warning when outcome differs from effective_outcome', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: '2026-04-15T10:00:00Z',
      finished_at: '2026-04-15T10:02:00Z',
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:02:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'step-1',
          name: 'Deploy service',
          step_type: 'shell',
          risk_level: 'low',
          command: 'deploy.sh',
          requires_approval: true,
          status: 'succeeded',
          started_at: '2026-04-15T10:00:05Z',
          finished_at: '2026-04-15T10:01:30Z',
          exit_code: 0,
          error_message: '',
          policy_evaluation: {
            id: 'eval-1',
            outcome: 'auto_approve',
            effective_outcome: 'approval_required',
            decision_source: 'policy_rule',
            matched: true,
            policy_id: 'policy-1',
            policy_name: 'Low risk policy',
            rule_id: 'rule-1',
            rule_name: 'Low risk auto',
            reason: '',
            evaluated_at: '2026-04-15T10:00:04Z',
          },
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(emptyArtifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText(/Approval Required floor was applied/i)).toBeInTheDocument()
    })
  })

  it('renders workflow default label when decision_source is workflow_default', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: null,
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: '2026-04-15T10:00:00Z',
      finished_at: '2026-04-15T10:02:00Z',
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:02:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'step-1',
          name: 'Verify prereqs',
          step_type: 'manual',
          risk_level: 'low',
          command: '',
          requires_approval: false,
          status: 'succeeded',
          started_at: '2026-04-15T10:00:05Z',
          finished_at: '2026-04-15T10:01:30Z',
          exit_code: 0,
          error_message: '',
          policy_evaluation: {
            id: 'eval-1',
            outcome: 'auto_approve',
            effective_outcome: 'auto_approve',
            decision_source: 'workflow_default',
            matched: false,
            policy_id: null,
            policy_name: null,
            rule_id: null,
            rule_name: null,
            reason: '',
            evaluated_at: '2026-04-15T10:00:04Z',
          },
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(emptyArtifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Auto Approved')).toBeInTheDocument()
    })

    expect(screen.getByText('Workflow default')).toBeInTheDocument()
  })

  it('distinguishes policy blocked failures from generic step errors', async () => {
    const execution = {
      id: 'execution-1',
      status: 'failed',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: '2026-04-15T10:00:00Z',
      finished_at: '2026-04-15T10:02:00Z',
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:02:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'step-1',
          name: 'Deploy service',
          step_type: 'shell',
          risk_level: 'critical',
          command: 'deploy.sh',
          requires_approval: false,
          status: 'failed',
          started_at: null,
          finished_at: '2026-04-15T10:01:30Z',
          exit_code: null,
          error_message: 'policy_blocked',
          policy_evaluation: {
            id: 'eval-1',
            outcome: 'block',
            effective_outcome: 'block',
            decision_source: 'policy_rule',
            matched: true,
            policy_id: 'policy-1',
            policy_name: 'Production Safety Policy',
            rule_id: 'rule-1',
            rule_name: 'Block critical',
            reason: 'Critical steps are blocked.',
            evaluated_at: '2026-04-15T10:00:04Z',
          },
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(emptyArtifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText(/Blocked by policy before command execution/i)).toBeInTheDocument()
    })

    expect(screen.queryByText('policy_blocked')).not.toBeInTheDocument()
  })

  it('renders execution audit trail events', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: '2026-04-15T10:00:01Z',
      last_heartbeat_at: '2026-04-15T10:00:10Z',
      started_at: '2026-04-15T10:00:00Z',
      finished_at: '2026-04-15T10:02:00Z',
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:02:00Z',
      steps: [],
    }

    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/artifacts/')) {
        return createJsonResponse(emptyArtifacts)
      }
      if (url.includes('/audit/')) {
        return createJsonResponse({
          count: 2,
          next: null,
          previous: null,
          results: [
            {
              id: 'audit-2',
              actor_type: 'runner',
              actor_id: 'runner-dev-01',
              actor_label: 'runner-dev-01',
              event_type: 'execution_step.started',
              object_type: 'execution_step',
              object_id: 'step-1',
              organization_id: 'org-1',
              metadata: {
                execution_id: 'execution-1',
                step_key: 'deploy',
                previous_status: 'pending',
                new_status: 'running',
                risk_level: 'high',
              },
              occurred_at: '2026-04-15T10:00:05Z',
            },
            {
              id: 'audit-1',
              actor_type: 'unknown',
              actor_id: '',
              actor_label: 'Unauthenticated public API',
              event_type: 'execution.created',
              object_type: 'execution',
              object_id: 'execution-1',
              organization_id: 'org-1',
              metadata: { initial_status: 'queued' },
              occurred_at: '2026-04-15T10:00:00Z',
            },
          ],
        })
      }
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('execution created')).toBeInTheDocument()
    })

    expect(screen.getByText('execution step started')).toBeInTheDocument()
    expect(screen.getByText(/From pending to running/i)).toBeInTheDocument()
    expect(screen.getByText(/Step deploy/i)).toBeInTheDocument()
  })

  it('renders artifact panel with empty state when no artifacts', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: '2026-04-15T10:00:01Z',
      last_heartbeat_at: null,
      started_at: '2026-04-15T10:00:00Z',
      finished_at: '2026-04-15T10:02:00Z',
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:02:00Z',
      steps: [],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(emptyArtifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('No artifacts uploaded yet.')).toBeInTheDocument()
    })
  })

  it('renders artifact rows with name, kind, and download button', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: 'runner-dev-01',
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }

    const artifacts = {
      count: 2,
      next: null,
      previous: null,
      results: [
        {
          id: 'artifact-1',
          execution_id: 'execution-1',
          step_id: 'step-1',
          kind: 'stdout',
          name: 'stdout.txt',
          mime_type: 'text/plain; charset=utf-8',
          size_bytes: 1024,
          checksum_sha256: 'a'.repeat(64),
          uploaded_by_runner_id: 'runner-dev',
          uploaded_at: '2026-04-15T10:01:00Z',
          metadata: { truncated: false },
        },
        {
          id: 'artifact-2',
          execution_id: 'execution-1',
          step_id: 'step-1',
          kind: 'stderr',
          name: 'stderr.txt',
          mime_type: 'text/plain; charset=utf-8',
          size_bytes: 256,
          checksum_sha256: 'b'.repeat(64),
          uploaded_by_runner_id: 'runner-dev',
          uploaded_at: '2026-04-15T10:01:01Z',
          metadata: { truncated: false },
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(artifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('stdout.txt')).toBeInTheDocument()
    })
    expect(screen.getByText('stderr.txt')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Download/i })).toHaveLength(2)
  })

  it('shows truncated indicator when artifact metadata.truncated is true', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: null,
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }

    const artifacts = {
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 'artifact-1',
          execution_id: 'execution-1',
          step_id: 'step-1',
          kind: 'stdout',
          name: 'stdout.txt',
          mime_type: 'text/plain; charset=utf-8',
          size_bytes: 5242880,
          checksum_sha256: 'a'.repeat(64),
          uploaded_by_runner_id: 'runner-dev',
          uploaded_at: '2026-04-15T10:01:00Z',
          metadata: {
            truncated: true,
            original_size_bytes: 10485760,
            captured_size_bytes: 5242880,
            truncation_reason: 'stream_limit',
          },
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes('/artifacts/')) return createJsonResponse(artifacts)
      if (String(input).includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText(/Output truncated/i)).toBeInTheDocument()
    })
  })

  it('download button fetches artifact content with auth headers', async () => {
    const createObjectURLSpy = vi.fn(() => 'blob:artifact-download')
    const revokeObjectURLSpy = vi.fn()
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: createObjectURLSpy,
      revokeObjectURL: revokeObjectURLSpy,
    })

    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: null,
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }

    const artifacts = {
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 'artifact-1',
          execution_id: 'execution-1',
          step_id: null,
          kind: 'stdout',
          name: 'stdout.txt',
          mime_type: 'text/plain; charset=utf-8',
          size_bytes: 100,
          checksum_sha256: 'a'.repeat(64),
          uploaded_by_runner_id: 'runner-dev',
          uploaded_at: '2026-04-15T10:01:00Z',
          metadata: {},
        },
      ],
    }

    const downloadResponse = {
      artifact_id: 'artifact-1',
      download_url:
        '/api/v1/artifacts/artifact-1/content/?organization_id=org-1&token=signed-token',
      expires_at: '2026-04-15T10:10:00Z',
      method: 'GET',
      content_disposition: 'attachment',
      filename: 'stdout.txt',
    }

    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/artifacts/') && url.includes('/download/')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(String(init?.body))).toEqual({ organization_id: 'org-1' })
        return createJsonResponse(downloadResponse)
      }
      if (url.includes('/artifacts/') && url.includes('/content/')) {
        expect(url).toBe(
          'http://localhost:8000/api/v1/artifacts/artifact-1/content/?organization_id=org-1&token=signed-token'
        )
        const headers = new Headers(init?.headers)
        expect(headers.get('Authorization')).toBe('Bearer test-token')
        expect(headers.get('X-Organization-Id')).toBe('org-1')
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'text/plain' }),
          blob: async () => new Blob(['artifact content'], { type: 'text/plain' }),
        } as Response
      }
      if (url.includes('/artifacts/')) return createJsonResponse(artifacts)
      if (url.includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Download/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Download/i }))

    await waitFor(() => {
      expect(createObjectURLSpy).toHaveBeenCalledWith(expect.any(Blob))
    })
    expect(clickSpy).toHaveBeenCalled()
    expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:artifact-download')
    clickSpy.mockRestore()
  })

  it('shows artifact list load errors', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: null,
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }

    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/artifacts/')) {
        return createJsonResponse(
          { errors: [{ code: 'artifact_storage_failed', detail: 'Artifact store unavailable.' }] },
          { status: 503 }
        )
      }
      if (url.includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Artifact store unavailable.')).toBeInTheDocument()
    })
  })

  it('shows download errors on the artifact row', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: null,
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }
    const artifacts = {
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 'artifact-1',
          execution_id: 'execution-1',
          step_id: null,
          kind: 'stdout',
          name: 'stdout.txt',
          mime_type: 'text/plain; charset=utf-8',
          size_bytes: 100,
          checksum_sha256: 'a'.repeat(64),
          uploaded_by_runner_id: 'runner-dev',
          uploaded_at: '2026-04-15T10:01:00Z',
          metadata: {},
        },
      ],
    }

    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/artifacts/') && url.includes('/download/')) {
        return createJsonResponse(
          { errors: [{ code: 'audit_unavailable', detail: 'Download audit failed.' }] },
          { status: 503 }
        )
      }
      if (url.includes('/artifacts/')) return createJsonResponse(artifacts)
      if (url.includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Download/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Download/i }))

    await waitFor(() => {
      expect(screen.getByText('Download audit failed.')).toBeInTheDocument()
    })
  })

  it('shows content fetch errors on the artifact row', async () => {
    const execution = {
      id: 'execution-1',
      status: 'succeeded',
      workflow_id: 'workflow-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      claimed_by_runner_id: null,
      claimed_at: null,
      last_heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [],
    }
    const artifacts = {
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 'artifact-1',
          execution_id: 'execution-1',
          step_id: null,
          kind: 'stdout',
          name: 'stdout.txt',
          mime_type: 'text/plain; charset=utf-8',
          size_bytes: 100,
          checksum_sha256: 'a'.repeat(64),
          uploaded_by_runner_id: 'runner-dev',
          uploaded_at: '2026-04-15T10:01:00Z',
          metadata: {},
        },
      ],
    }
    const downloadResponse = {
      artifact_id: 'artifact-1',
      download_url:
        '/api/v1/artifacts/artifact-1/content/?organization_id=org-1&token=signed-token',
      expires_at: '2026-04-15T10:10:00Z',
      method: 'GET',
      content_disposition: 'attachment',
      filename: 'stdout.txt',
    }

    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/artifacts/') && url.includes('/download/')) {
        return createJsonResponse(downloadResponse)
      }
      if (url.includes('/artifacts/') && url.includes('/content/')) {
        return createJsonResponse(
          {
            errors: [{ code: 'artifact_not_found', detail: 'Artifact file not found in storage.' }],
          },
          { status: 404 }
        )
      }
      if (url.includes('/artifacts/')) return createJsonResponse(artifacts)
      if (url.includes('/audit/'))
        return createJsonResponse({ count: 0, next: null, previous: null, results: [] })
      return createJsonResponse(execution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Download/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Download/i }))

    await waitFor(() => {
      expect(screen.getByText('Artifact file not found in storage.')).toBeInTheDocument()
    })
  })
})
