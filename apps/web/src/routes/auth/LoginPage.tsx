import { type FormEvent, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { getApiErrorMessage } from '../../shared/api/client'
import { useAuth } from '../../features/auth/context/useAuth'

interface LocationState {
  from?: {
    pathname?: string
    search?: string
  }
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { isAuthenticated, isInitializing, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const state = location.state as LocationState | null
  const from = `${state?.from?.pathname ?? '/organizations'}${state?.from?.search ?? ''}`

  if (!isInitializing && isAuthenticated) {
    return <Navigate replace to={from} />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login({ email, password })
      navigate(from, { replace: true })
    } catch (loginError) {
      setError(loginError)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="panel auth-panel">
        <div className="panel__header">
          <p className="eyebrow">Runbook Platform</p>
          <h1>Sign in</h1>
        </div>

        <form className="stack-md" onSubmit={handleSubmit}>
          <label className="field">
            <span className="field__label">Email</span>
            <input
              autoComplete="email"
              className="input"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>

          <label className="field">
            <span className="field__label">Password</span>
            <input
              autoComplete="current-password"
              className="input"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>

          {error ? <p className="banner banner--error">{getApiErrorMessage(error)}</p> : null}

          <button className="button" disabled={isSubmitting || isInitializing} type="submit">
            {isSubmitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  )
}
