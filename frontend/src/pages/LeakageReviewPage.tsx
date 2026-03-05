import React, { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getLeakageRecords } from '../api/endpoints/leakage';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Pagination } from '../components/ui/Pagination';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { Card } from '../components/ui/Card';
import type { ColumnDef, SortingState } from '@tanstack/react-table';
import type { LeakageRecord, LeakageStatus, LeakageType } from '../types/api';

const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<{ label: string; value: LeakageStatus | '' }> = [
  { label: 'All Statuses', value: '' },
  { label: 'Pending', value: 'PENDING' },
  { label: 'Accepted', value: 'ACCEPTED' },
  { label: 'Rejected', value: 'REJECTED' },
  { label: 'Pending FX Rate', value: 'PENDING_FX_RATE' },
];

const TYPE_OPTIONS: Array<{ label: string; value: LeakageType | '' }> = [
  { label: 'All Types', value: '' },
  { label: 'Price Mismatch', value: 'PRICE_MISMATCH' },
  { label: 'Duplicate Invoice', value: 'DUPLICATE_INVOICE' },
  { label: 'Quantity Mismatch', value: 'QUANTITY_MISMATCH' },
];

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

const columns: ColumnDef<LeakageRecord, unknown>[] = [
  {
    accessorKey: 'vendor_name',
    header: 'Vendor',
    cell: ({ getValue }) => (
      <span style={{ color: 'var(--text-primary)', fontWeight: 500, fontFamily: 'var(--font-body)' }}>
        {getValue() as string}
      </span>
    ),
  },
  {
    accessorKey: 'leakage_type',
    header: 'Type',
    cell: ({ getValue }) => (
      <span style={{ fontSize: 'var(--text-xs)', fontFamily: 'var(--font-body)', textTransform: 'uppercase' as const, letterSpacing: '0.04em', color: 'var(--text-secondary)' }}>
        {(getValue() as string).replace(/_/g, ' ')}
      </span>
    ),
  },
  {
    accessorKey: 'amount',
    header: 'Amount',
    cell: ({ row }) => (
      <span style={{ fontWeight: 600, color: 'var(--accent)', fontFamily: 'var(--font-display)' }}>
        {formatCurrency(row.original.amount, row.original.currency)}
      </span>
    ),
  },
  {
    accessorKey: 'confidence',
    header: 'Confidence',
    cell: ({ getValue }) => (
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
        {((getValue() as number) * 100).toFixed(0)}%
      </span>
    ),
  },
  {
    accessorKey: 'invoice_no',
    header: 'Invoice',
  },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ getValue }) => <StatusBadge status={getValue() as LeakageStatus} />,
  },
  {
    accessorKey: 'created_at',
    header: 'Date',
    cell: ({ getValue }) => {
      const v = getValue() as string | null;
      return v ? new Date(v).toLocaleDateString() : '—';
    },
  },
];

export default function LeakageReviewPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [sorting, setSorting] = useState<SortingState>([]);

  const { data, isLoading } = useQuery({
    queryKey: ['leakageRecords', page, statusFilter, typeFilter, sorting],
    queryFn: () =>
      getLeakageRecords({
        page,
        page_size: PAGE_SIZE,
        status: statusFilter || undefined,
        leakage_type: typeFilter || undefined,
        sort_by: sorting[0]?.id,
        sort_dir: sorting[0]?.desc ? 'desc' : 'asc',
      }),
  });

  const handleRowClick = useCallback(
    (row: LeakageRecord) => {
      navigate(`/leakage/${row.id}`);
    },
    [navigate],
  );

  return (
    <div className="animate-fadeIn">
      <h1
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 'var(--text-3xl)',
          fontWeight: 700,
          color: 'var(--text-primary)',
          marginBottom: 'var(--space-2)',
          letterSpacing: '-0.01em',
        }}
      >
        Leakage Review
      </h1>
      <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 'var(--space-6)' }}>
        Review and action flagged findings
      </p>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 'var(--space-3)', marginBottom: 'var(--space-5)', flexWrap: 'wrap' }}>
        <FilterSelect
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1); }}
          options={STATUS_OPTIONS}
        />
        <FilterSelect
          value={typeFilter}
          onChange={(v) => { setTypeFilter(v); setPage(1); }}
          options={TYPE_OPTIONS}
        />
      </div>

      {/* Table */}
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
            <LoadingSpinner size={32} />
          </div>
        ) : !data?.data.length ? (
          <div style={{ padding: 'var(--space-8)' }}>
            <EmptyState title="No leakage records found" description="Adjust your filters or run an analysis." />
          </div>
        ) : (
          <>
            <DataTable
              data={data.data}
              columns={columns}
              sorting={sorting}
              onSortingChange={setSorting}
              onRowClick={handleRowClick}
              getRowId={(row) => row.id}
              manualSorting
            />
            {data.pagination && (
              <div style={{ padding: 'var(--space-4)' }}>
                <Pagination
                  page={data.pagination.page}
                  totalPages={data.pagination.total_pages}
                  totalRecords={data.pagination.total_records}
                  pageSize={data.pagination.page_size}
                  onPageChange={setPage}
                />
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

/* ── Filter select ─────────────────────────────────────────────── */

function FilterSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ label: string; value: string }>;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        backgroundColor: 'var(--bg-surface-1)',
        color: 'var(--text-primary)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-2) var(--space-3)',
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        outline: 'none',
        minWidth: 150,
        transition: 'border-color 150ms ease',
      }}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
