export type AuditActorType = 'user' | 'runner' | 'system' | 'api_client' | 'unknown'

export interface AuditEvent {
  id: string
  actor_type: AuditActorType
  actor_id: string
  actor_label: string
  event_type: string
  object_type: string
  object_id: string
  organization_id: string
  metadata: Record<string, unknown>
  occurred_at: string
}

export interface AuditEventListResponse {
  count: number
  next: string | null
  previous: string | null
  results: AuditEvent[]
}
