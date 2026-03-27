import React, { useState, useRef, useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { uploadDocument, triggerRun, getRunStatus, listRuns, listDocuments } from '../api/endpoints/ingest';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { useToast } from '../context/ToastContext';
import type { UploadResponse, RunStatus } from '../types/api';

const ACCEPTED_TYPES = ['.pdf', '.xlsx', '.xls', '.docx'];
const ACCEPTED_MIME = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];

const DOC_TYPES = ['INVOICE', 'CONTRACT', 'PURCHASE_ORDER'] as const;

export default function UploadPage() {
  const { addToast } = useToast();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedDocType, setSelectedDocType] = useState<string>(DOC_TYPES[0]);
  const [uploadedDocs, setUploadedDocs] = useState<UploadResponse[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const allDocsParsed = uploadedDocs.length > 0 && uploadedDocs.every((d) => d.parse_status === 'PARSED');

  /* ── Upload mutation ─────────────────────────────────────────── */
  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(file, selectedDocType),
    onSuccess: (data) => {
      setUploadedDocs((prev) => [...prev, data]);
      addToast('success', `Uploaded ${data.filename}`);
    },
    onError: (err: Error) => {
      addToast('error', `Upload failed: ${err.message}`);
    },
  });

  /* ── Trigger run mutation ────────────────────────────────────── */
  const triggerMutation = useMutation({
    mutationFn: () => {
      const ids = uploadedDocs.map((d) => d.document_id);
      return triggerRun(ids);
    },
    onSuccess: (data) => {
      setActiveRunId(data.run_id);
      setUploadedDocs([]);
      addToast('success', 'Analysis run started');
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
    onError: (err: Error) => {
      addToast('error', `Failed to start analysis: ${err.message}`);
    },
  });

  /* ── Poll active run status ──────────────────────────────────── */
  const { data: runStatus } = useQuery({
    queryKey: ['runStatus', activeRunId],
    queryFn: () => getRunStatus(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === 'COMPLETE' || status === 'FAILED' || status === 'PARTIAL_SUCCESS') return false;
      return 3000;
    },
  });

  React.useEffect(() => {
    if (runStatus && (runStatus.status === 'COMPLETE' || runStatus.status === 'FAILED' || runStatus.status === 'PARTIAL_SUCCESS')) {
      if (runStatus.status === 'COMPLETE') {
        addToast('success', `Analysis complete — ${runStatus.leakage_record_count} findings`);
      } else if (runStatus.status === 'PARTIAL_SUCCESS') {
        addToast('warning', `Analysis partially complete — ${runStatus.leakage_record_count} findings (some items need attention)`);
      } else {
        addToast('error', `Analysis failed: ${runStatus.error_summary ?? 'Unknown error'}`);
      }
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    }
  }, [runStatus?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Poll uploaded document parse statuses ───────────────────── */
  const { data: docsStatus } = useQuery({
    queryKey: ['documents', { page: 1, page_size: 200 }],
    queryFn: () => listDocuments({ page: 1, page_size: 200 }),
    enabled: uploadedDocs.length > 0,
    refetchInterval: allDocsParsed ? false : 2000,
  });

  React.useEffect(() => {
    if (!docsStatus?.data?.length || uploadedDocs.length === 0) return;

    const statusById = new Map(docsStatus.data.map((d) => [d.document_id, d.parse_status]));

    setUploadedDocs((prev) => {
      let changed = false;
      const next = prev.map((doc) => {
        const latestStatus = statusById.get(doc.document_id);
        if (!latestStatus || latestStatus === doc.parse_status) return doc;
        changed = true;
        return { ...doc, parse_status: latestStatus };
      });
      return changed ? next : prev;
    });
  }, [docsStatus, uploadedDocs.length]);

  /* ── Recent runs ─────────────────────────────────────────────── */
  const { data: recentRuns, isLoading: runsLoading } = useQuery({
    queryKey: ['runs', { page: 1, page_size: 5 }],
    queryFn: () => listRuns({ page: 1, page_size: 5 }),
  });

  /* ── Drag / drop handlers ────────────────────────────────────── */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      files.forEach((file) => {
        if (ACCEPTED_MIME.includes(file.type)) {
          uploadMutation.mutate(file);
        } else {
          addToast('warning', `Unsupported file type: ${file.name}`);
        }
      });
    },
    [uploadMutation, addToast],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      files.forEach((file) => uploadMutation.mutate(file));
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    [uploadMutation],
  );

  return (
    <div className="animate-fadeIn" style={{ maxWidth: 960, margin: '0 auto' }}>
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
        Upload Documents
      </h1>
      <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 'var(--space-8)' }}>
        Upload invoices, contracts, and purchase orders for analysis
      </p>

      {/* Document type selector */}
      <div style={{ marginBottom: 'var(--space-5)', display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
        <label style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Document Type:</label>
        <select
          value={selectedDocType}
          onChange={(e) => setSelectedDocType(e.target.value)}
          style={{
            backgroundColor: 'var(--bg-surface-1)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-2) var(--space-3)',
            fontFamily: 'var(--font-body)',
            fontSize: 'var(--text-sm)',
            outline: 'none',
          }}
        >
          {DOC_TYPES.map((dt) => (
            <option key={dt} value={dt}>
              {dt.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${isDragging ? 'var(--accent)' : 'var(--border-default)'}`,
          borderRadius: 'var(--radius-xl)',
          padding: '60px var(--space-8)',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: isDragging ? 'var(--accent-dim)' : 'transparent',
          transition: 'all 200ms ease',
          marginBottom: 'var(--space-8)',
        }}
      >
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke={isDragging ? 'var(--accent)' : 'var(--text-muted)'}
          strokeWidth="1.5"
          style={{ marginBottom: 'var(--space-4)', display: 'inline-block' }}
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-base)', color: 'var(--text-primary)', marginBottom: 'var(--space-2)' }}>
          {isDragging ? 'Drop files here' : 'Drag & drop files or click to browse'}
        </p>
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          Accepted: PDF, Excel (.xlsx/.xls), Word (.docx)
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(',')}
          onChange={handleFileSelect}
          multiple
          style={{ display: 'none' }}
        />
      </div>

      {/* Upload in progress */}
      {uploadMutation.isPending && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
          <LoadingSpinner size={20} />
          <span style={{ fontFamily: 'var(--font-body)', color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>Uploading...</span>
        </div>
      )}

      {/* Uploaded documents list */}
      {uploadedDocs.length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
            <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Pending Documents ({uploadedDocs.length})
            </h3>
            <Button
              onClick={() => triggerMutation.mutate()}
              loading={triggerMutation.isPending}
              disabled={uploadedDocs.length === 0 || !allDocsParsed}
            >
              Trigger Analysis Run
            </Button>
          </div>
          {!allDocsParsed && (
            <p style={{ marginBottom: 'var(--space-4)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', color: 'var(--color-warning)' }}>
              Documents are still being parsed. Trigger analysis after all selected files show PARSED.
            </p>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {uploadedDocs.map((doc) => (
              <div
                key={doc.document_id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: 'var(--space-3) var(--space-4)',
                  backgroundColor: 'var(--bg-base)',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <span style={{ fontFamily: 'var(--font-body)', color: 'var(--text-primary)', fontSize: 'var(--text-sm)' }}>{doc.filename}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>{doc.doc_type}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', color: doc.parse_status === 'PARSED' ? 'var(--color-success)' : 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
                    {doc.parse_status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Active run progress */}
      {activeRunId && runStatus && (
        <Card highlight={runStatus.status === 'COMPLETE'} style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
            <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Active Analysis Run
            </h3>
            <StatusBadge status={runStatus.status} />
          </div>
          <ProgressBar percentage={runStatus.progress_percentage} status={runStatus.status} />
          <div style={{ display: 'flex', gap: 'var(--space-6)', marginTop: 'var(--space-3)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            <span>Documents: {runStatus.processed_documents}/{runStatus.total_documents}</span>
            <span>Findings: {runStatus.leakage_record_count}</span>
          </div>
          {runStatus.status === 'COMPLETE' && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <Button variant="secondary" onClick={() => setActiveRunId(null)}>
                Dismiss
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* Recent runs */}
      <Card>
        <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-5)' }}>
          Recent Analysis Runs
        </h3>
        {runsLoading ? (
          <LoadingSpinner size={24} />
        ) : !recentRuns?.data.length ? (
          <EmptyState
            title="No runs yet"
            description="Upload documents and trigger an analysis run to get started."
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {recentRuns.data.map((run) => (
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
                    {run.run_id.slice(0, 8)}...
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
        )}
      </Card>
    </div>
  );
}

/* ── Progress Bar ──────────────────────────────────────────────── */

function ProgressBar({ percentage, status }: { percentage: number; status: RunStatus }) {
  const colorMap: Record<RunStatus, string> = {
    QUEUED: 'var(--text-muted)',
    PROCESSING: 'var(--accent)',
    PARTIAL_SUCCESS: 'var(--color-warning)',
    COMPLETE: 'var(--color-success)',
    FAILED: 'var(--color-danger)',
  };

  return (
    <div
      style={{
        width: '100%',
        height: 6,
        backgroundColor: 'var(--bg-surface-3)',
        borderRadius: 'var(--radius-full)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${Math.min(100, Math.max(0, percentage))}%`,
          height: '100%',
          backgroundColor: colorMap[status],
          borderRadius: 'var(--radius-full)',
          transition: 'width 500ms ease',
        }}
      />
    </div>
  );
}
