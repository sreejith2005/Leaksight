import React from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../ui/Card';
import { StatusBadge } from '../ui/StatusBadge';
import type { StructuringRun } from '../../api/structuring';

interface StructuringRunCardProps {
  run: StructuringRun;
}

export function StructuringRunCard({ run }: StructuringRunCardProps) {
  return (
    <Card style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-4)' }}>
      <div>
        <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--text-primary)' }}>
          {run.run_label || 'Untitled Structuring Run'}
        </div>
        <div style={{ marginTop: '6px', display: 'flex', gap: 'var(--space-4)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          <span>{run.total_documents} docs</span>
          <span>{run.total_line_items_found} items</span>
          <span>{run.total_clauses_found} clauses</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        <StatusBadge status={run.status as any} />
        <Link to={`/structuring/${run.id}`} style={{ color: 'var(--accent)', fontFamily: 'var(--font-body)', fontWeight: 600, textDecoration: 'none' }}>
          View
        </Link>
      </div>
    </Card>
  );
}
