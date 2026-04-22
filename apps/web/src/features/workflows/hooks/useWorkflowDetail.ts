import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getWorkflow } from '../api/workflowsApi'

export function useWorkflowDetail(workflowId: string | null) {
  return useQuery({
    queryKey: queryKeys.workflow(workflowId ?? 'missing'),
    enabled: Boolean(workflowId),
    queryFn: () => getWorkflow(workflowId ?? ''),
  })
}
