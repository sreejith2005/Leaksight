import React from 'react';
import { Button } from '../ui/Button';
import { ConfidenceFlag } from './ConfidenceFlag';
import type { StructuringLineItem } from '../../api/structuring';

interface LineItemTableProps {
  items: StructuringLineItem[];
  onConfirm: (id: string) => Promise<void>;
  onReject: (id: string, reason: string) => Promise<void>;
  onEdit: (itemId: string, patch: Partial<Pick<StructuringLineItem, 'item_description' | 'unit_raw' | 'unit_price'>>) => Promise<void>;
  onBulkConfirm: () => Promise<void>;
  bulkState: {
    isRunning: boolean;
    completed: number;
    total: number;
  };
}

type EditableField = 'item_description' | 'unit_raw' | 'unit_price';

function computedConfidence(item: StructuringLineItem): number {
  return Math.min(item.item_confidence, item.price_confidence, item.unit_confidence);
}

function formatPrice(value: number | null): string {
  if (value == null) return '—';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function reviewStatusBadge(status: StructuringLineItem['review_status']) {
  const config: Record<StructuringLineItem['review_status'], { bg: string; color: string; label: string }> = {
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

function displayValue(item: StructuringLineItem, field: EditableField): string {
  if (field === 'unit_price') return item.unit_price == null ? '' : String(item.unit_price);
  if (field === 'item_description') return item.item_description || '';
  return item.unit_raw || '';
}

function formatLocation(item: StructuringLineItem): string {
  if (item.source_page == null) return '—';

  const method = (item.extraction_method || '').toUpperCase();
  if (method === 'EXCEL_SHEET') return `Sheet ${item.source_page}`;
  if (method === 'CAMELOT_LATTICE' || method === 'CAMELOT_STREAM' || method === 'PDFPLUMBER') return `Page ${item.source_page}`;
  if (method === 'DOCX_TABLE') return `Table ${item.source_page}`;
  return `p.${item.source_page}`;
}

export function LineItemTable({ items, onConfirm, onReject, onEdit, onBulkConfirm, bulkState }: LineItemTableProps) {
  const [needsReviewOnly, setNeedsReviewOnly] = React.useState(false);
  const [editingCell, setEditingCell] = React.useState<{ id: string; field: EditableField } | null>(null);
  const [draftValue, setDraftValue] = React.useState('');
  const [savingRows, setSavingRows] = React.useState<Record<string, boolean>>({});
  const [rejectingId, setRejectingId] = React.useState<string | null>(null);
  const [rejectReason, setRejectReason] = React.useState('');
  const [busyActionRows, setBusyActionRows] = React.useState<Record<string, boolean>>({});

  const visibleItems = React.useMemo(
    () => (needsReviewOnly ? items.filter((item) => item.needs_review) : items),
    [items, needsReviewOnly],
  );

  const startEdit = (item: StructuringLineItem, field: EditableField) => {
    if (item.review_status === 'CONFIRMED') return;
    setEditingCell({ id: item.id, field });
    setDraftValue(displayValue(item, field));
  };

  const commitEdit = async (item: StructuringLineItem) => {
    if (!editingCell || editingCell.id !== item.id) return;
    const field = editingCell.field;
    const previousValue = displayValue(item, field);
    const nextValue = draftValue.trim();
    setEditingCell(null);

    if (nextValue === previousValue.trim()) {
      return;
    }

    setSavingRows((prev) => ({ ...prev, [item.id]: true }));
    try {
      if (field === 'unit_price') {
        await onEdit(item.id, { unit_price: Number(nextValue) });
      } else if (field === 'item_description') {
        await onEdit(item.id, { item_description: nextValue || null });
      } else {
        await onEdit(item.id, { unit_raw: nextValue || null });
      }
    } finally {
      setSavingRows((prev) => ({ ...prev, [item.id]: false }));
    }
  };

  const handleConfirm = async (itemId: string) => {
    setBusyActionRows((prev) => ({ ...prev, [itemId]: true }));
    try {
      await onConfirm(itemId);
    } finally {
      setBusyActionRows((prev) => ({ ...prev, [itemId]: false }));
    }
  };

  const submitReject = async (itemId: string) => {
    setBusyActionRows((prev) => ({ ...prev, [itemId]: true }));
    try {
      await onReject(itemId, rejectReason.trim());
      setRejectingId(null);
      setRejectReason('');
    } finally {
      setBusyActionRows((prev) => ({ ...prev, [itemId]: false }));
    }
  };

  return (
    <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 'var(--space-3)',
          flexWrap: 'wrap',
        }}
      >
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
          <input
            type="checkbox"
            checked={needsReviewOnly}
            onChange={(e) => setNeedsReviewOnly(e.target.checked)}
          />
          Show only: Needs Review
        </label>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          {bulkState.isRunning && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              Confirming {bulkState.completed}/{bulkState.total}
            </span>
          )}
          <Button
            variant="secondary"
            onClick={() => void onBulkConfirm()}
            disabled={bulkState.isRunning}
            loading={bulkState.isRunning}
          >
            Confirm All High-Confidence
          </Button>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {['#', 'Contract ID', 'Item', 'Unit', 'Unit Price', 'Currency', 'Location', 'Confidence', 'Status', 'Actions'].map((h) => (
              <th key={h} style={{ textAlign: 'left', padding: 'var(--space-3)', color: 'var(--text-secondary)', fontSize: 'var(--text-xs)', borderBottom: '1px solid var(--border-default)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleItems.map((item, index) => {
            const confidence = computedConfidence(item);
            const isConfirmed = item.review_status === 'CONFIRMED';
            const isRejected = item.review_status === 'REJECTED';
            const isTerminal = isConfirmed || isRejected;
            const isSavingRow = savingRows[item.id] || busyActionRows[item.id];

            const rowStyle: React.CSSProperties = {
              opacity: isConfirmed ? 0.62 : 1,
              textDecoration: isRejected ? 'line-through' : 'none',
              background: item.needs_review ? 'var(--color-warning-dim)' : 'transparent',
            };

            const cellStyle: React.CSSProperties = {
              padding: 'var(--space-3)',
              borderBottom: '1px solid var(--border-subtle)',
              verticalAlign: 'top',
              color: 'var(--text-primary)',
            };

            const editStyle: React.CSSProperties = {
              width: '100%',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-surface-1)',
              color: 'var(--text-primary)',
              padding: '6px 8px',
              fontSize: 'var(--text-sm)',
            };

            return (
              <tr key={item.id} style={rowStyle}>
                <td style={cellStyle}>{index + 1}</td>

                <td style={{ ...cellStyle, width: 140, minWidth: 140, maxWidth: 140 }}>
                  {item.contract_id?.trim() ? (
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>{item.contract_id}</span>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>

                <td style={cellStyle}>
                  {editingCell?.id === item.id && editingCell.field === 'item_description' ? (
                    <input
                      autoFocus
                      value={draftValue}
                      onChange={(e) => setDraftValue(e.target.value)}
                      onBlur={() => void commitEdit(item)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          void commitEdit(item);
                        }
                        if (e.key === 'Escape') {
                          setEditingCell(null);
                        }
                      }}
                      style={editStyle}
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => startEdit(item, 'item_description')}
                      disabled={isTerminal}
                      style={{
                        border: 0,
                        background: 'transparent',
                        color: 'var(--text-primary)',
                        padding: 0,
                        textAlign: 'left',
                        cursor: isTerminal ? 'default' : 'text',
                        fontFamily: 'var(--font-body)',
                        width: '100%',
                      }}
                    >
                      {item.item_description || '—'}
                    </button>
                  )}
                </td>

                <td style={cellStyle}>
                  {editingCell?.id === item.id && editingCell.field === 'unit_raw' ? (
                    <input
                      autoFocus
                      value={draftValue}
                      onChange={(e) => setDraftValue(e.target.value)}
                      onBlur={() => void commitEdit(item)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          void commitEdit(item);
                        }
                        if (e.key === 'Escape') {
                          setEditingCell(null);
                        }
                      }}
                      style={editStyle}
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => startEdit(item, 'unit_raw')}
                      disabled={isTerminal}
                      style={{
                        border: 0,
                        background: 'transparent',
                        color: 'var(--text-primary)',
                        padding: 0,
                        textAlign: 'left',
                        cursor: isTerminal ? 'default' : 'text',
                        fontFamily: 'var(--font-body)',
                        width: '100%',
                      }}
                    >
                      {item.unit_raw?.trim() ? item.unit_raw : '—'}
                    </button>
                  )}
                </td>

                <td style={cellStyle}>
                  {editingCell?.id === item.id && editingCell.field === 'unit_price' ? (
                    <input
                      autoFocus
                      value={draftValue}
                      type="number"
                      min={0.0001}
                      step="0.0001"
                      onChange={(e) => setDraftValue(e.target.value)}
                      onBlur={() => void commitEdit(item)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          void commitEdit(item);
                        }
                        if (e.key === 'Escape') {
                          setEditingCell(null);
                        }
                      }}
                      style={editStyle}
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => startEdit(item, 'unit_price')}
                      disabled={isTerminal}
                      style={{
                        border: 0,
                        background: 'transparent',
                        color: 'var(--text-primary)',
                        padding: 0,
                        textAlign: 'left',
                        cursor: isTerminal ? 'default' : 'text',
                        fontFamily: 'var(--font-mono)',
                        width: '100%',
                      }}
                    >
                      {formatPrice(item.unit_price)}
                    </button>
                  )}
                </td>

                <td style={cellStyle}>{item.currency || '—'}</td>
                <td style={cellStyle}>{formatLocation(item)}</td>
                <td style={cellStyle}>
                  <ConfidenceFlag confidence={confidence} />
                </td>

                <td style={cellStyle}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                    {reviewStatusBadge(item.review_status)}
                    {isConfirmed && (
                      <span title="Confirmed item is immutable" style={{ color: 'var(--text-muted)', display: 'inline-flex' }}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                        </svg>
                      </span>
                    )}
                  </div>
                </td>

                <td style={cellStyle}>
                  {isConfirmed ? (
                    <span style={{ color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                      </svg>
                      Locked
                    </span>
                  ) : isRejected ? (
                    <span style={{ color: 'var(--text-muted)' }}>No actions</span>
                  ) : rejectingId === item.id ? (
                    <div style={{ display: 'grid', gap: '8px', minWidth: 220 }}>
                      <input
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        placeholder="Reason for rejection"
                        style={editStyle}
                      />
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <Button
                          variant="danger"
                          onClick={() => void submitReject(item.id)}
                          disabled={!rejectReason.trim() || isSavingRow}
                          loading={isSavingRow}
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
                          disabled={isSavingRow}
                          style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                      <Button
                        onClick={() => void handleConfirm(item.id)}
                        disabled={isSavingRow}
                        loading={isSavingRow && !rejectingId}
                        style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setRejectingId(item.id);
                          setRejectReason('');
                        }}
                        disabled={isSavingRow}
                        style={{ padding: '6px 10px', fontSize: 'var(--text-xs)' }}
                      >
                        Reject
                      </Button>
                    </div>
                  )}

                  {isSavingRow && (
                    <div style={{ marginTop: '6px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '10px' }}>
                      Saving...
                    </div>
                  )}
                </td>
              </tr>
            );
          })}

          {visibleItems.length === 0 && (
            <tr>
              <td colSpan={10} style={{ padding: 'var(--space-5)', color: 'var(--text-muted)', textAlign: 'center' }}>
                No line items match the current filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}
