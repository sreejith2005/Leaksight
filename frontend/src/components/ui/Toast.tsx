import React, { useEffect, useRef } from 'react';
import { useToast } from '../../context/ToastContext';

const typeStyles: Record<string, { border: string; icon: string }> = {
  success: { border: 'var(--color-success)', icon: '✓' },
  error: { border: 'var(--color-error)', icon: '✕' },
  warning: { border: 'var(--color-warning)', icon: '⚠' },
};

export function ToastContainer() {
  const { toasts, removeToast } = useToast();

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 'var(--space-6)',
        right: 'var(--space-6)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        zIndex: 10000,
        maxWidth: 380,
        width: '100%',
      }}
    >
      {toasts.map((toast) => (
        <ToastItem
          key={toast.id}
          id={toast.id}
          type={toast.type}
          message={toast.message}
          onDismiss={removeToast}
        />
      ))}
    </div>
  );
}

function ToastItem({
  id,
  type,
  message,
  onDismiss,
}: {
  id: string;
  type: 'success' | 'error' | 'warning';
  message: string;
  onDismiss: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const style = typeStyles[type];

  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.style.opacity = '0';
      el.style.transform = 'translateX(100%)';
      requestAnimationFrame(() => {
        el.style.transition = 'opacity 0.3s, transform 0.3s';
        el.style.opacity = '1';
        el.style.transform = 'translateX(0)';
      });
    }
  }, []);

  return (
    <div
      ref={ref}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-3)',
        padding: 'var(--space-4)',
        backgroundColor: 'var(--color-prussian-blue)',
        borderLeft: `4px solid ${style.border}`,
        borderRadius: 'var(--radius-md)',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
        color: 'var(--color-grey)',
        fontSize: '14px',
        lineHeight: 1.5,
      }}
    >
      <span
        style={{
          flexShrink: 0,
          width: 20,
          height: 20,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: style.border,
          fontWeight: 700,
          fontSize: '14px',
        }}
      >
        {style.icon}
      </span>
      <span style={{ flex: 1 }}>{message}</span>
      <button
        onClick={() => onDismiss(id)}
        style={{
          flexShrink: 0,
          background: 'none',
          border: 'none',
          color: 'var(--color-muted)',
          cursor: 'pointer',
          fontSize: '16px',
          padding: 0,
          lineHeight: 1,
        }}
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}
