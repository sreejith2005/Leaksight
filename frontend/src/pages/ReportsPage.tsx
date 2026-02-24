import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { listRuns } from '../api/endpoints/ingest';
import { getRunSummary, downloadEvidencePack, downloadExcelExport } from '../api/endpoints/reports';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { useToast } from '../context/ToastContext';
import type { CFOSummaryResponse } from '../types/api';

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(amount);
}

export default function ReportsPage() {
  const { addToast } = useToast();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  /* ── Completed runs list ─────────────────────────────────────── */
  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['runs', { page: 1, page_size: 20, status: 'COMPLETE' }],
    queryFn: () => listRuns({ page: 1, page_size: 20, status: 'COMPLETE' }),
  });

  /* ── CFO summary for selected run ───────────────────────────── */
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['cfoSummary', selectedRunId],
    queryFn: () => getRunSummary(selectedRunId!),
    enabled: !!selectedRunId,
  });

  /* ── Download mutations ──────────────────────────────────────── */
  const evidenceDownload = useMutation({
    mutationFn: (runId: string) => downloadEvidencePack(runId),
    onError: (err: Error) => addToast('error', `Download failed: ${err.message}`),
  });

  const excelDownload = useMutation({
    mutationFn: (runId: string) => downloadExcelExport(runId),
    onError: (err: Error) => addToast('error', `Download failed: ${err.message}`),
  });

  // Auto-select first completed run
  React.useEffect(() => {
    if (runsData?.data.length && !selectedRunId) {
      setSelectedRunId(runsData.data[0].run_id);
    }
  }, [runsData, selectedRunId]);

  if (runsLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  if (!runsData?.data.length) {
    return (
      <EmptyState
        title="No completed runs"
        description="Complete an analysis run to generate reports."
      />
    );
  }

  return (
    <div>
      <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)', marginBottom: 'var(--space-6)' }}>
        Reports
      </h1>

      {/* Run selector */}
      <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <label style={{ fontSize: '14px', color: 'var(--color-grey)' }}>Select Run:</label>
        <select
          value={selectedRunId ?? ''}
          onChange={(e) => setSelectedRunId(e.target.value)}
          style={{
            backgroundColor: 'var(--color-prussian-blue)',
            color: 'var(--color-grey)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-2) var(--space-3)',
            fontSize: '14px',
            outline: 'none',
            minWidth: 260,
          }}
        >
          {runsData.data.map((run) => (
            <option key={run.run_id} value={run.run_id}>
              {run.run_id.slice(0, 8)} — {run.created_at ? new Date(run.created_at).toLocaleDateString() : 'Unknown'} ({run.leakage_record_count} findings)
            </option>
          ))}
        </select>
      </div>

      {/* Download actions */}
      <div style={{ display: 'flex', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <Button
          onClick={() => selectedRunId && evidenceDownload.mutate(selectedRunId)}
          loading={evidenceDownload.isPending}
          disabled={!selectedRunId}
          variant="secondary"
        >
          📄 Download Evidence Pack (PDF)
        </Button>
        <Button
          onClick={() => selectedRunId && excelDownload.mutate(selectedRunId)}
          loading={excelDownload.isPending}
          disabled={!selectedRunId}
          variant="secondary"
        >
          📊 Download Excel Export
        </Button>
      </div>

      {/* CFO Summary */}
      {summaryLoading ? (
        <LoadingSpinner size={32} />
      ) : summary ? (
        <CFOSummaryView summary={summary} />
      ) : null}
    </div>
  );
}

/* ── CFO Summary component ─────────────────────────────────────── */

function CFOSummaryView({ summary }: { summary: CFOSummaryResponse }) {
  const s = summary.summary;

  return (
    <div>
      {/* Status row */}
      <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <StatusBadge status={summary.run_status} />
        <span style={{ fontSize: '12px', color: 'var(--color-muted)' }}>
          Generated {new Date(summary.generated_at).toLocaleString()}
        </span>
      </div>

      {summary.partial_success_notes && (
        <Card
          style={{
            marginBottom: 'var(--space-4)',
            borderLeft: '4px solid var(--color-warning)',
          }}
        >
          <span style={{ color: 'var(--color-warning)', fontSize: '14px' }}>
            ⚠ {summary.partial_success_notes}
          </span>
        </Card>
      )}

      {/* KPI row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-6)',
        }}
      >
        <Card highlight>
          <div style={{ fontSize: '12px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-2)' }}>
            Total Leakage (accepted findings only)
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-orange)' }}>
            {formatCurrency(s.total_leakage, s.currency)}
          </div>
        </Card>
        <Card>
          <div style={{ fontSize: '12px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-2)' }}>
            Pending Review
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)' }}>
            {s.pending_review_count}
          </div>
        </Card>
        <Card>
          <div style={{ fontSize: '12px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-2)' }}>
            Pending FX Rate
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-warning)' }}>
            {s.pending_fx_rate_count}
          </div>
        </Card>
      </div>

      {/* Top vendors */}
      {s.top_vendors.length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
            Top Vendors
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {s.top_vendors.map((v, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: 'var(--space-3)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <span style={{ color: 'var(--color-grey)', fontSize: '14px' }}>{v.vendor_name}</span>
                <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', color: 'var(--color-muted)' }}>{v.record_count} findings</span>
                  <span style={{ color: 'var(--color-orange)', fontWeight: 600, fontSize: '14px' }}>
                    {formatCurrency(v.leakage_amount, s.currency)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* By Rule */}
      {Object.keys(s.by_rule).length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
            Breakdown by Rule
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--space-3)' }}>
            {Object.entries(s.by_rule).map(([rule, data]) => (
              <div
                key={rule}
                style={{
                  padding: 'var(--space-4)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-md)',
                  borderLeft: '3px solid var(--color-orange)',
                }}
              >
                <div style={{ fontSize: '12px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-1)' }}>
                  {rule.replace(/_/g, ' ')}
                </div>
                <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--color-white)' }}>
                  {formatCurrency(data.amount, s.currency)}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--color-muted)' }}>{data.count} findings</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Confidence bands */}
      <Card>
        <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
          Confidence Bands
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--space-3)' }}>
          {(['high', 'medium', 'low'] as const).map((band) => {
            const colors = {
              high: 'var(--color-success)',
              medium: 'var(--color-warning)',
              low: 'var(--color-error)',
            };
            return (
              <div
                key={band}
                style={{
                  padding: 'var(--space-4)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-md)',
                  borderTop: `3px solid ${colors[band]}`,
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: '11px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-2)' }}>
                  {band}
                </div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--color-white)' }}>
                  {s.confidence_bands[band].count}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--color-muted)' }}>
                  {formatCurrency(s.confidence_bands[band].amount, s.currency)}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
