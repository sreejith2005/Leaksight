import React from 'react';

interface CardProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
  highlight?: boolean;
  borderColor?: string;
  onClick?: () => void;
}

export function Card({ children, style, highlight, borderColor, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--bg-surface-1)',
        border: highlight
          ? `1px solid ${borderColor || 'var(--accent)'}`
          : '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-6)',
        color: 'var(--text-primary)',
        cursor: onClick ? 'pointer' : undefined,
        transition: 'border-color 150ms ease, box-shadow 150ms ease',
        ...style,
      }}
    >
      {children}
    </div>
  );
}
