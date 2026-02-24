import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { listRuns } from '../api/endpoints/ingest';
import { getLeakageSummary } from '../api/endpoints/leakage';
import { getRunSummary } from '../api/endpoints/reports';
import { Card } from '../components/ui/Card';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { useNavigate } from 'react-router-dom';

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export default function DashboardPage() {
  const navigate = useNavigate();

  /* ── Fetch recent runs ───────────────────────────────────────── */
  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['runs', { page: 1, page_size: 5 }],
    queryFn: () => listRuns({ page: 1, page_size: 5 }),
  });

  const latestRun = runsData?.data?.[0];

  /* ── Fetch leakage summary (accepted findings only) ──────────── */
  const { data: summaryData, isLoading: summaryLoading } = useQuery({
    queryKey: ['leakageSummary', latestRun?.run_id],
    queryFn: () => getLeakageSummary(latestRun!.run_id, 'ACCEPTED'),
    enabled: !!latestRun && latestRun.status === 'COMPLETE',
  });

  /* ── CFO summary for latest complete run ─────────────────────── */
  const { data: cfoData } = useQuery({
    queryKey: ['cfoSummary', latestRun?.run_id],
    queryFn: () => getRunSummary(latestRun!.run_id),
    enabled: !!latestRun && latestRun.status === 'COMPLETE',
  });

  const loading = runsLoading || summaryLoading;

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  if (!latestRun) {
    return (
      <EmptyState
        title="No analysis runs"
        description="Upload documents and trigger an analysis run to see your dashboard."
        actionLabel="Go to Upload"
        onAction={() => navigate('/upload')}
      />
    );
  }

  return (
    <div>
      <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)', marginBottom: 'var(--space-6)' }}>
        Dashboard
      </h1>

      {/* KPI cards row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-6)',
        }}
      >
        <KPICard
          label="Total Leakage (accepted findings only)"
          value={summaryData ? formatCurrency(summaryData.total_leakage_amount, summaryData.currency) : '—'}
          highlight
        />
        <KPICard
          label="Pending Review"
          value={cfoData?.summary.pending_review_count?.toString() ?? '—'}
        />
        <KPICard
          label="Pending FX Rate"
          value={cfoData?.summary.pending_fx_rate_count?.toString() ?? '—'}
        />
        <KPICard
          label="Avg Confidence"
          value={summaryData?.average_confidence != null ? `${(summaryData.average_confidence * 100).toFixed(1)}%` : '—'}
        />
      </div>

      {/* By type breakdown */}
      {summaryData && Object.keys(summaryData.by_type).length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
            Leakage by Type (accepted findings only)
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--space-3)' }}>
            {Object.entries(summaryData.by_type).map(([type, data]) => (
              <div
                key={type}
                style={{
                  padding: 'var(--space-4)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-md)',
                  borderLeft: '3px solid var(--color-orange)',
                }}
              >
                <div style={{ fontSize: '12px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-1)' }}>
                  {type.replace(/_/g, ' ')}
                </div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--color-white)' }}>
                  {formatCurrency(data.total_amount, summaryData.currency)}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--color-muted)', marginTop: 'var(--space-1)' }}>
                  {data.count} finding{data.count !== 1 ? 's' : ''}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Top vendors */}
      {summaryData && summaryData.by_vendor.length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
            Top Vendors by Leakage (accepted findings only)
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {summaryData.by_vendor.slice(0, 5).map((vendor) => (
              <div
                key={vendor.vendor_id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: 'var(--space-3)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                }}
                onClick={() => navigate(`/vendors/${vendor.vendor_id}`)}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'rgba(252, 163, 17, 0.06)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--color-black)';
                }}
              >
                <span style={{ color: 'var(--color-grey)', fontSize: '14px' }}>{vendor.vendor_name}</span>
                <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
                  <span style={{ color: 'var(--color-muted)', fontSize: '12px' }}>
                    {vendor.record_count} finding{vendor.record_count !== 1 ? 's' : ''}
                  </span>
                  <span style={{ color: 'var(--color-orange)', fontWeight: 600, fontSize: '14px' }}>
                    {formatCurrency(vendor.total_amount, summaryData.currency)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Recent runs */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)' }}>
            Recent Runs
          </h3>
          <button
            onClick={() => navigate('/upload')}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-orange)',
              cursor: 'pointer',
              fontSize: '13px',
            }}
          >
            View all →
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {runsData?.data.map((run) => (
            <div
              key={run.run_id}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: 'var(--space-3)',
                backgroundColor: 'var(--color-black)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '14px',
              }}
            >
              <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
                <StatusBadge status={run.status} />
                <span style={{ color: 'var(--color-grey)', fontFamily: 'monospace', fontSize: '12px' }}>
                  {run.run_id.slice(0, 8)}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center', fontSize: '12px', color: 'var(--color-muted)' }}>
                <span>{run.total_documents} docs</span>
                <span>{run.leakage_record_count} findings</span>
                <span>{run.created_at ? new Date(run.created_at).toLocaleDateString() : '—'}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── KPI Card ──────────────────────────────────────────────────── */

function KPICard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <Card highlight={highlight}>
      <div style={{ fontSize: '12px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-2)' }}>
        {label}
      </div>
      <div style={{ fontSize: '24px', fontWeight: 700, color: highlight ? 'var(--color-orange)' : 'var(--color-white)' }}>
        {value}
      </div>
    </Card>
  );
}
