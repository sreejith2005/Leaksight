/**
 * LeakSight V1 — Central API Client
 *
 * Source: docs/ARCHITECTURE.md (Section 6.1), docs/CLAUDE.md (API client rule)
 *
 * All API calls go through this module. Components never call fetch directly.
 * Handles:
 *   - Base URL configuration from VITE_API_BASE_URL
 *   - JWT Authorization header on every request
 *   - 401 → redirect to /login and clear stored JWT
 *   - Non-2xx → throw typed APIError
 *   - Binary download (PDF, Excel) via apiDownloadFile
 */

import type { APIErrorBody } from '../types/api';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';
const TOKEN_KEY = 'leaksight_token';

/* ── APIError class ─────────────────────────────────────────────── */

export class APIError extends Error {
  status: number;
  code: string;
  details?: Array<{ field?: string; message: string }>;

  constructor(status: number, code: string, message: string, details?: Array<{ field?: string; message: string }>) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/* ── Token helpers ──────────────────────────────────────────────── */

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/* ── Internal fetch wrapper ─────────────────────────────────────── */

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  isFormData?: boolean,
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {};

  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (!isFormData && body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(url, {
    method,
    headers,
    body: isFormData
      ? (body as FormData)
      : body !== undefined
        ? JSON.stringify(body)
        : undefined,
  });

  // Handle 401 globally — session expired
  if (response.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new APIError(401, 'UNAUTHORIZED', 'Session expired');
  }

  // Handle non-2xx responses
  if (!response.ok) {
    let errorBody: APIErrorBody | null = null;
    try {
      errorBody = await response.json();
    } catch {
      // Response body not JSON
    }

    const code = errorBody?.error?.code || 'UNKNOWN_ERROR';
    const message = errorBody?.error?.message || `Request failed with status ${response.status}`;
    const details = errorBody?.error?.details;

    throw new APIError(response.status, code, message, details);
  }

  // Handle empty responses (204 No Content)
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

/* ── Typed API methods ──────────────────────────────────────────── */

export function apiGet<T>(path: string): Promise<T> {
  return request<T>('GET', path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body);
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('PUT', path, body);
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('PATCH', path, body);
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>('DELETE', path);
}

export function apiPostFormData<T>(path: string, formData: FormData): Promise<T> {
  return request<T>('POST', path, formData, true);
}

/* ── Binary file download ───────────────────────────────────────── */

export async function apiDownloadFile(path: string, filename: string): Promise<void> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {};

  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    method: 'GET',
    headers,
  });

  if (response.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new APIError(401, 'UNAUTHORIZED', 'Session expired');
  }

  if (!response.ok) {
    let errorBody: APIErrorBody | null = null;
    try {
      errorBody = await response.json();
    } catch {
      // Binary response, can't parse JSON
    }

    const code = errorBody?.error?.code || 'DOWNLOAD_FAILED';
    const message = errorBody?.error?.message || `Download failed with status ${response.status}`;
    throw new APIError(response.status, code, message);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(objectUrl);
}
