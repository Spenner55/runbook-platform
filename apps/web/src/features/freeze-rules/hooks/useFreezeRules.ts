import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listFreezeRules } from '../api/freezeRulesApi'

export function useFreezeRules(
  organizationId: string | null,
  isActive: 'true' | 'false' | 'all' = 'all'
) {
  return useQuery({
    queryKey: queryKeys.freezeRules(organizationId ?? '', isActive),
    enabled: Boolean(organizationId),
    queryFn: () => listFreezeRules({ organization_id: organizationId!, is_active: isActive }),
  })
}
