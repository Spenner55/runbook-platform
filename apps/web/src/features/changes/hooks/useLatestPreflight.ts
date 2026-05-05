import { useQuery } from '@tanstack/react-query'

import { ApiError } from '../../../shared/api/client'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { getLatestPreflight } from '../api/changesApi'

export function useLatestPreflight(changeId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.changePreflight(changeId),
    queryFn: async () => {
      try {
        return await getLatestPreflight(changeId)
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
