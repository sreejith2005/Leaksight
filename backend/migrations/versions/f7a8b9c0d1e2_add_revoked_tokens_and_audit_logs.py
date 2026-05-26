"""add_revoked_tokens_and_audit_logs

Revision ID: f7a8b9c0d1e2
Revises: e65c379efa6e
Create Date: 2026-04-19 17:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e65c379efa6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column(
            "revoked_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_revoked_tokens_jti"),
    )
    op.create_index("idx_revoked_tokens_jti", "revoked_tokens", ["jti"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_revoked_tokens()
        RETURNS integer AS $$
        DECLARE
            deleted_count integer;
        BEGIN
            DELETE FROM revoked_tokens
            WHERE expires_at < NOW();
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "details_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_audit_logs_action_created_at",
        "audit_logs",
        ["action", "created_at"],
    )

    op.execute("GRANT ALL ON revoked_tokens TO app_admin")
    op.execute("GRANT SELECT, INSERT, DELETE ON revoked_tokens TO app_tenant_user")
    op.execute("GRANT ALL ON audit_logs TO app_admin")


def downgrade() -> None:
    op.execute("REVOKE ALL ON audit_logs FROM app_admin")
    op.execute("REVOKE SELECT, INSERT, DELETE ON revoked_tokens FROM app_tenant_user")
    op.execute("REVOKE ALL ON revoked_tokens FROM app_admin")

    op.drop_index("idx_audit_logs_action_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.execute("DROP FUNCTION IF EXISTS cleanup_revoked_tokens()")
    op.drop_index("idx_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
