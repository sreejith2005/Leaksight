import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { useParams } from 'react-router-dom';
import { getToken } from '../../api/client';
import { uploadDocument } from '../../api/endpoints/ingest';
import {
  attachDocument,
  createRevalidationDoc,
  getDocCatalog,
  getRevalidationDoc,
  getSubject,
  getSubjectDocuments,
  updateDatesManually,
  type DocCatalogResponse,
  type ManualDateUpdate,
  type RevalidationDocResponse,
} from '../../api/revalidation';
import { ComplianceMeter } from '../../components/revalidation/ComplianceMeter';
import { SlideOverPanel } from '../../components/revalidation/SlideOverPanel';
import { StatusBadge } from '../../components/revalidation/StatusBadge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorMessage } from '../../components/ui/ErrorMessage';
import { FormField } from '../../components/ui/FormField';
import { LoadingSpinner } from '../../components/ui/LoadingSpinner';
import { SectionHeader } from '../../components/ui/SectionHeader';
import { formatDateValue } from '../../components/leakage/leakageDetailUtils';
import { useToast } from '../../context/ToastContext';

type CreateMode = 'upload' | 'manual';
interface EditState { id: string; issue_date: string; expiry_date: string; has_expiry: boolean; notes: string; }

const VALID_INGEST_DOC_TYPES = new Set(['INVOICE', 'CONTRACT', 'PO', 'GRN']);
const DOCUMENT_VIEW_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';
const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--border-default)',
  backgroundColor: 'var(--bg-surface-1)',
  color: 'var(--text-primary)',
};
const textareaStyle: React.CSSProperties = { ...inputStyle, resize: 'vertical', minHeight: 120 };
const optionStyle: React.CSSProperties = {
  border: '1px solid var(--border-default)',
  backgroundColor: 'var(--bg-surface-1)',
  color: 'var(--text-secondary)',
  borderRadius: 'var(--radius-md)',
  padding: '10px 14px',
  cursor: 'pointer',
  fontWeight: 600,
};
const selectedOptionStyle: React.CSSProperties = {
  ...optionStyle,
  border: '1px solid var(--accent)',
  backgroundColor: 'var(--accent-dim)',
  color: 'var(--accent)',
};
const tableHeaderStyle: React.CSSProperties = {
  padding: 'var(--space-3) var(--space-4)',
  textAlign: 'left',
  fontWeight: 600,
  fontSize: 'var(--text-xs)',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--text-secondary)',
  backgroundColor: 'var(--bg-surface-1)',
  borderBottom: '1px solid var(--border-default)',
  whiteSpace: 'nowrap',
};
const tableCellStyle: React.CSSProperties = {
  padding: 'var(--space-3) var(--space-4)',
  color: 'var(--text-primary)',
  borderBottom: '1px solid var(--border-subtle)',
  whiteSpace: 'nowrap',
  lineHeight: 1.6,
};

function getDocumentQueryKey(subjectId: string | undefined) {
  return ['revalidationSubjectDocuments', subjectId];
}

function getSubjectTypeBadge(subjectType: string) {
  return subjectType === 'EMPLOYEE'
    ? { label: 'Employee', color: 'var(--color-success)', background: 'var(--color-success-dim)' }
    : { label: 'Vendor', color: 'var(--accent)', background: 'var(--accent-dim)' };
}

function getDaysDisplay(documentItem: RevalidationDocResponse) {
  if (
    documentItem.status === 'NO_EXPIRY'
    || documentItem.status === 'PENDING_UPLOAD'
    || documentItem.status === 'REVALIDATION_PENDING'
    || documentItem.days_until_expiry === null
  ) {
    return { label: '—', color: 'var(--text-secondary)' };
  }
  if (documentItem.status === 'EXPIRED') return { label: `${documentItem.days_until_expiry} days`, color: 'var(--color-danger)' };
  if (documentItem.status === 'EXPIRING_SOON') return { label: `${documentItem.days_until_expiry} days`, color: 'var(--color-warning)' };
  return { label: `${documentItem.days_until_expiry} days`, color: 'var(--color-success)' };
}

function getEditState(documentItem: RevalidationDocResponse): EditState {
  return {
    id: documentItem.id,
    issue_date: documentItem.issue_date || '',
    expiry_date: documentItem.expiry_date || '',
    has_expiry: documentItem.has_expiry,
    notes: documentItem.notes || '',
  };
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function SubjectDetailPage() {
  const { subjectId } = useParams();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const fileInputRefs = React.useRef<Record<string, HTMLInputElement | null>>({});
  const [isPanelOpen, setIsPanelOpen] = React.useState(false);
  const [selectedCatalogId, setSelectedCatalogId] = React.useState('');
  const [createMode, setCreateMode] = React.useState<CreateMode>('upload');
  const [panelFile, setPanelFile] = React.useState<File | null>(null);
  const [editingDocument, setEditingDocument] = React.useState<EditState | null>(null);
  const [uploadingDocId, setUploadingDocId] = React.useState<string | null>(null);
  const [viewingDocumentId, setViewingDocumentId] = React.useState<string | null>(null);

  const subjectQuery = useQuery({
    queryKey: ['revalidationSubject', subjectId],
    queryFn: () => getSubject(subjectId!),
    enabled: Boolean(subjectId),
  });
  const documentsQuery = useQuery({
    queryKey: getDocumentQueryKey(subjectId),
    queryFn: () => getSubjectDocuments(subjectId!),
    enabled: Boolean(subjectId),
  });
  const catalogQuery = useQuery({
    queryKey: ['revalidationCatalog', subjectQuery.data?.subject_type],
    queryFn: () => getDocCatalog(subjectQuery.data?.subject_type),
    enabled: Boolean(subjectQuery.data?.subject_type),
  });

  React.useEffect(() => {
    if (isPanelOpen && catalogQuery.data?.length) {
      setSelectedCatalogId(catalogQuery.data[0].id);
      setCreateMode('upload');
      setPanelFile(null);
    }
  }, [catalogQuery.data, isPanelOpen]);

  const createDocumentMutation = useMutation({
    mutationFn: (catalogItem: DocCatalogResponse) => createRevalidationDoc(subjectId!, {
      subject_id: subjectId!,
      category: catalogItem.category,
      display_name: catalogItem.display_name,
      has_expiry: catalogItem.has_expiry,
      alert_days_before: catalogItem.alert_days_before,
      notes: null,
    }),
  });
  const updateDatesMutation = useMutation({
    mutationFn: ({ revalDocId, data }: { revalDocId: string; data: ManualDateUpdate }) => updateDatesManually(revalDocId, data),
  });

  function upsertDocument(documentItem: RevalidationDocResponse) {
    queryClient.setQueryData<RevalidationDocResponse[]>(getDocumentQueryKey(subjectId), (current) => {
      const remaining = (current || []).filter((existing) => existing.id !== documentItem.id);
      return [documentItem, ...remaining];
    });
  }

  async function runUploadFlow(revalidationDoc: RevalidationDocResponse, file: File) {
    const uploadDocType = VALID_INGEST_DOC_TYPES.has('OTHER') ? 'OTHER' : 'CONTRACT';
    setUploadingDocId(revalidationDoc.id);
    try {
      const uploadedDocument = await uploadDocument(file, uploadDocType);
      let latestDocument = await attachDocument(revalidationDoc.id, uploadedDocument.document_id);
      upsertDocument(latestDocument);
      for (let attempt = 0; attempt < 10; attempt += 1) {
        await wait(3000);
        latestDocument = await getRevalidationDoc(revalidationDoc.id);
        upsertDocument(latestDocument);
        if (latestDocument.status !== 'REVALIDATION_PENDING') break;
      }
      await queryClient.invalidateQueries({ queryKey: getDocumentQueryKey(subjectId) });
      if (latestDocument.status === 'REVALIDATION_PENDING') {
        addToast('warning', 'Date extraction is still pending. You can enter dates manually if needed.');
      } else {
        addToast('success', 'Document attached');
      }
    } catch (error) {
      addToast('error', `Upload failed: ${(error as Error).message}`);
      await queryClient.invalidateQueries({ queryKey: getDocumentQueryKey(subjectId) });
    } finally {
      setUploadingDocId(null);
    }
  }

  async function handleCreateDocument(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedCatalogItem = catalogQuery.data?.find((catalogItem) => catalogItem.id === selectedCatalogId);
    if (!selectedCatalogItem) {
      addToast('error', 'Select a document category first.');
      return;
    }
    if (createMode === 'upload' && !panelFile) {
      addToast('error', 'Select a file to upload.');
      return;
    }
    try {
      const createdDocument = await createDocumentMutation.mutateAsync(selectedCatalogItem);
      upsertDocument(createdDocument);
      setIsPanelOpen(false);
      if (createMode === 'manual') {
        setEditingDocument(getEditState(createdDocument));
        addToast('success', 'Document slot created');
      } else if (panelFile) {
        await runUploadFlow(createdDocument, panelFile);
      }
    } catch (error) {
      addToast('error', `Failed to create document slot: ${(error as Error).message}`);
    }
  }

  async function handleSaveDates(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingDocument) return;
    try {
      const updatedDocument = await updateDatesMutation.mutateAsync({
        revalDocId: editingDocument.id,
        data: {
          issue_date: editingDocument.issue_date || null,
          expiry_date: editingDocument.has_expiry ? editingDocument.expiry_date || null : null,
          has_expiry: editingDocument.has_expiry,
          notes: editingDocument.notes || null,
        },
      });
      upsertDocument(updatedDocument);
      setEditingDocument(null);
      await queryClient.invalidateQueries({ queryKey: getDocumentQueryKey(subjectId) });
      addToast('success', 'Dates updated');
    } catch (error) {
      addToast('error', `Failed to save dates: ${(error as Error).message}`);
    }
  }

  async function openDocumentInNewTab(documentId: string) {
    const token = getToken();
    if (!token) {
      addToast('error', 'Session expired');
      return;
    }
    setViewingDocumentId(documentId);
    try {
      const response = await fetch(`${DOCUMENT_VIEW_BASE_URL}/documents/${documentId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      window.open(objectUrl, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
    } catch (error) {
      addToast('error', `Unable to open document: ${(error as Error).message}`);
    } finally {
      setViewingDocumentId(null);
    }
  }

  const columns: ColumnDef<RevalidationDocResponse>[] = [
    { accessorKey: 'display_name', header: 'Document Type' },
    { accessorKey: 'status', header: 'Status', cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    { accessorKey: 'issue_date', header: 'Issue Date', cell: ({ row }) => formatDateValue(row.original.issue_date) },
    { accessorKey: 'expiry_date', header: 'Expiry Date', cell: ({ row }) => formatDateValue(row.original.expiry_date) },
    {
      id: 'days',
      header: 'Days',
      cell: ({ row }) => {
        const days = getDaysDisplay(row.original);
        return <span style={{ color: days.color, fontWeight: 700 }}>{days.label}</span>;
      },
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => {
        const documentItem = row.original;
        const isUploading = uploadingDocId === documentItem.id;
        const isSaving = updateDatesMutation.isPending && updateDatesMutation.variables?.revalDocId === documentItem.id;
        const isViewing = viewingDocumentId === documentItem.document_id;
        return (
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            {!documentItem.document_id ? (
              <>
                <input
                  ref={(node) => {
                    fileInputRefs.current[documentItem.id] = node;
                  }}
                  type="file"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) void runUploadFlow(documentItem, file);
                  }}
                />
                <Button
                  variant="secondary"
                  onClick={(event) => {
                    event.stopPropagation();
                    fileInputRefs.current[documentItem.id]?.click();
                  }}
                  loading={isUploading}
                  disabled={isUploading}
                  style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}
                >
                  Upload File
                </Button>
              </>
            ) : null}
            <Button
              variant="secondary"
              onClick={(event) => {
                event.stopPropagation();
                setEditingDocument(getEditState(documentItem));
              }}
              loading={isSaving}
              disabled={isSaving}
              style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}
            >
              Enter Dates
            </Button>
            {documentItem.document_id ? (
              <Button
                variant="secondary"
                onClick={(event) => {
                  event.stopPropagation();
                  void openDocumentInNewTab(documentItem.document_id!);
                }}
                loading={isViewing}
                disabled={isViewing}
                style={{ padding: '6px 12px', fontSize: 'var(--text-xs)' }}
              >
                View File
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];

  const documents = documentsQuery.data || [];
  const table = useReactTable({ data: documents, columns, getCoreRowModel: getCoreRowModel(), getRowId: (row) => row.id });

  if (subjectQuery.isLoading || documentsQuery.isLoading) {
    return <Card style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-12)' }}><LoadingSpinner size={32} /></Card>;
  }
  if (subjectQuery.error) return <ErrorMessage message={subjectQuery.error.message} />;
  if (documentsQuery.error) return <ErrorMessage message={documentsQuery.error.message} />;
  if (!subjectQuery.data) return <ErrorMessage message="Subject not found." />;

  const subject = subjectQuery.data;
  const subjectTypeBadge = getSubjectTypeBadge(subject.subject_type);
  const complianceSummary = subject.compliance_summary;

  return (
    <div className="animate-fadeIn" style={{ display: 'grid', gap: 'var(--space-6)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
          <SectionHeader>Document Revalidation</SectionHeader>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', color: 'var(--text-primary)', margin: 0 }}>{subject.name}</h1>
            <span style={{ display: 'inline-flex', alignItems: 'center', borderRadius: 'var(--radius-full)', padding: '4px 10px', backgroundColor: subjectTypeBadge.background, color: subjectTypeBadge.color, fontSize: 'var(--text-xs)', fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
              {subjectTypeBadge.label}
            </span>
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)', lineHeight: 1.7 }}>
            <div>{subject.identifier}</div>
            {subject.department ? <div>{subject.department}</div> : null}
          </div>
          <ComplianceMeter uploaded={complianceSummary?.uploaded ?? 0} total_required={complianceSummary?.total_required ?? 0} expired={complianceSummary?.expired ?? 0} expiring_soon={complianceSummary?.expiring_soon ?? 0} />
        </div>
        <Button onClick={() => setIsPanelOpen(true)}>Add Document</Button>
      </div>

      {!documents.length ? (
        <Card style={{ padding: 0 }}>
          <EmptyState title="No document slots yet" description="Add a required document category to begin tracking expiry and compliance." actionLabel="Add Document" onAction={() => setIsPanelOpen(true)} />
        </Card>
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)' }}>
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th key={header.id} style={tableHeaderStyle}>
                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row, index) => (
                  <React.Fragment key={row.id}>
                    <tr style={{ backgroundColor: index % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-surface-2)' }}>
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} style={tableCellStyle}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                      ))}
                    </tr>
                    {editingDocument?.id === row.original.id ? (
                      <tr>
                        <td colSpan={columns.length} style={{ padding: 'var(--space-4)', backgroundColor: 'var(--bg-surface-1)' }}>
                          <form onSubmit={handleSaveDates} style={{ display: 'grid', gap: 'var(--space-4)' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--space-4)' }}>
                              <FormField label="Issue Date">
                                <input type="date" value={editingDocument.issue_date} onChange={(event) => setEditingDocument((current) => current ? { ...current, issue_date: event.target.value } : current)} style={inputStyle} />
                              </FormField>
                              <FormField label="Has Expiry">
                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-primary)' }}>
                                  <input type="checkbox" checked={editingDocument.has_expiry} onChange={(event) => setEditingDocument((current) => current ? { ...current, has_expiry: event.target.checked, expiry_date: event.target.checked ? current.expiry_date : '' } : current)} />
                                  This document expires
                                </label>
                              </FormField>
                              {editingDocument.has_expiry ? (
                                <FormField label="Expiry Date">
                                  <input type="date" value={editingDocument.expiry_date} onChange={(event) => setEditingDocument((current) => current ? { ...current, expiry_date: event.target.value } : current)} style={inputStyle} />
                                </FormField>
                              ) : null}
                            </div>
                            <FormField label="Notes">
                              <textarea value={editingDocument.notes} onChange={(event) => setEditingDocument((current) => current ? { ...current, notes: event.target.value } : current)} rows={4} style={textareaStyle} />
                            </FormField>
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)' }}>
                              <Button type="button" variant="secondary" onClick={() => setEditingDocument(null)}>Cancel</Button>
                              <Button type="submit" loading={updateDatesMutation.isPending} disabled={updateDatesMutation.isPending}>Save</Button>
                            </div>
                          </form>
                        </td>
                      </tr>
                    ) : null}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <SlideOverPanel open={isPanelOpen} onClose={() => setIsPanelOpen(false)} title="Add Document" subtitle="Create a revalidation slot, then upload a file or move directly into manual date entry.">
        <form onSubmit={handleCreateDocument} style={{ display: 'grid', gap: 'var(--space-5)' }}>
          <FormField label="Step 1 — Category">
            {catalogQuery.isLoading ? (
              <LoadingSpinner size={24} />
            ) : (
              <select value={selectedCatalogId} onChange={(event) => setSelectedCatalogId(event.target.value)} style={inputStyle}>
                {(catalogQuery.data || []).map((catalogItem) => (
                  <option key={catalogItem.id} value={catalogItem.id}>{catalogItem.display_name}</option>
                ))}
              </select>
            )}
          </FormField>
          <FormField label="Step 2 — Next Action">
            <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
              <button type="button" onClick={() => setCreateMode('upload')} style={createMode === 'upload' ? selectedOptionStyle : optionStyle}>Upload File</button>
              <button type="button" onClick={() => setCreateMode('manual')} style={createMode === 'manual' ? selectedOptionStyle : optionStyle}>Enter Dates Manually</button>
            </div>
          </FormField>
          {createMode === 'upload' ? (
            <FormField label="File">
              <input type="file" onChange={(event) => setPanelFile(event.target.files?.[0] || null)} style={inputStyle} />
            </FormField>
          ) : (
            <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)', lineHeight: 1.6 }}>
              The new document row will open inline so you can enter issue and expiry dates immediately.
            </p>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)' }}>
            <Button type="button" variant="secondary" onClick={() => setIsPanelOpen(false)}>Cancel</Button>
            <Button type="submit" loading={createDocumentMutation.isPending} disabled={createDocumentMutation.isPending || catalogQuery.isLoading || !(catalogQuery.data || []).length}>Save</Button>
          </div>
        </form>
      </SlideOverPanel>
    </div>
  );
}
