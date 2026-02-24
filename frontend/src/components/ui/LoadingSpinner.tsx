import React from 'react';

export function LoadingSpinner({ size = 32 }: { size?: number }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-8)',
      }}
    >
      <div
        style={{
          width: size,
          height: size,
          border: '3px solid var(--color-prussian-blue)',
          borderTop: '3px solid var(--color-orange)',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }}
      />
    </div>
  );
}
