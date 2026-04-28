import { apiRequest } from '../../../shared/api/client'
import type {
  CreateIntegrationInput,
  IntegrationConnection,
  IntegrationDeliveryAttempt,
} from '../types'

function withOrganization(path: string, organizationId: string) {
  const query = new URLSearchParams({ organization_id: organizationId })
  return `${path}?${query}`
}

export function listIntegrations(organizationId: string) {
  return apiRequest<IntegrationConnection[]>(
    withOrganization('/api/v1/integrations/', organizationId)
  )
}

export function getIntegration(integrationId: string, organizationId: string) {
  return apiRequest<IntegrationConnection>(
    withOrganization(`/api/v1/integrations/${integrationId}/`, organizationId)
  )
}

export function createIntegration(input: CreateIntegrationInput) {
  return apiRequest<IntegrationConnection>('/api/v1/integrations/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function deactivateIntegration(integrationId: string, organizationId: string) {
  return apiRequest<IntegrationConnection>(
    withOrganization(`/api/v1/integrations/${integrationId}/deactivate/`, organizationId),
    {
      method: 'POST',
      body: JSON.stringify({}),
    }
  )
}

export function listIntegrationDeliveryAttempts(integrationId: string, organizationId: string) {
  return apiRequest<{ results: IntegrationDeliveryAttempt[] }>(
    withOrganization(`/api/v1/integrations/${integrationId}/delivery-attempts/`, organizationId)
  )
}
