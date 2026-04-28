import { createBrowserRouter, Navigate } from 'react-router-dom'

import { AppLayout } from './AppLayout'
import { ApprovalsInboxPage } from '../routes/approvals/ApprovalsInboxPage'
import { ExecutionDetailPage } from '../routes/executions/ExecutionDetailPage'
import { IntegrationDetailPage } from '../routes/integrations/IntegrationDetailPage'
import { IntegrationsPage } from '../routes/integrations/IntegrationsPage'
import { OrganizationsPage } from '../routes/organizations/OrganizationsPage'
import { PoliciesPage } from '../routes/policies/PoliciesPage'
import { PolicyDetailPage } from '../routes/policies/PolicyDetailPage'
import { RunbooksPage } from '../routes/runbooks/RunbooksPage'
import { WorkflowCreatePage } from '../routes/workflows/WorkflowCreatePage'
import { WorkflowDetailPage } from '../routes/workflows/WorkflowDetailPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate replace to="/organizations" /> },
      { path: 'organizations', element: <OrganizationsPage /> },
      { path: 'runbooks', element: <RunbooksPage /> },
      { path: 'workflows/new', element: <WorkflowCreatePage /> },
      { path: 'workflows/:workflowId', element: <WorkflowDetailPage /> },
      { path: 'executions/:executionId', element: <ExecutionDetailPage /> },
      { path: 'approvals', element: <ApprovalsInboxPage /> },
      { path: 'policies', element: <PoliciesPage /> },
      { path: 'policies/:policyId', element: <PolicyDetailPage /> },
      { path: 'integrations', element: <IntegrationsPage /> },
      { path: 'integrations/:integrationId', element: <IntegrationDetailPage /> },
    ],
  },
])
