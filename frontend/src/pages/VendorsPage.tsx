import React, { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getVendors } from '../api/endpoints/vendors';
import { DataTable } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { Card } from '../components/ui/Card';
import type { ColumnDef, SortingState } from '@tanstack/react-table';
import type { Vendor } from '../types/api';

const PAGE_SIZE = 20;

const columns: ColumnDef<Vendor, unknown>[] = [
  {
    accessorKey: 'normalized_name',
    header: 'Vendor Name',
    cell: ({ getValue }) => (
      <span style={{ color: 'var(--text-primary)', fontWeight: 500, fontFamily: 'var(--font-body)' }}>
        {getValue() as string}
      </span>
    ),
  },
  {
    accessorKey: 'raw_names',
    header: 'Variations',
    cell: ({ getValue }) => {
      const raw = getValue() as string[];
      return (
        <span style={{ fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
          {raw.slice(0, 3).join(', ')}
          {raw.length > 3 ? ` +${raw.length - 3} more` : ''}
        </span>
      );
    },
  },
  {
    accessorKey: 'gst_id',
    header: 'GST ID',
    cell: ({ getValue }) => (getValue() as string | null) ?? '—',
  },
  {
    accessorKey: 'alias_count',
    header: 'Aliases',
    cell: ({ getValue }) => getValue() as number,
  },
  {
    accessorKey: 'created_at',
    header: 'Created',
    cell: ({ getValue }) => {
      const v = getValue() as string | null;
      return v ? new Date(v).toLocaleDateString() : '—';
    },
  },
];

export default function VendorsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [sorting, setSorting] = useState<SortingState>([]);

  const { data, isLoading } = useQuery({
    queryKey: ['vendors', page, search, sorting],
    queryFn: () =>
      getVendors({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
      }),
  });

  const handleRowClick = useCallback(
    (row: Vendor) => navigate(`/vendors/${row.id}`),
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
        Vendors
      </h1>
      <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 'var(--space-6)' }}>
        Normalized vendor directory
      </p>

      {/* Search */}
      <div style={{ marginBottom: 'var(--space-5)' }}>
        <input
          type="text"
          placeholder="Search vendors..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          style={{
            backgroundColor: 'var(--bg-surface-1)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-2) var(--space-4)',
            fontFamily: 'var(--font-body)',
            fontSize: 'var(--text-sm)',
            width: 300,
            outline: 'none',
            transition: 'border-color 200ms ease',
          }}
          onFocus={(e) => { (e.target as HTMLElement).style.borderColor = 'var(--accent)'; }}
          onBlur={(e) => { (e.target as HTMLElement).style.borderColor = 'var(--border-default)'; }}
        />
      </div>

      <Card style={{ padding: 0, overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
            <LoadingSpinner size={32} />
          </div>
        ) : !data?.data.length ? (
          <div style={{ padding: 'var(--space-8)' }}>
            <EmptyState title="No vendors found" description="Vendors are created automatically when documents are parsed." />
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
