import { useNavigate } from 'react-router-dom'

import { getApiErrorMessage } from '../../shared/api/client'
import { useAuth } from './context/useAuth'
import { useCurrentUser } from './hooks/useCurrentUser'

export function AuthStatus() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const currentUserQuery = useCurrentUser()

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="auth-status">
      <div>
        <p className="eyebrow">Signed in</p>
        <p className="auth-status__email">
          {currentUserQuery.data?.email ??
            (currentUserQuery.isLoading ? 'Loading...' : 'Unknown user')}
        </p>
      </div>
      {currentUserQuery.error ? (
        <p className="field__error">{getApiErrorMessage(currentUserQuery.error)}</p>
      ) : null}
      <button className="button button--secondary" onClick={handleLogout} type="button">
        Log out
      </button>
    </div>
  )
}
