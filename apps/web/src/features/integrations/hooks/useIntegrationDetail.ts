import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getIntegration } from '../api/integrationsApi'

export function useIntegrationDetail(
  integrationId: string | undefined,
  organizationId: string | null
) {
  return useQuery({
    queryKey: queryKeys.integration(integrationId ?? '', organizationId ?? ''),
    enabled: Boolean(integrationId && organizationId),
    queryFn: () => getIntegration(integrationId!, organizationId!),
  })
}
