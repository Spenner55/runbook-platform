export const queryKeys = {
  organizations: ['organizations'] as const,
  runbooks: (organizationId?: string) => ['runbooks', organizationId ?? 'all'] as const,
  runbook: (runbookId: string) => ['runbook', runbookId] as const,
  workflow: (workflowId: string) => ['workflow', workflowId] as const,
  execution: (executionId: string) => ['execution', executionId] as const,
  approvals: (organizationId: string, status?: string) =>
    ['approvals', organizationId, status ?? 'pending'] as const,
}
