import { useCallback, useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { useAuth } from '../../auth/context/useAuth'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { getExecution } from '../api/executionsApi'
import { useExecutionStream } from './useExecutionStream'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

export function useExecutionDetail(executionId: string | null) {
  const { accessToken, activeOrganizationId } = useAuth()
  const [pollingFallbackExecutionId, setPollingFallbackExecutionId] = useState<string | null>(null)
  const isPollingFallback = Boolean(
    executionId && pollingFallbackExecutionId && pollingFallbackExecutionId === executionId
  )
  const activatePollingFallback = useCallback(() => {
    setPollingFallbackExecutionId(executionId)
  }, [executionId])

  const query = useQuery({
    queryKey: queryKeys.execution(executionId ?? 'missing'),
    enabled: Boolean(executionId),
    queryFn: () => getExecution(executionId ?? ''),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!status || !ACTIVE_EXECUTION_STATUSES.has(status)) {
        return false
      }
      return isPollingFallback ? 1500 : false
    },
  })

  const isActiveExecution = Boolean(
    query.data?.status && ACTIVE_EXECUTION_STATUSES.has(query.data.status)
  )
  const stream = useExecutionStream({
    accessToken,
    enabled: Boolean(executionId) && isActiveExecution && !isPollingFallback,
    executionId,
    onPollingFallback: activatePollingFallback,
    organizationId: query.data?.organization_id ?? activeOrganizationId,
  })

  return {
    ...query,
    isPollingFallback,
    isStreaming: stream.isStreaming,
    streamClosed: stream.streamClosed,
  }
}
