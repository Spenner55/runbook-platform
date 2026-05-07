import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { submitRetroReview } from '../api/changesApi'
import type { SubmitRetroReviewInput } from '../types'

export function useSubmitRetroReview(changeId: string, reviewId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: SubmitRetroReviewInput) => submitRetroReview(changeId, reviewId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.changeRetroReviews(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.change(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.retroReviewInbox })
    },
  })
}
