export type IntegrationType = 'slack_webhook' | 'generic_webhook'
export type IntegrationLastDeliveryStatus = 'success' | 'failed' | ''

export interface IntegrationConnection {
  id: string
  organization_id: string
  type: IntegrationType
  name: string
  config: Record<string, unknown>
  event_types: string[]
  is_active: boolean
  credentials_configured: boolean
  last_delivery_at: string | null
  last_delivery_status: IntegrationLastDeliveryStatus
  created_at: string
  updated_at: string
}

export interface IntegrationDeliveryAttempt {
  id: string
  integration_id: string
  organization_id: string
  event_type: string
  payload_preview: Record<string, unknown>
  http_status: number | null
  success: boolean
  error_detail: string
  latency_ms: number | null
  attempted_at: string
  created_at: string
  updated_at: string
}

export interface CreateIntegrationInput {
  organization_id: string
  type: IntegrationType
  name: string
  credentials: {
    url: string
  }
  config?: Record<string, unknown>
  event_types?: string[]
}
