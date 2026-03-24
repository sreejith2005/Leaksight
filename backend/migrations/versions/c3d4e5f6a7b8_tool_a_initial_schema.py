"""tool_a_initial_schema

Creates Tool A contract structuring schema:
  - contract_structuring_runs
  - contract_structuring_run_documents
  - raw_contract_tables
  - extracted_line_items
  - extracted_clauses
  - contract_structuring_exports

Includes required enums, indexes, RLS policies, and grants.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RLS_TABLES = (
    "contract_structuring_runs",
    "contract_structuring_run_documents",
    "raw_contract_tables",
    "extracted_line_items",
    "extracted_clauses",
    "contract_structuring_exports",
)


def upgrade() -> None:
    structuring_run_status_enum = postgresql.ENUM(
        "PENDING",
        "PROCESSING",
        "COMPLETE",
        "PARTIAL_SUCCESS",
        "FAILED",
        name="structuring_run_status_enum",
        create_type=False,
    )
    structuring_task_status_enum = postgresql.ENUM(
        "PENDING",
        "PROCESSING",
        "COMPLETE",
        "FAILED",
        name="structuring_task_status_enum",
        create_type=False,
    )
    structuring_extraction_method_enum = postgresql.ENUM(
        "CAMELOT_LATTICE",
        "CAMELOT_STREAM",
        "PDFPLUMBER",
        "PADDLE_OCR",
        "DOCX_TABLE",
        "EXCEL_SHEET",
        name="structuring_extraction_method_enum",
        create_type=False,
    )
    structuring_line_item_review_status_enum = postgresql.ENUM(
        "PENDING_REVIEW",
        "CONFIRMED",
        "REJECTED",
        name="structuring_line_item_review_status_enum",
        create_type=False,
    )
    structuring_clause_type_enum = postgresql.ENUM(
        "EFFECTIVE_DATE",
        "EXPIRY_DATE",
        "AMENDMENT_REF",
        "ESCALATION",
        "VENDOR_NAME",
        "CONTRACT_REF",
        name="structuring_clause_type_enum",
        create_type=False,
    )
    structuring_clause_review_status_enum = postgresql.ENUM(
        "PENDING_REVIEW",
        "CONFIRMED",
        "REJECTED",
        name="structuring_clause_review_status_enum",
        create_type=False,
    )
    structuring_export_format_enum = postgresql.ENUM(
        "EXCEL",
        "ERP_JSON",
        "ERP_CSV",
        "LEAKSIGHT_IMPORT",
        name="structuring_export_format_enum",
        create_type=False,
    )

    op.execute(
        "CREATE TYPE structuring_run_status_enum AS ENUM ('PENDING', 'PROCESSING', 'COMPLETE', 'PARTIAL_SUCCESS', 'FAILED')"
    )
    op.execute(
        "CREATE TYPE structuring_task_status_enum AS ENUM ('PENDING', 'PROCESSING', 'COMPLETE', 'FAILED')"
    )
    op.execute(
        "CREATE TYPE structuring_extraction_method_enum AS ENUM ('CAMELOT_LATTICE', 'CAMELOT_STREAM', 'PDFPLUMBER', 'PADDLE_OCR', 'DOCX_TABLE', 'EXCEL_SHEET')"
    )
    op.execute(
        "CREATE TYPE structuring_line_item_review_status_enum AS ENUM ('PENDING_REVIEW', 'CONFIRMED', 'REJECTED')"
    )
    op.execute(
        "CREATE TYPE structuring_clause_type_enum AS ENUM ('EFFECTIVE_DATE', 'EXPIRY_DATE', 'AMENDMENT_REF', 'ESCALATION', 'VENDOR_NAME', 'CONTRACT_REF')"
    )
    op.execute(
        "CREATE TYPE structuring_clause_review_status_enum AS ENUM ('PENDING_REVIEW', 'CONFIRMED', 'REJECTED')"
    )
    op.execute(
        "CREATE TYPE structuring_export_format_enum AS ENUM ('EXCEL', 'ERP_JSON', 'ERP_CSV', 'LEAKSIGHT_IMPORT')"
    )

    op.create_table(
        "contract_structuring_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_label", sa.String(length=255), nullable=True),
        sa.Column("status", structuring_run_status_enum, server_default="PENDING", nullable=False),
        sa.Column("total_documents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed_documents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_line_items_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_clauses_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_structuring_runs_tenant"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_structuring_runs_created_by"),
    )
    op.create_index("idx_structuring_runs_tenant", "contract_structuring_runs", ["tenant_id"])
    op.create_index(
        "idx_structuring_runs_status",
        "contract_structuring_runs",
        ["tenant_id", "status"],
    )

    op.create_table(
        "contract_structuring_run_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_status", structuring_task_status_enum, server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processing_time_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_structuring_run_docs_tenant"),
        sa.ForeignKeyConstraint(["run_id"], ["contract_structuring_runs.id"], name="fk_structuring_run_docs_run"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_structuring_run_docs_document"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "document_id",
            name="uq_structuring_run_docs_tenant_run_document",
        ),
    )
    op.create_index(
        "idx_structuring_run_docs_tenant",
        "contract_structuring_run_documents",
        ["tenant_id"],
    )
    op.create_index(
        "idx_structuring_run_docs_run",
        "contract_structuring_run_documents",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "idx_structuring_run_docs_doc",
        "contract_structuring_run_documents",
        ["tenant_id", "document_id"],
    )

    op.create_table(
        "raw_contract_tables",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("extraction_method", structuring_extraction_method_enum, nullable=False),
        sa.Column("raw_table_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("table_confidence", sa.Float(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("is_continuation", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("continued_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_raw_contract_tables_tenant"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_raw_contract_tables_document"),
        sa.ForeignKeyConstraint(
            ["run_document_id"],
            ["contract_structuring_run_documents.id"],
            name="fk_raw_contract_tables_run_document",
        ),
        sa.ForeignKeyConstraint(
            ["continued_from_id"],
            ["raw_contract_tables.id"],
            name="fk_raw_contract_tables_continued_from",
        ),
        sa.CheckConstraint(
            "table_confidence >= 0 AND table_confidence <= 1",
            name="ck_raw_contract_tables_confidence_range",
        ),
    )
    op.create_index("idx_raw_contract_tables_tenant", "raw_contract_tables", ["tenant_id"])
    op.create_index(
        "idx_raw_contract_tables_document",
        "raw_contract_tables",
        ["tenant_id", "document_id"],
    )

    op.create_table(
        "extracted_line_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_description", sa.Text(), nullable=True),
        sa.Column("normalized_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unit_raw", sa.String(length=100), nullable=True),
        sa.Column("normalized_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default="INR", nullable=True),
        sa.Column("slab_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("version_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("item_confidence", sa.Float(), nullable=False),
        sa.Column("price_confidence", sa.Float(), nullable=False),
        sa.Column("unit_confidence", sa.Float(), nullable=False),
        sa.Column(
            "review_status",
            structuring_line_item_review_status_enum,
            server_default="PENDING_REVIEW",
            nullable=False,
        ),
        sa.Column("needs_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_extracted_line_items_tenant"),
        sa.ForeignKeyConstraint(["run_id"], ["contract_structuring_runs.id"], name="fk_extracted_line_items_run"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_extracted_line_items_document"),
        sa.ForeignKeyConstraint(["raw_table_id"], ["raw_contract_tables.id"], name="fk_extracted_line_items_raw_table"),
        sa.ForeignKeyConstraint(["normalized_unit_id"], ["canonical_units.id"], name="fk_extracted_line_items_unit"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], name="fk_extracted_line_items_reviewed_by"),
        sa.CheckConstraint(
            "item_confidence >= 0 AND item_confidence <= 1",
            name="ck_extracted_line_items_item_confidence",
        ),
        sa.CheckConstraint(
            "price_confidence >= 0 AND price_confidence <= 1",
            name="ck_extracted_line_items_price_confidence",
        ),
        sa.CheckConstraint(
            "unit_confidence >= 0 AND unit_confidence <= 1",
            name="ck_extracted_line_items_unit_confidence",
        ),
    )
    op.create_index("idx_extracted_line_items_tenant", "extracted_line_items", ["tenant_id"])
    op.create_index(
        "idx_extracted_line_items_run",
        "extracted_line_items",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "idx_extracted_line_items_doc",
        "extracted_line_items",
        ["tenant_id", "document_id"],
    )
    op.create_index(
        "idx_extracted_line_items_status",
        "extracted_line_items",
        ["tenant_id", "review_status"],
    )

    op.create_table(
        "extracted_clauses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clause_type", structuring_clause_type_enum, nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "review_status",
            structuring_clause_review_status_enum,
            server_default="PENDING_REVIEW",
            nullable=False,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_extracted_clauses_tenant"),
        sa.ForeignKeyConstraint(["run_id"], ["contract_structuring_runs.id"], name="fk_extracted_clauses_run"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_extracted_clauses_document"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_extracted_clauses_confidence_range",
        ),
    )
    op.create_index("idx_extracted_clauses_tenant", "extracted_clauses", ["tenant_id"])
    op.create_index(
        "idx_extracted_clauses_run",
        "extracted_clauses",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "idx_extracted_clauses_doc",
        "extracted_clauses",
        ["tenant_id", "document_id"],
    )

    op.create_table(
        "contract_structuring_exports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("export_format", structuring_export_format_enum, nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line_items_included", sa.Integer(), nullable=True),
        sa.Column("generated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_structuring_exports_tenant"),
        sa.ForeignKeyConstraint(["run_id"], ["contract_structuring_runs.id"], name="fk_structuring_exports_run"),
        sa.ForeignKeyConstraint(["generated_by_user_id"], ["users.id"], name="fk_structuring_exports_generated_by"),
    )
    op.create_index("idx_structuring_exports_tenant", "contract_structuring_exports", ["tenant_id"])
    op.create_index(
        "idx_structuring_exports_run",
        "contract_structuring_exports",
        ["tenant_id", "run_id"],
    )

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING (tenant_id::text = current_setting('app.current_tenant_id'))"
        )
        op.execute(f"GRANT ALL ON {table} TO app_admin")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO app_tenant_user")


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_structuring_exports_run", table_name="contract_structuring_exports")
    op.drop_index("idx_structuring_exports_tenant", table_name="contract_structuring_exports")
    op.drop_table("contract_structuring_exports")

    op.drop_index("idx_extracted_clauses_doc", table_name="extracted_clauses")
    op.drop_index("idx_extracted_clauses_run", table_name="extracted_clauses")
    op.drop_index("idx_extracted_clauses_tenant", table_name="extracted_clauses")
    op.drop_table("extracted_clauses")

    op.drop_index("idx_extracted_line_items_status", table_name="extracted_line_items")
    op.drop_index("idx_extracted_line_items_doc", table_name="extracted_line_items")
    op.drop_index("idx_extracted_line_items_run", table_name="extracted_line_items")
    op.drop_index("idx_extracted_line_items_tenant", table_name="extracted_line_items")
    op.drop_table("extracted_line_items")

    op.drop_index("idx_raw_contract_tables_document", table_name="raw_contract_tables")
    op.drop_index("idx_raw_contract_tables_tenant", table_name="raw_contract_tables")
    op.drop_table("raw_contract_tables")

    op.drop_index("idx_structuring_run_docs_doc", table_name="contract_structuring_run_documents")
    op.drop_index("idx_structuring_run_docs_run", table_name="contract_structuring_run_documents")
    op.drop_index("idx_structuring_run_docs_tenant", table_name="contract_structuring_run_documents")
    op.drop_table("contract_structuring_run_documents")

    op.drop_index("idx_structuring_runs_status", table_name="contract_structuring_runs")
    op.drop_index("idx_structuring_runs_tenant", table_name="contract_structuring_runs")
    op.drop_table("contract_structuring_runs")

    op.execute("DROP TYPE IF EXISTS structuring_export_format_enum")
    op.execute("DROP TYPE IF EXISTS structuring_clause_review_status_enum")
    op.execute("DROP TYPE IF EXISTS structuring_clause_type_enum")
    op.execute("DROP TYPE IF EXISTS structuring_line_item_review_status_enum")
    op.execute("DROP TYPE IF EXISTS structuring_extraction_method_enum")
    op.execute("DROP TYPE IF EXISTS structuring_task_status_enum")
    op.execute("DROP TYPE IF EXISTS structuring_run_status_enum")
