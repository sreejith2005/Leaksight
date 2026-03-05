import React from 'react';

interface ConfidenceBarProps {
  value: number; // 0–1
  width?: number;
  showLabel?: boolean;
  style?: React.CSSProperties;
}

function getConfidenceColor(value: number): string {
  if (value >= 0.85) return 'var(--color-success)';
  if (value >= 0.7) return 'var(--color-warning)';
  return 'var(--color-danger)';
}

export function ConfidenceBar({ value, width = 60, showLabel = true, style }: ConfidenceBarProps) {
  const pct = Math.min(Math.max(value, 0), 1) * 100;
  const color = getConfidenceColor(value);

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', ...style }}>
      <div
        style={{
          width,
          height: 4,
          borderRadius: 'var(--radius-full)',
          background: 'var(--bg-surface-3)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: color,
            borderRadius: 'var(--radius-full)',
            transition: 'width 300ms ease-out',
          }}
        />
      </div>
      {showLabel && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-secondary)',
            minWidth: 32,
          }}
        >
          {(value * 100).toFixed(0)}%
        </span>
      )}
    </div>
  );
}
