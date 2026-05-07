import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createLegalHold } from '../api/evidenceApi'
import type { CreateLegalHoldInput } from '../types'

export function useCreateLegalHold(bundleId: string, changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateLegalHoldInput) => createLegalHold(bundleId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.latestEvidenceBundle(changeId) })
    },
  })
}
