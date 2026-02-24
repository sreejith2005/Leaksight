import React from 'react';

interface ErrorMessageProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorMessage({ message, onDismiss }: ErrorMessageProps) {
  return (
    <div
      style={{
        background: 'var(--color-prussian-blue)',
        borderLeft: '4px solid var(--color-danger)',
        padding: 'var(--space-3) var(--space-4)',
        borderRadius: 'var(--border-radius)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--space-3)',
        color: 'var(--color-white)',
        fontSize: '14px',
      }}
    >
      <span>{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--color-grey)',
            cursor: 'pointer',
            fontSize: '16px',
          }}
        >
          ✕
        </button>
      )}
    </div>
  );
}
