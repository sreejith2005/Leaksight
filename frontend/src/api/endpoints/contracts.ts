import { apiGet, apiPost } from '../client';
import type {
  PaginatedResponse,
  Contract,
  ContractVersionsResponse,
} from '../../types/api';

export function getContracts(params?: {
  vendor_id?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<Contract>> {
  const searchParams = new URLSearchParams();
  if (params?.vendor_id) searchParams.set('vendor_id', params.vendor_id);
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.page_size) searchParams.set('page_size', String(params.page_size));
  const qs = searchParams.toString();
  return apiGet<PaginatedResponse<Contract>>(`/contracts/${qs ? `?${qs}` : ''}`);
}

export function getContractVersions(contractId: string): Promise<ContractVersionsResponse> {
  return apiGet<ContractVersionsResponse>(`/contracts/${contractId}/versions`);
}

export interface CreateContractRequest {
  vendor_id: string;
  contract_ref?: string;
  version: {
    valid_from: string;
    valid_to: string;
    line_items: Array<{
      item_desc: string;
      unit: string;
      unit_price: number;
      currency?: string;
    }>;
  };
}

export function createContract(data: CreateContractRequest): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>('/contracts/', data);
}
