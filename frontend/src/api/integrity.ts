import { apiGet, apiPost } from './client';

export type IntegrityRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';
export type IntegrityComparisonStatus = 'NEW' | 'UNCHANGED' | 'MODIFIED' | 'INCONCLUSIVE';
export type IntegrityDocumentType = 'INVOICE' | 'CONTRACT' | 'PO';

export interface NumericChange {
  previous_value: number;
  current_value: number;
  context: string;
  change_pct: number;
}

export interface IntegrityMetadata {
  creation_date?: string | null;
  modification_date?: string | null;
  author?: string | null;
  software?: string | null;
  page_count?: number | null;
  revision_count?: number | null;
  anomalies?: string[];
  [key: string]: unknown;
}

export interface IntegrityReport {
  document_id: string;
  filename: string;
  doc_type: IntegrityDocumentType;
  risk_score: number | null;
  risk_level: IntegrityRiskLevel | null;
  comparison_status: IntegrityComparisonStatus;
  version_count: number;
  flags: string[];
  numeric_changes: NumericChange[];
  metadata: IntegrityMetadata;
  analyzed_at: string | null;
}

export interface IntegrityListItem {
  document_id: string;
  filename: string;
  doc_type: IntegrityDocumentType;
  risk_score: number | null;
  risk_level: IntegrityRiskLevel | null;
  comparison_status: IntegrityComparisonStatus | null;
  analyzed_at: string | null;
}

export interface IntegrityListResponse {
  items: IntegrityListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface AnalyzeDocumentResponse {
  task_queued: boolean;
  document_id: string;
}

export interface BatchAnalyzeResponse {
  queued: number;
  document_ids: string[];
}

export function listDocuments(
  page: number,
  pageSize: number,
  riskLevel?: IntegrityRiskLevel,
): Promise<IntegrityListResponse> {
  const search = new URLSearchParams();
  search.set('page', String(page));
  search.set('page_size', String(pageSize));
  if (riskLevel) {
    search.set('risk_level', riskLevel);
  }

  return apiGet<IntegrityListResponse>(`/integrity/documents?${search.toString()}`);
}

export function getReport(documentId: string): Promise<IntegrityReport> {
  return apiGet<IntegrityReport>(`/integrity/documents/${documentId}`);
}

export function analyzeDocument(documentId: string): Promise<AnalyzeDocumentResponse> {
  return apiPost<AnalyzeDocumentResponse>(`/integrity/analyze/${documentId}`);
}

export async function analyzeBatch(documentIds: string[]): Promise<BatchAnalyzeResponse> {
  const uniqueIds = Array.from(new Set(documentIds));
  if (!uniqueIds.length) {
    return { queued: 0, document_ids: [] };
  }

  const chunkSize = 50;
  const responses: BatchAnalyzeResponse[] = [];

  for (let index = 0; index < uniqueIds.length; index += chunkSize) {
    const chunk = uniqueIds.slice(index, index + chunkSize);
    const response = await apiPost<BatchAnalyzeResponse>('/integrity/analyze-batch', {
      document_ids: chunk,
    });
    responses.push(response);
  }

  return {
    queued: responses.reduce((total, response) => total + response.queued, 0),
    document_ids: responses.flatMap((response) => response.document_ids),
  };
}
