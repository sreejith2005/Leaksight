import React from 'react';
import { useQuery } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { getRevalidationDoc, getSubject, listAlerts, type AlertResponse } from '../../api/revalidation';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { DataTable } from '../../components/ui/DataTable';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { SectionHeader } from '../../components/ui/SectionHeader';
import { formatDateValue } from '../../components/leakage/leakageDetailUtils';

const PAGE_SIZE = 20;

function getAlertBadgeTone(alertType: string) {
  if (alertType === 'EXPIRED') return { color: 'var(--color-danger)', background: 'var(--color-danger-dim)' };
  if (alertType === 'EXPIRING_SOON' || alertType === 'REVALIDATION_REQUESTED') return { color: 'var(--color-warning)', background: 'var(--color-warning-dim)' };
  return { color: 'var(--text-secondary)', background: 'var(--bg-surface-2)' };
}

function truncateMessage(message: string) {
  return message.length <= 80 ? message : `${message.slice(0, 77)}...`;
}

async function fetchAlertContext(alerts: AlertResponse[]) {
  const subjectNames = new Map<string, string>();
  const entries = await Promise.all(alerts.map(async (alert) => {
    const revalidationDoc = await getRevalidationDoc(alert.revalidation_doc_id);
    let subjectName = subjectNames.get(revalidationDoc.subject_id);
    if (!subjectName) {
      const subject = await getSubject(revalidationDoc.subject_id);
      subjectName = subject.name;
      subjectNames.set(revalidationDoc.subject_id, subjectName);
    }
    return [alert.id, { subjectName, documentName: revalidationDoc.display_name }] as const;
  }));
  return Object.fromEntries(entries);
}

export default function AlertsPage() {
  const [page, setPage] = React.useState(1);
  const alertsQuery = useQuery({
    queryKey: ['revalidationAlerts', { page, page_size: PAGE_SIZE }],
    queryFn: () => listAlerts({ page, page_size: PAGE_SIZE }),
  });
  const alerts = alertsQuery.data?.data ?? [];
  const alertContextQuery = useQuery({
    queryKey: ['revalidationAlertContext', alerts.map((alert) => alert.revalidation_doc_id)],
    queryFn: () => fetchAlertContext(alerts),
    enabled: alerts.length > 0,
  });
  const alertContext = alertContextQuery.data ?? {};
  const columns: ColumnDef<AlertResponse>[] = [
    { id: 'subject', header: 'Subject', cell: ({ row }) => alertContext[row.original.id]?.subjectName ?? '—' },
    { id: 'document', header: 'Document', cell: ({ row }) => alertContext[row.original.id]?.documentName ?? '—' },
    {
      accessorKey: 'alert_type',
      header: 'Alert Type',
      cell: ({ row }) => {
        const tone = getAlertBadgeTone(row.original.alert_type);
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', borderRadius: 'var(--radius-full)', padding: '4px 10px', backgroundColor: tone.background, color: tone.color, fontSize: 'var(--text-xs)', fontWeight: 700, letterSpacing: '0.04em' }}>
            {row.original.alert_type.replace(/_/g, ' ')}
          </span>
        );
      },
    },
    {
      accessorKey: 'message',
      header: 'Message',
      cell: ({ row }) => (
        <span title={row.original.message} style={{ display: 'inline-block', maxWidth: 460, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {truncateMessage(row.original.message)}
        </span>
      ),
    },
    { accessorKey: 'created_at', header: 'Date', cell: ({ row }) => formatDateValue(row.original.created_at) },
  ];

  if (alertsQuery.isLoading) return <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-12)' }}><LoadingSpinner size={32} /></Card>;
  if (alertsQuery.error) return <ErrorMessage message={alertsQuery.error.message} />;

  const pagination = alertsQuery.data?.pagination;

  return (
    <div className="animate-fadeIn" style={{ display: 'grid', gap: 'var(--space-6)' }}>
      <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
        <SectionHeader>Document Revalidation</SectionHeader>
        <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
          Review paginated compliance alerts across all tracked subjects.
        </p>
      </div>

      {!alerts.length ? (
        <Card style={{ padding: 0 }}>
          <EmptyState
            title="No alerts"
            description="No alerts"
            icon={(
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" strokeWidth="1.8">
                <circle cx="12" cy="12" r="9" />
                <path d="m8 12 2.5 2.5 5.5-5.5" />
              </svg>
            )}
          />
        </Card>
      ) : alertContextQuery.isLoading ? (
        <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-12)' }}><LoadingSpinner size={28} /></Card>
      ) : alertContextQuery.error ? (
        <ErrorMessage message={alertContextQuery.error.message} />
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <DataTable data={alerts} columns={columns} getRowId={(row) => row.id} />
        </Card>
      )}

      {pagination && pagination.total_pages > 1 ? (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>Page {pagination.page} of {pagination.total_pages}</span>
          <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
            <Button variant="secondary" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={pagination.page <= 1}>Previous</Button>
            <Button variant="secondary" onClick={() => setPage((current) => Math.min(pagination.total_pages, current + 1))} disabled={pagination.page >= pagination.total_pages}>Next</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
