import React from 'react';

interface ComplianceMeterProps {
  uploaded: number;
  total_required: number;
  expired: number;
  expiring_soon: number;
}

export function ComplianceMeter({
  uploaded,
  total_required,
  expired,
  expiring_soon,
}: ComplianceMeterProps) {
  if (total_required === 0) {
    return (
      <span
        style={{
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
        }}
      >
        No required documents
      </span>
    );
  }

  const progress = Math.min(100, Math.max(0, (uploaded / total_required) * 100));
  const fillColor = expired > 0
    ? 'var(--color-danger)'
    : expiring_soon > 0
      ? 'var(--color-warning)'
      : 'var(--color-success)';

  return (
    <div style={{ display: 'grid', gap: 'var(--space-2)', minWidth: 180 }}>
      <span
        style={{
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
        }}
      >
        {uploaded} / {total_required} documents
      </span>
      <div
        aria-hidden="true"
        style={{
          width: '100%',
          height: '6px',
          borderRadius: 'var(--radius-full)',
          backgroundColor: 'var(--bg-surface-3)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            borderRadius: 'var(--radius-full)',
            backgroundColor: fillColor,
            transition: 'width var(--transition-base)',
          }}
        />
      </div>
    </div>
  );
}
