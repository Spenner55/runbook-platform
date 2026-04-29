import type { PropsWithChildren } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { useQueryClient } from '@tanstack/react-query'

import { buildApiUrl } from '../../../shared/api/env'
import { queryKeys } from '../../../shared/lib/queryKeys'
import { getCurrentUser, login as loginRequest, logout as logoutRequest } from '../api/authApi'
import {
  getAccessToken,
  setAccessToken,
  setActiveOrganizationId,
  subscribeToAccessToken,
} from '../authTokenStore'
import type { CurrentUser, LoginInput } from '../types'
import { AuthContext } from './authContext'

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient()
  const [accessToken, setAccessTokenState] = useState(getAccessToken)
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [activeOrganizationIdState, setActiveOrganizationIdState] = useState<string | null>(null)
  const [isInitializing, setIsInitializing] = useState(true)

  useEffect(() => subscribeToAccessToken(setAccessTokenState), [])

  const clearAuthState = useCallback(() => {
    setAccessToken(null)
    setActiveOrganizationId(null)
    setActiveOrganizationIdState(null)
    setUser(null)
    queryClient.removeQueries()
  }, [queryClient])

  const applyCurrentUser = useCallback(
    (currentUser: CurrentUser) => {
      const activeOrgId =
        currentUser.active_organization_id ?? currentUser.memberships[0]?.organization.id ?? null
      setUser(currentUser)
      setActiveOrganizationId(activeOrgId)
      setActiveOrganizationIdState(activeOrgId)
      queryClient.setQueryData(queryKeys.currentUser, currentUser)
    },
    [queryClient]
  )

  const reloadCurrentUser = useCallback(async () => {
    const currentUser = await queryClient.fetchQuery({
      queryKey: queryKeys.currentUser,
      queryFn: getCurrentUser,
      staleTime: 60_000,
    })
    applyCurrentUser(currentUser)
  }, [applyCurrentUser, queryClient])

  useEffect(() => {
    let ignore = false

    async function bootstrap() {
      try {
        const response = await fetch(buildApiUrl('/api/v1/auth/refresh/'), {
          method: 'POST',
          credentials: 'include',
          headers: {
            Accept: 'application/json',
          },
        })

        if (!response.ok) {
          return
        }

        const data = (await response.json()) as { access?: unknown }
        if (typeof data.access !== 'string') {
          return
        }

        setAccessToken(data.access)
        const currentUser = await getCurrentUser()
        if (!ignore) {
          applyCurrentUser(currentUser)
        }
      } catch {
        setAccessToken(null)
      } finally {
        if (!ignore) {
          setIsInitializing(false)
        }
      }
    }

    void bootstrap()

    return () => {
      ignore = true
    }
  }, [applyCurrentUser, queryClient])

  useEffect(() => {
    function handleUnauthorized() {
      clearAuthState()
    }

    window.addEventListener('runbook-platform:unauthorized', handleUnauthorized)
    return () => {
      window.removeEventListener('runbook-platform:unauthorized', handleUnauthorized)
    }
  }, [clearAuthState])

  const login = useCallback(
    async (input: LoginInput) => {
      const response = await loginRequest(input)
      setAccessToken(response.access)
      applyCurrentUser(response.user)
    },
    [applyCurrentUser]
  )

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      clearAuthState()
    }
  }, [clearAuthState])

  const value = useMemo(
    () => ({
      accessToken,
      user,
      activeOrganizationId: activeOrganizationIdState,
      isAuthenticated: Boolean(accessToken),
      isInitializing,
      login,
      logout,
      reloadCurrentUser,
    }),
    [accessToken, activeOrganizationIdState, isInitializing, login, logout, reloadCurrentUser, user]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
