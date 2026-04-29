import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getCurrentUser } from '../api/authApi'
import { useAuth } from '../context/useAuth'

export function useCurrentUser() {
  const { isAuthenticated, user } = useAuth()

  return useQuery({
    queryKey: queryKeys.currentUser,
    queryFn: getCurrentUser,
    enabled: isAuthenticated,
    initialData: user ?? undefined,
    staleTime: 60_000,
  })
}
