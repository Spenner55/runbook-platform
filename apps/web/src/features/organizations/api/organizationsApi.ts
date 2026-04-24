import { apiRequest } from '../../../shared/api/client'
import type { CreateOrganizationInput, Organization } from '../types'

export function listOrganizations() {
  return apiRequest<Organization[]>('/api/v1/organizations/')
}

export function createOrganization(input: CreateOrganizationInput) {
  return apiRequest<Organization>('/api/v1/organizations/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
