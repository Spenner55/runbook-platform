let accessToken: string | null = null
let activeOrganizationId: string | null = null

type Listener = (token: string | null) => void

const listeners = new Set<Listener>()

export function getAccessToken() {
  return accessToken
}

export function setAccessToken(token: string | null) {
  accessToken = token
  listeners.forEach((listener) => listener(accessToken))
}

export function subscribeToAccessToken(listener: Listener) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getActiveOrganizationId() {
  return activeOrganizationId
}

export function setActiveOrganizationId(organizationId: string | null) {
  activeOrganizationId = organizationId
}
