"""
Tests for LeakSight logging sanitization.

Source: docs/CLAUDE.md (Logging Convention), pilot readiness checklist Section 6.8.

These tests verify that the structural logging rules prevent PII and financial
data from appearing in log output.
"""

import json

import structlog

from backend.app.core.logging import sanitize_log_event, setup_logging, PERMITTED_FIELDS


class TestSanitizeLogEvent:
    """Test the sanitize_log_event processor directly."""

    def test_permitted_fields_pass_through(self) -> None:
        """Permitted fields like event, tenant_id, run_id should pass through."""
        event_dict = {
            "event": "document_parsed",
            "tenant_id": "abc-123",
            "run_id": "run-456",
            "status": "success",
            "duration_ms": 1234,
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert result["event"] == "document_parsed"
        assert result["tenant_id"] == "abc-123"
        assert result["run_id"] == "run-456"
        assert result["status"] == "success"
        assert result["duration_ms"] == 1234

    def test_financial_amount_in_event_is_redacted(self) -> None:
        """A financial amount like ₹1,50,000 in the event field must be redacted."""
        event_dict = {
            "event": "Leakage found: ₹1,50,000 from Tata Steel",
            "tenant_id": "abc-123",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "₹1,50,000" not in result.get("event", "")
        assert "1,50,000" not in result.get("event", "")
        assert result["event"] == "[REDACTED]"

    def test_vendor_name_in_event_is_redacted(self) -> None:
        """A vendor name like 'Tata Steel Pvt Ltd' in event must be redacted."""
        event_dict = {
            "event": "Processing invoice from Tata Steel Pvt Ltd",
            "tenant_id": "abc-123",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "Tata Steel" not in result.get("event", "")
        assert "Pvt Ltd" not in result.get("event", "")
        assert result["event"] == "[REDACTED]"

    def test_invoice_number_in_event_is_redacted(self) -> None:
        """An invoice number like INV-2024-001 in event must be redacted."""
        event_dict = {
            "event": "Parsed invoice INV-2024-001 successfully",
            "tenant_id": "abc-123",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "INV-2024-001" not in result.get("event", "")
        assert result["event"] == "[REDACTED]"

    def test_dollar_amounts_redacted(self) -> None:
        """Dollar amounts like $5,000.00 must be redacted."""
        event_dict = {
            "event": "Total overcharge detected: $5,000.00",
            "tenant_id": "abc-123",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "$5,000.00" not in result.get("event", "")
        assert result["event"] == "[REDACTED]"

    def test_non_permitted_fields_are_dropped(self) -> None:
        """Fields not in PERMITTED_FIELDS must be dropped entirely."""
        event_dict = {
            "event": "document_parsed",
            "tenant_id": "abc-123",
            "vendor_name": "Reliance Industries Pvt Ltd",
            "raw_text": "This is the full invoice text with amounts...",
            "invoice_amount": 50000.00,
            "line_items": [{"desc": "Cement", "amount": 1000}],
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "vendor_name" not in result
        assert "raw_text" not in result
        assert "invoice_amount" not in result
        assert "line_items" not in result
        assert result["event"] == "document_parsed"
        assert result["tenant_id"] == "abc-123"

    def test_financial_amount_in_status_field_is_redacted(self) -> None:
        """Even permitted fields have their VALUES checked for financial data."""
        event_dict = {
            "event": "run_complete",
            "status": "Found ₹3,000 leakage",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "₹3,000" not in result.get("status", "")
        assert result["status"] == "[REDACTED]"

    def test_clean_permitted_values_pass_through(self) -> None:
        """Clean values in permitted fields should not be redacted."""
        event_dict = {
            "event": "analysis_started",
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            "run_id": "660e8400-e29b-41d4-a716-446655440000",
            "document_id": "770e8400-e29b-41d4-a716-446655440000",
            "status": "PROCESSING",
            "method": "POST",
            "path": "/api/v1/ingest/upload",
            "status_code": 201,
            "duration_ms": 450,
            "error_code": "NONE",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert result["event"] == "analysis_started"
        assert result["status"] == "PROCESSING"
        assert result["method"] == "POST"
        assert result["path"] == "/api/v1/ingest/upload"
        assert result["status_code"] == 201

    def test_event_always_exists_in_output(self) -> None:
        """If event key is missing or dropped, a placeholder must exist."""
        event_dict = {
            "tenant_id": "abc-123",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert "event" in result

    def test_combined_pii_and_financial_data(self) -> None:
        """Combined vendor name + financial amount must both be blocked."""
        event_dict = {
            "event": "Tata Steel Pvt Ltd overcharged ₹50,000 on INV-2024-005",
            "tenant_id": "abc-123",
            "run_id": "run-789",
        }
        result = sanitize_log_event(None, "info", event_dict)
        output = json.dumps(result)
        assert "Tata Steel" not in output
        assert "50,000" not in output
        assert "INV-2024-005" not in output
        # Permitted fields should still be present
        assert result["tenant_id"] == "abc-123"
        assert result["run_id"] == "run-789"


class TestSetupLogging:
    """Test that logging setup configures structlog correctly."""

    def test_setup_does_not_raise(self) -> None:
        """setup_logging() must complete without errors."""
        setup_logging()

    def test_logger_can_be_obtained(self) -> None:
        """get_logger should return a usable logger after setup."""
        setup_logging()
        from backend.app.core.logging import get_logger
        logger = get_logger("test")
        assert logger is not None


class TestTimestampNotRedacted:
    """Ensure ISO 8601 timestamps are not redacted as financial data."""

    def test_iso_timestamp_passes_through(self) -> None:
        """ISO timestamps contain decimals but must not be redacted."""
        event_dict = {
            "event": "test_event",
            "timestamp": "2025-01-15T10:30:00.123456Z",
            "level": "info",
            "logger": "test.module",
        }
        result = sanitize_log_event(None, "info", event_dict)
        assert result["timestamp"] == "2025-01-15T10:30:00.123456Z"
        assert result["level"] == "info"
        assert result["logger"] == "test.module"
