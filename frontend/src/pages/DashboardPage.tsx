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
    enabled: !!latestRun && (latestRun.status === 'COMPLETE' || latestRun.status === 'PARTIAL_SUCCESS'),
  });

  /* ── CFO summary for latest complete run ─────────────────────── */
  const { data: cfoData } = useQuery({
    queryKey: ['cfoSummary', latestRun?.run_id],
    queryFn: () => getRunSummary(latestRun!.run_id),
    enabled: !!latestRun && (latestRun.status === 'COMPLETE' || latestRun.status === 'PARTIAL_SUCCESS'),
  });

  const loading = runsLoading || summaryLoading;

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '120px 0' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  if (!latestRun) {
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
          Dashboard
        </h1>
        <p style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
          color: 'var(--text-muted)',
          marginBottom: 'var(--space-8)',
        }}>
          Welcome to LeakSight — your financial leakage detection engine
        </p>

        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 'var(--space-6)',
            }}
          >
            Get Started in Three Steps
          </h3>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
              gap: 'var(--space-4)',
            }}
          >
            {/* Step 1 */}
            <div
              style={{
                padding: 'var(--space-6)',
                backgroundColor: 'var(--bg-base)',
                borderRadius: 'var(--radius-md)',
                borderLeft: '3px solid var(--accent)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'var(--accent-dim)',
                    color: 'var(--accent)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: 'var(--font-display)',
                    fontWeight: 700,
                    fontSize: 'var(--text-sm)',
                    flexShrink: 0,
                  }}
                >
                  1
                </div>
                <span
                  style={{
                    fontFamily: 'var(--font-body)',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    fontSize: 'var(--text-sm)',
                  }}
                >
                  Upload Documents
                </span>
              </div>
              <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
                Upload your contracts (Excel/PDF) and invoices (Excel/CSV). These form the commercial and financial truth that LeakSight compares.
              </p>
            </div>

            {/* Step 2 */}
            <div
              style={{
                padding: 'var(--space-6)',
                backgroundColor: 'var(--bg-base)',
                borderRadius: 'var(--radius-md)',
                borderLeft: '3px solid var(--accent)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'var(--accent-dim)',
                    color: 'var(--accent)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: 'var(--font-display)',
                    fontWeight: 700,
                    fontSize: 'var(--text-sm)',
                    flexShrink: 0,
                  }}
                >
                  2
                </div>
                <span
                  style={{
                    fontFamily: 'var(--font-body)',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    fontSize: 'var(--text-sm)',
                  }}
                >
                  Trigger Analysis
                </span>
              </div>
              <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
                Select your uploaded documents and trigger an analysis run. LeakSight will parse, normalize, match, and apply three deterministic rules.
              </p>
            </div>

            {/* Step 3 */}
            <div
              style={{
                padding: 'var(--space-6)',
                backgroundColor: 'var(--bg-base)',
                borderRadius: 'var(--radius-md)',
                borderLeft: '3px solid var(--accent)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'var(--accent-dim)',
                    color: 'var(--accent)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: 'var(--font-display)',
                    fontWeight: 700,
                    fontSize: 'var(--text-sm)',
                    flexShrink: 0,
                  }}
                >
                  3
                </div>
                <span
                  style={{
                    fontFamily: 'var(--font-body)',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    fontSize: 'var(--text-sm)',
                  }}
                >
                  Review Findings
                </span>
              </div>
              <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
                Review each flagged leakage finding with full evidence. Accept confirmed findings or reject false positives with notes. Generate CFO-ready reports.
              </p>
            </div>
          </div>

          <div style={{ marginTop: 'var(--space-6)', textAlign: 'center' }}>
            <button
              onClick={() => navigate('/upload')}
              style={{
                backgroundColor: 'var(--accent)',
                color: 'var(--text-inverse)',
                border: 'none',
                borderRadius: 'var(--radius-md)',
                padding: 'var(--space-3) var(--space-6)',
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-sm)',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'background-color 150ms ease',
              }}
              onMouseEnter={(e) => { (e.target as HTMLElement).style.backgroundColor = 'var(--accent-hover)'; }}
              onMouseLeave={(e) => { (e.target as HTMLElement).style.backgroundColor = 'var(--accent)'; }}
            >
              Start by Uploading Documents
            </button>
          </div>
        </Card>
      </div>
    );
  }

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
        Dashboard
      </h1>
      <p style={{
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-sm)',
        color: 'var(--text-muted)',
        marginBottom: 'var(--space-8)',
      }}>
        Latest analysis overview
      </p>

      {/* KPI cards row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-8)',
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
          <h3
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 'var(--space-5)',
            }}
          >
            Leakage by Type (accepted findings only)
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-4)' }}>
            {Object.entries(summaryData.by_type).map(([type, data]) => (
              <div
                key={type}
                style={{
                  padding: 'var(--space-5)',
                  backgroundColor: 'var(--bg-base)',
                  borderRadius: 'var(--radius-md)',
                  borderLeft: '3px solid var(--accent)',
                }}
              >
                <div
                  style={{
                    fontFamily: 'var(--font-body)',
                    fontSize: 'var(--text-xs)',
                    fontWeight: 600,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                    marginBottom: 'var(--space-2)',
                  }}
                >
                  {type.replace(/_/g, ' ')}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontSize: 'var(--text-xl)',
                    fontWeight: 700,
                    color: 'var(--text-primary)',
                  }}
                >
                  {formatCurrency(data.total_amount, summaryData.currency)}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-muted)',
                    marginTop: 'var(--space-1)',
                  }}
                >
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
          <h3
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 'var(--space-5)',
            }}
          >
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
                  padding: 'var(--space-3) var(--space-4)',
                  backgroundColor: 'var(--bg-base)',
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer',
                  transition: 'background-color 150ms ease',
                }}
                onClick={() => navigate(`/vendors/${vendor.vendor_id}`)}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--accent-dim)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--bg-base)';
                }}
              >
                <span style={{ fontFamily: 'var(--font-body)', color: 'var(--text-primary)', fontSize: 'var(--text-sm)', textTransform: 'capitalize' }}>
                  {vendor.vendor_name}
                </span>
                <div style={{ display: 'flex', gap: 'var(--space-6)', alignItems: 'center' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
                    {vendor.record_count} finding{vendor.record_count !== 1 ? 's' : ''}
                  </span>
                  <span style={{ fontFamily: 'var(--font-display)', color: 'var(--accent)', fontWeight: 600, fontSize: 'var(--text-sm)' }}>
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-5)' }}>
          <h3
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            Recent Runs
          </h3>
          <button
            onClick={() => navigate('/upload')}
            style={{
              background: 'none',
              border: 'none',
              fontFamily: 'var(--font-body)',
              color: 'var(--accent)',
              cursor: 'pointer',
              fontSize: 'var(--text-xs)',
              fontWeight: 500,
              transition: 'opacity 150ms ease',
            }}
            onMouseEnter={(e) => { (e.target as HTMLElement).style.opacity = '0.8'; }}
            onMouseLeave={(e) => { (e.target as HTMLElement).style.opacity = '1'; }}
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
                padding: 'var(--space-3) var(--space-4)',
                backgroundColor: 'var(--bg-base)',
                borderRadius: 'var(--radius-md)',
              }}
            >
              <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
                <StatusBadge status={run.status} />
                <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                  {run.run_id.slice(0, 8)}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 'var(--space-6)', alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
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
      <div
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-xs)',
          fontWeight: 600,
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 'var(--space-3)',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 'var(--text-2xl)',
          fontWeight: 700,
          color: highlight ? 'var(--accent)' : 'var(--text-primary)',
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </div>
    </Card>
  );
}
