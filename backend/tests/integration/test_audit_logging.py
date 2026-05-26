"""
LeakSight V1 — Phase 10 Step 10.9
Test Suite: Audit Logging / PII Sanitisation

Pilot Readiness Checklist Section:
  - Section 6.8: Logs never contain raw financial amounts, vendor names, PII
  - Section 9.1: sanitize_log_event drops non-permitted fields
  - Section 9.2: PERMITTED_FIELDS is an explicit allowlist
  - Section 9.3: Financial amounts / invoice numbers / vendor names redacted

Tests are pure-function tests against sanitize_log_event and helpers —
no DB or network required.
"""

import pytest

from backend.app.core.logging import (
    PERMITTED_FIELDS,
    _contains_pii_or_financial_data,
    sanitize_log_event,
)


# ────────────────────────────────────────────────────────────────────────
# 10.9.1 — PERMITTED_FIELDS allowlist
# ────────────────────────────────────────────────────────────────────────

class TestPermittedFieldsAllowlist:
    """Verify the PERMITTED_FIELDS frozenset is a strict allowlist."""

    def test_is_frozenset(self):
        assert isinstance(PERMITTED_FIELDS, frozenset)

    def test_contains_expected_fields(self):
        expected = {
            "event", "level", "timestamp", "logger",
            "document_id", "run_id", "tenant_id",
            "task_name", "status", "duration", "duration_ms",
            "error_code", "error_type",
        }
        assert expected.issubset(PERMITTED_FIELDS)

    def test_does_not_contain_pii_fields(self):
        """No field named amount, price, vendor_name, email, invoice_number."""
        forbidden = {"amount", "price", "vendor_name", "email", "invoice_number",
                      "raw_text", "document_text", "password"}
        assert PERMITTED_FIELDS.isdisjoint(forbidden)


# ────────────────────────────────────────────────────────────────────────
# 10.9.2 — sanitize_log_event: field dropping
# ────────────────────────────────────────────────────────────────────────

class TestSanitizeFieldDropping:
    """Non-permitted fields must be silently dropped."""

    def test_permitted_field_passes(self):
        event = {"event": "analysis_started", "run_id": "abc-123"}
        result = sanitize_log_event(None, "info", event)
        assert result["event"] == "analysis_started"
        assert result["run_id"] == "abc-123"

    def test_non_permitted_field_dropped(self):
        event = {"event": "analysis_started", "secret_amount": "₹50000"}
        result = sanitize_log_event(None, "info", event)
        assert "secret_amount" not in result

    def test_internal_underscore_field_kept(self):
        """Structlog internal fields starting with _ are preserved."""
        event = {"event": "test", "_context": {"foo": "bar"}}
        result = sanitize_log_event(None, "info", event)
        assert "_context" in result

    def test_no_event_key_gets_redacted_default(self):
        """If 'event' is stripped, it's replaced with [REDACTED]."""
        event = {"vendor_name": "Tata Steel Pvt Ltd"}
        result = sanitize_log_event(None, "info", event)
        assert result["event"] == "[REDACTED]"

    def test_multiple_non_permitted_fields_all_dropped(self):
        event = {
            "event": "test",
            "raw_text": "full document content",
            "line_amount": "50000.00",
            "vendor_email": "finance@tata.com",
        }
        result = sanitize_log_event(None, "info", event)
        assert "raw_text" not in result
        assert "line_amount" not in result
        assert "vendor_email" not in result
        assert result["event"] == "test"


# ────────────────────────────────────────────────────────────────────────
# 10.9.3 — sanitize_log_event: PII value redaction
# ────────────────────────────────────────────────────────────────────────

class TestSanitizePIIRedaction:
    """Values of permitted fields containing PII/financial data are redacted."""

    def test_financial_amount_in_permitted_field_redacted(self):
        """e.g. status = '₹50,000.00 invoice' → [REDACTED]."""
        event = {"event": "check", "status": "₹50,000.00 pending"}
        result = sanitize_log_event(None, "info", event)
        assert result["status"] == "[REDACTED]"

    def test_dollar_amount_redacted(self):
        event = {"event": "check", "status": "$1,234.56 found"}
        result = sanitize_log_event(None, "info", event)
        assert result["status"] == "[REDACTED]"

    def test_invoice_number_redacted(self):
        event = {"event": "check", "status": "Processed INV-2024001"}
        result = sanitize_log_event(None, "info", event)
        assert result["status"] == "[REDACTED]"

    def test_po_number_redacted(self):
        event = {"event": "check", "status": "Linked to PO-0012345"}
        result = sanitize_log_event(None, "info", event)
        assert result["status"] == "[REDACTED]"

    def test_vendor_name_indicator_redacted(self):
        event = {"event": "check", "status": "Vendor Tata Steel Pvt Ltd matched"}
        result = sanitize_log_event(None, "info", event)
        assert result["status"] == "[REDACTED]"

    def test_safe_value_not_redacted(self):
        event = {"event": "run_complete", "status": "COMPLETE"}
        result = sanitize_log_event(None, "info", event)
        assert result["status"] == "COMPLETE"

    def test_structlog_internal_fields_skip_pii_scan(self):
        """timestamp, level, logger skip PII scanning even if value looks financial."""
        event = {
            "event": "test",
            "timestamp": "2024-01-15T10:30:00",
            "level": "info",
            "logger": "some.module",
        }
        result = sanitize_log_event(None, "info", event)
        assert result["timestamp"] == "2024-01-15T10:30:00"
        assert result["level"] == "info"


# ────────────────────────────────────────────────────────────────────────
# 10.9.4 — _contains_pii_or_financial_data helper
# ────────────────────────────────────────────────────────────────────────

class TestContainsPIIDetection:
    """Verify PII/financial pattern detection helper."""

    def test_rupee_amount(self):
        assert _contains_pii_or_financial_data("₹50,000.00") is True

    def test_dollar_amount(self):
        assert _contains_pii_or_financial_data("$1234.56") is True

    def test_euro_amount(self):
        assert _contains_pii_or_financial_data("€999.99") is True

    def test_pound_amount(self):
        assert _contains_pii_or_financial_data("£500.00") is True

    def test_invoice_number(self):
        assert _contains_pii_or_financial_data("INV-2024001") is True

    def test_po_number(self):
        assert _contains_pii_or_financial_data("PO-12345") is True

    def test_grn_number(self):
        assert _contains_pii_or_financial_data("GRN-001") is True

    def test_vendor_name_with_pvt_ltd(self):
        assert _contains_pii_or_financial_data("Tata Steel Pvt Ltd") is True

    def test_vendor_name_with_industries(self):
        assert _contains_pii_or_financial_data("Acme Industries") is True

    def test_plain_safe_text(self):
        assert _contains_pii_or_financial_data("analysis run started") is False

    def test_non_string_returns_false(self):
        assert _contains_pii_or_financial_data(12345) is False  # type: ignore

    def test_empty_string(self):
        assert _contains_pii_or_financial_data("") is False
