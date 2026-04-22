export interface Runbook {
  id: string
  title: string
  slug: string
  status: string
  organization_id: string
  created_at: string
}

export interface RunbookDetail extends Runbook {
  raw_content: string
  updated_at: string
}

export interface CreateRunbookInput {
  organization_id: string
  title: string
  slug: string
  raw_content: string
}
