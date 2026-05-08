import { useQuery } from '@tanstack/react-query'

import { useAuth } from '../../auth/context/useAuth'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { searchAuditChanges } from '../api/auditorApi'
import type { AuditChangeSearchFilters } from '../types'

export function useAuditChangeSearch(filters: AuditChangeSearchFilters) {
  const { activeOrganizationId } = useAuth()

  return useQuery({
    queryKey: queryKeys.auditChanges(activeOrganizationId ?? 'unknown-org', filters),
    queryFn: () => searchAuditChanges(filters),
  })
}
