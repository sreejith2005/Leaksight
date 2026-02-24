import { apiGet, apiPut, apiPost } from '../client';
import type { NotificationsResponse } from '../../types/api';

export function getNotifications(params?: {
  unread_only?: boolean;
  skip?: number;
  limit?: number;
}): Promise<NotificationsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.unread_only) searchParams.set('unread_only', 'true');
  if (params?.skip !== undefined) searchParams.set('skip', String(params.skip));
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
  const qs = searchParams.toString();
  return apiGet<NotificationsResponse>(`/notifications${qs ? `?${qs}` : ''}`);
}

export function markNotificationRead(id: string): Promise<{ id: string; read_at: string | null }> {
  return apiPut<{ id: string; read_at: string | null }>(`/notifications/${id}/read`);
}

export function markAllNotificationsRead(): Promise<{ marked_read_count: number }> {
  return apiPost<{ marked_read_count: number }>('/notifications/read-all');
}
