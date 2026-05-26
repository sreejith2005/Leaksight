import { apiGet, apiDownloadFile } from '../client';
import type { CFOSummaryResponse } from '../../types/api';

export function getRunSummary(runId: string): Promise<CFOSummaryResponse> {
  return apiGet<CFOSummaryResponse>(`/reports/runs/${runId}/summary`);
}

export function downloadEvidencePack(runId: string): Promise<void> {
  return apiDownloadFile(`/reports/runs/${runId}/evidence-pack`, `evidence-pack-${runId}.pdf`);
}

export function downloadExcelExport(runId: string): Promise<void> {
  return apiDownloadFile(`/reports/runs/${runId}/export-excel`, `leakage-export-${runId}.xlsx`);
}
