import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import {
  analyzeBatch,
  analyzeDocument,
  listDocuments,
  type IntegrityComparisonStatus,
  type IntegrityListItem,
  type IntegrityRiskLevel,
} from '../../api/integrity';
import { RiskBadge } from '../../components/integrity/RiskBadge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { DataTable } from '../../components/ui/DataTable';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { useToast } from '../../context/ToastContext';

const PAGE_SIZE = 100;
const FILTER_OPTIONS: Array<{ label: string; value: '' | IntegrityRiskLevel }> = [
  { label: 'All', value: '' },
  { label: 'Low Risk', value: 'LOW' },
  { label: 'Medium Risk', value: 'MEDIUM' },
  { label: 'High Risk', value: 'HIGH' },
];

const COMPARISON_STATUS_STYLES: Record<
  IntegrityComparisonStatus,
  { color: string; background: string }
> = {
  NEW: { color: 'var(--color-info)', background: 'var(--color-info-dim)' },
  UNCHANGED: { color: 'var(--color-success)', background: 'var(--color-success-dim)' },
  MODIFIED: { color: 'var(--color-danger)', background: 'var(--color-danger-dim)' },
  INCONCLUSIVE: { color: 'var(--color-warning)', background: 'var(--color-warning-dim)' },
};

async function fetchAllDocuments(riskLevel?: IntegrityRiskLevel): Promise<IntegrityListItem[]> {
  const firstPage = await listDocuments(1, PAGE_SIZE, riskLevel);
  if (firstPage.total <= firstPage.items.length) {
    return firstPage.items;
  }

  const totalPages = Math.ceil(firstPage.total / PAGE_SIZE);
  const remainingPages = await Promise.all(
    Array.from({ length: totalPages - 1 }, (_, index) => listDocuments(index + 2, PAGE_SIZE, riskLevel)),
  );

  return [firstPage, ...remainingPages].flatMap((page) => page.items);
}

function formatDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  return new Date(value).toLocaleString();
}

function ComparisonStatusBadge({ status }: { status: IntegrityComparisonStatus | null }) {
  if (!status) {
    return <span style={{ color: 'var(--text-secondary)' }}>Not analyzed</span>;
  }

  const config = COMPARISON_STATUS_STYLES[status];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '4px 10px',
        borderRadius: 'var(--radius-full)',
        backgroundColor: config.background,
        color: config.color,
        fontSize: 'var(--text-xs)',
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
      }}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}

export default function IntegrityPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const [riskFilter, setRiskFilter] = React.useState<'' | IntegrityRiskLevel>('');

  const documentsQuery = useQuery({
    queryKey: ['integrityDocuments', { riskLevel: riskFilter || 'ALL' }],
    queryFn: () => fetchAllDocuments(riskFilter || undefined),
    refetchInterval: 30000,
  });

  const analyzeOneMutation = useMutation({
    mutationFn: (documentId: string) => analyzeDocument(documentId),
    onSuccess: () => {
      addToast('success', 'Integrity analysis queued');
      queryClient.invalidateQueries({ queryKey: ['integrityDocuments'] });
    },
    onError: (error: Error) => addToast('error', `Failed to queue analysis: ${error.message}`),
  });

  const analyzeAllMutation = useMutation({
    mutationFn: (documentIds: string[]) => analyzeBatch(documentIds),
    onSuccess: (response) => {
      addToast('success', `${response.queued} document analyses queued`);
      queryClient.invalidateQueries({ queryKey: ['integrityDocuments'] });
    },
    onError: (error: Error) => addToast('error', `Failed to queue batch analysis: ${error.message}`),
  });

  const columns = React.useMemo<ColumnDef<IntegrityListItem>[]>(
    () => [
      {
        accessorKey: 'filename',
        header: 'Filename',
        cell: ({ row }) => (
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            {row.original.filename}
          </span>
        ),
      },
      {
        accessorKey: 'doc_type',
        header: 'Document Type',
      },
      {
        id: 'risk_score',
        header: 'Risk Score',
        cell: ({ row }) => (
          <RiskBadge
            risk_score={row.original.risk_score}
            risk_level={row.original.risk_level}
          />
        ),
      },
      {
        accessorKey: 'comparison_status',
        header: 'Comparison Status',
        cell: ({ row }) => <ComparisonStatusBadge status={row.original.comparison_status} />,
      },
      {
        accessorKey: 'analyzed_at',
        header: 'Analyzed At',
        cell: ({ row }) => formatDate(row.original.analyzed_at),
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => {
          const isPending = analyzeOneMutation.isPending && analyzeOneMutation.variables === row.original.document_id;

          return (
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <Button
                variant="secondary"
                onClick={(event) => {
                  event.stopPropagation();
                  navigate(`/integrity/${row.original.document_id}`);
                }}
                style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}
              >
                View Report
              </Button>
              <Button
                onClick={(event) => {
                  event.stopPropagation();
                  analyzeOneMutation.mutate(row.original.document_id);
                }}
                loading={isPending}
                disabled={isPending}
                style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}
              >
                Analyze
              </Button>
            </div>
          );
        },
      },
    ],
    [analyzeOneMutation.isPending, analyzeOneMutation.variables, navigate],
  );

  const documents = documentsQuery.data || [];

  return (
    <div className="animate-fadeIn">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-5)',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'var(--text-3xl)',
              margin: 0,
              color: 'var(--text-primary)',
            }}
          >
            Document Integrity
          </h1>
          <p
            style={{
              color: 'var(--text-muted)',
              marginTop: '6px',
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-sm)',
            }}
          >
            Review document tamper risk, compare versions, and queue fresh integrity analysis.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
          <label
            style={{
              display: 'grid',
              gap: '6px',
              color: 'var(--text-secondary)',
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            Filter
            <select
              value={riskFilter}
              onChange={(event) => setRiskFilter(event.target.value as '' | IntegrityRiskLevel)}
              style={{
                minWidth: 180,
                backgroundColor: 'var(--bg-surface-1)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-md)',
                padding: '10px 12px',
              }}
            >
              {FILTER_OPTIONS.map((option) => (
                <option key={option.label} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <Button
            onClick={() => analyzeAllMutation.mutate(documents.map((documentItem) => documentItem.document_id))}
            loading={analyzeAllMutation.isPending}
            disabled={!documents.length || analyzeAllMutation.isPending}
          >
            Analyze All
          </Button>
        </div>
      </div>

      {documentsQuery.isLoading ? (
        <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <LoadingSpinner size={30} />
        </Card>
      ) : documentsQuery.error ? (
        <ErrorMessage message={documentsQuery.error.message} />
      ) : !documents.length ? (
        <Card style={{ padding: 0 }}>
          <EmptyState
            title="No documents available"
            description="Upload documents first, then integrity analysis results will appear here."
          />
        </Card>
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <DataTable
            data={documents}
            columns={columns}
            getRowId={(row) => row.document_id}
          />
        </Card>
      )}
    </div>
  );
}
