import { useQuery } from '@tanstack/react-query'

import { ApiError } from '../../../shared/api/client'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { getLatestEvidenceBundle } from '../api/evidenceApi'

export function useLatestEvidenceBundle(changeId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.latestEvidenceBundle(changeId),
    queryFn: async () => {
      try {
        return await getLatestEvidenceBundle(changeId)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return null
        }
        throw error
      }
    },
    enabled: Boolean(changeId) && enabled,
  })
}
