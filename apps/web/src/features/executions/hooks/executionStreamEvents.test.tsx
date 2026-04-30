import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { queryKeys } from '../../../shared/lib/queryKeys'
import type { ExecutionDetail } from '../types'
import { applyStreamEvent } from './executionStreamEvents'
import { useExecutionStream } from './useExecutionStream'

const fetchEventSourceMock = vi.hoisted(() => vi.fn())

vi.mock('@microsoft/fetch-event-source', () => ({
  EventStreamContentType: 'text/event-stream',
  fetchEventSource: fetchEventSourceMock,
}))

function executionDetail(overrides: Partial<ExecutionDetail> = {}): ExecutionDetail {
  return {
    id: 'execution-1',
    status: 'running',
    workflow_id: 'workflow-1',
    organization_id: 'org-1',
    workflow_version: 1,
    workflow_snapshot: {},
    claimed_by_runner_id: 'runner-1',
    claimed_at: null,
    last_heartbeat_at: null,
    started_at: null,
    finished_at: null,
    created_at: '2026-04-15T10:00:00Z',
    updated_at: '2026-04-15T10:00:00Z',
    steps: [
      {
        id: 'step-1',
        position: 1,
        step_key: 'deploy',
        name: 'Deploy',
        step_type: 'shell',
        risk_level: 'low',
        command: 'deploy.sh',
        requires_approval: false,
        status: 'pending',
        started_at: null,
        finished_at: null,
        exit_code: null,
        error_message: '',
        policy_evaluation: null,
      },
    ],
    ...overrides,
  }
}

function streamResponse(): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'text/event-stream' }),
  } as Response
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('applyStreamEvent', () => {
  it('updates execution status', () => {
    const updated = applyStreamEvent(executionDetail(), {
      event: 'execution.status_changed',
      data: {
        execution_id: 'execution-1',
        status: 'succeeded',
        started_at: '2026-04-15T10:00:01Z',
        finished_at: '2026-04-15T10:00:30Z',
      },
    })

    expect(updated?.status).toBe('succeeded')
    expect(updated?.started_at).toBe('2026-04-15T10:00:01Z')
    expect(updated?.finished_at).toBe('2026-04-15T10:00:30Z')
  })

  it('updates step status', () => {
    const updated = applyStreamEvent(executionDetail(), {
      event: 'step.status_changed',
      data: {
        execution_id: 'execution-1',
        step_id: 'step-1',
        position: 1,
        status: 'failed',
        started_at: '2026-04-15T10:00:05Z',
        finished_at: '2026-04-15T10:00:10Z',
        exit_code: 1,
        error_message: 'command failed',
      },
    })

    expect(updated?.steps[0]?.status).toBe('failed')
    expect(updated?.steps[0]?.exit_code).toBe(1)
    expect(updated?.steps[0]?.error_message).toBe('command failed')
  })
})

describe('useExecutionStream', () => {
  beforeEach(() => {
    fetchEventSourceMock.mockReset()
  })

  it('stream.closed disables streaming', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(queryKeys.execution('execution-1'), executionDetail())
    let options!: {
      onopen: (response: Response) => Promise<void>
      onmessage: (message: { event: string; data: string }) => void
    }

    fetchEventSourceMock.mockImplementation((_url, streamOptions) => {
      options = streamOptions
      return new Promise(() => {})
    })

    const { result } = renderHook(
      () =>
        useExecutionStream({
          accessToken: 'access-token',
          enabled: true,
          executionId: 'execution-1',
          organizationId: 'org-1',
        }),
      { wrapper: createWrapper(queryClient) }
    )

    await act(async () => {
      await options.onopen(streamResponse())
    })
    expect(result.current.isStreaming).toBe(true)

    act(() => {
      options.onmessage({
        event: 'stream.closed',
        data: JSON.stringify({
          execution_id: 'execution-1',
          final_status: 'succeeded',
          reason: 'terminal_state',
        }),
      })
    })

    expect(result.current.isStreaming).toBe(false)
    expect(result.current.streamClosed).toBe(true)
    expect(queryClient.getQueryData<ExecutionDetail>(queryKeys.execution('execution-1'))?.status).toBe(
      'succeeded'
    )
  })

  it('3 failures activate polling fallback', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let options!: { onerror: (error: Error) => number | void }
    const onPollingFallback = vi.fn()

    fetchEventSourceMock.mockImplementation((_url, streamOptions) => {
      options = streamOptions
      return new Promise(() => {})
    })

    const { result } = renderHook(
      () =>
        useExecutionStream({
          accessToken: 'access-token',
          enabled: true,
          executionId: 'execution-1',
          onPollingFallback,
          organizationId: 'org-1',
        }),
      { wrapper: createWrapper(queryClient) }
    )

    act(() => {
      options.onerror(new Error('failure 1'))
      options.onerror(new Error('failure 2'))
      try {
        options.onerror(new Error('failure 3'))
      } catch {
        // fetch-event-source stops retrying after the hook aborts the stream.
      }
    })

    await waitFor(() => {
      expect(result.current.isPollingFallback).toBe(true)
    })
    expect(onPollingFallback).toHaveBeenCalledTimes(1)
  })

  it('does not append token to stream URL', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    fetchEventSourceMock.mockImplementation(() => new Promise(() => {}))

    renderHook(
      () =>
        useExecutionStream({
          accessToken: 'access-token',
          enabled: true,
          executionId: 'execution-1',
          organizationId: 'org-1',
        }),
      { wrapper: createWrapper(queryClient) }
    )

    const [url, options] = fetchEventSourceMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/v1\/executions\/execution-1\/stream\/$/)
    expect(String(url)).not.toContain('access-token')
    expect(options.headers.Authorization).toBe('Bearer access-token')
  })

  it('onerror returns undefined so the server retry interval is honored', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let options!: { onerror: (error: Error) => number | undefined | void }

    fetchEventSourceMock.mockImplementation((_url, streamOptions) => {
      options = streamOptions
      return new Promise(() => {})
    })

    renderHook(
      () =>
        useExecutionStream({
          accessToken: 'access-token',
          enabled: true,
          executionId: 'execution-1',
          organizationId: 'org-1',
        }),
      { wrapper: createWrapper(queryClient) }
    )

    // First two failures should return undefined, not 0.
    const result1 = options.onerror(new Error('failure 1'))
    const result2 = options.onerror(new Error('failure 2'))
    expect(result1).toBeUndefined()
    expect(result2).toBeUndefined()
  })

  it('fallback activates after repeated premature stream closes', async () => {
    // A premature close sequence: onopen (200) → onclose (throws) → onerror.
    // Because onopen no longer resets the failure count, each premature close
    // accumulates toward MAX_STREAM_FAILURES (3).
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const onPollingFallback = vi.fn()
    let options!: {
      onopen: (response: Response) => Promise<void>
      onclose: () => void
      onerror: (error: Error) => number | undefined | void
    }

    fetchEventSourceMock.mockImplementation((_url, streamOptions) => {
      options = streamOptions
      return new Promise(() => {})
    })

    const { result } = renderHook(
      () =>
        useExecutionStream({
          accessToken: 'access-token',
          enabled: true,
          executionId: 'execution-1',
          onPollingFallback,
          organizationId: 'org-1',
        }),
      { wrapper: createWrapper(queryClient) }
    )

    // Simulate 3 premature closes (MAX_STREAM_FAILURES): each opens (200) then immediately closes.
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        await options.onopen(streamResponse())
      })
      act(() => {
        // onclose throws for premature close → library calls onerror
        try {
          options.onclose()
        } catch {
          // expected: onclose throws to signal failure
        }
        try {
          options.onerror(new Error(`premature close ${i + 1}`))
        } catch {
          // onerror throws on final failure to stop retrying
        }
      })
    }

    await waitFor(() => {
      expect(result.current.isPollingFallback).toBe(true)
    })
    expect(onPollingFallback).toHaveBeenCalledTimes(1)
  })
})
