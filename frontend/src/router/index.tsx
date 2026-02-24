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
    ],
  },
]);
