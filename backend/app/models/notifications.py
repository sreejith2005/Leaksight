"""
LeakSight V1 — Notifications Model

Source: docs/DATABASE_SCHEMA.md (Section 4.4 — notifications)
       docs/DECISIONS.md (ADR-004 — RLS, ADR-005 — no real-time push)
       docs/ARCHITECTURE.md (Section 6.3 — notification_service)

Stores both IN_APP and EMAIL notification records.
RLS-scoped by tenant_id.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base

# --- Enums ---
notification_type_enum = Enum(
    "RUN_COMPLETE", "RUN_PARTIAL_SUCCESS", "RUN_FAILED",
    name="notification_type_enum",
    create_type=True,
)

notification_channel_enum = Enum(
    "IN_APP", "EMAIL",
    name="notification_channel_enum",
    create_type=True,
)


class Notification(Base):
    """In-app and email notification records for users.

    Both IN_APP and EMAIL channels create a row here. IN_APP notifications
    have is_read/read_at tracking. EMAIL notifications have email_sent_at
    and email_failed_reason tracking.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"), nullable=False)
    notification_type = Column(notification_type_enum, nullable=False)
    message = Column(Text, nullable=False)
    channel = Column(notification_channel_enum, nullable=False)
    is_read = Column(Boolean, nullable=False, server_default="false")
    read_at = Column(TIMESTAMP(timezone=True), nullable=True)
    email_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    email_failed_reason = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_notifications_tenant", "tenant_id"),
        Index("idx_notifications_user", "tenant_id", "user_id"),
        Index(
            "idx_notifications_user_unread",
            "tenant_id", "user_id", "read_at",
            postgresql_where="read_at IS NULL",
        ),
        Index("idx_notifications_run", "run_id"),
    )
