"""add_tool_c_revalidation_tables

Revision ID: e65c379efa6e
Revises: e5f6a7b8c9d0
Create Date: 2026-04-07 12:27:02.304490
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e65c379efa6e"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revalidation_subjects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "subject_type",
            "identifier",
            name="uq_revalidation_subjects_tenant_type_identifier",
        ),
    )

    op.create_table(
        "revalidation_doc_catalog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_expiry", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("alert_days_before", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        """
        INSERT INTO revalidation_doc_catalog (
            id,
            tenant_id,
            subject_type,
            category,
            display_name,
            is_required,
            has_expiry,
            alert_days_before
        ) VALUES
            (uuid_generate_v4(), NULL, 'EMPLOYEE', 'ID_PROOF', 'Identity Proof', TRUE, TRUE, 30),
            (uuid_generate_v4(), NULL, 'EMPLOYEE', 'CERTIFICATION', 'Professional Certification', FALSE, TRUE, 60),
            (uuid_generate_v4(), NULL, 'EMPLOYEE', 'LICENSE', 'License', FALSE, TRUE, 60),
            (uuid_generate_v4(), NULL, 'EMPLOYEE', 'EMPLOYMENT_CONTRACT', 'Employment Contract', TRUE, FALSE, 30),
            (uuid_generate_v4(), NULL, 'EMPLOYEE', 'OTHER', 'Other Document', FALSE, TRUE, 30),
            (uuid_generate_v4(), NULL, 'VENDOR', 'GST_CERTIFICATE', 'GST Certificate', TRUE, TRUE, 30),
            (uuid_generate_v4(), NULL, 'VENDOR', 'PAN_CARD', 'PAN Card', TRUE, FALSE, 30),
            (uuid_generate_v4(), NULL, 'VENDOR', 'TRADE_LICENSE', 'Trade License', TRUE, TRUE, 45),
            (uuid_generate_v4(), NULL, 'VENDOR', 'COMPLIANCE_CERTIFICATE', 'Compliance Certificate', FALSE, TRUE, 30),
            (uuid_generate_v4(), NULL, 'VENDOR', 'OTHER', 'Other Document', FALSE, TRUE, 30)
        """
    )

    op.create_table(
        "revalidation_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("has_expiry", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("manually_reviewed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'PENDING_UPLOAD'"),
            nullable=False,
        ),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("alert_days_before", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("last_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["revalidation_subjects.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "revalidation_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revalidation_doc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_type", sa.String(length=30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["revalidation_doc_id"], ["revalidation_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute("ALTER TABLE revalidation_subjects ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON revalidation_subjects
          USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid)
        """
    )

    op.execute("ALTER TABLE revalidation_documents ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON revalidation_documents
          USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid)
        """
    )

    op.execute("ALTER TABLE revalidation_alerts ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON revalidation_alerts
          USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid)
        """
    )

    op.execute("ALTER TABLE revalidation_doc_catalog ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY catalog_tenant_isolation ON revalidation_doc_catalog
          USING (
            tenant_id IS NULL OR
            tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS catalog_tenant_isolation ON revalidation_doc_catalog")
    op.execute("ALTER TABLE revalidation_doc_catalog DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON revalidation_alerts")
    op.execute("ALTER TABLE revalidation_alerts DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON revalidation_documents")
    op.execute("ALTER TABLE revalidation_documents DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON revalidation_subjects")
    op.execute("ALTER TABLE revalidation_subjects DISABLE ROW LEVEL SECURITY")

    op.drop_table("revalidation_alerts")
    op.drop_table("revalidation_documents")
    op.drop_table("revalidation_doc_catalog")
    op.drop_table("revalidation_subjects")
