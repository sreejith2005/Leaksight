import React from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { listStructuringExports } from '../../api/structuring';
import { Card } from '../../components/ui/Card';

export default function StructuringExportPage() {
  const { runId = '' } = useParams();
  const { data, isLoading } = useQuery({
    queryKey: ['structuringExports', runId],
    queryFn: () => listStructuringExports(runId),
    enabled: !!runId,
  });

  return (
    <div className="animate-fadeIn">
      <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)' }}>Structuring Exports</h1>
      <Card style={{ marginTop: 'var(--space-4)' }}>
        {isLoading ? (
          <div>Loading exports...</div>
        ) : (
          <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
            {data?.data.map((exp) => (
              <div key={exp.id} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 'var(--space-2)' }}>
                <span>{exp.export_format}</span>
                <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>{exp.file_path || 'N/A'}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
