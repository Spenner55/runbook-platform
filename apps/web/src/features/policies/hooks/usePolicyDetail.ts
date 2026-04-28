import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getPolicy } from '../api/policiesApi'

export function usePolicyDetail(policyId: string | null, organizationId: string | null) {
  return useQuery({
    queryKey: queryKeys.policy(policyId ?? '', organizationId ?? ''),
    enabled: Boolean(policyId && organizationId),
    queryFn: () => getPolicy(policyId!, organizationId!),
  })
}
