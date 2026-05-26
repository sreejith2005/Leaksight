import { apiGet, apiPost, apiPut } from '../client';
import type {
  PaginatedResponse,
  Vendor,
  VendorDetail,
  AddAliasRequest,
  AddAliasResponse,
  DeactivateAliasResponse,
} from '../../types/api';

export function getVendors(params?: {
  search?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<Vendor>> {
  const searchParams = new URLSearchParams();
  if (params?.search) searchParams.set('search', params.search);
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.page_size) searchParams.set('page_size', String(params.page_size));
  const qs = searchParams.toString();
  return apiGet<PaginatedResponse<Vendor>>(`/vendors/${qs ? `?${qs}` : ''}`);
}

export function getVendor(id: string): Promise<VendorDetail> {
  return apiGet<VendorDetail>(`/vendors/${id}`);
}

export function addAlias(vendorId: string, data: AddAliasRequest): Promise<AddAliasResponse> {
  return apiPost<AddAliasResponse>(`/vendors/${vendorId}/aliases`, data);
}

export function deactivateAlias(vendorId: string, aliasId: string): Promise<DeactivateAliasResponse> {
  return apiPut<DeactivateAliasResponse>(`/vendors/${vendorId}/aliases/${aliasId}/deactivate`);
}
