import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listPolicies } from '../api/policiesApi'

export function usePolicies(organizationId: string | null, isActive: 'true' | 'false' | 'all' = 'true') {
  return useQuery({
    queryKey: queryKeys.policies(organizationId ?? '', isActive),
    enabled: Boolean(organizationId),
    queryFn: () => listPolicies({ organization_id: organizationId!, is_active: isActive }),
  })
}
