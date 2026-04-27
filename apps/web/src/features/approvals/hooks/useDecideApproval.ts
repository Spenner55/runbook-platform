import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { decideApproval } from '../api/approvalsApi'
import type { DecideApprovalInput } from '../types'

export function useDecideApproval(organizationId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      approvalId,
      input,
    }: {
      approvalId: string
      input: DecideApprovalInput
    }) => decideApproval(approvalId, input),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.approvals(organizationId ?? '', undefined) })
      queryClient.invalidateQueries({ queryKey: queryKeys.approvals(organizationId ?? '', 'all') })
      queryClient.invalidateQueries({ queryKey: queryKeys.approvals(organizationId ?? '', 'pending') })
      queryClient.invalidateQueries({ queryKey: queryKeys.execution(data.execution_id) })
    },
  })
}
