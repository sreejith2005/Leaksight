import { apiGet, apiPost } from '../client';
import type {
  PaginatedResponse,
  LeakageRecord,
  LeakageRecordDetail,
  ReviewRequest,
  ReviewResponse,
  LeakageSummary,
} from '../../types/api';

export interface LeakageListParams {
  page?: number;
  page_size?: number;
  status?: string;
  leakage_type?: string;
  vendor_id?: string;
  run_id?: string;
  min_amount?: number;
  max_amount?: number;
  min_confidence?: number;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_dir?: string;
}

export function getLeakageRecords(params?: LeakageListParams): Promise<PaginatedResponse<LeakageRecord>> {
  const searchParams = new URLSearchParams();
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.page_size) searchParams.set('page_size', String(params.page_size));
  if (params?.status) searchParams.set('status', params.status);
  if (params?.leakage_type) searchParams.set('leakage_type', params.leakage_type);
  if (params?.vendor_id) searchParams.set('vendor_id', params.vendor_id);
  if (params?.run_id) searchParams.set('run_id', params.run_id);
  if (params?.min_amount !== undefined) searchParams.set('min_amount', String(params.min_amount));
  if (params?.max_amount !== undefined) searchParams.set('max_amount', String(params.max_amount));
  if (params?.min_confidence !== undefined) searchParams.set('min_confidence', String(params.min_confidence));
  if (params?.date_from) searchParams.set('date_from', params.date_from);
  if (params?.date_to) searchParams.set('date_to', params.date_to);
  if (params?.sort_by) searchParams.set('sort_by', params.sort_by);
  if (params?.sort_dir) searchParams.set('sort_dir', params.sort_dir);
  const qs = searchParams.toString();
  return apiGet<PaginatedResponse<LeakageRecord>>(`/leakage/records${qs ? `?${qs}` : ''}`);
}

export function getLeakageRecord(id: string): Promise<LeakageRecordDetail> {
  return apiGet<LeakageRecordDetail>(`/leakage/records/${id}`);
}

export function acceptRecord(id: string, notes?: string): Promise<ReviewResponse> {
  const body: ReviewRequest = notes ? { notes } : {};
  return apiPost<ReviewResponse>(`/leakage/records/${id}/accept`, body);
}

export function rejectRecord(id: string, notes: string): Promise<ReviewResponse> {
  return apiPost<ReviewResponse>(`/leakage/records/${id}/reject`, { notes });
}

export function getLeakageSummary(runId?: string, status?: string): Promise<LeakageSummary> {
  const searchParams = new URLSearchParams();
  if (runId) searchParams.set('run_id', runId);
  if (status) searchParams.set('status', status);
  const qs = searchParams.toString();
  return apiGet<LeakageSummary>(`/leakage/summary${qs ? `?${qs}` : ''}`);
}
