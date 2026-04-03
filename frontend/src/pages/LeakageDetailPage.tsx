import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLeakageRecord, acceptRecord, rejectRecord } from '../api/endpoints/leakage';
import { ExplanationPanel } from '../components/leakage/ExplanationPanel';
import { EvidencePanel } from '../components/leakage/EvidencePanel';
import { EMPTY_VALUE, formatDateValue } from '../components/leakage/leakageDetailUtils';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { Modal } from '../components/ui/Modal';
import { useToast } from '../context/ToastContext';

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export default function LeakageDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectNotes, setRejectNotes] = useState('');

  const { data: record, isLoading, error } = useQuery({
    queryKey: ['leakageRecord', id],
    queryFn: () => getLeakageRecord(id!),
    enabled: !!id,
  });

  const acceptMutation = useMutation({
    mutationFn: () => acceptRecord(id!),
    onSuccess: () => {
      addToast('success', 'Finding accepted');
      queryClient.invalidateQueries({ queryKey: ['leakageRecord', id] });
      queryClient.invalidateQueries({ queryKey: ['leakageRecords'] });
    },
    onError: (err: Error) => addToast('error', `Failed to accept: ${err.message}`),
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectRecord(id!, rejectNotes),
    onSuccess: () => {
      addToast('success', 'Finding rejected');
      setShowRejectModal(false);
      setRejectNotes('');
      queryClient.invalidateQueries({ queryKey: ['leakageRecord', id] });
      queryClient.invalidateQueries({ queryKey: ['leakageRecords'] });
    },
    onError: (err: Error) => addToast('error', `Failed to reject: ${err.message}`),
  });

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  if (error || !record) {
    return <ErrorMessage message={error?.message || 'Record not found'} />;
  }

  /*
   * NON-NEGOTIABLE: PENDING_FX_RATE records must NEVER show accept or reject buttons.
   * Only PENDING status records can be reviewed.
   */
  const canReview = record.status === 'PENDING';

  return (
    <div className="animate-fadeIn" style={{ maxWidth: 800, margin: '0 auto' }}>
      <button
        onClick={() => navigate('/leakage')}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--accent)',
          cursor: 'pointer',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-xs)',
          marginBottom: 'var(--space-6)',
          padding: 0,
          transition: 'opacity 150ms ease',
        }}
        onMouseEnter={(e) => { (e.target as HTMLElement).style.opacity = '0.8'; }}
        onMouseLeave={(e) => { (e.target as HTMLElement).style.opacity = '1'; }}
      >
        {'<- Back to Leakage Review'}
      </button>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-8)', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 'var(--space-3)', letterSpacing: '-0.01em', textTransform: 'capitalize' }}>
            {record.vendor_name || EMPTY_VALUE}
          </h1>
          <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
            <StatusBadge status={record.status} />
            <span style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              {record.leakage_type.replace(/_/g, ' ')}
            </span>
          </div>
        </div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', fontWeight: 700, color: 'var(--accent)' }}>
          {formatCurrency(record.amount, record.currency)}
        </div>
      </div>

      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-5)' }}>
          Finding Details
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
          <DetailField label="Invoice No" value={record.invoice_no} />
          <DetailField label="Invoice Date" value={formatDateValue(record.invoice_date)} />
          <DetailField label="Confidence" value={`${(record.confidence * 100).toFixed(0)}%`} />
          <DetailField label="Rule Applied" value={record.rule_applied} />
          <DetailField label="Created" value={formatDateValue(record.created_at)} />
          <DetailField label="Currency" value={record.currency} />
        </div>
      </Card>

      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-4)' }}>
          Explanation
        </h3>
        <ExplanationPanel
          leakageType={record.leakage_type}
          evidence={record.evidence}
          explanation={record.explanation}
          currency={record.currency}
        />
      </Card>

      {record.evidence && Object.keys(record.evidence).length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-4)' }}>
            Evidence
          </h3>
          <EvidencePanel
            leakageType={record.leakage_type}
            evidence={record.evidence}
            confidence={record.confidence}
            ruleApplied={record.rule_applied}
            vendorName={record.vendor_name}
            explanation={record.explanation}
            currency={record.currency}
          />
        </Card>
      )}

      {record.reviewed_by && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-4)' }}>
            Review
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
            <DetailField label="Reviewed By" value={record.reviewed_by} />
            <DetailField label="Reviewed At" value={formatDateValue(record.reviewed_at)} />
          </div>
          {record.review_notes && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <DetailField label="Notes" value={record.review_notes} />
            </div>
          )}
        </Card>
      )}

      {record.status === 'PENDING_FX_RATE' && (
        <Card
          style={{
            marginBottom: 'var(--space-6)',
            borderLeft: '4px solid var(--color-warning)',
          }}
        >
          <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-warning)" strokeWidth="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <span style={{ color: 'var(--color-warning)', fontSize: '14px' }}>
              This finding is awaiting FX rate data. Review will be available after rates are uploaded.
            </span>
          </div>
        </Card>
      )}

      {canReview && (
        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          <Button
            onClick={() => acceptMutation.mutate()}
            loading={acceptMutation.isPending}
          >
            Accept Finding
          </Button>
          <Button
            variant="danger"
            onClick={() => setShowRejectModal(true)}
          >
            Reject Finding
          </Button>
        </div>
      )}

      <Modal
        open={showRejectModal}
        onClose={() => setShowRejectModal(false)}
        title="Reject Finding"
      >
        <p style={{ fontFamily: 'var(--font-body)', color: 'var(--text-primary)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-4)' }}>
          Please provide a reason for rejecting this finding. This is required.
        </p>
        <textarea
          value={rejectNotes}
          onChange={(e) => setRejectNotes(e.target.value)}
          placeholder="Enter rejection reason..."
          rows={4}
          style={{
            width: '100%',
            backgroundColor: 'var(--bg-base)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-3) var(--space-4)',
            fontFamily: 'var(--font-body)',
            fontSize: 'var(--text-sm)',
            resize: 'vertical',
            outline: 'none',
            transition: 'border-color 200ms ease',
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
          <Button variant="secondary" onClick={() => setShowRejectModal(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => rejectMutation.mutate()}
            loading={rejectMutation.isPending}
            disabled={!rejectNotes.trim()}
          >
            Confirm Reject
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 'var(--space-1)' }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>{value || EMPTY_VALUE}</div>
    </div>
  );
}
