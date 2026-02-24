import React from 'react';
import type { RunStatus, LeakageStatus } from '../../types/api';

type StatusType = RunStatus | LeakageStatus;

interface StatusBadgeProps {
  status: StatusType;
  style?: React.CSSProperties;
}

const STATUS_CONFIG: Record<string, { bg: string; color: string; label: string }> = {
  COMPLETE: { bg: '#22c55e', color: '#000000', label: 'Complete' },
  ACCEPTED: { bg: '#22c55e', color: '#000000', label: 'Accepted' },
  PARTIAL_SUCCESS: { bg: '#fca311', color: '#000000', label: 'Partial Success' },
  PENDING_FX_RATE: { bg: '#fca311', color: '#000000', label: 'Pending FX Rate' },
  FAILED: { bg: '#ef4444', color: '#ffffff', label: 'Failed' },
  PENDING: { bg: '#e5e5e5', color: '#000000', label: 'Pending' },
  REJECTED: { bg: 'rgba(239,68,68,0.2)', color: '#ef4444', label: 'Rejected' },
  QUEUED: { bg: '#14213d', color: '#e5e5e5', label: 'Queued' },
  PROCESSING: { bg: '#14213d', color: '#e5e5e5', label: 'Processing' },
};

export function StatusBadge({ status, style }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] || { bg: '#e5e5e5', color: '#000000', label: status };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-1)',
        padding: '2px var(--space-2)',
        borderRadius: 'var(--border-radius)',
        fontSize: '11px',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        background: config.bg,
        color: config.color,
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
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: 'var(--color-orange)',
            animation: 'pulse 1.5s ease-in-out infinite',
          }}
        />
      )}
      {config.label}
    </span>
  );
}
