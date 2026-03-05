import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { useAuth } from '../../context/AuthContext';

export function Layout() {
  const { currentUser } = useAuth();

  if (!currentUser) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="noise-overlay" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar />
      <div
        style={{
          flex: 1,
          marginLeft: 'var(--sidebar-width)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <TopBar />
        <main
          style={{
            flex: 1,
            marginTop: 'var(--topbar-height)',
            padding: 'var(--content-padding)',
            backgroundColor: 'var(--bg-base)',
            minHeight: 'calc(100vh - var(--topbar-height))',
          }}
        >
          <div style={{ maxWidth: 'var(--content-max-width)', margin: '0 auto', width: '100%' }}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
