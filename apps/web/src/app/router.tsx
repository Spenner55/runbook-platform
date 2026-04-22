import { createBrowserRouter, Navigate } from 'react-router-dom'

import { AppLayout } from './AppLayout'
import { ExecutionDetailPage } from '../routes/executions/ExecutionDetailPage'
import { OrganizationsPage } from '../routes/organizations/OrganizationsPage'
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
    ],
  },
])
