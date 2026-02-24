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
        borderRadius: 'var(--border-radius)',
        fontSize: '11px',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        background: bgColor || 'var(--color-prussian-blue)',
        color: color || 'var(--color-grey)',
        ...style,
      }}
    >
      {children}
    </span>
  );
}
