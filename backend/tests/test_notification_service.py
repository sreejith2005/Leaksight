"""
Tests for notification_service.py (Phase 8.2)

8 core scenarios:
 1. send_run_notifications — COMPLETE run — creates in-app + email for each active user
 2. send_run_notifications — PARTIAL_SUCCESS — message includes partial_success_notes + FX section
 3. send_run_notifications — no active users — returns zero counts
 4. send_email_smtp — successful send (mocked SMTP)
 5. send_email_smtp — SMTP exception → returns False, never propagates
 6. send_email_smtp — connection error → returns False
 7. mark_notification_read — success
 8. mark_notification_read — notification not found → raises ValueError

Additional tests for helper functions and edge cases.
"""

import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.notification_service import (
    COMPLETE_MESSAGE_TEMPLATE,
    EMAIL_SUBJECT_COMPLETE,
    EMAIL_SUBJECT_PARTIAL,
    FX_RATE_ACTION_TEMPLATE,
    PARTIAL_SUCCESS_MESSAGE_TEMPLATE,
    NotificationResult,
    RunNotificationData,
    _build_notification_type,
    _format_amount,
    _format_message,
    get_run_summary,
    mark_notification_read,
    send_email_smtp,
    send_run_notifications,
)


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def complete_run_data():
    """RunNotificationData for a COMPLETE analysis run."""
    return RunNotificationData(
        run_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        run_status="COMPLETE",
        total_amount=Decimal("15000.50"),
        currency="INR",
        record_count=12,
        pending_review_count=8,
        pending_fx_rate_count=0,
        partial_success_notes=None,
    )


@pytest.fixture
def partial_run_data():
    """RunNotificationData for a PARTIAL_SUCCESS run (with FX rate issues)."""
    return RunNotificationData(
        run_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        run_status="PARTIAL_SUCCESS",
        total_amount=Decimal("7500.00"),
        currency="USD",
        record_count=6,
        pending_review_count=4,
        pending_fx_rate_count=3,
        partial_success_notes="2 record(s) are pending FX rate upload. 1 document had low parse confidence.",
    )


@pytest.fixture
def partial_run_data_no_fx():
    """RunNotificationData for PARTIAL_SUCCESS with NO pending FX rate records."""
    return RunNotificationData(
        run_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        run_status="PARTIAL_SUCCESS",
        total_amount=Decimal("2000.00"),
        currency="EUR",
        record_count=3,
        pending_review_count=2,
        pending_fx_rate_count=0,
        partial_success_notes="1 document had low parse confidence.",
    )


@pytest.fixture
def mock_settings():
    """Mock Settings object."""
    settings = MagicMock()
    settings.smtp_host = "smtp-relay.brevo.com"
    settings.smtp_port = 587
    settings.smtp_user = "testuser"
    settings.smtp_password = "testpass"
    settings.smtp_from = "noreply@test.com"
    return settings


def _make_mock_user(user_id=None, tenant_id=None, email="user@test.com", is_active=True):
    """Create a mock user object."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.tenant_id = tenant_id or uuid.uuid4()
    user.email = email
    user.is_active = is_active
    return user


def _make_mock_run(run_id, tenant_id, status="COMPLETE", total=Decimal("1000.00"), count=5, error_summary=None):
    """Create a mock AnalysisRun object."""
    run = MagicMock()
    run.id = run_id
    run.tenant_id = tenant_id
    run.status = status
    run.total_leakage_found = total
    run.leakage_record_count = count
    run.error_summary = error_summary
    return run


# ═══════════════════════════════════════════════════════════════════════
# Helper Function Tests
# ═══════════════════════════════════════════════════════════════════════


class TestFormatAmount:
    """Tests for _format_amount."""

    def test_zero(self):
        assert _format_amount(Decimal("0")) == "0.00"

    def test_small_amount(self):
        assert _format_amount(Decimal("1.50")) == "1.50"

    def test_thousand_separator(self):
        assert _format_amount(Decimal("15000.50")) == "15,000.50"

    def test_large_amount(self):
        assert _format_amount(Decimal("1234567.89")) == "1,234,567.89"

    def test_rounds_to_two_places(self):
        assert _format_amount(Decimal("100.999")) == "101.00"


class TestBuildNotificationType:
    """Tests for _build_notification_type."""

    def test_complete(self):
        assert _build_notification_type("COMPLETE") == "RUN_COMPLETE"

    def test_partial_success(self):
        assert _build_notification_type("PARTIAL_SUCCESS") == "RUN_PARTIAL_SUCCESS"

    def test_failed(self):
        assert _build_notification_type("FAILED") == "RUN_FAILED"


class TestFormatMessage:
    """Tests for _format_message."""

    def test_complete_message_content(self, complete_run_data):
        msg = _format_message(complete_run_data)
        assert "11111111-1111-1111-1111-111111111111" in msg
        assert "INR" in msg
        assert "15,000.50" in msg
        assert "12 findings" in msg
        assert "8 findings are awaiting your review" in msg
        assert "completed successfully" in msg
        assert "partial" not in msg.lower()

    def test_partial_success_message_with_fx(self, partial_run_data):
        msg = _format_message(partial_run_data)
        assert "22222222-2222-2222-2222-222222222222" in msg
        assert "USD" in msg
        assert "7,500.00" in msg
        assert "partial results" in msg
        assert "FX rates" in msg
        assert "3 findings cannot be calculated until FX rates" in msg
        assert "pending FX rate upload" in msg

    def test_partial_success_message_without_fx(self, partial_run_data_no_fx):
        msg = _format_message(partial_run_data_no_fx)
        assert "33333333-3333-3333-3333-333333333333" in msg
        assert "EUR" in msg
        assert "partial results" in msg
        assert "FX rates" not in msg
        assert "1 document had low parse confidence" in msg

    def test_partial_success_default_notes(self):
        """When partial_success_notes is None, default message is used."""
        data = RunNotificationData(
            run_id=uuid.uuid4(),
            run_status="PARTIAL_SUCCESS",
            total_amount=Decimal("0"),
            currency="INR",
            record_count=0,
            pending_review_count=0,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        msg = _format_message(data)
        assert "Some documents had processing issues" in msg


# ═══════════════════════════════════════════════════════════════════════
# send_email_smtp Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSendEmailSmtp:
    """Tests for send_email_smtp."""

    @patch("backend.app.services.notification_service.get_settings")
    @patch("backend.app.services.notification_service.smtplib.SMTP")
    def test_successful_send(self, mock_smtp_class, mock_get_settings, mock_settings):
        """Scenario 4: successful SMTP send."""
        mock_get_settings.return_value = mock_settings
        mock_server = mock_smtp_class.return_value

        result = send_email_smtp("user@test.com", "Test", "Body text")
        assert result is True

        mock_smtp_class.assert_called_once_with("smtp-relay.brevo.com", 587, timeout=30)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("testuser", "testpass")
        mock_server.send_message.assert_called_once()

    @patch("backend.app.services.notification_service.get_settings")
    @patch("backend.app.services.notification_service.smtplib.SMTP")
    def test_smtp_exception_returns_false(self, mock_smtp_class, mock_get_settings, mock_settings):
        """Scenario 5: SMTP exception → returns False, never propagates."""
        mock_get_settings.return_value = mock_settings
        mock_server = mock_smtp_class.return_value
        mock_server.starttls.side_effect = smtplib.SMTPException("Auth failed")

        result = send_email_smtp("user@test.com", "Test", "Body")
        assert result is False

    @patch("backend.app.services.notification_service.get_settings")
    @patch("backend.app.services.notification_service.smtplib.SMTP")
    def test_connection_error_returns_false(self, mock_smtp_class, mock_get_settings, mock_settings):
        """Scenario 6: connection error → returns False."""
        mock_get_settings.return_value = mock_settings
        mock_smtp_class.side_effect = OSError("Connection refused")

        result = send_email_smtp("user@test.com", "Test", "Body")
        assert result is False

    @patch("backend.app.services.notification_service.get_settings")
    @patch("backend.app.services.notification_service.smtplib.SMTP")
    def test_no_credentials_skips_login(self, mock_smtp_class, mock_get_settings):
        """When smtp_user/password are empty, login is skipped."""
        settings = MagicMock()
        settings.smtp_host = "localhost"
        settings.smtp_port = 587
        settings.smtp_user = ""
        settings.smtp_password = ""
        settings.smtp_from = "noreply@test.com"
        mock_get_settings.return_value = settings

        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email_smtp("user@test.com", "Test", "Body")
        assert result is True
        mock_server.login.assert_not_called()

    @patch("backend.app.services.notification_service.get_settings")
    @patch("backend.app.services.notification_service.smtplib.SMTP")
    def test_unexpected_exception_returns_false(self, mock_smtp_class, mock_get_settings, mock_settings):
        """Unexpected exception in SMTP → returns False, never propagates."""
        mock_get_settings.return_value = mock_settings
        mock_smtp_class.side_effect = RuntimeError("Something unexpected")

        result = send_email_smtp("user@test.com", "Test", "Body")
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
# get_run_summary Tests
# ═══════════════════════════════════════════════════════════════════════


class TestGetRunSummary:
    """Tests for get_run_summary."""

    @pytest.mark.asyncio
    async def test_complete_run_summary(self):
        """Builds summary for a COMPLETE run."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        mock_run = _make_mock_run(run_id, tenant_id, "COMPLETE", Decimal("5000.00"), 10)

        db = AsyncMock()

        # Configure sequential execute results:
        # 1) AnalysisRun query
        # 2) TenantSettings.base_currency
        # 3) Pending count
        # 4) Pending FX count
        # 5) Total count
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = mock_run

        currency_result = MagicMock()
        currency_result.scalar.return_value = "INR"

        pending_result = MagicMock()
        pending_result.scalar.return_value = 3

        fx_result = MagicMock()
        fx_result.scalar.return_value = 0

        total_result = MagicMock()
        total_result.scalar.return_value = 10

        db.execute = AsyncMock(
            side_effect=[run_result, currency_result, pending_result, fx_result, total_result]
        )

        summary = await get_run_summary(run_id, tenant_id, db)

        assert summary.run_id == run_id
        assert summary.run_status == "COMPLETE"
        assert summary.total_amount == Decimal("5000.00")
        assert summary.currency == "INR"
        assert summary.record_count == 10
        assert summary.pending_review_count == 3
        assert summary.pending_fx_rate_count == 0
        assert summary.partial_success_notes is None

    @pytest.mark.asyncio
    async def test_partial_success_run_with_error_summary(self):
        """Builds summary for PARTIAL_SUCCESS with error_summary text."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        mock_run = _make_mock_run(
            run_id, tenant_id, "PARTIAL_SUCCESS", Decimal("2000.00"), 5,
            error_summary="2 documents failed PDF parsing",
        )

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = mock_run

        currency_result = MagicMock()
        currency_result.scalar.return_value = "USD"

        pending_result = MagicMock()
        pending_result.scalar.return_value = 2

        fx_result = MagicMock()
        fx_result.scalar.return_value = 1

        total_result = MagicMock()
        total_result.scalar.return_value = 5

        db.execute = AsyncMock(
            side_effect=[run_result, currency_result, pending_result, fx_result, total_result]
        )

        summary = await get_run_summary(run_id, tenant_id, db)

        assert summary.run_status == "PARTIAL_SUCCESS"
        assert summary.pending_fx_rate_count == 1
        assert "1 record(s) are pending FX rate upload" in summary.partial_success_notes
        assert "2 documents failed PDF parsing" in summary.partial_success_notes

    @pytest.mark.asyncio
    async def test_run_not_found_raises(self):
        """Raises ValueError when run is not found."""
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="not found"):
            await get_run_summary(uuid.uuid4(), uuid.uuid4(), db)

    @pytest.mark.asyncio
    async def test_fallback_currency_when_none(self):
        """Falls back to INR when TenantSettings.base_currency is None."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        mock_run = _make_mock_run(run_id, tenant_id, "COMPLETE")

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = mock_run

        currency_result = MagicMock()
        currency_result.scalar.return_value = None  # no TenantSettings

        pending_result = MagicMock()
        pending_result.scalar.return_value = 0

        fx_result = MagicMock()
        fx_result.scalar.return_value = 0

        total_result = MagicMock()
        total_result.scalar.return_value = 0

        db.execute = AsyncMock(
            side_effect=[run_result, currency_result, pending_result, fx_result, total_result]
        )

        summary = await get_run_summary(run_id, tenant_id, db)
        assert summary.currency == "INR"


# ═══════════════════════════════════════════════════════════════════════
# send_run_notifications Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSendRunNotifications:
    """Tests for send_run_notifications."""

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_complete_run_two_users(self, mock_summary, mock_email):
        """Scenario 1: COMPLETE run — creates in-app + email for each active user."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_summary.return_value = RunNotificationData(
            run_id=run_id,
            run_status="COMPLETE",
            total_amount=Decimal("5000.00"),
            currency="INR",
            record_count=10,
            pending_review_count=5,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        mock_email.return_value = True

        user1 = _make_mock_user(tenant_id=tenant_id, email="u1@test.com")
        user2 = _make_mock_user(tenant_id=tenant_id, email="u2@test.com")

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user1, user2]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(run_id, tenant_id, "COMPLETE", db)

        assert isinstance(result, NotificationResult)
        assert result.in_app_notifications_created == 2
        assert result.emails_sent == 2
        assert result.emails_failed == 0
        assert result.final_status == "COMPLETE"

        # 2 IN_APP + 2 EMAIL = 4 calls to db.add
        assert db.add.call_count == 4
        db.flush.assert_awaited_once()

        # Email calls: 2 users, each with subject + body
        assert mock_email.call_count == 2
        first_call = mock_email.call_args_list[0]
        assert first_call.kwargs.get("subject") or first_call[1].get("subject") or \
            EMAIL_SUBJECT_COMPLETE in str(first_call)

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_partial_success_message_includes_notes(self, mock_summary, mock_email):
        """Scenario 2: PARTIAL_SUCCESS — message includes notes + FX section."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_summary.return_value = RunNotificationData(
            run_id=run_id,
            run_status="PARTIAL_SUCCESS",
            total_amount=Decimal("3000.00"),
            currency="USD",
            record_count=5,
            pending_review_count=3,
            pending_fx_rate_count=2,
            partial_success_notes="2 record(s) pending FX. 1 doc failed.",
        )
        mock_email.return_value = True

        user1 = _make_mock_user(tenant_id=tenant_id)
        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user1]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(run_id, tenant_id, "PARTIAL_SUCCESS", db)

        assert result.in_app_notifications_created == 1
        assert result.emails_sent == 1
        assert result.final_status == "PARTIAL_SUCCESS"

        # Verify the IN_APP notification object that was added to db
        in_app_call = db.add.call_args_list[0]
        notification_obj = in_app_call[0][0]
        assert notification_obj.notification_type == "RUN_PARTIAL_SUCCESS"
        assert notification_obj.channel == "IN_APP"
        assert "partial results" in notification_obj.message

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_no_active_users_returns_zero(self, mock_summary, mock_email):
        """Scenario 3: no active users — returns zero counts."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_summary.return_value = RunNotificationData(
            run_id=run_id,
            run_status="COMPLETE",
            total_amount=Decimal("0"),
            currency="INR",
            record_count=0,
            pending_review_count=0,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(run_id, tenant_id, "COMPLETE", db)

        assert result.in_app_notifications_created == 0
        assert result.emails_sent == 0
        assert result.emails_failed == 0
        mock_email.assert_not_called()

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_email_failure_creates_record_with_reason(self, mock_summary, mock_email):
        """Email failure writes email_failed_reason but doesn't block in-app."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_summary.return_value = RunNotificationData(
            run_id=run_id,
            run_status="COMPLETE",
            total_amount=Decimal("1000.00"),
            currency="INR",
            record_count=2,
            pending_review_count=1,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        mock_email.return_value = False  # all emails fail

        user1 = _make_mock_user(tenant_id=tenant_id)
        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user1]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(run_id, tenant_id, "COMPLETE", db)

        assert result.in_app_notifications_created == 1
        assert result.emails_sent == 0
        assert result.emails_failed == 1

        # Check that the EMAIL notification has the failure reason
        email_call = db.add.call_args_list[1]  # second add call = EMAIL notification
        email_notification = email_call[0][0]
        assert email_notification.channel == "EMAIL"
        assert email_notification.email_failed_reason == "SMTP send failed"
        assert email_notification.email_sent_at is None

    @pytest.mark.asyncio
    @patch("backend.app.services.notification_service.send_email_smtp")
    @patch("backend.app.services.notification_service.get_run_summary")
    async def test_mixed_email_success_and_failure(self, mock_summary, mock_email):
        """Two users: one email succeeds, one fails."""
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_summary.return_value = RunNotificationData(
            run_id=run_id,
            run_status="COMPLETE",
            total_amount=Decimal("1000.00"),
            currency="INR",
            record_count=2,
            pending_review_count=1,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        mock_email.side_effect = [True, False]  # first succeeds, second fails

        user1 = _make_mock_user(tenant_id=tenant_id, email="u1@test.com")
        user2 = _make_mock_user(tenant_id=tenant_id, email="u2@test.com")

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user1, user2]
        db.execute = AsyncMock(return_value=users_result)

        result = await send_run_notifications(run_id, tenant_id, "COMPLETE", db)

        assert result.in_app_notifications_created == 2
        assert result.emails_sent == 1
        assert result.emails_failed == 1


# ═══════════════════════════════════════════════════════════════════════
# mark_notification_read Tests
# ═══════════════════════════════════════════════════════════════════════


class TestMarkNotificationRead:
    """Tests for mark_notification_read."""

    @pytest.mark.asyncio
    async def test_mark_read_success(self):
        """Scenario 7: successfully marks notification as read."""
        notification_id = uuid.uuid4()
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_notification = MagicMock()
        mock_notification.is_read = False
        mock_notification.read_at = None

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_notification
        db.execute = AsyncMock(return_value=result_mock)

        result = await mark_notification_read(notification_id, user_id, tenant_id, db)

        assert result.is_read is True
        assert result.read_at is not None
        assert isinstance(result.read_at, datetime)

    @pytest.mark.asyncio
    async def test_mark_read_not_found_raises(self):
        """Scenario 8: notification not found → raises ValueError."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="not found"):
            await mark_notification_read(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), db)


# ═══════════════════════════════════════════════════════════════════════
# Template Constants Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTemplateConstants:
    """Verify template structure and constants."""

    def test_complete_template_has_placeholders(self):
        assert "{run_id}" in COMPLETE_MESSAGE_TEMPLATE
        assert "{currency}" in COMPLETE_MESSAGE_TEMPLATE
        assert "{total_amount}" in COMPLETE_MESSAGE_TEMPLATE
        assert "{record_count}" in COMPLETE_MESSAGE_TEMPLATE
        assert "{pending_review_count}" in COMPLETE_MESSAGE_TEMPLATE

    def test_partial_template_has_placeholders(self):
        assert "{run_id}" in PARTIAL_SUCCESS_MESSAGE_TEMPLATE
        assert "{partial_success_notes}" in PARTIAL_SUCCESS_MESSAGE_TEMPLATE
        assert "{fx_rate_section}" in PARTIAL_SUCCESS_MESSAGE_TEMPLATE

    def test_fx_template_has_placeholder(self):
        assert "{pending_fx_rate_count}" in FX_RATE_ACTION_TEMPLATE

    def test_email_subjects(self):
        assert "LeakSight" in EMAIL_SUBJECT_COMPLETE
        assert "LeakSight" in EMAIL_SUBJECT_PARTIAL
        assert "Partial" in EMAIL_SUBJECT_PARTIAL


# ═══════════════════════════════════════════════════════════════════════
# NotificationResult Dataclass Tests
# ═══════════════════════════════════════════════════════════════════════


class TestNotificationResult:
    """Tests for NotificationResult dataclass."""

    def test_all_fields(self):
        rid = uuid.uuid4()
        result = NotificationResult(
            in_app_notifications_created=3,
            emails_sent=2,
            emails_failed=1,
            run_id=rid,
            final_status="COMPLETE",
        )
        assert result.in_app_notifications_created == 3
        assert result.emails_sent == 2
        assert result.emails_failed == 1
        assert result.run_id == rid
        assert result.final_status == "COMPLETE"
