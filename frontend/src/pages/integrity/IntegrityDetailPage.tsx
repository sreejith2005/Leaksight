import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { analyzeDocument, getReport } from '../../api/integrity';
import { IntegrityReport } from '../../components/integrity/IntegrityReport';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { useToast } from '../../context/ToastContext';

export default function IntegrityDetailPage() {
  const navigate = useNavigate();
  const { documentId = '' } = useParams();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const [isAwaitingAnalysis, setIsAwaitingAnalysis] = React.useState(false);

  const reportQuery = useQuery({
    queryKey: ['integrityReport', documentId],
    queryFn: () => getReport(documentId),
    enabled: !!documentId,
    refetchInterval: (query) => {
      const report = query.state.data as Awaited<ReturnType<typeof getReport>> | undefined;
      if (!report) {
        return false;
      }
      return report.risk_score === null || isAwaitingAnalysis ? 3000 : false;
    },
  });

  const reanalyzeMutation = useMutation({
    mutationFn: () => analyzeDocument(documentId),
    onSuccess: () => {
      setIsAwaitingAnalysis(true);
      addToast('success', 'Integrity analysis queued');
      queryClient.invalidateQueries({ queryKey: ['integrityReport', documentId] });
      queryClient.invalidateQueries({ queryKey: ['integrityDocuments'] });
    },
    onError: (error: Error) => addToast('error', `Failed to queue re-analysis: ${error.message}`),
  });

  React.useEffect(() => {
    if (!isAwaitingAnalysis) {
      return;
    }

    if (reportQuery.data?.risk_score !== null && reportQuery.data?.risk_score !== undefined) {
      setIsAwaitingAnalysis(false);
      addToast('success', 'Integrity report refreshed');
      queryClient.invalidateQueries({ queryKey: ['integrityDocuments'] });
    }
  }, [addToast, isAwaitingAnalysis, queryClient, reportQuery.data?.risk_score]);

  if (reportQuery.isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  if (reportQuery.error || !reportQuery.data) {
    return <ErrorMessage message={reportQuery.error?.message || 'Integrity report not found'} />;
  }

  return (
    <div className="animate-fadeIn" style={{ display: 'grid', gap: 'var(--space-5)' }}>
      <button
        onClick={() => navigate('/integrity')}
        style={{
          width: 'fit-content',
          background: 'none',
          border: 'none',
          color: 'var(--accent)',
          cursor: 'pointer',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-xs)',
          padding: 0,
        }}
      >
        {'<- Back to Document Integrity'}
      </button>

      <IntegrityReport
        report={reportQuery.data}
        onReanalyze={() => reanalyzeMutation.mutate()}
        isReanalyzing={reanalyzeMutation.isPending}
        isPollingForUpdate={isAwaitingAnalysis}
      />
    </div>
  );
}
