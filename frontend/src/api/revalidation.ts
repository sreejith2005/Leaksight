import { apiGet, apiPost, apiPut } from './client';

export interface SubjectCreate {
  subject_type: 'EMPLOYEE' | 'VENDOR';
  name: string;
  identifier: string;
  department?: string | null;
  email?: string | null;
}

export interface ComplianceSummary {
  total_required: number;
  uploaded: number;
  expired: number;
  expiring_soon: number;
  missing: number;
}

export interface SubjectResponse {
  id: string;
  tenant_id: string;
  subject_type: 'EMPLOYEE' | 'VENDOR';
  name: string;
  identifier: string;
  department: string | null;
  email: string | null;
  is_active: boolean;
  created_at: string;
  compliance_summary: ComplianceSummary | null;
}

export interface DocCatalogResponse {
  id: string;
  subject_type: 'EMPLOYEE' | 'VENDOR';
  category: string;
  display_name: string;
  is_required: boolean;
  has_expiry: boolean;
  alert_days_before: number;
}

export interface RevalidationDocCreate {
  subject_id: string;
  category: string;
  display_name: string;
  has_expiry?: boolean;
  alert_days_before?: number;
  notes?: string | null;
}

export interface RevalidationDocResponse {
  id: string;
  tenant_id: string;
  subject_id: string;
  document_id: string | null;
  category: string;
  display_name: string;
  issue_date: string | null;
  expiry_date: string | null;
  has_expiry: boolean;
  manually_reviewed: boolean;
  status: string;
  extraction_confidence: number | null;
  alert_days_before: number;
  last_checked_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  days_until_expiry: number | null;
}

export interface ManualDateUpdate {
  issue_date?: string | null;
  expiry_date?: string | null;
  has_expiry: boolean;
  notes?: string | null;
}

export interface AlertResponse {
  id: string;
  tenant_id: string;
  revalidation_doc_id: string;
  alert_type: string;
  message: string;
  sent_at: string | null;
  created_at: string;
}

export interface ComplianceDashboard {
  employees_total: number;
  vendors_total: number;
  docs_valid: number;
  docs_expiring_soon: number;
  docs_expired: number;
  docs_missing: number;
  docs_pending_upload: number;
  recent_alerts: AlertResponse[];
}

export interface PaginatedSubjects {
  data: SubjectResponse[];
  pagination: {
    page: number;
    page_size: number;
    total_records: number;
    total_pages: number;
  };
}

export interface PaginatedAlerts {
  data: AlertResponse[];
  pagination: {
    page: number;
    page_size: number;
    total_records: number;
    total_pages: number;
  };
}

function buildPagination(total: number, page: number, pageSize: number) {
  return {
    page,
    page_size: pageSize,
    total_records: total,
    total_pages: Math.max(1, Math.ceil(total / pageSize)),
  };
}

export function createSubject(data: SubjectCreate): Promise<SubjectResponse> {
  return apiPost<SubjectResponse>('/revalidation/subjects', data);
}

export async function listSubjects(params?: {
  subject_type?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedSubjects> {
  const search = new URLSearchParams();
  if (params?.subject_type) search.set('subject_type', params.subject_type);
  if (params?.page) search.set('page', String(params.page));
  if (params?.page_size) search.set('page_size', String(params.page_size));
  const qs = search.toString();
  const response = await apiGet<{ items: SubjectResponse[]; total: number; page: number; page_size: number }>(
    `/revalidation/subjects${qs ? `?${qs}` : ''}`,
  );

  return {
    data: response.items,
    pagination: buildPagination(response.total, response.page, response.page_size),
  };
}

export function getSubject(subjectId: string): Promise<SubjectResponse> {
  return apiGet<SubjectResponse>(`/revalidation/subjects/${subjectId}`);
}

export function getDocCatalog(subjectType?: string): Promise<DocCatalogResponse[]> {
  const search = new URLSearchParams();
  if (subjectType) search.set('subject_type', subjectType);
  const qs = search.toString();
  return apiGet<DocCatalogResponse[]>(`/revalidation/catalog${qs ? `?${qs}` : ''}`);
}

export function createRevalidationDoc(
  subjectId: string,
  data: RevalidationDocCreate,
): Promise<RevalidationDocResponse> {
  return apiPost<RevalidationDocResponse>(`/revalidation/subjects/${subjectId}/documents`, data);
}

export function getSubjectDocuments(subjectId: string): Promise<RevalidationDocResponse[]> {
  return apiGet<RevalidationDocResponse[]>(`/revalidation/subjects/${subjectId}/documents`);
}

export function getRevalidationDoc(revalDocId: string): Promise<RevalidationDocResponse> {
  return apiGet<RevalidationDocResponse>(`/revalidation/documents/${revalDocId}`);
}

export function attachDocument(
  revalDocId: string,
  documentId: string,
): Promise<RevalidationDocResponse> {
  return apiPost<RevalidationDocResponse>(`/revalidation/documents/${revalDocId}/attach`, {
    document_id: documentId,
  });
}

export function updateDatesManually(
  revalDocId: string,
  data: ManualDateUpdate,
): Promise<RevalidationDocResponse> {
  return apiPut<RevalidationDocResponse>(`/revalidation/documents/${revalDocId}/dates`, data);
}

export function getDashboard(): Promise<ComplianceDashboard> {
  return apiGet<ComplianceDashboard>('/revalidation/dashboard');
}

export async function listAlerts(params?: {
  page?: number;
  page_size?: number;
}): Promise<PaginatedAlerts> {
  const search = new URLSearchParams();
  if (params?.page) search.set('page', String(params.page));
  if (params?.page_size) search.set('page_size', String(params.page_size));
  const qs = search.toString();
  const response = await apiGet<{ items: AlertResponse[]; total: number; page: number; page_size: number }>(
    `/revalidation/alerts${qs ? `?${qs}` : ''}`,
  );

  return {
    data: response.items,
    pagination: buildPagination(response.total, response.page, response.page_size),
  };
}

export function triggerExpiryCheck(): Promise<{ message: string; tenant_id: string }> {
  return apiPost<{ message: string; tenant_id: string }>('/revalidation/admin/check-expiry');
}
