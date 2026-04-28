import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createIntegration } from '../api/integrationsApi'
import type { CreateIntegrationInput } from '../types'

export function useCreateIntegration(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateIntegrationInput) => createIntegration(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.integrations(organizationId) })
    },
  })
}
