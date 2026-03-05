import React from 'react';

interface GiltDividerProps {
  style?: React.CSSProperties;
}

export function GiltDivider({ style }: GiltDividerProps) {
  return (
    <div
      style={{
        height: '1px',
        background: 'linear-gradient(90deg, var(--accent) 0%, var(--accent-border) 30%, transparent 100%)',
        opacity: 0.4,
        margin: 'var(--space-8) 0',
        ...style,
      }}
    />
  );
}
