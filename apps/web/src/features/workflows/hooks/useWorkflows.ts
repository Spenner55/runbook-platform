import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listWorkflows } from '../api/workflowsApi'

export function useWorkflows() {
  return useQuery({
    queryKey: queryKeys.workflows,
    queryFn: listWorkflows,
  })
}
