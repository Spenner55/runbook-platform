import { useQuery } from '@tanstack/react-query'

import { useAuth } from '../../auth/context/useAuth'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { listAuditorAccessGrants } from '../api/auditorApi'

export function useAuditorAccessGrants() {
  const { activeOrganizationId } = useAuth()

  return useQuery({
    queryKey: queryKeys.auditorAccessGrants(activeOrganizationId ?? 'unknown-org'),
    queryFn: listAuditorAccessGrants,
  })
}
