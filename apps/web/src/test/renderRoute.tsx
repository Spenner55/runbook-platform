import type { ReactElement } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { AuthContext } from '../features/auth/context/authContext'
import type { AuthContextValue } from '../features/auth/context/authContext'

const DEFAULT_AUTH: AuthContextValue = {
  accessToken: 'test-token',
  user: null,
  activeOrganizationId: null,
  isAuthenticated: true,
  isInitializing: false,
  login: async () => {},
  logout: async () => {},
  reloadCurrentUser: async () => {},
}

export function renderRoute(
  element: ReactElement,
  {
    path,
    route,
    auth,
  }: {
    path: string
    route: string
    auth?: Partial<AuthContextValue>
  }
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  const authValue: AuthContextValue = { ...DEFAULT_AUTH, ...auth }

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route element={element} path={path} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}
