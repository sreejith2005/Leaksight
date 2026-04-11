import React from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import {
  createSubject,
  listSubjects,
  type ComplianceSummary,
  type SubjectCreate,
  type SubjectResponse,
} from '../../api/revalidation';
import { ComplianceMeter } from '../../components/revalidation/ComplianceMeter';
import { SlideOverPanel } from '../../components/revalidation/SlideOverPanel';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { DataTable } from '../../components/ui/DataTable';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { FormField } from '../../components/ui/FormField';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { SectionHeader } from '../../components/ui/SectionHeader';
import { useToast } from '../../context/ToastContext';

type SubjectType = 'EMPLOYEE' | 'VENDOR';

function getInitialFormState(subjectType: SubjectType): SubjectCreate {
  return {
    subject_type: subjectType,
    name: '',
    identifier: '',
    department: '',
    email: '',
  };
}

function getStatusMeta(summary: ComplianceSummary | null) {
  if (!summary) {
    return {
      label: 'Pending Setup',
      color: 'var(--text-secondary)',
      background: 'var(--bg-surface-2)',
    };
  }

  if (summary.expired > 0) {
    return {
      label: 'Action Required',
      color: 'var(--color-danger)',
      background: 'var(--color-danger-dim)',
    };
  }

  if (summary.expiring_soon > 0) {
    return {
      label: 'Expiring Soon',
      color: 'var(--color-warning)',
      background: 'var(--color-warning-dim)',
    };
  }

  if (summary.missing > 0) {
    return {
      label: 'Incomplete',
      color: 'var(--color-warning)',
      background: 'var(--color-warning-dim)',
    };
  }

  return {
    label: 'Compliant',
    color: 'var(--color-success)',
    background: 'var(--color-success-dim)',
  };
}

function SubjectTypeTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: active ? '1px solid var(--accent)' : '1px solid var(--border-default)',
        backgroundColor: active ? 'var(--accent-dim)' : 'var(--bg-surface-1)',
        color: active ? 'var(--accent)' : 'var(--text-secondary)',
        borderRadius: 'var(--radius-full)',
        padding: '8px 16px',
        fontSize: 'var(--text-sm)',
        fontWeight: 600,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
}

export default function SubjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isPanelOpen, setIsPanelOpen] = React.useState(false);
  const [formState, setFormState] = React.useState<SubjectCreate>(getInitialFormState('EMPLOYEE'));

  const activeTab: SubjectType = searchParams.get('type') === 'VENDOR' ? 'VENDOR' : 'EMPLOYEE';

  const subjectsQuery = useQuery({
    queryKey: ['revalidationSubjects', activeTab],
    queryFn: () => listSubjects({ subject_type: activeTab }),
  });

  const createSubjectMutation = useMutation({
    mutationFn: createSubject,
    onSuccess: async (subject) => {
      addToast('success', 'Subject saved');
      setIsPanelOpen(false);
      setSearchParams({ type: subject.subject_type });
      await queryClient.invalidateQueries({ queryKey: ['revalidationSubjects'] });
    },
    onError: (error: Error) => {
      addToast('error', `Failed to save subject: ${error.message}`);
    },
  });

  const columns: ColumnDef<SubjectResponse>[] = [
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
          {row.original.name}
        </span>
      ),
    },
    {
      accessorKey: 'identifier',
      header: 'Identifier',
    },
    {
      id: 'department',
      header: 'Department',
      cell: ({ row }) => row.original.department || '—',
    },
    {
      id: 'compliance',
      header: 'Compliance',
      cell: ({ row }) => {
        const summary = row.original.compliance_summary;
        return (
          <ComplianceMeter
            uploaded={summary?.uploaded ?? 0}
            total_required={summary?.total_required ?? 0}
            expired={summary?.expired ?? 0}
            expiring_soon={summary?.expiring_soon ?? 0}
          />
        );
      },
    },
    {
      id: 'status',
      header: 'Status',
      cell: ({ row }) => {
        const status = getStatusMeta(row.original.compliance_summary);
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              borderRadius: 'var(--radius-full)',
              padding: '4px 10px',
              backgroundColor: status.background,
              color: status.color,
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              letterSpacing: '0.04em',
              whiteSpace: 'nowrap',
            }}
          >
            {status.label}
          </span>
        );
      },
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => (
        <Button
          variant="secondary"
          onClick={(event) => {
            event.stopPropagation();
            navigate(`/revalidation/subjects/${row.original.id}`);
          }}
          style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}
        >
          Open
        </Button>
      ),
    },
  ];

  function openCreatePanel() {
    setFormState(getInitialFormState(activeTab));
    setIsPanelOpen(true);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await createSubjectMutation.mutateAsync({
      ...formState,
      department: formState.subject_type === 'EMPLOYEE' ? formState.department || null : null,
      email: formState.email || null,
    });
  }

  return (
    <div className="animate-fadeIn" style={{ display: 'grid', gap: 'var(--space-6)' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: 'var(--space-4)',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
          <SectionHeader>Document Revalidation</SectionHeader>
          <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
            Track employees and vendors, then review their document compliance status.
          </p>
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <SubjectTypeTab
              label="Employees"
              active={activeTab === 'EMPLOYEE'}
              onClick={() => setSearchParams({ type: 'EMPLOYEE' })}
            />
            <SubjectTypeTab
              label="Vendors"
              active={activeTab === 'VENDOR'}
              onClick={() => setSearchParams({ type: 'VENDOR' })}
            />
          </div>
        </div>
        <Button onClick={openCreatePanel}>Add Subject</Button>
      </div>

      {subjectsQuery.isLoading ? (
        <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-12)' }}>
          <LoadingSpinner size={32} />
        </Card>
      ) : subjectsQuery.error ? (
        <ErrorMessage message={subjectsQuery.error.message} />
      ) : !subjectsQuery.data?.data.length ? (
        <Card style={{ padding: 0 }}>
          <EmptyState
            title={`No ${activeTab === 'EMPLOYEE' ? 'employees' : 'vendors'} yet`}
            description="Add a subject to start tracking required compliance documents."
            actionLabel="Add Subject"
            onAction={openCreatePanel}
          />
        </Card>
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <DataTable
            data={subjectsQuery.data.data}
            columns={columns}
            getRowId={(row) => row.id}
            onRowClick={(row) => navigate(`/revalidation/subjects/${row.id}`)}
          />
        </Card>
      )}

      <SlideOverPanel
        open={isPanelOpen}
        onClose={() => setIsPanelOpen(false)}
        title="Add Subject"
        subtitle="Create an employee or vendor profile and start tracking its required compliance documents."
      >
        <form onSubmit={handleSubmit} style={{ display: 'grid', gap: 'var(--space-5)' }}>
          <FormField label="Subject Type">
            <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
              {(['EMPLOYEE', 'VENDOR'] as SubjectType[]).map((subjectType) => (
                <label
                  key={subjectType}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 'var(--space-2)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <input
                    type="radio"
                    name="subject_type"
                    checked={formState.subject_type === subjectType}
                    onChange={() => setFormState((current) => ({ ...current, subject_type: subjectType }))}
                  />
                  {subjectType === 'EMPLOYEE' ? 'Employee' : 'Vendor'}
                </label>
              ))}
            </div>
          </FormField>

          <FormField label="Name">
            <input
              required
              value={formState.name}
              onChange={(event) => setFormState((current) => ({ ...current, name: event.target.value }))}
              style={inputStyle}
            />
          </FormField>

          <FormField label={formState.subject_type === 'EMPLOYEE' ? 'Employee ID' : 'GST / Vendor Code'}>
            <input
              required
              value={formState.identifier}
              onChange={(event) => setFormState((current) => ({ ...current, identifier: event.target.value }))}
              style={inputStyle}
            />
          </FormField>

          {formState.subject_type === 'EMPLOYEE' ? (
            <FormField label="Department">
              <input
                value={formState.department || ''}
                onChange={(event) => setFormState((current) => ({ ...current, department: event.target.value }))}
                style={inputStyle}
              />
            </FormField>
          ) : null}

          <FormField label="Email">
            <input
              type="email"
              value={formState.email || ''}
              onChange={(event) => setFormState((current) => ({ ...current, email: event.target.value }))}
              style={inputStyle}
            />
          </FormField>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)' }}>
            <Button type="button" variant="secondary" onClick={() => setIsPanelOpen(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              loading={createSubjectMutation.isPending}
              disabled={createSubjectMutation.isPending}
            >
              Save
            </Button>
          </div>
        </form>
      </SlideOverPanel>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--border-default)',
  backgroundColor: 'var(--bg-surface-1)',
  color: 'var(--text-primary)',
};
