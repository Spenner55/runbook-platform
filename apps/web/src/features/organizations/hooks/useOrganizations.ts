import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listOrganizations } from '../api/organizationsApi'

export function useOrganizations() {
  return useQuery({
    queryKey: queryKeys.organizations,
    queryFn: listOrganizations,
  })
}
