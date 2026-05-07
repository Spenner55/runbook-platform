import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createEvidenceExport } from '../api/evidenceApi'
import type { CreateEvidenceExportInput } from '../types'

export function useCreateEvidenceExport(bundleId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateEvidenceExportInput) => createEvidenceExport(bundleId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.evidenceExports(bundleId) })
    },
  })
}
