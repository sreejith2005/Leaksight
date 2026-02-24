import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getContracts, getContractVersions } from '../api/endpoints/contracts';
import { DataTable } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { Card } from '../components/ui/Card';
import { Modal } from '../components/ui/Modal';
import type { ColumnDef } from '@tanstack/react-table';
import type { Contract, ContractVersionsResponse } from '../types/api';

const PAGE_SIZE = 20;

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(amount);
}

const columns: ColumnDef<Contract, unknown>[] = [
  {
    accessorKey: 'vendor_name',
    header: 'Vendor',
    cell: ({ getValue }) => (
      <span style={{ color: 'var(--color-white)', fontWeight: 500 }}>{getValue() as string}</span>
    ),
  },
  {
    accessorKey: 'contract_ref',
    header: 'Reference',
    cell: ({ getValue }) => (getValue() as string | null) ?? '—',
  },
  {
    accessorKey: 'total_versions',
    header: 'Versions',
  },
  {
    accessorKey: 'active_version',
    header: 'Active Period',
    cell: ({ row }) => {
      const v = row.original.active_version;
      if (!v) return '—';
      return `${new Date(v.valid_from).toLocaleDateString()} – ${new Date(v.valid_to).toLocaleDateString()}`;
    },
  },
  {
    id: 'line_items',
    header: 'Line Items',
    cell: ({ row }) => row.original.active_version?.line_item_count ?? '—',
  },
  {
    accessorKey: 'created_at',
    header: 'Created',
    cell: ({ getValue }) => {
      const v = getValue() as string | null;
      return v ? new Date(v).toLocaleDateString() : '—';
    },
  },
];

export default function ContractsPage() {
  const [page, setPage] = useState(1);
  const [selectedContract, setSelectedContract] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['contracts', page],
    queryFn: () => getContracts({ page, page_size: PAGE_SIZE }),
  });

  const { data: versionData, isLoading: versionsLoading } = useQuery({
    queryKey: ['contractVersions', selectedContract],
    queryFn: () => getContractVersions(selectedContract!),
    enabled: !!selectedContract,
  });

  return (
    <div>
      <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)', marginBottom: 'var(--space-6)' }}>
        Contracts
      </h1>

      <Card style={{ padding: 0, overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
            <LoadingSpinner size={32} />
          </div>
        ) : !data?.data.length ? (
          <div style={{ padding: 'var(--space-8)' }}>
            <EmptyState title="No contracts found" description="Contracts are created from uploaded documents." />
          </div>
        ) : (
          <>
            <DataTable
              data={data.data}
              columns={columns}
              onRowClick={(row) => setSelectedContract(row.id)}
              getRowId={(row) => row.id}
            />
            {data.pagination && (
              <div style={{ padding: 'var(--space-4)' }}>
                <Pagination
                  page={data.pagination.page}
                  totalPages={data.pagination.total_pages}
                  totalRecords={data.pagination.total_records}
                  pageSize={data.pagination.page_size}
                  onPageChange={setPage}
                />
              </div>
            )}
          </>
        )}
      </Card>

      {/* Contract versions modal */}
      <Modal
        open={!!selectedContract}
        onClose={() => setSelectedContract(null)}
        title={versionData?.vendor_name ? `${versionData.vendor_name} — Contract Versions` : 'Contract Versions'}
      >
        {versionsLoading ? (
          <LoadingSpinner size={24} />
        ) : !versionData?.versions.length ? (
          <p style={{ color: 'var(--color-muted)', fontSize: '14px' }}>No versions found.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
            {versionData.versions.map((ver) => (
              <Card key={ver.id}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
                  <span style={{ color: 'var(--color-white)', fontWeight: 600, fontSize: '14px' }}>
                    Version {ver.version_number}
                  </span>
                  <span style={{ color: 'var(--color-muted)', fontSize: '12px' }}>
                    {new Date(ver.valid_from).toLocaleDateString()} – {new Date(ver.valid_to).toLocaleDateString()}
                  </span>
                </div>
                {ver.line_items.length > 0 && (
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      fontSize: '13px',
                    }}
                  >
                    <thead>
                      <tr>
                        {['Item', 'Unit', 'Unit Price', 'Currency'].map((h) => (
                          <th
                            key={h}
                            style={{
                              textAlign: 'left',
                              padding: 'var(--space-2)',
                              color: 'var(--color-muted)',
                              fontSize: '11px',
                              textTransform: 'uppercase',
                              borderBottom: '1px solid var(--color-border)',
                            }}
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {ver.line_items.map((item) => (
                        <tr key={item.id}>
                          <td style={{ padding: 'var(--space-2)', color: 'var(--color-grey)' }}>{item.item_desc}</td>
                          <td style={{ padding: 'var(--space-2)', color: 'var(--color-grey)' }}>{item.unit}</td>
                          <td style={{ padding: 'var(--space-2)', color: 'var(--color-orange)', fontWeight: 600 }}>
                            {formatCurrency(item.unit_price, item.currency)}
                          </td>
                          <td style={{ padding: 'var(--space-2)', color: 'var(--color-grey)' }}>{item.currency}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}
