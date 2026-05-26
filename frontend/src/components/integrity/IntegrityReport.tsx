import React from 'react';
import type { IntegrityComparisonStatus, IntegrityReport as IntegrityReportData } from '../../api/integrity';
import { RiskBadge } from './RiskBadge';
import { VersionDiff } from './VersionDiff';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { SectionHeader } from '../ui/SectionHeader';

interface IntegrityReportProps {
  report: IntegrityReportData;
  onReanalyze: () => void;
  isReanalyzing: boolean;
  isPollingForUpdate: boolean;
}

const COMPARISON_TEXT: Record<IntegrityComparisonStatus, string> = {
  NEW: 'First time seen - no comparison available',
  UNCHANGED: 'Document matches original - no changes detected',
  MODIFIED: 'Document has been modified since original upload',
  INCONCLUSIVE: 'Analysis inconclusive - review manually',
};

const STATUS_STYLES: Record<IntegrityComparisonStatus, { color: string; background: string }> = {
  NEW: {
    color: 'var(--color-info)',
    background: 'var(--color-info-dim)',
  },
  UNCHANGED: {
    color: 'var(--color-success)',
    background: 'var(--color-success-dim)',
  },
  MODIFIED: {
    color: 'var(--color-danger)',
    background: 'var(--color-danger-dim)',
  },
  INCONCLUSIVE: {
    color: 'var(--color-warning)',
    background: 'var(--color-warning-dim)',
  },
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  return new Date(value).toLocaleString();
}

function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'number') {
    return new Intl.NumberFormat('en-US').format(value);
  }
  return String(value);
}

function hasAnomaly(anomalies: string[], key: 'creation_date' | 'modification_date' | 'author' | 'software' | 'page_count'): boolean {
  if (key === 'creation_date') {
    return anomalies.includes('modification_date_precedes_creation_date');
  }
  if (key === 'modification_date') {
    return (
      anomalies.includes('modification_date_precedes_creation_date')
      || anomalies.includes('unusually_old_modification_date')
    );
  }
  if (key === 'author') {
    return anomalies.includes('missing_author_metadata');
  }
  if (key === 'software') {
    return anomalies.includes('software_mismatch_for_invoice');
  }
  return false;
}

function MetadataRow({
  label,
  value,
  highlighted,
}: {
  label: string;
  value: unknown;
  highlighted?: boolean;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(150px, 220px) 1fr',
        gap: 'var(--space-4)',
        padding: 'var(--space-3) var(--space-4)',
        borderRadius: 'var(--radius-md)',
        border: highlighted ? '1px solid var(--color-warning)' : '1px solid var(--border-subtle)',
        backgroundColor: highlighted ? 'var(--color-warning-dim)' : 'var(--bg-surface-2)',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: highlighted ? 'var(--color-warning)' : 'var(--text-secondary)',
        }}
      >
        {label}
      </span>
      <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>
        {formatMetadataValue(value)}
      </span>
    </div>
  );
}

export function IntegrityReport({
  report,
  onReanalyze,
  isReanalyzing,
  isPollingForUpdate,
}: IntegrityReportProps) {
  const anomalies = Array.isArray(report.metadata?.anomalies)
    ? report.metadata.anomalies.filter((value): value is string => typeof value === 'string')
    : [];
  const statusStyle = STATUS_STYLES[report.comparison_status];

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Card>
        <SectionHeader>Summary</SectionHeader>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 'var(--space-4)',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
            <h1
              style={{
                margin: 0,
                fontFamily: 'var(--font-display)',
                fontSize: 'var(--text-3xl)',
                color: 'var(--text-primary)',
              }}
            >
              {report.filename}
            </h1>
            <div
              style={{
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-sm)',
                color: 'var(--text-secondary)',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              {report.doc_type}
            </div>
          </div>
          <RiskBadge risk_score={report.risk_score} risk_level={report.risk_level} size="lg" />
        </div>

        <div
          style={{
            marginTop: 'var(--space-5)',
            display: 'grid',
            gap: 'var(--space-3)',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              width: 'fit-content',
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: statusStyle.background,
              color: statusStyle.color,
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}
          >
            {report.comparison_status.replace(/_/g, ' ')}
          </div>
          <div style={{ color: 'var(--text-primary)', lineHeight: 1.7 }}>
            {COMPARISON_TEXT[report.comparison_status]}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
            Analyzed at: {formatDateTime(report.analyzed_at)}
          </div>
        </div>
      </Card>

      {report.flags.length > 0 && (
        <Card>
          <SectionHeader>Flags</SectionHeader>
          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
            {report.flags.map((flag) => (
              <div
                key={flag}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 'var(--space-3)',
                  padding: 'var(--space-3) var(--space-4)',
                  backgroundColor: 'var(--bg-surface-2)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="var(--color-warning)"
                  strokeWidth="2"
                  style={{ flexShrink: 0, marginTop: '2px' }}
                >
                  <path d="M12 9v4" />
                  <path d="M12 17h.01" />
                  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
                </svg>
                <span style={{ color: 'var(--text-primary)', lineHeight: 1.6 }}>{flag}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {report.comparison_status === 'MODIFIED' && (
        <Card>
          <SectionHeader>Numeric Changes</SectionHeader>
          <VersionDiff changes={report.numeric_changes} />
        </Card>
      )}

      <Card>
        <SectionHeader>Metadata</SectionHeader>
        <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
          <MetadataRow
            label="Creation Date"
            value={report.metadata?.creation_date}
            highlighted={hasAnomaly(anomalies, 'creation_date')}
          />
          <MetadataRow
            label="Modification Date"
            value={report.metadata?.modification_date}
            highlighted={hasAnomaly(anomalies, 'modification_date')}
          />
          <MetadataRow
            label="Author"
            value={report.metadata?.author}
            highlighted={hasAnomaly(anomalies, 'author')}
          />
          <MetadataRow
            label="Software"
            value={report.metadata?.software}
            highlighted={hasAnomaly(anomalies, 'software')}
          />
          <MetadataRow
            label="Page Count"
            value={report.metadata?.page_count}
            highlighted={hasAnomaly(anomalies, 'page_count')}
          />
        </div>
      </Card>

      <Card>
        <SectionHeader>Re-Analyze</SectionHeader>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--space-4)',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {isPollingForUpdate
              ? 'Polling for a refreshed report...'
              : 'Queue the latest integrity analysis for this document.'}
          </div>
          <Button
            onClick={onReanalyze}
            loading={isReanalyzing || isPollingForUpdate}
            disabled={isReanalyzing || isPollingForUpdate}
          >
            {isPollingForUpdate ? 'Waiting for Update' : 'Re-Analyze'}
          </Button>
        </div>
      </Card>
    </div>
  );
}
