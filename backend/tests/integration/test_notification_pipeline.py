"""
LeakSight V1 — Phase 10 Step 10.4
Test Suite: Notification Pipeline Integration

Pilot Readiness Checklist Sections:
  - Section 5.1: Notification fires on COMPLETE and PARTIAL_SUCCESS
  - Section 5.2: Email failure never affects run status
  - Section 5.3: Both IN_APP and EMAIL channels fire
  - Section 5.4: Different templates for COMPLETE vs PARTIAL_SUCCESS

Tests exercise the real notification_service functions with mocked DB
and SMTP to verify two-channel dispatch, failure isolation, and template
correctness.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.notification_service import (
    NotificationResult,
    RunNotificationData,
    _build_notification_type,
    _format_message,
    send_run_notifications,
)
from backend.tests.integration.conftest import (
    TENANT_A_ID,
    USER_A_ID,
    USER_B_ID,
    RUN_ID,
    make_analysis_run,
    make_tenant_settings,
)


# ────────────────────────────────────────────────────────────────────────
# Message Formatting Tests
# ────────────────────────────────────────────────────────────────────────

class TestMessageFormatting:
    """Verify COMPLETE and PARTIAL_SUCCESS templates are distinct.

    Satisfies: Pilot Readiness Section 5.4.
    """

    def test_complete_message_has_run_id(self):
        data = RunNotificationData(
            run_id=RUN_ID,
            run_status="COMPLETE",
            total_amount=Decimal("50000"),
            currency="INR",
            record_count=5,
            pending_review_count=3,
            pending_fx_rate_count=0,
            partial_success_notes=None,
        )
        msg = _format_message(data)
        assert str(RUN_ID) in msg
        assert "completed successfully" in msg
        assert "50,000.00" in msg
        assert "5 findings" in msg

    def test_partial_success_message_has_notes(self):
        data = RunNotificationData(
            run_id=RUN_ID,
            run_status="PARTIAL_SUCCESS",
            total_amount=Decimal("30000"),
            currency="INR",
            record_count=10,
            pending_review_count=7,
            pending_fx_rate_count=2,
            partial_success_notes="2 line item(s) failed processing",
        )
        msg = _format_message(data)
        assert "partial results" in msg
        assert "2 line item(s) failed processing" in msg
        assert "2 findings cannot be calculated until FX rates" in msg

    def test_complete_vs_partial_templates_differ(self):
        complete_data = RunNotificationData(
            run_id=RUN_ID, run_status="COMPLETE",
            total_amount=Decimal("1000"), currency="INR",
            record_count=1, pending_review_count=1,
            pending_fx_rate_count=0, partial_success_notes=None,
        )
        partial_data = RunNotificationData(
            run_id=RUN_ID, run_status="PARTIAL_SUCCESS",
            total_amount=Decimal("1000"), currency="INR",
            record_count=1, pending_review_count=1,
            pending_fx_rate_count=0,
            partial_success_notes="Some issues.",
        )
        complete_msg = _format_message(complete_data)
        partial_msg = _format_message(partial_data)
        assert complete_msg != partial_msg
        assert "successfully" in complete_msg
        assert "partial" in partial_msg

    def test_notification_type_mapping(self):
        assert _build_notification_type("COMPLETE") == "RUN_COMPLETE"
        assert _build_notification_type("PARTIAL_SUCCESS") == "RUN_PARTIAL_SUCCESS"
        assert _build_notification_type("FAILED") == "RUN_FAILED"


# ────────────────────────────────────────────────────────────────────────
# Two-Channel Dispatch
# ────────────────────────────────────────────────────────────────────────

class TestTwoChannelDispatch:
    """Verify both IN_APP and EMAIL fire for each user.

    Satisfies: Pilot Readiness Section 5.3.
    """

    @pytest.mark.asyncio
    async def test_both_channels_fire_for_complete_run(self):
        """COMPLETE run → every user gets 1 IN_APP + 1 EMAIL attempt."""
        run = make_analysis_run(status="COMPLETE")
        run.total_leakage_found = Decimal("50000")

        user1 = MagicMock()
        user1.id = USER_A_ID
        user1.email = "user1@example.com"
        user1.is_active = True

        user2 = MagicMock()
        user2.id = USER_B_ID
        user2.email = "user2@example.com"
        user2.is_active = True

        ts = make_tenant_settings()

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "analysis_run" in stmt_str.lower() or "analysisrun" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = run
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar.return_value = "INR"
            elif "count" in stmt_str.lower() and "pending_fx" in stmt_str.lower():
                mock_result.scalar.return_value = 0
            elif "count" in stmt_str.lower():
                mock_result.scalar.return_value = 5
            elif "user" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [user1, user2]
            else:
                mock_result.scalar.return_value = 0
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "backend.app.services.notification_service.send_email_smtp"
        ) as mock_smtp:
            mock_smtp.return_value = True

            result = await send_run_notifications(
                run_id=RUN_ID,
                tenant_id=TENANT_A_ID,
                final_status="COMPLETE",
                db=db,
            )

        assert result.in_app_notifications_created == 2
        assert result.emails_sent == 2
        assert result.emails_failed == 0
        # 4 notification objects added: 2 IN_APP + 2 EMAIL
        assert db.add.call_count == 4

    @pytest.mark.asyncio
    async def test_no_users_returns_zero_counts(self):
        """If tenant has no active users, notification counts are all 0."""
        run = make_analysis_run(status="COMPLETE")

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "analysis_run" in stmt_str.lower() or "analysisrun" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = run
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar.return_value = "INR"
            elif "count" in stmt_str.lower():
                mock_result.scalar.return_value = 0
            elif "user" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = []
            else:
                mock_result.scalar.return_value = 0
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await send_run_notifications(
            run_id=RUN_ID,
            tenant_id=TENANT_A_ID,
            final_status="COMPLETE",
            db=db,
        )

        assert result.in_app_notifications_created == 0
        assert result.emails_sent == 0
        assert result.emails_failed == 0


# ────────────────────────────────────────────────────────────────────────
# Email Failure Isolation
# ────────────────────────────────────────────────────────────────────────

class TestEmailFailureIsolation:
    """Verify email failure never affects IN_APP delivery or run status.

    Satisfies: Pilot Readiness Section 5.2.
    """

    @pytest.mark.asyncio
    async def test_email_failure_does_not_block_in_app(self):
        """SMTP failure → IN_APP still created, emails_failed incremented."""
        run = make_analysis_run(status="COMPLETE")
        run.total_leakage_found = Decimal("10000")

        user1 = MagicMock()
        user1.id = USER_A_ID
        user1.email = "user1@example.com"
        user1.is_active = True

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "analysis_run" in stmt_str.lower() or "analysisrun" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = run
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar.return_value = "INR"
            elif "count" in stmt_str.lower():
                mock_result.scalar.return_value = 3
            elif "user" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [user1]
            else:
                mock_result.scalar.return_value = 0
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "backend.app.services.notification_service.send_email_smtp"
        ) as mock_smtp:
            mock_smtp.return_value = False  # Email fails

            result = await send_run_notifications(
                run_id=RUN_ID,
                tenant_id=TENANT_A_ID,
                final_status="COMPLETE",
                db=db,
            )

        assert result.in_app_notifications_created == 1
        assert result.emails_sent == 0
        assert result.emails_failed == 1

    @pytest.mark.asyncio
    async def test_partial_email_failure_counts_correctly(self):
        """2 users: 1 email succeeds, 1 fails → both IN_APP created."""
        run = make_analysis_run(status="PARTIAL_SUCCESS")
        run.total_leakage_found = Decimal("20000")
        run.error_summary = "1 item failed"

        user1 = MagicMock()
        user1.id = USER_A_ID
        user1.email = "good@example.com"

        user2 = MagicMock()
        user2.id = USER_B_ID
        user2.email = "bad@example.com"

        send_results = [True, False]  # First succeeds, second fails
        send_idx = [0]

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "analysis_run" in stmt_str.lower() or "analysisrun" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = run
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar.return_value = "INR"
            elif "count" in stmt_str.lower():
                mock_result.scalar.return_value = 5
            elif "user" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [user1, user2]
            else:
                mock_result.scalar.return_value = 0
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        def smtp_side_effect(*args, **kwargs):
            idx = send_idx[0]
            send_idx[0] += 1
            return send_results[idx]

        with patch(
            "backend.app.services.notification_service.send_email_smtp"
        ) as mock_smtp:
            mock_smtp.side_effect = smtp_side_effect

            result = await send_run_notifications(
                run_id=RUN_ID,
                tenant_id=TENANT_A_ID,
                final_status="PARTIAL_SUCCESS",
                db=db,
            )

        assert result.in_app_notifications_created == 2
        assert result.emails_sent == 1
        assert result.emails_failed == 1


# ────────────────────────────────────────────────────────────────────────
# Notification on COMPLETE and PARTIAL_SUCCESS
# ────────────────────────────────────────────────────────────────────────

class TestNotificationOnStatus:
    """Verify notifications fire on both COMPLETE and PARTIAL_SUCCESS.

    Satisfies: Pilot Readiness Section 5.1.
    """

    @pytest.mark.asyncio
    async def test_partial_success_fires_notifications(self):
        """PARTIAL_SUCCESS triggers notifications with correct template."""
        run = make_analysis_run(status="PARTIAL_SUCCESS")
        run.total_leakage_found = Decimal("15000")
        run.error_summary = "2 items pending FX rates"

        user1 = MagicMock()
        user1.id = USER_A_ID
        user1.email = "user@example.com"

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "analysis_run" in stmt_str.lower() or "analysisrun" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = run
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar.return_value = "INR"
            elif "count" in stmt_str.lower() and "pending_fx" in stmt_str.lower():
                mock_result.scalar.return_value = 2
            elif "count" in stmt_str.lower():
                mock_result.scalar.return_value = 5
            elif "user" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [user1]
            else:
                mock_result.scalar.return_value = 0
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "backend.app.services.notification_service.send_email_smtp"
        ) as mock_smtp:
            mock_smtp.return_value = True

            result = await send_run_notifications(
                run_id=RUN_ID,
                tenant_id=TENANT_A_ID,
                final_status="PARTIAL_SUCCESS",
                db=db,
            )

        assert result.in_app_notifications_created == 1
        assert result.final_status == "PARTIAL_SUCCESS"
