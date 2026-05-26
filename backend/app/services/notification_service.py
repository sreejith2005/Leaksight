"""
LeakSight V1 — Notification Service

Source: docs/ARCHITECTURE.md (Section 6.3 — notification_service)
       docs/DECISIONS.md (ADR-005 — no real-time push, ADR-006 — no outbound internet from workers)
       docs/DATABASE_SCHEMA.md (Section 4.4 — notifications)
       docs/API_CONTRACTS.md (Section 10 — notification endpoints)
       Build Order Checklist Phase 8.1

Two-channel notification system:
  1. IN_APP — write a notification row to the database
  2. EMAIL — send via SMTP (Brevo free tier, smtplib only)

Both channels fire on every COMPLETE or PARTIAL_SUCCESS run.

Standing rules:
  - Notification failure must NEVER affect run status
  - Email failure must not block in-app notification
  - Never log user email addresses
  - Never log financial amounts or vendor names
  - Use Python built-in smtplib only — no external email libraries
"""

import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.models.derived import AnalysisRun, LeakageRecord
from backend.app.models.notifications import Notification
from backend.app.models.tenant import TenantSettings, User

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""

    in_app_notifications_created: int
    emails_sent: int
    emails_failed: int
    run_id: UUID
    final_status: str


@dataclass
class RunNotificationData:
    """Aggregated data needed to format notification messages."""

    run_id: UUID
    run_status: str
    total_amount: Decimal
    currency: str
    record_count: int
    pending_review_count: int
    pending_fx_rate_count: int
    partial_success_notes: Optional[str]


# ═══════════════════════════════════════════════════════════════════════
# Message Templates
# ═══════════════════════════════════════════════════════════════════════

COMPLETE_MESSAGE_TEMPLATE = (
    "Analysis run {run_id} has completed successfully.\n"
    "\n"
    "Total leakage identified: {currency} {total_amount} across {record_count} findings.\n"
    "{pending_review_count} findings are awaiting your review.\n"
    "\n"
    "Log in to LeakSight to review findings and generate your report."
)

PARTIAL_SUCCESS_MESSAGE_TEMPLATE = (
    "Analysis run {run_id} has completed with partial results.\n"
    "\n"
    "Total leakage identified so far: {currency} {total_amount} across {record_count} findings.\n"
    "{pending_review_count} findings are awaiting your review.\n"
    "\n"
    "Note: {partial_success_notes}\n"
    "{fx_rate_section}"
    "\n"
    "Log in to LeakSight to review findings and upload any missing data."
)

FX_RATE_ACTION_TEMPLATE = (
    "{pending_fx_rate_count} findings cannot be calculated until FX rates are "
    "uploaded for the relevant dates. Please upload the missing rates in the Admin section.\n"
)

EMAIL_SUBJECT_COMPLETE = "LeakSight — Analysis Run Complete"
EMAIL_SUBJECT_PARTIAL = "LeakSight — Analysis Run Completed with Partial Results"


# ═══════════════════════════════════════════════════════════════════════
# Core Functions
# ═══════════════════════════════════════════════════════════════════════


def _format_amount(amount: Decimal) -> str:
    """Format a decimal amount for display. No currency symbol — currency code used."""
    if amount == 0:
        return "0.00"
    return f"{amount:,.2f}"


def _build_notification_type(final_status: str) -> str:
    """Map run status to notification_type enum value."""
    if final_status == "COMPLETE":
        return "RUN_COMPLETE"
    elif final_status == "PARTIAL_SUCCESS":
        return "RUN_PARTIAL_SUCCESS"
    else:
        return "RUN_FAILED"


def _format_message(data: RunNotificationData) -> str:
    """Format the notification message based on run status.

    COMPLETE: straightforward summary with call-to-action.
    PARTIAL_SUCCESS: includes why results are partial + FX rate action if needed.
    """
    if data.run_status == "COMPLETE":
        return COMPLETE_MESSAGE_TEMPLATE.format(
            run_id=str(data.run_id),
            currency=data.currency,
            total_amount=_format_amount(data.total_amount),
            record_count=data.record_count,
            pending_review_count=data.pending_review_count,
        )
    else:
        # PARTIAL_SUCCESS
        fx_section = ""
        if data.pending_fx_rate_count > 0:
            fx_section = FX_RATE_ACTION_TEMPLATE.format(
                pending_fx_rate_count=data.pending_fx_rate_count,
            )

        notes = data.partial_success_notes or "Some documents had processing issues."

        return PARTIAL_SUCCESS_MESSAGE_TEMPLATE.format(
            run_id=str(data.run_id),
            currency=data.currency,
            total_amount=_format_amount(data.total_amount),
            record_count=data.record_count,
            pending_review_count=data.pending_review_count,
            partial_success_notes=notes,
            fx_rate_section=fx_section,
        )


async def get_run_summary(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> RunNotificationData:
    """Get aggregate numbers for a run to populate notification messages.

    Queries analysis_runs and leakage_records to build the notification data.

    Args:
        run_id: Analysis run UUID.
        tenant_id: Tenant UUID.
        db: Async database session.

    Returns:
        RunNotificationData with all fields populated.

    Raises:
        ValueError: If run not found.
    """
    # Fetch the run
    run_stmt = select(AnalysisRun).where(
        AnalysisRun.id == run_id,
        AnalysisRun.tenant_id == tenant_id,
    )
    result = await db.execute(run_stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise ValueError(f"Analysis run {run_id} not found for tenant {tenant_id}")

    # Get tenant currency
    ts_stmt = select(TenantSettings.base_currency).where(
        TenantSettings.tenant_id == tenant_id,
    )
    ts_result = await db.execute(ts_stmt)
    currency = ts_result.scalar() or "INR"

    # Count pending review records
    pending_stmt = select(func.count()).where(
        LeakageRecord.run_id == run_id,
        LeakageRecord.tenant_id == tenant_id,
        LeakageRecord.status == "PENDING",
    )
    pending_result = await db.execute(pending_stmt)
    pending_review_count = pending_result.scalar() or 0

    # Count pending FX rate records
    fx_stmt = select(func.count()).where(
        LeakageRecord.run_id == run_id,
        LeakageRecord.tenant_id == tenant_id,
        LeakageRecord.status == "PENDING_FX_RATE",
    )
    fx_result = await db.execute(fx_stmt)
    pending_fx_rate_count = fx_result.scalar() or 0

    # Total record count
    total_stmt = select(func.count()).where(
        LeakageRecord.run_id == run_id,
        LeakageRecord.tenant_id == tenant_id,
    )
    total_result = await db.execute(total_stmt)
    record_count = total_result.scalar() or 0

    # Build partial success notes
    partial_success_notes = None
    run_status = run.status if isinstance(run.status, str) else str(run.status)
    if run_status == "PARTIAL_SUCCESS":
        notes_parts = []
        if pending_fx_rate_count > 0:
            notes_parts.append(
                f"{pending_fx_rate_count} record(s) are pending FX rate upload."
            )
        if run.error_summary:
            notes_parts.append(run.error_summary)
        if notes_parts:
            partial_success_notes = " ".join(notes_parts)
        else:
            partial_success_notes = (
                "Some documents had low parse confidence or processing issues."
            )

    return RunNotificationData(
        run_id=run_id,
        run_status=run_status,
        total_amount=run.total_leakage_found or Decimal("0"),
        currency=currency,
        record_count=record_count,
        pending_review_count=pending_review_count,
        pending_fx_rate_count=pending_fx_rate_count,
        partial_success_notes=partial_success_notes,
    )


def send_email_smtp(
    to_address: str,
    subject: str,
    body: str,
    notification_id: Optional[UUID] = None,
) -> bool:
    """Send an email via SMTP using Python built-in smtplib.

    Uses STARTTLS on port 587 (Brevo free tier configuration).

    Args:
        to_address: Recipient email address.
        subject: Email subject line.
        body: Email body text.
        notification_id: For logging context only (never log the to_address).

    Returns:
        True if sent successfully, False if failed.

    Note:
        Never logs the to_address — only boolean success/failure with
        notification_id. All SMTP exceptions are caught — never propagated.
    """
    settings = get_settings()

    # Skip email if SMTP is not properly configured (dev/test environments)
    if not settings.smtp_host or not settings.smtp_from:
        logger.info(
            "email_skipped_no_smtp_config",
            status="skipped",
            component="notification_service",
        )
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = settings.smtp_from
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        try:
            server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                server.close()

        logger.info(
            "email_sent_success",
            status="sent",
            component="notification_service",
        )
        return True

    except smtplib.SMTPException:
        logger.error(
            "email_send_failed",
            status="failed",
            error_type="SMTPException",
            component="notification_service",
        )
        return False
    except OSError:
        logger.error(
            "email_send_failed",
            status="failed",
            error_type="ConnectionError",
            component="notification_service",
        )
        return False
    except Exception:
        logger.error(
            "email_send_failed",
            status="failed",
            error_type="UnexpectedError",
            component="notification_service",
        )
        return False


async def send_run_notifications(
    run_id: UUID,
    tenant_id: UUID,
    final_status: str,
    db: AsyncSession,
) -> NotificationResult:
    """Send notifications (IN_APP + EMAIL) for a completed analysis run.

    Called from analysis_run_task after final_status is determined.
    Both channels fire for every COMPLETE or PARTIAL_SUCCESS run.

    Args:
        run_id: Analysis run UUID.
        tenant_id: Tenant UUID.
        final_status: "COMPLETE" or "PARTIAL_SUCCESS".
        db: Async database session.

    Returns:
        NotificationResult with counts of notifications created and emails sent/failed.
    """
    in_app_count = 0
    emails_sent = 0
    emails_failed = 0

    # Step 1: Get run summary data
    summary = await get_run_summary(run_id, tenant_id, db)

    # Step 2: Format message
    message = _format_message(summary)

    # Step 3: Determine notification type
    notification_type = _build_notification_type(final_status)

    # Step 4: Get email subject
    if final_status == "COMPLETE":
        email_subject = EMAIL_SUBJECT_COMPLETE
    else:
        email_subject = EMAIL_SUBJECT_PARTIAL

    # Step 5: Find all active users for this tenant
    users_stmt = select(User).where(
        User.tenant_id == tenant_id,
        User.is_active == True,  # noqa: E712
    )
    users_result = await db.execute(users_stmt)
    users = list(users_result.scalars().all())

    if not users:
        logger.info(
            "notification_no_users",
            run_id=str(run_id),
            tenant_id=str(tenant_id),
            component="notification_service",
        )
        return NotificationResult(
            in_app_notifications_created=0,
            emails_sent=0,
            emails_failed=0,
            run_id=run_id,
            final_status=final_status,
        )

    # Step 6: For each user, create IN_APP notification and send EMAIL
    for user in users:
        # 6a. Write IN_APP notification
        in_app_notification = Notification(
            tenant_id=tenant_id,
            user_id=user.id,
            run_id=run_id,
            notification_type=notification_type,
            message=message,
            channel="IN_APP",
        )
        db.add(in_app_notification)
        in_app_count += 1

        # 6b. Send EMAIL notification
        email_sent = send_email_smtp(
            to_address=user.email,
            subject=email_subject,
            body=message,
            notification_id=in_app_notification.id,
        )

        # 6c. Create EMAIL notification record
        email_notification = Notification(
            tenant_id=tenant_id,
            user_id=user.id,
            run_id=run_id,
            notification_type=notification_type,
            message=message,
            channel="EMAIL",
        )

        if email_sent:
            email_notification.email_sent_at = datetime.now(timezone.utc)
            emails_sent += 1
        else:
            email_notification.email_failed_reason = "SMTP send failed"
            emails_failed += 1

        db.add(email_notification)

    await db.flush()

    logger.info(
        "notifications_sent",
        run_id=str(run_id),
        tenant_id=str(tenant_id),
        status=final_status,
        count=in_app_count,
        component="notification_service",
    )

    return NotificationResult(
        in_app_notifications_created=in_app_count,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
        run_id=run_id,
        final_status=final_status,
    )


async def mark_notification_read(
    notification_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> Notification:
    """Mark a single IN_APP notification as read.

    Sets is_read = True and read_at = now().

    Args:
        notification_id: Notification UUID.
        user_id: User UUID (must own the notification).
        tenant_id: Tenant UUID (must match notification's tenant).
        db: Async database session.

    Returns:
        Updated Notification object.

    Raises:
        ValueError: If notification not found or doesn't belong to this user/tenant.
    """
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
        Notification.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()

    if notification is None:
        raise ValueError(
            f"Notification {notification_id} not found for user {user_id}"
        )

    notification.is_read = True
    notification.read_at = datetime.now(timezone.utc)

    return notification
