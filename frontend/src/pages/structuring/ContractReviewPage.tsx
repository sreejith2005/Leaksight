import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Card } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { LineItemTable } from '../../components/structuring/LineItemTable';
import { ClausePanel } from '../../components/structuring/ClausePanel';
import { ColumnRoleMapper } from '../../components/structuring/ColumnRoleMapper';
import {
  confirmLineItem,
  getRunResults,
  rejectLineItem,
  updateClause,
  updateLineItem,
  type StructuringClause,
  type StructuringLineItem,
  type StructuringRunResults,
} from '../../api/structuring';
import { APIError } from '../../api/client';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { useToast } from '../../context/ToastContext';

const WIDE_LAYOUT_BREAKPOINT = 1024;

function lineItemConfidence(item: StructuringLineItem): number {
  return Math.min(item.item_confidence, item.price_confidence, item.unit_confidence);
}

function patchLineItemInResults(
  results: StructuringRunResults | undefined,
  itemId: string,
  updater: (item: StructuringLineItem) => StructuringLineItem,
): StructuringRunResults | undefined {
  if (!results) return results;
  return {
    ...results,
    documents: results.documents.map((doc) => ({
      ...doc,
      line_items: doc.line_items.map((item) => (item.id === itemId ? updater(item) : item)),
    })),
  };
}

function patchClauseInResults(
  results: StructuringRunResults | undefined,
  clauseId: string,
  updater: (clause: StructuringClause) => StructuringClause,
): StructuringRunResults | undefined {
  if (!results) return results;
  return {
    ...results,
    documents: results.documents.map((doc) => ({
      ...doc,
      clauses: doc.clauses.map((clause) => (clause.id === clauseId ? updater(clause) : clause)),
    })),
  };
}

function parseApiError(err: unknown): { status: number | null; message: string } {
  if (err instanceof APIError) {
    return { status: err.status, message: err.message };
  }
  if (err instanceof Error) {
    return { status: null, message: err.message };
  }
  return { status: null, message: 'Request failed' };
}

function isUuidLike(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.trim());
}

function safeDisplayLabel(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || isUuidLike(trimmed)) return '';
  return trimmed;
}

export default function ContractReviewPage() {
  const { runId = '', documentId = '' } = useParams();
  const { addToast } = useToast();
  const queryClient = useQueryClient();
  const [bulkState, setBulkState] = React.useState({ isRunning: false, completed: 0, total: 0 });
  const [dismissVersionBanner, setDismissVersionBanner] = React.useState(false);
  const [pendingClauseIds, setPendingClauseIds] = React.useState<Record<string, boolean>>({});
  const [isNarrowLayout, setIsNarrowLayout] = React.useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth < WIDE_LAYOUT_BREAKPOINT;
  });

  React.useEffect(() => {
    const media = window.matchMedia(`(max-width: ${WIDE_LAYOUT_BREAKPOINT - 1}px)`);
    const onChange = () => setIsNarrowLayout(media.matches);
    onChange();
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const queryKey = React.useMemo(
    () => ['structuringRunResults', runId, { document_id: documentId }] as const,
    [runId, documentId],
  );

  const resultsQuery = useQuery({
    queryKey,
    queryFn: () => getRunResults(runId, { document_id: documentId }),
    enabled: Boolean(runId && documentId),
  });

  const doc = resultsQuery.data?.documents[0] || null;
  const lineItems = doc?.line_items || [];
  const clauses = doc?.clauses || [];
  const hasVersionDiff = lineItems.some((item) => Number(item.version_number || 1) > 1);
  const showLowConfidenceNotice = lineItems.some((item) => item.needs_review && item.item_confidence < 0.5);

  const documentName = React.useMemo(() => {
    const docMeta = doc as { filename?: string; document_filename?: string; original_filename?: string } | null;
    const maybeFilename = docMeta?.filename
      || docMeta?.document_filename
      || docMeta?.original_filename
      || 'Document';

    const safeFilename = safeDisplayLabel(maybeFilename);
    if (safeFilename) {
      return safeFilename;
    }

    return 'Document';
  }, [doc]);

  const vendorName = React.useMemo(() => {
    const vendorClause = clauses.find((clause) => clause.clause_type === 'VENDOR_NAME');
    const candidate = vendorClause?.extracted_value?.trim() || '';
    return safeDisplayLabel(candidate);
  }, [clauses]);

  const updateLineItemField = React.useCallback(
    async (
      itemId: string,
      patch: Partial<Pick<StructuringLineItem, 'item_description' | 'unit_raw' | 'unit_price'>>,
    ) => {
      if (patch.unit_price !== undefined && patch.unit_price !== null && Number(patch.unit_price) <= 0) {
        addToast('warning', 'Unit price must be greater than zero');
        throw new Error('unit_price invalid');
      }

      const previous = queryClient.getQueryData<StructuringRunResults>(queryKey);
      queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
        patchLineItemInResults(current, itemId, (item) => ({ ...item, ...patch })),
      );

      try {
        const updated = await updateLineItem(itemId, patch);
        queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
          patchLineItemInResults(current, itemId, () => updated),
        );
      } catch (err) {
        queryClient.setQueryData(queryKey, previous);
        const apiErr = parseApiError(err);
        if (apiErr.status === 409) {
          queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
            patchLineItemInResults(current, itemId, (item) => ({ ...item, review_status: 'CONFIRMED' })),
          );
          addToast('warning', 'This item is already confirmed');
          return;
        }
        if (apiErr.status === 422) {
          addToast('error', 'Invalid value. Please review the input and try again.');
          return;
        }
        addToast('error', apiErr.message || 'Failed to update line item');
        throw err;
      }
    },
    [addToast, queryClient, queryKey],
  );

  const confirmItem = React.useCallback(
    async (itemId: string, silent?: boolean): Promise<boolean> => {
      const previous = queryClient.getQueryData<StructuringRunResults>(queryKey);
      queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
        patchLineItemInResults(current, itemId, (item) => ({ ...item, review_status: 'CONFIRMED' })),
      );

      try {
        const updated = await confirmLineItem(itemId);
        queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
          patchLineItemInResults(current, itemId, () => updated),
        );
        if (!silent) {
          addToast('success', 'Line item confirmed');
        }
        return true;
      } catch (err) {
        queryClient.setQueryData(queryKey, previous);
        const apiErr = parseApiError(err);
        if (apiErr.status === 409) {
          queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
            patchLineItemInResults(current, itemId, (item) => ({ ...item, review_status: 'CONFIRMED' })),
          );
          addToast('warning', 'This item is already confirmed');
          return false;
        }
        if (!silent) {
          addToast('error', apiErr.message || 'Failed to confirm line item');
        }
        return false;
      }
    },
    [addToast, queryClient, queryKey],
  );

  const rejectItem = React.useCallback(
    async (itemId: string, reason: string): Promise<void> => {
      if (!reason.trim()) {
        addToast('warning', 'Rejection reason is required');
        throw new Error('reason required');
      }

      const previous = queryClient.getQueryData<StructuringRunResults>(queryKey);
      queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
        patchLineItemInResults(current, itemId, (item) => ({ ...item, review_status: 'REJECTED', reviewer_notes: reason })),
      );

      try {
        const updated = await rejectLineItem(itemId, reason);
        queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
          patchLineItemInResults(current, itemId, () => updated),
        );
        addToast('success', 'Line item rejected');
      } catch (err) {
        queryClient.setQueryData(queryKey, previous);
        const apiErr = parseApiError(err);
        if (apiErr.status === 409) {
          queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
            patchLineItemInResults(current, itemId, (item) => ({ ...item, review_status: 'CONFIRMED' })),
          );
          addToast('warning', 'This item is already confirmed');
          return;
        }
        addToast('error', apiErr.message || 'Failed to reject line item');
        throw err;
      }
    },
    [addToast, queryClient, queryKey],
  );

  const confirmAllHighConfidence = React.useCallback(async () => {
    const snapshot = queryClient.getQueryData<StructuringRunResults>(queryKey);
    const allItems = snapshot?.documents.flatMap((d) => d.line_items) || [];
    const eligible = allItems.filter(
      (item) => item.review_status === 'PENDING_REVIEW' && lineItemConfidence(item) >= 0.85,
    );

    if (eligible.length === 0) {
      addToast('warning', 'No high-confidence items available to confirm');
      return;
    }

    setBulkState({ isRunning: true, completed: 0, total: eligible.length });

    let successCount = 0;
    let failedCount = 0;
    for (let i = 0; i < eligible.length; i += 1) {
      const ok = await confirmItem(eligible[i].id, true);
      if (ok) {
        successCount += 1;
      } else {
        failedCount += 1;
      }
      setBulkState({ isRunning: true, completed: i + 1, total: eligible.length });
    }

    setBulkState({ isRunning: false, completed: eligible.length, total: eligible.length });

    if (failedCount > 0) {
      addToast('warning', `Confirmed ${successCount} items (${failedCount} failed)`);
    } else {
      addToast('success', `Confirmed ${successCount} items`);
    }
  }, [addToast, confirmItem, queryClient, queryKey]);

  const confirmClause = React.useCallback(
    async (clauseId: string) => {
      const previous = queryClient.getQueryData<StructuringRunResults>(queryKey);
      setPendingClauseIds((prev) => ({ ...prev, [clauseId]: true }));

      queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
        patchClauseInResults(current, clauseId, (clause) => ({
          ...clause,
          review_status: 'CONFIRMED',
        })),
      );

      try {
        const updated = await updateClause(clauseId, { review_status: 'CONFIRMED' });
        queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
          patchClauseInResults(current, clauseId, (clause) => ({
            ...clause,
            ...updated,
            review_status: 'CONFIRMED',
          })),
        );
        addToast('success', 'Clause confirmed');
      } catch (err) {
        queryClient.setQueryData(queryKey, previous);
        addToast('error', parseApiError(err).message || 'Failed to update clause');
      } finally {
        setPendingClauseIds((prev) => ({ ...prev, [clauseId]: false }));
      }
    },
    [addToast, queryClient, queryKey],
  );

  const rejectClause = React.useCallback(
    async (clauseId: string, reason: string) => {
      if (!reason.trim()) {
        addToast('warning', 'Rejection reason is required');
        return;
      }

      const note = reason.trim();
      const previous = queryClient.getQueryData<StructuringRunResults>(queryKey);
      setPendingClauseIds((prev) => ({ ...prev, [clauseId]: true }));

      queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
        patchClauseInResults(current, clauseId, (clause) => ({
          ...clause,
          review_status: 'REJECTED',
          reviewer_notes: note,
        })),
      );

      try {
        await updateClause(clauseId, { review_status: 'REJECTED', reviewer_notes: note });
        queryClient.setQueryData<StructuringRunResults | undefined>(queryKey, (current) =>
          patchClauseInResults(current, clauseId, (clause) => ({
            ...clause,
            review_status: 'REJECTED',
            reviewer_notes: note,
          })),
        );
        addToast('success', 'Clause marked as rejected');
      } catch (err) {
        queryClient.setQueryData(queryKey, previous);
        addToast('error', parseApiError(err).message || 'Failed to update clause');
      } finally {
        setPendingClauseIds((prev) => ({ ...prev, [clauseId]: false }));
      }
    },
    [addToast, queryClient, queryKey],
  );

  return (
    <div className="animate-fadeIn">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 'var(--space-4)',
          gap: 'var(--space-3)',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'grid', gap: '8px' }}>
          <Link to={`/structuring/${runId}`} style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: 'var(--text-sm)' }}>
            ← Back to Run
          </Link>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', margin: 0, color: 'var(--text-primary)' }}>
            {documentName}
          </h1>
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
              {resultsQuery.data?.run.run_label || `Run ${runId.slice(0, 8)}`}
            </span>
            {doc?.task_status && <StatusBadge status={doc.task_status as any} />}
          </div>
        </div>
        <Link to="#" onClick={(e) => { e.preventDefault(); void confirmAllHighConfidence(); }}>
          <Button variant="secondary" disabled={bulkState.isRunning} loading={bulkState.isRunning}>
            Confirm All High-Confidence
          </Button>
        </Link>
      </div>

      {resultsQuery.isLoading ? (
        <Card>
          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
            <LoadingSpinner size={26} />
            <div style={{ height: 10, width: '65%', borderRadius: 'var(--radius-full)', background: 'var(--bg-surface-2)' }} />
            <div style={{ height: 10, width: '85%', borderRadius: 'var(--radius-full)', background: 'var(--bg-surface-2)' }} />
            <div style={{ height: 10, width: '45%', borderRadius: 'var(--radius-full)', background: 'var(--bg-surface-2)' }} />
          </div>
        </Card>
      ) : resultsQuery.error ? (
        <Card>
          <p style={{ margin: 0, color: 'var(--color-danger)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
            Failed to load contract review data.
          </p>
        </Card>
      ) : !doc ? (
        <Card>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
            No reviewable document data found for this run.
          </p>
        </Card>
      ) : (
        <div
          style={{
            display: 'grid',
            gap: 'var(--space-4)',
            gridTemplateColumns: isNarrowLayout ? '1fr' : 'minmax(0, 3fr) minmax(0, 2fr)',
            alignItems: 'start',
          }}
        >
          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
            {hasVersionDiff && !dismissVersionBanner && (
              <Card style={{ background: 'var(--color-warning-dim)', borderColor: 'var(--color-warning)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-2)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--color-warning)' }}>
                    <span>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <path d="M14 2v6h6" />
                      </svg>
                    </span>
                    <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      Amendment detected — some items differ from the previous contract version
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setDismissVersionBanner(true)}
                    style={{ border: 0, background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}
                  >
                    Dismiss
                  </button>
                </div>
              </Card>
            )}

            {showLowConfidenceNotice && <ColumnRoleMapper />}

            <Card style={{ padding: 'var(--space-3)' }}>
              <LineItemTable
                items={lineItems}
                onConfirm={async (id) => {
                  await confirmItem(id);
                }}
                onReject={rejectItem}
                onEdit={updateLineItemField}
                onBulkConfirm={confirmAllHighConfidence}
                bulkState={bulkState}
              />
            </Card>
          </div>

          <Card style={{ padding: 'var(--space-3)' }}>
            <ClausePanel
              clauses={clauses}
              onConfirm={confirmClause}
              onReject={rejectClause}
              pendingIds={pendingClauseIds}
            />
          </Card>
        </div>
      )}
    </div>
  );
}
