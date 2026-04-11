import React from 'react';

interface StatusBadgeProps {
  status: string;
}

const STATUS_STYLES: Record<string, { color: string; background: string }> = {
  VALID: {
    color: 'var(--color-success)',
    background: 'var(--color-success-dim)',
  },
  EXPIRING_SOON: {
    color: 'var(--color-warning)',
    background: 'var(--color-warning-dim)',
  },
  EXPIRED: {
    color: 'var(--color-danger)',
    background: 'var(--color-danger-dim)',
  },
  PENDING_UPLOAD: {
    color: 'var(--color-text-secondary, var(--text-secondary))',
    background: 'var(--bg-surface-2)',
  },
  REVALIDATION_PENDING: {
    color: 'var(--color-warning)',
    background: 'var(--color-warning-dim)',
  },
  NO_EXPIRY: {
    color: 'var(--color-text-secondary, var(--text-secondary))',
    background: 'var(--bg-surface-2)',
  },
};

function toTitleCase(value: string): string {
  return value
    .toLowerCase()
    .split(' ')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toUpperCase();
  const style = STATUS_STYLES[normalized] || {
    color: 'var(--color-text-secondary, var(--text-secondary))',
    background: 'var(--bg-surface-2)',
  };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: 'var(--radius-full)',
        padding: '4px 10px',
        backgroundColor: style.background,
        border: '1px solid var(--border-subtle)',
        color: style.color,
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: 700,
        letterSpacing: '0.04em',
      }}
    >
      {toTitleCase(normalized.replace(/_/g, ' '))}
    </span>
  );
}
