import React from 'react';
import type { IntegrityRiskLevel } from '../../api/integrity';

interface RiskBadgeProps {
  risk_score: number | null;
  risk_level: IntegrityRiskLevel | null;
  size?: 'sm' | 'lg';
  style?: React.CSSProperties;
}

const LEVEL_STYLES: Record<IntegrityRiskLevel, { color: string; background: string }> = {
  LOW: {
    color: 'var(--color-success)',
    background: 'var(--color-success-dim)',
  },
  MEDIUM: {
    color: 'var(--color-warning)',
    background: 'var(--color-warning-dim)',
  },
  HIGH: {
    color: 'var(--color-danger)',
    background: 'var(--color-danger-dim)',
  },
};

const SIZE_STYLES = {
  sm: {
    padding: '4px 10px',
    fontSize: 'var(--text-xs)',
    borderRadius: 'var(--radius-full)',
  },
  lg: {
    padding: '10px 16px',
    fontSize: 'var(--text-lg)',
    borderRadius: 'var(--radius-md)',
  },
};

export function RiskBadge({
  risk_score,
  risk_level,
  size = 'sm',
  style,
}: RiskBadgeProps) {
  if (risk_score === null || risk_level === null) {
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: SIZE_STYLES[size].padding,
          borderRadius: SIZE_STYLES[size].borderRadius,
          backgroundColor: 'var(--bg-surface-2)',
          border: '1px solid var(--border-subtle)',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-body)',
          fontSize: SIZE_STYLES[size].fontSize,
          fontWeight: 700,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          whiteSpace: 'nowrap',
          ...style,
        }}
      >
        Not Analyzed
      </span>
    );
  }

  const levelStyle = LEVEL_STYLES[risk_level];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: SIZE_STYLES[size].padding,
        borderRadius: SIZE_STYLES[size].borderRadius,
        backgroundColor: levelStyle.background,
        border: `1px solid ${levelStyle.color}`,
        color: levelStyle.color,
        fontFamily: 'var(--font-body)',
        fontSize: SIZE_STYLES[size].fontSize,
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {risk_score} {risk_level}
    </span>
  );
}
