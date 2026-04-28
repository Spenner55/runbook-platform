export const queryKeys = {
  organizations: ['organizations'] as const,
  runbooks: (organizationId?: string) => ['runbooks', organizationId ?? 'all'] as const,
  runbook: (runbookId: string) => ['runbook', runbookId] as const,
  workflow: (workflowId: string) => ['workflow', workflowId] as const,
  execution: (executionId: string) => ['execution', executionId] as const,
  approvals: (organizationId: string, status?: string) =>
    ['approvals', organizationId, status ?? 'pending'] as const,
  policies: (organizationId: string, isActive?: string) =>
    ['policies', organizationId, isActive ?? 'true'] as const,
  policy: (policyId: string, organizationId?: string) =>
    ['policy', policyId, organizationId ?? 'unknown-org'] as const,
  policyEvaluations: (executionId: string) => ['policy-evaluations', executionId] as const,
  auditTrail: (organizationId: string, objectType: string, objectId: string) =>
    ['audit', organizationId, objectType, objectId] as const,
  executionAuditTrail: (executionId: string) => ['execution', executionId, 'audit'] as const,
  executionArtifacts: (organizationId: string, executionId: string) =>
    ['organization', organizationId, 'execution', executionId, 'artifacts'] as const,
  artifact: (artifactId: string) => ['artifact', artifactId] as const,
  integrations: (organizationId: string) => ['integrations', organizationId] as const,
  integration: (integrationId: string, organizationId: string) =>
    ['integration', integrationId, organizationId] as const,
  integrationDelivery: (integrationId: string, organizationId: string) =>
    ['integration', integrationId, organizationId, 'delivery-attempts'] as const,
}
