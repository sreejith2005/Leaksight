import { apiGet, apiPatch, apiPost } from './client';

export interface StructuringRun {
  id: string;
  tenant_id: string;
  run_label: string | null;
  status: string;
  total_documents: number;
  processed_documents: number;
  total_line_items_found: number;
  total_clauses_found: number;
  started_at: string | null;
  completed_at: string | null;
  created_by_user_id: string | null;
  created_at: string | null;
}

export interface StructuringRunStatus {
  run_id: string;
  status: string;
  processed_documents: number;
  total_documents: number;
  progress_percentage: number;
  total_line_items_found: number;
  total_clauses_found: number;
}

export interface StructuringLineItem {
  id: string;
  tenant_id: string;
  run_id: string;
  document_id: string;
  raw_table_id: string;
  contract_id?: string | null;
  item_description: string | null;
  normalized_item_id: string | null;
  unit_raw: string | null;
  normalized_unit_id: string | null;
  unit_price: number | null;
  currency: string | null;
  slab_info: Record<string, unknown> | Array<unknown> | null;
  effective_date: string | null;
  expiry_date: string | null;
  version_number: number;
  source_page: number | null;
  extraction_method: string | null;
  item_confidence: number;
  price_confidence: number;
  unit_confidence: number;
  review_status: 'PENDING_REVIEW' | 'CONFIRMED' | 'REJECTED';
  needs_review: boolean;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  reviewer_notes: string | null;
  created_at: string;
}

export interface StructuringClause {
  id: string;
  tenant_id: string;
  run_id: string;
  document_id: string;
  clause_type: string;
  raw_text: string;
  extracted_value: string | null;
  reviewer_notes: string | null;
  source_page: number | null;
  confidence: number;
  needs_review: boolean;
  review_status: 'PENDING_REVIEW' | 'CONFIRMED' | 'REJECTED';
  created_at: string;
}

export interface StructuringRunDocument {
  id: string;
  tenant_id: string;
  run_id: string;
  document_id: string;
  task_status: string;
  error_message: string | null;
  processing_time_seconds: number | null;
  created_at: string;
  line_items: StructuringLineItem[];
  clauses: StructuringClause[];
}

export interface StructuringRunResults {
  run: StructuringRun;
  documents: StructuringRunDocument[];
}

export interface StructuringExport {
  id: string;
  tenant_id: string;
  run_id: string;
  export_format: string;
  file_path: string | null;
  line_items_included: number | null;
  generated_by_user_id: string | null;
  created_at: string;
}

export interface PaginatedStructuringRuns {
  data: StructuringRun[];
  pagination: {
    page: number;
    page_size: number;
    total_records: number;
    total_pages: number;
  };
}

export interface UploadedDocument {
  document_id: string;
  filename: string;
  doc_type: string;
  file_size: number;
  parse_status: string;
  created_at: string | null;
}

export interface PaginatedUploadedDocuments {
  data: UploadedDocument[];
  pagination: {
    page: number;
    page_size: number;
    total_records: number;
    total_pages: number;
  };
}

export function createStructuringRun(documentIds: string[], runLabel: string): Promise<{ id: string; status: string; total_documents: number }> {
  return apiPost('/structuring/runs', { document_ids: documentIds, run_label: runLabel });
}

export async function listStructuringRuns(params?: { status?: string; page?: number; page_size?: number }): Promise<PaginatedStructuringRuns> {
  const search = new URLSearchParams();
  if (params?.status) search.set('status', params.status);
  if (params?.page) search.set('page', String(params.page));
  if (params?.page_size) search.set('page_size', String(params.page_size));
  const qs = search.toString();
  const response = await apiGet<{ items: StructuringRun[]; total: number; page: number; page_size: number }>(`/structuring/runs${qs ? `?${qs}` : ''}`);

  return {
    data: response.items,
    pagination: {
      page: response.page,
      page_size: response.page_size,
      total_records: response.total,
      total_pages: Math.max(1, Math.ceil(response.total / response.page_size)),
    },
  };
}

export function getRunStatus(runId: string): Promise<StructuringRunStatus> {
  return apiGet<StructuringRunStatus>(`/structuring/runs/${runId}/status`);
}

export function getRunResults(
  runId: string,
  params?: { document_id?: string; needs_review?: boolean; page?: number; page_size?: number },
): Promise<StructuringRunResults> {
  const search = new URLSearchParams();
  if (params?.document_id) search.set('document_id', params.document_id);
  if (params?.needs_review !== undefined) search.set('needs_review', String(params.needs_review));
  if (params?.page) search.set('page', String(params.page));
  if (params?.page_size) search.set('page_size', String(params.page_size));
  const qs = search.toString();
  return apiGet<StructuringRunResults>(`/structuring/runs/${runId}/results${qs ? `?${qs}` : ''}`);
}

export function getRunExports(runId: string): Promise<StructuringExport[]> {
  return apiGet<StructuringExport[]>(`/structuring/runs/${runId}/exports`);
}

export async function listStructuringExports(runId: string): Promise<{ data: StructuringExport[] }> {
  const data = await getRunExports(runId);
  return { data };
}

export function triggerExcelExport(runId: string): Promise<{ message: string; export_format: string; run_id: string }> {
  return apiPost<{ message: string; export_format: string; run_id: string }>(`/structuring/runs/${runId}/export/excel`);
}

export function triggerErpJsonExport(runId: string): Promise<{ message: string; export_format: string; run_id: string }> {
  return apiPost<{ message: string; export_format: string; run_id: string }>(`/structuring/runs/${runId}/export/erp-json`);
}

export function triggerLeakSightImport(runId: string): Promise<{ message: string; export_format: string; run_id: string }> {
  return apiPost<{ message: string; export_format: string; run_id: string }>(`/structuring/runs/${runId}/export/leaksight-import`);
}

export function updateLineItem(itemId: string, data: Record<string, unknown>): Promise<StructuringLineItem> {
  return apiPatch<StructuringLineItem>(`/structuring/line-items/${itemId}`, data);
}

export function confirmLineItem(itemId: string): Promise<StructuringLineItem> {
  return apiPost<StructuringLineItem>(`/structuring/line-items/${itemId}/confirm`);
}

export function rejectLineItem(itemId: string, reason: string): Promise<StructuringLineItem> {
  return apiPost<StructuringLineItem>(`/structuring/line-items/${itemId}/reject`, { reason });
}

export function updateClause(
  clauseId: string,
  data: { extracted_value?: string; reviewer_notes?: string; review_status?: 'PENDING_REVIEW' | 'CONFIRMED' | 'REJECTED' },
): Promise<StructuringClause> {
  return apiPatch<StructuringClause>(`/structuring/clauses/${clauseId}`, data);
}

export function listUploadedDocuments(params?: { doc_type?: string; page?: number; page_size?: number }): Promise<PaginatedUploadedDocuments> {
  const search = new URLSearchParams();
  if (params?.doc_type) search.set('doc_type', params.doc_type);
  if (params?.page) search.set('page', String(params.page));
  if (params?.page_size) search.set('page_size', String(params.page_size));
  const qs = search.toString();
  return apiGet<PaginatedUploadedDocuments>(`/ingest/documents${qs ? `?${qs}` : ''}`);
}

// Backward-compatible aliases used by existing pages/components.
export const getStructuringRunStatus = getRunStatus;
export const getStructuringRunResults = getRunResults;
export const exportStructuringExcel = triggerExcelExport;
export const exportStructuringErpJson = triggerErpJsonExport;
export const exportStructuringLeakSightImport = triggerLeakSightImport;
export const patchLineItem = updateLineItem;
export const patchClause = updateClause;
