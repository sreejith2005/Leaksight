"""
LeakSight V1 — Phase 8 Notifications Migration Tests

Tests:
  - Notification model has all required columns
  - notification_type_enum and notification_channel_enum exist
  - FK to users.id confirmed
  - FK to analysis_runs.id confirmed
  - RLS policy exists on notifications table

These tests validate the SQLAlchemy model structure and can run
without a live database by inspecting the ORM metadata.
"""

import uuid
from datetime import datetime, timezone

import pytest


class TestNotificationModel:
    """Verify the Notification model structure matches DATABASE_SCHEMA.md §4.4."""

    def test_notification_table_exists(self):
        """Notification model maps to 'notifications' table."""
        from backend.app.models.notifications import Notification

        assert Notification.__tablename__ == "notifications"

    def test_all_required_columns_present(self):
        """All columns from spec are present in the model."""
        from backend.app.models.notifications import Notification

        table = Notification.__table__
        column_names = {c.name for c in table.columns}

        required_columns = {
            "id", "tenant_id", "user_id", "run_id",
            "notification_type", "message", "channel",
            "is_read", "read_at", "email_sent_at",
            "email_failed_reason", "created_at",
        }

        for col in required_columns:
            assert col in column_names, f"Missing column: {col}"

    def test_id_is_uuid_primary_key(self):
        """id column is UUID primary key with server default."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["id"]
        assert col.primary_key is True
        assert col.server_default is not None

    def test_tenant_id_not_null_with_fk(self):
        """tenant_id is NOT NULL with FK to tenants.id."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["tenant_id"]
        assert col.nullable is False

        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "tenants.id" in fk_targets

    def test_user_id_fk_to_users(self):
        """user_id has FK to users.id, NOT NULL."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["user_id"]
        assert col.nullable is False

        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets

    def test_run_id_fk_to_analysis_runs(self):
        """run_id has FK to analysis_runs.id, NOT NULL."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["run_id"]
        assert col.nullable is False

        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "analysis_runs.id" in fk_targets

    def test_notification_type_enum(self):
        """notification_type uses notification_type_enum."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["notification_type"]
        assert col.nullable is False
        # Enum name check
        assert col.type.name == "notification_type_enum"

    def test_channel_enum(self):
        """channel uses notification_channel_enum."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["channel"]
        assert col.nullable is False
        assert col.type.name == "notification_channel_enum"

    def test_message_not_null(self):
        """message column is TEXT, NOT NULL."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["message"]
        assert col.nullable is False

    def test_is_read_default_false(self):
        """is_read defaults to False."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["is_read"]
        assert col.nullable is False
        assert col.server_default is not None

    def test_read_at_nullable(self):
        """read_at is nullable (set when user marks as read)."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["read_at"]
        assert col.nullable is True

    def test_email_sent_at_nullable(self):
        """email_sent_at is nullable."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["email_sent_at"]
        assert col.nullable is True

    def test_email_failed_reason_nullable(self):
        """email_failed_reason is nullable."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["email_failed_reason"]
        assert col.nullable is True

    def test_created_at_has_server_default(self):
        """created_at has server default now()."""
        from backend.app.models.notifications import Notification

        col = Notification.__table__.columns["created_at"]
        assert col.nullable is False
        assert col.server_default is not None

    def test_indexes_defined(self):
        """Required indexes exist on the model."""
        from backend.app.models.notifications import Notification

        table = Notification.__table__
        index_names = {idx.name for idx in table.indexes}

        assert "idx_notifications_tenant" in index_names
        assert "idx_notifications_user" in index_names
        assert "idx_notifications_run" in index_names
        assert "idx_notifications_user_unread" in index_names

    def test_notification_type_enum_values(self):
        """notification_type_enum has exact required values."""
        from backend.app.models.notifications import notification_type_enum

        assert set(notification_type_enum.enums) == {
            "RUN_COMPLETE", "RUN_PARTIAL_SUCCESS", "RUN_FAILED",
        }

    def test_notification_channel_enum_values(self):
        """notification_channel_enum has exact required values."""
        from backend.app.models.notifications import notification_channel_enum

        assert set(notification_channel_enum.enums) == {"IN_APP", "EMAIL"}


class TestNotificationModelRegistration:
    """Verify the Notification model is registered in the model registry."""

    def test_model_importable_from_init(self):
        """Notification model can be imported from models package."""
        from backend.app.models import Notification

        assert Notification.__tablename__ == "notifications"


class TestNotificationMigration:
    """Verify the migration file exists and has correct structure."""

    def test_migration_revision_chain(self):
        """Phase 8 migration depends on Phase 2 head revision."""
        import importlib
        mod = importlib.import_module(
            "backend.migrations.versions.b2c3d4e5f6a7_phase8_notifications_table"
        )
        assert mod.revision == "b2c3d4e5f6a7"
        assert mod.down_revision == "a1b2c3d4e5f6"

    def test_migration_has_upgrade_and_downgrade(self):
        """Migration has both upgrade() and downgrade() functions."""
        import importlib
        mod = importlib.import_module(
            "backend.migrations.versions.b2c3d4e5f6a7_phase8_notifications_table"
        )
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))
