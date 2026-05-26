import React from 'react';

interface MetricDisplayProps {
  value: string | number;
  label: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  color?: string;
  prefix?: string;
  style?: React.CSSProperties;
}

const sizes = {
  sm: { value: 'var(--text-xl)', label: 'var(--text-xs)' },
  md: { value: 'var(--text-2xl)', label: 'var(--text-xs)' },
  lg: { value: 'var(--text-3xl)', label: 'var(--text-sm)' },
  xl: { value: 'var(--text-4xl)', label: 'var(--text-sm)' },
};

export function MetricDisplay({ value, label, size = 'md', color, prefix, style }: MetricDisplayProps) {
  const s = sizes[size];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', ...style }}>
      <span
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: s.label,
          fontWeight: 600,
          textTransform: 'uppercase' as const,
          letterSpacing: '0.06em',
          color: 'var(--text-secondary)',
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: s.value,
          fontWeight: 700,
          color: color || 'var(--text-primary)',
          letterSpacing: '-0.01em',
          lineHeight: 1.1,
        }}
      >
        {prefix}{value}
      </span>
    </div>
  );
}
