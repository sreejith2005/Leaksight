import React from 'react';

interface ConfidenceFlagProps {
  confidence: number;
  showLabel?: boolean;
}

export function ConfidenceFlag({ confidence, showLabel = true }: ConfidenceFlagProps) {
  const tier = confidence >= 0.85 ? 'HIGH' : confidence >= 0.6 ? 'MEDIUM' : 'LOW';
  const color = tier === 'HIGH'
    ? 'var(--color-success)'
    : tier === 'MEDIUM'
      ? 'var(--color-warning)'
      : 'var(--color-danger)';
  const bg = tier === 'HIGH'
    ? 'var(--color-success-dim)'
    : tier === 'MEDIUM'
      ? 'var(--color-warning-dim)'
      : 'var(--color-danger-dim)';

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        borderRadius: 'var(--radius-full)',
        padding: '4px 10px',
        background: bg,
        color,
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: 700,
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
      }}
      title={`Confidence ${Math.round(confidence * 100)}%`}
    >
      {tier === 'LOW' && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )}
      {showLabel ? tier : `${Math.round(confidence * 100)}%`}
    </span>
  );
}
