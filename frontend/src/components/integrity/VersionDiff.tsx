import React from 'react';
import type { SortingState, ColumnDef } from '@tanstack/react-table';
import type { NumericChange } from '../../api/integrity';
import { DataTable } from '../ui/DataTable';

interface VersionDiffProps {
  changes: NumericChange[];
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatChangePercent(value: number): string {
  return `${new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)}%`;
}

function getChangeColor(changePct: number): string {
  if (changePct > 10) {
    return 'var(--color-danger)';
  }
  if (changePct > 0) {
    return 'var(--color-warning)';
  }
  return 'var(--color-success)';
}

export function VersionDiff({ changes }: VersionDiffProps) {
  const [sorting, setSorting] = React.useState<SortingState>([{ id: 'change_pct', desc: true }]);

  const columns = React.useMemo<ColumnDef<NumericChange>[]>(
    () => [
      {
        accessorKey: 'context',
        header: 'Context',
        cell: ({ getValue }) => (
          <span style={{ whiteSpace: 'normal', lineHeight: 1.5 }}>
            {String(getValue() || 'Unlabeled value')}
          </span>
        ),
      },
      {
        accessorKey: 'previous_value',
        header: 'Previous Value',
        cell: ({ getValue }) => formatNumber(Number(getValue() || 0)),
      },
      {
        accessorKey: 'current_value',
        header: 'Current Value',
        cell: ({ getValue }) => formatNumber(Number(getValue() || 0)),
      },
      {
        accessorKey: 'change_pct',
        header: 'Change %',
        cell: ({ getValue }) => {
          const changePct = Number(getValue() || 0);
          return (
            <span style={{ color: getChangeColor(changePct), fontWeight: 700 }}>
              {formatChangePercent(changePct)}
            </span>
          );
        },
      },
    ],
    [],
  );

  if (!changes.length) {
    return (
      <div
        style={{
          padding: 'var(--space-6)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          backgroundColor: 'var(--bg-surface-2)',
          color: 'var(--text-secondary)',
        }}
      >
        No numeric changes detected
      </div>
    );
  }

  return (
    <div style={{ overflow: 'hidden', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
      <DataTable
        data={changes}
        columns={columns}
        sorting={sorting}
        onSortingChange={setSorting}
        getRowId={(row) => `${row.context}-${row.previous_value}-${row.current_value}`}
      />
    </div>
  );
}
