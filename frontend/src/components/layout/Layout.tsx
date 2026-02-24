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
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar />
      <div
        style={{
          flex: 1,
          marginLeft: 240,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <TopBar />
        <main
          style={{
            flex: 1,
            marginTop: 56,
            padding: 'var(--space-6)',
            backgroundColor: 'var(--color-black)',
            minHeight: 'calc(100vh - 56px)',
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
