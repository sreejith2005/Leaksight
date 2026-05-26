"""
LeakSight V1 — E2E Notification Test (Phase 8.5)

Tests the complete notification flow from analysis run completion through
to notification retrieval via API. Uses mocked SMTP and mocked DB.

16 assertions across 4 test scenarios:

 1. COMPLETE run → in-app + email notifications created, message content correct
 2. PARTIAL_SUCCESS run → message includes partial notes + FX section
 3. Email SMTP failure → in-app still created, email_failed_reason populated
 4. API retrieval → list returns notifications, mark-read updates read_at
"""

import smtplib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.notifications import router as notifications_router
from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.services.notification_service import (
    NotificationResult,
    RunNotificationData,
    _format_message,
    send_email_smtp,
    send_run_notifications,
)


# ═══════════════════════════════════════════════════════════════════════
# Test constants
# ═══════════════════════════════════════════════════════════════════════

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
RUN_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")


def _user():
    return CurrentUser(
        user_id=USER_ID, tenant_id=TENANT_ID, email="user@test.com", role="ADMIN"
    )


def _mock_user(user_id=None, email="user@test.com"):
    u = MagicMock()
    u.id = user_id or USER_ID
    u.tenant_id = TENANT_ID
    u.email = email
    u.is_active = True
    return u


def _create_api_app(db_mock):
    """Create a FastAPI test app with notification endpoints."""
    app = FastAPI()
    r = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
    r.include_router(notifications_router)
    app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: _user()

    async def _db():
        yield db_mock

    app.dependency_overrides[get_db] = _db
    return app


# ═══════════════════════════════════════════════════════════════════════
# Scenario 1: COMPLETE run → full notification flow
# ═══════════════════════════════════════════════════════════════════════


class TestE2ECompleteRun:
    """End-to-end: COMPLETE run creates both in-app and email notifications."""

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_complete_run_creates_notifications(self, mock_summary, mock_email):
        """Assertion 1-4: COMPLETE run creates correct in-app and email records."""
        mock_summary.return_value = RunNotificationData(
            run_id=RUN_ID,
            run_status="COMPLETE",
            total_amount=Decimal("25000.00"),
            currency="INR",
            record_count=15,
            pending_review_count=10,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        mock_email.return_value = True

        user1 = _mock_user()

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user1]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(RUN_ID, TENANT_ID, "COMPLETE", db)

        # Assertion 1: NotificationResult has correct counts
        assert result.in_app_notifications_created == 1
        # Assertion 2: Email was sent
        assert result.emails_sent == 1
        # Assertion 3: No email failures
        assert result.emails_failed == 0
        # Assertion 4: Final status matches
        assert result.final_status == "COMPLETE"

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_complete_message_content(self, mock_summary, mock_email):
        """Assertion 5-6: COMPLETE message contains correct data."""
        mock_summary.return_value = RunNotificationData(
            run_id=RUN_ID,
            run_status="COMPLETE",
            total_amount=Decimal("25000.00"),
            currency="INR",
            record_count=15,
            pending_review_count=10,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        mock_email.return_value = True

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [_mock_user()]
        db.execute = AsyncMock(return_value=users_result)

        await send_run_notifications(RUN_ID, TENANT_ID, "COMPLETE", db)

        # Get the actual IN_APP notification object written to DB
        in_app_obj = db.add.call_args_list[0][0][0]

        # Assertion 5: Message contains financial summary
        assert "25,000.00" in in_app_obj.message
        assert "INR" in in_app_obj.message
        assert "15 findings" in in_app_obj.message

        # Assertion 6: Message contains call-to-action
        assert "review" in in_app_obj.message.lower()


# ═══════════════════════════════════════════════════════════════════════
# Scenario 2: PARTIAL_SUCCESS → message includes notes + FX
# ═══════════════════════════════════════════════════════════════════════


class TestE2EPartialSuccess:
    """End-to-end: PARTIAL_SUCCESS run includes partial notes and FX action."""

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_partial_success_message_content(self, mock_summary, mock_email):
        """Assertion 7-10: PARTIAL_SUCCESS message has notes, FX section, action items."""
        mock_summary.return_value = RunNotificationData(
            run_id=RUN_ID,
            run_status="PARTIAL_SUCCESS",
            total_amount=Decimal("8500.00"),
            currency="USD",
            record_count=7,
            pending_review_count=5,
            pending_fx_rate_count=3,
            partial_success_notes="3 record(s) are pending FX rate upload. 1 document failed.",
        )
        mock_email.return_value = True

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [_mock_user()]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(RUN_ID, TENANT_ID, "PARTIAL_SUCCESS", db)

        in_app_obj = db.add.call_args_list[0][0][0]

        # Assertion 7: notification_type is RUN_PARTIAL_SUCCESS
        assert in_app_obj.notification_type == "RUN_PARTIAL_SUCCESS"

        # Assertion 8: Message mentions partial results
        assert "partial results" in in_app_obj.message

        # Assertion 9: Message contains FX rate action
        assert "FX rates" in in_app_obj.message
        assert "3 findings" in in_app_obj.message

        # Assertion 10: Message includes partial_success_notes
        assert "pending FX rate upload" in in_app_obj.message


# ═══════════════════════════════════════════════════════════════════════
# Scenario 3: Email failure → graceful degradation
# ═══════════════════════════════════════════════════════════════════════


class TestE2EEmailFailure:
    """End-to-end: SMTP failure creates in-app notification + failure record."""

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_email_failure_graceful(self, mock_summary, mock_email):
        """Assertion 11-13: Email failure creates in-app + email failure record."""
        mock_summary.return_value = RunNotificationData(
            run_id=RUN_ID,
            run_status="COMPLETE",
            total_amount=Decimal("5000.00"),
            currency="INR",
            record_count=3,
            pending_review_count=2,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        mock_email.return_value = False  # SMTP fails

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [_mock_user()]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(RUN_ID, TENANT_ID, "COMPLETE", db)

        # Assertion 11: IN_APP notification still created despite email failure
        assert result.in_app_notifications_created == 1

        # Assertion 12: Email failure recorded
        assert result.emails_failed == 1
        assert result.emails_sent == 0

        # Assertion 13: EMAIL notification has failure reason
        email_obj = db.add.call_args_list[1][0][0]  # second db.add call
        assert email_obj.channel == "EMAIL"
        assert email_obj.email_failed_reason == "SMTP send failed"

    @patch("backend.app.services.notification_service.get_settings")
    @patch("backend.app.services.notification_service.smtplib.SMTP")
    def test_smtp_exception_returns_false(self, mock_smtp_class, mock_settings):
        """Assertion 14: Raw SMTP exception is caught — returns False, never propagates."""
        settings = MagicMock()
        settings.smtp_host = "smtp-relay.brevo.com"
        settings.smtp_port = 587
        settings.smtp_user = "test"
        settings.smtp_password = "test"
        settings.smtp_from = "noreply@test.com"
        mock_settings.return_value = settings

        mock_smtp_class.side_effect = smtplib.SMTPConnectError(421, "Service not available")

        result = send_email_smtp("user@test.com", "Test", "Body")

        # Assertion 14: Returns False, no exception raised
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
# Scenario 4: API retrieval + mark-read flow
# ═══════════════════════════════════════════════════════════════════════


class TestE2EApiRetrieval:
    """End-to-end: List notifications via API, then mark as read."""

    @patch("backend.app.api.endpoints.notifications.set_tenant_context")
    def test_list_then_mark_read(self, mock_tc):
        """Assertion 15-16: GET list returns data, PUT mark-read updates timestamp."""
        mock_tc.return_value = None
        db = AsyncMock()
        db.commit = AsyncMock()

        notif_id = uuid.uuid4()
        mock_notif = MagicMock()
        mock_notif.id = notif_id
        mock_notif.message = "Analysis run completed"
        mock_notif.notification_type = "RUN_COMPLETE"
        mock_notif.run_id = RUN_ID
        mock_notif.is_read = False
        mock_notif.read_at = None
        mock_notif.created_at = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        mock_notif.channel = "IN_APP"

        # GET /notifications — returns list
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        unread_result = MagicMock()
        unread_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [mock_notif]

        db.execute = AsyncMock(side_effect=[count_result, unread_result, data_result])

        app = _create_api_app(db)
        client = TestClient(app)

        list_resp = client.get("/api/v1/notifications")

        # Assertion 15: List returns the notification with correct structure
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == str(notif_id)
        assert body["unread_count"] == 1
        assert body["data"][0]["notification_type"] == "RUN_COMPLETE"

        # PUT /{id}/read — mark notification as read
        read_time = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)

        with patch(
            "backend.app.api.endpoints.notifications.mark_notification_read"
        ) as mock_mark:
            marked_notif = MagicMock()
            marked_notif.id = notif_id
            marked_notif.read_at = read_time
            mock_mark.return_value = marked_notif

            read_resp = client.put(f"/api/v1/notifications/{notif_id}/read")

        # Assertion 16: Mark-read returns id and read_at timestamp
        assert read_resp.status_code == 200
        read_body = read_resp.json()
        assert read_body["id"] == str(notif_id)
        assert read_body["read_at"] is not None
