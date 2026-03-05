import React from 'react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  getSortedRowModel,
  OnChangeFn,
} from '@tanstack/react-table';

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, any>[];
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  onRowClick?: (row: T) => void;
  getRowId?: (row: T) => string;
  manualSorting?: boolean;
}

export function DataTable<T>({
  data,
  columns,
  sorting,
  onSortingChange,
  onRowClick,
  getRowId,
  manualSorting = false,
}: DataTableProps<T>) {
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: manualSorting ? undefined : getSortedRowModel(),
    manualSorting,
    getRowId,
  });

  return (
    <div style={{ overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
        }}
      >
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  onClick={header.column.getCanSort() ? header.column.getToggleSortingHandler() : undefined}
                  style={{
                    padding: 'var(--space-3) var(--space-4)',
                    textAlign: 'left',
                    fontWeight: 600,
                    fontSize: 'var(--text-xs)',
                    textTransform: 'uppercase' as const,
                    letterSpacing: '0.06em',
                    color: 'var(--text-secondary)',
                    backgroundColor: 'var(--bg-surface-1)',
                    borderBottom: '1px solid var(--border-default)',
                    cursor: header.column.getCanSort() ? 'pointer' : 'default',
                    userSelect: header.column.getCanSort() ? 'none' : undefined,
                    whiteSpace: 'nowrap',
                  }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getCanSort() && (
                      <span style={{ opacity: header.column.getIsSorted() ? 1 : 0.3 }}>
                        {{
                          asc: ' ▲',
                          desc: ' ▼',
                        }[header.column.getIsSorted() as string] ?? ' ⇅'}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                style={{
                  padding: 'var(--space-12)',
                  textAlign: 'center',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-body)',
                  fontSize: 'var(--text-sm)',
                }}
              >
                No data available
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row, i) => (
              <tr
                key={row.id}
                onClick={() => onRowClick?.(row.original)}
                style={{
                  backgroundColor: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-surface-2)',
                  cursor: onRowClick ? 'pointer' : 'default',
                  transition: 'background-color 150ms ease',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--bg-surface-3)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor =
                    i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-surface-2)';
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    style={{
                      padding: 'var(--space-3) var(--space-4)',
                      color: 'var(--text-primary)',
                      borderBottom: '1px solid var(--border-subtle)',
                      whiteSpace: 'nowrap',
                      lineHeight: '1.6',
                    }}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
