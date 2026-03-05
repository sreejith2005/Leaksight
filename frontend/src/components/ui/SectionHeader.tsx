import React from 'react';

interface SectionHeaderProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function SectionHeader({ children, style }: SectionHeaderProps) {
  return (
    <h3
      style={{
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: 600,
        textTransform: 'uppercase' as const,
        letterSpacing: '0.08em',
        color: 'var(--text-secondary)',
        marginBottom: 'var(--space-4)',
        ...style,
      }}
    >
      {children}
    </h3>
  );
}
