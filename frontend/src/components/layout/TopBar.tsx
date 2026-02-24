import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { useQuery } from '@tanstack/react-query';
import { getNotifications } from '../../api/endpoints/notifications';
import { useNavigate } from 'react-router-dom';

export function TopBar() {
  const { currentUser, logout } = useAuth();
  const navigate = useNavigate();

  const { data: notifData } = useQuery({
    queryKey: ['notifications', { unread: true }],
    queryFn: () => getNotifications({ skip: 0, limit: 1, unread_only: true }),
    refetchInterval: 30_000,
    enabled: !!currentUser,
  });

  const unreadCount = notifData?.unread_count ?? 0;

  return (
    <header
      style={{
        height: 56,
        backgroundColor: 'var(--color-prussian-blue)',
        borderBottom: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        padding: '0 var(--space-6)',
        gap: 'var(--space-4)',
        position: 'fixed',
        top: 0,
        left: 240,
        right: 0,
        zIndex: 99,
      }}
    >
      {/* Notification bell */}
      <button
        onClick={() => navigate('/notifications')}
        style={{
          position: 'relative',
          background: 'none',
          border: 'none',
          color: 'var(--color-grey)',
          cursor: 'pointer',
          padding: 'var(--space-2)',
          borderRadius: 'var(--radius-sm)',
          transition: 'color 0.15s',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.color = 'var(--color-orange)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.color = 'var(--color-grey)';
        }}
        aria-label="Notifications"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: 2,
              right: 2,
              minWidth: 16,
              height: 16,
              backgroundColor: 'var(--color-error)',
              color: 'var(--color-white)',
              fontSize: '10px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: '50%',
              padding: '0 4px',
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* User email */}
      {currentUser && (
        <span
          style={{
            fontSize: '13px',
            color: 'var(--color-grey)',
          }}
        >
          {currentUser.email}
        </span>
      )}

      {/* Logout */}
      <button
        onClick={logout}
        style={{
          background: 'none',
          border: '1px solid var(--color-border)',
          color: 'var(--color-grey)',
          cursor: 'pointer',
          padding: 'var(--space-1) var(--space-3)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '13px',
          transition: 'all 0.15s',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--color-orange)';
          (e.currentTarget as HTMLElement).style.color = 'var(--color-orange)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--color-border)';
          (e.currentTarget as HTMLElement).style.color = 'var(--color-grey)';
        }}
      >
        Logout
      </button>
    </header>
  );
}
