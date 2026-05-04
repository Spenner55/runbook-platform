import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listChanges } from '../api/changesApi'

export function useChangesList() {
  return useQuery({
    queryKey: queryKeys.changes,
    queryFn: listChanges,
  })
}
