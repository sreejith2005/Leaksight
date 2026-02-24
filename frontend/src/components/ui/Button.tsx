import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger';
  loading?: boolean;
  fullWidth?: boolean;
}

const baseStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 'var(--space-2)',
  padding: 'var(--space-2) var(--space-4)',
  borderRadius: 'var(--border-radius)',
  fontWeight: 700,
  fontSize: '14px',
  cursor: 'pointer',
  border: '2px solid transparent',
  transition: 'opacity 0.15s, background 0.15s',
  lineHeight: '1.5',
};

const variants: Record<string, React.CSSProperties> = {
  primary: {
    background: 'var(--color-orange)',
    color: 'var(--color-black)',
    borderColor: 'var(--color-orange)',
  },
  secondary: {
    background: 'transparent',
    color: 'var(--color-orange)',
    borderColor: 'var(--color-orange)',
  },
  danger: {
    background: 'var(--color-danger)',
    color: 'var(--color-white)',
    borderColor: 'var(--color-danger)',
  },
};

export function Button({
  variant = 'primary',
  loading = false,
  fullWidth = false,
  disabled,
  children,
  style,
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      {...props}
      disabled={isDisabled}
      style={{
        ...baseStyle,
        ...variants[variant],
        ...(fullWidth ? { width: '100%' } : {}),
        ...(isDisabled ? { opacity: 0.6, cursor: 'not-allowed' } : {}),
        ...style,
      }}
    >
      {loading && <LoadingDots />}
      {children}
    </button>
  );
}

function LoadingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: '2px' }}>
      <span style={dotStyle}>●</span>
      <span style={{ ...dotStyle, animationDelay: '0.2s' }}>●</span>
      <span style={{ ...dotStyle, animationDelay: '0.4s' }}>●</span>
    </span>
  );
}

const dotStyle: React.CSSProperties = {
  fontSize: '8px',
  animation: 'pulse 1s ease-in-out infinite',
};
