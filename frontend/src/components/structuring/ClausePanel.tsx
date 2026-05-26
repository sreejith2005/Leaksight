import React from 'react';
import { Button } from '../ui/Button';
import { ConfidenceFlag } from './ConfidenceFlag';
import type { StructuringClause } from '../../api/structuring';

interface ClausePanelProps {
  clauses: StructuringClause[];
  onConfirm: (clauseId: string) => Promise<void>;
  onReject: (clauseId: string, reason: string) => Promise<void>;
  pendingIds: Record<string, boolean>;
}

const CLAUSE_TYPES = ['EFFECTIVE_DATE', 'EXPIRY_DATE', 'CONTRACT_REF', 'VENDOR_NAME', 'AMENDMENT_REF', 'ESCALATION'];

function getDisplayStatus(clause: StructuringClause): 'PENDING_REVIEW' | 'CONFIRMED' | 'REJECTED' {
  return clause.review_status;
}

function clauseStatusBadge(status: 'PENDING_REVIEW' | 'CONFIRMED' | 'REJECTED') {
  const config: Record<'PENDING_REVIEW' | 'CONFIRMED' | 'REJECTED', { bg: string; color: string; label: string }> = {
    PENDING_REVIEW: { bg: 'transparent', color: 'var(--text-muted)', label: 'PENDING REVIEW' },
    CONFIRMED: { bg: 'var(--color-success-dim)', color: 'var(--color-success)', label: 'CONFIRMED' },
    REJECTED: { bg: 'var(--color-danger-dim)', color: 'var(--color-danger)', label: 'REJECTED' },
  };
  const cfg = config[status];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: 'var(--radius-full)',
        padding: status === 'PENDING_REVIEW' ? '2px 8px' : '3px 10px',
        background: cfg.bg,
        color: cfg.color,
        border: status === 'PENDING_REVIEW' ? '1px solid var(--border-default)' : '1px solid transparent',
        fontFamily: 'var(--font-body)',
        fontSize: 'var(--text-xs)',
        fontWeight: status === 'PENDING_REVIEW' ? 500 : 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {cfg.label}
    </span>
  );
}

export function ClausePanel({ clauses, onConfirm, onReject, pendingIds }: ClausePanelProps) {
  const [rejectingId, setRejectingId] = React.useState<string | null>(null);
  const [rejectReason, setRejectReason] = React.useState('');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      {CLAUSE_TYPES.map((type) => {
        const group = clauses.filter((c) => c.clause_type === type);
        return (
          <div key={type} style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)' }}>
            <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 'var(--space-2)' }}>
              {type}
            </div>
            {group.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)' }}>None detected</div>
            ) : (
              group.map((clause) => (
                <div
                  key={clause.id}
                  style={{
                    padding: 'var(--space-3)',
                    borderTop: '1px dashed var(--border-subtle)',
                    borderLeft: clause.needs_review ? '3px solid var(--color-warning)' : '3px solid transparent',
                    background: clause.needs_review ? 'var(--color-warning-dim)' : 'transparent',
                  }}
                >
                  <div style={{ fontFamily: 'var(--font-body)', fontSize: '11px', fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                    {clause.clause_type.replace(/_/g, ' ')}
                  </div>
                  <div style={{ marginTop: '6px', fontFamily: 'var(--font-display)', fontSize: 'var(--text-lg)', color: 'var(--text-primary)', fontWeight: 700 }}>
                    {clause.extracted_value || '—'}
                  </div>
                  <div style={{ marginTop: '6px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                    {(clause.raw_text || '').slice(0, 150) || '—'}
                    {(clause.raw_text || '').length > 150 ? '...' : ''}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-2)', marginTop: 'var(--space-2)', flexWrap: 'wrap' }}>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <ConfidenceFlag confidence={clause.confidence} />
                      {clauseStatusBadge(getDisplayStatus(clause))}
                    </div>
                    <div style={{ display: 'inline-flex', gap: 'var(--space-2)' }}>
                      <Button
                        variant="secondary"
                        onClick={() => void onConfirm(clause.id)}
                        disabled={pendingIds[clause.id]}
                        loading={pendingIds[clause.id]}
                        style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          setRejectingId(clause.id);
                          setRejectReason('');
                        }}
                        disabled={pendingIds[clause.id]}
                        style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                      >
                        Reject
                      </Button>
                    </div>
                  </div>

                  {rejectingId === clause.id && (
                    <div style={{ marginTop: 'var(--space-2)', display: 'grid', gap: '8px' }}>
                      <input
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        placeholder="Rejection reason"
                        style={{
                          border: '1px solid var(--border-default)',
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-surface-1)',
                          color: 'var(--text-primary)',
                          padding: '6px 8px',
                          fontSize: 'var(--text-sm)',
                        }}
                      />
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <Button
                          variant="danger"
                          onClick={() => {
                            void onReject(clause.id, rejectReason.trim());
                            setRejectingId(null);
                            setRejectReason('');
                          }}
                          disabled={!rejectReason.trim() || pendingIds[clause.id]}
                          loading={pendingIds[clause.id]}
                          style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                        >
                          Submit
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setRejectingId(null);
                            setRejectReason('');
                          }}
                          disabled={pendingIds[clause.id]}
                          style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        );
      })}
    </div>
  );
}
