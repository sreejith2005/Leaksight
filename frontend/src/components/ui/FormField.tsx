import React from 'react';

interface FormFieldProps {
  label: string;
  description?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function FormField({ label, description, children, style }: FormFieldProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', ...style }}>
      <label
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-xs)',
          fontWeight: 600,
          textTransform: 'uppercase' as const,
          letterSpacing: '0.06em',
          color: 'var(--text-secondary)',
        }}
      >
        {label}
      </label>
      {children}
      {description && (
        <span
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-muted)',
            lineHeight: 1.4,
          }}
        >
          {description}
        </span>
      )}
    </div>
  );
}
