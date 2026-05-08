import { useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../auth/context/useAuth'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { revokeAuditorAccessGrant } from '../api/auditorApi'

export function useRevokeAuditorAccessGrant() {
  const queryClient = useQueryClient()
  const { activeOrganizationId } = useAuth()

  return useMutation({
    mutationFn: revokeAuditorAccessGrant,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.auditorAccessGrants(activeOrganizationId ?? 'unknown-org'),
      })
    },
  })
}
