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
        background: 'var(--color-prussian-blue)',
        border: highlight
          ? `1px solid ${borderColor || 'var(--color-orange)'}`
          : '1px solid var(--border-color)',
        borderRadius: 'var(--border-radius)',
        padding: 'var(--space-6)',
        color: 'var(--color-white)',
        cursor: onClick ? 'pointer' : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
