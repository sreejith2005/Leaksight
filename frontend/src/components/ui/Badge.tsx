import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  color?: string;
  bgColor?: string;
  style?: React.CSSProperties;
}

export function Badge({ children, color, bgColor, style }: BadgeProps) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px var(--space-2)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: 600,
        textTransform: 'uppercase' as const,
        letterSpacing: '0.04em',
        background: bgColor || 'var(--bg-surface-2)',
        color: color || 'var(--text-secondary)',
        border: '1px solid var(--border-subtle)',
        ...style,
      }}
    >
      {children}
    </span>
  );
}
