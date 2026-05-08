import { useQuery } from '@tanstack/react-query'

import { useAuth } from '../../auth/context/useAuth'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { getAuditChangeDetail } from '../api/auditorApi'

export function useAuditChangeDetail(changeId: string | undefined) {
  const { activeOrganizationId } = useAuth()

  return useQuery({
    queryKey: queryKeys.auditChange(activeOrganizationId ?? 'unknown-org', changeId ?? ''),
    queryFn: () => getAuditChangeDetail(changeId ?? ''),
    enabled: Boolean(changeId),
  })
}
