import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  getRunResults,
  getRunStatus,
  listUploadedDocuments,
  triggerErpJsonExport,
  triggerExcelExport,
  triggerLeakSightImport,
} from '../../api/structuring';
import { Card } from '../../components/ui/Card';
import { MetricDisplay } from '../../components/ui/MetricDisplay';
import { Button } from '../../components/ui/Button';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { EmptyState } from '../../components/ui/EmptyState';
import { useToast } from '../../context/ToastContext';
import { Modal } from '../../components/ui/Modal';

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

function ProgressBar({ percentage, status }: { percentage: number; status: string }) {
  const color = status === 'FAILED'
    ? 'var(--color-danger)'
    : status === 'COMPLETE'
      ? 'var(--color-success)'
      : 'var(--color-warning)';

  return (
    <div
      style={{
        width: '100%',
        height: 8,
        backgroundColor: 'var(--bg-surface-3)',
        borderRadius: 'var(--radius-full)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${Math.max(0, Math.min(100, percentage))}%`,
          height: '100%',
          backgroundColor: color,
          transition: 'width 500ms ease',
        }}
      />
    </div>
  );
}

export default function StructuringRunDetailPage() {
  const { addToast } = useToast();
  const { runId = '' } = useParams();
  const [confirmImportOpen, setConfirmImportOpen] = React.useState(false);

  const statusQuery = useQuery({
    queryKey: ['structuringRunStatus', runId],
    queryFn: () => getRunStatus(runId),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = String(q.state.data?.status || '').toUpperCase();
      if (s === 'COMPLETE' || s === 'PARTIAL_SUCCESS' || s === 'FAILED') return false;
      return 3000;
    },
  });

  const resultsQuery = useQuery({
    queryKey: ['structuringRunResults', runId],
    queryFn: () => getRunResults(runId),
    enabled: !!runId,
    refetchInterval: (q) => {
      const runStatusValue = String(statusQuery.data?.status || '').toUpperCase();
      const documents = q.state.data?.documents || [];
      const allDocumentsTerminal = documents.length > 0 && documents.every((doc) => {
        const taskStatus = String(doc.task_status || '').toUpperCase();
        return taskStatus === 'COMPLETE' || taskStatus === 'FAILED';
      });
      if (
        (runStatusValue === 'COMPLETE' || runStatusValue === 'PARTIAL_SUCCESS' || runStatusValue === 'FAILED')
        && allDocumentsTerminal
      ) {
        return false;
      }
      return 3000;
    },
  });

  const docsQuery = useQuery({
    queryKey: ['uploadedDocuments', { page: 1, page_size: 200 }],
    queryFn: () => listUploadedDocuments({ page: 1, page_size: 200 }),
    enabled: !!runId,
  });

  const documentNameMap = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const doc of docsQuery.data?.data || []) {
      map[doc.document_id] = doc.filename;
    }
    return map;
  }, [docsQuery.data]);

  const exportExcel = useMutation({
    mutationFn: () => triggerExcelExport(runId),
    onSuccess: () => addToast('success', 'Excel export queued'),
    onError: (err: Error) => addToast('error', `Excel export failed: ${err.message}`),
  });

  const exportErp = useMutation({
    mutationFn: () => triggerErpJsonExport(runId),
    onSuccess: () => addToast('success', 'ERP JSON export queued'),
    onError: (err: Error) => addToast('error', `ERP JSON export failed: ${err.message}`),
  });

  const exportLs = useMutation({
    mutationFn: () => triggerLeakSightImport(runId),
    onSuccess: () => {
      addToast('success', 'LeakSight import export queued');
      setConfirmImportOpen(false);
    },
    onError: (err: Error) => addToast('error', `LeakSight export failed: ${err.message}`),
  });

  const runStatus = String(statusQuery.data?.status || 'PENDING').toUpperCase();
  const isTerminal = runStatus === 'COMPLETE' || runStatus === 'PARTIAL_SUCCESS' || runStatus === 'FAILED';

  const totals = React.useMemo(() => {
    const docs = resultsQuery.data?.documents || [];
    let lineItems = 0;
    let clauses = 0;
    let needsReview = 0;
    for (const doc of docs) {
      lineItems += doc.line_items.length;
      clauses += doc.clauses.length;
      needsReview += doc.line_items.filter((item) => item.needs_review).length;
    }
    return {
      totalDocuments: statusQuery.data?.total_documents ?? docs.length,
      lineItems,
      clauses,
      needsReview,
    };
  }, [resultsQuery.data, statusQuery.data]);

  return (
    <div className="animate-fadeIn">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', margin: 0, color: 'var(--text-primary)' }}>
            {resultsQuery.data?.run.run_label || 'Structuring Run'}
          </h1>
          <p style={{ marginTop: '6px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
            Run ID: {runId}
          </p>
        </div>
        {statusBadge(runStatus)}
      </div>

      <Card style={{ marginTop: 'var(--space-4)' }}>
        {(statusQuery.isLoading || resultsQuery.isLoading) ? (
          <LoadingSpinner size={28} />
        ) : (
          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
            <ProgressBar percentage={statusQuery.data?.progress_percentage ?? 0} status={runStatus} />
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              Processed documents: {statusQuery.data?.processed_documents ?? 0}/{statusQuery.data?.total_documents ?? 0}
            </div>
          </div>
        )}
      </Card>

      {isTerminal && (
        <Card style={{ marginTop: 'var(--space-4)' }}>
          <div style={{ display: 'grid', gap: 'var(--space-4)', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <MetricDisplay value={totals.totalDocuments} label="Total Documents" />
            <MetricDisplay value={totals.lineItems} label="Line Items Found" />
            <MetricDisplay value={totals.clauses} label="Clauses Found" />
            <MetricDisplay value={totals.needsReview} label="Items Needing Review" />
          </div>
        </Card>
      )}

      {isTerminal && (
        <div style={{ marginTop: 'var(--space-4)', display: 'grid', gap: 'var(--space-3)' }}>
          {!resultsQuery.data?.documents.length ? (
            <Card style={{ padding: 0 }}>
              <EmptyState title="No document results available" description="This run completed without document-level extraction output." />
            </Card>
          ) : (
            resultsQuery.data.documents.map((doc) => (
              <Card key={doc.document_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-4)' }}>
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                    {documentNameMap[doc.document_id] || doc.document_id}
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
                    {statusBadge(doc.task_status)}
                    <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                      {doc.line_items.length} line items
                    </span>
                    <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                      {doc.clauses.length} clauses
                    </span>
                  </div>
                  {doc.task_status === 'FAILED' && doc.error_message && (
                    <p style={{ marginTop: '8px', color: 'var(--color-danger)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
                      {doc.error_message}
                    </p>
                  )}
                </div>
                <Link to={`/structuring/${runId}/contract/${doc.document_id}`}>
                  <Button variant="secondary">Review</Button>
                </Link>
              </Card>
            ))
          )}
        </div>
      )}

      {isTerminal && (
        <Card style={{ marginTop: 'var(--space-5)', display: 'grid', gap: 'var(--space-3)' }}>
          <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
            Export
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            <Button onClick={() => exportExcel.mutate()} disabled={exportExcel.isPending} loading={exportExcel.isPending}>
              Download Excel
            </Button>
            <Button variant="secondary" onClick={() => exportErp.mutate()} disabled={exportErp.isPending} loading={exportErp.isPending}>
              Export ERP JSON
            </Button>
            <Button variant="secondary" onClick={() => setConfirmImportOpen(true)} disabled={exportLs.isPending}>
              Send to LeakSight
            </Button>
          </div>
        </Card>
      )}

      <Modal open={confirmImportOpen} onClose={() => setConfirmImportOpen(false)} title="Confirm LeakSight Import">
        <p style={{ marginTop: 0, marginBottom: 'var(--space-5)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          This will write confirmed line items to the LeakSight contract database. Continue?
        </p>
        <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={() => setConfirmImportOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => exportLs.mutate()} loading={exportLs.isPending}>
            Continue
          </Button>
        </div>
      </Modal>
    </div>
  );
}
