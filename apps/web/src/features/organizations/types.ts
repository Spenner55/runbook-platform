export interface Organization {
  id: string
  name: string
  slug: string
  created_at: string
  updated_at: string
}

export interface CreateOrganizationInput {
  name: string
  slug: string
}
