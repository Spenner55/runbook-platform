import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExecutionDetailPage } from './ExecutionDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

describe('ExecutionDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders execution detail and polls while the execution is active', async () => {
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
      executionFetchCount += 1
      return createJsonResponse(executionFetchCount === 1 ? runningExecution : finishedExecution)
    })

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    expect(screen.getByText('Loading execution…')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('Polling for runner updates…')).toBeInTheDocument()
    })

    await waitFor(
      () => {
        expect(executionFetchCount).toBe(2)
      },
      { timeout: 3000 }
    )

    expect(screen.getAllByText('succeeded').length).toBeGreaterThan(0)
  })

  it('renders the Django error envelope when execution detail fails', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({ detail: 'execution unavailable' }, { status: 503 })
    )

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

    fetchMock.mockResolvedValue(createJsonResponse(execution))

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

    fetchMock.mockResolvedValue(createJsonResponse(execution))

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

    fetchMock.mockResolvedValue(createJsonResponse(execution))

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

    fetchMock.mockResolvedValue(createJsonResponse(execution))

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
})
