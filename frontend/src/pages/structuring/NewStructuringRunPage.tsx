import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { createStructuringRun, listUploadedDocuments } from '../../api/structuring';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { useToast } from '../../context/ToastContext';

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function NewStructuringRunPage() {
  const { addToast } = useToast();
  const navigate = useNavigate();
  const [runLabel, setRunLabel] = React.useState('');
  const [selectedIds, setSelectedIds] = React.useState<Record<string, boolean>>({});
  const [inlineError, setInlineError] = React.useState<string>('');

  const docsQuery = useQuery({
    queryKey: ['uploadedDocuments', { doc_type: 'CONTRACT', page: 1, page_size: 100 }],
    queryFn: () => listUploadedDocuments({ doc_type: 'CONTRACT', page: 1, page_size: 100 }),
  });

  const selectedDocumentIds = React.useMemo(
    () => Object.keys(selectedIds).filter((id) => selectedIds[id]),
    [selectedIds],
  );

  const createMutation = useMutation({
    mutationFn: () => createStructuringRun(selectedDocumentIds, runLabel.trim()),
    onSuccess: (res) => {
      addToast('success', 'Structuring run started');
      navigate(`/structuring/${res.id}`);
    },
    onError: (err: Error) => {
      setInlineError(err.message);
      addToast('error', `Failed to start run: ${err.message}`);
    },
  });

  const canSubmit = runLabel.trim().length > 0 && selectedDocumentIds.length > 0;

  return (
    <div className="animate-fadeIn">
      <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', color: 'var(--text-primary)', marginBottom: 'var(--space-2)' }}>
        New Structuring Run
      </h1>
      <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 'var(--space-6)' }}>
        Select uploaded contract documents and launch a structuring run.
      </p>

      <Card style={{ marginTop: 'var(--space-4)', display: 'grid', gap: 'var(--space-5)' }}>
        {inlineError && <ErrorMessage message={inlineError} onDismiss={() => setInlineError('')} />}

        <label style={{ display: 'grid', gap: '6px' }}>
          <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Run Label
          </span>
          <input
            value={runLabel}
            onChange={(e) => setRunLabel(e.target.value)}
            placeholder="e.g. Q1 Rate Card Onboarding"
            style={{
              width: '100%',
              backgroundColor: 'var(--bg-base)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-md)',
              padding: '10px 12px',
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-sm)',
            }}
          />
        </label>

        <div>
          <div style={{ marginBottom: 'var(--space-3)', color: 'var(--text-secondary)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Contract Documents
          </div>

          {docsQuery.isLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <LoadingSpinner size={28} />
            </div>
          ) : docsQuery.isError ? (
            <ErrorMessage message={(docsQuery.error as Error).message} />
          ) : !docsQuery.data?.data.length ? (
            <div style={{ padding: 'var(--space-4)', border: '1px dashed var(--border-default)', borderRadius: 'var(--radius-md)', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
              No uploaded CONTRACT documents found.
            </div>
          ) : (
            <div style={{ overflowX: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
                <thead>
                  <tr>
                    <th style={{ padding: '10px', borderBottom: '1px solid var(--border-default)', textAlign: 'left' }} />
                    <th style={{ padding: '10px', borderBottom: '1px solid var(--border-default)', textAlign: 'left', color: 'var(--text-secondary)', fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Filename</th>
                    <th style={{ padding: '10px', borderBottom: '1px solid var(--border-default)', textAlign: 'left', color: 'var(--text-secondary)', fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Upload Date</th>
                    <th style={{ padding: '10px', borderBottom: '1px solid var(--border-default)', textAlign: 'left', color: 'var(--text-secondary)', fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>File Size</th>
                  </tr>
                </thead>
                <tbody>
                  {docsQuery.data.data.map((doc) => (
                    <tr key={doc.document_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '10px' }}>
                        <input
                          type="checkbox"
                          checked={!!selectedIds[doc.document_id]}
                          onChange={(e) => {
                            setSelectedIds((prev) => ({ ...prev, [doc.document_id]: e.target.checked }));
                          }}
                        />
                      </td>
                      <td style={{ padding: '10px', color: 'var(--text-primary)' }}>{doc.filename}</td>
                      <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>{doc.created_at ? new Date(doc.created_at).toLocaleString() : '—'}</td>
                      <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>{formatFileSize(doc.file_size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <Button
          onClick={() => createMutation.mutate()}
          disabled={!canSubmit || createMutation.isPending}
          loading={createMutation.isPending}
        >
          Start Structuring Run
        </Button>
      </Card>
    </div>
  );
}
