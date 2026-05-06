import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getVerificationPlan } from '../api/changesApi'

export function useVerificationPlan(changeId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.changeVerificationPlan(changeId),
    queryFn: () => getVerificationPlan(changeId),
    enabled: Boolean(changeId) && enabled,
  })
}
