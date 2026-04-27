import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listApprovals } from '../api/approvalsApi'

export function useApprovalsInbox(organizationId: string | null, statusFilter?: string) {
  return useQuery({
    queryKey: queryKeys.approvals(organizationId ?? '', statusFilter),
    enabled: Boolean(organizationId),
    queryFn: () =>
      listApprovals({ organization_id: organizationId ?? '', status: statusFilter }),
    refetchInterval: 3000,
  })
}
