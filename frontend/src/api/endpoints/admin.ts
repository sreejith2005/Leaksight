import { apiGet, apiPost, apiPut } from '../client';
import type {
  PaginatedResponse,
  FxRate,
  FxRateUploadRequest,
  FxRateUploadResponse,
  TenantSettings,
  TenantSettingsUpdate,
} from '../../types/api';

export function uploadFxRates(data: FxRateUploadRequest): Promise<FxRateUploadResponse> {
  return apiPost<FxRateUploadResponse>('/admin/fx-rates/upload', data);
}

export function listFxRates(params?: {
  from_currency?: string;
  to_currency?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<FxRate>> {
  const searchParams = new URLSearchParams();
  if (params?.from_currency) searchParams.set('from_currency', params.from_currency);
  if (params?.to_currency) searchParams.set('to_currency', params.to_currency);
  if (params?.date_from) searchParams.set('date_from', params.date_from);
  if (params?.date_to) searchParams.set('date_to', params.date_to);
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.page_size) searchParams.set('page_size', String(params.page_size));
  const qs = searchParams.toString();
  return apiGet<PaginatedResponse<FxRate>>(`/admin/fx-rates${qs ? `?${qs}` : ''}`);
}

export function getTenantSettings(): Promise<TenantSettings> {
  return apiGet<TenantSettings>('/admin/tenant-settings');
}

export function updateTenantSettings(data: TenantSettingsUpdate): Promise<TenantSettings> {
  return apiPut<TenantSettings>('/admin/tenant-settings', data);
}
