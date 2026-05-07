import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { sealEvidenceBundle } from '../api/evidenceApi'

export function useSealEvidenceBundle(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (bundleId: string) => sealEvidenceBundle(bundleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.latestEvidenceBundle(changeId) })
    },
  })
}
