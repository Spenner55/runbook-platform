import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './context/useAuth'

export function ProtectedRoute() {
  const location = useLocation()
  const { isAuthenticated, isInitializing } = useAuth()

  if (isInitializing) {
    return <p className="banner banner--info">Checking session...</p>
  }

  if (!isAuthenticated) {
    return <Navigate replace state={{ from: location }} to="/login" />
  }

  return <Outlet />
}
