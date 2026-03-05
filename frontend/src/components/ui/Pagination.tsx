import React from 'react';

interface PaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  totalRecords?: number;
  pageSize?: number;
}

export function Pagination({ page, totalPages, onPageChange, totalRecords, pageSize }: PaginationProps) {
  const start = totalRecords ? (page - 1) * (pageSize || 20) + 1 : 0;
  const end = totalRecords ? Math.min(page * (pageSize || 20), totalRecords) : 0;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: 'var(--space-3) 0',
        gap: 'var(--space-4)',
      }}
    >
      {totalRecords !== undefined && (
        <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', letterSpacing: '0.02em' }}>
          Showing {start}–{end} of {totalRecords} findings
        </span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          style={navBtnStyle}
        >
          ← Previous
        </button>
        <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', padding: '0 var(--space-2)' }}>
          Page {page} of {totalPages}
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          style={navBtnStyle}
        >
          Next →
        </button>
      </div>
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  background: 'var(--bg-surface-2)',
  border: '1px solid var(--border-default)',
  color: 'var(--text-secondary)',
  padding: 'var(--space-1) var(--space-3)',
  borderRadius: 'var(--radius-md)',
  cursor: 'pointer',
  fontFamily: 'var(--font-body)',
  fontSize: 'var(--text-sm)',
  fontWeight: 500,
  transition: 'all 150ms ease',
};
