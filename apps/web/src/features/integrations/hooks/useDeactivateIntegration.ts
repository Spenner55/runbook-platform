import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { deactivateIntegration } from '../api/integrationsApi'

export function useDeactivateIntegration(integrationId: string, organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deactivateIntegration(integrationId, organizationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.integrations(organizationId) })
      queryClient.invalidateQueries({
        queryKey: queryKeys.integration(integrationId, organizationId),
      })
    },
  })
}
