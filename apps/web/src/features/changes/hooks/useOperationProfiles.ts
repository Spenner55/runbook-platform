import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listOperationProfiles } from '../api/changesApi'

export function useOperationProfiles() {
  return useQuery({
    queryKey: queryKeys.operationProfiles,
    queryFn: listOperationProfiles,
  })
}
