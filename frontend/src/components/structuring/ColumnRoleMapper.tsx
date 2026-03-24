import React from 'react';
export function ColumnRoleMapper() {
  return (
    <div
      style={{
        border: '1px solid var(--color-warning)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--color-warning-dim)',
        padding: 'var(--space-4)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
          fontWeight: 700,
          color: 'var(--color-warning)',
          marginBottom: 'var(--space-2)',
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
        }}
      >
        Low-Confidence Extraction Notice
      </div>
      <div
        style={{
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
          lineHeight: 1.6,
        }}
      >
        Some items were extracted with low confidence. Review and correct them individually using the edit controls in the table below.
      </div>
    </div>
  );
}
