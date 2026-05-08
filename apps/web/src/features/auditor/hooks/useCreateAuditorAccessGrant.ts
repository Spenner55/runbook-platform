import { useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../auth/context/useAuth'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { createAuditorAccessGrant } from '../api/auditorApi'

export function useCreateAuditorAccessGrant() {
  const queryClient = useQueryClient()
  const { activeOrganizationId } = useAuth()

  return useMutation({
    mutationFn: createAuditorAccessGrant,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.auditorAccessGrants(activeOrganizationId ?? 'unknown-org'),
      })
    },
  })
}
