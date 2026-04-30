import { useEffect, useRef, useState } from 'react'

import { EventStreamContentType, fetchEventSource } from '@microsoft/fetch-event-source'
import { useQueryClient } from '@tanstack/react-query'

import { buildApiUrl } from '../../../shared/api/env'
import { queryKeys } from '../../../shared/lib/queryKeys'
import type { ExecutionDetail } from '../types'
import { applyStreamEvent } from './executionStreamEvents'
import type { ExecutionStreamEvent } from './executionStreamEvents'

const MAX_STREAM_FAILURES = 3

interface UseExecutionStreamInput {
  accessToken: string | null
  enabled: boolean
  executionId: string | null
  onPollingFallback?: () => void
  organizationId: string | null
}

export interface ExecutionStreamState {
  isPollingFallback: boolean
  isStreaming: boolean
  streamClosed: boolean
}

function parseStreamEvent(event: string, data: string): ExecutionStreamEvent | null {
  if (!event || !data) {
    return null
  }

  try {
    const parsed = JSON.parse(data) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return null
    }
    return { event, data: parsed as Record<string, unknown> }
  } catch {
    return null
  }
}

export function useExecutionStream({
  accessToken,
  enabled,
  executionId,
  onPollingFallback,
  organizationId,
}: UseExecutionStreamInput): ExecutionStreamState {
  const queryClient = useQueryClient()
  const [pollingFallbackExecutionId, setPollingFallbackExecutionId] = useState<string | null>(null)
  const [streamingExecutionId, setStreamingExecutionId] = useState<string | null>(null)
  const [closedExecutionId, setClosedExecutionId] = useState<string | null>(null)
  const failureCountRef = useRef(0)
  const lastExecutionIdRef = useRef<string | null>(null)
  const isPollingFallback = Boolean(
    executionId && pollingFallbackExecutionId && pollingFallbackExecutionId === executionId
  )
  const isStreaming = Boolean(
    enabled && executionId && streamingExecutionId && streamingExecutionId === executionId
  )
  const streamClosed = Boolean(
    executionId && closedExecutionId && closedExecutionId === executionId
  )

  useEffect(() => {
    if (lastExecutionIdRef.current !== executionId) {
      failureCountRef.current = 0
      lastExecutionIdRef.current = executionId
    }

    if (!enabled || !executionId || !organizationId || !accessToken || isPollingFallback) {
      return undefined
    }

    let closedByServer = false
    let cancelled = false
    const controller = new AbortController()

    void fetchEventSource(buildApiUrl(`/api/v1/executions/${executionId}/stream/`), {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'X-Organization-Id': organizationId,
      },
      openWhenHidden: true,
      signal: controller.signal,
      async onopen(response) {
        const contentType = response.headers.get('content-type') ?? ''
        if (!response.ok || !contentType.includes(EventStreamContentType)) {
          throw new Error(`Execution stream failed with status ${response.status}.`)
        }
        setStreamingExecutionId(executionId)
      },
      onmessage(message) {
        const streamEvent = parseStreamEvent(message.event, message.data)
        if (!streamEvent) {
          return
        }

        queryClient.setQueryData<ExecutionDetail | undefined>(
          queryKeys.execution(executionId),
          (current) => applyStreamEvent(current, streamEvent)
        )

        if (streamEvent.event === 'stream.closed') {
          closedByServer = true
          setClosedExecutionId(executionId)
          setStreamingExecutionId(null)
          void queryClient.invalidateQueries({ queryKey: queryKeys.execution(executionId) })
          controller.abort()
        }
      },
      onclose() {
        setStreamingExecutionId(null)
        if (!closedByServer && !cancelled) {
          throw new Error('Execution stream closed before terminal state.')
        }
      },
      onerror(error) {
        setStreamingExecutionId(null)
        failureCountRef.current += 1
        if (failureCountRef.current >= MAX_STREAM_FAILURES) {
          setPollingFallbackExecutionId(executionId)
          onPollingFallback?.()
          controller.abort()
          throw error
        }
        // Return undefined to let fetch-event-source honor the server's
        // retry interval (set to 3000ms via "retry: 3000" in the SSE stream).
        return undefined
      },
    }).catch(() => {
      setStreamingExecutionId(null)
    })

    return () => {
      cancelled = true
      setStreamingExecutionId(null)
      controller.abort()
    }
  }, [
    accessToken,
    enabled,
    executionId,
    isPollingFallback,
    onPollingFallback,
    organizationId,
    queryClient,
  ])

  return {
    isPollingFallback,
    isStreaming: isStreaming && !isPollingFallback,
    streamClosed,
  }
}
