import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  uploadFxRates,
  listFxRates,
  getTenantSettings,
  updateTenantSettings,
} from '../api/endpoints/admin';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { DataTable } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { EmptyState } from '../components/ui/EmptyState';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import type { ColumnDef } from '@tanstack/react-table';
import type { FxRate, TenantSettings, TenantSettingsUpdate } from '../types/api';

const PAGE_SIZE = 20;

const fxColumns: ColumnDef<FxRate, unknown>[] = [
  { accessorKey: 'from_currency', header: 'From' },
  { accessorKey: 'to_currency', header: 'To' },
  {
    accessorKey: 'rate',
    header: 'Rate',
    cell: ({ getValue }) => (getValue() as number).toFixed(6),
  },
  {
    accessorKey: 'rate_date',
    header: 'Date',
    cell: ({ getValue }) => new Date(getValue() as string).toLocaleDateString(),
  },
  { accessorKey: 'source', header: 'Source' },
];

export default function AdminPage() {
  const { currentUser } = useAuth();

  if (currentUser?.role !== 'ADMIN') {
    return (
      <EmptyState
        title="Access Denied"
        description="You must be an administrator to access this page."
      />
    );
  }

  return (
    <div className="animate-fadeIn">
      <h1
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 'var(--text-3xl)',
          fontWeight: 700,
          color: 'var(--text-primary)',
          marginBottom: 'var(--space-2)',
          letterSpacing: '-0.01em',
        }}
      >
        Administration
      </h1>
      <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 'var(--space-8)' }}>
        FX rates, matching thresholds, and tenant configuration
      </p>
      <FxRatesSection />
      <div style={{ marginTop: 'var(--space-8)' }}>
        <TenantSettingsSection />
      </div>
    </div>
  );
}

/* ── FX Rates Section ──────────────────────────────────────────── */

function FxRatesSection() {
  const { addToast } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);

  const [newRate, setNewRate] = useState({
    from_currency: '',
    to_currency: '',
    rate: '',
    rate_date: '',
    source: 'MANUAL_UPLOAD',
  });

  const { data: fxData, isLoading } = useQuery({
    queryKey: ['fxRates', page],
    queryFn: () => listFxRates({ page, page_size: PAGE_SIZE }),
  });

  const uploadMutation = useMutation({
    mutationFn: () =>
      uploadFxRates({
        rates: [
          {
            from_currency: newRate.from_currency.toUpperCase(),
            to_currency: newRate.to_currency.toUpperCase(),
            rate: parseFloat(newRate.rate),
            rate_date: newRate.rate_date,
            source: newRate.source,
          },
        ],
      }),
    onSuccess: (data) => {
      addToast('success', `Uploaded ${data.uploaded_count} FX rate(s)`);
      setNewRate({ from_currency: '', to_currency: '', rate: '', rate_date: '', source: 'MANUAL_UPLOAD' });
      queryClient.invalidateQueries({ queryKey: ['fxRates'] });
    },
    onError: (err: Error) => {
      // Show specific message for duplicate rate (409 Conflict)
      if ('status' in err && (err as any).status === 409) {
        addToast('error', 'An exchange rate for this currency pair and date already exists. Update the existing rate or use a different date.');
      } else {
        addToast('error', err.message);
      }
    },
  });

  const canSubmit =
    newRate.from_currency.length === 3 &&
    newRate.to_currency.length === 3 &&
    !isNaN(parseFloat(newRate.rate)) &&
    parseFloat(newRate.rate) > 0 &&
    newRate.rate_date;

  return (
    <Card>
      <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-5)' }}>
        FX Rates
      </h3>

      {/* Input form */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-4)',
          alignItems: 'end',
        }}
      >
        <InputField label="From Currency" value={newRate.from_currency} onChange={(v) => setNewRate({ ...newRate, from_currency: v })} placeholder="USD" maxLength={3} />
        <InputField label="To Currency" value={newRate.to_currency} onChange={(v) => setNewRate({ ...newRate, to_currency: v })} placeholder="EUR" maxLength={3} />
        <InputField label="Rate" value={newRate.rate} onChange={(v) => setNewRate({ ...newRate, rate: v })} placeholder="1.0850" type="number" />
        <InputField label="Rate Date" value={newRate.rate_date} onChange={(v) => setNewRate({ ...newRate, rate_date: v })} type="date" />
        <div>
          <Button
            onClick={() => uploadMutation.mutate()}
            loading={uploadMutation.isPending}
            disabled={!canSubmit}
          >
            Add Rate
          </Button>
        </div>
      </div>

      {/* FX rates table */}
      {isLoading ? (
        <LoadingSpinner size={24} />
      ) : !fxData?.data.length ? (
        <EmptyState title="No FX rates" description="Add exchange rates to resolve PENDING_FX_RATE findings." />
      ) : (
        <>
          <DataTable
            data={fxData.data}
            columns={fxColumns}
            getRowId={(row) => row.id}
          />
          {fxData.pagination && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <Pagination
                page={fxData.pagination.page}
                totalPages={fxData.pagination.total_pages}
                totalRecords={fxData.pagination.total_records}
                pageSize={fxData.pagination.page_size}
                onPageChange={setPage}
              />
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/* ── Tenant Settings Section ───────────────────────────────────── */

function TenantSettingsSection() {
  const { addToast } = useToast();
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: ['tenantSettings'],
    queryFn: getTenantSettings,
  });

  const [form, setForm] = useState<TenantSettingsUpdate>({});

  React.useEffect(() => {
    if (settings) {
      setForm({
        fuzzy_threshold: settings.fuzzy_threshold,
        duplicate_window_days: settings.duplicate_window_days,
        manual_review_threshold: settings.manual_review_threshold,
        base_currency: settings.base_currency,
      });
    }
  }, [settings]);

  const updateMutation = useMutation({
    mutationFn: () => updateTenantSettings(form),
    onSuccess: () => {
      addToast('success', 'Settings updated');
      queryClient.invalidateQueries({ queryKey: ['tenantSettings'] });
    },
    onError: (err: Error) => addToast('error', err.message),
  });

  if (isLoading) return <LoadingSpinner size={24} />;

  return (
    <Card>
      <h3 style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 'var(--space-5)' }}>
        Tenant Settings
      </h3>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-6)',
        }}
      >
        <InputField
          label="Fuzzy Match Threshold"
          value={form.fuzzy_threshold?.toString() ?? ''}
          onChange={(v) => setForm({ ...form, fuzzy_threshold: parseFloat(v) || 0 })}
          type="number"
        />
        <InputField
          label="Duplicate Window (days)"
          value={form.duplicate_window_days?.toString() ?? ''}
          onChange={(v) => setForm({ ...form, duplicate_window_days: parseInt(v) || 0 })}
          type="number"
        />
        <InputField
          label="Manual Review Threshold"
          value={form.manual_review_threshold?.toString() ?? ''}
          onChange={(v) => setForm({ ...form, manual_review_threshold: parseFloat(v) || 0 })}
          type="number"
        />
        <InputField
          label="Base Currency"
          value={form.base_currency ?? ''}
          onChange={(v) => setForm({ ...form, base_currency: v.toUpperCase() })}
          maxLength={3}
          placeholder="USD"
        />
      </div>

      {/* Abbreviation dictionary (read-only display) */}
      {settings?.abbreviation_dictionary && Object.keys(settings.abbreviation_dictionary).length > 0 && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 'var(--space-2)' }}>
            Abbreviation Dictionary
          </div>
          <pre
            style={{
              backgroundColor: 'var(--bg-base)',
              padding: 'var(--space-4)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              overflow: 'auto',
              maxHeight: 200,
              border: '1px solid var(--border-subtle)',
            }}
          >
            {JSON.stringify(settings.abbreviation_dictionary, null, 2)}
          </pre>
        </div>
      )}

      <Button
        onClick={() => updateMutation.mutate()}
        loading={updateMutation.isPending}
      >
        Save Settings
      </Button>

      {settings?.updated_at && (
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--space-3)' }}>
          Last updated: {new Date(settings.updated_at).toLocaleString()}
        </p>
      )}
    </Card>
  );
}

/* ── Shared input field ────────────────────────────────────────── */

function InputField({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  maxLength?: number;
}) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 'var(--space-2)' }}>
        {label}
      </div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        style={{
          width: '100%',
          backgroundColor: 'var(--bg-base)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          padding: 'var(--space-2) var(--space-3)',
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-sm)',
          outline: 'none',
          transition: 'border-color 200ms ease',
        }}
      />
    </div>
  );
}
