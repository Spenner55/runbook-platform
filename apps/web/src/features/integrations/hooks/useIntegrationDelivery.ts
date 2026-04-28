import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listIntegrationDeliveryAttempts } from '../api/integrationsApi'

export function useIntegrationDelivery(
  integrationId: string | undefined,
  organizationId: string | null
) {
  return useQuery({
    queryKey: queryKeys.integrationDelivery(integrationId ?? '', organizationId ?? ''),
    enabled: Boolean(integrationId && organizationId),
    queryFn: () => listIntegrationDeliveryAttempts(integrationId!, organizationId!),
  })
}
