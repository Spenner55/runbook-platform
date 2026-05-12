import { createBrowserRouter, Navigate } from 'react-router-dom'

import { AppLayout } from './AppLayout'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { ApprovalsInboxPage } from '../routes/approvals/ApprovalsInboxPage'
import { AuditChangeDetailPage } from '../routes/auditor/AuditChangeDetailPage'
import { AuditorAccessAdminPage } from '../routes/auditor/AuditorAccessAdminPage'
import { AuditorSearchPage } from '../routes/auditor/AuditorSearchPage'
import { LoginPage } from '../routes/auth/LoginPage'
import { ChangeCreatePage } from '../routes/changes/ChangeCreatePage'
import { ChangeDetailPage } from '../routes/changes/ChangeDetailPage'
import { ChangeEmergencyCreatePage } from '../routes/changes/ChangeEmergencyCreatePage'
import { ChangesPage } from '../routes/changes/ChangesPage'
import { RetroReviewInboxPage } from '../routes/changes/RetroReviewInboxPage'
import { FreezeRulesPage } from '../routes/freeze-rules/FreezeRulesPage'
import { ExecutionDetailPage } from '../routes/executions/ExecutionDetailPage'
import { ExecutionsPage } from '../routes/executions/ExecutionsPage'
import { IntegrationDetailPage } from '../routes/integrations/IntegrationDetailPage'
import { IntegrationsPage } from '../routes/integrations/IntegrationsPage'
import { OrganizationsPage } from '../routes/organizations/OrganizationsPage'
import { PoliciesPage } from '../routes/policies/PoliciesPage'
import { PolicyDetailPage } from '../routes/policies/PolicyDetailPage'
import { RunbookDetailPage } from '../routes/runbooks/RunbookDetailPage'
import { RunbooksPage } from '../routes/runbooks/RunbooksPage'
import { SettingsPage } from '../routes/settings/SettingsPage'
import { WorkflowCreatePage } from '../routes/workflows/WorkflowCreatePage'
import { WorkflowDetailPage } from '../routes/workflows/WorkflowDetailPage'
import { WorkflowReviewPage } from '../routes/workflows/WorkflowReviewPage'
import { WorkflowsPage } from '../routes/workflows/WorkflowsPage'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <Navigate replace to="/runbooks" /> },
          { path: 'organizations', element: <OrganizationsPage /> },
          { path: 'runbooks', element: <RunbooksPage /> },
          { path: 'runbooks/:runbookId', element: <RunbookDetailPage /> },
          { path: 'workflows', element: <WorkflowsPage /> },
          { path: 'workflows/new', element: <WorkflowCreatePage /> },
          { path: 'workflows/:workflowId', element: <WorkflowDetailPage /> },
          { path: 'workflows/:workflowId/review', element: <WorkflowReviewPage /> },
          { path: 'executions', element: <ExecutionsPage /> },
          { path: 'executions/:executionId', element: <ExecutionDetailPage /> },
          { path: 'approvals', element: <ApprovalsInboxPage /> },
          { path: 'policies', element: <PoliciesPage /> },
          { path: 'policies/:policyId', element: <PolicyDetailPage /> },
          { path: 'integrations', element: <IntegrationsPage /> },
          { path: 'integrations/:integrationId', element: <IntegrationDetailPage /> },
          { path: 'changes', element: <ChangesPage /> },
          { path: 'changes/new', element: <ChangeCreatePage /> },
          { path: 'changes/new/emergency', element: <ChangeEmergencyCreatePage /> },
          { path: 'changes/:changeId', element: <ChangeDetailPage /> },
          { path: 'audit/changes', element: <AuditorSearchPage /> },
          { path: 'audit/changes/:changeId', element: <AuditChangeDetailPage /> },
          { path: 'audit/access', element: <AuditorAccessAdminPage /> },
          { path: 'retro-reviews', element: <RetroReviewInboxPage /> },
          { path: 'freeze-rules', element: <FreezeRulesPage /> },
          { path: 'settings', element: <SettingsPage /> },
        ],
      },
    ],
  },
])
