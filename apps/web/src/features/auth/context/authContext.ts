import { createContext } from 'react'

import type { CurrentUser, LoginInput } from '../types'

export interface AuthContextValue {
  accessToken: string | null
  user: CurrentUser | null
  activeOrganizationId: string | null
  isAuthenticated: boolean
  isInitializing: boolean
  login: (input: LoginInput) => Promise<void>
  logout: () => Promise<void>
  reloadCurrentUser: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
