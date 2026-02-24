import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from '../api/endpoints/notifications';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { useToast } from '../context/ToastContext';

export default function NotificationsPage() {
  const { addToast } = useToast();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['notifications', { skip: 0, limit: 50 }],
    queryFn: () => getNotifications({ skip: 0, limit: 50 }),
  });

  const markReadMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const markAllMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      addToast('success', 'All notifications marked as read');
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  const notifications = data?.data ?? [];
  const unreadCount = data?.unread_count ?? 0;

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)' }}>
          Notifications {unreadCount > 0 && (
            <span style={{ fontSize: '14px', color: 'var(--color-orange)', fontWeight: 400 }}>
              ({unreadCount} unread)
            </span>
          )}
        </h1>
        {unreadCount > 0 && (
          <Button variant="secondary" onClick={() => markAllMutation.mutate()} loading={markAllMutation.isPending}>
            Mark All Read
          </Button>
        )}
      </div>

      {notifications.length === 0 ? (
        <EmptyState title="No notifications" description="You're all caught up." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {notifications.map((notif) => (
            <Card
              key={notif.id}
              style={{
                opacity: notif.is_read ? 0.6 : 1,
                borderLeft: notif.is_read ? undefined : '3px solid var(--color-orange)',
                cursor: notif.is_read ? 'default' : 'pointer',
              }}
              onClick={() => {
                if (!notif.is_read) markReadMutation.mutate(notif.id);
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <p style={{ color: 'var(--color-grey)', fontSize: '14px', lineHeight: 1.5 }}>
                    {notif.message}
                  </p>
                  <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
                    <span style={{ fontSize: '11px', color: 'var(--color-muted)' }}>
                      {notif.notification_type.replace(/_/g, ' ')}
                    </span>
                    <span style={{ fontSize: '11px', color: 'var(--color-muted)' }}>
                      {notif.created_at ? new Date(notif.created_at).toLocaleString() : ''}
                    </span>
                  </div>
                </div>
                {!notif.is_read && (
                  <div
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      backgroundColor: 'var(--color-orange)',
                      flexShrink: 0,
                      marginTop: 6,
                    }}
                  />
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
