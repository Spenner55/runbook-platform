import { apiRequest } from '../../../shared/api/client'
import type { CurrentUser, LoginInput, LoginResponse } from '../types'

export function login(input: LoginInput) {
  return apiRequest<LoginResponse>('/api/v1/auth/login/', {
    method: 'POST',
    body: JSON.stringify(input),
    skipAuthRefresh: true,
  })
}

export function getCurrentUser() {
  return apiRequest<CurrentUser>('/api/v1/auth/me/')
}

export function logout() {
  return apiRequest<void>('/api/v1/auth/logout/', {
    method: 'POST',
    skipAuthRefresh: true,
  })
}
