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
  padding: '10px var(--space-5)',
  borderRadius: 'var(--radius-md)',
  fontFamily: 'var(--font-body)',
  fontWeight: 600,
  fontSize: 'var(--text-sm)',
  letterSpacing: '0.01em',
  cursor: 'pointer',
  border: '1px solid transparent',
  transition: 'all 150ms ease',
  lineHeight: '1.5',
};

const variants: Record<string, React.CSSProperties> = {
  primary: {
    background: 'var(--accent)',
    color: 'var(--text-inverse)',
    borderColor: 'var(--accent)',
    boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
  },
  secondary: {
    background: 'transparent',
    color: 'var(--accent)',
    borderColor: 'var(--accent-border)',
  },
  danger: {
    background: 'var(--color-danger)',
    color: '#ffffff',
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
