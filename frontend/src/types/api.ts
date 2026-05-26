/* ── Status Enums ───────────────────────────────────────────────── */

export type RunStatus =
  | 'QUEUED'
  | 'PROCESSING'
  | 'PARTIAL_SUCCESS'
  | 'COMPLETE'
  | 'FAILED';

export type LeakageStatus =
  | 'PENDING'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'PENDING_FX_RATE';

export type LeakageType =
  | 'PRICE_MISMATCH'
  | 'DUPLICATE_INVOICE'
  | 'QUANTITY_MISMATCH';

/* ── Pagination ────────────────────────────────────────────────── */

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_records: number;
  total_pages: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  pagination: PaginationMeta;
}

/* ── API Error ─────────────────────────────────────────────────── */

export interface APIErrorDetail {
  field?: string;
  message: string;
}

export interface APIErrorBody {
  error: {
    code: string;
    message: string;
    details?: APIErrorDetail[];
  };
}

/* ── Auth ──────────────────────────────────────────────────────── */

export interface LoginRequest {
  email: string;
  password: string;
  tenant_name?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: string;
    email: string;
    role: string;
    tenant_id: string;
    tenant_name: string;
  };
}

export interface CurrentUser {
  user_id: string;
  tenant_id: string;
  email: string;
  role: string;
  tenant_name?: string;
}

/* ── Ingest ────────────────────────────────────────────────────── */

export interface UploadResponse {
  document_id: string;
  filename: string;
  doc_type: string;
  sha256_hash: string;
  file_size: number;
  parse_status: string;
  created_at: string | null;
  note?: string;
}

export interface TriggerRunResponse {
  run_id: string;
  status: string;
  total_documents: number;
  created_at: string | null;
}

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  total_documents: number;
  processed_documents: number;
  progress_percentage: number;
  total_leakage_found: number;
  leakage_record_count: number;
  error_summary: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

/* ── Leakage ───────────────────────────────────────────────────── */

export interface LeakageRecord {
  id: string;
  run_id: string | null;
  leakage_type: LeakageType;
  amount: number;
  currency: string;
  confidence: number;
  rule_applied: string;
  explanation: string;
  status: LeakageStatus;
  vendor_name: string;
  invoice_no: string;
  invoice_date: string | null;
  created_at: string | null;
}

export interface LeakageRecordDetail extends LeakageRecord {
  evidence: Record<string, unknown>;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
}

export interface ReviewRequest {
  notes?: string;
}

export interface ReviewResponse {
  id: string;
  status: LeakageStatus;
  reviewed_by: string;
  reviewed_at: string;
  review_notes: string | null;
}

export interface LeakageSummary {
  total_leakage_amount: number;
  currency: string;
  by_type: Record<string, { count: number; total_amount: number }>;
  by_status: Record<string, number>;
  by_vendor: Array<{
    vendor_id: string;
    vendor_name: string;
    total_amount: number;
    record_count: number;
  }>;
  average_confidence: number | null;
}

/* ── Vendors ───────────────────────────────────────────────────── */

export interface Vendor {
  id: string;
  normalized_name: string;
  raw_names: string[];
  gst_id: string | null;
  alias_count: number;
  created_at: string | null;
}

export interface VendorAlias {
  id: string;
  alias_name: string;
  override_source: string;
  applied_by: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface VendorDetail {
  id: string;
  normalized_name: string;
  raw_names: string[];
  gst_id: string | null;
  aliases: VendorAlias[];
  created_at: string | null;
}

export interface AddAliasRequest {
  alias_name: string;
}

export interface AddAliasResponse {
  id: string;
  vendor_id: string;
  alias_name: string;
  override_source: string;
  applied_by: string;
  is_active: boolean;
  created_at: string | null;
}

export interface DeactivateAliasResponse {
  id: string;
  alias_name: string;
  is_active: boolean;
  deactivated_at: string;
}

/* ── Contracts ─────────────────────────────────────────────────── */

export interface ContractVersion {
  version_number: number;
  valid_from: string;
  valid_to: string;
  line_item_count: number;
}

export interface Contract {
  id: string;
  vendor_id: string;
  vendor_name: string;
  contract_ref: string | null;
  active_version: ContractVersion | null;
  total_versions: number;
  created_at: string | null;
}

export interface ContractLineItem {
  id: string;
  item_desc: string;
  unit: string;
  unit_price: number;
  currency: string;
}

export interface ContractVersionDetail {
  id: string;
  version_number: number;
  valid_from: string;
  valid_to: string;
  line_items: ContractLineItem[];
}

export interface ContractVersionsResponse {
  contract_id: string;
  vendor_name: string;
  contract_ref: string | null;
  versions: ContractVersionDetail[];
}

/* ── Reports ───────────────────────────────────────────────────── */

export interface CFOSummaryResponse {
  run_id: string;
  run_status: RunStatus;
  summary: {
    total_leakage: number;
    currency: string;
    pending_review_count: number;
    pending_fx_rate_count: number;
    top_vendors: Array<{
      vendor_name: string;
      leakage_amount: number;
      record_count: number;
    }>;
    by_rule: Record<string, { count: number; amount: number }>;
    confidence_bands: {
      high: { count: number; amount: number };
      medium: { count: number; amount: number };
      low: { count: number; amount: number };
    };
  };
  partial_success_notes: string | null;
  generated_at: string;
}

/* ── Admin ─────────────────────────────────────────────────────── */

export interface FxRateItem {
  from_currency: string;
  to_currency: string;
  rate: number;
  rate_date: string;
  source: string;
}

export interface FxRateUploadRequest {
  rates: FxRateItem[];
}

export interface FxRateUploadResponse {
  uploaded_count: number;
  rates: Array<{
    id: string | null;
    from_currency: string;
    to_currency: string;
    rate: number;
    rate_date: string;
  }>;
}

export interface FxRate {
  id: string;
  from_currency: string;
  to_currency: string;
  rate: number;
  rate_date: string;
  source: string;
  uploaded_by: string | null;
  created_at: string | null;
}

export interface TenantSettings {
  tenant_id: string;
  fuzzy_threshold: number;
  duplicate_window_days: number;
  manual_review_threshold: number;
  base_currency: string;
  abbreviation_dictionary: Record<string, string>;
  updated_at: string | null;
}

export interface TenantSettingsUpdate {
  fuzzy_threshold?: number;
  duplicate_window_days?: number;
  manual_review_threshold?: number;
  base_currency?: string;
  abbreviation_dictionary_additions?: Record<string, string>;
}

/* ── Notifications ─────────────────────────────────────────────── */

export interface Notification {
  id: string;
  message: string;
  notification_type: string;
  run_id: string | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string | null;
}

export interface NotificationsResponse {
  data: Notification[];
  pagination: {
    total: number;
    skip: number;
    limit: number;
  };
  unread_count: number;
}
