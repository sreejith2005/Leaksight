"""phase2_data_model

Source: docs/DATABASE_SCHEMA.md — all sections
Source: docs/DECISIONS.md — ADR-004 (RLS), ADR-009 (three-layer schema)
Source: docs/RULES_ENGINE.md — composite index requirements

Creates all Phase 2 tables in dependency order:
  1. Foundational: tenants, users
  2. RAW layer: documents, raw_parses
  3. Canonical layer: vendors, vendor_aliases, canonical_units,
     unit_conversion_factors, fx_rates, contracts, contract_versions,
     contract_line_items, invoices, invoice_line_items, purchase_orders,
     po_line_items, grns, grn_line_items, tenant_settings
  4. Derived layer: analysis_runs, leakage_records, document_hashes

Applies:
  - RLS + FORCE ROW LEVEL SECURITY on all tenant-scoped tables
  - GRANT permissions to app_admin and app_tenant_user
  - Seed data for canonical_units, unit_conversion_factors, tenant_settings
  - Immutability trigger on leakage_records
  - FK from documents.run_id → analysis_runs.id (deferred)

Revision ID: a1b2c3d4e5f6
Revises: d539857749ba
Create Date: 2026-02-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd539857749ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Tables that get RLS ---
_RLS_TABLES = [
    "users",
    "documents",
    "raw_parses",
    "vendors",
    "vendor_aliases",
    "fx_rates",
    "contracts",
    "contract_versions",
    "contract_line_items",
    "invoices",
    "invoice_line_items",
    "purchase_orders",
    "po_line_items",
    "grns",
    "grn_line_items",
    "tenant_settings",
    "analysis_runs",
    "leakage_records",
    "document_hashes",
]


def upgrade() -> None:
    # ==========================================================================
    # ENUMS
    # ==========================================================================
    user_role_enum = postgresql.ENUM(
        'ADMIN', 'REVIEWER', name='user_role_enum', create_type=False
    )
    doc_type_enum = postgresql.ENUM(
        'INVOICE', 'CONTRACT', 'PO', 'GRN', name='doc_type_enum', create_type=False
    )
    parse_status_enum = postgresql.ENUM(
        'PENDING', 'PARSING', 'PARSED', 'FAILED', name='parse_status_enum', create_type=False
    )
    alias_source_enum = postgresql.ENUM(
        'MANUAL_REVIEW', 'IMPORT', 'AUTO_ACCEPTED', name='alias_source_enum', create_type=False
    )
    unit_dimension_enum = postgresql.ENUM(
        'WEIGHT', 'VOLUME', 'COUNT', 'AREA', 'LENGTH', 'TIME',
        name='unit_dimension_enum', create_type=False
    )
    fx_source_enum = postgresql.ENUM(
        'ECB', 'RBI', 'MANUAL_UPLOAD', 'ADMIN_IMPORT',
        name='fx_source_enum', create_type=False
    )
    run_status_enum = postgresql.ENUM(
        'QUEUED', 'PROCESSING', 'PARTIAL_SUCCESS', 'COMPLETE', 'FAILED',
        name='run_status_enum', create_type=False
    )
    leakage_type_enum = postgresql.ENUM(
        'PRICE_MISMATCH', 'DUPLICATE_INVOICE', 'QUANTITY_MISMATCH',
        name='leakage_type_enum', create_type=False
    )
    leakage_status_enum = postgresql.ENUM(
        'PENDING', 'ACCEPTED', 'REJECTED', 'PENDING_FX_RATE',
        name='leakage_status_enum', create_type=False
    )
    hash_type_enum = postgresql.ENUM(
        'BASELINE', 'REUPLOAD', 'PERIODIC_CHECK',
        name='hash_type_enum', create_type=False
    )
    comparison_status_enum = postgresql.ENUM(
        'NEW', 'UNCHANGED', 'MODIFIED', 'INCONCLUSIVE',
        name='comparison_status_enum', create_type=False
    )

    # Create all enum types
    op.execute("CREATE TYPE user_role_enum AS ENUM ('ADMIN', 'REVIEWER')")
    op.execute("CREATE TYPE doc_type_enum AS ENUM ('INVOICE', 'CONTRACT', 'PO', 'GRN')")
    op.execute("CREATE TYPE parse_status_enum AS ENUM ('PENDING', 'PARSING', 'PARSED', 'FAILED')")
    op.execute("CREATE TYPE alias_source_enum AS ENUM ('MANUAL_REVIEW', 'IMPORT', 'AUTO_ACCEPTED')")
    op.execute("CREATE TYPE unit_dimension_enum AS ENUM ('WEIGHT', 'VOLUME', 'COUNT', 'AREA', 'LENGTH', 'TIME')")
    op.execute("CREATE TYPE fx_source_enum AS ENUM ('ECB', 'RBI', 'MANUAL_UPLOAD', 'ADMIN_IMPORT')")
    op.execute("CREATE TYPE run_status_enum AS ENUM ('QUEUED', 'PROCESSING', 'PARTIAL_SUCCESS', 'COMPLETE', 'FAILED')")
    op.execute("CREATE TYPE leakage_type_enum AS ENUM ('PRICE_MISMATCH', 'DUPLICATE_INVOICE', 'QUANTITY_MISMATCH')")
    op.execute("CREATE TYPE leakage_status_enum AS ENUM ('PENDING', 'ACCEPTED', 'REJECTED', 'PENDING_FX_RATE')")
    op.execute("CREATE TYPE hash_type_enum AS ENUM ('BASELINE', 'REUPLOAD', 'PERIODIC_CHECK')")
    op.execute("CREATE TYPE comparison_status_enum AS ENUM ('NEW', 'UNCHANGED', 'MODIFIED', 'INCONCLUSIVE')")

    # ==========================================================================
    # 1. FOUNDATIONAL TABLES
    # ==========================================================================

    # --- tenants (no RLS) ---
    op.create_table(
        'tenants',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('role', user_role_enum, server_default='REVIEWER', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'email', name='uq_users_tenant_email'),
    )

    # ==========================================================================
    # 2. RAW LAYER TABLES
    # ==========================================================================

    # --- documents ---
    op.create_table(
        'documents',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=True),  # FK added after analysis_runs
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('original_filename', sa.Text(), nullable=False),
        sa.Column('sha256_hash', sa.String(64), nullable=False),
        sa.Column('doc_type', doc_type_enum, nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.Text(), nullable=False),
        sa.Column('parse_status', parse_status_enum, server_default='PENDING', nullable=False),
        sa.Column('low_confidence_flag', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_documents_tenant_id', 'documents', ['tenant_id'])
    op.create_index('idx_documents_tenant_doc_type', 'documents', ['tenant_id', 'doc_type'])
    op.create_index('idx_documents_sha256', 'documents', ['sha256_hash'])

    # --- raw_parses ---
    op.create_table(
        'raw_parses',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('raw_version', sa.Integer(), nullable=False),
        sa.Column('parser_used', sa.Text(), nullable=False),
        sa.Column('parser_version', sa.Text(), nullable=False),
        sa.Column('structured_output_jsonb', postgresql.JSONB(), nullable=False),
        sa.Column('parse_confidence', sa.Float(), nullable=False),
        sa.Column('failure_flags', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'raw_version', name='uq_raw_parses_doc_version'),
        sa.CheckConstraint('parse_confidence >= 0 AND parse_confidence <= 1', name='ck_raw_parses_confidence_range'),
    )
    op.create_index('idx_raw_parses_document_id', 'raw_parses', ['document_id'])
    op.create_index('idx_raw_parses_tenant_id', 'raw_parses', ['tenant_id'])

    # ==========================================================================
    # 3. CANONICAL LAYER TABLES
    # ==========================================================================

    # --- vendors ---
    op.create_table(
        'vendors',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('normalized_name', sa.Text(), nullable=False),
        sa.Column('raw_names_jsonb', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('gst_id', sa.Text(), nullable=True),
        sa.Column('source_system_ref', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'normalized_name', name='uq_vendors_tenant_normalized_name'),
    )
    op.create_index('idx_vendors_tenant_id', 'vendors', ['tenant_id'])
    op.create_index('idx_vendors_gst_id', 'vendors', ['gst_id'])
    # Trigram index for fuzzy search per DATABASE_SCHEMA.md
    op.execute(
        "CREATE INDEX idx_vendors_normalized_name_trgm ON vendors "
        "USING gin (normalized_name gin_trgm_ops)"
    )

    # --- vendor_aliases ---
    op.create_table(
        'vendor_aliases',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('alias_name', sa.Text(), nullable=False),
        sa.Column('override_source', alias_source_enum, nullable=False),
        sa.Column('applied_by_user_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id']),
        sa.ForeignKeyConstraint(['applied_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'alias_name', name='uq_vendor_aliases_tenant_alias'),
    )
    op.create_index('idx_vendor_aliases_tenant_id', 'vendor_aliases', ['tenant_id'])
    op.create_index('idx_vendor_aliases_vendor_id', 'vendor_aliases', ['vendor_id'])
    op.create_index('idx_vendor_aliases_alias_name', 'vendor_aliases', ['alias_name'])

    # --- canonical_units (no RLS — system-wide) ---
    op.create_table(
        'canonical_units',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('symbol', sa.Text(), nullable=False),
        sa.Column('dimension', unit_dimension_enum, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('symbol'),
    )

    # --- unit_conversion_factors (no RLS — system defaults) ---
    op.create_table(
        'unit_conversion_factors',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('from_unit_id', sa.UUID(), nullable=False),
        sa.Column('to_unit_id', sa.UUID(), nullable=False),
        sa.Column('factor', sa.Numeric(20, 10), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['from_unit_id'], ['canonical_units.id']),
        sa.ForeignKeyConstraint(['to_unit_id'], ['canonical_units.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('from_unit_id', 'to_unit_id', 'tenant_id', name='uq_conversion_from_to_tenant'),
    )

    # --- fx_rates ---
    op.create_table(
        'fx_rates',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('from_currency', sa.String(3), nullable=False),
        sa.Column('to_currency', sa.String(3), nullable=False),
        sa.Column('rate', sa.Numeric(20, 10), nullable=False),
        sa.Column('rate_date', sa.Date(), nullable=False),
        sa.Column('source', fx_source_enum, nullable=False),
        sa.Column('uploaded_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_fx_rates_currency_date', 'fx_rates', ['from_currency', 'to_currency', 'rate_date'])

    # --- contracts ---
    op.create_table(
        'contracts',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('contract_ref', sa.Text(), nullable=True),
        sa.Column('source_document_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id']),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_contracts_tenant_vendor', 'contracts', ['tenant_id', 'vendor_id'])

    # --- contract_versions ---
    op.create_table(
        'contract_versions',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('contract_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('valid_to', sa.Date(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contract_id', 'version_number', name='uq_contract_versions_contract_version'),
    )
    op.create_index('idx_contract_versions_vendor_dates', 'contract_versions', ['tenant_id', 'valid_from', 'valid_to'])

    # --- contract_line_items ---
    op.create_table(
        'contract_line_items',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('contract_version_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('item_desc', sa.Text(), nullable=False),
        sa.Column('raw_item_desc', sa.Text(), nullable=False),
        sa.Column('unit', sa.Text(), nullable=False),
        sa.Column('unit_price', sa.Numeric(20, 6), nullable=False),
        sa.Column('currency', sa.String(3), server_default='INR', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contract_version_id'], ['contract_versions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_contract_line_items_version', 'contract_line_items', ['contract_version_id'])

    # --- invoices ---
    op.create_table(
        'invoices',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('invoice_no', sa.Text(), nullable=False),
        sa.Column('invoice_date', sa.Date(), nullable=False),
        sa.Column('total_amount', sa.Numeric(20, 6), nullable=False),
        sa.Column('currency', sa.String(3), server_default='INR', nullable=False),
        sa.Column('source_document_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id']),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'invoice_no', name='uq_invoices_tenant_invoice_no'),
    )
    op.create_index('idx_invoices_tenant_id', 'invoices', ['tenant_id'])
    op.create_index('idx_invoices_vendor_id', 'invoices', ['vendor_id'])
    op.create_index('idx_invoices_tenant_vendor_date', 'invoices', ['tenant_id', 'vendor_id', 'invoice_date'])

    # --- invoice_line_items ---
    op.create_table(
        'invoice_line_items',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('item_desc', sa.Text(), nullable=False),
        sa.Column('raw_item_desc', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 6), nullable=False),
        sa.Column('unit', sa.Text(), nullable=False),
        sa.Column('unit_price', sa.Numeric(20, 6), nullable=False),
        sa.Column('line_total', sa.Numeric(20, 6), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_invoice_line_items_invoice', 'invoice_line_items', ['invoice_id'])

    # --- purchase_orders ---
    op.create_table(
        'purchase_orders',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('po_no', sa.Text(), nullable=False),
        sa.Column('po_date', sa.Date(), nullable=False),
        sa.Column('source_document_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id']),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'po_no', name='uq_po_tenant_po_no'),
    )
    op.create_index('idx_po_tenant_vendor', 'purchase_orders', ['tenant_id', 'vendor_id'])

    # --- po_line_items ---
    op.create_table(
        'po_line_items',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('po_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('item_desc', sa.Text(), nullable=False),
        sa.Column('raw_item_desc', sa.Text(), nullable=False),
        sa.Column('unit', sa.Text(), nullable=False),
        sa.Column('ordered_qty', sa.Numeric(20, 6), nullable=False),
        sa.Column('unit_price', sa.Numeric(20, 6), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_po_line_items_po', 'po_line_items', ['po_id'])

    # --- grns ---
    op.create_table(
        'grns',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('po_id', sa.UUID(), nullable=False),
        sa.Column('grn_no', sa.Text(), nullable=False),
        sa.Column('grn_date', sa.Date(), nullable=False),
        sa.Column('source_document_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id']),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'grn_no', name='uq_grns_tenant_grn_no'),
    )
    op.create_index('idx_grns_tenant_po', 'grns', ['tenant_id', 'po_id'])

    # --- grn_line_items ---
    op.create_table(
        'grn_line_items',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('grn_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('item_desc', sa.Text(), nullable=False),
        sa.Column('raw_item_desc', sa.Text(), nullable=False),
        sa.Column('unit', sa.Text(), nullable=False),
        sa.Column('received_qty', sa.Numeric(20, 6), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['grn_id'], ['grns.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_grn_line_items_grn', 'grn_line_items', ['grn_id'])

    # --- tenant_settings ---
    op.create_table(
        'tenant_settings',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('abbreviation_dictionary', postgresql.JSONB(), nullable=False),
        sa.Column('fuzzy_threshold', sa.Float(), server_default='0.85', nullable=False),
        sa.Column('duplicate_window_days', sa.Integer(), server_default='30', nullable=False),
        sa.Column('manual_review_threshold', sa.Float(), server_default='0.70', nullable=False),
        sa.Column('base_currency', sa.String(3), server_default='INR', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('tenant_id'),
    )

    # ==========================================================================
    # 4. DERIVED LAYER TABLES
    # ==========================================================================

    # --- analysis_runs ---
    op.create_table(
        'analysis_runs',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('status', run_status_enum, server_default='QUEUED', nullable=False),
        sa.Column('total_documents', sa.Integer(), server_default='0', nullable=False),
        sa.Column('processed_documents', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_leakage_found', sa.Numeric(20, 6), server_default='0', nullable=False),
        sa.Column('leakage_record_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_analysis_runs_tenant', 'analysis_runs', ['tenant_id'])
    op.create_index('idx_analysis_runs_status', 'analysis_runs', ['tenant_id', 'status'])

    # --- Add FK from documents.run_id → analysis_runs.id ---
    op.create_foreign_key(
        'fk_documents_run_id',
        'documents', 'analysis_runs',
        ['run_id'], ['id'],
    )

    # --- leakage_records ---
    op.create_table(
        'leakage_records',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('leakage_type', leakage_type_enum, nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('invoice_line_item_id', sa.UUID(), nullable=True),
        sa.Column('contract_line_item_id', sa.UUID(), nullable=True),
        sa.Column('amount', sa.Numeric(20, 6), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('evidence_jsonb', postgresql.JSONB(), nullable=False),
        sa.Column('rule_applied', sa.Text(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('status', leakage_status_enum, server_default='PENDING', nullable=False),
        sa.Column('reviewed_by_user_id', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['run_id'], ['analysis_runs.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id']),
        sa.ForeignKeyConstraint(['invoice_line_item_id'], ['invoice_line_items.id']),
        sa.ForeignKeyConstraint(['contract_line_item_id'], ['contract_line_items.id']),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_leakage_confidence_range'),
    )
    op.create_index('idx_leakage_tenant', 'leakage_records', ['tenant_id'])
    op.create_index('idx_leakage_run', 'leakage_records', ['run_id'])
    op.create_index('idx_leakage_status', 'leakage_records', ['tenant_id', 'status'])
    op.create_index('idx_leakage_type', 'leakage_records', ['tenant_id', 'leakage_type'])

    # --- document_hashes ---
    op.create_table(
        'document_hashes',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('hash_sha256', sa.String(64), nullable=False),
        sa.Column('hash_type', hash_type_enum, nullable=False),
        sa.Column('upload_sequence', sa.Integer(), nullable=False),
        sa.Column('comparison_status', comparison_status_enum, server_default='NEW', nullable=False),
        sa.Column('comparison_against_id', sa.UUID(), nullable=True),
        sa.Column('metadata_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('risk_score', sa.Integer(), nullable=True),
        sa.Column('flagged_anomalies_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.ForeignKeyConstraint(['comparison_against_id'], ['document_hashes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('risk_score >= 0 AND risk_score <= 100', name='ck_doc_hashes_risk_score_range'),
    )
    op.create_index('idx_doc_hashes_document', 'document_hashes', ['document_id'])
    op.create_index('idx_doc_hashes_tenant', 'document_hashes', ['tenant_id'])

    # ==========================================================================
    # 5. ROW LEVEL SECURITY
    # ==========================================================================
    # Per DATABASE_SCHEMA.md Section 5: every table with tenant_id gets:
    #   ENABLE ROW LEVEL SECURITY
    #   FORCE ROW LEVEL SECURITY
    #   Policy: USING (tenant_id::text = current_setting('app.current_tenant_id'))
    # Then GRANT to app_admin and app_tenant_user

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING (tenant_id::text = current_setting('app.current_tenant_id'))"
        )
        # Grant ALL to app_admin; SELECT, INSERT to app_tenant_user
        op.execute(f"GRANT ALL ON {table} TO app_admin")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO app_tenant_user")

    # System tables (no RLS): grant read/write to both roles
    for table in ['tenants', 'canonical_units', 'unit_conversion_factors']:
        op.execute(f"GRANT ALL ON {table} TO app_admin")
        op.execute(f"GRANT SELECT ON {table} TO app_tenant_user")

    # ==========================================================================
    # 6. IMMUTABILITY TRIGGER on leakage_records
    # ==========================================================================
    # Per DATABASE_SCHEMA.md Section 4.2.2
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_accepted_leakage_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status = 'ACCEPTED' THEN
                IF NEW.amount IS DISTINCT FROM OLD.amount
                   OR NEW.leakage_type IS DISTINCT FROM OLD.leakage_type
                   OR NEW.confidence IS DISTINCT FROM OLD.confidence
                   OR NEW.evidence_jsonb IS DISTINCT FROM OLD.evidence_jsonb
                   OR NEW.rule_applied IS DISTINCT FROM OLD.rule_applied
                   OR NEW.explanation IS DISTINCT FROM OLD.explanation THEN
                    RAISE EXCEPTION 'Cannot modify accepted leakage record fields: amount, leakage_type, confidence, evidence_jsonb, rule_applied, explanation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_leakage_immutability
            BEFORE UPDATE ON leakage_records
            FOR EACH ROW
            EXECUTE FUNCTION prevent_accepted_leakage_modification();
    """)

    # ==========================================================================
    # 7. SEED DATA
    # ==========================================================================

    # --- canonical_units (11 units per DATABASE_SCHEMA.md Section 3.5) ---
    op.execute("""
        INSERT INTO canonical_units (id, name, symbol, dimension) VALUES
            (uuid_generate_v4(), 'metric_ton', 'MT', 'WEIGHT'),
            (uuid_generate_v4(), 'kilogram', 'KG', 'WEIGHT'),
            (uuid_generate_v4(), 'gram', 'G', 'WEIGHT'),
            (uuid_generate_v4(), 'litre', 'L', 'VOLUME'),
            (uuid_generate_v4(), 'millilitre', 'ML', 'VOLUME'),
            (uuid_generate_v4(), 'nos', 'Nos', 'COUNT'),
            (uuid_generate_v4(), 'box', 'Box', 'COUNT'),
            (uuid_generate_v4(), 'set', 'Set', 'COUNT'),
            (uuid_generate_v4(), 'square_foot', 'Sqft', 'AREA'),
            (uuid_generate_v4(), 'square_metre', 'Sqm', 'AREA'),
            (uuid_generate_v4(), 'running_metre', 'RMT', 'LENGTH');
    """)

    # --- unit_conversion_factors (system defaults, tenant_id = NULL) ---
    # Per DATABASE_SCHEMA.md Section 3.6 — V1 Seed Conversions
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'MT'),
               (SELECT id FROM canonical_units WHERE symbol = 'KG'),
               1000.0, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'KG'),
               (SELECT id FROM canonical_units WHERE symbol = 'MT'),
               0.001, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'KG'),
               (SELECT id FROM canonical_units WHERE symbol = 'G'),
               1000.0, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'G'),
               (SELECT id FROM canonical_units WHERE symbol = 'KG'),
               0.001, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'MT'),
               (SELECT id FROM canonical_units WHERE symbol = 'G'),
               1000000.0, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'G'),
               (SELECT id FROM canonical_units WHERE symbol = 'MT'),
               0.000001, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'L'),
               (SELECT id FROM canonical_units WHERE symbol = 'ML'),
               1000.0, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'ML'),
               (SELECT id FROM canonical_units WHERE symbol = 'L'),
               0.001, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'Sqm'),
               (SELECT id FROM canonical_units WHERE symbol = 'Sqft'),
               10.7639, NULL;
    """)
    op.execute("""
        INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
        SELECT uuid_generate_v4(),
               (SELECT id FROM canonical_units WHERE symbol = 'Sqft'),
               (SELECT id FROM canonical_units WHERE symbol = 'Sqm'),
               0.092903, NULL;
    """)

    # --- tenant_settings seed: system default row ---
    # Per DATABASE_SCHEMA.md Section 3.17 — create a system default tenant
    # with the abbreviation dictionary seed values
    op.execute("""
        INSERT INTO tenants (id, name, is_active)
        VALUES ('00000000-0000-0000-0000-000000000001', 'System Default', true);
    """)
    op.execute("""
        INSERT INTO tenant_settings (tenant_id, abbreviation_dictionary)
        VALUES (
            '00000000-0000-0000-0000-000000000001',
            '{"MT": "metric_ton", "KG": "kilogram", "KGS": "kilogram", "GM": "gram", "GMS": "gram", "NOS": "nos", "NO": "nos", "PCS": "nos", "PC": "nos", "BOX": "box", "BX": "box", "SET": "set", "SQFT": "square_foot", "SFT": "square_foot", "SQM": "square_metre", "RMT": "running_metre", "RM": "running_metre", "LTR": "litre", "LT": "litre", "ML": "millilitre", "PKT": "packet", "PKG": "package", "DZ": "dozen", "PR": "pair"}'::jsonb
        );
    """)


def downgrade() -> None:
    # Drop all tables in reverse dependency order
    op.execute("DROP TRIGGER IF EXISTS trg_leakage_immutability ON leakage_records")
    op.execute("DROP FUNCTION IF EXISTS prevent_accepted_leakage_modification()")

    # Drop RLS policies before tables
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table('document_hashes')
    op.drop_table('leakage_records')
    op.drop_table('analysis_runs')
    op.drop_table('tenant_settings')
    op.drop_table('grn_line_items')
    op.drop_table('grns')
    op.drop_table('po_line_items')
    op.drop_table('purchase_orders')
    op.drop_table('invoice_line_items')
    op.drop_table('invoices')
    op.drop_table('contract_line_items')
    op.drop_table('contract_versions')
    op.drop_table('contracts')
    op.drop_table('fx_rates')
    op.drop_table('unit_conversion_factors')
    op.drop_table('canonical_units')
    op.drop_table('vendor_aliases')
    op.drop_table('vendors')
    op.drop_table('raw_parses')
    # Remove FK before dropping documents
    op.drop_constraint('fk_documents_run_id', 'documents', type_='foreignkey')
    op.drop_table('documents')
    op.drop_table('users')
    op.drop_table('tenants')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS comparison_status_enum")
    op.execute("DROP TYPE IF EXISTS hash_type_enum")
    op.execute("DROP TYPE IF EXISTS leakage_status_enum")
    op.execute("DROP TYPE IF EXISTS leakage_type_enum")
    op.execute("DROP TYPE IF EXISTS run_status_enum")
    op.execute("DROP TYPE IF EXISTS fx_source_enum")
    op.execute("DROP TYPE IF EXISTS unit_dimension_enum")
    op.execute("DROP TYPE IF EXISTS alias_source_enum")
    op.execute("DROP TYPE IF EXISTS parse_status_enum")
    op.execute("DROP TYPE IF EXISTS doc_type_enum")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
