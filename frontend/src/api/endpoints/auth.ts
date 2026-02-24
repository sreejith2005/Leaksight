import { apiPost } from '../client';
import type { LoginRequest, LoginResponse } from '../../types/api';

export function login(data: LoginRequest): Promise<LoginResponse> {
  return apiPost<LoginResponse>('/auth/token', data);
}
