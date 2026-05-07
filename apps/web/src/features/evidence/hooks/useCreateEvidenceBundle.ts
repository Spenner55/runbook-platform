import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createEvidenceBundle } from '../api/evidenceApi'
import type { CreateEvidenceBundleInput } from '../types'

export function useCreateEvidenceBundle(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateEvidenceBundleInput) => createEvidenceBundle(changeId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.latestEvidenceBundle(changeId) })
    },
  })
}
