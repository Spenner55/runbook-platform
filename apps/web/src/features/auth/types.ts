export interface UserMembership {
  id: string
  role: 'owner' | 'admin' | 'operator' | 'viewer'
  organization: {
    id: string
    name: string
    slug: string
  }
}

export interface CurrentUser {
  id: string
  email: string
  first_name: string
  last_name: string
  full_name: string
  is_staff: boolean
  created_at: string
  memberships: UserMembership[]
  active_organization_id: string | null
}

export interface LoginInput {
  email: string
  password: string
}

export interface LoginResponse {
  access: string
  user: CurrentUser
}

export interface RefreshResponse {
  access: string
}
