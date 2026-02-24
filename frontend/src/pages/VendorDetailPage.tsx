import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getVendor, addAlias, deactivateAlias } from '../api/endpoints/vendors';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { Modal } from '../components/ui/Modal';
import { useToast } from '../context/ToastContext';

export default function VendorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  const [showAddModal, setShowAddModal] = useState(false);
  const [newAlias, setNewAlias] = useState('');

  const { data: vendor, isLoading, error } = useQuery({
    queryKey: ['vendor', id],
    queryFn: () => getVendor(id!),
    enabled: !!id,
  });

  const addAliasMutation = useMutation({
    mutationFn: () => addAlias(id!, { alias_name: newAlias }),
    onSuccess: () => {
      addToast('success', `Alias "${newAlias}" added`);
      setShowAddModal(false);
      setNewAlias('');
      queryClient.invalidateQueries({ queryKey: ['vendor', id] });
    },
    onError: (err: Error) => addToast('error', err.message),
  });

  const deactivateMutation = useMutation({
    mutationFn: (aliasId: string) => deactivateAlias(id!, aliasId),
    onSuccess: () => {
      addToast('success', 'Alias deactivated');
      queryClient.invalidateQueries({ queryKey: ['vendor', id] });
    },
    onError: (err: Error) => addToast('error', err.message),
  });

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-16)' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }

  if (error || !vendor) {
    return <ErrorMessage message={error?.message || 'Vendor not found'} />;
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <button
        onClick={() => navigate('/vendors')}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--color-orange)',
          cursor: 'pointer',
          fontSize: '13px',
          marginBottom: 'var(--space-4)',
          padding: 0,
        }}
      >
        ← Back to Vendors
      </button>

      <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--color-white)', marginBottom: 'var(--space-6)' }}>
        {vendor.normalized_name}
      </h1>

      {/* Overview */}
      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-4)' }}>
          Overview
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
          <div>
            <div style={{ fontSize: '11px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-1)' }}>
              GST ID
            </div>
            <div style={{ fontSize: '14px', color: 'var(--color-grey)' }}>{vendor.gst_id || '—'}</div>
          </div>
          <div>
            <div style={{ fontSize: '11px', color: 'var(--color-muted)', textTransform: 'uppercase', marginBottom: 'var(--space-1)' }}>
              Created
            </div>
            <div style={{ fontSize: '14px', color: 'var(--color-grey)' }}>
              {vendor.created_at ? new Date(vendor.created_at).toLocaleDateString() : '—'}
            </div>
          </div>
        </div>
      </Card>

      {/* Raw names */}
      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)', marginBottom: 'var(--space-3)' }}>
          Raw Name Variations
        </h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
          {vendor.raw_names.map((name) => (
            <Badge key={name}>{name}</Badge>
          ))}
        </div>
      </Card>

      {/* Aliases */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-white)' }}>
            Aliases ({vendor.aliases.length})
          </h3>
          <Button onClick={() => setShowAddModal(true)}>Add Alias</Button>
        </div>

        {vendor.aliases.length === 0 ? (
          <p style={{ color: 'var(--color-muted)', fontSize: '14px' }}>No aliases defined yet.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {vendor.aliases.map((alias) => (
              <div
                key={alias.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: 'var(--space-3)',
                  backgroundColor: 'var(--color-black)',
                  borderRadius: 'var(--radius-sm)',
                  opacity: alias.is_active ? 1 : 0.5,
                }}
              >
                <div>
                  <span style={{ color: 'var(--color-grey)', fontSize: '14px' }}>{alias.alias_name}</span>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-1)' }}>
                    <span style={{ fontSize: '11px', color: 'var(--color-muted)' }}>
                      {alias.override_source}
                    </span>
                    {!alias.is_active && (
                      <Badge
                        color="var(--color-error)"
                        bgColor="rgba(239, 68, 68, 0.12)"
                      >
                        Inactive
                      </Badge>
                    )}
                  </div>
                </div>
                {alias.is_active && (
                  <Button
                    variant="danger"
                    onClick={() => deactivateMutation.mutate(alias.id)}
                    loading={deactivateMutation.isPending}
                  >
                    Deactivate
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Add alias modal */}
      <Modal open={showAddModal} onClose={() => setShowAddModal(false)} title="Add Vendor Alias">
        <p style={{ color: 'var(--color-grey)', fontSize: '14px', marginBottom: 'var(--space-4)' }}>
          Enter a new alias name for this vendor.
        </p>
        <input
          type="text"
          value={newAlias}
          onChange={(e) => setNewAlias(e.target.value)}
          placeholder="Alias name"
          style={{
            width: '100%',
            backgroundColor: 'var(--color-black)',
            color: 'var(--color-grey)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-3)',
            fontSize: '14px',
            outline: 'none',
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
          <Button variant="secondary" onClick={() => setShowAddModal(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => addAliasMutation.mutate()}
            loading={addAliasMutation.isPending}
            disabled={!newAlias.trim()}
          >
            Add Alias
          </Button>
        </div>
      </Modal>
    </div>
  );
}
