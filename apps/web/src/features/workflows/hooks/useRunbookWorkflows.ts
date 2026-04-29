import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listWorkflows } from '../api/workflowsApi'

// NOTE: GET /api/v1/workflows/ does not accept a runbook_id query parameter.
// We fetch all org-scoped workflows and filter client-side. Acceptable for
// demo/testing data volumes; add a backend filter in a future phase if needed.
export function useRunbookWorkflows(runbookId: string | null) {
  return useQuery({
    queryKey: queryKeys.runbookWorkflows(runbookId ?? 'missing'),
    enabled: Boolean(runbookId),
    queryFn: async () => {
      const workflows = await listWorkflows()
      return workflows.filter((w) => w.runbook_id === runbookId)
    },
  })
}
