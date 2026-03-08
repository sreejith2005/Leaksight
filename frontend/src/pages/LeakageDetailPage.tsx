import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLeakageRecord, acceptRecord, rejectRecord } from '../api/endpoints/leakage';
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
      {/* Back button */}
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
        ← Back to Leakage Review
      </button>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-8)' }}>
        <div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 'var(--space-3)', letterSpacing: '-0.01em', textTransform: 'capitalize' }}>
            {record.vendor_name}
          </h1>
          <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
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

      {/* Detail fields */}
      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-5)' }}>
          Finding Details
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
          <DetailField label="Invoice No" value={record.invoice_no} />
          <DetailField label="Invoice Date" value={record.invoice_date ? new Date(record.invoice_date).toLocaleDateString() : '—'} />
          <DetailField label="Confidence" value={`${(record.confidence * 100).toFixed(0)}%`} />
          <DetailField label="Rule Applied" value={record.rule_applied} />
          <DetailField label="Created" value={record.created_at ? new Date(record.created_at).toLocaleDateString() : '—'} />
          <DetailField label="Currency" value={record.currency} />
        </div>
      </Card>

      {/* Explanation */}
      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-4)' }}>
          Explanation
        </h3>
        <p style={{ fontFamily: 'var(--font-body)', color: 'var(--text-primary)', fontSize: 'var(--text-sm)', lineHeight: 1.7 }}>
          {record.explanation}
        </p>
      </Card>

      {/* Evidence */}
      {record.evidence && Object.keys(record.evidence).length > 0 && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-4)' }}>
            Evidence
          </h3>
          <pre
            style={{
              backgroundColor: 'var(--bg-base)',
              padding: 'var(--space-5)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              overflow: 'auto',
              maxHeight: 300,
              border: '1px solid var(--border-subtle)',
              lineHeight: 1.6,
            }}
          >
            {JSON.stringify(record.evidence, null, 2)}
          </pre>
        </Card>
      )}

      {/* Review history */}
      {record.reviewed_by && (
        <Card style={{ marginBottom: 'var(--space-6)' }}>
          <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-4)' }}>
            Review
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
            <DetailField label="Reviewed By" value={record.reviewed_by} />
            <DetailField label="Reviewed At" value={record.reviewed_at ? new Date(record.reviewed_at).toLocaleDateString() : '—'} />
          </div>
          {record.review_notes && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <DetailField label="Notes" value={record.review_notes} />
            </div>
          )}
        </Card>
      )}

      {/* PENDING_FX_RATE info banner */}
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

      {/* Action buttons — ONLY for PENDING status, NEVER for PENDING_FX_RATE */}
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

      {/* Reject modal */}
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

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 'var(--space-1)' }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}
