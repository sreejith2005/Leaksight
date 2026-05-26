import React from 'react';
import type { RunStatus, LeakageStatus } from '../../types/api';

type StatusType = RunStatus | LeakageStatus;

interface StatusBadgeProps {
  status: StatusType;
  style?: React.CSSProperties;
}

const STATUS_CONFIG: Record<string, { bg: string; color: string; label: string }> = {
  COMPLETE: { bg: 'var(--color-success-dim)', color: 'var(--color-success)', label: 'Complete' },
  ACCEPTED: { bg: 'var(--color-success-dim)', color: 'var(--color-success)', label: 'Accepted' },
  PARTIAL_SUCCESS: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)', label: 'Partial Success' },
  PENDING_FX_RATE: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)', label: 'Pending FX Rate' },
  FAILED: { bg: 'var(--color-danger-dim)', color: 'var(--color-danger)', label: 'Failed' },
  PENDING: { bg: 'transparent', color: 'var(--text-muted)', label: 'Pending Review' },
  REJECTED: { bg: 'var(--color-danger-dim)', color: 'var(--color-danger)', label: 'Rejected' },
  QUEUED: { bg: 'var(--bg-surface-2)', color: 'var(--text-secondary)', label: 'Queued' },
  PROCESSING: { bg: 'var(--color-info-dim)', color: 'var(--color-info)', label: 'Processing' },
};

export function StatusBadge({ status, style }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] || { bg: 'var(--bg-surface-2)', color: 'var(--text-secondary)', label: status };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        padding: status === 'PENDING' ? '2px 8px' : '3px 10px',
        borderRadius: 'var(--radius-full)',
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: status === 'PENDING' ? 500 : 600,
        textTransform: 'uppercase' as const,
        letterSpacing: '0.04em',
        background: config.bg,
        color: config.color,
        border: status === 'PENDING' ? '1px solid var(--border-default)' : '1px solid transparent',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {status === 'PENDING_FX_RATE' && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      )}
      {status === 'PROCESSING' && (
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: 'var(--color-info)',
            animation: 'pulse 1.5s ease-in-out infinite',
          }}
        />
      )}
      {config.label}
    </span>
  );
}
