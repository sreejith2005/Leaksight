import React, { useState, useRef, useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { uploadDocument, triggerRun, getRunStatus, listRuns } from '../api/endpoints/ingest';
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
      if (status === 'COMPLETE' || status === 'FAILED') return false;
      return 3000;
    },
  });

  React.useEffect(() => {
    if (runStatus && (runStatus.status === 'COMPLETE' || runStatus.status === 'FAILED')) {
      if (runStatus.status === 'COMPLETE') {
        addToast('success', `Analysis complete — ${runStatus.leakage_record_count} findings`);
      } else {
        addToast('error', `Analysis failed: ${runStatus.error_summary ?? 'Unknown error'}`);
      }
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    }
  }, [runStatus?.status]); // eslint-disable-line react-hooks/exhaustive-deps

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
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)', marginBottom: 'var(--space-6)' }}>
        Upload Documents
      </h1>

      {/* Document type selector */}
      <div style={{ marginBottom: 'var(--space-4)', display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
        <label style={{ fontSize: '14px', color: 'var(--color-grey)' }}>Document Type:</label>
        <select
          value={selectedDocType}
          onChange={(e) => setSelectedDocType(e.target.value)}
          style={{
            backgroundColor: 'var(--color-prussian-blue)',
            color: 'var(--color-grey)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-2) var(--space-3)',
            fontSize: '14px',
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
          border: `2px dashed ${isDragging ? 'var(--color-orange)' : 'var(--color-border)'}`,
          borderRadius: 'var(--radius-lg)',
          padding: 'var(--space-12)',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: isDragging ? 'rgba(252, 163, 17, 0.04)' : 'transparent',
          transition: 'all 0.2s',
          marginBottom: 'var(--space-6)',
        }}
      >
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke={isDragging ? 'var(--color-orange)' : 'var(--color-muted)'}
          strokeWidth="1.5"
          style={{ marginBottom: 'var(--space-4)', display: 'inline-block' }}
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <p style={{ fontSize: '16px', color: 'var(--color-grey)', marginBottom: 'var(--space-2)' }}>
          {isDragging ? 'Drop files here' : 'Drag & drop files or click to browse'}
        </p>
        <p style={{ fontSize: '12px', color: 'var(--color-muted)' }}>
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
          <span style={{ color: 'var(--color-grey)', fontSize: '14px' }}>Uploading...</span>
        </div>
      )}

      {/* Uploaded documents list */}
      {uploadedDocs.length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)' }}>
              Pending Documents ({uploadedDocs.length})
            </h3>
            <Button
              onClick={() => triggerMutation.mutate()}
              loading={triggerMutation.isPending}
              disabled={uploadedDocs.length === 0}
            >
              Trigger Analysis Run
            </Button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {uploadedDocs.map((doc) => (
              <div
                key={doc.document_id}
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
                <span style={{ color: 'var(--color-grey)' }}>{doc.filename}</span>
                <span style={{ color: 'var(--color-muted)', fontSize: '12px' }}>{doc.doc_type}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Active run progress */}
      {activeRunId && runStatus && (
        <Card highlight={runStatus.status === 'COMPLETE'} style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)' }}>
              Active Analysis Run
            </h3>
            <StatusBadge status={runStatus.status} />
          </div>
          <ProgressBar percentage={runStatus.progress_percentage} status={runStatus.status} />
          <div style={{ display: 'flex', gap: 'var(--space-6)', marginTop: 'var(--space-3)', fontSize: '13px', color: 'var(--color-muted)' }}>
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
        <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
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
                  padding: 'var(--space-3)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '14px',
                }}
              >
                <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
                  <StatusBadge status={run.status} />
                  <span style={{ color: 'var(--color-grey)', fontFamily: 'monospace', fontSize: '12px' }}>
                    {run.run_id.slice(0, 8)}...
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
        )}
      </Card>
    </div>
  );
}

/* ── Progress Bar ──────────────────────────────────────────────── */

function ProgressBar({ percentage, status }: { percentage: number; status: RunStatus }) {
  const colorMap: Record<RunStatus, string> = {
    QUEUED: 'var(--color-muted)',
    PROCESSING: 'var(--color-orange)',
    PARTIAL_SUCCESS: 'var(--color-warning)',
    COMPLETE: 'var(--color-success)',
    FAILED: 'var(--color-error)',
  };

  return (
    <div
      style={{
        width: '100%',
        height: 8,
        backgroundColor: 'var(--color-black)',
        borderRadius: 'var(--radius-sm)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${Math.min(100, Math.max(0, percentage))}%`,
          height: '100%',
          backgroundColor: colorMap[status],
          borderRadius: 'var(--radius-sm)',
          transition: 'width 0.5s ease',
        }}
      />
    </div>
  );
}
