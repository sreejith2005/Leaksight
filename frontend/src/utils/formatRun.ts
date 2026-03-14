/**
 * LeakSight V1 — Run Label Formatting Utility
 *
 * Provides a human-readable label for analysis runs.
 * Never shows UUID fragments in user-facing text.
 */

import type { RunStatusResponse } from '../types/api';

/**
 * Format a human-readable label for an analysis run.
 *
 * - If multiple runs share the same date, the time is appended.
 * - Finding count is always shown.
 * - UUID fragments are never shown.
 */
export function formatRunLabel(
  run: RunStatusResponse,
  allRuns?: RunStatusResponse[],
): string {
  const dateObj = run.created_at ? new Date(run.created_at) : null;
  const findings = run.leakage_record_count ?? 0;
  const findingsStr = `${findings} finding${findings !== 1 ? 's' : ''}`;

  if (!dateObj || isNaN(dateObj.getTime())) {
    return `Analysis Run · ${findingsStr}`;
  }

  const dateStr = dateObj.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  // Check if multiple runs share the same calendar date
  let showTime = false;
  if (allRuns && allRuns.length > 1) {
    const sameDateRuns = allRuns.filter((r) => {
      if (!r.created_at) return false;
      const d = new Date(r.created_at);
      return (
        d.getFullYear() === dateObj.getFullYear() &&
        d.getMonth() === dateObj.getMonth() &&
        d.getDate() === dateObj.getDate()
      );
    });
    showTime = sameDateRuns.length > 1;
  }

  const timeStr = showTime
    ? ` ${dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}`
    : '';

  return `Analysis Run · ${dateStr}${timeStr} · ${findingsStr}`;
}
