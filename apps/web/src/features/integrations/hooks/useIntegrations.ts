import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listIntegrations } from '../api/integrationsApi'

export function useIntegrations(organizationId: string | null) {
  return useQuery({
    queryKey: queryKeys.integrations(organizationId ?? ''),
    enabled: Boolean(organizationId),
    queryFn: () => listIntegrations(organizationId!),
  })
}
