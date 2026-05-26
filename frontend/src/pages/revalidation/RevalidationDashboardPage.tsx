import React from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getDashboard,
  getRevalidationDoc,
  getSubject,
  triggerExpiryCheck,
  type AlertResponse,
} from '../../api/revalidation';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { GiltDivider } from '../../components/ui/GiltDivider';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { MetricDisplay } from '../../components/ui/MetricDisplay';
import { SectionHeader } from '../../components/ui/SectionHeader';
import { useToast } from '../../context/ToastContext';
import { formatDateValue } from '../../components/leakage/leakageDetailUtils';

function getAlertColor(alertType: string): string {
  if (alertType === 'EXPIRED') {
    return 'var(--color-danger)';
  }

  if (alertType === 'EXPIRING_SOON' || alertType === 'REVALIDATION_REQUESTED') {
    return 'var(--color-warning)';
  }

  return 'var(--text-secondary)';
}

function formatAlertType(alertType: string): string {
  return alertType.replace(/_/g, ' ');
}

async function fetchAlertContext(alerts: AlertResponse[]) {
  const subjectNames = new Map<string, string>();
  const entries = await Promise.all(
    alerts.map(async (alert) => {
      const revalidationDoc = await getRevalidationDoc(alert.revalidation_doc_id);
      let subjectName = subjectNames.get(revalidationDoc.subject_id);

      if (!subjectName) {
        const subject = await getSubject(revalidationDoc.subject_id);
        subjectName = subject.name;
        subjectNames.set(revalidationDoc.subject_id, subjectName);
      }

      return [
        alert.id,
        {
          subjectName,
          documentName: revalidationDoc.display_name,
        },
      ] as const;
    }),
  );

  return Object.fromEntries(entries);
}

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <Card>
      <MetricDisplay label={label} value={value} size="lg" color={color} />
    </Card>
  );
}

export default function RevalidationDashboardPage() {
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  const dashboardQuery = useQuery({
    queryKey: ['revalidationDashboard'],
    queryFn: getDashboard,
  });

  const recentAlerts = dashboardQuery.data?.recent_alerts ?? [];

  const recentAlertContextQuery = useQuery({
    queryKey: ['revalidationRecentAlertContext', recentAlerts.map((alert) => alert.revalidation_doc_id)],
    queryFn: () => fetchAlertContext(recentAlerts),
    enabled: recentAlerts.length > 0,
  });

  const triggerExpiryCheckMutation = useMutation({
    mutationFn: triggerExpiryCheck,
    onSuccess: async () => {
      addToast('success', 'Expiry check queued');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['revalidationDashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['revalidationAlerts'] }),
      ]);
    },
    onError: (error: Error) => {
      addToast('error', `Failed to queue expiry check: ${error.message}`);
    },
  });

  if (dashboardQuery.isLoading) {
    return (
      <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-12)' }}>
        <LoadingSpinner size={32} />
      </Card>
    );
  }

  if (dashboardQuery.error) {
    return <ErrorMessage message={dashboardQuery.error.message} />;
  }

  const dashboard = dashboardQuery.data;

  if (!dashboard) {
    return <ErrorMessage message="Dashboard data is unavailable." />;
  }

  const recentAlertContext = recentAlertContextQuery.data ?? {};

  return (
    <div className="animate-fadeIn" style={{ display: 'grid', gap: 'var(--space-6)' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: 'var(--space-4)',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <SectionHeader>Document Revalidation</SectionHeader>
          <p
            style={{
              color: 'var(--text-secondary)',
              fontSize: 'var(--text-sm)',
              lineHeight: 1.6,
              maxWidth: 640,
            }}
          >
            Track employee and vendor compliance documents, expiry status, and recent alert activity.
          </p>
        </div>
        <Button
          onClick={() => triggerExpiryCheckMutation.mutate()}
          loading={triggerExpiryCheckMutation.isPending}
          disabled={triggerExpiryCheckMutation.isPending}
        >
          Run Expiry Check
        </Button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 'var(--space-4)',
        }}
      >
        <MetricCard label="Employees Tracked" value={dashboard.employees_total} />
        <MetricCard label="Vendors Tracked" value={dashboard.vendors_total} />
        <MetricCard
          label="Expiring Soon"
          value={dashboard.docs_expiring_soon}
          color={dashboard.docs_expiring_soon > 0 ? 'var(--color-warning)' : undefined}
        />
        <MetricCard
          label="Expired"
          value={dashboard.docs_expired}
          color={dashboard.docs_expired > 0 ? 'var(--color-danger)' : undefined}
        />
      </div>

      <GiltDivider style={{ margin: 0 }} />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 'var(--space-4)',
        }}
      >
        <MetricCard label="Valid Documents" value={dashboard.docs_valid} color="var(--color-success)" />
        <MetricCard label="Pending Upload" value={dashboard.docs_pending_upload} color="var(--text-secondary)" />
        <MetricCard
          label="Missing Documents"
          value={dashboard.docs_missing}
          color={dashboard.docs_missing > 0 ? 'var(--color-warning)' : undefined}
        />
      </div>

      <GiltDivider style={{ margin: 0 }} />

      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--space-4)',
            padding: 'var(--space-6)',
            borderBottom: recentAlerts.length ? '1px solid var(--border-subtle)' : undefined,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <SectionHeader style={{ marginBottom: 'var(--space-2)' }}>Recent Alerts</SectionHeader>
            <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
              Last 10 document compliance alerts.
            </p>
          </div>
          <Link to="/revalidation/alerts">View All Alerts</Link>
        </div>

        {!recentAlerts.length ? (
          <EmptyState
            title="No alerts"
            description="No alerts — all documents are in compliance"
            icon={(
              <svg
                width="48"
                height="48"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--color-success)"
                strokeWidth="1.8"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="m8 12 2.5 2.5 5.5-5.5" />
              </svg>
            )}
          />
        ) : recentAlertContextQuery.isLoading ? (
          <LoadingSpinner size={28} />
        ) : recentAlertContextQuery.error ? (
          <div style={{ padding: 'var(--space-6)' }}>
            <ErrorMessage message={recentAlertContextQuery.error.message} />
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-sm)',
              }}
            >
              <thead>
                <tr>
                  {['Subject', 'Document', 'Alert Type', 'Date'].map((column) => (
                    <th
                      key={column}
                      style={{
                        padding: 'var(--space-3) var(--space-4)',
                        textAlign: 'left',
                        fontWeight: 600,
                        fontSize: 'var(--text-xs)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em',
                        color: 'var(--text-secondary)',
                        backgroundColor: 'var(--bg-surface-1)',
                        borderBottom: '1px solid var(--border-default)',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recentAlerts.map((alert, index) => (
                  <tr
                    key={alert.id}
                    style={{
                      backgroundColor: index % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-surface-2)',
                    }}
                  >
                    <td style={cellStyle}>{recentAlertContext[alert.id]?.subjectName ?? '—'}</td>
                    <td style={cellStyle}>{recentAlertContext[alert.id]?.documentName ?? '—'}</td>
                    <td style={cellStyle}>
                      <span style={{ color: getAlertColor(alert.alert_type), fontWeight: 700 }}>
                        {formatAlertType(alert.alert_type)}
                      </span>
                    </td>
                    <td style={cellStyle}>{formatDateValue(alert.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

const cellStyle: React.CSSProperties = {
  padding: 'var(--space-3) var(--space-4)',
  color: 'var(--text-primary)',
  borderBottom: '1px solid var(--border-subtle)',
  whiteSpace: 'nowrap',
  lineHeight: 1.6,
};
