"""phase8_notifications_table

Source: docs/DATABASE_SCHEMA.md (Section 4.4 — notifications)
       docs/DECISIONS.md (ADR-004 — RLS requirement)

Creates the notifications table with:
  - All required columns for IN_APP and EMAIL channels
  - notification_type_enum and notification_channel_enum
  - RLS policy + FORCE ROW LEVEL SECURITY
  - FK to users.id and analysis_runs.id
  - Partial index on unread notifications
  - GRANT permissions to app_admin and app_tenant_user

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Create enums ---
    notification_type_enum = postgresql.ENUM(
        'RUN_COMPLETE', 'RUN_PARTIAL_SUCCESS', 'RUN_FAILED',
        name='notification_type_enum',
        create_type=False,
    )
    notification_channel_enum = postgresql.ENUM(
        'IN_APP', 'EMAIL',
        name='notification_channel_enum',
        create_type=False,
    )

    op.execute("CREATE TYPE notification_type_enum AS ENUM ('RUN_COMPLETE', 'RUN_PARTIAL_SUCCESS', 'RUN_FAILED')")
    op.execute("CREATE TYPE notification_channel_enum AS ENUM ('IN_APP', 'EMAIL')")

    # --- Create notifications table ---
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('notification_type', notification_type_enum, nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('channel', notification_channel_enum, nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('read_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('email_sent_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('email_failed_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_notifications_tenant'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_notifications_user'),
        sa.ForeignKeyConstraint(['run_id'], ['analysis_runs.id'], name='fk_notifications_run'),
    )

    # --- Indexes ---
    op.create_index('idx_notifications_tenant', 'notifications', ['tenant_id'])
    op.create_index('idx_notifications_user', 'notifications', ['tenant_id', 'user_id'])
    op.create_index('idx_notifications_run', 'notifications', ['run_id'])

    # Partial index for unread notifications
    op.execute("""
        CREATE INDEX idx_notifications_user_unread
        ON notifications(tenant_id, user_id, read_at)
        WHERE read_at IS NULL
    """)

    # --- RLS ---
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY notifications_tenant_isolation ON notifications
        USING (tenant_id::text = current_setting('app.current_tenant_id'))
    """)

    # --- Grants ---
    op.execute("GRANT SELECT, INSERT ON notifications TO app_tenant_user")
    op.execute("GRANT ALL ON notifications TO app_admin")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS notifications_tenant_isolation ON notifications")
    op.execute("ALTER TABLE notifications DISABLE ROW LEVEL SECURITY")
    op.drop_index('idx_notifications_user_unread', table_name='notifications')
    op.drop_index('idx_notifications_run', table_name='notifications')
    op.drop_index('idx_notifications_user', table_name='notifications')
    op.drop_index('idx_notifications_tenant', table_name='notifications')
    op.drop_table('notifications')
    op.execute("DROP TYPE IF EXISTS notification_channel_enum")
    op.execute("DROP TYPE IF EXISTS notification_type_enum")
