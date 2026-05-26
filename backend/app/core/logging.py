"""
LeakSight V1 — Structured Logging Configuration

Source: docs/CLAUDE.md (Logging Convention), docs/DECISIONS.md, pilot readiness checklist Section 6.8

Hard rules enforced structurally:
  - Never log raw document text
  - Never log line-level financial amounts
  - Never log PII (vendor names in raw form, invoice numbers, amounts)
  - Log only: event type, document_id, run_id, tenant_id, task name, status, duration, error codes
"""

import re
import logging
from typing import Any

import structlog


# Fields that are PERMITTED in log output
PERMITTED_FIELDS: frozenset[str] = frozenset({
    "event",
    "level",
    "timestamp",
    "logger",
    "document_id",
    "run_id",
    "tenant_id",
    "task_name",
    "status",
    "duration",
    "duration_ms",
    "error_code",
    "error_type",
    "method",
    "path",
    "status_code",
    "user_id",
    "action",
    "result",
    "doc_type",
    "parse_status",
    "service",
    "component",
    "phase",
    "count",
    "total",
    "progress",
})

# Regex patterns for detecting PII/financial data that must never appear in logs
_FINANCIAL_AMOUNT_PATTERN = re.compile(
    r"[₹$€£¥][\s]*[\d,]+\.?\d*"  # Currency symbols followed by amounts
    r"|[\d,]+\.\d{2,6}\b"         # Decimal amounts (2-6 decimal places)
    r"|\b\d{1,3}(,\d{2,3})*\.\d+"  # Indian/Western formatted numbers
)

_INVOICE_NUMBER_PATTERN = re.compile(
    r"\bINV[-/]?\d{3,}\b"           # INV-001, INV2024001
    r"|\bPO[-/]?\d{3,}\b"           # PO-001, PO2024001
    r"|\bGRN[-/]?\d{3,}\b"          # GRN-001
    r"|\b[A-Z]{2,5}[-/]\d{4,}\b"   # XX-0001 style (requires hyphen/slash + 4+ digits)
    r"|\bINV[OICE]*[-/\s]+\d+"
    r"|\binvoice\s*#\s*\d+",
    re.IGNORECASE,
)

_VENDOR_NAME_INDICATORS = re.compile(
    r"\b(pvt|ltd|llc|inc|corp|limited|private|industries|enterprises|steel|cement)\b",
    re.IGNORECASE,
)


def _contains_pii_or_financial_data(value: str) -> bool:
    """Check if a string value contains PII or financial data."""
    if not isinstance(value, str):
        return False
    if _FINANCIAL_AMOUNT_PATTERN.search(value):
        return True
    if _INVOICE_NUMBER_PATTERN.search(value):
        return True
    if _VENDOR_NAME_INDICATORS.search(value):
        return True
    return False


def sanitize_log_event(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that strips PII and financial data from log events.

    This processor enforces the logging prohibition rules at the structural level,
    making it impossible for downstream code to accidentally log sensitive data.
    """
    # Fields set by structlog processors — never contain user data, skip PII scan
    _STRUCTLOG_INTERNAL_FIELDS: frozenset[str] = frozenset({
        "timestamp", "level", "logger",
    })

    sanitized: dict[str, Any] = {}

    for key, value in event_dict.items():
        # Always keep permitted fields
        if key in PERMITTED_FIELDS:
            # Structlog-internal fields are safe — skip PII scanning
            if key in _STRUCTLOG_INTERNAL_FIELDS:
                sanitized[key] = value
            # User-supplied permitted fields get their VALUES checked for PII
            elif isinstance(value, str) and _contains_pii_or_financial_data(value):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value
        # Drop non-permitted fields entirely — they should not be logged
        # Exception: structlog internal fields
        elif key.startswith("_"):
            sanitized[key] = value

    # Ensure 'event' key always exists
    if "event" not in sanitized:
        sanitized["event"] = "[REDACTED]"

    return sanitized


def setup_logging() -> None:
    """Configure structured logging for the entire application.

    Must be called once at application startup, before any other logging occurs.
    The sanitize_log_event processor is inserted into the chain to enforce
    PII/financial data prohibition at the structural level.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_log_event,  # PII/financial data filter — must run before rendering
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to go through structlog
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler()],
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Optional logger name (typically __name__ of the calling module).

    Returns:
        A bound structlog logger configured with PII sanitization.
    """
    return structlog.get_logger(name)
