import React, { lazy, Suspense } from 'react';
import { createBrowserRouter } from 'react-router-dom';
import { Layout } from '../components/layout/Layout';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';

const LoginPage = lazy(() => import('../pages/LoginPage'));
const DashboardPage = lazy(() => import('../pages/DashboardPage'));
const UploadPage = lazy(() => import('../pages/UploadPage'));
const LeakageReviewPage = lazy(() => import('../pages/LeakageReviewPage'));
const LeakageDetailPage = lazy(() => import('../pages/LeakageDetailPage'));
const VendorsPage = lazy(() => import('../pages/VendorsPage'));
const VendorDetailPage = lazy(() => import('../pages/VendorDetailPage'));
const ContractsPage = lazy(() => import('../pages/ContractsPage'));
const ReportsPage = lazy(() => import('../pages/ReportsPage'));
const AdminPage = lazy(() => import('../pages/AdminPage'));
const NotificationsPage = lazy(() => import('../pages/NotificationsPage'));
const StructuringRunsPage = lazy(() => import('../pages/structuring/StructuringRunsPage'));
const NewStructuringRunPage = lazy(() => import('../pages/structuring/NewStructuringRunPage'));
const StructuringRunDetailPage = lazy(() => import('../pages/structuring/StructuringRunDetailPage'));
const ContractReviewPage = lazy(() => import('../pages/structuring/ContractReviewPage'));
const StructuringExportPage = lazy(() => import('../pages/structuring/StructuringExportPage'));
const IntegrityPage = lazy(() => import('../pages/integrity/IntegrityPage'));
const IntegrityDetailPage = lazy(() => import('../pages/integrity/IntegrityDetailPage'));
const RevalidationDashboardPage = lazy(() => import('../pages/revalidation/RevalidationDashboardPage'));
const SubjectsPage = lazy(() => import('../pages/revalidation/SubjectsPage'));
const SubjectDetailPage = lazy(() => import('../pages/revalidation/SubjectDetailPage'));
const AlertsPage = lazy(() => import('../pages/revalidation/AlertsPage'));

function SuspenseWrapper({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
          <LoadingSpinner size={40} />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: (
      <SuspenseWrapper>
        <LoginPage />
      </SuspenseWrapper>
    ),
  },
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        index: true,
        element: (
          <SuspenseWrapper>
            <DashboardPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'upload',
        element: (
          <SuspenseWrapper>
            <UploadPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'leakage',
        element: (
          <SuspenseWrapper>
            <LeakageReviewPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'leakage/:id',
        element: (
          <SuspenseWrapper>
            <LeakageDetailPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'vendors',
        element: (
          <SuspenseWrapper>
            <VendorsPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'vendors/:id',
        element: (
          <SuspenseWrapper>
            <VendorDetailPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'contracts',
        element: (
          <SuspenseWrapper>
            <ContractsPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'reports',
        element: (
          <SuspenseWrapper>
            <ReportsPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'admin',
        element: (
          <SuspenseWrapper>
            <AdminPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'notifications',
        element: (
          <SuspenseWrapper>
            <NotificationsPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'structuring',
        element: (
          <SuspenseWrapper>
            <StructuringRunsPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'structuring/new',
        element: (
          <SuspenseWrapper>
            <NewStructuringRunPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'structuring/:runId',
        element: (
          <SuspenseWrapper>
            <StructuringRunDetailPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'structuring/:runId/contract/:documentId',
        element: (
          <SuspenseWrapper>
            <ContractReviewPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'structuring/:runId/exports',
        element: (
          <SuspenseWrapper>
            <StructuringExportPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'integrity',
        element: (
          <SuspenseWrapper>
            <IntegrityPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'integrity/:documentId',
        element: (
          <SuspenseWrapper>
            <IntegrityDetailPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'revalidation',
        element: (
          <SuspenseWrapper>
            <RevalidationDashboardPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'revalidation/subjects',
        element: (
          <SuspenseWrapper>
            <SubjectsPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'revalidation/subjects/:subjectId',
        element: (
          <SuspenseWrapper>
            <SubjectDetailPage />
          </SuspenseWrapper>
        ),
      },
      {
        path: 'revalidation/alerts',
        element: (
          <SuspenseWrapper>
            <AlertsPage />
          </SuspenseWrapper>
        ),
      },
    ],
  },
]);
