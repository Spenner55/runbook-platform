export const queryKeys = {
  currentUser: ['auth', 'current-user'] as const,
  organizations: ['organizations'] as const,
  runbooks: (organizationId?: string) => ['runbooks', organizationId ?? 'all'] as const,
  runbook: (runbookId: string) => ['runbook', runbookId] as const,
  runbookWorkflows: (runbookId: string) => ['runbook-workflows', runbookId] as const,
  workflows: ['workflows'] as const,
  workflow: (workflowId: string) => ['workflow', workflowId] as const,
  executions: (status?: string) => ['executions', status ?? 'all'] as const,
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
  operationProfiles: ['operation-profiles'] as const,
  changes: ['changes'] as const,
  change: (changeId: string) => ['change', changeId] as const,
  changePreflight: (changeId: string) => ['change', changeId, 'preflight'] as const,
  changeVerificationPlan: (changeId: string) => ['change', changeId, 'verification-plan'] as const,
  freezeRules: (organizationId: string, isActive?: string) =>
    ['freeze-rules', organizationId, isActive ?? 'all'] as const,
  changeExceptions: (changeId: string) => ['change', changeId, 'exceptions'] as const,
  changeRetroReviews: (changeId: string) => ['change', changeId, 'retro-reviews'] as const,
  retroReviewInbox: ['retro-review-inbox'] as const,
  latestEvidenceBundle: (changeId: string) => ['evidence-bundle', 'latest', changeId] as const,
  evidenceExports: (bundleId: string) => ['evidence-exports', bundleId] as const,
}
