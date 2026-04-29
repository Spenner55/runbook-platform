import { createBrowserRouter, Navigate } from 'react-router-dom'

import { AppLayout } from './AppLayout'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { ApprovalsInboxPage } from '../routes/approvals/ApprovalsInboxPage'
import { LoginPage } from '../routes/auth/LoginPage'
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
          { path: 'settings', element: <SettingsPage /> },
        ],
      },
    ],
  },
])
