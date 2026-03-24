import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { listStructuringRuns } from '../../api/structuring';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import { DataTable } from '../../components/ui/DataTable';
import { Card } from '../../components/ui/Card';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import type { ColumnDef } from '@tanstack/react-table';
import type { StructuringRun } from '../../api/structuring';

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

function statusBadge(status: string) {
  const normalized = status.toUpperCase();
  const statusConfig: Record<string, { bg: string; color: string }> = {
    COMPLETE: { bg: 'var(--color-success-dim)', color: 'var(--color-success)' },
    PROCESSING: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)' },
    PENDING: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)' },
    QUEUED: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)' },
    PARTIAL_SUCCESS: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)' },
    FAILED: { bg: 'var(--color-danger-dim)', color: 'var(--color-danger)' },
  };
  const cfg = statusConfig[normalized] || { bg: 'var(--bg-surface-2)', color: 'var(--text-secondary)' };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: 'var(--radius-full)',
        padding: '4px 10px',
        backgroundColor: cfg.bg,
        color: cfg.color,
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: 600,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
      }}
    >
      {normalized.replace(/_/g, ' ')}
    </span>
  );
}

const columns: ColumnDef<StructuringRun>[] = [
  {
    accessorKey: 'run_label',
    header: 'Run Label',
    cell: ({ row }) => (
      <span style={{ fontFamily: 'var(--font-body)', fontWeight: 600, color: 'var(--text-primary)' }}>
        {row.original.run_label || `Run ${row.original.id.slice(0, 8)}`}
      </span>
    ),
  },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ getValue }) => statusBadge(String(getValue() || 'PENDING')),
  },
  {
    accessorKey: 'total_documents',
    header: 'Documents',
    cell: ({ getValue }) => <span>{Number(getValue() || 0)}</span>,
  },
  {
    accessorKey: 'total_line_items_found',
    header: 'Line Items Found',
    cell: ({ getValue }) => <span>{Number(getValue() || 0)}</span>,
  },
  {
    accessorKey: 'created_at',
    header: 'Created At',
    cell: ({ getValue }) => <span>{formatDate((getValue() as string | null) ?? null)}</span>,
  },
  {
    id: 'actions',
    header: 'Actions',
    cell: ({ row }) => (
      <Link to={`/structuring/${row.original.id}`} onClick={(e) => e.stopPropagation()}>
        <Button variant="secondary" style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}>
          View
        </Button>
      </Link>
    ),
  },
];

export default function StructuringRunsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['structuringRuns', { page: 1, page_size: 50 }],
    queryFn: () => listStructuringRuns({ page: 1, page_size: 20 }),
  });

  return (
    <div className="animate-fadeIn">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-5)' }}>
        <div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', margin: 0, color: 'var(--text-primary)' }}>Contract Structuring</h1>
          <p style={{ color: 'var(--text-muted)', marginTop: '6px', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
            View previous structuring runs and start a new extraction flow.
          </p>
        </div>
        <Link to="/structuring/new">
          <Button>New Run</Button>
        </Link>
      </div>

      {isLoading ? (
        <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <LoadingSpinner size={30} />
        </Card>
      ) : !data?.data.length ? (
        <Card style={{ padding: 0 }}>
          <EmptyState
            title="No structuring runs yet"
            description="1. Upload contract documents → 2. Run structuring → 3. Review and export"
          />
        </Card>
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <DataTable data={data.data} columns={columns} getRowId={(row) => row.id} />
        </Card>
      )}
    </div>
  );
}
