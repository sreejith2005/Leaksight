import { apiGet, apiPost, apiPostFormData } from '../client';
import type {
  UploadResponse,
  TriggerRunResponse,
  RunStatusResponse,
  PaginatedResponse,
} from '../../types/api';

export function uploadDocument(file: File, docType: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('doc_type', docType);
  return apiPostFormData<UploadResponse>('/ingest/upload', formData);
}

export function triggerRun(documentIds: string[]): Promise<TriggerRunResponse> {
  return apiPost<TriggerRunResponse>('/ingest/trigger-run', { document_ids: documentIds });
}

export function listDocuments(params?: {
  page?: number;
  page_size?: number;
  doc_type?: string;
}): Promise<PaginatedResponse<UploadResponse>> {
  const searchParams = new URLSearchParams();
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.page_size) searchParams.set('page_size', String(params.page_size));
  if (params?.doc_type) searchParams.set('doc_type', params.doc_type);
  const qs = searchParams.toString();
  return apiGet<PaginatedResponse<UploadResponse>>(`/ingest/documents${qs ? `?${qs}` : ''}`);
}

export function getRunStatus(runId: string): Promise<RunStatusResponse> {
  return apiGet<RunStatusResponse>(`/ingest/runs/${runId}/status`);
}

export function listRuns(params?: {
  page?: number;
  page_size?: number;
  status?: string;
}): Promise<PaginatedResponse<RunStatusResponse>> {
  const searchParams = new URLSearchParams();
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.page_size) searchParams.set('page_size', String(params.page_size));
  if (params?.status) searchParams.set('status', params.status);
  const qs = searchParams.toString();
  return apiGet<PaginatedResponse<RunStatusResponse>>(`/ingest/runs${qs ? `?${qs}` : ''}`);
}
